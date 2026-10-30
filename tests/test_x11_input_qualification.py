import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
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
                     logWritesSucceeded=True, authenticatedServerCommand=True, positiveHelperReadyMarker=True,
                     missingCookie=dict(exitCode=3, listenerCreated=False, readyMarker=False, logDrained=True),
                     wrongCookie=dict(exitCode=3, listenerCreated=False, readyMarker=False, logDrained=True))
        self.assertTrue(x11.passed(value, 0))
        for key in value:
            changed = copy.deepcopy(value)
            changed[key] = 1 if type(value[key]) is int else not value[key]
            with self.subTest(key=key): self.assertFalse(x11.passed(changed, 0))
        for code in (-9, 1, False, None): self.assertFalse(x11.passed(value, code))
        for name in ('expectedExit', 'observerExit', 'helperExit'):
            self.assertFalse(x11.passed(dict(value, **{name: False}), 0))
        for name in ('missingCookie', 'wrongCookie'):
            for key, replacement in (('exitCode', 0), ('exitCode', False), ('readyMarker', True),
                                     ('listenerCreated', True), ('logDrained', False)):
                changed = copy.deepcopy(value); changed[name][key] = replacement
                with self.subTest(name=name, key=key): self.assertFalse(x11.passed(changed, 0))

    def test_actual_application_java_formatter_and_commands(self):
        if not shutil.which('javac'):
            if os.environ.get('ESTERIA_REQUIRE_JAVA_TESTS') == '1': self.fail('javac required by this qualification')
            self.skipTest('host JDK17 required for actual application formatter')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); fixture = root / 'fixture'; output = root / 'public'
            fixture.mkdir(mode=0o700); output.mkdir(); (root / 'session').mkdir()
            proof = x11.prepare_authority(root, fixture, output)
            self.assertTrue(proof['actualApplicationFormatterExecuted'])
            self.assertFalse(proof['privateCookiesExported'])
            self.assertEqual(proof['sources'], {name: x11.identity(x11.ROOT / name) for name in x11.FORMATTER_SOURCES})
            cookie = x11.authority_cookie(fixture / 'auth-session/Xauthority')
            wrong = x11.authority_cookie(fixture / 'auth-session/Xauthority-wrong')
            self.assertEqual(list((root / 'session').iterdir()), [])
            self.assertNotEqual(cookie, wrong)
            self.assertEqual(len(cookie), 16)
            self.assertEqual({path.name for path in output.iterdir()}, {'formatter-compile.log', 'formatter-run.log'})
            for path in output.iterdir(): self.assertNotIn(cookie, path.read_bytes())
            command = x11.server_command(fixture / 'server-argv.txt')
            self.assertIn('-auth', command); self.assertNotIn('-ac', command)
            self.assertEqual(command[command.index('-auth') + 1], '/session/Xauthority')
            with self.assertRaises(ValueError): x11.prepare_authority(root, fixture, output)
            authority = fixture / 'auth-session/Xauthority'
            authority.chmod(0o644)
            with self.assertRaises(ValueError): x11.authority_cookie(authority)
            authority.chmod(0o600); original = authority.read_bytes()
            for malformed in (original[:-1], original + b'\x00', b'\xff\xff\xff\xff', b'x' * 257):
                authority.write_bytes(malformed)
                with self.assertRaises(ValueError): x11.authority_cookie(authority)
            plan = fixture / 'server-argv.txt'
            plan.write_text('\n'.join(command + ['-ac']) + '\n')
            with self.assertRaises(ValueError): x11.server_command(plan)

    def test_session_mountpoint_must_not_replace_existing_files_or_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); fixture = root / 'fixture'; fixture.mkdir(); output = root / 'logs'; output.mkdir()
            session = root / 'session'; session.mkdir(); retained = session / 'retained'; retained.write_bytes(b'original')
            with self.assertRaises(ValueError): x11.prepare_authority(root, fixture, output)
            self.assertEqual(retained.read_bytes(), b'original')
            retained.unlink(); session.rmdir(); foreign = root / 'foreign'; foreign.mkdir(); session.symlink_to(foreign)
            with self.assertRaises(ValueError): x11.prepare_authority(root, fixture, output)
            self.assertEqual(list(foreign.iterdir()), [])

    def test_negative_probe_requires_source_specific_exit_without_listener_or_marker(self):
        cases = [('raise SystemExit(3)', True), ('raise SystemExit(0)', False),
                 ('print("ESTERIA_X11_INPUT_READY protocol=1"); raise SystemExit(3)', False),
                 ('from pathlib import Path; Path(__import__("sys").argv[1]).write_text("listener"); raise SystemExit(3)', False)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for number, (script, accepted) in enumerate(cases):
                captures = []; endpoint = root / ('endpoint-' + str(number))
                command = [sys.executable, '-c', script, str(endpoint)]
                try:
                    if accepted:
                        result = x11.rejected_helper(command, endpoint, root / (str(number) + '.log'), captures)
                        self.assertTrue(x11.rejection_passed(result))
                    else:
                        with self.assertRaises(ValueError):
                            x11.rejected_helper(command, endpoint, root / (str(number) + '.log'), captures)
                finally:
                    for capture in captures:
                        self.assertTrue(capture.finish(5)); self.assertIsNotNone(capture.process.poll())

    def test_x11_environment_selects_only_the_requested_authority(self):
        for authority in ('/session/Xauthority', '/session/Xauthority-wrong', '/session/Xauthority-missing'):
            command = x11.x11_command(Path('/runtime'), authority, '/helper', '/socket')
            self.assertEqual(command[-4:], ['DISPLAY=:64', 'XAUTHORITY=' + authority, '/helper', '/socket'])

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
