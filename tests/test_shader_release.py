"""Write-once dependency guards with explicit synthetic compiler fixtures."""
import copy
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tests import test_shader_provider as fixtures
from tools import release_shader_tools as release


class ShaderRelease(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ShaderProvider('test_deterministic_archive_full_readback_and_no_replace')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root; self.provider = self.fixture.output
        proof = release.provider.build(self.fixture.bundle, self.provider)
        self.pin = release.provider.load_pin()
        self.lock = dict(formatVersion=1, repository=release.shared.REPOSITORY,
            scope='shader-tools-inputs-write-once-prerelease', tag='deps-shader-tools-synthetic', targetCommit='a'*40,
            clientRevision=self.pin['clientRevision'], compilerIntegrationRevision=self.pin['compilerIntegrationRevision'],
            workflowRun=100, providerLockSha256=release.provider.bundle.identity(release.provider.LOCK)['sha256'],
            artifact=dict(id=123, name='synthetic-original.zip', bytes=1, sha256='0'*64),
            artifactPrefix='out/turnip/payload/', originalRunConclusion='failure',
            archive={k: proof['archive'][k] for k in ('bytes', 'sha256')})
        self.candidate = self.root / 'candidate'

    def stage(self):
        return release.stage(self.provider, self.candidate, self.lock, self.pin)

    def test_full_candidate_readback_export_and_existing_destinations_retained(self):
        identities = self.stage()
        self.assertEqual(set(identities), release.RELEASE_FILES)
        output = self.root / 'exported'
        self.assertTrue(release.export_provider(self.candidate, output, self.lock, self.pin)['providerVerified'])
        original = self.provider / 'assets' / release.provider.ASSETS
        for file in (output / 'assets' / release.provider.ASSETS).iterdir():
            self.assertEqual(release.shared.identity(file), release.shared.identity(original / file.name))
        for operation in (lambda: self.stage(), lambda: release.export_provider(self.candidate, output, self.lock, self.pin)):
            with self.assertRaisesRegex(ValueError, 'output-exists'): operation()
        self.assertEqual(identities, release.verify_candidate(self.candidate, self.lock, self.pin))

    def test_changed_scope_notice_hash_or_extra_state_is_rejected(self):
        self.stage()
        for name in ('NOTICE.txt', 'bundle.json', 'SHA256SUMS', release.DESCRIPTOR):
            path = self.candidate / name; original = path.read_bytes(); path.write_bytes(original + b'changed')
            with self.subTest(name=name), self.assertRaises(ValueError):
                release.verify_candidate(self.candidate, self.lock, self.pin)
            path.write_bytes(original)
        private = self.candidate / 'database-secret'; private.write_bytes(b'not-a-real-secret')
        with self.assertRaisesRegex(ValueError, 'file-set-mismatch'): release.verify_candidate(self.candidate, self.lock, self.pin)
        self.assertEqual(private.read_bytes(), b'not-a-real-secret')

    def test_public_fetch_needs_pinned_owned_urls_and_never_uses_actions(self):
        identities = self.stage(); lock = copy.deepcopy(self.lock)
        lock['published'] = dict(repository=release.shared.REPOSITORY, tag=lock['tag'], targetCommit=lock['targetCommit'],
            assets={name: dict(pin, url='https://github.com/'+release.shared.REPOSITORY+'/releases/download/'+lock['tag']+'/'+name)
                    for name, pin in identities.items()})
        requests = []
        class API:
            def download(_, url, path, expected):
                requests.append(url); source = self.candidate / path.name
                self.assertEqual(release.shared.identity(source), {k: expected[k] for k in ('bytes', 'sha256')})
                shutil.copyfile(source, path)
        result = release.fetch(API(), self.root / 'fetched', lock, self.pin)
        self.assertEqual(result, identities); self.assertEqual(len(requests), len(release.RELEASE_FILES))
        self.assertTrue(all('/releases/download/' in url for url in requests))
        lock['published']['assets']['NOTICE.txt']['url'] = 'https://elsewhere.invalid/NOTICE.txt'
        with self.assertRaisesRegex(ValueError, 'download-pin'): release.fetch(API(), self.root / 'foreign', lock, self.pin)
        self.assertFalse((self.root / 'foreign').exists())
        lock['published'] = None
        with self.assertRaisesRegex(ValueError, 'not-yet-recorded'): release.fetch(API(), self.root / 'unpublished', lock, self.pin)

    def original_zip(self):
        selected = release.selected_originals(self.pin); target = self.root / 'original.zip'
        with zipfile.ZipFile(target, 'w') as archive:
            for name in selected: archive.write(self.fixture.fixture.payload / name, self.lock['artifactPrefix'] + name)
        self.lock['artifact'].update(release.shared.identity(target)); return target

    def test_original_zip_only_extracts_exact_source_compiler_evidence_subset(self):
        artifact = self.original_zip(); output = self.root / 'original-subset'
        release.extract_original(artifact, output, self.lock, self.pin)
        self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}, set(release.selected_originals(self.pin)))
        with self.assertRaisesRegex(ValueError, 'output-exists'): release.extract_original(artifact, output, self.lock, self.pin)
        artifact.write_bytes(artifact.read_bytes() + b'trailing')
        with self.assertRaisesRegex(ValueError, 'identity'): release.extract_original(artifact, self.root / 'tampered', self.lock, self.pin)
        self.assertFalse((self.root / 'tampered').exists())

    def test_changed_original_run_or_artifact_is_rejected_before_download(self):
        lock = self.lock; calls = []
        run = dict(head_sha=lock['compilerIntegrationRevision'], status='completed', conclusion='failure', head_branch='android/client-server')
        row = dict(name=lock['artifact']['name'], size_in_bytes=lock['artifact']['bytes'], digest='sha256:'+lock['artifact']['sha256'],
                   expired=False, workflow_run=dict(id=lock['workflowRun'], head_sha=lock['compilerIntegrationRevision']))
        class API:
            def json(_, path): return run if '/runs/' in path else row
            def download(_, *args): calls.append(args)
        release.download_original(API(), Path('/not-downloaded-by-fake'), lock)
        self.assertEqual(len(calls), 1)
        for record, field, value in ((run,'head_sha','b'*40),(run,'status','in_progress'),(run,'conclusion','success'),(row,'expired',True),(row,'digest','sha256:'+'f'*64)):
            previous = record[field]; record[field] = value; calls.clear()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'provenance|mismatched'):
                release.download_original(API(), Path('/must-not-download'), lock)
            self.assertEqual(calls, []); record[field] = previous


class MeasuredReleasePin(unittest.TestCase):
    def test_actual_pin_preserves_compiler_scope_and_all_three_originals(self):
        lock, pin = release.load_lock()
        self.assertEqual(lock['archive']['sha256'], '7937274c8379882a045fb93c50ea9bb8575e25d5f769f7d8a3077d1518522c57')
        self.assertEqual(len([name for name in pin['files'] if name.startswith('corresponding-source/')]), 3)
        self.assertEqual(lock['originalRunConclusion'], 'failure')
        self.assertTrue(pin['nativeCompilerFixtureQualified']); self.assertFalse(pin['androidQualified'])


if __name__ == '__main__': unittest.main()
