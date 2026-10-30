"""Isolated, private file-syscall diagnostics for a fresh MySQL initialization.

This never adopts an earlier fixture or qualifies SQL, accounts or gameplay.
The caller verifies the engine and /usr/bin/strace provenance before calling.
Only fixed syscall/errno/path-role enums leave the private capture directory.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import os
from pathlib import Path
import posixpath
import re
import selectors
import stat
import subprocess
import time

from runtime import mysql_bootstrap as db
from runtime.owned_process_group import OwnedGroup


_ORIGINAL_OWNER = OwnedGroup
LOG_LIMIT = 2 * 1024 * 1024
LINE_LIMIT = 32 * 1024
TIMEOUT = 180
PUBLIC_ROW_LIMIT = 8
STRACE = Path('/usr/bin/strace')
SYSCALLS = ('openat', 'openat2', 'newfstatat', 'statx', 'mkdir', 'mkdirat',
            'getdents64', 'readlink', 'readlinkat', 'chdir', 'access',
            'faccessat', 'faccessat2')
ERRNOS = ('EACCES', 'EPERM', 'EROFS', 'EEXIST', 'ENOENT', 'ENOTDIR', 'EINVAL',
          'EIO', 'EINTR', 'EMFILE', 'ENFILE', 'ENAMETOOLONG', 'ELOOP')
ROLES = ('owned-staging-datadir', 'owned-initialization-tmpdir', 'owned-state',
         'absolute-outside-owned-state', 'relative-path', 'not-reported')
_CALL = re.compile(r'^(?:\d+\s+|\[pid\s+\d+\]\s+)?([a-zA-Z0-9_]+)\((.*)\)\s+=\s+-1\s+([A-Z0-9_]+)\b')


class TraceError(RuntimeError):
    """A fixed-text diagnostic precondition error, without private path text."""


@dataclass(frozen=True)
class FailedFileCall:
    syscall: str
    errno: str
    path_role: str

    def as_dict(self):
        return {'syscall': self.syscall, 'errno': self.errno, 'pathRole': self.path_role}


@dataclass(frozen=True)
class TraceReceipt:
    started: bool
    exit_code: int | None
    timed_out: bool
    process_group_cleaned: bool
    capture_drained: bool
    capture_failed: bool
    trace_truncated: bool
    parser_line_truncated: bool
    bytes_captured: int
    bytes_observed: int
    failed_file_calls: tuple[FailedFileCall, ...]

    def as_dict(self):
        complete = (self.started and self.capture_drained and not self.capture_failed
                    and not self.trace_truncated and not self.parser_line_truncated
                    and not self.timed_out and self.process_group_cleaned)
        return {'formatVersion': 1, 'scope': 'mysql-initialization-file-syscall-diagnostic-only',
                'started': self.started, 'exitCode': self.exit_code, 'timedOut': self.timed_out,
                'processGroupCleaned': self.process_group_cleaned, 'captureDrained': self.capture_drained,
                'captureFailed': self.capture_failed, 'traceComplete': complete,
                'traceTruncated': self.trace_truncated, 'parserLineTruncated': self.parser_line_truncated,
                'bytesCaptured': self.bytes_captured, 'bytesObserved': self.bytes_observed,
                'failedFileCalls': [row.as_dict() for row in self.failed_file_calls],
                'tracedInitializationSucceeded': complete and self.exit_code == 0,
                'qualificationSucceeded': False, 'sqlAuthenticated': False, 'sqlQualified': False,
                'accountQualified': False, 'protocolQualified': False,
                'androidRuntimeQualified': False, 'gameplayQualified': False}


def _arguments(text):
    """Split syscall arguments without treating quoted commas as delimiters."""
    result, start, depth, quoted, escaped, annotation = [], 0, 0, False, False, False
    for index, character in enumerate(text):
        if quoted:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == '"':
                quoted = False
        elif annotation:
            if character == '>':
                annotation = False
        elif character == '"':
            quoted = True
        elif character == '<':
            annotation = True
        elif character in '([{':
            depth += 1
        elif character in ')]}':
            depth -= 1
            if depth < 0:
                return []
        elif character == ',' and depth == 0:
            result.append(text[start:index].strip())
            start = index + 1
    if quoted or annotation or depth:
        return []
    return result + [text[start:].strip()]


def _quoted_path(argument):
    if not argument.startswith('"') or len(argument) > LINE_LIMIT:
        return None
    # Only a complete quoted argument is accepted; strace's trailing ... means
    # the filename was abbreviated and cannot establish a path identity.
    try:
        value = ast.literal_eval(argument)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    return value if isinstance(value, str) and '\x00' not in value else None


def _fd_path(argument):
    match = re.fullmatch(r'(?:-?\d+|AT_FDCWD)<(/[^<>\x00]*)>', argument)
    return match[1] if match else None


class FileCallParser:
    """Bounded streaming parser. Paths are classified and immediately discarded."""
    def __init__(self, state: Path, stage: Path, temporary: Path):
        self.paths = tuple(posixpath.normpath(str(path)) for path in (stage, temporary, state))
        self.rows = set()  # Fixed universe: len(SYSCALLS)*len(ERRNOS)*len(ROLES).
        self.pending = bytearray()
        self.dropping = False
        self.line_truncated = False

    def _role(self, path):
        if path is None:
            return 'not-reported'
        if not path.startswith('/'):
            return 'relative-path'
        path = posixpath.normpath(path)
        for root, role in zip(self.paths, ROLES):
            if path == root or path.startswith(root + '/'):
                return role
        return 'absolute-outside-owned-state'

    def _line(self, raw):
        match = _CALL.match(raw.decode('utf-8', errors='replace'))
        if match is None or match[1] not in SYSCALLS or match[3] not in ERRNOS:
            return
        syscall, arguments, error = match[1], _arguments(match[2]), match[3]
        path = None
        if arguments:
            if syscall == 'getdents64':
                path = _fd_path(arguments[0])
            elif syscall in ('openat', 'openat2', 'newfstatat', 'statx', 'mkdirat',
                             'readlinkat', 'faccessat', 'faccessat2'):
                if len(arguments) > 1:
                    path = _quoted_path(arguments[1])
                    directory = _fd_path(arguments[0])
                    if path is not None and not path.startswith('/') and directory is not None:
                        path = posixpath.join(directory, path)
            else:
                path = _quoted_path(arguments[0])
        self.rows.add(FailedFileCall(syscall, error, self._role(path)))

    def feed(self, block: bytes):
        # Split a bounded read, retaining at most one LINE_LIMIT byte fragment.
        for part in block.splitlines(keepends=True):
            ended = part.endswith(b'\n')
            if not self.dropping:
                if len(self.pending) + len(part) > LINE_LIMIT:
                    self.pending.clear()
                    self.dropping = self.line_truncated = True
                else:
                    self.pending.extend(part)
            if ended:
                if not self.dropping:
                    self._line(self.pending)
                self.pending.clear()
                self.dropping = False

    def finish(self):
        if self.pending and not self.dropping:
            self._line(self.pending)
        self.pending.clear()
        return tuple(sorted(self.rows, key=lambda row: (ROLES.index(row.path_role),
            0 if row.errno in ('EACCES', 'EPERM', 'EROFS') else 1,
            ERRNOS.index(row.errno), SYSCALLS.index(row.syscall)))[:PUBLIC_ROW_LIMIT])


def _run_owned(command, state, log, parser, *, timeout=TIMEOUT):
    """Drain continuously, even when the private prefix is full or unwritable."""
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    os.fchmod(descriptor, 0o600)
    process = group = None
    timed_out = cleaned = drained = failed = False
    captured = observed = 0
    exit_code = None
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'MYSQL_TEST_LOGIN_FILE': os.devnull}
    try:
        try:
            process = subprocess.Popen(command, cwd=state, env=environment, umask=0o077,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                start_new_session=True)
            try:
                group = OwnedGroup(process)
            except Exception:
                # Retain a cleanup owner even if an injected/wrapped factory
                # fails. The original class repeats all ownership validation;
                # never guess a group identity or reap outside that owner.
                try:
                    group = _ORIGINAL_OWNER(process)
                except Exception:
                    raise TraceError('Diagnostic process ownership could not be established') from None
                failed = True
        except OSError:
            failed = True
        if group is not None:
            deadline = time.monotonic() + timeout
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while selector.get_map():
                    if not cleaned and time.monotonic() >= deadline:
                        timed_out = True
                        exit_code, _ = group.stop(graceful_timeout=0, reap_timeout=5)
                        cleaned = True
                        deadline = time.monotonic() + 5
                    elif cleaned and time.monotonic() >= deadline:
                        failed = True
                        break
                    for key, _ in selector.select(.1):
                        block = os.read(key.fd, 8192)
                        if not block:
                            selector.unregister(key.fd)
                            drained = True
                            continue
                        observed += len(block)
                        parser.feed(block)
                        prefix = block[:max(0, LOG_LIMIT - captured)]
                        if prefix and not failed:
                            try:
                                view = memoryview(prefix)
                                while view:
                                    count = os.write(descriptor, view)
                                    if not count:
                                        raise OSError('diagnostic capture write failed')
                                    captured += count
                                    view = view[count:]
                            except OSError:
                                failed = True
                if not cleaned:
                    try:
                        exit_code = group.wait(max(0, deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        timed_out = True
    finally:
        try:
            if process is not None and group is None:
                # Also cover asynchronous interruption during construction.
                # This factory validates the still-unreaped child itself.
                try:
                    group = _ORIGINAL_OWNER(process)
                except Exception:
                    raise TraceError('Diagnostic process ownership could not be established') from None
            if group is not None and not cleaned:
                exit_code, _ = group.stop(graceful_timeout=0, reap_timeout=5)
                cleaned = True
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            try:
                os.fsync(descriptor)
            except OSError:
                failed = True
            finally:
                os.close(descriptor)
    return TraceReceipt(process is not None, exit_code, timed_out, cleaned, drained, failed,
                        observed > LOG_LIMIT, parser.line_truncated, captured, observed, parser.finish())


def _require_namespace():
    if os.getpid() != 1 or os.geteuid() != 0 or os.environ.get('ESTERIA_AUTH_NAMESPACE') != '1':
        raise TraceError('Initialization tracing requires the owned root authentication namespace')


def diagnose(mysqld: Path, parent: Path) -> TraceReceipt:
    """Run only strace + --initialize-insecure in a separate new private state.

    Never reuse this directory, including after failure. The caller's normal
    initialization result is unaffected by a diagnostic initialization success.
    The private prefix is parent/mysql-initialization-trace/initialization-file-trace.log.
    """
    _require_namespace()
    try:
        parent = db.private_path(Path(parent))
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise TraceError('Diagnostic parent must be an existing owned private directory')
        mysqld = db.private_path(Path(mysqld))
        if not stat.S_ISREG(mysqld.lstat().st_mode) or not os.access(mysqld, os.X_OK):
            raise TraceError('Diagnostic engine must be an executable regular file')
        state = parent / 'mysql-initialization-trace'
        state.mkdir(mode=0o700)
        db.sync_directory(parent)
        stage, run = state / 'database-initializing', state / 'run'
        stage.mkdir(mode=0o700)
        run.mkdir(mode=0o700)
        initialization = db.initialization_command(mysqld, stage, run)
        db.sync_directory(state)
    except (OSError, db.BootstrapError):
        raise TraceError('Fresh private diagnostic state is unavailable; existing state is preserved') from None
    command = [str(STRACE), '-f', '-yy', '-s', '4096', '-e', 'trace=%file,getdents64',
               '-o', '/proc/self/fd/1', *initialization]
    return _run_owned(command, state, state / 'initialization-file-trace.log',
                      FileCallParser(state, stage, run / 'initialize-tmp'), timeout=TIMEOUT)
