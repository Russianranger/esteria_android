import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import export_apk_signature as detached
from tools import sign_android_apk as signing


class PublicRecipeGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_existing_output_is_preserved_before_reading_any_apk(self):
        output = self.root / 'keep'; output.write_bytes(b'original')
        for action in (lambda: detached.export(self.root / 'missing', self.root / 'also-missing', output),
                       lambda: detached.apply(self.root / 'missing', self.root / 'missing.json', output)):
            with self.assertRaisesRegex(ValueError, 'output-already-exists'):
                action()
            self.assertEqual(output.read_bytes(), b'original')

    def test_arbitrary_or_duplicate_signature_block_ids_are_rejected(self):
        def block(ids):
            records = b''.join(struct.pack('<QI', 5, key) + b'X' for key in ids)
            size = len(records) + 24
            return struct.pack('<Q', size) + records + struct.pack('<Q', size) + detached.MAGIC
        for ids in ((detached.V2,), (detached.V2, detached.V3, 0xdeadbeef),
                    (detached.V2, detached.V3, detached.V2)):
            with self.assertRaises(ValueError):
                detached.block_ids(block(ids))
        # This tests the transport parser only, never an authentic signature.
        self.assertEqual(detached.block_ids(block((detached.V2, detached.V3))), ['0x7109871a', '0xf05368c0'])

    def test_directory_and_eocd_bounds_refuse_zip64_or_trailing_data(self):
        apk = self.root / 'ordinary.zip'
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('AndroidManifest.xml', b'synthetic-transport-layout')
        raw = bytearray(apk.read_bytes()); parsed = detached.layout(apk)
        self.assertIsNone(parsed.block)
        raw[-6:-2] = struct.pack('<I', 0xffffffff)
        apk.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, 'central-directory-bounds'):
            detached.layout(apk)
        apk.write_bytes(bytes(raw) + b'trailing')
        with self.assertRaisesRegex(ValueError, 'terminal-eocd'):
            detached.layout(apk)


@unittest.skipUnless(os.environ.get('ESTERIA_SIGNING_TEST_BUILD_TOOLS') and os.environ.get('ESTERIA_SIGNING_TEST_DEBUG_KEY'),
                     'actual SDK/pre-existing disposable key not supplied')
class ActualSdkDetachedSignature(unittest.TestCase):
    def test_actual_v2_v3_signature_reconstruction_and_tamper_refusal(self):
        # Reuse the real SDK fixture, including its external owner-only disposable
        # key copy. No production key is generated, exported or made available.
        from tests.test_android_signing import ActualSdkSigning
        fixture = ActualSdkSigning('test_actual_stock_identity_is_separate_from_custom_package')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.lock_value['packageId'] = signing.STOCK_PACKAGE; fixture.write_lock()
        unsigned = fixture.apk(1, signing.STOCK_PACKAGE)
        receipt = signing.sign(fixture.args(unsigned, 1, 'detached-original'))
        signed = fixture.root / 'detached-original/esteria-development.apk'
        recipe_file = fixture.root / 'public-signature.json'
        recipe = detached.export(unsigned, signed, recipe_file)
        self.assertEqual(recipe['signed']['sha256'], receipt['signedApk']['apkSha256'])
        self.assertEqual(set(recipe), {'formatVersion', 'scope', 'unsigned', 'signed', 'signingBlockBase64',
            'signingBlockIds', 'alignmentPaddingBytes', 'unsignedCentralDirectoryOffset', 'centralDirectoryBytes', 'eocdPatch'})
        reconstructed = fixture.root / 'reconstructed.apk'
        proof = detached.apply(unsigned, recipe_file, reconstructed)
        self.assertTrue(proof['exactPreviouslySignedBytesReconstructed'])
        self.assertFalse(proof['cryptographicSignatureVerifiedHere'])
        self.assertEqual(signed.read_bytes(), reconstructed.read_bytes())
        self.assertEqual(signing.payload(unsigned), signing.payload(reconstructed))
        verified = signing.verify(reconstructed, fixture.tools, fixture.lock_value, 1, True)
        self.assertEqual(verified['apkSha256'], receipt['signedApk']['apkSha256'])

        positions = detached.layout(signed)
        for label, offset, message in (
                ('prefix', 10, 'prefix-bytes-changed'),
                ('directory', positions.directory_offset + 10, 'central-directory-bytes-changed')):
            bad = fixture.root / (label + '.apk'); content = bytearray(signed.read_bytes()); content[offset] ^= 1; bad.write_bytes(content)
            with self.subTest(mutation=label), self.assertRaisesRegex(ValueError, message):
                detached.export(unsigned, bad, fixture.root / (label + '.json'))
        with self.assertRaisesRegex(ValueError, 'must-be-unsigned'):
            detached.export(signed, signed, fixture.root / 'already-signed.json')

        for label in ('unsigned', 'signed', 'block'):
            changed = json.loads(recipe_file.read_text())
            if label in ('unsigned', 'signed'):
                changed[label]['sha256'] = 'f' * 64
            else:
                block = bytearray(base64.b64decode(changed['signingBlockBase64'])); block[30] ^= 1
                changed['signingBlockBase64'] = base64.b64encode(block).decode()
            source = fixture.root / ('changed-' + label + '.json'); source.write_text(json.dumps(changed))
            output = fixture.root / ('refused-' + label + '.apk')
            with self.subTest(recipeMutation=label), self.assertRaises(ValueError):
                detached.apply(unsigned, source, output)
            self.assertFalse(output.exists())
        self.assertFalse(list(fixture.root.glob('.public-apk-signature-*')))


if __name__ == '__main__':
    unittest.main()
