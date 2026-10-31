import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

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
    @staticmethod
    def stored_alignment_apk(output, manifest):
        """Classic ZIP with authentic compiled manifest and local-only zero extras.

        Android's APK writer may place 2/3 padding zeros in local headers without
        declaring them in CD extras. This reproduces that metadata shape without
        shipping a full application, provider archive or persistent signing key.
        """
        entries = [('AndroidManifest.xml', manifest, 0)]
        entries += [('assets/stored-%02d.dat' % index, b'fixture-' + bytes([65 + index]) * (index + 1),
                     (0, 2, 3)[index % 3]) for index in range(9)]
        local, central, observed = bytearray(), bytearray(), {}
        for name, payload, extra_length in entries:
            # Every STORED input is unaligned, exercising all three extra shapes.
            if name != 'AndroidManifest.xml' and (len(local) + 30 + len(name) + extra_length) % 4 == 0:
                name = name.replace('.dat', 'x.dat')
            encoded = name.encode('ascii'); extra = b'\0' * extra_length
            offset = len(local); crc = zlib.crc32(payload) & 0xffffffff
            local += struct.pack('<4s5H3I2H', b'PK\x03\x04', 20, 0, zipfile.ZIP_STORED,
                0, 0x5821, crc, len(payload), len(payload), len(encoded), len(extra)) + encoded + extra + payload
            central += struct.pack('<4s6H3I5H2I', b'PK\x01\x02', 20, 20, 0, zipfile.ZIP_STORED,
                0, 0x5821, crc, len(payload), len(payload), len(encoded), 0, 0, 0, 0, 0, offset) + encoded
            observed[name] = extra_length
        eocd = struct.pack('<4s4H2IH', b'PK\x05\x06', 0, 0, len(entries), len(entries), len(central), len(local), 0)
        output.write_bytes(local + central + eocd)
        return observed

    @staticmethod
    def local_parts(raw, info):
        offset = info.header_offset
        name_length, extra_length = struct.unpack_from('<HH', raw, offset + 26)
        extra_offset = offset + 30 + name_length
        return extra_offset, extra_length, extra_offset + extra_length

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
        if recipe['alignmentPaddingBytes']:
            bad = fixture.root / 'nonzero-padding.apk'; content = bytearray(signed.read_bytes())
            content[recipe['unsignedCentralDirectoryOffset']] = 1; bad.write_bytes(content)
            with self.assertRaisesRegex(ValueError, 'alignment-padding-not-zero'):
                detached.export(unsigned, bad, fixture.root / 'nonzero-padding.json')
        with self.assertRaisesRegex(ValueError, 'must-be-unsigned'):
            detached.export(signed, signed, fixture.root / 'already-signed.json')

        for label in ('unsigned', 'signed', 'block', 'padding-type'):
            changed = json.loads(recipe_file.read_text())
            if label in ('unsigned', 'signed'):
                changed[label]['sha256'] = 'f' * 64
            elif label == 'padding-type':
                changed['alignmentPaddingBytes'] = True
            else:
                block = bytearray(base64.b64decode(changed['signingBlockBase64'])); block[30] ^= 1
                changed['signingBlockBase64'] = base64.b64encode(block).decode()
            source = fixture.root / ('changed-' + label + '.json'); source.write_text(json.dumps(changed))
            output = fixture.root / ('refused-' + label + '.apk')
            with self.subTest(recipeMutation=label), self.assertRaises(ValueError):
                detached.apply(unsigned, source, output)
            self.assertFalse(output.exists())
        self.assertFalse(list(fixture.root.glob('.public-apk-signature-*')))

    def test_actual_stored_zip_alignment_records_reconstruct_and_refuse_other_changes(self):
        from tests.test_android_signing import ActualSdkSigning
        fixture = ActualSdkSigning('test_actual_stock_identity_is_separate_from_custom_package')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.lock_value['packageId'] = signing.STOCK_PACKAGE; fixture.write_lock()
        compiled = fixture.apk(1, signing.STOCK_PACKAGE)
        with zipfile.ZipFile(compiled) as archive:
            manifest = archive.read('AndroidManifest.xml')
        unsigned = fixture.root / 'unaligned-stored.apk'
        observed = self.stored_alignment_apk(unsigned, manifest)
        with zipfile.ZipFile(unsigned) as archive:
            self.assertEqual({len(info.extra) for info in archive.infolist()}, {0})
            raw = unsigned.read_bytes()
            for info in archive.infolist():
                extra_offset, extra_length, data_offset = self.local_parts(raw, info)
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
                self.assertEqual(extra_length, observed[info.filename])
                self.assertEqual(raw[extra_offset:data_offset], b'\0' * extra_length)
                self.assertNotEqual(data_offset % 4, 0)
        receipt = signing.sign(fixture.args(unsigned, 1, 'stored-signed'))
        signed = fixture.root / 'stored-signed/esteria-development.apk'
        recipe_file = fixture.root / 'stored-public-recipe.json'
        recipe = detached.export(unsigned, signed, recipe_file)
        self.assertEqual(recipe['formatVersion'], 2)
        self.assertEqual(recipe['scope'], 'public-apk-v2-v3-signature-and-zip-alignment-only')
        self.assertEqual(set(recipe['zipAlignmentEntries']), set(observed))
        self.assertEqual({observed[name] for name in recipe['zipAlignmentEntries']}, {0, 2, 3})
        restored = fixture.root / 'stored-reconstructed.apk'
        proof = detached.apply(unsigned, recipe_file, restored)
        self.assertTrue(proof['exactPreviouslySignedBytesReconstructed'])
        self.assertEqual(restored.read_bytes(), signed.read_bytes())
        self.assertEqual(signing.payload(unsigned), signing.payload(restored))
        checked = signing.verify(restored, fixture.tools, fixture.lock_value, 1, True)
        self.assertEqual(checked['apkSha256'], receipt['signedApk']['apkSha256'])

        # A recipe chooses only source entry names; it cannot carry patch bytes.
        for label, names in (('missing-entry', recipe['zipAlignmentEntries'][1:]),
                ('foreign-entry', recipe['zipAlignmentEntries'] + ['assets/not-in-source.dat'])):
            altered = dict(recipe, zipAlignmentEntries=names)
            selected = fixture.root / (label + '.json'); selected.write_text(json.dumps(altered))
            output = fixture.root / (label + '.apk')
            with self.subTest(selection=label), self.assertRaises(ValueError):
                detached.apply(unsigned, selected, output)
            self.assertFalse(output.exists())

        signed_raw = bytearray(signed.read_bytes())
        with zipfile.ZipFile(signed) as archive:
            info = archive.getinfo(next(name for name in observed if name.startswith('assets/')))
        extra_offset, extra_length, data_offset = self.local_parts(signed_raw, info)
        marker = signed_raw[extra_offset:data_offset].find(b'\x35\xd9')
        self.assertGreaterEqual(marker, 0, 'Actual SDK must emit its canonical 0xd935 alignment extra')
        self.assertGreaterEqual(extra_length - marker, 6)
        for label, offset in (('noncanonical-extra', extra_offset + marker + 4), ('payload-change', data_offset)):
            changed = bytearray(signed_raw); changed[offset] ^= 1
            mutated = fixture.root / (label + '.apk'); mutated.write_bytes(changed)
            output = fixture.root / (label + '.json')
            with self.subTest(signedMutation=label), self.assertRaises(ValueError):
                detached.export(unsigned, mutated, output)
            self.assertFalse(output.exists())
        self.assertFalse(list(fixture.root.glob('.public-apk-signature-*')))


if __name__ == '__main__':
    unittest.main()
