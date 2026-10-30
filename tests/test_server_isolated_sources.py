"""Git-free preparation guards; fixtures never qualify a source rebuild."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_server_isolated_sources as isolated


def pin(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def archive(path, members):
    inventory = {}
    with path.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as tar:
            for name, data in members.items():
                info = isolated.package.tar_info(name, len(data)); tar.addfile(info, io.BytesIO(data))
                inventory[name] = pin(data)
    return inventory


def build_record():
    version = 'AzerothCore rev. f35f04d01689+ 2026-10-28 12:35:08 -0500 (HEAD branch) (Unix, RelWithDebInfo, Static)'
    return dict(serverSource={'commit':'f35f04d01689f034778e3474b3c820092f51e461'},
                hostLoaderSmoke={'qualified':True,'outputs':{'authserver':version,'worldserver':version}})


class IsolatedArchiveGuards(unittest.TestCase):
    def test_regular_archive_readback_and_provenance_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); stage=root/'stage'; stage.mkdir(); path=root/'inputs.tar.gz'
            rows=archive(path,{'source/src/main.cpp':b'// synthetic source\n',
                'integration/LICENSE':b'fixture notice\n','metadata/source-inputs.json':b'{"fixture":true}\n'})
            isolated.extract_verified(path,rows,stage)
            self.assertEqual((stage/'source/src/main.cpp').read_bytes(),b'// synthetic source\n')
            self.assertTrue((stage/'provenance/metadata/source-inputs.json').is_file())
            self.assertFalse((stage/'metadata').exists())
            rows['source/src/main.cpp']['sha256']='0'*64
            other=root/'bad';other.mkdir()
            with self.assertRaisesRegex(ValueError,'member-sha256'): isolated.extract_verified(path,rows,other)

    def test_git_metadata_assets_and_noncanonical_paths_refused_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); stage=root/'stage'; stage.mkdir()
            for name in ('source/.git/config','source/Harvested/private.DBC','source/modules/mod-one/data/game.MPQ',
                         'source/../escape','unrecognized/file'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    isolated.extract_verified(root/'not-opened', {name:pin(b'x')}, stage)
            self.assertEqual(list(stage.iterdir()),[])

    def test_existing_and_overlapping_outputs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); inputs=root/'inputs';inputs.mkdir()
            existing=root/'existing';existing.mkdir();(existing/'marker').write_text('preserved')
            for output in (existing,inputs/'new-output'):
                with self.subTest(output=output),self.assertRaisesRegex(ValueError,'output-exists-or-overlaps'):
                    isolated.prepare(inputs,output)
            self.assertEqual((existing/'marker').read_text(),'preserved')

    def test_failed_validation_retains_unpublished_private_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); inputs=root/'inputs';inputs.mkdir()
            arc=inputs/'server-engine-source-inputs.tar.gz'
            rows=archive(arc,{'source/main.cpp':b'synthetic source only\n'})
            receipt=dict(formatVersion=1,scope='unsealed-engine-source-input-package',completeArchiveReadbackVerified=True,
                archive=dict(file=arc.name,**isolated.files.identity(arc)),archiveFiles=rows)
            (inputs/'source-inputs-receipt.json').write_text(json.dumps(receipt))
            output=root/'rejected'
            with patch.object(isolated,'validate_tree',side_effect=ValueError('synthetic-validation-failure')), \
                 patch('sys.stderr',new_callable=io.StringIO), self.assertRaisesRegex(ValueError,'synthetic-validation-failure'):
                isolated.prepare(inputs,output)
            self.assertFalse(output.exists()); stages=list(root.glob('.rejected.stage-*'))
            self.assertEqual(len(stages),1);self.assertEqual(stages[0].stat().st_mode & 0o777,0o700)

    def test_source_manifest_cannot_rebind_the_current_application_lock(self):
        manifest=dict(formatVersion=1,scope='unsealed-engine-source-input-preservation',
            sourceLock={'bytes':1,'sha256':'0'*64},source={'commit':'a'*40})
        manifest_pin={'bytes':2,'sha256':'1'*64}
        receipt={'manifest':manifest_pin,'sourceLock':manifest['sourceLock']}
        with patch.object(isolated.modules,'read_json',return_value=(manifest,manifest_pin)), \
             self.assertRaisesRegex(ValueError,'current-lock-mismatch'):
            isolated.validate_tree(Path('/not-read'),receipt)


class SemanticPatchReplay(unittest.TestCase):
    def fixture(self,root):
        source=root/'source/src/demo.cpp';source.parent.mkdir(parents=True);source.write_bytes(b'int value=1;\n')
        original=isolated.inputs.local_identity(source)
        adapted=root/'provenance/adapted-source/src/demo.cpp';adapted.parent.mkdir(parents=True)
        adapted.write_bytes(b'int value=7;\n');desired=isolated.inputs.local_identity(adapted)
        text=b'diff --git a/src/demo.cpp b/src/demo.cpp\n--- a/src/demo.cpp\n+++ b/src/demo.cpp\n@@ -1 +1 @@\n-int value=1;\n+int value=7;\n'
        patch_path=root/'integration/patches/fixture.patch';patch_path.parent.mkdir(parents=True);patch_path.write_bytes(text)
        manifest=dict(pristineGitFiles={'server':{'src/demo.cpp':original},'eluna':{}},
            adaptedFiles=[dict(path='src/demo.cpp',origin='server',pristine=original,adapted=desired)],
            source={'patches':[dict(path='patches/fixture.patch',sha256=hashlib.sha256(text).hexdigest())]})
        return source,manifest

    def test_actual_git_apply_without_index_reproduces_paired_adapted_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path,manifest=self.fixture(root)
            proof=isolated.replay_patches(root,manifest,{'src/demo.cpp'})
            self.assertEqual(path.read_bytes(),b'int value=7;\n')
            self.assertTrue(proof['exactAdaptedCopiesReproduced']);self.assertFalse(proof['gitMetadataCreated'])
            self.assertFalse(any(root.rglob('.git')))

    def test_changed_patch_or_adapted_identity_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path,manifest=self.fixture(root)
            manifest['source']['patches'][0]['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'patch-identity'):
                isolated.replay_patches(root,manifest,{'src/demo.cpp'})
            self.assertEqual(path.read_bytes(),b'int value=1;\n')


class OriginalLuaAndArchivalMetadata(unittest.TestCase):
    def test_lua_extracts_bounded_original_source_without_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'provenance/external/lua-5.2.4.tar.gz';path.parent.mkdir(parents=True)
            archive(path,{'lua-5.2.4/README':b'original archive fixture notice\n','lua-5.2.4/src/lua.h':b'// fixture\n'})
            with patch.object(isolated.inputs,'LUA_SHA256',isolated.files.identity(path)['sha256']):
                proof=isolated.extract_lua(root)
            self.assertFalse(proof['fetched']);self.assertTrue((root/'external/lua-5.2.4/src/lua.h').is_file())

    def test_lua_traversal_refused_even_for_pinned_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); path=root/'provenance/external/lua-5.2.4.tar.gz';path.parent.mkdir(parents=True)
            archive(path,{'lua-5.2.4/../../outside':b'forbidden'})
            with patch.object(isolated.inputs,'LUA_SHA256',isolated.files.identity(path)['sha256']),self.assertRaises(ValueError):
                isolated.extract_lua(root)
            self.assertFalse((root/'outside').exists())

    def test_recorded_version_guard_and_recurring_target_forwarding_preserve_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); genrev=root/'source/src/cmake/genrev.cmake';genrev.parent.mkdir(parents=True)
            original=b'# original license-bearing recipe\nconfigure_file("fixture" "output" @ONLY)\n';genrev.write_bytes(original)
            target=root/'source/src/genrev/CMakeLists.txt';target.parent.mkdir(parents=True)
            old=b'COMMAND "${CMAKE_COMMAND}" -DBUILDDIR="${CMAKE_BINARY_DIR}" -P "${CMAKE_SOURCE_DIR}/src/cmake/genrev.cmake"\n'
            target.write_bytes(old)
            proof=isolated.adapt_revision(root,build_record())
            self.assertFalse(proof['fabricatedGitMetadata']);self.assertFalse(proof['semanticPatchSetChanged'])
            self.assertEqual(proof['recordedRevision']['hash'],'f35f04d01689+')
            self.assertEqual(proof['recordedRevision']['branch'],'Archived source package')
            self.assertTrue(genrev.read_bytes().endswith(original))
            self.assertIn(b'-DESTERIA_ARCHIVAL_REVISION_FILE=',target.read_bytes())
            self.assertEqual((root/'provenance/source-export-adaptations/src/cmake/genrev.cmake').read_bytes(),original)
            self.assertEqual((root/'provenance/archival-revision.txt').read_text().splitlines(),
                ['f35f04d01689+','2026-10-28 12:35:08 -0500','Archived source package','2026'])

    def test_mismatched_or_fabricated_recorded_version_refused(self):
        build=build_record();build['serverSource']['commit']='a'*40
        with self.assertRaisesRegex(ValueError,'version-source-mismatch'):isolated.archival_revision(build)
        build=build_record();build['hostLoaderSmoke']['outputs']['worldserver']='different'
        with self.assertRaisesRegex(ValueError,'version-output-required'):isolated.archival_revision(build)


class SourceSupplement(unittest.TestCase):
    def test_exact_same_commit_header_added_and_mutation_or_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);stage=root/'stage';stage.mkdir();source=root/'supplements/modules/ModulesScriptLoader.h'
            source.parent.mkdir(parents=True);source.write_bytes(b'// original header fixture\n')
            row=isolated.inputs.local_identity(source);row['sourceCommit']='a'*40
            pin={'sourceSupplements':{'modules/ModulesScriptLoader.h':row}}
            manifest={'source':{'commit':'a'*40}}
            with patch.object(isolated.build_inputs,'load_pin',return_value=pin):
                result=isolated.add_supplements(stage,root/'supplements',manifest)
                self.assertEqual(result,pin['sourceSupplements'])
                self.assertEqual((stage/'source/modules/ModulesScriptLoader.h').read_bytes(),source.read_bytes())
                with self.assertRaisesRegex(ValueError,'overwrite'):isolated.add_supplements(stage,root/'supplements',manifest)
                source.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'git-blob-mismatch'):isolated.add_supplements(stage,root/'supplements',manifest)


if __name__=='__main__':unittest.main()
