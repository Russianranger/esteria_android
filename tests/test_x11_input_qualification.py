import copy
import json
from pathlib import Path
import unittest

from tools import qualify_x11_input as x11


class X11InputQualification(unittest.TestCase):
    def test_every_actual_observer_assertion_and_narrow_scope_are_required(self):
        value = dict(formatVersion=1, scope=x11.SCOPE, groupsPassed=7, observedEvents=16, acknowledgments=15,
                     **{key: True for key in x11.CHECKS}, **{key: False for key in x11.UNQUALIFIED})
        self.assertEqual(x11.fixture_receipt(value), value)
        cases = [(key, False) for key in x11.CHECKS] + [(key, True) for key in x11.UNQUALIFIED]
        cases += [('observedEvents', 15), ('acknowledgments', 14), ('groupsPassed', 6),
                  ('formatVersion', True), ('scope', 'android-input-qualified')]
        for key, replacement in cases:
            changed = copy.deepcopy(value); changed[key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError): x11.fixture_receipt(changed)
        with self.assertRaises(ValueError): x11.fixture_receipt(dict(value, extra=True))

    def test_namespace_helper_exit_cleanup_and_log_failures_cannot_qualify(self):
        value = dict(expectedExit=0, workerCompleted=True, networkIsolated=True, displayReady=True,
                     helperReady=True, observerExit=0, receiptValidated=True, helperExit=0, helperForced=False,
                     socketRemoved=True, displayStopped=True, logStreamsDrained=True, logsWithinLimit=True,
                     logWritesSucceeded=True)
        self.assertTrue(x11.passed(value, 0))
        for key in value:
            changed = copy.deepcopy(value)
            changed[key] = 1 if type(value[key]) is int else not value[key]
            with self.subTest(key=key): self.assertFalse(x11.passed(changed, 0))
        for code in (-9, 1, False, None): self.assertFalse(x11.passed(value, code))
        self.assertFalse(x11.passed(dict(value, expectedExit=False), 0))

    def test_x11_closure_is_pinned_to_exact_runtime_and_actual_arm64_images(self):
        root = Path(__file__).resolve().parents[1]
        lock = json.loads((root / 'runtime/bridges/x11-runtime.lock.json').read_text())
        runtime = json.loads((root / 'runtime/runtime-sources.lock.json').read_text())['packages']['wine-arm64']
        self.assertEqual(lock['runtimeArchiveSha256'], runtime['archive']['sha256'])
        self.assertEqual(set(lock['entrypoints']), {'usr/bin/Xtigervnc', 'usr/bin/xkbcomp'})
        self.assertGreaterEqual(len(lock['components']), 40)
        for name, pin in lock['components'].items():
            self.assertTrue(name.startswith(('usr/', 'lib/')) and '..' not in Path(name).parts)
            self.assertGreater(pin['bytes'], 0)
            self.assertRegex(pin['sha256'], '^[0-9a-f]{64}$')
            self.assertEqual((pin['elfMachine'], pin['elfClass']), (183, 2))
        self.assertFalse(lock['inputQualified']); self.assertFalse(lock['androidQualified'])
        self.assertEqual(lock['symlinks']['lib'], 'usr/lib')
        self.assertEqual(lock['symlinks']['lib/ld-linux-aarch64.so.1'], 'aarch64-linux-gnu/ld-linux-aarch64.so.1')
        self.assertIn('etc/ld.so.cache', lock['loaderConfiguration'])
        self.assertTrue(lock['preloadFileAbsent'])


if __name__ == '__main__': unittest.main()
