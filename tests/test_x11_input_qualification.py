import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from tools import qualify_x11_input as x11


class X11InputQualification(unittest.TestCase):
    def test_selected_runtime_and_x11_locks_require_exact_prepared_archive_and_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); runtime = root / 'runtime'; recipe = root / 'source/runtime/bridges'
            recipe.mkdir(parents=True); (runtime / 'rootfs/usr/bin').mkdir(parents=True)
            (runtime / 'rootfs/usr/lib').mkdir(); (runtime / 'rootfs/etc').mkdir()
            (runtime / 'rootfs/lib').symlink_to('usr/lib')
            image = bytearray(64); image[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', image, 18, 183)
            for name in ('Xtigervnc', 'xkbcomp'): (runtime / 'rootfs/usr/bin' / name).write_bytes(image)
            (runtime / 'rootfs/etc/ld.so.conf').write_bytes(b'/usr/lib\n')
            images = {f'usr/bin/{name}': dict(x11.identity(runtime / 'rootfs/usr/bin' / name), elfMachine=183,
                                            elfClass=2) for name in ('Xtigervnc', 'xkbcomp')}
            config = {'etc/ld.so.conf': x11.identity(runtime / 'rootfs/etc/ld.so.conf')}
            package = dict(archive={'sha256': 'b' * 64}, manifest={'sha256': 'c' * 64})
            default_lock = root / 'default-runtime.json'; candidate_lock = root / 'candidate-runtime.json'
            selected_x11 = root / 'candidate-x11.json'
            def write(path, value): path.write_text(json.dumps(value))
            def prepare(value):
                write(runtime / 'package-receipt.json', dict(archiveSha256=value['archive']['sha256'],
                    manifestSha256=value['manifest']['sha256'],
                    packagePinSha256=hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                    preparerSha256=x11.identity(Path(x11.packages.__file__))['sha256'],
                    archiveExtracted=True, stagedFilesReadBack=True))
            closure = dict(formatVersion=1, scope='pinned-wine-rootfs-x11-static-library-closure',
                runtimeArchiveSha256='b' * 64, entrypoints=list(images), components=images,
                loaderConfiguration=config, symlinks={'lib': 'usr/lib'}, preloadFileAbsent=True,
                androidQualified=False, inputQualified=False)
            write(default_lock, dict(formatVersion=1, packages={'wine-arm64': package}))
            write(recipe / 'x11-runtime.lock.json', closure); prepare(package)
            with patch.object(x11, 'ROOT', root / 'source'), patch.object(x11.packages, 'DEFAULT_LOCK', default_lock):
                actual, proof = x11.validate_runtime(runtime)
                self.assertEqual(actual, package)
                self.assertEqual(proof['runtimeLockSha256'], x11.identity(default_lock)['sha256'])
                self.assertEqual(proof['x11RuntimeLockSha256'], x11.identity(recipe / 'x11-runtime.lock.json')['sha256'])
                candidate = dict(package, archive={'sha256': 'e' * 64})
                write(candidate_lock, dict(formatVersion=1, packages={'wine-arm64': candidate}))
                prepare(candidate)
                with self.assertRaisesRegex(ValueError, 'fresh-runtime-preparation-required'):
                    x11.validate_runtime(runtime)
                with self.assertRaisesRegex(ValueError, 'x11-runtime-pin-mismatch'):
                    x11.validate_runtime(runtime, candidate_lock)
                rebound = dict(closure, runtimeArchiveSha256='e' * 64)
                write(selected_x11, rebound)
                actual, proof = x11.validate_runtime(runtime, candidate_lock, selected_x11)
                self.assertEqual(actual, candidate)
                self.assertEqual(proof['runtimeLockSha256'], x11.identity(candidate_lock)['sha256'])
                self.assertEqual(proof['x11RuntimeLockSha256'], x11.identity(selected_x11)['sha256'])
                for key, wrong in (('formatVersion', True), ('scope', 'android-qualified'), ('inputQualified', True)):
                    write(selected_x11, dict(rebound, **{key: wrong}))
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'x11-runtime-lock-scope'):
                        x11.validate_runtime(runtime, candidate_lock, selected_x11)
                write(selected_x11, rebound)
                (runtime / 'rootfs/usr/bin/Xtigervnc').write_bytes(bytes(image) + b'changed')
                with self.assertRaisesRegex(ValueError, 'package-size-mismatch'):
                    x11.validate_runtime(runtime, candidate_lock, selected_x11)

    def test_selected_bridge_lock_is_hashed_and_bound_to_candidate_not_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source'; payload = root / 'payload'
            for name in ('native/guest-bridges', 'native/presentation', 'native/guest-tests', 'runtime/bridges'):
                (source / name).mkdir(parents=True)
            for name in ('guest-bridges/fixture.c', 'presentation/frame_protocol.h', 'presentation/frame_transport.h',
                         'guest-tests/x11_input_observer.c'):
                (source / 'native' / name).write_bytes(b'source fixture\n')
            for name in ('bin', 'x11-test'): (payload / name).mkdir(parents=True)
            for name in ('bin/' + x11.HELPER, 'x11-test/' + x11.OBSERVER): (payload / name).write_bytes(b'elf fixture')
            sources = {name: x11.identity(source / 'native' / name) for name in
                       ('guest-bridges/fixture.c', 'presentation/frame_protocol.h', 'presentation/frame_transport.h')}
            revision = 'a' * 40; old = 'b' * 64; candidate = 'e' * 64; binary = {'sha256': 'd' * 64}
            default_lock = source / 'runtime/bridges/sources.lock.json'; selected_lock = root / 'selected-bridge.json'
            default_lock.write_text(json.dumps(dict(formatVersion=1, scope='guest-bridge-build-inputs-only',
                architecture='arm64', runtimeArchiveSha256=old)))
            selected = dict(formatVersion=1, scope='guest-bridge-build-inputs-only', architecture='arm64',
                            runtimeArchiveSha256=candidate)
            selected_lock.write_text(json.dumps(selected))
            def record(archive, lock_path):
                input_sha = x11.identity(lock_path)['sha256']
                (payload / 'bridge-build.json').write_text(json.dumps(dict(formatVersion=1, compiled=True,
                    scope='linux-arm64-guest-bridge-build-only', integrationRevision=revision, sources=sources,
                    inputLockSha256=input_sha, runtimeArchiveSha256=archive, binaries={x11.HELPER: binary})))
                (payload / 'x11-test/observer-build.json').write_text(json.dumps(dict(formatVersion=1,
                    scope='linux-arm64-x11-observer-build-only', integrationRevision=revision, inputLockSha256=input_sha,
                    bridgeReceipt=x11.identity(payload / 'bridge-build.json'), binary=binary,
                    source=x11.identity(source / 'native/guest-tests/x11_input_observer.c'),
                    executionQualified=False, androidQualified=False, gameplayQualified=False)))
            spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda _: None))
            with patch.object(x11, 'ROOT', source), \
                 patch.object(x11.importlib.util, 'spec_from_file_location', return_value=spec), \
                 patch.object(x11.importlib.util, 'module_from_spec', return_value=types.SimpleNamespace(elf=lambda _: binary)):
                record(old, default_lock)
                self.assertEqual(x11.build_identity(payload, revision, {'archive': {'sha256': old}})['inputLockSha256'],
                                 x11.identity(default_lock)['sha256'])
                record(candidate, selected_lock)
                package = {'archive': {'sha256': candidate}}
                self.assertEqual(x11.build_identity(payload, revision, package, selected_lock)['inputLockSha256'],
                                 x11.identity(selected_lock)['sha256'])
                with self.assertRaisesRegex(ValueError, 'bridge-build-input-lock'):
                    x11.build_identity(payload, revision, package)
                for key, wrong in (('runtimeArchiveSha256', old), ('architecture', 'x64'), ('formatVersion', True),
                                   ('scope', 'unbound-build')):
                    selected_lock.write_text(json.dumps(dict(selected, **{key: wrong}))); record(candidate, selected_lock)
                    with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'bridge-input-runtime-pin-mismatch'):
                        x11.build_identity(payload, revision, package, selected_lock)

    def test_cli_passes_selected_paths_and_preserves_default_lock_selection(self):
        args = ['qualify_x11_input.py', '--runtime', '/runtime', '--bridge-dir', '/bridge',
                '--bridge-revision', 'a' * 40, '--output', '/output']
        with patch.object(sys, 'argv', args), patch.object(x11, 'qualify') as qualify:
            self.assertEqual(x11.main(), 0)
            self.assertEqual(qualify.call_args.args[-3:], (None, None, None))
        args += ['--runtime-lock', '/candidate.json', '--x11-runtime-lock', '/x11.json',
                 '--bridge-input-lock', '/bridge.json']
        with patch.object(sys, 'argv', args), patch.object(x11, 'qualify') as qualify:
            self.assertEqual(x11.main(), 0)
            self.assertEqual(qualify.call_args.args[-3:], (Path('/candidate.json'), Path('/x11.json'), Path('/bridge.json')))

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
