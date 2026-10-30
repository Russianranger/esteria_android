"""Bounded Linux PCM capture for FMOD/Wine/ALSA qualification, never Android audio.

Implements the same playback-only wire contract as core.presentation.PcmProtocol.
The playback head is a monotonic software clock; captured samples prove transport
and channel content, not AudioTrack, a physical DAC, latency or audible output.
"""
from array import array
import hashlib
import math
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import threading
import time

RATE = 48000
MAX_STREAM_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_STREAMS = 64
MAX_CONNECTIONS = 8


class PlaybackClock:
    def __init__(self, capacity, now=time.monotonic_ns):
        if not 64 <= capacity <= RATE:
            raise ValueError('pcm-capacity-invalid')
        self.capacity = capacity
        self.now = now
        self.reset()

    def reset(self):
        self.played = self.written = self.fraction = 0
        self.active = False
        self.previous = self.now()

    def update(self):
        current = self.now()
        elapsed = max(0, current - self.previous)
        self.previous = current
        if self.active:
            scaled = elapsed * RATE + self.fraction
            due, remainder = divmod(scaled, 1_000_000_000)
            queued = self.written - self.played
            self.played += min(due, queued)
            self.fraction = remainder if due <= queued else 0

    def start(self):
        self.update()
        self.active = True

    def write(self, frames):
        self.update()
        accepted = min(frames, self.capacity - (self.written - self.played))
        self.written += accepted
        return accepted

    def head(self):
        self.update()
        return self.played & 0xffffffff


def receive(connection, count, *, allow_eof=False):
    data = bytearray()
    while len(data) < count:
        block = connection.recv(count - len(data))
        if not block:
            if allow_eof and not data:
                return None
            raise ValueError('truncated-pcm-command')
        data.extend(block)
    return bytes(data)


def analyze(pcm):
    """Recognize the fixture's stereo 1kHz-left/2kHz-right signal, including phase shifts."""
    if len(pcm) % 4 or len(pcm) > MAX_STREAM_BYTES:
        raise ValueError('invalid-captured-pcm-length')
    samples = array('h', pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    frames = len(samples) // 2
    # Integral sample periods avoid phase accumulation over a long capture.
    oscillators = [(tuple(math.cos(2 * math.pi * i / period) for i in range(period)),
                    tuple(math.sin(2 * math.pi * i / period) for i in range(period))) for period in (48, 24)]
    energy = [0, 0]
    strong = [0, 0]
    real = [[0.0, 0.0], [0.0, 0.0]]
    imaginary = [[0.0, 0.0], [0.0, 0.0]]
    for i in range(frames):
        for channel in range(2):
            value = samples[i * 2 + channel]
            energy[channel] += value * value
            strong[channel] += abs(value) >= 256
            for tone, (cosine, sine) in enumerate(oscillators):
                index = i % len(cosine)
                real[channel][tone] += value * cosine[index]
                imaginary[channel][tone] += value * sine[index]
    amplitudes = [[2 * math.hypot(real[ch][tone], imaginary[ch][tone]) / max(1, frames)
                   for tone in range(2)] for ch in range(2)]
    passed = all(strong[ch] >= 72000 and amplitudes[ch][ch] >= 500 and
                 amplitudes[ch][ch] > 8 * amplitudes[ch][1 - ch] for ch in range(2))
    return dict(frames=frames, strongSamples=strong,
                rms=[math.sqrt(value / max(1, frames)) for value in energy],
                amplitudes1k2k=amplitudes, knownStereoSignalMatched=passed)


class PcmCapture:
    """Own one private socket and bounded workers; no replacement of an existing endpoint."""
    def __init__(self, path):
        self.path = Path(path)
        parent = self.path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077 or
                self.path.parent.resolve() != self.path.parent):
            raise ValueError('pcm-directory-must-be-private-and-owned')
        if len(os.fsencode(self.path)) >= 108 or not self.path.is_absolute() or os.path.lexists(self.path):
            raise ValueError('pcm-endpoint-invalid-or-existing')
        self.lock = threading.Lock()
        self.closed = False
        self.connections = set()
        self.workers = []
        self.streams = []
        self.failures = []
        self.total_bytes = 0
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.identity = None
        try:
            self.listener.bind(str(self.path))
            owned = self.path.lstat()
            self.identity = (owned.st_dev, owned.st_ino)
            self.path.chmod(0o600)
            self.listener.listen(MAX_CONNECTIONS)
            self.listener.settimeout(.2)
            self.acceptor = threading.Thread(target=self._accept, daemon=True)
            self.acceptor.start()
        except BaseException:
            self.listener.close()
            self._unlink()
            raise

    def _unlink(self):
        if self.identity is None:
            return
        try:
            actual = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(actual.st_mode) or (actual.st_dev, actual.st_ino) != self.identity:
            raise ValueError('pcm-endpoint-ownership-changed')
        self.path.unlink()

    def _accept(self):
        try:
            while not self.closed:
                try:
                    connection, _ = self.listener.accept()
                except socket.timeout:
                    continue
                with self.lock:
                    if self.closed or len(self.connections) >= MAX_CONNECTIONS or len(self.streams) >= MAX_STREAMS:
                        connection.close()
                        if not self.closed and 'pcm-connection-limit' not in self.failures:
                            self.failures.append('pcm-connection-limit')
                        continue
                    try:
                        _, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
                    except OSError:
                        connection.close()
                        raise
                    if uid != os.geteuid():
                        connection.close()
                        if 'pcm-peer-uid-mismatch' not in self.failures:
                            self.failures.append('pcm-peer-uid-mismatch')
                        continue
                    stream = dict(pcm=bytearray(), commands=0, configured=False, cleanEof=False)
                    self.streams.append(stream)
                    self.connections.add(connection)
                    worker = threading.Thread(target=self._stream, args=(connection, stream), daemon=True)
                    self.workers.append(worker)
                    worker.start()
        except OSError as error:
            if not self.closed:
                self.failures.append('pcm-listener-failed:' + type(error).__name__)

    def _stream(self, connection, stream):
        try:
            connection.settimeout(3)
            header = receive(connection, 20, allow_eof=True)
            if header is None:
                stream['cleanEof'] = True
                return
            magic, version, rate, channels, capacity = struct.unpack('<5I', header)
            if (magic, version, rate, channels) != (0x50414c54, 1, RATE, 2):
                raise ValueError('pcm-handshake-mismatch')
            clock = PlaybackClock(capacity)
            stream['configured'] = True
            connection.sendall(struct.pack('<I', 0))
            while not self.closed:
                command = receive(connection, 4, allow_eof=True)
                if command is None:
                    stream['cleanEof'] = True
                    break
                command, = struct.unpack('<I', command)
                stream['commands'] += 1
                reply = 0
                if command == 1:
                    clock.start()
                elif command in (2, 5):
                    clock.reset()
                elif command == 3:
                    reply = clock.head()
                elif command == 4:
                    count, = struct.unpack('<I', receive(connection, 4))
                    if not 1 <= count <= 4096:
                        raise ValueError('pcm-write-limit')
                    block = receive(connection, count * 4)
                    reply = clock.write(count)
                    selected = block[:reply * 4]
                    with self.lock:
                        if len(stream['pcm']) + len(selected) > MAX_STREAM_BYTES or self.total_bytes + len(selected) > MAX_TOTAL_BYTES:
                            raise ValueError('pcm-capture-byte-limit')
                        stream['pcm'].extend(selected)
                        self.total_bytes += len(selected)
                else:
                    raise ValueError('pcm-command-unknown')
                connection.sendall(struct.pack('<I', reply))
        except (OSError, ValueError) as error:
            if not self.closed:
                stream['failure'] = str(error)
        finally:
            connection.close()
            with self.lock:
                self.connections.discard(connection)

    def wait_eof(self, timeout):
        """Allow already-connected producers to reach EOF before forced local cleanup."""
        deadline = time.monotonic() + timeout
        with self.lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        return all(not worker.is_alive() for worker in workers)

    def close(self):
        self.closed = True
        self.listener.close()
        deadline = time.monotonic() + 4
        self.acceptor.join(max(0, deadline - time.monotonic()))
        with self.lock:
            connections = list(self.connections)
            workers = list(self.workers)
        for connection in connections:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        if self.acceptor.is_alive() or any(worker.is_alive() for worker in workers):
            raise ValueError('pcm-workers-did-not-stop')
        self._unlink()

    def report(self, output, prefix='captured'):
        if not self.closed or any(worker.is_alive() for worker in self.workers):
            raise ValueError('pcm-capture-must-be-stopped-before-report')
        if not prefix or any(character not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for character in prefix):
            raise ValueError('pcm-capture-prefix-invalid')
        output = Path(output)
        reports = []
        for index, stream in enumerate(self.streams):
            name = f'{prefix}-{index:02d}.s16le'
            with (output / name).open('xb') as capture:
                capture.write(stream['pcm'])
            value = {key: value for key, value in stream.items() if key != 'pcm'}
            value.update(analyze(stream['pcm']), file=name, bytes=len(stream['pcm']),
                         sha256=hashlib.sha256(stream['pcm']).hexdigest())
            reports.append(value)
        clean = not self.failures and all('failure' not in stream and stream['cleanEof'] for stream in self.streams)
        return dict(scope='linux-fmod-wine-alsa-pcm-capture-only', playbackClock='simulated-monotonic',
                    androidAudioQualified=False, audibleOutputQualified=False, physicalLatencyQualified=False,
                    failures=list(self.failures), totalBytes=self.total_bytes, streams=reports,
                    pcmSignalQualified=bool(clean and any(stream['knownStereoSignalMatched'] for stream in reports)))
