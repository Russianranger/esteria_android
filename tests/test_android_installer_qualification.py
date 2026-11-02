import unittest
import copy
import pathlib
import tempfile
import sys
from tools.qualify_android_installer import (instrument_passed, named_instrumentation_passed,
    qualify_preparation_components, validate_preparation_observations, run_bounded, HELPER_ASSET_FILES,
    PREPARATION_TEST, PREPARATION_METHODS, PREPARATION_SOURCES)

class InstrumentationResults(unittest.TestCase):
    def test_receipt_helper_counts_match_the_exact_packaged_closures(self):
        from tools.package_combined_android import HELPER_SETS
        self.assertEqual({'server-installation': 18, 'server-data': 6, 'server-session': 24}, HELPER_ASSET_FILES)
        for directory, count in HELPER_ASSET_FILES.items():
            self.assertEqual(count, len(HELPER_SETS[directory]), directory)

    def test_requires_one_completed_test(self):
        self.assertTrue(instrument_passed('OK (1 test)\nINSTRUMENTATION_CODE: -1\n'))
        for output in ('OK (0 tests)\nINSTRUMENTATION_CODE: -1\n', 'OK (1 test)\n',
                       'INSTRUMENTATION_CODE: -1\n', 'OK (1 test)\nINSTRUMENTATION_CODE: 0\n',
                       'OK (1 test)\nINSTRUMENTATION_STATUS_CODE: -2\nINSTRUMENTATION_CODE: -1\n',
                       'Process crashed\nOK (1 test)\nINSTRUMENTATION_CODE: -1\n'):
            self.assertFalse(instrument_passed(output), output)

    def test_process_log_is_bounded_while_draining(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / 'log'
            with self.assertRaisesRegex(RuntimeError, 'diagnostic limit'):
                run_bounded([sys.executable, '-c', 'import sys;sys.stdout.write("x"*1000000)'], path, 10, 8192)
            self.assertEqual(path.stat().st_size, 8192)

    def test_timed_out_process_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                run_bounded([sys.executable, '-c', 'import time;time.sleep(30)'], pathlib.Path(temporary)/'log', 0.1)

    @staticmethod
    def preparation_output():
        rows = []
        for index, name in enumerate(PREPARATION_METHODS, 1):
            for status in (1, 0):
                rows.extend(['INSTRUMENTATION_STATUS: class=' + PREPARATION_TEST,
                    'INSTRUMENTATION_STATUS: current=' + str(index),
                    'INSTRUMENTATION_STATUS: id=AndroidJUnitRunner',
                    'INSTRUMENTATION_STATUS: numtests=4',
                    'INSTRUMENTATION_STATUS: test=' + name,
                    'INSTRUMENTATION_STATUS_CODE: ' + str(status)])
                if status == 1:
                    rows.extend(['INSTRUMENTATION_STATUS: stream=bounded fixture observation',
                        'INSTRUMENTATION_STATUS_CODE: 2'])
        rows.extend(['OK (4 tests)', 'INSTRUMENTATION_CODE: -1'])
        return '\n'.join(rows) + '\n'

    def test_preparation_receipt_requires_each_exact_named_test_start_and_success(self):
        output = self.preparation_output()
        self.assertTrue(named_instrumentation_passed(output, PREPARATION_TEST, PREPARATION_METHODS))
        mutations = [
            output.replace(PREPARATION_METHODS[0], 'differentMethod'),
            output.replace(PREPARATION_TEST, PREPARATION_TEST + 'Other'),
            output.replace('INSTRUMENTATION_STATUS_CODE: 0', 'INSTRUMENTATION_STATUS_CODE: -2', 1),
            output.replace('INSTRUMENTATION_STATUS_CODE: 1', 'INSTRUMENTATION_STATUS_CODE: 0', 1),
            output.replace('INSTRUMENTATION_STATUS: current=2', 'INSTRUMENTATION_STATUS: current=1', 1),
            output.replace('INSTRUMENTATION_STATUS: numtests=4', 'INSTRUMENTATION_STATUS: numtests=3', 1),
            output.replace('INSTRUMENTATION_CODE: -1', 'INSTRUMENTATION_CODE: 0'),
            output + 'INSTRUMENTATION_CODE: -1\n',
            output + 'INSTRUMENTATION_CODE: 0\n',
            output.replace('OK (4 tests)', 'OK (3 tests)'),
            output + 'Process crashed\n',
        ]
        for mutation in mutations:
            self.assertFalse(named_instrumentation_passed(mutation, PREPARATION_TEST, PREPARATION_METHODS))
        self.assertFalse(named_instrumentation_passed('OK (4 tests)\nINSTRUMENTATION_CODE: -1\n',
            PREPARATION_TEST, PREPARATION_METHODS))

    @staticmethod
    def observations():
        rows = [dict(visibleLevels=3, defaultSpeed='balanced', reopenedSpeed='fast', operationUnchanged=True,
                    rates=dict(gentle=8 << 20, balanced=32 << 20, fast=64 << 20)),
            dict(healthyCriticalTrimLevel=1, realLowMemoryLevel=2, unknownMemoryCriticalTrimLevel=2,
                actualTrimRecorded=True, selectedNormalBytesPerSecond=32 << 20, pressureBytesPerSecond=2 << 20),
            dict(workerScoped=True, nestedSelectionRestored=True, unrelatedWorkerUnaffected=True,
                inputEnvironmentUnchanged=True, afterCloseUnselected=True),
            dict(previewBytes=128, removedBytes=128, afterReclaimableBytes=0, currentAndExpectedPreserved=True,
                importSavesAndPartialWorldPreserved=True, outsideSymlinkTargetPreserved=True, busyRefused=True)]
        for name, row in zip(PREPARATION_METHODS, rows):
            row.update(case=name, scope='android13-x64-preparation-controls-fixture',
                ownerGameData=False, thorQualified=False, gameplayQualified=False)
        return rows

    def test_preparation_observations_require_measured_values_and_explicit_boundary(self):
        observations = self.observations()
        self.assertEqual(set(PREPARATION_METHODS), set(validate_preparation_observations(observations)))
        for index, key, value in ((0, 'operationUnchanged', False), (0, 'defaultSpeed', 'gentle'),
            (0, 'thorQualified', True), (1, 'actualTrimRecorded', False), (1, 'realLowMemoryLevel', 1),
            (1, 'healthyCriticalTrimLevel', True),
            (2, 'afterCloseUnselected', False), (3, 'removedBytes', 127), (3, 'previewBytes', True),
            (3, 'outsideSymlinkTargetPreserved', False), (3, 'busyRefused', False)):
            changed = copy.deepcopy(observations); changed[index][key] = value
            with self.assertRaises(RuntimeError):
                validate_preparation_observations(changed)
        for changed in ([], observations[:-1], observations + [observations[-1]],
            [observations[0], observations[0], observations[2], observations[3]]):
            with self.assertRaises(RuntimeError):
                validate_preparation_observations(changed)

    def test_preparation_refuses_other_devices_and_unpinned_source_before_running_adb(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            destination = pathlib.Path(temporary)
            for properties, revision, message in (
                ({'ro.kernel.qemu': '0', 'ro.build.version.sdk': '33', 'ro.product.cpu.abi': 'x86_64'}, 'a' * 40, 'emulator'),
                ({'ro.kernel.qemu': '1', 'ro.build.version.sdk': '34', 'ro.product.cpu.abi': 'x86_64'}, 'a' * 40, 'emulator'),
                ({'ro.kernel.qemu': '1', 'ro.build.version.sdk': '33', 'ro.product.cpu.abi': 'arm64-v8a'}, 'a' * 40, 'emulator'),
                ({'ro.kernel.qemu': '1', 'ro.build.version.sdk': '33', 'ro.product.cpu.abi': 'x86_64'}, 'non-custom', 'source revision'),
            ):
                with self.assertRaisesRegex(RuntimeError, message):
                    qualify_preparation_components(root, destination, properties, {}, revision, adb='nonexistent-adb')
            self.assertEqual([], list(destination.iterdir()))

    def test_new_preparation_component_keeps_the_old_rosters_and_pins_its_own_sources(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        self.assertEqual(4, len(PREPARATION_METHODS))
        self.assertEqual(len(PREPARATION_SOURCES), len(set(PREPARATION_SOURCES)))
        for name in PREPARATION_SOURCES:
            self.assertTrue((root / name).is_file(), name)
        workflow = (root / '.github/workflows/android-instrumentation.yml').read_text()
        self.assertIn('expectedTests=14', workflow)
        self.assertIn('qualify_preparation_components(root, destination, properties', workflow)
