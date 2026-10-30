import copy
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile

from tools import qualify_android_presentation as presentation


class AndroidPresentationQualification(unittest.TestCase):
    def test_widget_ime_requires_every_check_and_preserves_execution_boundary(self):
        receipt = dict(formatVersion=1, scope=presentation.INPUT_SCOPE, sourceRevision='a' * 40, fingerprint='fixture',
                       abi='x86_64', api=33, targetSdk=35, groupsPassed=8, recordingSinkCapacity=256,
                       batchCapacityRefusals=1, controllerStickMotionQualified=False, controllerCameraMotionQualified=False,
                       registeredControllerAvailable=False, constructedMotionEventWithRealDevice=False,
                       registeredControllerEofRemovalVerified=False, registeredControllerAxisRangeCount=0,
                       registeredControllerUnavailableReason='registration-not-observed',
                       **{flag: True for flag in presentation.INPUT_FLAGS},
                       **{flag: False for flag in presentation.INPUT_UNQUALIFIED})
        presentation.validate_input_receipt(receipt, 'a' * 40, 'fixture')
        failures = [(flag, False) for flag in presentation.INPUT_FLAGS] + [(flag, True) for flag in presentation.INPUT_UNQUALIFIED]
        failures += [('api', True), ('targetSdk', 34), ('groupsPassed', 7), ('recordingSinkCapacity', 257),
                     ('batchCapacityRefusals', True), ('batchCapacityRefusals', 0),
                     ('controllerStickMotionQualified', True), ('controllerCameraMotionQualified', True),
                     ('controllerStickMotionQualified', 0), ('controllerCameraMotionQualified', None),
                     ('registeredControllerAvailable', True), ('constructedMotionEventWithRealDevice', True),
                     ('registeredControllerEofRemovalVerified', True), ('registeredControllerAxisRangeCount', True),
                     ('registeredControllerUnavailableReason', 'ignored'),
                     ('scope', presentation.SCOPE), ('sourceRevision', 'b' * 40), ('fingerprint', 'different'), ('abi', 'arm64-v8a')]
        for key, value in failures:
            changed = copy.deepcopy(receipt); changed[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                presentation.validate_input_receipt(changed, 'a' * 40, 'fixture')
        for key in (*presentation.INPUT_FLAGS, *presentation.INPUT_UNQUALIFIED, 'recordingSinkCapacity',
                    'controllerStickMotionQualified', 'controllerCameraMotionQualified', 'registeredControllerAvailable',
                    'constructedMotionEventWithRealDevice', 'registeredControllerEofRemovalVerified',
                    'registeredControllerAxisRangeCount', 'registeredControllerUnavailableReason'):
            changed = copy.deepcopy(receipt); del changed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
                presentation.validate_input_receipt(changed, 'a' * 40, 'fixture')
        registered = copy.deepcopy(receipt)
        for key in ('registeredControllerAvailable', 'constructedMotionEventWithRealDevice',
                    'registeredControllerEofRemovalVerified', 'controllerStickMotionQualified', 'controllerCameraMotionQualified'):
            registered[key] = True
        registered.update(registeredControllerAxisRangeCount=8, registeredControllerUnavailableReason='none')
        presentation.validate_input_receipt(registered, 'a' * 40, 'fixture')
        for key, value in [('registeredControllerEofRemovalVerified', False), ('registeredControllerAxisRangeCount', 7),
                           ('constructedMotionEventWithRealDevice', False), ('registeredControllerUnavailableReason', 'registration-not-observed')]:
            changed = copy.deepcopy(registered); changed[key] = value
            with self.subTest(registered_key=key), self.assertRaises(ValueError):
                presentation.validate_input_receipt(changed, 'a' * 40, 'fixture')

    def test_every_real_check_and_exact_emulator_scope_are_required(self):
        receipt = dict(formatVersion=1, scope=presentation.SCOPE, sourceRevision='a' * 40, fingerprint='fixture',
                       abi='x86_64', api=33, targetSdk=35, groupsPassed=6,
                       surfaceLifecycleConnections=2, surfaceLifecyclePeerEofs=2, audioTrackAcceptedFrames=4800,
                       audioTrackPlayedFrames=4800, **{flag: True for flag in presentation.FLAGS},
                       **{flag: False for flag in presentation.UNQUALIFIED})
        presentation.validate_receipt(receipt, 'a' * 40, 'fixture')
        failures = [(flag, False) for flag in presentation.FLAGS] + [(flag, True) for flag in presentation.UNQUALIFIED]
        failures += [('abi', 'arm64-v8a'), ('sourceRevision', 'b' * 40), ('fingerprint', 'different'),
                     ('api', True), ('targetSdk', 28), ('groupsPassed', 5), ('audioTrackAcceptedFrames', True),
                     ('surfaceLifecycleConnections', True), ('surfaceLifecycleConnections', 1),
                     ('surfaceLifecycleConnections', 3), ('surfaceLifecyclePeerEofs', True),
                     ('surfaceLifecyclePeerEofs', 1), ('surfaceLifecyclePeerEofs', 3),
                     ('audioTrackPlayedFrames', 4799), ('audioTrackPlayedFrames', 999999)]
        for key, value in failures:
            changed = copy.deepcopy(receipt); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                presentation.validate_receipt(changed, 'a' * 40, 'fixture')

        for key in (*presentation.FLAGS, 'surfaceLifecycleConnections', 'surfaceLifecyclePeerEofs'):
            changed = copy.deepcopy(receipt); del changed[key]
            with self.subTest(missing=key), self.assertRaises(ValueError):
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
