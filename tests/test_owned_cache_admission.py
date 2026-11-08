"""Production admission on a disposable, fully published server-data fixture."""
import multiprocessing
import os
import unittest
from unittest.mock import patch

from runtime import prepared_data_cache as cache
from tests import test_prepared_data_cache as fixtures


def hold_writer_lock(path, ready, release):
    import fcntl
    with path.open('a+b') as lock:
        fcntl.lockf(lock,fcntl.LOCK_EX)
        ready.set()
        release.wait(30)


class OwnedCacheAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.PreparedDataCacheTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scratch=self.fixture.root/'operation'
        self.scratch.mkdir(mode=0o700)
        self.lock=self.scratch/'owner.lock'
        self.lock.touch(mode=0o600)
        self.ready=multiprocessing.Event()
        self.release=multiprocessing.Event()
        self.owner=multiprocessing.Process(target=hold_writer_lock,args=(self.lock,self.ready,self.release))
        self.owner.start()
        self.addCleanup(self.stop_owner)
        self.assertTrue(self.ready.wait(5))
        self.root=self.fixture.selected
        self.receipt=self.fixture.receipt
        self.inputs=self.receipt['inputs']
        self.pin=self.fixture.receipt_pin

    def stop_owner(self):
        self.release.set()
        self.owner.join(10)
        self.assertFalse(self.owner.is_alive())

    def seal(self):
        fs=cache.OwnedFilesystem(self.root,self.scratch)
        return cache.seal(self.root,self.receipt['generation'],self.pin,self.fixture.helper,
                          self.scratch/'cache.jsonl',expected_inputs=self.inputs,filesystem=fs)['cache']

    def admit(self, proof, **options):
        return cache.admit(self.root,self.inputs,self.pin,self.scratch,proof,**options)

    def test_warm_admission_requires_the_current_owner_and_observes_every_node(self):
        proof=self.seal()
        with patch.object(cache.data,'verify_completed',side_effect=AssertionError('unexpected payload audit')):
            self.assertEqual(self.admit(proof),self.receipt)
        self.stop_owner()
        with patch.object(cache.data,'verify_completed',wraps=cache.data.verify_completed) as full:
            self.assertEqual(self.admit(proof),self.receipt)
            self.assertEqual(full.call_count,1)
        self.assertFalse((self.scratch/'stale').exists())

    def test_added_hardlink_falls_back_without_adopting_it(self):
        proof=self.seal()
        os.link(self.root/'data/dbc/Map.dbc',self.scratch/'external')
        with patch.object(cache.data,'verify_completed',wraps=cache.data.verify_completed) as full:
            self.assertEqual(self.admit(proof),self.receipt)
            self.assertEqual(full.call_count,1)
        self.assertTrue((self.scratch/'stale').exists())
        (self.scratch/'cache.jsonl').unlink()
        with self.assertRaisesRegex(ValueError,'hard link'):
            self.seal()

    def test_same_size_with_restored_mtime_is_refused_by_full_fallback(self):
        proof=self.seal()
        leaf=self.root/'data/dbc/Map.dbc'
        st=leaf.stat()
        raw=bytearray(leaf.read_bytes());raw[-1]^=1
        leaf.write_bytes(raw)
        os.utime(leaf,ns=(st.st_atime_ns,st.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'prepared server data changed'):
            self.admit(proof)
        self.assertFalse((self.scratch/'stale').exists())

    def test_cancelled_verification_does_not_start_full_fallback(self):
        proof=self.seal()
        with patch.object(cache.data,'verify_completed',side_effect=AssertionError('cancel became a full audit')):
            with self.assertRaisesRegex(ValueError,'cancelled'):
                self.admit(proof,cancelled=lambda:True)
        self.assertFalse((self.scratch/'stale').exists())
        self.assertEqual(self.admit(proof),self.receipt)

    def test_missing_or_invalid_index_performs_full_verification(self):
        for pin in (None,{'bytes':3,'sha256':'a'*64}):
            with patch.object(cache.data,'verify_completed',wraps=cache.data.verify_completed) as full:
                self.assertEqual(self.admit(pin),self.receipt)
                self.assertEqual(full.call_count,1)
