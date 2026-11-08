"""Real Linux sockets, unprivileged child filter and exec/descriptor ownership."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import server_session, server_session_process as processes
from runtime import server_activation as activation


class ActivatedServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.configuration = self.root / 'server.conf'
        self.configuration.write_text('Network.UseSocketActivation = 0\n')
        self.child = None
        self.addCleanup(self.stop)

    def stop(self):
        if self.child is not None and not self.child.closed:
            try:
                self.child.stop(auth_timeout=.3, world_timeout=.3)
            except ValueError:
                pass

    def launch(self, body):
        program = self.root / 'authserver'
        program.write_text('#!' + sys.executable + '\n' +
                           "import os;from pathlib import Path;Path('proc-pid').write_text(os.readlink('/proc/self'))\n" + body)
        program.chmod(0o700)
        self.child = processes.ServerChild('authserver', program, self.configuration,
            self.root, self.root / 'log', activate=True)
        self.child.start()

    def map_test_proc(self):
        # Some managed hosts mount an outer PID namespace's procfs. Only the
        # fixture maps its own kernel-exported PID into the local test view.
        outer_pid = (self.root / 'proc-pid').read_text()
        if outer_pid == str(self.child.process.pid):
            return
        proc = self.root / 'proc'
        proc.mkdir()
        (proc / str(self.child.process.pid)).symlink_to(Path('/proc') / outer_pid)
        self.child.owns_listener = lambda port: self.child.listener.owns(self.child.group, port, proc)

    def await_guard(self):
        self.map_test_proc()
        deadline = time.monotonic() + 5
        while not self.child.owns_listener(3724):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)

    @unittest.skipUnless(sys.platform == 'linux' and os.uname().machine in ('aarch64','x86_64'),
                         'qualified Linux seccomp ABI required')
    def test_guarded_real_grunt_and_all_denied_listener_routes(self):
        self.launch("""import errno, os, signal, socket, struct, time
from pathlib import Path
assert os.environ['LISTEN_FDS'] == '1' and int(os.environ['LISTEN_PID']) == os.getpid()
assert os.environ['AC_NETWORK_USE_SOCKET_ACTIVATION'] == '1'
listener=socket.socket(fileno=3)
assert listener.getsockname() == ('127.0.0.1',3724)
listener.listen()
def denied(action):
 try: action()
 except OSError as ex:
  assert ex.errno == errno.EPERM, ex
 else: raise AssertionError('operation unexpectedly permitted')
for family,endpoint in [(socket.AF_INET,('0.0.0.0',0)),(socket.AF_INET6,('::',0))]:
 s=socket.socket(family); denied(lambda:s.bind(endpoint)); denied(s.listen)
 assert not s.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN); s.close()
denied(lambda:socket.socket(socket.AF_UNIX))
dupe=os.dup(3)
with socket.socket(fileno=dupe) as alias: denied(alias.listen)
# Substituting a different fd at 3 cannot turn it into a listening socket.
saved=os.dup(3)
with socket.socket() as rogue:
 os.dup2(rogue.fileno(),3); listener.listen()
 assert listener.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN) == 0
 os.dup2(saved,3)
os.close(saved)
stop=False
def finish(*_):
 global stop
 stop=True
signal.signal(signal.SIGTERM,finish)
Path('guard-tests').touch()
# Prove startup can exceed the old one-second post-listener challenge budget.
time.sleep(1.15)
with listener.accept()[0] as conn:
 packet=conn.recv(50, socket.MSG_WAITALL)
 assert len(packet)==50 and struct.unpack_from('<H',packet,11)[0]==12340
 conn.sendall(b'\\0\\0\\4')
while not stop:time.sleep(.02)
""")
        deadline=time.monotonic()+5
        while not (self.root/'guard-tests').exists():
            self.assertTrue(self.child.alive(), self.child.log.read_text())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        self.await_guard()
        self.assertTrue(server_session.Session._wire_probe(self.child,3724,processes.auth_challenge,
                                                               deadline,lambda:False))
        self.assertTrue(self.child.owns_listener(3724))
        self.child.stop()
        self.assertTrue(self.child.shutdown_acknowledged)
        self.assertEqual(self.child.listener.socket.fileno(),-1)
        self.assertEqual(self.configuration.read_text(),'Network.UseSocketActivation = 0\n')

    def test_fd3_substitution_loses_ownership_before_wire(self):
        self.launch("""import os,signal,socket,time
from pathlib import Path
signal.signal(signal.SIGTERM,lambda *_:exit(0))
s=socket.socket();os.dup2(s.fileno(),3);Path('changed').touch()
while True:time.sleep(.02)
""")
        deadline=time.monotonic()+5
        while not (self.root/'changed').exists():
            self.assertTrue(self.child.alive(), self.child.log.read_text())
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        with self.assertRaisesRegex(ValueError,'descriptor changed'):
            self.await_guard()

    def test_preexisting_foreign_server_prevents_spawn_and_owner_can_stop(self):
        with socket.socket() as foreign:
            foreign.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            foreign.bind(('127.0.0.1',3724));foreign.listen()
            with self.assertRaises(OSError):
                self.launch('raise AssertionError()')
            self.assertIsNone(self.child.process)
            self.child.stop()
            self.assertTrue(self.child.closed)
            self.assertEqual(foreign.getsockopt(socket.SOL_SOCKET,socket.SO_ACCEPTCONN),1)

    def test_spawn_failure_closes_listener_and_ack_descriptors(self):
        with patch.object(subprocess,'Popen',side_effect=OSError('test spawn refused')):
            with self.assertRaisesRegex(OSError,'spawn refused'):
                self.launch('raise AssertionError()')
        self.child.stop()
        listener=self.child.listener
        self.assertEqual(listener.socket.fileno(),-1)
        self.assertIsNone(listener.ack_read)
        self.assertIsNone(listener.ack_write)

    def test_missing_filter_ack_is_never_readiness(self):
        self.child=activation.ActivatedListener('authserver')
        self.addCleanup(self.child.close)
        listener=self.child
        self.child=None
        listener.spawned()
        class Unreaped:
            @staticmethod
            def observe():
                return None
        with self.assertRaisesRegex(ValueError,'did not install'):
            listener.owns(Unreaped(),3724)


if __name__ == '__main__':
    unittest.main()
