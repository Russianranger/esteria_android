"""Actual Linux stat/hash mutation tests. Synthetic headers are not game assets."""
import copy
import hashlib
import json
import os
from pathlib import Path
import stat
import time
import tracemalloc
import unittest
from unittest.mock import patch
from runtime import prepared_data_cache as cache
from tests import test_server_data_generation as fixtures


class PreparedDataCacheTests(unittest.TestCase):
    generate=fixtures.ServerDataGenerationTests.generate
    fake_execute=fixtures.ServerDataGenerationTests.fake_execute

    def setUp(self):
        fixtures.ServerDataGenerationTests.setUp(self)
        with patch.object(cache.data,'execute',side_effect=self.fake_execute):self.receipt=self.generate()
        self.selected=self.store/'generations'/self.receipt['generation']
        self.receipt_pin=cache.data.storage.identity(self.selected/'receipt.json',64<<20)
        self.helper=cache.data.preparation_helper_generation()
        self.output=self.root/'candidate.jsonl'

    def seal(self):
        return cache.seal(self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.output)

    def verify(self,pin):
        return cache.verify(self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.output,pin)

    def modify(self,action):
        proof=self.seal();action()
        with self.assertRaises(ValueError):self.verify(proof['cache'])

    def test_initial_full_seal_and_cached_compare_read_no_payload_bytes(self):
        proof=self.seal();self.assertTrue(proof['fullStableFdHashesVerified']);self.assertTrue(proof['headerPreflightVerified'])
        original=cache.stable_hash;reads=[]
        def tracked(path,*args,**kwargs):reads.append(path);return original(path,*args,**kwargs)
        with patch.object(cache,'stable_hash',side_effect=tracked),\
                patch.object(cache.data,'inventory',side_effect=AssertionError('warm cache must not rehash data')),\
                patch.object(cache.data.formats,'check_server_data',side_effect=AssertionError('warm cache must not reparse payload headers')):
            checked=self.verify(proof['cache'])
        self.assertEqual(checked['payloadBytesRead'],0)
        self.assertTrue(all(path==self.selected/'receipt.json' for path in reads))
        self.assertFalse(checked['productionFastPathEnabled']);self.assertFalse(cache.PRODUCTION_FAST_PATH_ENABLED)

    def test_same_length_write_with_restored_mtime_rejects_changed_ctime(self):
        path=self.selected/'data/dbc/Map.dbc';before=path.stat()
        def action():
            time.sleep(.01);raw=path.read_bytes();path.write_bytes(raw[:-1]+b'x')
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertEqual(path.stat().st_size,before.st_size);self.assertEqual(path.stat().st_mtime_ns,before.st_mtime_ns)
            self.assertNotEqual(path.stat().st_ctime_ns,before.st_ctime_ns)
        self.modify(action)

    def test_mtime_and_mode_and_link_count_mutations_each_fail_closed(self):
        for kind in ('mtime','mode','link'):
            with self.subTest(kind=kind):
                self.output.unlink(missing_ok=True);proof=self.seal();path=self.selected/'data/dbc/Map.dbc';before=path.stat()
                if kind=='mtime':os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns+1000000))
                elif kind=='mode':os.chmod(path,stat.S_IMODE(before.st_mode)^0o100)
                else:os.link(path,self.root/'external-link')
                with self.assertRaises(ValueError):self.verify(proof['cache'])

    def test_identical_byte_inode_replacement_fails_closed(self):
        path=self.selected/'data/dbc/Map.dbc';before=path.stat()
        def action():
            replacement=path.with_suffix('.replace');replacement.write_bytes(path.read_bytes())
            os.utime(replacement,ns=(before.st_atime_ns,before.st_mtime_ns));os.replace(replacement,path)
            self.assertNotEqual(path.stat().st_ino,before.st_ino)
        self.modify(action)

    def test_directory_entry_changes_even_with_restored_mtime_fail_closed(self):
        empty=self.selected/'data/empty';empty.mkdir();before=empty.stat()
        def action():
            time.sleep(.01);path=empty/'unrecorded';path.write_bytes(b'x');path.unlink()
            os.utime(empty,ns=(before.st_atime_ns,before.st_mtime_ns))
            self.assertEqual(empty.stat().st_mtime_ns,before.st_mtime_ns)
            self.assertNotEqual(empty.stat().st_ctime_ns,before.st_ctime_ns)
        self.modify(action)

    def test_regular_and_ancestor_symlinks_are_rejected_without_following_them(self):
        for ancestor in (False,True):
            with self.subTest(ancestor=ancestor):
                self.output.unlink(missing_ok=True);proof=self.seal()
                path=self.selected/('data/dbc' if ancestor else 'data/dbc/Map.dbc')
                saved=path.with_name(path.name+'-saved');path.rename(saved);path.symlink_to(saved)
                with self.assertRaises(ValueError):self.verify(proof['cache'])
                path.unlink();saved.rename(path)

    def test_foreign_receipt_helper_generation_and_cache_pin_cannot_be_relabelled(self):
        proof=self.seal()
        for role in ('receipt','helper','generation','cache'):
            with self.subTest(role=role):
                args=[self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.output,proof['cache']]
                if role=='receipt':args[2]=dict(self.receipt_pin,sha256='0'*64)
                elif role=='helper':args[3]='0'*64
                elif role=='generation':args[1]='0'*64
                else:args[5]=dict(proof['cache'],sha256='0'*64)
                with self.assertRaises(ValueError):cache.verify(*args)

    def test_missing_truncated_mutated_private_cache_is_not_its_own_authority(self):
        proof=self.seal();original=self.output.read_bytes()
        for kind in ('truncated','extra','mutated','mode','hardlink'):
            with self.subTest(kind=kind):
                self.output.write_bytes(original);os.chmod(self.output,0o600)
                if kind=='truncated':self.output.write_bytes(original[:-1])
                elif kind=='extra':self.output.write_bytes(original+b'{}\n')
                elif kind=='mutated':self.output.write_bytes(original.replace(b'file',b'xxxx',1))
                elif kind=='mode':os.chmod(self.output,0o644)
                else:os.link(self.output,self.root/'cache-link')
                with self.assertRaises(ValueError):self.verify(proof['cache'])
                if kind=='hardlink':(self.root/'cache-link').unlink()
        self.output.unlink()
        with self.assertRaises((ValueError,FileNotFoundError)):self.verify(proof['cache'])

    def test_forged_canonical_rows_still_require_types_closure_and_real_receipt_identity(self):
        proof=self.seal();original=self.output.read_bytes();rows=[json.loads(line) for line in original.splitlines()]
        for kind in ('boolean-schema','duplicate','parent','hash','special-type'):
            with self.subTest(kind=kind):
                changed=copy.deepcopy(rows)
                if kind=='boolean-schema':changed[0]['formatVersion']=True
                elif kind=='duplicate':changed.insert(2,copy.deepcopy(changed[1]))
                elif kind=='parent':changed[1]['path']='../foreign'
                elif kind=='hash':next(row for row in changed if row.get('kind')=='file')['sha256']='0'*64
                else:changed[1]['stat']['mode']=stat.S_IFIFO|0o600
                raw=b''.join(cache.encoded(row) for row in changed);self.output.write_bytes(raw)
                with self.assertRaises(ValueError):self.verify(cache.identity(raw))

    def test_partial_cancelled_or_failed_seal_never_publishes_candidate(self):
        with self.assertRaisesRegex(ValueError,'cancelled'):
            cache.seal(self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.output,cancelled=lambda:True)
        self.assertFalse(self.output.exists());self.assertFalse(list(self.root.glob('.candidate.jsonl-*')))
        path=self.selected/'data/dbc/Map.dbc';path.write_bytes(path.read_bytes()[:-1]+b'x')
        with self.assertRaisesRegex(ValueError,'bytes differ'):self.seal()
        self.assertFalse(self.output.exists())

    def test_full_recovery_can_reseal_unchanged_bytes_and_preserves_previous_proof(self):
        first=self.seal();original=self.output.read_bytes();self.output=self.root/'second.jsonl'
        path=self.selected/'data/dbc/Map.dbc';before=path.stat();os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns+1000000))
        with self.assertRaises(ValueError):cache.verify(self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.root/'candidate.jsonl',first['cache'])
        second=self.seal();self.assertNotEqual(first['cache'],second['cache']);self.verify(second['cache'])
        self.assertEqual((self.root/'candidate.jsonl').read_bytes(),original)
        self.assertEqual(cache.data.storage.identity(self.selected/'receipt.json',64<<20),self.receipt_pin)

    def test_large_file_streams_without_materializing_payload(self):
        path=self.selected/'data/vmaps/000.vmtree'
        with path.open('wb') as output:
            output.write(b'VMAP_4.8')
            for _ in range(512):output.write(b'x'*(128<<10))
        self.receipt['files']['vmaps/000.vmtree']=cache.data.storage.identity(path,cache.data.MAX_FILE)
        (self.selected/'receipt.json').write_bytes(cache.encoded(self.receipt))
        self.receipt_pin=cache.data.storage.identity(self.selected/'receipt.json',64<<20)
        tracemalloc.start()
        try:self.seal();_,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,8<<20)

    def test_tiny_metadata_read_does_not_allocate_configured_maximum(self):
        # Production metadata validation uses a 64 MiB ceiling; a tiny receipt
        # must not allocate that ceiling before JSON parsing.
        tracemalloc.start()
        try:
            self.assertEqual(cache.data.document(self.selected/'receipt.json'),self.receipt)
            _,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertLess(peak,512<<10)

    def test_existing_output_and_inside_generation_cache_are_preserved_or_refused(self):
        self.output.write_bytes(b'preserve')
        with self.assertRaises(ValueError):self.seal()
        self.assertEqual(self.output.read_bytes(),b'preserve')
        with self.assertRaises(ValueError):cache.seal(self.selected,self.receipt['generation'],self.receipt_pin,self.helper,self.selected/'cache.jsonl')

    def test_candidate_published_by_another_operation_is_never_replaced(self):
        link=os.link
        def competing_publish(source,target,**options):
            self.assertEqual(target,self.output)
            target.write_bytes(b'concurrent retained proof\n')
            return link(source,target,**options)
        with patch.object(cache.os,'link',side_effect=competing_publish):
            with self.assertRaisesRegex(ValueError,'exclusive name'):self.seal()
        self.assertEqual(self.output.read_bytes(),b'concurrent retained proof\n')
        self.assertFalse(list(self.root.glob('.candidate.jsonl-*')))


if __name__=='__main__':unittest.main()
