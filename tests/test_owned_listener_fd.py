"""Exercise the restricted-proc fallback with kernel-backed, owned child FDs."""
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import server_session_process as owner
from runtime.owned_process_group import OwnedGroup


class OwnedFdTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.proc = Path(temporary.name)

    def child(self, extra='', *, listening=True):
        script = '''
import json, os, signal, socket, sys
s=socket.socket();s.bind(('127.0.0.1',0))
alias=os.dup(s.fileno())
try: unix=socket.socketpair()
except PermissionError: unix=None
active=socket.socket()
''' + ('s.listen()\n' if listening else '') + extra + '''
print(json.dumps([os.readlink('/proc/self'),s.getsockname()[1], s.fileno()]),flush=True)
sys.stdin.buffer.read(1)
'''
        child = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, start_new_session=True)
        group = OwnedGroup(child)
        def close():
            child.stdin.close()
            group.stop(graceful_timeout=.25)
            child.stdout.close()
        self.addCleanup(close)
        outer, port, remote = json.loads(child.stdout.readline())
        # Managed host's procfs can belong to its outer PID namespace. Its
        # child's actual kernel FD directory is still the one inspected.
        (self.proc / str(child.pid)).symlink_to(Path('/proc') / outer)
        return group, port, remote

    def test_genuine_owned_listener_alias_nonlisteners_and_wrong_port(self):
        group, port, _ = self.child()
        with patch.object(owner, '_read', side_effect=PermissionError(errno.EACCES, 'table denied')):
            try:
                self.assertTrue(owner.owns_loopback_listener(group, port, proc=self.proc))
            except PermissionError as error:
                self.skipTest('Kernel refuses direct pidfd descriptor duplication: ' + str(error.errno))
            with self.assertRaisesRegex(ValueError, 'unexpected IPv4'):
                owner.owns_loopback_listener(group, 1 if port != 1 else 2, proc=self.proc)

    def test_extra_loopback_wildcard_and_ipv6_listeners_rejected(self):
        for family, address, reason in [('AF_INET','127.0.0.1','IPv4'),('AF_INET','0.0.0.0','IPv4'),
                                        ('AF_INET6','::','IPv6')]:
            with self.subTest(family=family, address=address):
                if family == 'AF_INET6' and not socket.has_ipv6:
                    continue
                group, port, _ = self.child(f"extra=socket.socket(socket.{family});"
                                             f"extra.bind(('{address}',0));extra.listen()\n")
                with patch.object(owner, '_read', side_effect=PermissionError()):
                    try:
                        with self.assertRaisesRegex(ValueError, 'unexpected ' + reason):
                            owner.owns_loopback_listener(group, port, proc=self.proc)
                    except PermissionError as error:
                        self.skipTest('Kernel refuses direct pidfd descriptor duplication: ' + str(error.errno))

    def test_transient_fd_replacement_restarts_cross_check_and_denial_fails_closed(self):
        group, port, _ = self.child()
        root = self.proc / str(group.process.pid)
        snapshot = owner._socket_fds(root)
        with patch.object(owner, '_socket_fds', side_effect=[snapshot,{},{},{},{}]), \
                patch.object(owner, '_read', side_effect=PermissionError()):
            self.assertFalse(owner.owns_loopback_listener(group, port, proc=self.proc))
        with patch.object(owner, '_read', side_effect=PermissionError()), \
                patch.object(owner, '_duplicate_fd', side_effect=OSError(errno.EBADF,'replaced')) as attempts:
            self.assertFalse(owner.owns_loopback_listener(group, port, proc=self.proc))
            self.assertEqual(attempts.call_count,3)
        with patch.object(owner, '_read', side_effect=PermissionError()), \
                patch.object(owner, '_duplicate_fd', side_effect=PermissionError(errno.EPERM,'forbidden')):
            with self.assertRaises(PermissionError):
                owner.owns_loopback_listener(group, port, proc=self.proc)

    def test_foreign_listener_cannot_make_a_child_ready(self):
        group, _, _ = self.child(listening=False)
        with socket.socket() as foreign:
            foreign.bind(('127.0.0.1',0));foreign.listen()
            with patch.object(owner,'_read',side_effect=PermissionError()):
                self.assertFalse(owner.owns_loopback_listener(group,foreign.getsockname()[1],proc=self.proc))


    def test_reused_fd_number_with_regular_file_never_qualifies_or_leaks_copy(self):
        group, port, _ = self.child()
        copies = []
        def changed(*_):
            fd = os.open('/dev/null', os.O_RDONLY)
            copies.append(fd)
            return fd
        with patch.object(owner, '_duplicate_fd', side_effect=changed), \
                patch.object(owner, '_read', side_effect=PermissionError()):
            self.assertFalse(owner.owns_loopback_listener(group, port, proc=self.proc))
        self.assertEqual(len(copies), 3)
        for fd in copies:
            with self.assertRaises(OSError):
                os.fstat(fd)

    def test_inspecting_child_under_nondefault_python_timeout_preserves_its_fd_flags(self):
        group, port, remote = self.child()
        fdinfo = self.proc / str(group.process.pid) / 'fdinfo' / str(remote)
        original = fdinfo.read_bytes()
        timeout = socket.getdefaulttimeout()
        try:
            socket.setdefaulttimeout(.2)
            with patch.object(owner, '_read', side_effect=PermissionError()):
                self.assertTrue(owner.owns_loopback_listener(group, port, proc=self.proc))
        finally:
            socket.setdefaulttimeout(timeout)
        self.assertEqual(fdinfo.read_bytes(), original)
