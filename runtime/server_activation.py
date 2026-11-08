"""Selected auth/world socket activation where Android hides TCP tables.

The owned parent binds the only network listener before starting its child.
The selected server accepts systemd-compatible fd 3. Its redundant listen(3)
must succeed, but no new kernel listen may run, even if a descriptor is reused.
"""
import ctypes
import errno
import os
from pathlib import Path
import platform
import socket
import stat
import sys

ENV_KEY = 'AC_NETWORK_USE_SOCKET_ACTIVATION'
ACK = b'esteria-activated-v1\n'
PORTS = {'authserver': 3724, 'worldserver': 8085}


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def tables_restricted(proc=Path('/proc')):
    try:
        for name in ('tcp', 'tcp6'):
            with (proc / 'self/net' / name).open('rb') as stream:
                stream.read(1)
    except PermissionError:
        return True
    return False


class Filter(ctypes.Structure):
    _fields_ = [('code', ctypes.c_ushort), ('jt', ctypes.c_ubyte),
                ('jf', ctypes.c_ubyte), ('k', ctypes.c_uint32)]


class Program(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ushort), ('rules', ctypes.POINTER(Filter))]


def forbid_new_listeners():
    """Install a single-threaded exec-inherited classic BPF filter on the child."""
    # Linux UAPI numbers for the two qualified little-endian 64-bit ABIs.
    numbers = {'aarch64': (0xc00000b7, 198, 200, 201),
               'x86_64': (0xc000003e, 41, 49, 50)}
    arch = platform.machine()
    check(arch in numbers and sys.byteorder == 'little' and ctypes.sizeof(ctypes.c_void_p) == 8,
          'Unsupported native listener filter ABI')
    audit_arch, socket_nr, bind_nr, listen_nr = numbers[arch]
    load, equal, greater_equal, ret = 0x20, 0x15, 0x35, 0x06
    allow, error = 0x7fff0000, 0x00050000  # SECCOMP_RET_ALLOW, SECCOMP_RET_ERRNO
    deny = error | errno.EPERM
    rules = [(load, 0, 0, 4), (equal, 1, 0, audit_arch), (ret, 0, 0, deny),
             (load, 0, 0, 0), (greater_equal, 0, 1, 0x40000000), (ret, 0, 0, deny)]
    # No alternate io_uring bind/listen/recvmsg, or obtaining another process's
    # open socket. No external Unix socket from which to receive SCM_RIGHTS.
    # Private socketpairs cannot bring in descriptors from an outside sender.
    for number in (bind_nr, 425, 426, 427, 438):
        rules += [(equal, 0, 1, number), (ret, 0, 0, deny)]
    rules += [
        (equal, 0, 4, listen_nr), (load, 0, 0, 16), (equal, 0, 1, 3),
        (ret, 0, 0, error), (ret, 0, 0, deny),
        (equal, 0, 4, socket_nr), (load, 0, 0, 16),
        (equal, 2, 0, socket.AF_INET), (equal, 1, 0, socket.AF_INET6),
        (ret, 0, 0, deny), (ret, 0, 0, allow),
    ]
    insns = (Filter * len(rules))(*(Filter(*row) for row in rules))
    program = Program(len(insns), insns)
    prctl = ctypes.CDLL(None, use_errno=True).prctl
    prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
    for option, arg1, arg2 in ((38, 1, 0), (22, 2, ctypes.addressof(program))):
        if prctl(option, arg1, arg2, 0, 0) == -1:
            raise OSError(ctypes.get_errno(), 'Cannot install owned listener guard')


def child_exec(descriptor, ack, program, executable, configuration):
    port = PORTS[program]
    check(Path(executable).is_absolute() and Path(configuration).is_absolute() and
          descriptor >= 3 and ack > 3 and descriptor != ack, 'Invalid owned listener launch')
    # ack is close-on-exec after its single write. Only fd 3 survives exec.
    os.set_inheritable(ack, False)
    if descriptor != 3:
        os.dup2(descriptor, 3, inheritable=True)
        os.close(descriptor)
    os.set_inheritable(3, True)
    # Close-fds Popen supplies pipes or /dev/null on 0..2 and the two allowed
    # descriptors. Verify there are no inherited network or Unix-rights sockets.
    for name in os.listdir('/proc/self/fd'):
        fd = int(name)
        try:
            mode = os.fstat(fd).st_mode
        except OSError as error:
            if error.errno == errno.EBADF:  # listdir's own closed directory fd
                continue
            raise
        check(fd in (0, 1, 2, 3, ack) and (fd == 3 or not stat.S_ISSOCK(mode)),
              'Unexpected inherited descriptor in owned listener launch')
    listener = socket.socket(fileno=3)
    try:
        check(listener.family == socket.AF_INET and listener.type == socket.SOCK_STREAM and
              listener.getsockname() == ('127.0.0.1', port) and
              listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1,
              'Inherited server listener differs from fixed endpoint')
    finally:
        listener.detach()
    env = dict(os.environ, LISTEN_PID=str(os.getpid()), LISTEN_FDS='1', **{ENV_KEY: '1'})
    forbid_new_listeners()
    check(os.write(ack, ACK) == len(ACK), 'Owned listener guard acknowledgement failed')
    os.execve(executable, [executable, '--config', configuration], env)


class ActivatedListener:
    def __init__(self, program):
        self.port = PORTS[program]
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.ack_read = self.ack_write = None
        self.acknowledged = False
        self.message = b''
        try:
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(('127.0.0.1', self.port))
            self.socket.listen(socket.SOMAXCONN)
            self.inode = os.fstat(self.socket.fileno()).st_ino
            self.ack_read, self.ack_write = os.pipe()
            os.set_blocking(self.ack_read, False)
        except BaseException:
            self.close()
            raise

    def command(self, program, executable, configuration):
        return [sys.executable, '-I', '-S', '-B', str(Path(__file__).resolve()),
                str(self.socket.fileno()), str(self.ack_write), program, str(executable), str(configuration)]

    def spawned(self):
        os.close(self.ack_write)
        self.ack_write = None

    def owns(self, group, port, proc=Path('/proc')):
        check(port == self.port and group.observe() is None, 'Owned activated server or endpoint changed')
        if not self.acknowledged:
            try:
                raw = os.read(self.ack_read, len(ACK) + 1)
            except BlockingIOError:
                return False
            self.message += raw
            check(ACK.startswith(self.message), 'Invalid owned listener guard acknowledgement')
            if raw:
                return False
            check(self.message == ACK, 'Server did not install its owned listener guard')
            os.close(self.ack_read)
            self.ack_read = None
            self.acknowledged = True
        endpoint = self.socket.getsockname()
        check(endpoint == ('127.0.0.1', port) and
              self.socket.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) == 1 and
              os.fstat(self.socket.fileno()).st_ino == self.inode and
              os.readlink(proc / str(group.process.pid) / 'fd/3') == f'socket:[{self.inode}]',
              'Owned activated listener descriptor changed')
        check(group.observe() is None, 'Server child exited during activated listener verification')
        return True

    def close(self):
        for name in ('ack_read', 'ack_write'):
            fd = getattr(self, name)
            if fd is not None:
                os.close(fd)
                setattr(self, name, None)
        self.socket.close()


if __name__ == '__main__':
    child_exec(int(sys.argv[1]), int(sys.argv[2]), *sys.argv[3:])
