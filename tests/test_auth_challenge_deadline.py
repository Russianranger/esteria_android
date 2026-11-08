"""Loopback tests for the one outstanding build-12340 auth readiness request."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import socket
import threading
import time
import unittest

from runtime import server_session_process as process


class AuthChallengeDeadlineTests(unittest.TestCase):
    @contextmanager
    def server(self, reply):
        """Accept only one request. The real client must close it without sending further bytes."""
        received = threading.Event()
        with socket.socket() as listener, ThreadPoolExecutor(max_workers=1) as worker:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            listener.settimeout(4)
            def serve():
                with listener.accept()[0] as peer:
                    peer.settimeout(4)
                    data = bytearray()
                    while len(data) < 50:
                        part = peer.recv(50 - len(data))
                        self.assertTrue(part)
                        data.extend(part)
                    self.assertEqual(data[33:38], b'\x10ERDY')
                    received.set()
                    reply(peer)
                    self.assertEqual(peer.recv(1), b'')
                listener.setblocking(False)
                with self.assertRaises(BlockingIOError):
                    listener.accept()
            result = worker.submit(serve)
            try:
                yield listener.getsockname()[1], received
            finally:
                result.result(timeout=5)

    def test_pending_sql_reply_after_one_second_on_original_connection(self):
        def reply(peer):
            peer.sendall(b'\0')
            time.sleep(1.15)
            peer.sendall(b'\0\4')
        checks = []
        with self.server(reply) as (port, received):
            self.assertTrue(process.auth_challenge(port, deadline=time.monotonic() + 4,
                                                  check_pending=lambda: checks.append(received.is_set())))
            self.assertGreaterEqual(checks.count(True), 2)

    def test_wrong_prefix_and_early_eof_are_immediate_failures(self):
        def early_eof(peer):
            peer.sendall(b'\0')
            peer.shutdown(socket.SHUT_WR)
        for reply, message in ((lambda p: p.sendall(b'\x01'), 'differs'), (early_eof, 'ended')):
            with self.subTest(message=message), self.server(reply) as (port, _):
                with self.assertRaisesRegex(ValueError, message):
                    process.auth_challenge(port, deadline=time.monotonic() + 3, check_pending=lambda: None)

    def test_pending_probe_cancels_with_silent_peer_before_overall_deadline(self):
        with self.server(lambda p: p.sendall(b'\0')) as (port, received):
            def cancel():
                if received.is_set():
                    raise ValueError('auth owner cancelled')
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'auth owner cancelled'):
                process.auth_challenge(port, deadline=started + 3, check_pending=cancel)
            self.assertLess(time.monotonic() - started, 2)

    def test_partial_reply_never_extends_the_original_deadline(self):
        with self.server(lambda p: p.sendall(b'\0\0')) as (port, _):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                process.auth_challenge(port, deadline=started + .35, check_pending=lambda: None)
            self.assertLess(time.monotonic() - started, 1.5)

    def test_expiry_during_initial_owner_check_opens_no_connection(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            with self.assertRaises(TimeoutError):
                process.auth_challenge(listener.getsockname()[1], deadline=time.monotonic() + .05,
                                       check_pending=lambda: time.sleep(.08))
            listener.setblocking(False)
            with self.assertRaises(BlockingIOError):
                listener.accept()

    def test_standalone_short_deadline_and_guarded_long_wait(self):
        with self.server(lambda peer: None) as (port, _):
            with self.assertRaises(TimeoutError):
                process.auth_challenge(port, timeout=.12)
        for options in ({'timeout': 4}, {'deadline': time.monotonic() + 4},
                        {'check_pending': lambda: None},
                        {'deadline': time.monotonic() + 601, 'check_pending': lambda: None}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                process.auth_challenge(**options)
