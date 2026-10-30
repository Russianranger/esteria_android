import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import sign_android_apk as signing


class SigningGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def lock(self, **changes):
        value = dict(formatVersion=1, purpose='qualification-only', packageId=signing.PACKAGE,
                     certificateSha256='1' * 64, lastPublished=None)
        value.update(changes)
        path = self.root / 'public.json'; path.write_text(json.dumps(value)); return path

    def test_unprovisioned_identity_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'certificate-not-pinned'):
            signing.load_lock(self.lock(certificateSha256=None), True)

    def test_test_identity_cannot_be_used_for_development(self):
        with self.assertRaisesRegex(ValueError, 'signing-lock-purpose'):
            signing.load_lock(self.lock(), False)

    def test_existing_output_preserved_before_reading_keys(self):
        path = self.root / 'delivered'; path.mkdir(); (path / 'save').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'output-already-exists'):
            signing.sign(SimpleNamespace(output=path))
        self.assertEqual((path / 'save').read_text(), 'keep')

    def test_password_permissions_and_line_validation(self):
        path = self.root / 'private-password'; path.write_text('synthetic\n'); path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'permissions'): signing.private_file(path, True)
        path.chmod(0o600); self.assertEqual(signing.private_file(path, True), path)
        path.write_text('synthetic\nsecond\n')
        with self.assertRaisesRegex(ValueError, 'one-nonempty-line'): signing.private_file(path, True)
        link = self.root / 'link'; link.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'symlink'): signing.private_file(link, True)

    def test_version_bounds(self):
        for value in (True, 0, -1, 2100000001, '2'):
            with self.assertRaisesRegex(ValueError, 'invalid-version'): signing.version(value)

    def test_update_requires_exact_published_previous_apk_and_increase(self):
        lock = dict(lastPublished=dict(versionCode=4, apkSha256='a' * 64))
        old = dict(versionCode=4, apkSha256='a' * 64)
        with patch.object(signing, 'verify', return_value=old):
            self.assertEqual(signing.continuity(lock, Path('prior'), {}, 5, False, True), old)
            for new in (3, 4):
                with self.assertRaisesRegex(ValueError, 'must-increase'):
                    signing.continuity(lock, Path('prior'), {}, new, False, True)
            with self.assertRaisesRegex(ValueError, 'already-established'):
                signing.continuity(lock, None, {}, 5, True, True)
        with patch.object(signing, 'verify', return_value=dict(old, apkSha256='b' * 64)):
            with self.assertRaisesRegex(ValueError, 'not-published-baseline'):
                signing.continuity(lock, Path('prior'), {}, 5, False, True)
        with self.assertRaisesRegex(ValueError, 'previous-published'):
            signing.continuity(lock, None, {}, 5, False, True)

    def test_sdk_error_never_exports_captured_output(self):
        with self.assertRaisesRegex(ValueError, '^apk-signing-failed$'):
            signing.command([sys.executable, '-I', '-c',
                             'import sys; print("synthetic private diagnostic"); sys.stderr.write("synthetic private password"); sys.exit(1)'],
                            'apk-signing')

    def test_actual_process_output_limits_apply_to_both_streams(self):
        for stream in ('stdout', 'stderr'):
            with self.assertRaisesRegex(ValueError, '^fixture-output-limit$'):
                signing.command([sys.executable, '-I', '-c',
                                 f'import sys; sys.{stream}.buffer.write(b"x" * (1024 * 1024 + 65536))'], 'fixture')


@unittest.skipUnless(os.environ.get('ESTERIA_SIGNING_TEST_BUILD_TOOLS') and os.environ.get('ESTERIA_SIGNING_TEST_DEBUG_KEY'),
                     'real SDK/key fixture not supplied; no key is generated')
class ActualSdkSigning(unittest.TestCase):
    """Uses ONLY a pre-existing disposable debug key and tiny generated manifests.

    No production key creation, application execution, install-over or save claim.
    """
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.build_tools = Path(os.environ['ESTERIA_SIGNING_TEST_BUILD_TOOLS'])
        self.tools = signing.sdk_tools(self.build_tools)
        self.android_jar = self.build_tools.parents[1] / 'platforms/android-35/android.jar'
        self.key = self.root / 'existing-test-key'; shutil.copyfile(os.environ['ESTERIA_SIGNING_TEST_DEBUG_KEY'], self.key)
        self.key.chmod(0o600)
        self.passwords = [self.root / name for name in ('store-pass', 'key-pass')]
        for password in self.passwords:
            password.write_text('android\n'); password.chmod(0o600)
        # Read only the public certificate from an actual SDK-signed fixture.
        self.first = self.apk(1)
        signed = self.root / 'certificate-fixture.apk'
        signing.command([self.tools['apksigner'], 'sign', '--ks', self.key, '--ks-key-alias', 'androiddebugkey',
                         '--ks-pass', 'file:' + str(self.passwords[0]), '--key-pass', 'file:' + str(self.passwords[1]),
                         '--v4-signing-enabled', 'false', '--in', self.first, '--out', signed], 'fixture-sign')
        output = signing.command([self.tools['apksigner'], 'verify', '--print-certs', signed], 'fixture-verify')
        import re
        certificate = re.findall(r'^Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})$', output, re.M)
        self.assertEqual(len(certificate), 1)
        self.lock_value = dict(formatVersion=1, purpose='qualification-only', packageId=signing.PACKAGE,
                               certificateSha256=certificate[0], lastPublished=None)
        self.lock = self.root / 'fixture-public-pin.json'; self.write_lock()

    def write_lock(self):
        self.lock.write_text(json.dumps(self.lock_value))

    def apk(self, code, package=signing.PACKAGE, debug=False):
        folder = self.root / ('manifest-' + str(code) + '-' + str(debug) + '-' + package); folder.mkdir()
        manifest = folder / 'AndroidManifest.xml'
        manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" '
                            f'package="{package}" android:versionCode="{code}" android:versionName="fixture">'
                            '<uses-sdk android:minSdkVersion="26" android:targetSdkVersion="35"/>'
                            f'<application android:debuggable="{str(debug).lower()}"/></manifest>')
        output = folder / 'unsigned.apk'
        signing.command([self.tools['aapt'], 'package', '-f', '-M', manifest, '-I', self.android_jar,
                         '-F', output], 'fixture-package')
        return output

    def args(self, apk, code, name, **changes):
        values = dict(apk=apk, version_code=code, output=self.root / name, lock=self.lock,
                      build_tools=self.build_tools, qualification_only=True, previous_apk=None,
                      initial_baseline=True, keystore=self.key, store_password_file=self.passwords[0],
                      key_password_file=self.passwords[1], alias='androiddebugkey')
        values.update(changes); return SimpleNamespace(**values)

    def test_actual_sign_update_payload_wrong_cert_and_preservation(self):
        key_before = signing.digest(self.key); source_before = signing.digest(self.first)
        first = signing.sign(self.args(self.first, 1, 'first'))
        previous = self.root / 'first/esteria-development.apk'
        self.assertTrue(first['payloadPreserved']); self.assertFalse(first['persistentSigningIdentityVerified'])
        self.assertFalse(first['actualInstallOverQualified'])
        self.lock_value['lastPublished'] = dict(versionCode=1, apkSha256=signing.digest(previous)); self.write_lock()
        updated = signing.sign(self.args(self.apk(2), 2, 'second', previous_apk=previous, initial_baseline=False))
        self.assertEqual(updated['signedApk']['versionCode'], 2)
        self.assertEqual(signing.digest(self.key), key_before); self.assertEqual(signing.digest(self.first), source_before)
        with self.assertRaisesRegex(ValueError, 'must-increase'):
            signing.sign(self.args(self.first, 1, 'downgrade', previous_apk=previous, initial_baseline=False))
        self.assertFalse((self.root / 'downgrade').exists())
        self.lock_value['lastPublished'] = None; self.lock_value['certificateSha256'] = '0' * 64; self.write_lock()
        with self.assertRaisesRegex(ValueError, 'certificate-mismatch'):
            signing.sign(self.args(self.first, 1, 'wrong-cert'))
        self.assertFalse((self.root / 'wrong-cert').exists())

    def test_actual_wrong_package_debug_and_private_credentials_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'package-or-version'):
            signing.sign(self.args(self.apk(1, 'org.example.wrong'), 1, 'wrong-package'))
        self.lock_value['purpose'] = 'persistent-development'; self.write_lock()
        with self.assertRaisesRegex(ValueError, 'debuggable-apk-not-distributable'):
            signing.sign(self.args(self.apk(1, debug=True), 1, 'debug', qualification_only=False))
        with self.assertRaisesRegex(ValueError, 'debug-certificate-not-persistent'):
            signing.sign(self.args(self.first, 1, 'debug-key', qualification_only=False))
        self.lock_value['purpose'] = 'qualification-only'; self.write_lock()
        self.passwords[0].write_text('intentionally-wrong-fixture-password\n')
        with self.assertRaisesRegex(ValueError, '^apk-signing-failed$'):
            signing.sign(self.args(self.first, 1, 'wrong-password'))
        for name in ('wrong-package', 'debug', 'debug-key', 'wrong-password'):
            self.assertFalse((self.root / name).exists())


if __name__ == '__main__':
    unittest.main()
