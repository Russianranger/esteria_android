from array import array
import math
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import pcm_capture as pcm


def signal(frames=96000, swapped=False):
    values = array('h')
    for i in range(frames):
        pair = (int(8192 * math.sin(2 * math.pi * (i % 48) / 48)),
                int(8192 * math.sin(2 * math.pi * (i % 24) / 24)))
        values.extend(pair[::-1] if swapped else pair)
    if sys.byteorder != 'little':
        values.byteswap()
    return values.tobytes()


class PcmCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def connect(self, capture):
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(connection.close)
        connection.settimeout(5)
        connection.connect(str(capture.path))
        connection.sendall(struct.pack('<5I', 0x50414c54, 1, 48000, 2, 48000))
        self.assertEqual(pcm.receive(connection, 4), b'\0' * 4)
        return connection

    def require_sockets(self):
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.close()
        except PermissionError:
            if os.environ.get('CI') == 'true' or os.environ.get('ESTERIA_REQUIRE_SOCKET_TESTS') == '1':
                raise
            self.skipTest('This host denies AF_UNIX creation; actual socket qualification requires CI')

    def stop_cleanly(self, capture):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with capture.lock:
                if not capture.connections:
                    break
            time.sleep(.005)
        capture.close()

    def test_clock_partial_writes_pause_wrap_and_underrun_do_not_replay(self):
        now = [0]
        clock = pcm.PlaybackClock(480, lambda: now[0])
        self.assertEqual(clock.write(600), 480)
        clock.start()
        now[0] += 5_000_000
        self.assertEqual(clock.head(), 240)
        self.assertEqual(clock.write(480), 240)
        now[0] += 1_000_000_000
        self.assertEqual(clock.head(), 720)
        self.assertEqual(clock.write(120), 120)
        self.assertEqual(clock.head(), 720)  # underrun time cannot consume newly accepted samples
        clock.reset()
        self.assertEqual(clock.head(), 0)
        self.assertEqual(clock.write(480), 480)
        now[0] += 10_000_000
        self.assertEqual(clock.head(), 0)  # reset is paused
        clock.played = clock.written = 0x100000005
        self.assertEqual(clock.head(), 5)

    def test_spectral_guard_rejects_silence_swapped_and_too_short_signals(self):
        self.assertTrue(pcm.analyze(signal())['knownStereoSignalMatched'])
        self.assertFalse(pcm.analyze(signal(swapped=True))['knownStereoSignalMatched'])
        self.assertFalse(pcm.analyze(b'\0' * 384000)['knownStereoSignalMatched'])
        self.assertFalse(pcm.analyze(signal(frames=12000))['knownStereoSignalMatched'])

    def test_real_socket_stream_captures_partial_write_retries_and_channel_content(self):
        self.require_sockets()
        capture = pcm.PcmCapture(self.root / 'audio.sock')
        self.addCleanup(capture.close)
        connection = self.connect(capture)
        connection.sendall(struct.pack('<I', 1))
        self.assertEqual(pcm.receive(connection, 4), b'\0' * 4)
        payload = signal()
        offset = 0
        deadline = time.monotonic() + 6
        saw_partial = False
        while offset < len(payload) and time.monotonic() < deadline:
            block = payload[offset:offset + 4096 * 4]
            connection.sendall(struct.pack('<2I', 4, len(block) // 4) + block)
            accepted, = struct.unpack('<I', pcm.receive(connection, 4))
            self.assertLessEqual(accepted * 4, len(block))
            saw_partial |= accepted * 4 < len(block)
            offset += accepted * 4
            if accepted * 4 < len(block):
                time.sleep(.002)
        self.assertEqual(offset, len(payload))
        self.assertTrue(saw_partial)
        connection.close()
        self.stop_cleanly(capture)
        report = capture.report(self.root)
        self.assertTrue(report['pcmSignalQualified'])
        self.assertFalse(report['androidAudioQualified'])
        self.assertEqual((self.root / report['streams'][0]['file']).read_bytes(), payload)

    def test_truncated_and_oversized_commands_fail_without_large_allocation(self):
        self.require_sockets()
        for index, payload in enumerate((b'\x04\0', struct.pack('<2I', 4, 0xffffffff))):
            capture = pcm.PcmCapture(self.root / f'audio-{index}.sock')
            connection = self.connect(capture)
            connection.sendall(payload)
            connection.close()
            self.stop_cleanly(capture)
            destination = self.root / str(index)
            destination.mkdir()
            report = capture.report(destination)
            self.assertFalse(report['pcmSignalQualified'])
            self.assertIn('failure', report['streams'][0])
            self.assertEqual(report['totalBytes'], 0)

    def test_capture_cap_and_endpoint_identity_are_enforced(self):
        self.require_sockets()
        capture = pcm.PcmCapture(self.root / 'audio.sock')
        connection = self.connect(capture)
        with patch.object(pcm, 'MAX_STREAM_BYTES', 8):
            connection.sendall(struct.pack('<2I', 4, 4) + b'\0' * 16)
            self.assertEqual(connection.recv(4), b'')
        connection.close()
        self.stop_cleanly(capture)
        self.assertEqual(capture.streams[0]['failure'], 'pcm-capture-byte-limit')
        self.assertEqual(capture.total_bytes, 0)
        path = self.root / 'owned.sock'
        second = pcm.PcmCapture(path)
        with self.assertRaisesRegex(ValueError, 'existing'):
            pcm.PcmCapture(path)
        path.unlink()
        path.write_text('unrelated replacement')
        with self.assertRaisesRegex(ValueError, 'ownership-changed'):
            second.close()
        self.assertEqual(path.read_text(), 'unrelated replacement')


if __name__ == '__main__':
    unittest.main()
