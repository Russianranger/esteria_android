import unittest
import pathlib
import tempfile
import sys
from tools.qualify_android_installer import instrument_passed, run_bounded, HELPER_ASSET_FILES

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
