"""Explicit Android preparation I/O policy; default host execution stays unpaced.

Advice concerns clean immutable inputs, never global caches or file content.
Native advice preserves the frozen extractor's hash validation and I/O rate.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import hashlib
import os
from pathlib import Path
import stat
import sys
import subprocess
import time

NORMAL_RATE, PRESSURE_RATE = 8 << 20, 2 << 20
CACHE_WINDOW, WAIT_SLICE, PRESSURE_TIMEOUT = 2 << 20, .1, 60
SPEED_ENVIRONMENT = 'ESTERIA_PREPARATION_SPEED'
SPEED_RATES = {'gentle': NORMAL_RATE, 'balanced': 32 << 20, 'fast': 64 << 20}
NATIVE_CACHE_BATCH, NATIVE_CACHE_INTERVAL = 8 << 20, 1.0
NATIVE_CACHE_PRESSURE_INTERVAL = .1
NATIVE_ADDRESS_SPACE_BYTES = 4 << 30
PAUSED_EXIT_CODE = 75
_active = ContextVar('esteria_world_io_policy', default=None)
_cancelled = ContextVar('esteria_world_io_cancelled', default=lambda: False)


class PreparationPaused(ValueError):
    pass


def print_pause():
    """Stable transient outcome; never echo paths, exceptions or credentials."""
    print('ESTERIA_PREPARATION_PAUSED: memory pressure; completed phases retained; retry after memory recovers',
          file=sys.stderr, flush=True)


def child_failure(role, status, log):
    """Relay only the bounded tail of the already-open owned child log."""
    allowed = {'map_extractor', 'vmap4_extractor', 'vmap4_assembler', 'mmaps_generator', 'shader-translator'}
    role = role if role in allowed else 'preparation-child'
    saved = log.tell()
    try:
        log.flush()
        log.seek(0, os.SEEK_END)
        end = log.tell()
        log.seek(max(0, end - 8192))
        raw = log.read(8192)
        text = raw.decode('utf-8', errors='replace')
        text = ''.join(char if char in '\n\t' or (ord(char) >= 32 and ord(char) != 127) else '?' for char in text)
        text = text.encode('utf-8')[-8192:].decode('utf-8', errors='ignore')
    except (OSError, ValueError):
        text = '[owned child output unavailable]'
    finally:
        log.seek(saved)
    return 'worker=' + role + '; exitStatus=' + str(status) + '\n[owned child log tail]\n' + (text or '[no child output]')


def _helpers():
    try:
        from . import shader_generation, extractor_order
    except ImportError:
        import shader_generation, extractor_order
    return shader_generation, extractor_order


@contextmanager
def adapt_helpers(*, cancelled=lambda: False):
    """Runtime adapters for historical, byte-pinned helpers; their files stay intact.

    Preparation is serialized in each guest process. Nested adapters restore
    the exact previous callables; no pinned recipe or source identity changes.
    """
    storage, order = _helpers()
    originals = storage.identity, storage.execute, order.file_identity
    token = _cancelled.set(cancelled)
    storage.identity, storage.execute, order.file_identity = identity, shader_execute, extractor_identity
    try:
        yield
    finally:
        storage.identity, storage.execute, order.file_identity = originals
        _cancelled.reset(token)


def identity(path, maximum):
    """The frozen storage identity contract with an optional Android read policy."""
    storage, _ = _helpers()
    path = storage.canonical(path, False)
    with path.open('rb') as source:
        before = os.fstat(source.fileno())
        storage.require(0 <= before.st_size <= maximum, 'file size bound exceeded')
        digest, count = hashlib.sha256(), 0
        for block in chunks(source, 128 << 10):
            count += len(block)
            storage.require(count <= maximum, 'file grew beyond bound')
            digest.update(block)
        after = os.fstat(source.fileno())
    storage.require(count == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
        (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'input changed during read')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def extractor_identity(path):
    """The frozen provider hash/metadata contract, with bounded cancel/cache I/O."""
    _, order = _helpers()
    cancelled = _cancelled.get()
    if cancelled():
        raise PreparationPaused('extractor input hashing cancelled; completed phases retained')
    info = path.lstat()
    order.require(stat.S_ISREG(info.st_mode) and info.st_size <= order.MAX_FILE,
                  'extractor input must be a bounded regular file')
    digest = hashlib.sha256()
    phase('provider-order-hashing')
    with path.open('rb') as source:
        for block in chunks(source, order.BLOCK):
            if cancelled():
                raise PreparationPaused('extractor input hashing cancelled; completed phases retained')
            digest.update(block)
    after = path.lstat()
    order.require((info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'extractor input changed while hashing')
    return dict(bytes=info.st_size, sha256=digest.hexdigest())


def shader_execute(command, output, timeout, *, cache_inputs=()):
    """Owned supervisor adapter, preserving frozen log/deadline/group semantics."""
    storage, _ = _helpers()
    storage.require(0 < timeout <= 14400, 'invalid shader setup deadline')
    with output.open('x+b') as log, native_inputs(cache_inputs) as cache:
        os.chmod(output, 0o600)
        child = subprocess.Popen(guarded_command(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'})
        deadline, written = time.monotonic() + timeout, 0
        os.set_blocking(child.stdout.fileno(), False)
        try:
            while True:
                cache.tick()
                while True:
                    storage.require(time.monotonic() < deadline, 'shader generation deadline exceeded')
                    try:
                        chunk = os.read(child.stdout.fileno(), 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    remaining = (8 << 20) - written
                    log.write(chunk[:remaining]); written += min(remaining, len(chunk))
                    storage.require(len(chunk) <= remaining, 'shader setup log exceeded8MiB')
                storage.require(time.monotonic() < deadline, 'shader generation deadline exceeded')
                if os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                    while True:
                        try:
                            tail = os.read(child.stdout.fileno(), 65536)
                        except BlockingIOError:
                            break
                        if not tail:
                            break
                        remaining = (8 << 20) - written
                        log.write(tail[:remaining]); written += min(remaining, len(tail))
                        storage.require(len(tail) <= remaining, 'shader setup log exceeded8MiB')
                    break
                time.sleep(.1)
        finally:
            try:
                os.killpg(child.pid, 9)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise storage.ShaderError('shader process did not reap within cleanup deadline') from error
            finally:
                child.stdout.close()
        if child.returncode == PAUSED_EXIT_CODE:
            raise PreparationPaused('Shader preparation paused; completed phases retained')
        if child.returncode != 0:
            raise storage.ShaderError('shader translator failed; previous generation retained; ' +
                child_failure('shader-translator', child.returncode, log))


def _memory_available():
    try:
        with open('/proc/meminfo', encoding='ascii') as stream:
            for index, line in enumerate(stream):
                if index >= 128:
                    break
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


class Policy:
    def __init__(self, cancelled=lambda: False, progress=lambda value: None, *,
                 clock=time.monotonic, sleeper=time.sleep, memory_probe=_memory_available, advice=None, speed=None):
        # A missing selection retains the historical component-fixture policy.
        # The launcher explicitly supplies its persisted preparation choice.
        self.speed = os.environ.get(SPEED_ENVIRONMENT, 'gentle') if speed is None else speed
        if not isinstance(self.speed, str) or self.speed not in SPEED_RATES:
            raise ValueError('Unknown world preparation speed')
        self.normal_rate = SPEED_RATES[self.speed]
        self.cancelled, self.progress = cancelled, progress
        self.clock, self.sleeper, self.memory_probe = clock, sleeper, memory_probe
        self.advice = advice if advice is not None else getattr(os, 'posix_fadvise', None)
        self.deadline = clock()
        self.read_bytes = self.cache_calls = self.cache_bytes = self.cache_errors = self.pressure_waits = 0
        self.native_pressure_aborts = 0
        self.phase = 'preparation-io'
        self.sample_at = self.report_at = None
        self.available = None

    def check_cancelled(self):
        if self.cancelled():
            raise PreparationPaused('World preparation cancelled; completed phases are retained')

    def pressure(self):
        now = self.clock()
        if self.sample_at is None or now - self.sample_at >= 1:
            self.sample_at, self.available = now, self.memory_probe()
        if self.available is not None and self.available <= 256 << 20:
            return 2
        return 1 if self.available is not None and self.available <= 512 << 20 else 0

    def checkpoint(self):
        self.check_cancelled()
        began, waiting = self.clock(), False
        while self.pressure() >= 2:
            if not waiting:
                self.pressure_waits += 1
                waiting = True
            self.report()
            if self.clock() - began >= PRESSURE_TIMEOUT:
                raise PreparationPaused('World preparation paused because memory remains low; completed phases are retained. Retry after memory recovers.')
            self.sleeper(WAIT_SLICE)
            self.check_cancelled()

    def consumed(self, count):
        self.checkpoint()
        self.read_bytes += count
        rate = PRESSURE_RATE if self.pressure() else self.normal_rate
        self.deadline = max(self.deadline, self.clock()) + count / rate
        while self.deadline - self.clock() > 0:
            self.checkpoint()
            delay = min(WAIT_SLICE, self.deadline - self.clock())
            if delay > 0:
                self.sleeper(delay)
            self.check_cancelled()
        self.report()

    def release(self, fd, offset, length):
        if length <= 0:
            return
        self.cache_calls += 1
        try:
            if self.advice is None or not hasattr(os, 'POSIX_FADV_DONTNEED'):
                raise OSError('input cache advice unavailable')
            self.advice(fd, offset, length, os.POSIX_FADV_DONTNEED)
            self.cache_bytes += length
        except (OSError, ValueError):
            self.cache_errors += 1

    def report(self, force=False):
        now = self.clock()
        if not force and self.report_at is not None and now - self.report_at < 1:
            return
        self.report_at = now
        self.progress('WORLD_IO ' + json.dumps(dict(phase=self.phase, readBytes=self.read_bytes,
            speed=self.speed, normalBytesPerSecond=self.normal_rate, pressureBytesPerSecond=PRESSURE_RATE,
            availableBytes=self.available, pressureLevel=self.pressure(), pressureWaits=self.pressure_waits,
            nativeAddressSpaceLimitBytes=NATIVE_ADDRESS_SPACE_BYTES, nativePressureAborts=self.native_pressure_aborts,
            nativeCacheWindowBytes=CACHE_WINDOW, nativeCacheBatchBytes=NATIVE_CACHE_BATCH,
            nativeCachePolicy='bounded-rotating-clean-input-windows',
            cacheCalls=self.cache_calls, cacheAdvisedBytes=self.cache_bytes, cacheErrors=self.cache_errors),
            separators=(',', ':'), sort_keys=True))


@contextmanager
def android_policy(cancelled=lambda: False, progress=lambda value: None, **test_options):
    policy = Policy(cancelled, progress, **test_options)
    token = _active.set(policy)
    try:
        with adapt_helpers(cancelled=cancelled):
            yield policy
    finally:
        try:
            policy.report(force=True)
        finally:
            _active.reset(token)


def phase(value):
    policy = _active.get()
    if policy is not None:
        policy.phase = value
        policy.report(force=True)


def enabled():
    return _active.get() is not None


def chunks(source, size):
    """Bounded reads, paced/accounted only within an explicit Android context."""
    policy = _active.get()
    if policy is None:
        while block := source.read(size):
            yield block
        return
    offset, pending = source.tell(), 0
    try:
        while True:
            policy.checkpoint()
            block = source.read(size)
            if not block:
                break
            pending += len(block)
            if pending >= CACHE_WINDOW:
                policy.release(source.fileno(), offset, pending)
                offset, pending = offset + pending, 0
            policy.consumed(len(block))
            yield block
    finally:
        if pending:
            policy.release(source.fileno(), offset, pending)


def copy_stream(incoming, outgoing, size=128 << 10, *, cancelled=lambda: False):
    policy = _active.get()
    offset, pending = outgoing.tell(), 0
    for block in chunks(incoming, size):
        if cancelled():
            raise PreparationPaused('World preparation cancelled; completed phases are retained')
        outgoing.write(block)
        pending += len(block)
        if policy is not None and pending >= CACHE_WINDOW:
            outgoing.flush()
            os.fdatasync(outgoing.fileno())
            policy.release(outgoing.fileno(), offset, pending)
            offset, pending = offset + pending, 0
    if policy is not None:
        outgoing.flush()
        os.fdatasync(outgoing.fileno())
        policy.release(outgoing.fileno(), offset, pending)


def archive_paths(root):
    """Known regular MPQs under the immutable Data input, for native cache advice."""
    root = Path(root)
    data = [p for p in root.iterdir() if p.name.lower() == 'data']
    if len(data) != 1 or data[0].is_symlink() or not data[0].is_dir():
        raise ValueError('One canonical Data directory required for preparation cache inputs')
    found = []
    for parent, dirs, files in os.walk(data[0], followlinks=False):
        if len(Path(parent).relative_to(data[0]).parts) > 32:
            raise ValueError('Preparation cache input directory depth bound')
        for name in dirs:
            if (Path(parent) / name).is_symlink():
                raise ValueError('Linked preparation cache input refused')
        for name in files:
            if name.lower().endswith('.mpq'):
                found.append(Path(parent) / name)
                if len(found) > 4096:
                    raise ValueError('Preparation cache archive count bound')
    return tuple(found)


class NativeInputs:
    """Bounded rotating clean-input advice; no child rate cap/reclaimed-byte claim.

    Advising every byte of every MPQ every 100ms discards useful native read
    cache repeatedly. Keep memory/cancellation checks at every tick, but advance
    through at most 8MiB in 2MiB windows once per second while memory is healthy.
    Pressure increases advice frequency without growing a batch or a buffer.
    """
    def __init__(self, paths):
        self.policy, self.files, self.next_at = _active.get(), [], 0
        self.offsets, self.cursor = [], 0
        if self.policy is None:
            return
        seen = set()
        try:
            for path in paths:
                path = Path(path)
                if path.absolute() != path.resolve(strict=True):
                    raise ValueError('Canonical native cache input required')
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode):
                        raise ValueError('Regular native cache input required')
                    key = (info.st_dev, info.st_ino)
                    if key not in seen:
                        self.files.append((fd, info.st_size)); self.offsets.append(0)
                        seen.add(key); fd = None
                finally:
                    if fd is not None:
                        os.close(fd)
        except BaseException:
            self.close()
            raise

    def tick(self, force=False):
        if self.policy is None:
            return
        self.policy.check_cancelled()
        pressure = self.policy.pressure()
        if pressure >= 2:
            self.policy.native_pressure_aborts += 1
            self.policy.report(force=True)
            raise PreparationPaused('World preparation paused because memory is critically low; the native operation is stopped and completed phases are retained.')
        now = self.policy.clock()
        if not force and now < self.next_at:
            return
        self.next_at = now + (NATIVE_CACHE_PRESSURE_INTERVAL if pressure else NATIVE_CACHE_INTERVAL)
        budget, completed = NATIVE_CACHE_BATCH, set()
        for _ in range(NATIVE_CACHE_BATCH // CACHE_WINDOW):
            # Completed small files receive no repeated advice within a batch;
            # all nonempty inputs rotate fairly across ticks.
            for _ in range(len(self.files)):
                index = self.cursor
                self.cursor = (self.cursor + 1) % len(self.files)
                fd, size = self.files[index]
                if size > 0 and index not in completed:
                    break
            else:
                break
            offset = self.offsets[index]
            length = min(CACHE_WINDOW, budget, size - offset)
            self.policy.release(fd, offset, length)
            self.offsets[index] = offset + length
            if self.offsets[index] == size:
                self.offsets[index] = 0
                completed.add(index)
            budget -= length
        self.policy.report()

    def close(self):
        while self.files:
            fd, _ = self.files.pop()
            os.close(fd)
        self.offsets.clear()

    def __enter__(self):
        try:
            self.tick(force=True)
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, typ, value, traceback):
        try:
            if typ is None:
                self.tick(force=True)
        finally:
            self.close()


def native_inputs(paths=()):
    return NativeInputs(paths)


def guarded_command(command):
    """Set the fixed Android child limit before exec, without a postlaunch race."""
    if not enabled():
        return command
    return [sys.executable, '-B', '-s', '-E', str(Path(__file__).resolve()), '--exec-with-memory-limit', *command]


def _exec_with_memory_limit(arguments):
    # This trusted helper is installed from the APK closure. Arguments remain
    # an exec argv, never a shell command; cwd, environment and group survive.
    if not arguments:
        raise ValueError('Native preparation executable is required')
    import resource
    _, inherited_hard = resource.getrlimit(resource.RLIMIT_AS)
    budget = NATIVE_ADDRESS_SPACE_BYTES if inherited_hard == resource.RLIM_INFINITY else min(inherited_hard, NATIVE_ADDRESS_SPACE_BYTES)
    resource.setrlimit(resource.RLIMIT_AS, (budget, budget))
    os.execv(arguments[0], arguments)


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '--exec-with-memory-limit':
        raise SystemExit('Use the fixed native preparation exec mode')
    try:
        _exec_with_memory_limit(sys.argv[2:])
    except (OSError, ValueError) as error:
        print('Native preparation memory guard failed: ' + str(error), file=sys.stderr)
        raise SystemExit(127)
