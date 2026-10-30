import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools.owned_process_group import OwnedGroup


@unittest.skipUnless(sys.platform == 'linux', 'Linux WNOWAIT process ownership')
class OwnedProcessGroups(unittest.TestCase):
    def start(self, source):
        process = subprocess.Popen([sys.executable, '-c', source], start_new_session=True,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        group = OwnedGroup(process)
        self.addCleanup(group.stop, .1)
        return group

    def test_natural_exit_keeps_identity_until_cleanup_and_stop_is_idempotent(self):
        group = self.start('raise SystemExit(7)')
        self.assertEqual(group.wait(5), 7)
        self.assertIsNone(group.process.returncode)
        original = os.killpg
        def checked(pid, number):
            self.assertEqual(pid, group.process.pid)
            self.assertEqual(number, signal.SIGKILL)
            self.assertIsNone(group.process.returncode)
            observed = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            self.assertEqual(observed.si_status, 7)
            return original(pid, number)
        with patch('tools.owned_process_group.os.killpg', side_effect=checked) as kill:
            self.assertEqual(group.stop(), (7, False))
            self.assertEqual(group.stop(), (7, False))
            self.assertEqual(kill.call_count, 1)
        self.assertEqual(group.process.returncode, 7)
        with self.assertRaises(ChildProcessError):
            os.waitid(os.P_PID, group.process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)

    def test_timeout_does_not_reap_and_graceful_stop_waits_for_real_zero_exit(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'ready'
            group = self.start('import signal,time,pathlib,sys\n'
                'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))\n'
                f'pathlib.Path({str(ready)!r}).write_text("ready")\n'
                'while True:time.sleep(.05)\n')
            self.wait_file(ready)
            with self.assertRaises(subprocess.TimeoutExpired): group.wait(.02)
            self.assertIsNone(group.process.returncode)
            self.assertEqual(group.stop(.5), (0, False))

    def test_ignored_term_is_forced_and_actual_nonzero_exit_is_observed(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'ready'
            group = self.start('import signal,time,pathlib\n'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                f'pathlib.Path({str(ready)!r}).write_text("ready")\n'
                'while True:time.sleep(.05)\n')
            self.wait_file(ready)
            self.assertEqual(group.stop(.02), (-signal.SIGKILL, True))

    @unittest.skipUnless(hasattr(os, 'pidfd_open'), 'pidfd observation required')
    def test_exited_leader_descendant_is_killed_before_leader_reap(self):
        with tempfile.TemporaryDirectory() as temporary:
            ready = Path(temporary) / 'ready'
            group = self.start('import os,signal,time,pathlib\n'
                'read,write=os.pipe()\n'
                'if os.fork()==0:\n'
                ' os.close(read);signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                f' pathlib.Path({str(ready)!r}).write_text(str(os.getpid()))\n'
                ' os.write(write,b"1");os.close(write)\n'
                ' while True:time.sleep(.05)\n'
                'os.close(write);os.read(read,1);os.close(read)\n')
            self.assertEqual(group.wait(5), 0)
            descriptor = os.pidfd_open(int(ready.read_text()))
            try:
                self.assertEqual(select.select([descriptor], [], [], 0)[0], [])
                self.assertEqual(group.stop(), (0, False))
                self.assertEqual(select.select([descriptor], [], [], 5)[0], [descriptor])
            finally: os.close(descriptor)

    def test_external_reap_refuses_any_pid_or_group_signal(self):
        group = self.start('raise SystemExit(0)')
        self.assertEqual(group.process.wait(timeout=5), 0)
        # Deliberately violate the ownership API; cleanup must never guess whether
        # that numeric PID now names a different group.
        with patch('tools.owned_process_group.os.killpg') as kill:
            with self.assertRaisesRegex(ValueError, 'reaped outside'):
                group.stop()
            kill.assert_not_called()
        group.closed = True  # no remaining child; disable registered cleanup

    def wait_file(self, path):
        deadline = time.monotonic() + 5
        while not path.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)


if __name__ == '__main__': unittest.main()
