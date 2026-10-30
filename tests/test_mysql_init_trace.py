import json
import os
from pathlib import Path
import select
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import mysql_init_trace as trace


class MySQLInitializationTrace(unittest.TestCase):
    def parser(self, root):
        return trace.FileCallParser(root, root / 'database-initializing', root / 'run/initialize-tmp')

    def test_known_failed_calls_escaped_paths_and_fd_annotations_are_redacted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parser = self.parser(root)
            stage = root / 'database-initializing'
            private = 'credential-never-public-secret'
            lines = [
                f'112 openat(AT_FDCWD, "{stage}/{private}", O_RDONLY) = -1 EACCES (Permission denied)',
                f'[pid 113] mkdir("{root}/run/initialize-tmp", 0700) = -1 EEXIST (File exists)',
                f'114 getdents64(4<{stage}>, 0xffff, 32768) = -1 EIO (Input/output error)',
                f'115 newfstatat(5<{root}>, "a\\054{private}", 0xffff, 0) = -1 ENOENT (No such file)',
                f'116 openat(6<{stage}>, "..\\057outside", O_RDONLY) = -1 ENOTDIR (Not directory)',
                '117 access("relative-secret", F_OK) = -1 ENOENT (No such file)',
                '118 readlink("/foreign/secret", 0xffff, 4096) = -1 EINVAL (Invalid argument)',
                '119 chdir(NULL) = -1 EACCES (Permission denied)',
                '120 execve("/private/secret", ["password", "SQL SECRET"], 0xffff) = -1 EACCES (denied)',
                '121 openat(AT_FDCWD, "/private/secret", O_RDONLY) = -1 EUNKNOWN (unknown)',
                '122 openat(AT_FDCWD, "/private/secret", O_RDONLY) = 3</private/secret>',
            ]
            raw = ('\n'.join(lines) + '\n').encode()
            for start in range(0, len(raw), 7):
                parser.feed(raw[start:start + 7])
            rows = parser.finish()
            public = json.dumps([row.as_dict() for row in rows])
            self.assertEqual(len(rows), 8)
            self.assertEqual(rows[0], trace.FailedFileCall('openat', 'EACCES', 'owned-staging-datadir'))
            self.assertIn(trace.FailedFileCall('getdents64', 'EIO', 'owned-staging-datadir'), rows)
            self.assertIn(trace.FailedFileCall('newfstatat', 'ENOENT', 'owned-state'), rows)
            self.assertIn(trace.FailedFileCall('openat', 'ENOTDIR', 'owned-state'), rows)
            self.assertIn(trace.FailedFileCall('access', 'ENOENT', 'relative-path'), rows)
            self.assertIn(trace.FailedFileCall('chdir', 'EACCES', 'not-reported'), rows)
            for secret in (temporary, private, 'relative-secret', '/foreign', 'password', 'SQL SECRET', '112', 'execve'):
                self.assertNotIn(secret, public)

    def test_owned_failures_rank_before_loader_noise_and_rows_are_fixed_bounded(self):
        root = Path('/owned/private')
        parser = self.parser(root)
        for syscall in trace.SYSCALLS:
            for error in trace.ERRNOS:
                parser.feed(f'{syscall}("/loader/secret", O_RDONLY) = -1 {error} (private text)\n'.encode())
        parser.feed(b'getdents64(7</owned/private/database-initializing>, 0, 32768) = -1 EACCES (denied)\n')
        parser.feed(b'mkdir("/owned/private/run/initialize-tmp/a", 0700) = -1 EROFS (denied)\n')
        rows = parser.finish()
        self.assertEqual(len(rows), trace.PUBLIC_ROW_LIMIT)
        self.assertEqual(rows[0], trace.FailedFileCall('getdents64', 'EACCES', 'owned-staging-datadir'))
        self.assertEqual(rows[1], trace.FailedFileCall('mkdir', 'EROFS', 'owned-initialization-tmpdir'))
        self.assertLessEqual(len(parser.rows), len(trace.SYSCALLS) * len(trace.ERRNOS) * len(trace.ROLES))
        for row in rows:
            self.assertIn(row.syscall, trace.SYSCALLS)
            self.assertIn(row.errno, trace.ERRNOS)
            self.assertIn(row.path_role, trace.ROLES)

    def test_malformed_oversize_and_unknown_calls_cannot_export_text_or_grow_fragment(self):
        parser = self.parser(Path('/owned/private'))
        parser.feed(b'x' * (trace.LINE_LIMIT * 3))
        self.assertEqual(parser.pending, b'')
        self.assertTrue(parser.line_truncated)
        parser.feed(b'\nopenat(AT_FDCWD, "relative", O_RDONLY) = -1 ENOENT (text)\n')
        for raw in (
                b'openat(AT_FDCWD, "unterminated, O_RDONLY) = -1 EACCES (text)\n',
                b'openat(AT_FDCWD, "__import__(\\"os\\").system(\\"secret\\")", O_RDONLY) = -1 EPERM (text)\n',
                b'openat(AT_FDCWD, "\\x00/secret", O_RDONLY) = -1 EROFS (text)\n',
                b'unknown("secret") = -1 EACCES (text)\n',
                b'execve("/secret", ["credential"], 0) = -1 EACCES (text)\n',
                b'openat(AT_FDCWD, "/secret"..., O_RDONLY) = -1 EUNKNOWN (text)\n'):
            parser.feed(raw)
        public = json.dumps([row.as_dict() for row in parser.finish()])
        for value in ('secret', 'credential', '__import__', 'unknown', 'EUNKNOWN'):
            self.assertNotIn(value, public)

    def test_diagnose_uses_only_fresh_separate_state_and_real_initialization_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            engine = Path(sys.executable).resolve()
            expected = trace.TraceReceipt(True, 7, False, True, True, False, False, False, 0, 0, ())
            with patch.object(trace, '_require_namespace'), patch.object(trace, '_run_owned', return_value=expected) as run:
                result = trace.diagnose(engine, parent)
            self.assertIs(result, expected)
            command, root, log, parser = run.call_args.args
            self.assertEqual(command[:10], ['/usr/bin/strace', '-f', '-yy', '-s', '4096', '-e',
                'trace=%file,getdents64', '-o', '/proc/self/fd/1', str(engine)])
            self.assertEqual(root, parent / 'mysql-initialization-trace')
            self.assertEqual(log, root / 'initialization-file-trace.log')
            self.assertIn('--initialize-insecure', command)
            self.assertIn('--skip-networking', command)
            self.assertIn('--datadir=' + str(root / 'database-initializing'), command)
            self.assertIn('--tmpdir=' + str(root / 'run/initialize-tmp'), command)
            self.assertEqual(run.call_args.kwargs, {'timeout': 180})
            for directory in (root, root / 'database-initializing', root / 'run', root / 'run/initialize-tmp'):
                self.assertTrue(directory.is_dir())
                self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertEqual(set(parent.iterdir()), {root})
            with patch.object(trace, '_require_namespace'), patch.object(trace, '_run_owned') as run, self.assertRaises(trace.TraceError):
                trace.diagnose(engine, parent)
            run.assert_not_called()

    def test_existing_diagnostic_file_link_or_directory_is_preserved_without_launch(self):
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'mysql-initialization-trace'
                if kind == 'file': path.write_bytes(b'preserved')
                elif kind == 'directory': path.mkdir()
                else: path.symlink_to(root / 'unavailable')
                with patch.object(trace, '_require_namespace'), patch.object(trace, '_run_owned') as run, self.assertRaises(trace.TraceError):
                    trace.diagnose(Path(sys.executable).resolve(), root)
                run.assert_not_called()
                self.assertTrue(path.exists() or path.is_symlink())
                if kind == 'file': self.assertEqual(path.read_bytes(), b'preserved')

    def test_parent_must_be_private_owned_directory_and_cannot_be_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parent = root / 'parent'; parent.mkdir(mode=0o755)
            with patch.object(trace, '_require_namespace'), self.assertRaises(trace.TraceError):
                trace.diagnose(Path(sys.executable).resolve(), parent)
            parent.chmod(0o700)
            link = root / 'link'; link.symlink_to(parent)
            with patch.object(trace, '_require_namespace'), self.assertRaises(trace.TraceError):
                trace.diagnose(Path(sys.executable).resolve(), link)
            self.assertFalse((parent / 'mysql-initialization-trace').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned process-group API')
    def test_real_owned_nonzero_runner_has_private_prefix_and_safe_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = f'getdents64(4<{root}/database-initializing>, 0, 4096) = -1 EACCES (PRIVATE SECRET)\n'
            source = 'import os,sys\n' + f'os.write(1, {raw.encode()!r})\n' + 'raise SystemExit(7)\n'
            receipt = trace._run_owned([sys.executable, '-c', source], root, root / 'trace.log',
                                      self.parser(root), timeout=5)
            self.assertEqual(receipt.exit_code, 7)
            self.assertTrue(receipt.process_group_cleaned)
            self.assertTrue(receipt.capture_drained)
            self.assertEqual((root / 'trace.log').read_text(), raw)
            self.assertEqual(stat.S_IMODE((root / 'trace.log').stat().st_mode), 0o600)
            public = receipt.as_dict()
            self.assertTrue(public['traceComplete'])
            self.assertFalse(public['qualificationSucceeded'])
            self.assertFalse(public['tracedInitializationSucceeded'])
            for key in ('sqlAuthenticated', 'sqlQualified', 'accountQualified', 'protocolQualified',
                        'androidRuntimeQualified', 'gameplayQualified'):
                self.assertIs(public[key], False)
            self.assertNotIn(temporary, json.dumps(public))
            self.assertNotIn('PRIVATE SECRET', json.dumps(public))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned process-group API')
    def test_prefix_truncation_keeps_draining_and_observes_late_owned_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = f'\nmkdir("{root}/database-initializing", 0700) = -1 EEXIST (File exists)\n'.encode()
            source = ('import os\n' + f'os.write(1, b"x" * {trace.LOG_LIMIT + 65536})\n'
                      + f'os.write(1, {raw!r})\n')
            receipt = trace._run_owned([sys.executable, '-c', source], root, root / 'trace.log',
                                      self.parser(root), timeout=5)
            self.assertEqual(receipt.exit_code, 0)
            self.assertEqual(receipt.bytes_captured, trace.LOG_LIMIT)
            self.assertEqual((root / 'trace.log').stat().st_size, trace.LOG_LIMIT)
            self.assertGreater(receipt.bytes_observed, trace.LOG_LIMIT)
            self.assertTrue(receipt.trace_truncated)
            self.assertTrue(receipt.capture_drained)
            self.assertIn(trace.FailedFileCall('mkdir', 'EEXIST', 'owned-staging-datadir'), receipt.failed_file_calls)
            self.assertFalse(receipt.as_dict()['traceComplete'])
            self.assertFalse(receipt.as_dict()['tracedInitializationSucceeded'])

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'pidfd_open'), 'Linux pidfd observation')
    def test_timeout_kills_descendant_before_leader_reap_and_drains_pipe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            ready = root / 'descendant'
            source = ('import os,signal,time,pathlib\n'
                'read,write=os.pipe()\n'
                'if os.fork()==0:\n'
                ' os.close(read);signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                f' pathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n'
                ' os.write(write,b"1");os.close(write)\n'
                ' while True:time.sleep(.05)\n'
                'os.close(write);os.read(read,1);os.close(read)\n')
            handles = []
            original = trace.OwnedGroup.stop
            def stop(group, **kwargs):
                # Observe the descendant before the owner kills its group. Some
                # hosts reap an orphan immediately after it dies.
                self.assertIsNone(group.process.returncode)
                handles.append(os.pidfd_open(int(ready.read_text())))
                self.assertEqual(select.select(handles, [], [], 0)[0], [])
                return original(group, **kwargs)
            with patch.object(trace.OwnedGroup, 'stop', stop):
                receipt = trace._run_owned([sys.executable, '-c', source], root, root / 'trace.log',
                                          self.parser(root), timeout=.3)
            self.assertTrue(ready.is_file())
            self.assertTrue(receipt.timed_out)
            self.assertTrue(receipt.process_group_cleaned)
            self.assertTrue(receipt.capture_drained)
            self.assertFalse(receipt.as_dict()['traceComplete'])
            try:
                self.assertEqual(select.select(handles, [], [], 5)[0], handles)
            finally:
                for descriptor in handles:
                    os.close(descriptor)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned process-group API')
    def test_write_failure_still_drains_and_cleans_group_without_raw_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = f'import os\nos.write(1, b"x" * {trace.LOG_LIMIT + 65536})\n'
            with patch.object(trace.os, 'write', side_effect=OSError('PRIVATE PATH PASSWORD')):
                receipt = trace._run_owned([sys.executable, '-c', source], root, root / 'trace.log',
                                          self.parser(root), timeout=5)
            self.assertTrue(receipt.capture_failed)
            self.assertTrue(receipt.capture_drained)
            self.assertTrue(receipt.process_group_cleaned)
            self.assertGreater(receipt.bytes_observed, trace.LOG_LIMIT)
            self.assertNotIn('PASSWORD', json.dumps(receipt.as_dict()))

    def test_explicit_environment_and_launch_options_never_set_data_file_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(trace.subprocess, 'Popen', side_effect=OSError('private launch failure')) as start:
                receipt = trace._run_owned(['/not-run', 'secret'], root, root / 'trace.log', self.parser(root))
            self.assertFalse(receipt.started)
            self.assertTrue(receipt.capture_failed)
            kwargs = start.call_args.kwargs
            self.assertEqual(kwargs['env'], {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                'LC_ALL': 'C.UTF-8', 'MYSQL_TEST_LOGIN_FILE': os.devnull})
            self.assertEqual(kwargs['umask'], 0o077)
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual(kwargs['stdin'], trace.subprocess.DEVNULL)
            self.assertNotIn('preexec_fn', kwargs)
            self.assertNotIn('private launch failure', json.dumps(receipt.as_dict()))

    def test_namespace_guard_runs_before_filesystem_or_launch(self):
        for pid, uid, marker in ((2, 0, '1'), (1, 1, '1'), (1, 0, ''), (1, 0, 'true')):
            with self.subTest(pid=pid, uid=uid, marker=marker), \
                    patch.object(trace.os, 'getpid', return_value=pid), \
                    patch.object(trace.os, 'geteuid', return_value=uid), \
                    patch.dict(trace.os.environ, {'ESTERIA_AUTH_NAMESPACE': marker}), \
                    patch.object(trace.db, 'private_path') as paths, \
                    patch.object(trace.subprocess, 'Popen') as start:
                with self.assertRaisesRegex(trace.TraceError, 'owned root authentication namespace'):
                    trace.diagnose(Path('/unread-engine'), Path('/unread-parent'))
                paths.assert_not_called()
                start.assert_not_called()
        with patch.object(trace.os, 'getpid', return_value=1), \
                patch.object(trace.os, 'geteuid', return_value=0), \
                patch.dict(trace.os.environ, {'ESTERIA_AUTH_NAMESPACE': '1'}):
            trace._require_namespace()

    @unittest.skipUnless(sys.platform == 'linux', 'Linux owned process-group API')
    def test_owner_factory_failure_still_uses_validated_owner_for_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(trace, 'OwnedGroup', side_effect=RuntimeError('private factory failure')):
                receipt = trace._run_owned([sys.executable, '-c', 'print("private output")'],
                    root, root / 'trace.log', self.parser(root), timeout=5)
            self.assertTrue(receipt.started)
            self.assertTrue(receipt.capture_failed)
            self.assertTrue(receipt.process_group_cleaned)
            self.assertTrue(receipt.capture_drained)
            self.assertNotIn('private', json.dumps(receipt.as_dict()))


if __name__ == '__main__':
    unittest.main()
