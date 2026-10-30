"""Tiny real Git trees exercise retained source identity without cloning LLVM."""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('capture_arm64_toolchain_sources',
    ROOT / 'runtime/wine-arm64/capture_toolchain_sources.py')
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)


@unittest.skipUnless(shutil.which('git') and hasattr(os, 'waitid'), 'Linux Git source fixture')
class ToolchainSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='esteria-toolchain-sources-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ca = self.root / 'ca.crt'
        self.ca.write_text('No network is used by this fixture.\n')
        self.repositories = {}
        recipe = self.repository('recipe')
        compiler = self.repository('compiler')
        license_raw = b'Original source license\n'
        self.lock = dict(toolchain=dict(recipe=recipe, sourceRefs=[compiler],
            archive=dict(file='unexecuted-binary-fixture.tar.xz', bytes=1, sha256='a' * 64)),
            licenses={'fixture-license':dict(
                url='https://raw.githubusercontent.com/fixture/recipe/' + recipe['revision'] + '/LICENSE',
                bytes=len(license_raw), sha256=hashlib.sha256(license_raw).hexdigest())})
        self.lock_path = self.root / 'sources.lock.json'
        self.save_lock()

    def command(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd, stderr=subprocess.PIPE,
                                       env=dict(os.environ, GIT_AUTHOR_DATE='2001-01-01T00:00:00Z',
                                                GIT_COMMITTER_DATE='2001-01-01T00:00:00Z')).decode().strip()

    def repository(self, name):
        working = self.root / (name + '-work')
        working.mkdir()
        self.command('init', '--quiet', str(working))
        (working / 'LICENSE').write_bytes(b'Original source license\n')
        (working / 'README').write_text('Original ' + name + ' source\n')
        (working / 'hidden.txt').write_text('Must survive export-ignore.\n')
        (working / 'substitute.txt').write_text('$Format:%H$\n')
        (working / '.gitattributes').write_text('hidden.txt export-ignore\nsubstitute.txt export-subst\n')
        (working / 'nested').mkdir()
        (working / 'nested/script').write_bytes(b'#!/bin/sh\nexit 0\n')
        (working / 'nested/script').chmod(0o755)
        (working / 'nested/readme').symlink_to('../README')
        self.command('add', '.', cwd=working)
        self.command('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '--quiet', '-m', name, cwd=working)
        revision = self.command('rev-parse', 'HEAD', cwd=working)
        bare = self.root / (name + '.git')
        self.command('clone', '--quiet', '--bare', str(working), str(bare))
        self.repositories[revision] = bare
        return dict(repository='https://github.com/fixture/' + name, revision=revision)

    def save_lock(self):
        self.lock_path.write_text(json.dumps(self.lock, indent=2) + '\n')

    def fetch_fixture(self, source, directory, ca):
        shutil.copytree(self.repositories[source['revision']], directory)
        (directory / 'info/attributes').write_text('* -export-ignore -export-subst\n')

    def capture(self, name='retained'):
        output = self.root / name
        with patch.object(CAPTURE, 'fetch', self.fetch_fixture):
            proof = CAPTURE.capture(self.lock_path, output, self.ca)
        return output, proof

    def change_manifest(self, output, mutate):
        path = output / 'SOURCE-MANIFEST.json'
        manifest = json.loads(path.read_bytes())
        mutate(manifest)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')

    def test_original_git_blobs_notices_modes_and_export_attributes_are_preserved(self):
        output, proof = self.capture()
        self.assertEqual(proof['sourceTrees'], 2)
        self.assertTrue(proof['allSelectedGitBlobsReadBack'])
        self.assertFalse(proof['binaryRebuildEquivalent'])
        self.assertEqual(CAPTURE.verify_output(self.lock_path, output), proof)
        with tarfile.open(output / 'recipe.tar.gz', 'r:gz') as archive:
            self.assertEqual(archive.extractfile('recipe/hidden.txt').read(), b'Must survive export-ignore.\n')
            self.assertEqual(archive.extractfile('recipe/substitute.txt').read(), b'$Format:%H$\n')
            self.assertEqual(archive.getmember('recipe/nested/script').mode, 0o755)
            self.assertEqual(archive.getmember('recipe/nested/readme').linkname, '../README')
        self.assertEqual((output / 'notices/recipe/LICENSE').read_bytes(), b'Original source license\n')
        second, _ = self.capture('second')
        self.assertEqual((output / 'recipe.tar.gz').read_bytes(), (second / 'recipe.tar.gz').read_bytes())

    def test_blob_mutation_with_updated_archive_hash_cannot_relabel_git_source(self):
        output, _ = self.capture()
        path = output / 'recipe.tar.gz'
        changed = self.root / 'changed.tar.gz'
        with tarfile.open(path, 'r:gz') as incoming, tarfile.open(changed, 'w:gz', format=tarfile.GNU_FORMAT) as outgoing:
            for item in incoming:
                if item.name == 'recipe/README':
                    data = b'Altered source retained under a truthful-looking manifest.\n'
                    item.size = len(data)
                    outgoing.addfile(item, io.BytesIO(data))
                else:
                    outgoing.addfile(item, incoming.extractfile(item) if item.isfile() else None)
        path.write_bytes(changed.read_bytes())
        def update(manifest):
            manifest['sources'][0].update(CAPTURE.identity(path))
            # An attacker can update declared byte counts but cannot reproduce
            # the pinned commit's Git root tree after changing a blob.
            with tarfile.open(path, 'r:gz') as archive:
                length = sum(x.size if x.isfile() else len(x.linkname.encode()) for x in archive)
            manifest['treeBytes'] += length - manifest['sources'][0]['gitBlobBytes']
            manifest['sources'][0]['gitBlobBytes'] = length
        self.change_manifest(output, update)
        with self.assertRaisesRegex(ValueError, 'git-tree-differs'):
            CAPTURE.verify_output(self.lock_path, output)

    def test_relabelled_ref_and_changed_commit_object_are_rejected(self):
        output, _ = self.capture()
        changed_lock = copy.deepcopy(self.lock)
        changed_lock['toolchain']['recipe']['revision'] = 'b' * 40
        (output / 'sources.lock.json').write_text(json.dumps(changed_lock) + '\n')
        def update(manifest):
            manifest['sources'][0]['revision'] = 'b' * 40
            manifest['sourceLockSha256'] = hashlib.sha256((output / 'sources.lock.json').read_bytes()).hexdigest()
        self.change_manifest(output, update)
        with self.assertRaisesRegex(ValueError, 'commit-object'):
            CAPTURE.verify_output(changed_lock, output)

    def test_extra_files_directories_and_linked_notices_are_rejected(self):
        for kind in ('file', 'directory', 'symlink'):
            with self.subTest(kind=kind):
                output, _ = self.capture(kind)
                if kind == 'file':
                    (output / 'unexpected').write_bytes(b'not retained source')
                elif kind == 'directory':
                    (output / 'unexpected').mkdir()
                else:
                    path = output / 'notices/recipe/LICENSE'
                    path.unlink()
                    path.symlink_to(self.root / 'ca.crt')
                with self.assertRaises(ValueError):
                    CAPTURE.verify_output(self.lock_path, output)

    def test_existing_output_and_mismatched_license_never_overwrite_files(self):
        output = self.root / 'retained'
        output.mkdir()
        marker = output / 'keep'
        marker.write_text('Preserve this existing output.\n')
        with patch.object(CAPTURE, 'fetch', self.fetch_fixture):
            with self.assertRaisesRegex(ValueError, 'output-exists'):
                CAPTURE.capture(self.lock_path, output, self.ca)
        self.assertEqual(marker.read_text(), 'Preserve this existing output.\n')
        self.lock['licenses']['fixture-license']['sha256'] = 'c' * 64
        self.save_lock()
        with self.assertRaisesRegex(ValueError, 'pinned-license-differs'):
            self.capture('bad-license')
        self.assertFalse((self.root / 'bad-license').exists())

    def test_gitlinks_require_exact_explicit_mapping(self):
        child = self.repository('dependency')
        working = self.root / 'recipe-work'
        self.command('update-index', '--add', '--cacheinfo', '160000,' + child['revision'] + ',dependency', cwd=working)
        self.command('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                     'commit', '--quiet', '-m', 'Explicit dependency', cwd=working)
        revision = self.command('rev-parse', 'HEAD', cwd=working)
        bare = self.root / 'with-submodule.git'
        self.command('clone', '--quiet', '--bare', str(working), str(bare))
        self.repositories[revision] = bare
        self.lock['toolchain']['recipe']['revision'] = revision
        self.lock['licenses']['fixture-license']['url'] = 'https://raw.githubusercontent.com/fixture/recipe/' + revision + '/LICENSE'
        self.save_lock()
        with self.assertRaisesRegex(ValueError, 'source-gitlinks'):
            self.capture('unlisted')
        self.lock['toolchain']['recipe']['submodules'] = {'dependency': child}
        self.save_lock()
        output, proof = self.capture('pinned')
        self.assertEqual(proof['sourceTrees'], 3)
        self.assertTrue(CAPTURE.verify_output(self.lock, output)['allSelectedGitBlobsReadBack'])
        self.lock['toolchain']['recipe']['submodules']['dependency']['revision'] = 'd' * 40
        self.save_lock()
        with self.assertRaisesRegex(ValueError, 'submodule-revision-differs'):
            self.capture('wrong-link')


if __name__ == '__main__':
    unittest.main()
