import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools import release_client_inputs as client


class ClientReleaseGuards(unittest.TestCase):
    def test_current_release_retains_proven_client_and_complete_measured_source(self):
        lock, pin = client.load_lock()
        self.assertEqual(lock['sourceRevision'], '471ee42faadf4a97a1d0a86989cf1452621f2dc5')
        self.assertEqual(lock['artifact']['sha256'], pin['artifact']['sha256'])
        self.assertEqual(lock['sourceArchive']['bytes'], 23449963)
        self.assertIn('tools/package_client_sources.py', lock['generationInputs'])
        self.assertEqual(set(lock['selectedInputs']), client.SELECTED_INPUT_PATHS)
        self.assertEqual(lock['targetCommit'], '33cf433a907a9181d27a6962b1f07516afc0773d')

    def test_existing_output_is_preserved_before_reading_any_inputs(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name); saved = path / 'saved'; saved.write_bytes(b'preserve')
            with patch.object(client, 'receipt_check') as source:
                with self.assertRaisesRegex(ValueError, 'output-exists'):
                    client.stage(None, None, path, {}, {}, None)
            source.assert_not_called(); self.assertEqual(saved.read_bytes(), b'preserve')

    def test_changed_source_receipt_fails_before_archive_use(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name); (path / client.SOURCE_RECEIPT).write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'receipt-identity'):
                client.receipt_check(path, {'sourceReceipt': {'bytes': 1, 'sha256': '0' * 64}}, {})

    def test_original_failed_run_prevents_binary_download(self):
        lock, _ = client.load_lock(); api = Mock()
        api.json.return_value = dict(head_sha=lock['sourceRevision'], conclusion='failure', head_branch='android/arm64-port')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            client.download_original(api, Path('/unused'), lock)
        api.download.assert_not_called()

    def test_unpublished_receipt_never_starts_durable_download(self):
        lock, pin = client.load_lock(); lock['published'] = None; api = Mock()
        with self.assertRaisesRegex(ValueError, 'not-yet-recorded'):
            client.fetch(api, Path('/unused'), lock, pin, Path('/source'))
        api.download.assert_not_called()

    def test_client_reader_rejects_arbitrary_repository_and_mutation_routes(self):
        api = client.ClientArtifacts('synthetic-token'); api.opener = Mock()
        for route in ('https://example.com/', '/git/refs', '/actions/artifacts/1/zip?token=x', '/actions/runs/../1', '/releases'):
            with self.subTest(route=route), self.assertRaisesRegex(ValueError, 'route-rejected'):
                api.open(route)
        api.opener.open.assert_not_called()

    def test_client_download_strips_authorization_on_signed_redirect(self):
        api = client.ClientArtifacts('synthetic-token'); api.opener = Mock()
        response = io.BytesIO(b'archive')
        api.opener.open.side_effect = [HTTPError('fixed', 302, 'redirect',
            {'Location': 'https://example.blob.core.windows.net/artifact?signature=private'}, None), response]
        self.assertIs(api.open('/actions/artifacts/1/zip'), response)
        first, second = (call.args[0] for call in api.opener.open.call_args_list)
        self.assertEqual(first.get_header('Authorization'), 'Bearer synthetic-token')
        self.assertIsNone(second.get_header('Authorization'))
        self.assertEqual(first.get_method(), 'GET'); self.assertEqual(second.get_method(), 'GET')

    def test_foreign_redirect_is_rejected_and_signed_error_url_is_not_reported(self):
        api = client.ClientArtifacts('synthetic-token'); api.opener = Mock()
        api.opener.open.side_effect = HTTPError('fixed', 302, 'redirect', {'Location': 'https://example.com/leak'}, None)
        with self.assertRaisesRegex(ValueError, 'unexpected-client-artifact-redirect'):
            api.open('/actions/artifacts/1/zip')
        api.opener.open.side_effect = [HTTPError('fixed', 302, 'redirect',
            {'Location': 'https://example.blob.core.windows.net/x?private-signature'}, None),
            HTTPError('https://example.blob.core.windows.net/x?private-signature', 403, 'private failure', {}, None)]
        with tempfile.TemporaryDirectory() as name, self.assertRaises(ValueError) as failure:
            api.download(1, Path(name) / 'archive.zip', {'bytes': 1, 'sha256': '0' * 64})
        self.assertNotIn('private-signature', str(failure.exception))
        self.assertIn('HTTP 403', str(failure.exception))


if __name__ == '__main__': unittest.main()
