import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock
from tools import release_wine_cohort as release


class CohortRelease(unittest.TestCase):
    def test_new_selected_schema_does_not_change_historical_two_input_validator(self):
        self.assertEqual(set(release.selected_inputs()),{'sources.lock.json','runtime/client/android-provider.lock.json','runtime/runtime-sources.lock.json'})
        self.assertEqual(release.original.SELECTED_INPUT_PATHS,{'sources.lock.json','runtime/client/android-provider.lock.json'})
        self.assertNotEqual(release.TAG,release.original.load_lock()[0]['tag'])

    def test_existing_output_refused_before_recipe_network_or_source_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'sentinel').write_text('preserve')
            with mock.patch.object(release,'recipe_inputs',side_effect=AssertionError('existing output consumed')):
                with self.assertRaises(ValueError):release.stage(path,path/'unused','a'*40,path)
            api=mock.Mock()
            with self.assertRaises(ValueError):release.prepare(path,path,path,api)
            api.json.assert_not_called();self.assertEqual((path/'sentinel').read_text(),'preserve')

    def test_compiler_sources_use_original_archive_paths_without_selecting_mesa(self):
        names=release.shader_source_names()
        self.assertEqual(len(names),3)
        self.assertTrue(all(name.startswith('corresponding-source/original-archives/') for name in names))
        self.assertFalse(any('mesa' in name.lower() for name in names))

    def test_old_two_key_source_receipt_is_not_relabelled_as_new_three_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'archive').write_bytes(b'x')
            value=dict(formatVersion=1,scope='retained-reconstructed-client-source-inputs',archiveReadBack=True,
                archive=release.identity(path/'archive'),gameplayQualified=False,androidRuntimeQualified=False,
                selectedInputs={k:v for k,v in release.selected_inputs().items() if k!='runtime/runtime-sources.lock.json'})
            (path/'receipt').write_bytes(release.encoded(value))
            with mock.patch.object(release,'read_archive',side_effect=AssertionError('misbound source parsed')):
                with self.assertRaisesRegex(ValueError,'exact-three'):
                    release.source_receipt(path,'archive','receipt',release.selected_inputs())

    def test_full_source_inventory_readback_rejects_links_traversal_duplicates_and_changed_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);inventory={'plain':dict(bytes=3,sha256=hashlib.sha256(b'abc').hexdigest())}
            for number,kind in enumerate(('valid','link','traversal','duplicate','changed')):
                path=root/str(number)
                with tarfile.open(path,'w:gz') as archive:
                    entry=tarfile.TarInfo('../escape' if kind=='traversal' else 'plain');entry.mode=0o444;entry.size=3
                    if kind=='link':entry.type=tarfile.SYMTYPE;entry.linkname='/private';entry.size=0
                    archive.addfile(entry,None if kind=='link' else io.BytesIO(b'bad' if kind=='changed' else b'abc'))
                    if kind=='duplicate':archive.addfile(entry,io.BytesIO(b'abc'))
                if kind=='valid':release.read_archive(path,inventory)
                else:
                    with self.subTest(kind=kind),self.assertRaises(ValueError):release.read_archive(path,inventory)
            self.assertFalse((root/'escape').exists())

    def test_whole_payload_hash_precedes_any_archive_or_receipt_parser(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in release.ALL_FILES:(root/name).write_bytes(b'changed')
            lock=dict(files={name:dict(bytes=7,sha256='0'*64) for name in release.PAYLOAD})
            with mock.patch.object(release,'validate_payload',side_effect=AssertionError('unverified archive parsed')):
                with self.assertRaises(ValueError):release.verify(root,lock)

    def test_publication_inherits_no_create_no_overwrite_policy(self):
        lock=dict(tag=release.TAG,targetCommit='a'*40);api=mock.Mock()
        publisher=release.PUBLICATION.DraftPublication(lock,release.body(lock),lambda path:{'asset':dict(bytes=1,sha256='b'*64)})
        api.json.return_value=[]
        with self.assertRaisesRegex(ValueError,'exact-owned-UI-draft-required'):publisher.upload_draft(api,Path('/unused'))
        api.upload.assert_not_called()
        with self.assertRaisesRegex(ValueError,'identity-mismatch'):
            publisher.check_release(dict(tag_name='old-tag',prerelease=True,body=release.body(lock)))


if __name__=='__main__':unittest.main()
