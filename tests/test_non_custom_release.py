import base64
import hashlib
import io
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
        with patch.dict(os.environ, secrets, clear=True), patch.object(signing, 'sign', side_effect=fail), \
                patch.object(ci, 'fetch_previous_apk', return_value=self.root / 'previous.apk') as previous:
            with self.assertRaisesRegex(ValueError, '^apk-signing-failed$'):
                ci.execute(self.args)
            previous.assert_called_once()
        self.assertFalse(self.args.private_directory.exists())
        self.args.private_directory.mkdir(); marker = self.args.private_directory / 'keep'; marker.write_text('keep')
        with patch.dict(os.environ, secrets, clear=True):
            with self.assertRaisesRegex(ValueError, 'exclusive-private-directory-required'):
                ci.execute(self.args)
        self.assertEqual(marker.read_text(), 'keep')

    def test_previous_official_apk_fetch_is_hash_and_length_bound_and_never_overwrites(self):
        data = b'synthetic previous APK, not installation evidence'
        lock = dict(packageId=signing.STOCK_PACKAGE,
            lastPublished=dict(versionCode=1, apkSha256=hashlib.sha256(data).hexdigest()))
        class Response(io.BytesIO):
            def __init__(self, value, length=None, code=200):
                super().__init__(value)
                self.headers = {'Content-Length': str(len(value)) if length is None else length}
                self.code = code
            def getcode(self):
                return self.code
        target = self.root / 'previous.apk'
        with patch.object(ci, 'urlopen', return_value=Response(data)) as opened:
            self.assertEqual(ci.fetch_previous_apk(lock, target), target)
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, 'https://github.com/Russianranger/esteria_android/releases/download/'
                'non-custom-v0.1.0-non-custom.1/Esteria-Stock-3.3.5a-arm64.apk')
            self.assertFalse(request.has_header('Authorization'))
            self.assertEqual(target.read_bytes(), data)
            with self.assertRaisesRegex(ValueError, 'previous-apk-output-exists'):
                ci.fetch_previous_apk(lock, target)
            self.assertEqual(opened.call_count, 1)
        target.unlink()
        for response in (Response(data + b'changed'), Response(data, str(len(data) + 1)),
                Response(data, str(len(data) - 1)), Response(data, ''),
                Response(data, str(ci.MAX_PREVIOUS_APK_BYTES + 1)), Response(data, code=206)):
            with patch.object(ci, 'urlopen', return_value=response), self.assertRaisesRegex(ValueError, 'previous-apk-download-'):
                ci.fetch_previous_apk(lock, target)
            self.assertFalse(target.exists())
        with patch.object(ci, 'urlopen') as opened:
            self.assertIsNone(ci.fetch_previous_apk(dict(lock, lastPublished=None), target))
            opened.assert_not_called()
        def raced(request, timeout):
            target.write_bytes(b'other writer owns this output')
            return Response(data)
        with patch.object(ci, 'urlopen', side_effect=raced), self.assertRaises(FileExistsError):
            ci.fetch_previous_apk(lock, target)
        self.assertEqual(target.read_bytes(), b'other writer owns this output')

    def test_downloaded_previous_apk_is_passed_to_sdk_and_removed_with_private_inputs(self):
        secrets = dict(ESTERIA_KEYSTORE_BASE64=base64.b64encode(b'synthetic-key').decode(),
                       ESTERIA_KEYSTORE_PASSWORD='synthetic-store', ESTERIA_KEY_PASSWORD='synthetic-key-pass')
        previous = self.args.private_directory / 'previous-stock.apk'
        def fetch(lock, path):
            self.assertEqual(path, previous)
            self.assertFalse((path.parent / 'key.jks').exists())
            path.write_bytes(b'synthetic previous APK')
            return path
        def verify(args):
            self.assertEqual(args.previous_apk, previous)
            self.assertEqual(args.previous_apk.read_bytes(), b'synthetic previous APK')
            self.assertFalse(args.initial_baseline)
            return dict(synthetic=True)
        with patch.dict(os.environ, secrets, clear=True), patch.object(ci, 'fetch_previous_apk', side_effect=fetch), \
                patch.object(signing, 'sign', side_effect=verify):
            self.assertEqual(ci.execute(self.args), dict(synthetic=True))
        self.assertFalse(self.args.private_directory.exists())
        self.args.previous_apk = self.root / 'explicit-previous.apk'
        with patch.dict(os.environ, secrets, clear=True), patch.object(ci, 'fetch_previous_apk') as fetched, \
                patch.object(signing, 'sign', return_value=dict(synthetic=True)) as signed:
            ci.execute(self.args)
            fetched.assert_not_called()
            self.assertEqual(signed.call_args.args[0].previous_apk, self.args.previous_apk)


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
