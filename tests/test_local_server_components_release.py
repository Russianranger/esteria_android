"""Source/debug admission, bounded transport and owned write-once release policy."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

from tools import release_local_server_components as release


class LocalServerRelease(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='local-server-release-policy-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def test_pending_lock_cannot_enable_a_provider_or_publication(self):
        value = copy.deepcopy(release.transport.small_json(release.LOCK))
        value.update(state='pending-measurement',targetCommit=None,ownedDraftReleaseId=None,
            selectedInputs=None,recipeInputs=None,files=None)
        path=self.root/'pending-fixture.json';path.write_bytes(release.encoded(value))
        release.load_lock(path,pending=True)
        with self.assertRaisesRegex(ValueError, 'real-measurement-required'): release.load_lock(path)
        with mock.patch.object(release, 'verify') as verify:
            api = mock.Mock()
            publisher = release.OwnedDraftPublication(value, 'fixture', verify)
            with self.assertRaisesRegex(ValueError, 'owned-draft-binding-required-before-upload'):
                publisher.upload_draft(api, self.root)
        verify.assert_not_called(); api.json.assert_not_called(); api.upload.assert_not_called()

    def test_fixed_twelve_assets_include_original_provider_and_full_recipe_not_an_apk(self):
        self.assertEqual(len(release.ALL_FILES), 12)
        self.assertEqual(set(release.BUNDLES), set(release.CONSUMER_DIRECTORIES))
        self.assertIs(release.BUNDLES['server-programs-playerbots-provider.tar.gz'][1], release.helper.provider.verify)
        self.assertIs(release.BUNDLES['server-data-tools-provider.tar.gz'][1], release.data_provider.verify)
        self.assertIs(release.BUNDLES['server-extractors-original-provider.tar.gz'][1], release.extractors.verify)
        self.assertFalse(any(name.endswith('.apk') for name in release.ALL_FILES))
        self.assertLess(release.MAX_BUNDLE, release.MAX_ASSET)
        self.assertIn('runtime/server/programs-playerbots-provider.lock.json', release.selected_inputs())

    def test_existing_input_candidate_and_consumer_output_are_preserved_before_work(self):
        retained = self.root / 'retained'; retained.mkdir(); (retained / 'sentinel').write_bytes(b'retain')
        with mock.patch.object(release, 'recipe_inputs', side_effect=AssertionError('existing output consumed')):
            with self.assertRaisesRegex(ValueError, 'existing-or-overlapping-output'):
                release.stage(self.root / 'inputs', 'a' * 40, retained)
        with mock.patch.object(release.stock, 'acquire') as acquire:
            with self.assertRaisesRegex(ValueError, 'existing-inputs-preserved'): release.prepare(retained)
        acquire.assert_not_called()
        with mock.patch.object(release, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'existing-consumer-output-preserved'):
                release.consume(self.root / 'unused', retained, {})
        verify.assert_not_called(); self.assertEqual((retained / 'sentinel').read_bytes(), b'retain')

    def test_original_full_source_debug_guard_failure_precedes_candidate_creation(self):
        validator = mock.Mock(side_effect=ValueError('actual-original-full-source-and-debug-required'))
        with mock.patch.object(release, 'recipe_inputs', return_value={'TEST_ONLY': {}}), \
                mock.patch.object(release, 'selected_inputs', return_value={'TEST_ONLY': {}}), \
                mock.patch.dict(release.BUNDLES, {'fixture.tar.gz': ('fixture', validator)}, clear=True):
            target = self.root / 'refused'
            with self.assertRaisesRegex(ValueError, 'actual-original-full-source-and-debug-required'):
                release.stage(self.root / 'inputs', 'a' * 40, target)
        validator.assert_called_once_with(self.root / 'inputs/fixture'); self.assertFalse(target.exists())

    def test_stored_gzip_roundtrip_preserves_nested_original_bytes_modes_and_determinism(self):
        source = self.root / 'source'; source.mkdir()
        original = b'original already-compressed archive fixture\0\xff' * 100
        (source / 'original.tar.gz').write_bytes(original)
        (source / 'helper').write_bytes(b'fixed executable fixture, never run'); (source / 'helper').chmod(0o555)
        rows = release.inventory(source)
        first, second = self.root / 'first.tar.gz', self.root / 'second.tar.gz'
        release.write_bundle(source, first, rows); release.write_bundle(source, second, rows)
        self.assertEqual(release.identity(first), release.identity(second))
        output = self.root / 'readback'; release.read_bundle(first, rows, output)
        self.assertEqual((output / 'original.tar.gz').read_bytes(), original)
        self.assertEqual((output / 'helper').stat().st_mode & 0o777, 0o555)

    def test_canonical_git_recipe_accepts_only_exact_declared_wrapper_checkout_conversion(self):
        repository=self.root/'git-fixture';repository.mkdir()
        def git(*arguments):
            return subprocess.check_output(['git','-c','user.name=Archive Fixture',
                '-c','user.email=fixture@example.invalid','-c','commit.gpgsign=false',*arguments],
                cwd=repository,stderr=subprocess.DEVNULL)
        git('init')
        contents={'.gitattributes':b'* text=auto eol=lf\n*.bat text eol=crlf\n',
            'gradlew.bat':b'@echo off\r\necho fixture\r\n',
            'tools/release_local_server_components.py':b'# TEST_ONLY recipe fixture; never executed\n',
            '.github/workflows/preserve-local-server-components.yml':b'# TEST_ONLY recipe fixture\n'}
        for name,raw in contents.items():
            path=repository/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        git('add','.');git('commit','-m','Fixture canonical source bytes')
        git('checkout-index','--force','--all')
        revision=git('rev-parse','HEAD').decode().strip()
        with mock.patch.object(release,'ROOT',repository):
            rows=release.recipe_inputs(revision)
            canonical=git('show',revision+':gradlew.bat')
            self.assertNotIn(b'\r',canonical);self.assertIn(b'\r\n',(repository/'gradlew.bat').read_bytes())
            self.assertEqual(rows['gradlew.bat']['sha256'],hashlib.sha256(canonical).hexdigest())
            archive=self.root/'canonical-recipe.tar.gz';release.write_recipe(revision,rows,archive)
            extracted=self.root/'canonical';release.read_bundle(archive,rows,extracted)
            self.assertEqual((extracted/'gradlew.bat').read_bytes(),canonical)
            (repository/'gradlew.bat').write_bytes(contents['gradlew.bat']+b'echo changed\r\n')
            with self.assertRaisesRegex(ValueError,'executing-recipe-changed:gradlew.bat'):
                release.recipe_inputs(revision)
            (repository/'gradlew.bat').write_bytes(contents['gradlew.bat'])
            (repository/'tools/release_local_server_components.py').write_bytes(b'# changed\r\n')
            with self.assertRaisesRegex(ValueError,'executing-recipe-changed:tools/'):
                release.recipe_inputs(revision)

    def test_inventory_and_archive_reject_changed_links_traversal_duplicates_missing_and_trailer(self):
        pin = dict(bytes=3, sha256=hashlib.sha256(b'abc').hexdigest(), mode=0o444)
        rows = {'plain': pin}
        for kind in ('valid', 'changed', 'link', 'traversal', 'duplicate', 'missing', 'trailer'):
            path = self.root / (kind + '.tar.gz')
            with path.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                    if kind != 'missing':
                        item = tarfile.TarInfo('../escape' if kind == 'traversal' else 'plain'); item.mode=0o444; item.size=3
                        if kind == 'link': item.type=tarfile.SYMTYPE; item.linkname='/private'; item.size=0
                        archive.addfile(item, None if kind == 'link' else io.BytesIO(b'bad' if kind == 'changed' else b'abc'))
                        if kind == 'duplicate': archive.addfile(item, io.BytesIO(b'abc'))
                if kind == 'trailer': compressed.write(b'unbound-nonzero-tail')
            if kind == 'valid': release.read_bundle(path, rows)
            else:
                with self.subTest(kind=kind), self.assertRaises((ValueError, tarfile.ReadError)):
                    release.read_bundle(path, rows)
        bad = {'../private': pin}
        with self.assertRaises(ValueError): release.validate_inventory(bad)
        self.assertFalse((self.root / 'escape').exists())

    def test_whole_asset_hash_precedes_any_manifest_source_or_archive_parse(self):
        for name in release.ALL_FILES: (self.root / name).write_bytes(b'changed')
        lock = dict(files={name: dict(bytes=7, sha256='0' * 64) for name in release.PAYLOAD})
        with mock.patch.object(release, 'validate_payload', side_effect=AssertionError('unverified payload parsed')):
            with self.assertRaisesRegex(ValueError, 'whole-asset-hash-differs'): release.verify(self.root, lock)

    def owned(self):
        return dict(tag=release.TAG,targetCommit='a'*40,state='owned-draft-bound',ownedDraftReleaseId=123)

    def ui_release(self, lock, **extra):
        result = dict(id=123,tag_name=release.TAG,prerelease=True,body=release.body(lock),draft=True,target_commitish='a'*40)
        result.update(extra); return result

    def test_matching_tag_and_body_cannot_authorize_a_different_owned_release_id(self):
        lock = self.owned(); verifier=mock.Mock(return_value={'fixed': dict(bytes=1,sha256='b'*64)})
        publisher=release.OwnedDraftPublication(lock,release.body(lock),verifier)
        api=mock.Mock();api.json.return_value=[self.ui_release(lock,id=999)]
        with self.assertRaisesRegex(ValueError, 'owned-draft-id-differs'): publisher.upload_draft(api,self.root)
        api.upload.assert_not_called()
        self.assertEqual(api.json.call_args_list,[mock.call('/releases?per_page=100&page=1')])

    def test_missing_draft_and_changed_existing_asset_never_create_or_replace_anything(self):
        lock=self.owned(); publisher=release.OwnedDraftPublication(lock,release.body(lock),lambda _: {'fixed':dict(bytes=1,sha256='b'*64)})
        api=mock.Mock();api.json.return_value=[]
        with self.assertRaisesRegex(ValueError,'exact-owned-UI-draft-required'): publisher.upload_draft(api,self.root)
        api.upload.assert_not_called()
        api=mock.Mock();api.json.side_effect=[[self.ui_release(lock)],None,
            [dict(name='fixed',state='uploaded',size=1,digest='sha256:'+'0'*64,id=77)]]
        with self.assertRaisesRegex(ValueError,'existing-asset-differs'): publisher.upload_draft(api,self.root)
        api.upload.assert_not_called();api.download.assert_not_called()
        self.assertTrue(all(not call.kwargs.get('method') for call in api.json.call_args_list))

    def test_anonymous_consumer_requires_public_bound_release_before_creating_output(self):
        lock=self.owned();api=mock.Mock();api.json.side_effect=[self.ui_release(lock),dict(object=dict(type='commit',sha='a'*40))]
        with mock.patch.object(release.shutil,'disk_usage',return_value=mock.Mock(free=8<<30)):
            with self.assertRaisesRegex(ValueError,'must-be-public-before-download'):
                release.fetch_published(self.root/'refused',lock,api)
        self.assertFalse((self.root/'refused').exists());api.download.assert_not_called()


if __name__ == '__main__': unittest.main()
