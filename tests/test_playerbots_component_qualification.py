"""Host guard fixtures; native SQL success can only come from the ARM64 job."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_playerbots_runtime as acquire, qualify_playerbots_component as qualify


class RuntimeTransfer(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_remote_run_and_artifact_pins_are_checked_before_download(self):
        disk = patch.object(acquire.shutil, 'disk_usage', return_value=acquire.shutil._ntuple_diskusage(8 << 30, 0, 8 << 30))
        disk.start(); self.addCleanup(disk.stop)
        api = Mock(); api.json.return_value = dict(id=acquire.RUN, head_sha='0' * 40,
                                                  status='completed', conclusion='success')
        with self.assertRaisesRegex(ValueError, 'producer-identity'):
            acquire.prepare(self.root / 'new', api)
        api.download.assert_not_called(); self.assertFalse((self.root / 'new').exists())
        api.json.side_effect = [dict(id=acquire.RUN, head_sha=acquire.REVISION, status='completed', conclusion='success'),
            dict(id=acquire.ARTIFACT['id'], expired=False, size_in_bytes=acquire.ARTIFACT['bytes'],
                 digest='sha256:' + '0' * 64, workflow_run=dict(id=acquire.RUN, head_sha=acquire.REVISION))]
        with self.assertRaisesRegex(ValueError, 'artifact-identity'):
            acquire.prepare(self.root / 'new', api)
        api.download.assert_not_called()

    def test_outer_hash_mismatch_preserves_output_and_does_not_open_zip(self):
        path = self.root / 'fixture.zip'; path.write_bytes(b'not original runtime ZIP')
        with patch.object(acquire.transfer, 'bounded_zip') as opened, \
                self.assertRaisesRegex(ValueError, 'transfer-changed'):
            acquire.extract_selected(path, self.root / 'out')
        opened.assert_not_called(); self.assertFalse((self.root / 'out').exists())

    def test_only_selected_plain_members_extract_and_original_receipts_bind(self):
        path = self.root / 'fixture.zip'
        engine, content = b'{"fixture":"engine"}\n', b'{"fixture":"content"}\n'
        expected = lambda raw: dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('server-engine-package/package-receipt.json', engine)
            archive.writestr('engine-inputs/content/package-receipt.json', content)
            archive.writestr('engine-inputs/locked/sources.lock.json', b'fixture archived lock')
            archive.writestr('server-extractors-package/ignored-runtime.tar.gz', b'excluded component')
        with patch.object(acquire, 'ARTIFACT', dict(acquire.ARTIFACT, **acquire.files.identity(path))), \
                patch.object(acquire, 'ENGINE_RECEIPT', expected(engine)), \
                patch.object(acquire, 'CONTENT_RECEIPT', expected(content)), \
                patch.object(acquire.inputs, 'load_pin') as verify:
            self.assertEqual(acquire.extract_selected(path, self.root / 'out'), 3)
        verify.assert_called_once_with(self.root / 'out/engine-inputs/locked/sources.lock.json')
        self.assertFalse((self.root / 'out/server-extractors-package').exists())
        self.assertEqual((self.root / 'out/server-engine-package/package-receipt.json').read_bytes(), engine)
        with self.assertRaisesRegex(ValueError, 'transfer-changed'):
            acquire.extract_selected(path, self.root / 'other')

    def test_archive_path_traversal_cannot_create_output(self):
        path = self.root / 'fixture.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('server-engine-package/../../outside', b'unsafe')
        with patch.object(acquire, 'ARTIFACT', dict(acquire.ARTIFACT, **acquire.files.identity(path))), \
                self.assertRaises(ValueError):
            acquire.extract_selected(path, self.root / 'out')
        self.assertFalse((self.root / 'outside').exists())


class NativeGateGuards(unittest.TestCase):
    def test_public_nested_records_exclude_configuration_digest_and_keep_false_scope(self):
        value = dict(product=dict(configGeneration='credential-derived', playerbotsAiQualified=False),
                     list=[dict(configGeneration='another', androidRuntimeQualified=False)])
        self.assertEqual(qualify.public_record(value),
                         dict(product=dict(playerbotsAiQualified=False), list=[dict(androidRuntimeQualified=False)]))
        self.assertIn('configGeneration', value['product'])

    def test_probe_requires_hex_and_reads_exact_binary_value(self):
        connection = Mock(); token = '00ff' * 16
        connection.query.return_value = [token.upper()]
        qualify.probe(connection, token, create=True)
        sql = [call.args[0] for call in connection.query.call_args_list]
        self.assertIn('BINARY(32)', sql[0]); self.assertIn("UNHEX('" + token + "')", sql[1])
        connection.reset_mock()
        with self.assertRaisesRegex(ValueError, 'marker'): qualify.probe(connection, "' unsafe SQL")
        connection.query.assert_not_called()
        connection.query.return_value = ['00' * 32]
        with self.assertRaisesRegex(ValueError, 'marker changed'): qualify.probe(connection, token)

    def test_wrong_architecture_and_existing_output_refuse_before_artifact_or_sql_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'new'
            arguments = (root, root, '0' * 64, root, root, root, '8.0.46', output,
                         root, root, '0' * 64)
            with patch.object(qualify.platform, 'machine', return_value='x86_64'), \
                    patch.object(qualify.importer, 'unpack_content') as unpack, \
                    patch.object(qualify.db, 'initialize') as initialize, \
                    self.assertRaisesRegex(ValueError, 'native Linux ARM64'):
                qualify.run(*arguments, engine_derivative_receipt=root)
            unpack.assert_not_called(); initialize.assert_not_called(); self.assertFalse(output.exists())
            output.mkdir(); (output / 'owned-marker').write_bytes(b'preserved')
            with patch.object(qualify.platform, 'machine', return_value='aarch64'), \
                    patch.object(qualify.importer, 'unpack_content') as unpack, \
                    self.assertRaisesRegex(ValueError, 'fixture preserved'):
                qualify.run(*arguments, engine_derivative_receipt=root)
            unpack.assert_not_called(); self.assertEqual((output / 'owned-marker').read_bytes(), b'preserved')

    def test_input_failure_exports_only_fixed_phase_and_class_and_never_initializes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); output = root / 'new'
            with patch.object(qualify.platform, 'machine', return_value='aarch64'), \
                    patch.object(qualify.importer, 'unpack_content', side_effect=ValueError('private SQL/path/password')), \
                    patch.object(qualify.db, 'initialize') as initialize, self.assertRaises(ValueError):
                qualify.run(root, root, '0' * 64, root, root, root, '8.0.46', output,
                            root, root, '0' * 64, engine_derivative_receipt=root)
            initialize.assert_not_called()
            raw = (output / 'qualification.json').read_text(); receipt = json.loads(raw)
            self.assertNotIn('private SQL', raw); self.assertEqual(receipt['failurePhase'], 'verify-inputs')
            self.assertEqual(receipt['failureClass'], 'ValueError'); self.assertFalse(receipt['qualificationSucceeded'])
            self.assertFalse(receipt['androidRuntimeQualified']); self.assertFalse(receipt['playerbotsAiQualified'])


if __name__ == '__main__': unittest.main()
