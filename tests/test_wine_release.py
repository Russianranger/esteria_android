import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests.test_dependency_release import FakeGithub
from tools import release_wine_arm64 as wine


class WineRelease(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.inputs = self.root / 'retained'
        self.package = self.inputs / 'runtime-package'; self.package.mkdir(parents=True)
        for name in wine.retained.RUNTIME_FILES: (self.package / name).write_bytes(('original ' + name + '\n').encode())
        with zipfile.ZipFile(self.inputs / 'sources.zip', 'w') as archive:
            archive.writestr('wine-arm64-sources/fixture.txt', b'original source bytes\n')
        self.source_proof = dict(formatVersion=1, scope='read-back-source-owned-arm64-wine-candidate-originals',
            allOriginalSourcesReadBack=True, completeIntegrationTreeReadBack=True,
            androidQualified=False, gameClientQualified=False, gameplayQualified=False)
        self.pin = copy.deepcopy(json.loads((wine.ROOT / 'runtime/wine-arm64-qualification/runtime-input.lock.json').read_text()))
        self.pin['files'] = {name: wine.identity(self.package / name) for name in sorted(wine.retained.RUNTIME_FILES)}
        self.pin['sourcesArtifact'] = wine.identity(self.inputs / 'sources.zip')
        self.pin['sourceReadbackReceipt'] = wine.bytes_identity((json.dumps(self.source_proof, indent=2) + '\n').encode())
        self.input_path = self.root / 'input.json'
        self.recipe = {'tools/release_wine_arm64.py': wine.bytes_identity(b'recipe fixture')}

    def selected(self):
        raw = json.dumps(self.pin, indent=2).encode(); self.input_path.write_bytes(raw)
        lock = dict(formatVersion=1, repository=wine.shared.REPOSITORY, scope=wine.SCOPE,
            tag='deps-wine-arm64-681b2e9-c0e13ed15a69', targetCommit='a' * 40,
            runtimeInputFile=wine.bytes_identity(raw), runtimeInput=copy.deepcopy(self.pin), recipeInputs=self.recipe)
        return lock, patch.multiple(wine, INPUT_IDENTITY=wine.bytes_identity(raw),
            INPUT_CANONICAL_SHA256=hashlib.sha256(wine.encoded(self.pin)).hexdigest())

    def check_package(self, package, pin):
        self.assertEqual({path.name for path in package.iterdir()}, wine.retained.RUNTIME_FILES)
        self.assertEqual(pin, self.pin)
        for name, expected in pin['files'].items(): wine.retained.client.verify_identity(package / name, expected)
        return {}, {}

    def check_sources(self, directory, metadata, revision):
        self.assertEqual((directory / 'fixture.txt').read_bytes(), b'original source bytes\n')
        self.assertEqual(metadata.read_bytes(), (self.package / 'runtime.json').read_bytes())
        self.assertEqual(revision, wine.PRODUCER)
        return copy.deepcopy(self.source_proof)

    def test_frozen_original_input_is_exact_and_separate_from_current_client_and_production(self):
        raw = (wine.ROOT / 'runtime/wine-arm64-qualification/runtime-input.lock.json').read_bytes()
        pin = wine.checked_input(raw)
        self.assertEqual(pin['workflowRun'], 41057900330)
        self.assertEqual(pin['files']['wine-arm64.tar.gz']['sha256'],
                         'c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46')
        self.assertEqual(pin['sourcesArtifact']['bytes'], 1681474721)
        self.assertEqual(pin['sourcesArtifact']['sha256'],
                         '38e16617545abb16f995ba75a8b52b8ca2bacad5d2688adf3646911f16c8fb06')
        with self.assertRaisesRegex(ValueError, 'runtime-input-changed'): wine.checked_input(raw + b' ')
        self.assertEqual(len(wine.RELEASE_FILES), 11)
        self.assertEqual(wine.SOURCE_ZIP, 'wine-arm64-corresponding-sources.zip')
        self.assertEqual(wine.TAG, 'deps-wine-arm64-681b2e9-c0e13ed15a69')

    def test_lock_generation_requires_real_matching_recipe_and_never_overwrites(self):
        lock, selection = self.selected(); path = self.root / 'release-lock.json'
        with selection, patch.object(wine, 'recipe_inputs', return_value=self.recipe) as recipe:
            actual = wine.make_lock('a' * 40, self.input_path, path)
            self.assertEqual(actual, lock); recipe.assert_called_once_with('a' * 40)
            self.assertEqual(wine.load_lock(path), lock)
            for key, wrong in (('formatVersion', True), ('repository', 'foreign/repo'), ('targetCommit', 'main'),
                               ('tag', 'deps-wine-arm64-aaaaaaa-c0e13ed15a69'),
                               ('runtimeInputFile', {'bytes': 1, 'sha256': '0' * 64}),
                               ('recipeInputs', {})):
                path.write_bytes(wine.encoded(dict(lock, **{key: wrong})))
                with self.subTest(key=key), self.assertRaises(ValueError): wine.load_lock(path)
            path.write_bytes(b'preserve')
            with self.assertRaisesRegex(ValueError, 'output-exists'):
                wine.make_lock('a' * 40, Path('/not-read'), path)
            self.assertEqual(path.read_bytes(), b'preserve')
        with self.assertRaisesRegex(ValueError, 'recipe-revision'):
            wine.recipe_inputs('main')

    def test_recipe_closure_is_taken_from_exact_git_blobs_and_checks_executing_files(self):
        root = self.root / 'recipe'; (root / 'tools').mkdir(parents=True)
        data = {'tools/entry.py': b'from . import helper\nimport pathlib\n', 'tools/helper.py': b'VALUE = 1\n'}
        for name, raw in data.items(): (root / name).write_bytes(raw)
        calls = []
        def git(argv, **kwargs):
            calls.append(argv)
            if argv[1] == 'ls-tree': return '\n'.join(data).encode()
            name = argv[-1].split(':', 1)[1]
            if argv[1] == 'cat-file': return str(len(data[name])).encode()
            self.assertEqual(argv[1], 'show'); return data[name]
        with patch.object(wine, 'ROOT', root), patch.object(wine, 'RECIPE_ROOTS', {'tools/entry.py'}), \
             patch.object(wine.subprocess, 'check_output', side_effect=git):
            self.assertEqual(wine.recipe_inputs('a' * 40), {name: wine.bytes_identity(raw) for name, raw in data.items()})
            self.assertTrue(all('a' * 40 in call or any(arg.startswith('a' * 40 + ':') for arg in call) for call in calls))
            (root / 'tools/helper.py').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'executing-recipe-changed:tools/helper.py'):
                wine.recipe_inputs('a' * 40)

    def test_stage_and_verification_preserve_all_original_bytes_and_call_full_source_consumer(self):
        lock, selection = self.selected(); output = self.root / 'release'
        originals = {name: (self.package / name).read_bytes() for name in wine.retained.RUNTIME_FILES}
        original_zip = (self.inputs / 'sources.zip').read_bytes()
        with selection, patch.object(wine.retained, 'runtime_package', side_effect=self.check_package) as package, \
             patch.object(wine.retained.original_sources, 'verify', side_effect=self.check_sources) as sources:
            identities = wine.stage(self.inputs, self.input_path, output, lock)
            self.assertEqual(wine.verify_candidate(output, lock), identities)
            self.assertEqual(package.call_count, 2); self.assertEqual(sources.call_count, 2)
            for name, raw in originals.items(): self.assertEqual((output / name).read_bytes(), raw)
            self.assertEqual((output / wine.SOURCE_ZIP).read_bytes(), original_zip)
            self.assertEqual((output / wine.INPUT_LOCK).read_bytes(), self.input_path.read_bytes())
            manifest = json.loads((output / 'release-manifest.json').read_bytes())
            self.assertTrue(manifest['entireSourceZipReadBack'] and manifest['completeOriginalSourcesVerified'])
            self.assertEqual(manifest['originalSourcesArtifact']['id'], self.pin['sourcesArtifactId'])
            self.assertFalse(manifest['androidQualified']); self.assertFalse(manifest['gameplayQualified'])
            (output / 'runtime.json').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '(size|identity)-mismatch'): wine.verify_candidate(output, lock)

    def test_existing_output_corruption_or_source_validation_failure_never_publishes(self):
        lock, selection = self.selected(); output = self.root / 'release'
        output.mkdir(); (output / 'saved').write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'output-exists'):
            wine.stage(Path('/not-read'), Path('/not-read'), output, lock)
        self.assertEqual((output / 'saved').read_bytes(), b'preserve')
        with selection, patch.object(wine.retained, 'runtime_package', side_effect=self.check_package), \
             patch.object(wine.retained.original_sources, 'verify', side_effect=ValueError('full-source-consumer-failed')):
            with self.assertRaisesRegex(ValueError, 'full-source-consumer-failed'):
                wine.stage(self.inputs, self.input_path, self.root / 'failed', lock)
            self.assertFalse((self.root / 'failed').exists())
        (self.inputs / 'sources.zip').write_bytes(b'changed')
        with selection, self.assertRaisesRegex(ValueError, 'copy-identity'):
            wine.stage(self.inputs, self.input_path, self.root / 'corrupt', lock)
        self.assertFalse((self.root / 'corrupt').exists())

    def test_truthfully_hashed_out_of_scope_zip_member_is_still_rejected(self):
        with zipfile.ZipFile(self.inputs / 'sources.zip', 'a') as archive:
            archive.writestr('private/accounts.sql', b'not source material')
        self.pin['sourcesArtifact'] = wine.identity(self.inputs / 'sources.zip')
        lock, selection = self.selected()
        with selection, patch.object(wine.retained, 'runtime_package', side_effect=self.check_package), \
             patch.object(wine.retained.original_sources, 'verify') as consumer:
            with self.assertRaisesRegex(ValueError, 'source-member-type-or-scope'):
                wine.stage(self.inputs, self.input_path, self.root / 'out-of-scope', lock)
            consumer.assert_not_called()
        self.assertFalse((self.root / 'out-of-scope').exists())

    def test_source_consumer_overclaim_or_changed_producer_receipt_cannot_publish(self):
        for changed in ({'allOriginalSourcesReadBack': False}, {'androidQualified': True}, {'extra': 'changed receipt'}):
            lock, selection = self.selected()
            with self.subTest(changed=changed), selection, \
                 patch.object(wine.retained, 'runtime_package', side_effect=self.check_package), \
                 patch.object(wine.retained.original_sources, 'verify', return_value=dict(self.source_proof, **changed)):
                target = self.root / 'never-published'
                with self.assertRaisesRegex(ValueError, 'source-(closure-incomplete|receipt-mismatch)'):
                    wine.stage(self.inputs, self.input_path, target, lock)
                self.assertFalse(target.exists())

    def test_upload_policy_only_adds_missing_asset_to_exact_owned_ui_draft(self):
        lock, _ = self.selected(); identities = {name: wine.bytes_identity(name.encode()) for name in wine.RELEASE_FILES}
        # The shared fixture's constructor also formats the historical server body.
        api = FakeGithub(dict(lock, workflowRun=wine.PRODUCER_RUN), identities, draft=True)
        api.release['body'] = wine.release_body(lock); api.ref = None; del api.assets[wine.SOURCE_ZIP]
        policy = wine.publication.DraftPublication(lock, wine.release_body(lock), lambda _: identities)
        result = policy.upload_draft(api, Path('/synthetic'))
        self.assertEqual(api.mutations, [('UPLOAD', wine.SOURCE_ZIP)])
        self.assertTrue(result['completeAssetSetVerified']); self.assertFalse(result['publicationQualified'])
        self.assertEqual(len(api.downloads), 11)
        for changed in ('body', 'target'):
            api = FakeGithub(dict(lock, workflowRun=wine.PRODUCER_RUN), identities, draft=True)
            api.release['body'] = wine.release_body(lock)
            if changed == 'body': api.release['body'] += 'changed'
            else: api.release['target_commitish'] = 'b' * 40
            with self.subTest(changed=changed), self.assertRaises(ValueError): policy.upload_draft(api, Path('/synthetic'))
            self.assertEqual(api.mutations, [])


if __name__ == '__main__': unittest.main()
