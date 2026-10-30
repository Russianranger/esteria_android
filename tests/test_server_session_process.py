"""Real Linux child/socket/pipe fixtures; these never execute auth/world binaries."""
from pathlib import Path
import os
import socket
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import server_session_process as process


class ServerSessionProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.children = []
        self.addCleanup(self.stop_children)

    def stop_children(self):
        for child in self.children:
            if not child.closed:
                try:
                    child.stop(world_timeout=.1, auth_timeout=.1)
                except (OSError, ValueError):
                    pass

    def script(self, name, body):
        path = self.root / name
        path.write_text('#!/usr/bin/env python3\n' + body)
        path.chmod(0o700)
        return path

    def child(self, program, body):
        index = len(self.children)
        executable = self.script('fixture-' + str(index), body)
        config = self.root / ('config-' + str(index)); config.write_text('TEST_ONLY_NOT_GAME_CONFIG\n')
        child = process.ServerChild(program, executable, config, self.root, self.root / ('log-' + str(index)))
        self.children.append(child)
        return child

    def await_file(self, name):
        deadline = time.monotonic() + 3
        while not (self.root / name).exists():
            self.assertLess(time.monotonic(), deadline, 'Actual child fixture never became ready')
            time.sleep(.01)

    def test_actual_owned_child_listener_inode_and_world_protocol(self):
        child = self.child('authserver', '''import signal,socket,time
signal.signal(signal.SIGTERM,lambda *_:exit(0))
s=socket.socket();s.bind(('127.0.0.1',0));s.listen()
open('port','w').write(str(s.getsockname()[1]))
while True: time.sleep(.05)
''').start()
        self.await_file('port'); port = int((self.root / 'port').read_text())
        try:
            owned = process.owns_loopback_listener(child.group, port)
        except PermissionError:
            self.skipTest('Managed host denies own-child /proc/fd readback; production remains fail-closed')
        if not owned:
            self.skipTest('Managed host child/socket proc projection differs; no actual inode ownership proof claimed')
        with self.assertRaisesRegex(ValueError, 'unexpected IPv4'):
            process.owns_loopback_listener(child.group, port + 1 if port < 65535 else port - 1)
        child.stop(); self.assertTrue(child.closed)
        self.assertEqual(child.process.returncode, 0)

    def test_actual_world_console_processing_challenge_and_shutdown(self):
        child = self.child('worldserver', '''import socket,struct,sys,threading
s=socket.socket();s.bind(('127.0.0.1',0));s.listen()
open('port','w').write(str(s.getsockname()[1]))
def challenge():
 while True:
  c,_=s.accept()
  with c:c.sendall(b'\\x00\\x2a\\xec\\x01'+struct.pack('<I',1)+b'x'*36)
threading.Thread(target=challenge,daemon=True).start()
for line in sys.stdin:
 if line=='server info\\n':
  print('Connected players: 0 Characters in world: 0',flush=True)
  print('Update time diff: 0',flush=True)
 elif line=='server shutdown 1\\n':
  open('world-command','w').write(line)
  raise SystemExit(0)
 else:raise SystemExit(9)
''').start()
        self.await_file('port');port = int((self.root / 'port').read_text())
        # Actual TCP protocol/console fixture only. Owned-inode parsing is
        # independently checked below; this managed host may deny /proc/fd.
        self.assertTrue(process.world_challenge(port))
        before = child.info_counter();child.send_world(process.WORLD_INFO)
        deadline = time.monotonic() + 3
        while child.info_counter() == before:
            self.assertLess(time.monotonic(), deadline);time.sleep(.01)
        child.stop(world_timeout=2)
        self.assertTrue(child.closed and child.world_command_queued)
        self.assertEqual((self.root / 'world-command').read_bytes(), process.WORLD_SHUTDOWN)
        self.assertEqual(child.process.returncode, 0)
        self.assertFalse(child.group.forced)

    def test_proc_parser_binds_only_the_owned_socket_and_rejects_extra_listeners(self):
        child = self.child('authserver', "import signal,time\nsignal.signal(signal.SIGTERM,lambda *_:exit(0))\nopen('started','w').write('TEST_ONLY')\nwhile True:time.sleep(.05)\n").start()
        self.await_file('started')
        # Explicit synthetic proc metadata, not actual inode qualification.
        root = self.root / 'proc' / str(child.process.pid)
        (root / 'fd').mkdir(parents=True);(root / 'net').mkdir()
        (root / 'fd/3').symlink_to('socket:[12345]')
        tcp = root / 'net/tcp';tcp6 = root / 'net/tcp6'
        tcp.write_text('header\n0: 0100007F:0E8C 00000000:0000 0A 0 0 0 0 0 12345\n')
        tcp6.write_text('header\n')
        self.assertTrue(process.owns_loopback_listener(child.group, 3724, proc=self.root / 'proc'))
        tcp.write_text('header\n0: 00000000:0E8C 00000000:0000 0A 0 0 0 0 0 12345\n')
        with self.assertRaisesRegex(ValueError, 'unexpected IPv4'):
            process.owns_loopback_listener(child.group, 3724, proc=self.root / 'proc')
        tcp.write_text('header\n')
        self.assertFalse(process.owns_loopback_listener(child.group, 3724, proc=self.root / 'proc'))
        tcp6.write_text('header\n0: 00000000000000000000000000000000:0E8C 0:0 0A 0 0 0 0 0 12345\n')
        with self.assertRaisesRegex(ValueError, 'unexpected IPv6'):
            process.owns_loopback_listener(child.group, 3724, proc=self.root / 'proc')
        child.stop()

    def test_actual_auth_probe_sends_build12340_challenge_without_proof_or_credentials(self):
        child = self.child('authserver', '''import signal,socket,struct,time
signal.signal(signal.SIGTERM,lambda *_:exit(0))
s=socket.socket();s.bind(('127.0.0.1',0));s.listen()
open('port','w').write(str(s.getsockname()[1]))
c,_=s.accept()
with c:
 packet=b''
 while len(packet)<34:
  packet+=c.recv(34-len(packet))
 length=packet[33]
 while len(packet)<34+length:
  packet+=c.recv(34+length-len(packet))
 assert packet[:2]==b"\\x00\\x00" and struct.unpack_from('<H',packet,11)[0]==12340
 assert length==16 and packet[34:38]==b'ERDY' and packet[34:].isalnum()
 open('challenge-bytes','wb').write(packet)
 c.sendall(b'\\x00\\x00\\x04')
 assert c.recv(1)==b''
 open('no-proof','w').write('TEST_ONLY')
while True:time.sleep(.05)
''').start()
        self.await_file('port');self.assertTrue(process.auth_challenge(int((self.root/'port').read_text())))
        self.await_file('no-proof');self.assertEqual((self.root/'challenge-bytes').stat().st_size,50)
        child.stop();self.assertTrue(child.shutdown_acknowledged)

    def test_start_failure_keeps_actual_child_for_owned_cleanup(self):
        child = self.child('authserver', '''import signal,time
signal.signal(signal.SIGTERM,lambda *_:exit(0))
open('started','w').write('TEST_ONLY')
while True:time.sleep(.05)
''')
        with patch.object(process, 'OwnedGroup', side_effect=ValueError('TEST_ONLY_POST_POPEN_FAILURE')):
            with self.assertRaisesRegex(ValueError, 'POST_POPEN'):
                child.start()
        self.await_file('started')
        self.assertIsNotNone(child.process)
        self.assertFalse(child.closed)
        child.stop();self.assertTrue(child.closed)
        self.assertEqual(child.process.returncode, 0)

    def test_cleanup_failure_keeps_streams_and_known_child_for_retry(self):
        child = self.child('authserver', '''import signal,time
signal.signal(signal.SIGTERM,lambda *_:exit(0))
open('started','w').write('TEST_ONLY')
while True:time.sleep(.05)
''').start()
        self.await_file('started')
        original = child.group.stop
        with patch.object(child.group, 'stop', side_effect=OSError('TEST_ONLY_REAP_REFUSAL')):
            with self.assertRaisesRegex(OSError, 'REAP_REFUSAL'):
                child.stop()
        self.assertFalse(child.closed or child.output.closed or child.process.stdout.closed)
        self.assertTrue(child.alive())
        child.stop();self.assertTrue(child.closed)
        self.assertEqual(child.process.returncode, 0)

    def test_large_actual_child_logs_are_bounded_and_nonzero_not_clean(self):
        child = self.child('authserver', '''import signal,sys,time
signal.signal(signal.SIGTERM,lambda *_:exit(0))
for _ in range(1100):sys.stdout.write('x'*8191+'\\n')
sys.stdout.flush();open('written','w').write('TEST_ONLY')
while True:time.sleep(.05)
''').start()
        self.await_file('written');child.stop()
        self.assertGreater(child.observed, process.LOG_LIMIT)
        self.assertEqual(child.stored, process.LOG_LIMIT)
        self.assertEqual(child.log.stat().st_size, process.LOG_LIMIT)
        failed = self.child('authserver', 'raise SystemExit(7)\n').start()
        deadline = time.monotonic() + 3
        while failed.alive():
            self.assertLess(time.monotonic(), deadline);time.sleep(.01)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            failed.stop()
        self.assertTrue(failed.closed)
        self.assertEqual(failed.process.returncode, 7)

    def test_auth_zero_exit_before_stop_is_not_a_source_signal_acknowledgment(self):
        child = self.child('authserver', "raise SystemExit(0)\n").start()
        deadline = time.monotonic() + 3
        while child.alive():
            self.assertLess(time.monotonic(), deadline);time.sleep(.01)
        with self.assertRaisesRegex(ValueError, 'recovery'):
            child.stop()
        self.assertTrue(child.closed)
        self.assertEqual(child.process.returncode, 0)
        self.assertFalse(child.auth_shutdown_requested or child.shutdown_acknowledged)

    def test_unstarted_owner_closes_without_launch_or_qualification(self):
        child = self.child('worldserver', 'raise SystemExit(99)\n')
        child.stop();self.assertTrue(child.closed)
        self.assertIsNone(child.process)
        with self.assertRaisesRegex(ValueError, 'single-use'):
            child.start()


if __name__ == '__main__':
    unittest.main()
