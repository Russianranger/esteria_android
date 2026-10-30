"""Bounded transfer fixtures only; no measured source or runtime claim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import prepare_playerbots_source_companion as inputs


class SourceInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='helper-source-transfer-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def fixture(self, *, extra=False, program=False):
        empty = dict(bytes=0, sha256=inputs.hashlib.sha256(b'').hexdigest())
        rows = {'source/README.md': empty}; body = b'TEST_ONLY_MODE_FIXTURE_NEVER_EXECUTED'
        if program: rows['bin/playerbots-schema'] = dict(bytes=len(body), sha256=inputs.hashlib.sha256(body).hexdigest())
        raw = (json.dumps(dict(scope='TEST_ONLY_NO_NATIVE_CLAIM', payloadFiles=rows)) + '\n').encode()
        qid = dict(bytes=len(raw), sha256=inputs.hashlib.sha256(raw).hexdigest())
        archive = self.root / ('extra.zip' if extra else 'native.zip')
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('source-build.json', raw); z.writestr('source/README.md', b'')
            if program: z.writestr('bin/playerbots-schema', body)
            if extra: z.writestr('unrecorded', b'unrecorded')
        pin = dict(nativeCapture=dict(workflowRun=1, job=2, integrationRevision='a' * 40,
                   receipt=qid, artifact=dict(id=3, **inputs.files.identity(archive))))
        return archive, pin

    def test_pending_pin_refuses_before_creating_parent_or_downloading(self):
        with patch.object(inputs.source, 'load_pin', side_effect=ValueError('pending measurement')), \
                patch.object(inputs, 'Github') as github:
            with self.assertRaisesRegex(ValueError, 'pending measurement'): inputs.prepare(self.root / 'new/output')
        self.assertFalse((self.root / 'new').exists()); github.assert_not_called()

    def test_exact_member_transfer_preserves_real_empty_source_bytes(self):
        archive, pin = self.fixture()
        with patch.object(inputs.source, 'verify_native') as verify:
            inputs.extract_native(archive, self.root / 'extracted', pin)
        self.assertEqual((self.root / 'extracted/source/README.md').read_bytes(), b'')
        verify.assert_called_once_with(self.root / 'extracted', pin)
        with self.assertRaisesRegex(ValueError, 'existing-helper-source-native-inputs-preserved'):
            inputs.extract_native(archive, self.root / 'extracted', pin)

    def test_outer_digest_extra_member_and_receipt_pin_are_not_optional(self):
        archive, pin = self.fixture(); changed = copy.deepcopy(pin)
        changed['nativeCapture']['artifact']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'downloaded-artifact-differs'):
            inputs.extract_native(archive, self.root / 'wrong', changed)
        changed = copy.deepcopy(pin); changed['nativeCapture']['receipt']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'receipt-artifact-pin-differs'):
            inputs.extract_native(archive, self.root / 'wrong-receipt', changed)
        archive, pin = self.fixture(extra=True)
        with self.assertRaisesRegex(ValueError, 'exact-members-required'):
            inputs.extract_native(archive, self.root / 'extra', pin)
        self.assertFalse((self.root / 'wrong').exists()); self.assertFalse((self.root / 'extra').exists())

    def test_fixed_helper_role_keeps_executable_mode_for_strict_elf_readback(self):
        archive, pin = self.fixture(program=True)
        def verify(root, actual):
            self.assertEqual((root / 'bin/playerbots-schema').stat().st_mode & 0o777, 0o555)
            self.assertEqual((root / 'source/README.md').stat().st_mode & 0o777, 0o444)
            self.assertEqual(actual, pin)
        with patch.object(inputs.source, 'verify_native', side_effect=verify) as called:
            inputs.extract_native(archive, self.root / 'roles', pin)
        called.assert_called_once()

    def test_exact_successful_native_run_and_job_are_required(self):
        _, pin = self.fixture()
        class Api:
            def json(self, path):
                if path == '/actions/runs/1':
                    return dict(id=1, head_sha='a' * 40, status='completed', conclusion='failure')
                return dict(id=2, run_id=1, status='completed', conclusion='success')
        with patch.object(inputs.stock, 'verify_remote') as artifact:
            with self.assertRaisesRegex(ValueError, 'producer-not-successful-exact-run'):
                inputs.verify_native_remote(Api(), pin)
        artifact.assert_called_once()


if __name__ == '__main__': unittest.main()
