"""Owned auth/world process primitives; no source/data/setup qualification here.

Production callers must verify the immutable programs, four-schema installation,
configuration and prepared data first. This module never discovers/kills a PID,
replays SQL or treats an open TCP port as owned server readiness.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import select
import secrets
import socket
import struct
import subprocess
import threading
import time

try:
    from .owned_process_group import OwnedGroup
except ImportError:
    from owned_process_group import OwnedGroup

LOG_LIMIT = 8 << 20
PROC_LIMIT = 16 << 20
WORLD_INFO = b'server info\n'
WORLD_SHUTDOWN = b'server shutdown 1\n'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _read(path, maximum):
    with path.open('rb') as source:
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, 'Owned listener metadata exceeds bound')
    return raw


def owns_loopback_listener(group, port, *, proc=Path('/proc')):
    """Match the retained child's socket inode, rejecting every extra listener.

    A reserved, unreaped leader prevents PID reuse. Failure to inspect its own
    descriptor/network metadata is an error, never fallback TCP readiness.
    """
    require(isinstance(group, OwnedGroup) and type(port) is int and 1 <= port <= 65535,
            'Owned child and fixed listener port required')
    require(group.observe() is None, 'Server child exited before listener verification')
    root = proc / str(group.process.pid)
    sockets, count = set(), 0
    try:
        for descriptor in (root / 'fd').iterdir():
            count += 1
            require(count <= 4096, 'Owned child descriptor count exceeds bound')
            try:
                target = os.readlink(descriptor)
            except FileNotFoundError:
                continue
            matched = re.fullmatch(r'socket:\[([0-9]+)\]', target)
            if matched:
                sockets.add(matched[1])
        tables = {name: _read(root / 'net' / name, PROC_LIMIT).decode('ascii').splitlines()[1:]
                  for name in ('tcp', 'tcp6')}
    except FileNotFoundError:
        require(group.observe() is None, 'Server child exited during listener verification')
        return False
    found = []
    for name, rows in tables.items():
        for row in rows:
            fields = row.split()
            require(len(fields) >= 10, 'Unexpected owned TCP metadata')
            if fields[3] != '0A' or fields[9] not in sockets:
                continue
            require(name == 'tcp', 'Server opened an unexpected IPv6 listener')
            found.append(fields[1])
    endpoint = '0100007F:' + f'{port:04X}'
    require(all(value == endpoint for value in found), 'Server opened an unexpected IPv4 listener')
    require(group.observe() is None, 'Server child exited during listener verification')
    return found == [endpoint]


def _probe_read(connection, count, deadline):
    result = b''
    while len(result) < count:
        remaining = deadline - time.monotonic()
        require(remaining > 0, 'Server protocol probe deadline exceeded')
        connection.settimeout(remaining)
        block = connection.recv(count - len(result))
        require(block, 'Server protocol probe ended before its declared payload')
        result += block
    return result


def auth_challenge(port=3724, *, timeout=1):
    """Process a source Grunt challenge without a password/proof/session key.

    A random16-character unknown name gets the source's three-byte error callback,
    proving actual auth I/O and async SQL processing. An unlikely name collision
    fails closed. No login/proof or client/auth SRP qualification is claimed.
    Caller checks owned socket-inode identity immediately before and after.
    """
    require(type(port) is int and 1 <= port <= 65535 and 0 < timeout <= 3,
            'Fixed auth probe endpoint/deadline required')
    name = ('ERDY' + secrets.token_hex(6).upper()).encode('ascii')
    packet = struct.pack('<BBH4sBBBH4s4s4sI4sB', 0, 0, 30 + len(name), b'WoW\0', 3, 3, 5, 12340,
                         b'68x\0', b'niW\0', b'SUne', 0, socket.inet_aton('127.0.0.1'), len(name)) + name
    deadline = time.monotonic() + timeout
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as connection:
        connection.settimeout(max(.001, deadline - time.monotonic()))
        connection.sendall(packet)
        require(_probe_read(connection, 3, deadline) == b'\0\0\x04',
                'Auth challenge callback differs from the selected source')
    return True


def world_challenge(port=8085, *, timeout=1):
    """Read only the source's initial SMSG_AUTH_CHALLENGE, no player login.

    Caller separately proves socket-inode ownership immediately before/after.
    This establishes neither character access nor world/gameplay readiness.
    """
    require(type(port) is int and 1 <= port <= 65535 and 0 < timeout <= 3,
            'Fixed world probe endpoint/deadline required')
    deadline = time.monotonic() + timeout
    with socket.create_connection(('127.0.0.1', port), timeout=timeout) as connection:
        packet = _probe_read(connection, 44, deadline)
    require(packet[:4] == b'\x00\x2a\xec\x01' and struct.unpack_from('<I', packet, 4)[0] == 1,
            'World challenge differs from the selected build12340 source')
    return True


class ServerChild:
    """Allocate before start; retain across every startup/cleanup exception.

    The application owner retains this child object and its parent guest until
    confirmed reaping. These generic primitives also support explicit host child
    fixtures; they are not a route around the production verifier.
    """
    def __init__(self, program, executable, configuration, working, log):
        require(program in ('authserver', 'worldserver'), 'Fixed server component required')
        self.program, self.executable = program, Path(executable)
        self.configuration, self.working, self.log = Path(configuration), Path(working), Path(log)
        require(all(path.is_absolute() for path in (self.executable, self.configuration, self.working, self.log)),
                'Absolute verified server paths required')
        self.process = self.group = self.reader = self.output = None
        self.error = None
        self.observed = self.stored = 0
        self.info_sequence = 0
        self.info_connected = False
        self.world_command_queued = False
        self.auth_shutdown_requested = False
        self.closed = False
        self.shutdown_acknowledged = False
        self._lock = threading.Lock()

    def start(self):
        require(self.process is None and not self.closed, 'Server child startup is single-use')
        self.output = self.log.open('xb')
        os.chmod(self.log, 0o600)
        # Attach Popen to the retained object before any later operation can fail.
        self.process = subprocess.Popen([str(self.executable), '--config', str(self.configuration)],
            cwd=self.working, env={**os.environ, 'LC_ALL': 'C', 'LANG': 'C'}, umask=0o077,
            stdin=subprocess.PIPE if self.program == 'worldserver' else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
        self.group = OwnedGroup(self.process)
        if self.process.stdin is not None:
            require(os.fpathconf(self.process.stdin.fileno(), 'PC_PIPE_BUF') >= 4096,
                    'World console pipe atomic bound differs')
            os.set_blocking(self.process.stdin.fileno(), False)
        self.reader = threading.Thread(target=self._drain, name='esteria-' + self.program + '-logs', daemon=True)
        self.reader.start()
        return self

    def _drain(self):
        pending = b''
        try:
            while block := self.process.stdout.read(8192):
                self.observed += len(block)
                keep = min(len(block), max(0, LOG_LIMIT - self.stored))
                self.output.write(block[:keep]); self.stored += keep
                pending += block
                while b'\n' in pending:
                    line, pending = pending.split(b'\n', 1)
                    # Source fixed read-only console response; retain counters,
                    # never player names, passwords or arbitrary diagnostic text.
                    with self._lock:
                        if b'Connected players:' in line:
                            self.info_connected = True
                        if self.info_connected and b'Update time diff:' in line:
                            self.info_sequence += 1; self.info_connected = False
                require(len(pending) <= 16384, 'Server diagnostic line exceeds bound')
        except (OSError, ValueError) as error:
            self.error = type(error).__name__

    def alive(self):
        return self.group is not None and not self.closed and self.group.observe() is None

    def send_world(self, command, timeout=.5):
        require(self.program == 'worldserver' and command in (WORLD_INFO, WORLD_SHUTDOWN) and 0 < timeout <= 1,
                'Fixed bounded world console command required')
        require(self.alive() and self.process.stdin is not None, 'Owned world console is unavailable')
        descriptor, deadline = self.process.stdin.fileno(), time.monotonic() + timeout
        while True:
            try:
                count = os.write(descriptor, command)
                require(count == len(command), 'World console atomic write was incomplete')
                if command == WORLD_SHUTDOWN:
                    self.world_command_queued = True
                return
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'World console command could not be queued')
                select.select([], [descriptor], [], min(.02, remaining))

    def info_counter(self):
        with self._lock:
            return self.info_sequence

    def stop(self, *, world_timeout=20, auth_timeout=3):
        """Source console+zero exit for world; direct source SIGTERM+zero for auth.

        Forced cleanup remains an error. A still-unreaped child retains all
        streams and this owner; the caller must keep the parent guest alive and
        retry instead of releasing the database/configuration dependency.
        """
        if self.closed:
            return
        status, forced, clean_world = None, False, False
        if self.process is None:
            if self.output is not None:
                self.output.close()
            self.closed = True
            return
        if self.process is not None:
            if self.group is None:
                self.group = OwnedGroup(self.process)
            if self.program == 'worldserver':
                if self.group.observe() is None:
                    try:
                        if not self.world_command_queued:
                            self.send_world(WORLD_SHUTDOWN)
                        status = self.group.wait(world_timeout)
                        clean_world = self.world_command_queued and status == 0
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        forced = True
                status, killed = self.group.stop(graceful_timeout=0, reap_timeout=5)
                forced = forced or killed or not clean_world
            else:
                # Unlike signalling the PRoot tracer, this targets the exact
                # child/session created here. Auth Main.cpp handles SIGTERM.
                # Preserve request intent across failed reap retries. A child
                # that already exited before our first source-stop request is
                # an unexpected exit even when its numeric status is zero.
                if self.group.observe() is None:
                    self.auth_shutdown_requested = True
                status, forced = self.group.stop(graceful_timeout=auth_timeout, reap_timeout=5)
                forced = forced or not self.auth_shutdown_requested
            if self.process.stdin is not None:
                self.process.stdin.close()
            if self.reader is not None:
                self.reader.join(timeout=2)
                require(not self.reader.is_alive(), 'Server diagnostic worker remains active')
            self.process.stdout.close()
        if self.output is not None:
            self.output.flush(); os.fsync(self.output.fileno()); self.output.close()
        self.closed = True
        self.shutdown_acknowledged = not forced and status == 0 and self.error is None
        require(self.shutdown_acknowledged,
                'Server did not acknowledge clean source shutdown; recovery is required')
