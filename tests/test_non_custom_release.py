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

    def test_v12_staging_preserves_existing_preparation_and_reports_unqualified_gameplay(self):
        self.receipt['signedApk'].update(versionCode=12, versionName='0.1.0-non-custom.12')
        self.write()
        result = release.stage(self.args)
        notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
        self.assertIn('choose Start local game if preparation already completed', notes)
        self.assertIn('If stock shaders or\ndatabase preparation are still missing', notes)
        self.assertIn('Do not uninstall, clear storage,\nreimport or delete completed navigation output', notes)
        self.assertNotIn('Import your complete ChromieCraft client', notes)
        self.assertIn('Full payload verification remains required', notes)
        self.assertIn('still disabled', notes)
        self.assertIn('This candidate is not Thor gameplay-qualified', notes)
        self.assertEqual(result['tag'], 'non-custom-v0.1.0-non-custom.12')
        for key in ('actualUserClientValidated', 'graphicalClientStartupQualified',
                    'characterCreationQualified', 'worldEntryQualified', 'thorQualified'):
            self.assertIs(result[key], False)
        self.assertEqual((self.args.output / 'Esteria-Stock-3.3.5a-arm64.apk').read_bytes(), self.apk.read_bytes())

    def test_recent_shader_updates_preserve_imports_and_direct_named_repair(self):
        for code, failure in [(13, 'MPQ delete markers are unsupported'), (14, 'Terrain1w:0')]:
            with self.subTest(version_code=code):
                version = '0.1.0-non-custom.' + str(code)
                self.receipt['signedApk'].update(versionCode=code, versionName=version)
                self.write()
                self.args.output = self.root / ('out-' + str(code))
                result = release.stage(self.args)
                notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
                self.assertEqual(result['tag'], 'non-custom-v' + version)
                self.assertIn('After the v' + str(code - 1) + ' shader failure', notes)
                self.assertIn('Repair local component → Shaders', notes)
                self.assertIn('Repair local component → Database setup', notes)
                self.assertIn(failure, notes)
                self.assertIn('Export support bundle', notes)
                self.assertNotIn('Import your complete ChromieCraft client', notes)
                self.assertFalse(result['thorQualified'])

    def test_existing_release_output_is_never_overwritten(self):
        self.args.output.mkdir(); marker = self.args.output / 'old-apk'; marker.write_text('preserve')
        with self.assertRaisesRegex(ValueError, 'release-output-already-exists'):
            release.stage(self.args)
        self.assertEqual(marker.read_text(), 'preserve')

    def test_renderer_release_records_executable_and_preparation_revisions(self):
        tree = self.root / 'integration'
        assets = tree / 'runtime/client'
        assets.mkdir(parents=True)
        for name in ('sources.lock.json', 'NON-CUSTOM-TESTING.md'):
            (tree / name).write_bytes((signing.ROOT / name).read_bytes())
        base = json.loads((tree / 'sources.lock.json').read_bytes())['sources']['client']['commit']
        renderer = dict(preparedClientRevision=base, executableRevision='b'*40,
                        preparedSourceLockSha256=signing.digest(tree/'sources.lock.json'),
                        executableSha256='3'*64, clientArchiveSha256='4'*64)
        contract = assets / 'renderer-compatibility.json'
        contract.write_text(json.dumps(renderer))
        pin = dict(bytes=contract.stat().st_size, sha256=signing.digest(contract))
        self.proof.update(rendererSelection=renderer, rendererContract=pin)
        self.receipt['signedApk'].update(versionCode=15, versionName='0.1.0-non-custom.15')
        self.write()
        with patch.object(signing, 'ROOT', tree):
            result = release.stage(self.args)
            self.assertEqual(result['clientRevision'], renderer['executableRevision'])
            self.assertEqual(result['preparedClientRevision'], base)
            self.assertEqual(result['rendererCompatibilitySha256'], pin['sha256'])
            self.assertIn('Repair local component → Client runtime', (self.args.output/'RELEASE-NOTES.md').read_text())
            self.receipt['signedApk'].update(versionCode=17, versionName='0.1.0-non-custom.17')
            self.write()
            self.args.output = self.root / 'v17'
            current = release.stage(self.args)
            notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
            self.assertEqual(current['clientRevision'], result['clientRevision'])
            self.assertEqual(current['tag'], 'non-custom-v0.1.0-non-custom.17')
            self.assertIn('From v16 with the client and shaders prepared, tap **Start local game**', notes)
            self.assertIn('For a previous shader failure, choose **Repair local component → Shaders** once', notes)
            self.assertIn('If upgrading from before v16 and you still need the corrected client', notes)
            self.receipt['signedApk'].update(versionCode=18, versionName='0.1.0-non-custom.18')
            self.write()
            self.args.output = self.root / 'v18'
            staged = release.stage(self.args)
            notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
            self.assertEqual(staged['tag'], 'non-custom-v0.1.0-non-custom.18')
            self.assertIn('With the client and shaders prepared, tap **Start local game**', notes)
            self.assertIn('If the previous failure was at shaders', notes)
            self.assertNotIn('Select **Repair local component → Client runtime**', notes)
            self.assertNotIn('Import your complete ChromieCraft client', notes)
            self.assertIn('Export support bundle', notes)
            self.receipt['signedApk'].update(versionCode=19, versionName='0.1.0-non-custom.19')
            self.write()
            self.args.output = self.root / 'v19'
            staged = release.stage(self.args)
            notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
            self.assertEqual(staged['clientRevision'], renderer['executableRevision'])
            self.assertEqual(staged['preparedClientRevision'], base)
            self.assertIn('Tap **Repair local component → Client runtime** once', notes)
            self.assertNotIn('Import your complete ChromieCraft client', notes)
            self.receipt['signedApk'].update(versionCode=20, versionName='0.1.0-non-custom.20')
            self.write()
            self.args.output = self.root / 'v20'
            staged = release.stage(self.args)
            notes = (self.args.output / 'RELEASE-NOTES.md').read_text()
            self.assertEqual(staged['tag'], 'non-custom-v0.1.0-non-custom.20')
            self.assertEqual(staged['clientRevision'], renderer['executableRevision'])
            self.assertEqual(staged['preparedClientRevision'], base)
            self.assertIn('From a prepared v19 installation, tap **Start local game**', notes)
            self.assertIn('restores its offline status', notes)
            contract.write_text(json.dumps(dict(renderer, executableSha256='9'*64)))
            self.args.output = self.root / 'rejected'
            with self.assertRaisesRegex(ValueError, 'release-renderer-recipe-selection-differs'):
                release.stage(self.args)


if __name__ == '__main__':
    unittest.main()
