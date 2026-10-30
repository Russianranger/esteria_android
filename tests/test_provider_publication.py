import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_dependency_release import FakeGithub, pin
from tools import dependency_publication as policy
from tools import release_guest_bridges as guest


class DraftGuards(unittest.TestCase):
    def setUp(self):
        self.lock = dict(tag='deps-test-inputs', targetCommit='a' * 40, workflowRun=10)
        self.identities = {name: pin(name.encode()) for name in ('NOTICE.txt', 'source.tar.gz', 'runtime.tar.gz')}
        self.body = 'Exact component scope and original source.\n'
        self.policy = policy.DraftPublication(self.lock, self.body, lambda path: self.identities)

    def api(self, draft=True):
        api = FakeGithub(self.lock, self.identities, draft=draft)
        api.release['body'] = self.body
        return api

    def test_partial_owned_ui_draft_uploads_only_missing_then_downloads_all(self):
        api = self.api(); api.ref = None; del api.assets['source.tar.gz']
        result = self.policy.upload_draft(api, Path('/fixture'))
        self.assertEqual(api.mutations, [('UPLOAD', 'source.tar.gz')])
        self.assertEqual(len(api.downloads), 3)
        self.assertTrue(result['draft'] and result['completeAssetSetVerified'])
        self.assertFalse(result['publicationQualified'])

    def test_published_release_has_readonly_complete_byte_verification(self):
        api = self.api(draft=False)
        result = self.policy.verify_published(api, Path('/fixture'))
        self.assertEqual(api.mutations, [])
        self.assertEqual(len(api.downloads), 3)
        self.assertFalse(result['githubImmutable'])

    def test_changed_identity_tag_asset_or_extra_name_is_never_mutated(self):
        for change in ('body', 'target', 'tag', 'asset', 'extra', 'duplicate'):
            api = self.api(); del api.assets['source.tar.gz']
            if change == 'body': api.release['body'] += ' '
            elif change == 'target': api.release['target_commitish'] = 'b' * 40
            elif change == 'tag': api.ref['object']['sha'] = 'b' * 40
            elif change == 'asset': api.assets['NOTICE.txt']['digest'] = 'sha256:' + '0' * 64
            elif change == 'extra': api.assets['saves.sql'] = api.asset('saves.sql', pin(b'private'), 99)
            else: api.assets['duplicate'] = copy.deepcopy(api.assets['NOTICE.txt'])
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.policy.upload_draft(api, Path('/fixture'))
            self.assertEqual(api.mutations, [])

    def test_published_missing_asset_is_never_repaired(self):
        api = self.api(draft=False); del api.assets['source.tar.gz']
        with self.assertRaisesRegex(ValueError, 'missing-assets'):
            self.policy.upload_draft(api, Path('/fixture'))
        self.assertEqual(api.mutations, [])

    def test_ui_crlf_is_only_normalization(self):
        for body, permitted in ((self.body.replace('\n', '\r\n'), True), (self.body.rstrip(), False),
                                (self.body.replace('\n', '\r'), False)):
            api = self.api(); api.release['body'] = body
            if permitted: self.policy.upload_draft(api, Path('/fixture'))
            else:
                with self.assertRaises(ValueError): self.policy.upload_draft(api, Path('/fixture'))
            self.assertEqual(api.mutations, [])

    def test_missing_draft_and_timeout_never_create_or_finalize_anything(self):
        api = self.api(); api.release = None; api.ref = None
        with self.assertRaisesRegex(ValueError, 'UI-draft-required'): self.policy.upload_draft(api, Path('/fixture'))
        with self.assertRaisesRegex(ValueError, 'not-yet-available'): self.policy.verify_published(api, Path('/fixture'))
        self.assertEqual(api.mutations, [])

    def test_finalized_during_upload_stops_before_next_write(self):
        api = self.api(); api.assets = {}; original = api.upload
        def finalize(*args):
            result = original(*args); api.release['draft'] = False; return result
        api.upload = finalize
        with self.assertRaisesRegex(ValueError, 'changed-before-upload'):
            self.policy.upload_draft(api, Path('/fixture'))
        self.assertEqual(len(api.mutations), 1)


class GuestReleaseGuards(unittest.TestCase):
    def test_current_pin_preserves_exact_measured_archive_and_original_lock(self):
        lock, measured = guest.load_lock()
        self.assertEqual(lock['archive']['bytes'], 469031)
        self.assertEqual(lock['originalIntegrationRevision'], measured['integrationRevision'])
        self.assertNotEqual(lock['targetCommit'], lock['originalIntegrationRevision'])

    def test_existing_candidate_and_payload_destinations_are_preserved(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name); marker = path / 'save'; marker.write_bytes(b'preserve')
            with self.assertRaisesRegex(ValueError, 'output-exists'):
                guest.stage(path / 'absent.zip', path, {}, {})
            with patch.object(guest, 'verify_candidate'):
                with self.assertRaisesRegex(ValueError, 'output-exists'):
                    guest.export_payload(path, path, {}, {})
            self.assertEqual(marker.read_bytes(), b'preserve')

    def test_original_artifact_must_match_successful_original_run(self):
        lock, measured = guest.load_lock()
        class API:
            def json(self, path):
                return dict(head_sha=lock['originalIntegrationRevision'], conclusion='failure', head_branch='android/client-server')
            def download(self, *args): raise AssertionError('unqualified artifact was downloaded')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            guest.download_original(API(), Path('/unused'), lock)

    def test_unpublished_or_foreign_durable_receipt_cannot_fetch(self):
        lock, measured = guest.load_lock()
        with tempfile.TemporaryDirectory() as name:
            for receipt in (None, dict(repository='other/repo', tag=lock['tag'], targetCommit=lock['targetCommit'], assets={})):
                lock['published'] = receipt
                with self.assertRaisesRegex(ValueError, 'not-yet-recorded'):
                    guest.fetch(None, Path(name) / 'fresh', lock, measured)
                self.assertFalse((Path(name) / 'fresh').exists())


if __name__ == '__main__': unittest.main()
