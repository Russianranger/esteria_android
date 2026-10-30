"""Real Git/metadata admission for the conditional public local-game profile."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import fetch_local_server_profile as consumer

release = consumer.release


class PublicLocalServerProfile(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='public-server-profile-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = self.root / 'application'; self.app.mkdir()
        self.directory = self.app / consumer.DIRECTORY; self.directory.mkdir(parents=True)
        self.lock_path = self.directory / 'dependency-release.lock.json'

    def put(self, path, value):
        path.write_bytes(release.encoded(value))

    def pending(self):
        value = dict(formatVersion=1, scope=release.SCOPE, repository=release.transport.REPOSITORY,
            tag=release.TAG, state='pending-measurement', targetCommit=None, ownedDraftReleaseId=None,
            selectedInputs=None, recipeInputs=None, files=None)
        self.put(self.lock_path, value)
        return value

    def owned(self):
        # Test-only metadata. It admits no real runtime bytes and is never
        # published. Real Git source checks below use every fixture blob.
        selected = release.selected_inputs()
        recipe = {name: dict(pin, mode=0o444) for name, pin in selected.items()}
        for name in ('tools/release_local_server_components.py', '.github/workflows/preserve-local-server-components.yml'):
            recipe[name] = dict(consumer.bytes_identity(b'# Test-only source fixture\n'), mode=0o444)
        value = dict(formatVersion=1, scope=release.SCOPE, repository=release.transport.REPOSITORY,
            tag=release.TAG, state='owned-draft-bound', targetCommit='a' * 40, ownedDraftReleaseId=123,
            selectedInputs=selected, recipeInputs=recipe,
            files={name: consumer.bytes_identity(name.encode()) for name in release.PAYLOAD})
        self.put(self.lock_path, value)
        return value

    def publish(self, lock):
        expected = consumer.expected_assets(lock)
        base = 'https://github.com/' + lock['repository'] + '/releases/'
        publication = dict(formatVersion=1, repository=lock['repository'], tag=lock['tag'],
            targetCommit=lock['targetCommit'], releaseId=lock['ownedDraftReleaseId'],
            url=base + 'tag/' + lock['tag'], githubImmutable=False, publisherNeverOverwrites=True,
            assets={name: dict(pin, url=base + 'download/' + lock['tag'] + '/' + name)
                for name, pin in expected.items()})
        readback = dict(formatVersion=1, scope='anonymous-complete-local-server-public-source-debug-readback',
            releaseId=lock['ownedDraftReleaseId'], targetCommit=lock['targetCommit'], assets=expected,
            allStoredBytesReadBack=True, completeOriginalSourceAndPairedDebugVerified=True, actionsArtifactsUsed=False,
            **{name: False for name in release.FALSE_FLAGS})
        self.put(self.directory / consumer.PUBLICATION, publication)
        self.put(self.directory / consumer.READBACK, readback)
        return publication, readback

    def test_absent_receipts_keep_retained_path_and_cannot_fetch(self):
        self.pending()
        self.assertEqual(consumer.selection(self.app)['source'], 'retained-actions')
        with mock.patch.object(consumer, 'recipe_checkout') as recipe, mock.patch.object(consumer, 'run_frozen') as run:
            with self.assertRaisesRegex(ValueError, 'not-yet-published'):
                consumer.acquire(self.root / 'unused', self.root / 'out', self.root / 'providers', self.app)
        recipe.assert_not_called(); run.assert_not_called(); self.assertFalse((self.root / 'out').exists())
        lock = self.owned(); lock.update(state='measured-unbound', ownedDraftReleaseId=None)
        self.put(self.lock_path, lock)
        self.assertEqual(consumer.selection(self.app)['source'], 'retained-actions')

    def test_partial_receipt_never_falls_back(self):
        self.pending(); self.put(self.directory / consumer.PUBLICATION, {})
        with self.assertRaisesRegex(ValueError, 'partial-publication-receipts'): consumer.selection(self.app)
        self.put(self.directory / consumer.READBACK, {})
        with self.assertRaisesRegex(ValueError, 'owned-published-lock-required'): consumer.selection(self.app)

    def test_exact_twelve_asset_receipts_admit_only_public_source_not_runtime(self):
        lock = self.owned(); self.publish(lock)
        chosen = consumer.selection(self.app)
        self.assertEqual(chosen['source'], 'public-release'); self.assertEqual(chosen['releaseId'], 123)
        self.assertEqual(chosen['recipeRevision'], lock['targetCommit'])
        self.assertEqual(set(chosen['assets']), release.ALL_FILES)
        self.assertEqual(chosen['releaseSelection'], release.identity(self.lock_path))
        self.assertFalse(chosen['runtimeQualified']); self.assertFalse(chosen['gameplayQualified'])

    def test_stale_source_recipe_identity_and_asset_pin_fail_before_network(self):
        original = self.owned(); self.publish(original)
        mutations = [lambda x: x.update(targetCommit='not-an-exact-sha'),
            lambda x: x['selectedInputs']['sources.lock.json'].update(sha256='0' * 64),
            lambda x: x['recipeInputs']['sources.lock.json'].update(sha256='0' * 64),
            lambda x: x['files']['NOTICE.txt'].update(bytes=True),
            lambda x: x.update(ownedDraftReleaseId=True),
            lambda x: x['recipeInputs'].pop('tools/release_local_server_components.py')]
        for mutation in mutations:
            lock = copy.deepcopy(original); mutation(lock); self.put(self.lock_path, lock)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): consumer.selection(self.app)

    def test_public_receipt_id_url_asset_and_qualification_changes_are_refused(self):
        lock = self.owned(); publication, readback = self.publish(lock)
        changes = [(consumer.PUBLICATION, publication, lambda x: x.update(releaseId=999)),
            (consumer.PUBLICATION, publication, lambda x: x.update(githubImmutable=None)),
            (consumer.PUBLICATION, publication, lambda x: x.update(url='https://unrelated.invalid/')),
            (consumer.PUBLICATION, publication, lambda x: x['assets']['NOTICE.txt'].update(sha256='0' * 64)),
            (consumer.READBACK, readback, lambda x: x.update(allStoredBytesReadBack=False)),
            (consumer.READBACK, readback, lambda x: x.update(completeOriginalSourceAndPairedDebugVerified=False)),
            (consumer.READBACK, readback, lambda x: x.update(actionsArtifactsUsed=True)),
            (consumer.READBACK, readback, lambda x: x.update(gameplayQualified=True)),
            (consumer.READBACK, readback, lambda x: x['assets'].pop('SHA256SUMS'))]
        for name, original, mutation in changes:
            self.publish(lock); value = copy.deepcopy(original); mutation(value); self.put(self.directory / name, value)
            with self.subTest(name=name, mutation=mutation), self.assertRaises(ValueError): consumer.selection(self.app)

    def recipe(self):
        source = self.root / 'frozen'; source.mkdir()
        lock = self.owned()
        for name in lock['recipeInputs']:
            target = source / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((release.ROOT / name).read_bytes() if name in release.SELECTED else b'# Test-only source fixture\n')
        def git(*args):
            return subprocess.check_output(['git', '-c', 'user.name=TEST ONLY', '-c',
                'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', '-C', str(source), *args],
                stderr=subprocess.DEVNULL)
        git('init'); git('add', '.'); git('commit', '-m', 'Test-only fixture')
        lock['targetCommit'] = git('rev-parse', 'HEAD').decode().strip(); self.put(self.lock_path, lock)
        return lock, source, git

    def test_real_git_roster_full_working_bytes_untracked_and_hidden_flags(self):
        lock, source, git = self.recipe()
        self.assertEqual(consumer.recipe_checkout(source, lock), source)
        path = source / 'tools/release_local_server_components.py'; original = path.read_bytes()
        path.write_bytes(b'# changed\n')
        with self.assertRaises((ValueError, subprocess.CalledProcessError)): consumer.recipe_checkout(source, lock)
        path.write_bytes(original); (source / 'untracked.py').write_bytes(b'# untrusted\n')
        with self.assertRaisesRegex(ValueError, 'untracked-recipe-files'): consumer.recipe_checkout(source, lock)
        (source / 'untracked.py').unlink(); git('update-index', '--assume-unchanged', 'tools/release_local_server_components.py')
        with self.assertRaisesRegex(ValueError, 'hidden-index-flags'): consumer.recipe_checkout(source, lock)
        git('update-index', '--no-assume-unchanged', 'tools/release_local_server_components.py')
        wrong = copy.deepcopy(lock); wrong['recipeInputs'].pop('sources.lock.json')
        with self.assertRaisesRegex(ValueError, 'recipe-git-member'): consumer.recipe_checkout(source, wrong)
        wrong = copy.deepcopy(lock); wrong['recipeInputs']['sources.lock.json']['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'retained-recipe-git-blob'): consumer.recipe_checkout(source, wrong)

    def test_existing_output_and_source_overlap_preserve_all_bytes(self):
        self.pending(); retained = self.root / 'retained'; retained.mkdir(); (retained / 'sentinel').write_bytes(b'keep')
        with mock.patch.object(consumer, 'selection') as select:
            with self.assertRaisesRegex(ValueError, 'existing-or-overlapping-output-preserved'):
                consumer.acquire(self.root / 'unused', retained, self.root / 'providers', self.app)
        select.assert_not_called(); self.assertEqual((retained / 'sentinel').read_bytes(), b'keep')
        lock, source, _ = self.recipe(); self.publish(lock)
        with self.assertRaisesRegex(ValueError, 'output-overlaps-frozen-source'):
            consumer.acquire(source, source / 'out', self.root / 'providers', self.app)
        self.assertFalse((source / 'out').exists())

    def test_acquisition_clears_tokens_and_rechecks_each_current_provider(self):
        lock, source, _ = self.recipe(); _, expected = self.publish(lock)
        restored = dict(scope='public-local-server-provider-directories-restored', selectedInputs=lock['selectedInputs'],
            actionsArtifactsUsed=False, completeOriginalSourceAndPairedDebugVerified=True,
            **{name: False for name in release.FALSE_FLAGS})
        admission = mock.Mock(return_value={'testOnlyProviderVerified': True})
        bundles = {name: (relative, admission) for name, (relative, _) in release.BUNDLES.items()}
        with mock.patch.dict(os.environ, {'GITHUB_TOKEN': 'TEST_ONLY', 'GH_TOKEN': 'TEST_ONLY', 'PYTHONPATH': 'TEST_ONLY'}), \
                mock.patch.object(consumer, 'run_frozen', side_effect=[expected, restored]) as run, \
                mock.patch.dict(release.BUNDLES, bundles, clear=True):
            result = consumer.acquire(source, self.root / 'download', self.root / 'providers', self.app)
        self.assertEqual(admission.call_count, 4)
        for call in run.call_args_list:
            self.assertFalse({'GITHUB_TOKEN', 'GH_TOKEN', 'PYTHONPATH'} & call.args[2].keys())
        self.assertEqual(run.call_args_list[0].args[3], 'fetch-published')
        self.assertEqual(run.call_args_list[1].args[3], 'consume')
        self.assertFalse(result['actionsArtifactsUsed']); self.assertFalse(result['gameplayQualified'])
        self.assertEqual(set(result['currentProviderAdmission']), {'programs', 'data-tools', 'content', 'extractors'})
        self.assertTrue((self.root / 'download/acquisition.json').is_file())


if __name__ == '__main__': unittest.main()
