import base64
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import prepare_non_custom_release as release
from tools import sign_android_apk as signing
from tools import sign_non_custom_ci as ci


class StockSigningBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = SimpleNamespace(private_directory=self.root / 'private', output=self.root / 'signed',
            apk=self.root / 'unsigned.apk', build_tools=self.root / 'tools', version_code=1, previous_apk=None)

    def test_absent_secrets_fail_before_creating_files(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, 'persistent-signing-secrets-not-configured'):
                ci.execute(self.args)
        self.assertFalse(self.args.private_directory.exists())
        self.assertFalse(self.args.output.exists())

    def test_private_inputs_are_external_exclusive_and_removed_on_sdk_failure(self):
        secrets = dict(ESTERIA_KEYSTORE_BASE64=' \n' + base64.b64encode(b'synthetic-key').decode() + '\r\n',
                       ESTERIA_KEYSTORE_PASSWORD='synthetic-store', ESTERIA_KEY_PASSWORD='synthetic-key-pass')
        def fail(args):
            self.assertEqual(args.keystore.read_bytes(), b'synthetic-key')
            self.assertEqual(args.keystore.stat().st_mode & 0o777, 0o600)
            self.assertEqual(args.keystore.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(args.lock, signing.ROOT / 'app/stock-signing.lock.json')
            self.assertFalse(args.qualification_only)
            raise ValueError('apk-signing-failed')
        with patch.dict(os.environ, secrets, clear=True), patch.object(signing, 'sign', side_effect=fail):
            with self.assertRaisesRegex(ValueError, '^apk-signing-failed$'):
                ci.execute(self.args)
        self.assertFalse(self.args.private_directory.exists())
        self.args.private_directory.mkdir(); marker = self.args.private_directory / 'keep'; marker.write_text('keep')
        with patch.dict(os.environ, secrets, clear=True):
            with self.assertRaisesRegex(ValueError, 'exclusive-private-directory-required'):
                ci.execute(self.args)
        self.assertEqual(marker.read_text(), 'keep')


class StockReleaseBoundary(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.signed = self.root / 'signed'; self.signed.mkdir()
        self.apk = self.signed / 'esteria-development.apk'; self.apk.write_bytes(b'synthetic signed bytes')
        self.receipt = dict(persistentSigningIdentityVerified=True, qualificationOnly=False, payloadPreserved=True,
            inputApkSha256='1' * 64, signedApk=dict(packageId=signing.STOCK_PACKAGE, debuggable=False,
            apkSha256=signing.digest(self.apk), apkBytes=self.apk.stat().st_size, versionName='0.1.0-non-custom.1',
            versionCode=1, certificateSha256='2' * 64))
        self.proof = dict(apk=dict(sha256='1' * 64), completeAssetInventoryVerified=True,
                          exactCurrentHelperClosureVerified=True)
        self.args = SimpleNamespace(signed=self.signed, cohort_proof=self.root / 'proof.json',
            output=self.root / 'release', app_revision='a' * 40, run_id='123')
        self.write()

    def write(self):
        (self.signed / 'signing-receipt.json').write_text(json.dumps(self.receipt))
        self.args.cohort_proof.write_text(json.dumps(self.proof))

    def test_changed_apk_or_unqualified_signing_cannot_be_published(self):
        self.apk.write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'signed-apk-identity-mismatch'):
            release.stage(self.args)
        self.assertFalse(self.args.output.exists())
        self.receipt['persistentSigningIdentityVerified'] = False; self.write()
        with self.assertRaisesRegex(ValueError, 'persistent-signing-and-preserved-payload-required'):
            release.stage(self.args)
        self.assertFalse(self.args.output.exists())

    def test_provider_proof_must_match_the_unsigned_apk_actually_signed(self):
        self.proof['apk']['sha256'] = '3' * 64; self.write()
        with self.assertRaisesRegex(ValueError, 'complete-provider-proof-required'):
            release.stage(self.args)
        self.assertFalse(self.args.output.exists())

    def test_existing_release_output_is_never_overwritten(self):
        self.args.output.mkdir(); marker = self.args.output / 'old-apk'; marker.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'release-output-already-exists'):
            release.stage(self.args)
        self.assertEqual(marker.read_text(), 'preserve')


if __name__ == '__main__':
    unittest.main()
