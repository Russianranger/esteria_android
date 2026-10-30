import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db


class MysqlStateLeases(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.state = Path(temporary.name) / 'state'

    def test_nested_real_lease_never_relocks_and_outer_lock_remains_exclusive(self):
        with db.state_lock(self.state) as lease:
            with patch.object(db.fcntl, 'flock', side_effect=AssertionError('nested scope must not relock')):
                with db.state_scope(self.state, lease) as nested:
                    self.assertIs(nested, lease)
                    with db.state_scope(self.state, nested): pass
            for acquire in (db.state_lock, db.state_scope):
                with self.assertRaisesRegex(db.BootstrapError, 'Another bootstrap operation'):
                    with acquire(self.state): self.fail('outer lock was released')
        with db.state_scope(self.state) as next_lease:
            self.assertIsNot(next_lease, lease)

    def test_wrong_state_expired_and_source_constructed_tokens_are_refused(self):
        with db.state_lock(self.state) as lease:
            wrong = self.state.parent / 'other'
            with self.assertRaises(db.BootstrapError):
                with db.state_scope(wrong, lease): pass
            self.assertFalse(wrong.exists())
            for fake in (True, object(), {}, db._StateLease()):
                with self.subTest(fake=type(fake).__name__), self.assertRaises(db.BootstrapError):
                    with db.state_scope(self.state, fake): pass
        with self.assertRaises(db.BootstrapError):
            with db.state_scope(self.state, lease): pass

    def test_lease_cannot_cross_thread(self):
        errors = []
        with db.state_lock(self.state) as lease:
            def worker():
                try:
                    with db.state_scope(self.state, lease): self.fail('cross-thread token accepted')
                except BaseException as error: errors.append(error)
            thread = threading.Thread(target=worker); thread.start(); thread.join(5)
            self.assertFalse(thread.is_alive()); self.assertEqual(len(errors), 1)
            self.assertIsInstance(errors[0], db.BootstrapError)

    @unittest.skipUnless(hasattr(os, 'fork'), 'fork process identity guard')
    def test_inherited_lease_cannot_cross_pid(self):
        with db.state_lock(self.state) as lease:
            child = os.fork()
            if child == 0:
                try:
                    with db.state_scope(self.state, lease): pass
                except db.BootstrapError: os._exit(0)
                except BaseException: os._exit(2)
                os._exit(1)
            _, status = os.waitpid(child, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_closed_fd_or_replaced_lock_path_invalidates_token(self):
        with self.assertRaises(db.BootstrapError):
            with db.state_lock(self.state) as lease:
                os.close(db._STATE_LEASES[lease]['fd'])
                with db.state_scope(self.state, lease): pass
        with self.assertRaises(db.BootstrapError):
            with db.state_lock(self.state) as lease:
                path = self.state / '.mysql-bootstrap.lock'
                path.rename(path.with_name('retained-old-lock'))
                path.write_bytes(b''); path.chmod(0o600)
                with db.state_scope(self.state, lease): pass

    def test_reuse_checks_token_after_nested_body(self):
        with self.assertRaisesRegex(db.BootstrapError, 'identity changed'):
            with db.state_lock(self.state) as lease:
                with db.state_scope(self.state, lease):
                    (self.state / '.mysql-bootstrap.lock').chmod(0o644)


if __name__ == '__main__': unittest.main()
