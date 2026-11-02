"""Real file/child I/O and deterministic Android pacing; fixtures are not game data."""
import hashlib
import os
from pathlib import Path
import sys
import subprocess
import json
import tempfile
import time
import unittest
import io as text_io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime import extractor_order as order, shader_generation as shaders, server_data_generation as data, world_io as io


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []
        self.after_sleep = lambda: None

    def clock(self):
        return self.now

    def sleep(self, delay):
        if not 0 < delay <= .1:
            raise AssertionError('Preparation wait exceeds100ms')
        self.sleeps.append(delay)
        self.now += delay
        self.after_sleep()


class WorldIoTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='world-io-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.clock = Clock()

    def context(self, **kwargs):
        return io.android_policy(clock=self.clock.clock, sleeper=self.clock.sleep,
            memory_probe=kwargs.pop('memory_probe', lambda: 4 << 30), **kwargs)

    def source(self, size=5 << 20):
        path = self.root / 'client.MPQ'
        block = bytes(range(256)) * 512
        with path.open('wb') as output:
            for _ in range(size // len(block)):
                output.write(block)
            output.write(block[:size % len(block)])
        return path

    def test_existing_hash_apis_are_unpaced_without_explicit_android_context(self):
        source = self.source()
        expected = {'bytes': source.stat().st_size, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        with patch.object(io.os, 'posix_fadvise', side_effect=AssertionError('Host default must not use Android cache policy')):
            self.assertEqual(order.file_identity(source), expected)
            self.assertEqual(shaders.identity(source, 8 << 20), expected)
        self.assertFalse(io.enabled())

    def test_owned_adapter_restores_frozen_callables_after_nested_pause(self):
        original = shaders.identity, shaders.execute, order.file_identity
        with self.assertRaises(io.PreparationPaused):
            with self.context():
                self.assertIs(shaders.identity, io.identity)
                self.assertIs(shaders.execute, io.shader_execute)
                self.assertIs(order.file_identity, io.extractor_identity)
                with io.adapt_helpers(cancelled=lambda: True):
                    order.file_identity(self.source())
        self.assertEqual((shaders.identity, shaders.execute, order.file_identity), original)
        self.assertFalse(io.enabled())

    def test_real_hashes_and_source_metadata_match_with2mib_cache_windows(self):
        source = self.source()
        before = source.stat()
        expected = order.file_identity(source)
        calls = []
        native_advice = getattr(os, 'posix_fadvise', None)
        def advice(fd, offset, size, kind):
            self.assertEqual(os.fstat(fd).st_ino, before.st_ino)
            calls.append((offset, size))
            if native_advice is not None:
                native_advice(fd, offset, size, kind)
        with self.context(advice=advice) as policy:
            actual = order.file_identity(source)
            self.assertEqual(policy.read_bytes, 5 << 20)
            self.assertEqual(policy.cache_errors, 0)
        self.assertEqual(actual, expected)
        self.assertEqual(calls, [(0, 2 << 20), (2 << 20, 2 << 20), (4 << 20, 1 << 20)])
        after = source.stat()
        self.assertEqual((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns))
        self.assertAlmostEqual(self.clock.now, 5 / 8, places=6)

    def test_normal_and_pressure_rate_caps_share_budget_across_files(self):
        with self.context() as policy:
            policy.consumed(8 << 20)
            self.assertAlmostEqual(self.clock.now, 1, places=6)
            self.clock.now += 3
            policy.consumed(1 << 20)
            self.assertAlmostEqual(self.clock.now, 4.125, places=6)
        with self.context(memory_probe=lambda: 400 << 20) as policy:
            began = self.clock.now
            policy.consumed(2 << 20)
            self.assertAlmostEqual(self.clock.now - began, 1, places=6)

    def test_explicit_speed_levels_keep_the_same_bounded_hash_and_pressure_backoff(self):
        source = self.source()
        expected = order.file_identity(source)
        for speed, rate in (('gentle', 8 << 20), ('balanced', 32 << 20), ('fast', 64 << 20)):
            with self.subTest(speed=speed):
                began = self.clock.now
                messages = []
                with self.context(speed=speed, progress=messages.append) as policy:
                    self.assertEqual(order.file_identity(source), expected)
                    self.assertEqual(policy.read_bytes, 5 << 20)
                    self.assertEqual(policy.cache_calls, 3, 'Speed does not enlarge cache windows')
                self.assertAlmostEqual(self.clock.now - began, (5 << 20) / rate, places=6)
                observation = json.loads(messages[-1].removeprefix('WORLD_IO '))
                self.assertEqual(observation['speed'], speed)
                self.assertEqual(observation['normalBytesPerSecond'], rate)
                self.assertEqual(observation['nativeAddressSpaceLimitBytes'], 4 << 30)
                began = self.clock.now
                with self.context(speed=speed, memory_probe=lambda: 400 << 20) as policy:
                    policy.consumed(2 << 20)
                self.assertAlmostEqual(self.clock.now - began, 1, places=6)

    def test_guest_environment_selection_is_explicit_and_unknown_speeds_are_refused(self):
        for speed in io.SPEED_RATES:
            with self.subTest(speed=speed), patch.dict(os.environ, {io.SPEED_ENVIRONMENT: speed}):
                with self.context() as policy:
                    self.assertEqual(policy.speed, speed)
                    self.assertEqual(policy.normal_rate, io.SPEED_RATES[speed])
        with patch.dict(os.environ, {io.SPEED_ENVIRONMENT: 'unlimited'}):
            with self.assertRaisesRegex(ValueError, 'Unknown world preparation speed'):
                with self.context():
                    self.fail('Invalid environment choice accepted')
        for speed in ('', 'FAST', '64', ['fast'], 64):
            with self.subTest(speed=speed), self.assertRaisesRegex(ValueError, 'Unknown world preparation speed'):
                with self.context(speed=speed):
                    self.fail('Invalid speed accepted')

    def test_actual_clock_enforces_reduced_hash_rate(self):
        source = self.source(2 << 20)
        began = time.monotonic()
        with io.android_policy(memory_probe=lambda: 4 << 30):
            actual = order.file_identity(source)
        elapsed = time.monotonic() - began
        self.assertGreaterEqual(elapsed, .24)
        self.assertEqual(actual['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux address-space and RSS measurement')
    def test_large_actual_file_hash_stays_below_process_memory_limit(self):
        source = self.root / 'large-sparse.MPQ'
        with source.open('wb') as output:
            output.truncate(256 << 20)
        code = '''import json,resource,sys
from pathlib import Path
from runtime import world_io as io,extractor_order as order
resource.setrlimit(resource.RLIMIT_AS,(96<<20,96<<20))
now=[0.0]
def sleep(delay):now[0]+=delay
with io.android_policy(clock=lambda:now[0],sleeper=sleep,memory_probe=lambda:4<<30) as policy:
    result=order.file_identity(Path(sys.argv[1]))
    status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    result.update(peakRssKiB=int(status['VmHWM'].split()[0]),lifetimeRusageMaxRssKiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,readBytes=policy.read_bytes,cacheCalls=policy.cache_calls,cacheErrors=policy.cache_errors,pacedSeconds=now[0])
print(json.dumps(result))
'''
        run = subprocess.run([sys.executable, '-c', code, str(source)], check=True, capture_output=True, text=True, timeout=30)
        actual = json.loads(run.stdout)
        print('WORLD_IO_HASH_MEASUREMENT=' + json.dumps(actual, sort_keys=True))
        expected = hashlib.sha256()
        block = bytes(1 << 20)
        for _ in range(256):
            expected.update(block)
        self.assertEqual(actual['sha256'], expected.hexdigest())
        self.assertEqual(actual['bytes'], 256 << 20)
        self.assertEqual(actual['readBytes'], 256 << 20)
        self.assertEqual(actual['cacheCalls'], 128)
        self.assertLess(actual['peakRssKiB'], 64 << 10)
        self.assertAlmostEqual(actual['pacedSeconds'], 32, places=5)

    def test_cancel_during_pacing_preserves_source_and_returns_within_one_slice(self):
        source = self.source()
        cancelled = [False]
        self.clock.after_sleep = lambda: cancelled.__setitem__(0, True)
        before = source.read_bytes()
        with self.assertRaisesRegex(io.PreparationPaused, 'cancelled; completed phases'):
            with self.context(cancelled=lambda: cancelled[0]):
                order.file_identity(source)
        self.assertLessEqual(self.clock.now, .1)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(io.enabled())

    def test_native_hash_api_cancellation_remains_active_without_policy(self):
        source = self.source()
        calls = [0]
        def cancelled():
            calls[0] += 1
            return calls[0] >= 2
        with self.assertRaisesRegex(ValueError, 'hashing cancelled'):
            with io.adapt_helpers(cancelled=cancelled):
                order.file_identity(source)
        self.assertEqual(calls[0], 2)

    def test_critical_pressure_recovers_then_times_out_with_resumable_message(self):
        with self.context(memory_probe=lambda: (100 << 20) if self.clock.now < 2 else (4 << 30)) as policy:
            policy.checkpoint()
            self.assertGreaterEqual(self.clock.now, 2)
            self.assertLess(self.clock.now, 2.2)
            self.assertEqual(policy.pressure_waits, 1)
        began = self.clock.now
        with self.assertRaisesRegex(io.PreparationPaused, 'completed phases are retained'):
            with self.context(memory_probe=lambda: 100 << 20) as policy:
                policy.checkpoint()
        self.assertGreaterEqual(self.clock.now - began, 60)
        self.assertLess(self.clock.now - began, 60.2)

    def test_advisory_failure_keeps_correct_hash_and_pacing(self):
        source = self.source()
        def unavailable(*args):
            raise OSError('Fixture advice unavailable')
        with self.context(advice=unavailable) as policy:
            actual = shaders.identity(source, 8 << 20)
            self.assertEqual(policy.cache_errors, 3)
        self.assertEqual(actual, order.file_identity(source))
        self.assertAlmostEqual(self.clock.now, 5 / 8, places=6)

    def test_plan_wire_and_all_hash_fingerprints_are_unchanged(self):
        client = self.root / 'source'
        for name in ('Data/common.MPQ', 'Data/enUS/locale-enUS.MPQ', 'Data/enUS/speech-enUS.MPQ', 'Data/patch.MPQ'):
            path = client / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('fixture:' + name).encode())
        expected = order.plan(client, 'enUS', profile=data.PROFILE)
        with self.context():
            actual = order.plan(client, 'enUS', profile=data.PROFILE)
        self.assertEqual(actual, expected)
        self.assertEqual(order.wire(actual), order.wire(expected))

    def test_native_child_repeated_cache_relief_keeps_hash_and_source_bytes(self):
        source = self.source(2 << 20)
        before = source.stat()
        expected = hashlib.sha256(source.read_bytes()).hexdigest()
        calls = []
        def advice(fd, offset, size, kind):
            calls.append((offset, size, os.fstat(fd).st_ino))
            os.posix_fadvise(fd, offset, size, kind)
        code = 'import hashlib,pathlib,sys,time;p=pathlib.Path(sys.argv[1]);print(hashlib.sha256(p.read_bytes()).hexdigest(),flush=True);time.sleep(.45)'
        began = time.monotonic()
        with io.android_policy(memory_probe=lambda: 4 << 30, advice=advice):
            result = data.execute([sys.executable, '-c', code, str(source)], self.root,
                self.root / 'native.log', 5, cache_inputs=(source, source))
        self.assertEqual(result['exitStatus'], 0)
        self.assertIn(expected, (self.root / 'native.log').read_text())
        self.assertGreaterEqual(len(calls), 2)
        self.assertLessEqual(len(calls), int(time.monotonic() - began) + 2,
            'Healthy native inputs are advised once per second plus entry/exit, not every100ms')
        self.assertTrue(all(row == (0, 2 << 20, before.st_ino) for row in calls))
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), expected)
        self.assertEqual(source.stat().st_mtime_ns, before.st_mtime_ns)

    def test_native_cache_rotates_bounded_windows_without_whole_archive_repeats(self):
        paths, calls = [], []
        for name in ('common', 'patch', 'locale'):
            path = self.root / (name + '.MPQ')
            with path.open('wb') as stream:
                stream.truncate(10 << 20)
            paths.append(path)
        def advice(fd, offset, length, kind):
            calls.append((os.fstat(fd).st_ino, offset, length))
        with self.context(advice=advice) as policy:
            with io.native_inputs(paths) as guard:
                first = len(calls)
                self.assertGreater(first, 0)
                self.assertLessEqual(first, 4)
                self.assertLessEqual(sum(row[2] for row in calls), 8 << 20)
                self.assertTrue(all(0 < row[2] <= 2 << 20 for row in calls))
                for _ in range(9):
                    self.clock.now += .1
                    guard.tick()
                self.assertEqual(len(calls), first, 'Healthy ticks keep useful cache between batches')
                self.clock.now = 1
                guard.tick()
                self.assertGreater(len(calls), first)
                self.assertLessEqual(len(calls), first + 4)
                self.assertEqual(len({row[0] for row in calls}), 3, 'All archive descriptors rotate fairly')
                self.assertEqual(len(set(calls)), len(calls), 'Offsets advance rather than repeatedly dropping whole inputs')
                self.assertTrue(all(0 < row[2] <= 2 << 20 and row[1] + row[2] <= 10 << 20 for row in calls))
                self.assertLessEqual(policy.cache_bytes, 16 << 20)

    def test_native_advice_pressure_keeps_batches_bounded_and_checks_cancel_between_them(self):
        source = self.source()
        calls, cancelled = [], [False]
        def advice(fd, offset, length, kind):
            calls.append((offset, length))
        with self.context(advice=advice, cancelled=lambda: cancelled[0], memory_probe=lambda: 400 << 20):
            with io.native_inputs((source,)) as guard:
                first = len(calls)
                self.assertLessEqual(first, 4)
                self.assertLessEqual(sum(row[1] for row in calls), 8 << 20)
                self.clock.now = .1
                guard.tick()
                self.assertGreater(len(calls), first)
                self.assertLessEqual(len(calls) - first, 4)
                cancelled[0] = True
                with self.assertRaisesRegex(io.PreparationPaused, 'cancelled'):
                    guard.tick()
                cancelled[0] = False

    def test_native_cache_tiny_inputs_get_no_duplicate_advice_in_one_batch(self):
        source = self.source(1)
        calls = []
        with self.context(advice=lambda fd, offset, length, kind: calls.append((offset, length))):
            with io.native_inputs((source, source)) as guard:
                self.assertEqual(calls, [(0, 1)])
                self.assertEqual(len(guard.files), 1)

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux resource limit and exec contract')
    def test_guarded_child_has4gib_limit_with_exact_argv_cwd_environment_and_clean_stdout(self):
        import resource
        inherited_hard = resource.getrlimit(resource.RLIMIT_AS)[1]
        expected_limit = io.NATIVE_ADDRESS_SPACE_BYTES if inherited_hard == resource.RLIM_INFINITY else min(inherited_hard, io.NATIVE_ADDRESS_SPACE_BYTES)
        arguments = ['literal ; with spaces', '$(literal)', '雪']
        code = 'import json,os,resource,sys;print(json.dumps(dict(limit=resource.getrlimit(resource.RLIMIT_AS),argv=sys.argv[1:],cwd=os.getcwd(),marker=os.environ["ESTERIA_WORLD_IO_FIXTURE"])))'
        log = self.root / 'guarded.log'
        with patch.dict(os.environ, {'ESTERIA_WORLD_IO_FIXTURE': 'fixture literal value'}):
            with io.android_policy(memory_probe=lambda: 4 << 30):
                result = data.execute([sys.executable, '-c', code, *arguments], self.root, log, 5)
        self.assertEqual(result['exitStatus'], 0)
        lines = log.read_text().splitlines()
        self.assertEqual(len(lines), 1, 'Exec guard emits no capability-breaking stdout')
        facts = json.loads(lines[0])
        self.assertEqual(facts, dict(limit=[expected_limit, expected_limit], argv=arguments,
            cwd=str(self.root), marker='fixture literal value'))

    @unittest.skipUnless(sys.platform.startswith('linux'), 'Linux resource limit and child reaping')
    def test_guarded_oversized_allocation_fails_without_kill_and_child_is_reaped(self):
        code = '''import json,os,sys
print(json.dumps(dict(pid=os.getpid())),flush=True)
try:
    value=bytearray(5<<30)
except MemoryError:
    print('EXPECTED_MEMORY_LIMIT',flush=True)
    raise SystemExit(27)
raise SystemExit('Oversized allocation escaped the preparation limit')
'''
        log = self.root / 'allocation.log'
        with io.android_policy(memory_probe=lambda: 4 << 30):
            with self.assertRaisesRegex(ValueError, 'extractor failed'):
                data.execute([sys.executable, '-c', code], self.root, log, 5)
        lines = log.read_text().splitlines()
        self.assertEqual(lines[1], 'EXPECTED_MEMORY_LIMIT')
        pid = json.loads(lines[0])['pid']
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_transient_child_exit_propagates_through_data_and_shader_supervisors(self):
        command = [sys.executable, '-c', 'raise SystemExit(75)']
        with self.assertRaises(io.PreparationPaused):
            data.execute(command, self.root, self.root / 'data-paused.log', 5)
        with self.assertRaises(io.PreparationPaused):
            io.shader_execute(command, self.root / 'shader-paused.log', 5)

    def test_nonzero_child_cause_reaches_bounded_parent_error_and_child_is_reaped(self):
        code = '''import json,os,sys
print(json.dumps(dict(pid=os.getpid())),flush=True)
sys.stdout.write('x'*30000);sys.stdout.flush()
sys.stderr.write('\\nFIXTURE_NATIVE_BAD_ALLOC_CAUSE\\n');sys.stderr.flush()
raise SystemExit(23)
'''
        for role in ('data', 'shader'):
            log = self.root / (role + '-failure.log')
            with self.subTest(role=role), self.assertRaises(ValueError) as caught:
                if role == 'data':
                    data.execute([sys.executable, '-c', code], self.root, log, 5)
                else:
                    io.shader_execute([sys.executable, '-c', code], log, 5)
            message = str(caught.exception)
            self.assertIn('FIXTURE_NATIVE_BAD_ALLOC_CAUSE', message)
            self.assertIn('exitStatus=23', message)
            self.assertIn('worker=' + ('preparation-child' if role == 'data' else 'shader-translator'), message)
            self.assertLessEqual(len(message.encode()), 8500)
            pid = json.loads(log.read_text().splitlines()[0])['pid']
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_pause_child_error_text_is_not_relayed_as_a_permanent_failure(self):
        code = 'import sys;print("FIXTURE_PRIVATE_PAUSE_DETAIL",file=sys.stderr);raise SystemExit(75)'
        for role in ('data', 'shader'):
            log = self.root / (role + '-private-paused.log')
            with self.subTest(role=role), self.assertRaises(io.PreparationPaused) as caught:
                if role == 'data':
                    data.execute([sys.executable, '-c', code], self.root, log, 5)
                else:
                    io.shader_execute([sys.executable, '-c', code], log, 5)
            self.assertNotIn('FIXTURE_PRIVATE_PAUSE_DETAIL', str(caught.exception))

    def test_transient_cli_outcome_is75_and_marker_never_echoes_exception_details(self):
        from runtime import stock_shader_generation as stock_shaders
        arguments = ['helper', '--store', str(self.root / 'store'), '--game', str(self.root / 'game'),
            '--tools', str(self.root / 'tools'), '--generation', 'a' * 64, '--locale', 'enUS']
        for module in (data, stock_shaders):
            argv = arguments + (['--selection', str(self.root / 'selection.json')] if module is data
                else ['--client-revision', 'b' * 40])
            stderr, stdout = text_io.StringIO(), text_io.StringIO()
            with patch.object(sys, 'argv', argv), patch.object(module, 'generate',
                    side_effect=io.PreparationPaused('FIXTURE_PRIVATE_DETAIL_NEVER_ECHO')), \
                    redirect_stderr(stderr), redirect_stdout(stdout):
                if module is data:
                    with patch.object(data, 'document', return_value={}):
                        result = module.main()
                else:
                    result = module.main()
            self.assertEqual(result, io.PAUSED_EXIT_CODE)
            self.assertEqual(stdout.getvalue(), '')
            self.assertIn('ESTERIA_PREPARATION_PAUSED', stderr.getvalue())
            self.assertNotIn('FIXTURE_PRIVATE_DETAIL', stderr.getvalue())
            self.assertLess(len(stderr.getvalue()), 256)

    def test_critical_pressure_stops_and_reaps_running_native_child_without_parent_wait(self):
        began = time.monotonic()
        probe = lambda: (4 << 30) if time.monotonic() - began < .3 else (100 << 20)
        code = 'import json,os,time;print(json.dumps(dict(pid=os.getpid())),flush=True);time.sleep(30)'
        log = self.root / 'critical.log'
        with io.android_policy(memory_probe=probe) as policy:
            with self.assertRaisesRegex(io.PreparationPaused, 'native operation is stopped'):
                data.execute([sys.executable, '-c', code], self.root, log, 10)
            self.assertEqual(policy.native_pressure_aborts, 1)
        self.assertLess(time.monotonic() - began, 5, 'Parent must stop the child rather than wait60seconds while it runs')
        pid = json.loads(log.read_text().splitlines()[0])['pid']
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_native_cache_guard_refuses_symlinks_and_closes_all_owned_descriptors(self):
        source = self.source()
        linked = self.root / 'linked.MPQ'
        linked.symlink_to(source)
        with self.context():
            with self.assertRaisesRegex(ValueError, 'Canonical native cache'):
                with io.native_inputs((source, linked)):
                    self.fail('Linked native input accepted')
            with io.native_inputs((source,)) as guard:
                fd = guard.files[0][0]
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_fallback_copy_forces_each_output_window_before_cache_advice(self):
        source = self.source()
        output = self.root / 'copy.bin'
        real_sync = os.fdatasync
        synced = []
        destination_fd = [None]
        def sync(fd):
            real_sync(fd)
            if fd == destination_fd[0]:
                synced.append(fd)
        output_releases = []
        def advice(fd, offset, size, kind):
            if fd == destination_fd[0]:
                self.assertGreater(len(synced), len(output_releases))
                output_releases.append((offset, size))
        with self.context(advice=advice), patch.object(io.os, 'fdatasync', side_effect=sync):
            with source.open('rb') as incoming, output.open('xb') as outgoing:
                destination_fd[0] = outgoing.fileno()
                io.copy_stream(incoming, outgoing)
        self.assertEqual(output_releases, [(0, 2 << 20), (2 << 20, 2 << 20), (4 << 20, 1 << 20)])
        self.assertEqual(output.read_bytes(), source.read_bytes())


if __name__ == '__main__':
    unittest.main()
