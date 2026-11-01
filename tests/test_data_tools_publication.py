"""Preservation gates; fixture metadata never qualifies real extractor bytes."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import publish_data_tools_update as public


def pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class DataToolsPublication(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.selected = dict(providerInputLock=pin(b'fixture-provider'), qualifiedInputLock=pin(b'fixture-qualified'))
        self.artifacts = {key: dict(pin((key + '-fixture').encode()), id=10 + n, workflowRun=77,
            integrationRevision='a' * 40, members={}) for n, key in enumerate(('package', 'native'))}
        self.lock = dict(formatVersion=1, scope=public.SCOPE, repository=public.REPOSITORY, tag=public.TAG,
            targetCommit='a' * 40, workflowRun=77, packageJobId=80, nativeJobId=81,
            selectedInputs=self.selected, artifacts=self.artifacts, **{k: False for k in public.FALSE_FLAGS})
        self.input_pin = dict(artifacts=self.artifacts)

    def metadata(self):
        run = dict(id=77, repository=dict(full_name=public.REPOSITORY), head_repository=dict(full_name=public.REPOSITORY),
            head_sha='a' * 40, head_branch='non-custom', path=public.WORKFLOW,
            status='completed', conclusion='success', event='push', run_attempt=1)
        job_steps = [
            ['Derive only ordered readers and compose unchanged stock tools',
             'Bind transfer receipt and completely read back original paired debug'],
            ['Run all four derived entry points and exact YAML in the reference image',
             'Exercise the actual stripped ordered pair through synthetic source-bound lookups']]
        jobs = dict(jobs=[dict(id=80 + n, run_id=77, name=key, head_sha='a' * 40,
            status='completed', conclusion='success', steps=[dict(name=name, status='completed', conclusion='success')
                for name in job_steps[n]]) for n, key in enumerate(('package', 'native'))])
        rows = []
        for key in ('package', 'native'):
            row = self.artifacts[key]; selected = public.artifact_selection(self.lock, key)
            rows.append(dict(id=row['id'], name=selected['name'], size_in_bytes=row['bytes'],
                digest='sha256:' + row['sha256'], expired=False,
                workflow_run=dict(id=77, head_sha='a' * 40, head_branch='non-custom')))
        return run, jobs, *rows

    def publication(self):
        base = 'https://github.com/' + public.REPOSITORY + '/releases/'
        return dict(formatVersion=1, scope=public.SCOPE, repository=public.REPOSITORY, tag=public.TAG,
            targetCommit='a' * 40, releaseId=100, url=base + 'tag/' + public.TAG, publisherNeverOverwrites=True,
            assets={name: dict(row, assetId=200 + n, url=base + 'download/' + public.TAG + '/' + name)
                for n, (name, row) in enumerate(public.expected_files(self.lock).items())})

    def test_measure_requires_exact_successful_source_jobs_and_artifact_metadata(self):
        args = self.metadata()
        with mock.patch.object(public.inputs, 'load_pin', return_value=self.input_pin), \
                mock.patch.object(public, 'selected_inputs', return_value=self.selected):
            self.assertEqual(public.measure(*args), self.lock)
            for slot, field, value in ((0, 'conclusion', 'failure'), (0, 'head_branch', 'main'),
                    (0, 'path', '.github/workflows/android.yml'), (2, 'digest', 'sha256:' + '0' * 64),
                    (3, 'expired', True)):
                bad = copy.deepcopy(args); bad[slot][field] = value
                with self.subTest(slot=slot, field=field), self.assertRaises(ValueError): public.measure(*bad)
            bad = copy.deepcopy(args); bad[1]['jobs'][1]['steps'][0]['conclusion'] = 'skipped'
            with self.assertRaises(ValueError): public.measure(*bad)
            bad = copy.deepcopy(args); bad[1]['jobs'][1]['head_sha'] = 'b' * 40
            with self.assertRaises(ValueError): public.measure(*bad)

    def test_lock_refuses_source_or_qualified_pin_and_boundary_changes(self):
        self.assertEqual(public.validate_lock(self.lock, self.selected, self.input_pin), self.lock)
        for key, value in (('tag', 'replace-old-release'), ('targetCommit', 'floating'),
                ('workflowRun', True), ('packageJobId', 81), ('androidRuntimeQualified', True)):
            changed = copy.deepcopy(self.lock); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                public.validate_lock(changed, self.selected, self.input_pin)
        changed = copy.deepcopy(self.selected); changed['qualifiedInputLock'] = pin(b'different')
        with self.assertRaises(ValueError): public.validate_lock(self.lock, changed, self.input_pin)

    def test_manifest_and_checksums_bind_original_zips_without_repacking(self):
        expected = public.expected_files(self.lock)
        self.assertEqual(set(expected), {*public.NAMES.values(), 'release-manifest.json', 'SHA256SUMS'})
        self.assertEqual(expected[public.NAMES['package']], pin(b'package-fixture'))
        self.assertEqual(expected['release-manifest.json'], pin(public.manifest(self.lock)))
        sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(expected.items())
            if name != 'SHA256SUMS').encode()
        self.assertEqual(expected['SHA256SUMS'], pin(sums))

    def stage_files(self):
        release = self.root / 'release'; release.mkdir()
        for key in ('package', 'native'): (release / public.NAMES[key]).write_bytes((key + '-fixture').encode())
        (release / 'release-manifest.json').write_bytes(public.manifest(self.lock))
        expected = public.expected_files(self.lock)
        (release / 'SHA256SUMS').write_text(''.join(row['sha256'] + '  ' + name + '\n'
            for name, row in sorted(expected.items()) if name != 'SHA256SUMS'))
        path = self.root / 'lock.json'; path.write_bytes(public.encoded(self.lock))
        proof = dict(lock=public.identity(path), completeSourceAndPairedDebugVerified=True, assets=expected)
        return path, proof

    def test_existing_tag_or_changed_staged_bytes_fail_before_release_mutation(self):
        path, proof = self.stage_files(); api = mock.Mock()
        api.json.return_value = dict(existing=True)
        with mock.patch.object(public, 'LOCK', path), mock.patch.object(public, 'load_lock', return_value=self.lock):
            with self.assertRaisesRegex(ValueError, 'existing-tag-or-release-preserved'):
                public.publish(api, self.root, proof)
            self.assertTrue(all(call.kwargs.get('method', 'GET') == 'GET' for call in api.json.call_args_list))
            api.upload.assert_not_called(); api.reset_mock()
            (self.root / 'release' / public.NAMES['package']).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'staged-qualification-or-bytes-changed'):
                public.publish(api, self.root, proof)
            api.json.assert_not_called(); api.upload.assert_not_called()

    def put_public_receipts(self):
        directory = self.root / public.DIRECTORY; directory.mkdir(parents=True)
        publication = self.publication()
        (directory / public.PUBLICATION).write_bytes(public.encoded(publication))
        read = dict(formatVersion=1, scope='anonymous-data-tools-complete-source-debug-readback', releaseId=100,
            targetCommit='a' * 40, assets=public.expected_files(self.lock), allStoredBytesReadBack=True,
            completeSourcesAndPairedDebugVerified=True, qualifiedInputLock=self.selected['qualifiedInputLock'],
            **{k: False for k in public.FALSE_FLAGS})
        (directory / public.READBACK).write_bytes(public.encoded(read))
        return directory, read

    def test_partial_or_mutated_public_receipt_never_falls_back(self):
        directory, read = self.put_public_receipts()
        qpath = self.root / 'qualified.json'; qpath.write_bytes(b'fixture-qualified')
        with mock.patch.object(public, 'ROOT', self.root), mock.patch.object(public, 'load_lock', return_value=self.lock), \
                mock.patch.object(public.inputs, 'LOCK', qpath):
            self.assertEqual(public.public_selection(self.input_pin)['publication']['releaseId'], 100)
            changed = dict(read, completeSourcesAndPairedDebugVerified=False)
            (directory / public.READBACK).write_bytes(public.encoded(changed))
            with self.assertRaisesRegex(ValueError, 'full-anonymous-readback-required'):
                public.public_selection(self.input_pin)
            (directory / public.READBACK).unlink()
            with self.assertRaisesRegex(ValueError, 'partial-receipts-refused'):
                public.public_selection(self.input_pin)

    def test_broken_explicit_public_selection_refuses_before_output_or_actions(self):
        out = self.root / 'fresh'
        with mock.patch.object(public.inputs, 'load_pin', return_value=self.input_pin), \
                mock.patch.object(public, 'public_selection', side_effect=ValueError('broken-explicit-receipt')), \
                mock.patch.object(public.inputs.transfer, 'verify_remote') as remote:
            with self.assertRaisesRegex(ValueError, 'broken-explicit-receipt'): public.inputs.acquire(out)
        self.assertFalse(out.exists()); remote.assert_not_called()


if __name__ == '__main__': unittest.main()
