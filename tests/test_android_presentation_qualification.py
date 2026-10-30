import copy
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from tools import qualify_android_presentation as presentation


class AndroidPresentationQualification(unittest.TestCase):
    def test_every_real_check_and_exact_emulator_scope_are_required(self):
        receipt = dict(formatVersion=1, scope=presentation.SCOPE, sourceRevision='a' * 40, fingerprint='fixture',
                       abi='x86_64', api=33, targetSdk=35, groupsPassed=5, audioTrackAcceptedFrames=4800,
                       audioTrackPlayedFrames=4800, **{flag: True for flag in presentation.FLAGS},
                       **{flag: False for flag in presentation.UNQUALIFIED})
        presentation.validate_receipt(receipt, 'a' * 40, 'fixture')
        failures = [(flag, False) for flag in presentation.FLAGS] + [(flag, True) for flag in presentation.UNQUALIFIED]
        failures += [('abi', 'arm64-v8a'), ('sourceRevision', 'b' * 40), ('fingerprint', 'different'),
                     ('api', True), ('targetSdk', 28), ('groupsPassed', 4), ('audioTrackAcceptedFrames', True),
                     ('audioTrackPlayedFrames', 4799), ('audioTrackPlayedFrames', 999999)]
        for key, value in failures:
            changed = copy.deepcopy(receipt); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                presentation.validate_receipt(changed, 'a' * 40, 'fixture')

    def test_both_real_x64_native_images_required_and_arm64_is_not_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.apk'
            header = bytearray(64); header[:7] = b'\x7fELF\x02\x01\x01'; struct.pack_into('<HH', header, 16, 3, 62)
            expected = ['lib/x86_64/libesteria_process.so', 'lib/x86_64/libesteria-presentation.so']
            with zipfile.ZipFile(path, 'w') as archive:
                for name in expected: archive.writestr(name, header)
            self.assertEqual(len(presentation.apk_identity(path)['native']), 2)
            for members, machine in [(expected[:1], 62), (expected + ['lib/x86_64/libother.so'], 62), (expected, 183)]:
                struct.pack_into('<H', header, 18, machine)
                with zipfile.ZipFile(path, 'w') as archive:
                    for name in members: archive.writestr(name, header)
                with self.subTest(members=members, machine=machine), self.assertRaises(ValueError):
                    presentation.apk_identity(path)


if __name__ == '__main__':
    unittest.main()
