"""Metadata/admission guards only; synthetic records do not establish native execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools import measure_ordered_extractor_update as measurement


class ProducerAndArtifactAdmission(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ordered-update-measurement-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.revision = 'a' * 40
        self.run = dict(id=11, head_sha=self.revision, head_branch='non-custom',
            path='.github/workflows/server-extractor-order.yml', event='push',
            repository=dict(id=7, full_name=measurement.REPOSITORY),
            head_repository=dict(id=7, full_name=measurement.REPOSITORY),
            status='completed', conclusion='success')
        self.job = dict(id=22, run_id=11, head_sha=self.revision, name='ordered-targets',
                        status='completed', conclusion='success')
        self.path = self.root / 'payload.zip'
        with zipfile.ZipFile(self.path, 'w') as archive:
            archive.writestr('fixture.txt', b'synthetic metadata fixture, not an extractor')
        actual = measurement.identity(self.path)
        self.metadata = dict(id=33, name='separate-ordered-extractors-' + self.revision,
            size_in_bytes=actual['bytes'], digest='sha256:' + actual['sha256'], expired=False,
            workflow_run=dict(id=11, head_sha=self.revision, head_branch='non-custom',
                              repository_id=7, head_repository_id=7))

    def admitted(self, run=None, jobs=None):
        return measurement.successful_job(run or self.run, jobs or [self.job],
                                          'server-extractor-order.yml', 'ordered-targets')

    def test_same_named_fork_changed_revision_and_nonfinal_job_cannot_supply_evidence(self):
        self.assertEqual(self.admitted(), self.job)
        for key, value in (('head_repository', dict(full_name='Other/esteria_android')),
                           ('path', '.github/workflows/another.yml'),
                           ('head_branch', 'main'), ('status', 'in_progress'),
                           ('conclusion', 'failure')):
            bad = copy.deepcopy(self.run); bad[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'exact-repository-run'):
                self.admitted(run=bad)
        for key, value in (('head_sha', 'b' * 40), ('run_id', 99), ('conclusion', 'cancelled')):
            bad = dict(self.job, **{key: value})
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source-matched-job'):
                self.admitted(jobs=[bad])
        with self.assertRaisesRegex(ValueError, 'one-producer-job'):
            self.admitted(jobs=[self.job, dict(self.job, id=23)])

    def test_api_identity_and_every_local_zip_byte_are_required(self):
        expected = dict(id=33, **measurement.identity(self.path))
        self.assertEqual(measurement.artifact_pin(self.metadata, self.run, self.path,
                         'separate-ordered-extractors-'), expected)
        for key, value in (('expired', True), ('id', '33'), ('name', 'unrelated'),
                           ('digest', 'sha256:' + '0' * 64)):
            bad = dict(self.metadata, **{key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                measurement.artifact_pin(bad, self.run, self.path, 'separate-ordered-extractors-')
        bad = copy.deepcopy(self.metadata); bad['workflow_run']['repository_id'] = 8
        with self.assertRaisesRegex(ValueError, 'artifact-metadata'):
            measurement.artifact_pin(bad, self.run, self.path, 'separate-ordered-extractors-')
        with self.path.open('ab') as outgoing: outgoing.write(b'changed after download')
        with self.assertRaisesRegex(ValueError, 'zip-hash-or-length'):
            measurement.artifact_pin(self.metadata, self.run, self.path, 'separate-ordered-extractors-')

    def test_json_ambiguity_and_nonfinite_qualification_claims_are_refused(self):
        self.assertEqual(measurement.document(b'{"phase":"complete"}'), {'phase': 'complete'})
        for raw in (b'{"phase":"failed","phase":"complete"}', b'{"value":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): measurement.document(raw)

    def test_incomplete_native_receipt_does_not_create_a_positive_candidate(self):
        # A success-shaped workflow and ZIP name are insufficient: the payload
        # must also carry its complete dependency capture and exact native pair.
        bad = self.root / 'incomplete.zip'
        with zipfile.ZipFile(bad, 'w') as archive:
            archive.writestr('ordered-build.json', json.dumps(dict(phase='complete')))
        base = json.loads(measurement.seal.LOCK.read_text())
        with self.assertRaisesRegex(ValueError, 'dependency-capture-required'):
            measurement.native_candidate(base, self.run, self.job, {}, {}, bad, self.path)

    def test_source_stage_refuses_extra_payload_or_an_unsealed_receipt(self):
        base = json.loads(measurement.provider.LOCK.read_text())
        measured = json.loads(measurement.seal.LOCK.read_text())
        archive = self.root / 'source.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr(measurement.seal.SOURCE_ARCHIVE, b'not actual sources')
            output.writestr(measurement.seal.RECEIPT, b'{}')
            output.writestr('unselected.txt', b'extra')
        with self.assertRaisesRegex(ValueError, 'source-artifact-member-set'):
            measurement.source_candidate(base, measured, self.run, self.job, {}, archive)
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr(measurement.seal.SOURCE_ARCHIVE, b'not actual sources')
            output.writestr(measurement.seal.RECEIPT, b'{}')
        with self.assertRaisesRegex(ValueError, 'complete-source-seal-required'):
            measurement.source_candidate(base, measured, self.run, self.job, {}, archive)


class ComposedInputMeasurement(unittest.TestCase):
    """Transfer/rollback fixtures below do not qualify any native executable."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='composed-update-measurement-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.run = dict(id=44, head_sha='d' * 40, head_branch='non-custom', event='push',
            path='.github/workflows/server-data-tools.yml', status='completed', conclusion='success',
            repository=dict(id=7, full_name=measurement.REPOSITORY),
            head_repository=dict(id=7, full_name=measurement.REPOSITORY))
        self.jobs = [dict(id=55 + i, name=name, run_id=44, head_sha='d' * 40,
                          status='completed', conclusion='success')
                     for i, name in enumerate(('package', 'native'))]
        self.package, self.package_row = self.archive('package.zip', measurement.COMPOSED_PACKAGE_MEMBERS,
                                                     'composed-data-tools-package-', 66)
        self.native, self.native_row = self.archive('native.zip', measurement.COMPOSED_NATIVE_MEMBERS,
                                                   'composed-data-tools-native-evidence-', 77)

    def archive(self, name, selected, prefix, artifact_id):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            for member in selected:
                archive.writestr(member, b'{}\n' if member.endswith('.json') else b'synthetic bounded archive')
            archive.writestr('diagnostic-only.log', b'unselected fixture diagnostic')
        row = measurement.identity(path)
        metadata = dict(id=artifact_id, name=prefix + self.run['head_sha'], expired=False,
            size_in_bytes=row['bytes'], digest='sha256:' + row['sha256'], workflow_run=dict(
                id=44, head_sha=self.run['head_sha'], head_branch='non-custom', repository_id=7, head_repository_id=7))
        return path, metadata

    def test_only_fixed_package_and_native_closures_are_extracted_and_hashed(self):
        target = self.root / 'selected'; target.mkdir()
        package = measurement.extract_selected(self.package, measurement.COMPOSED_PACKAGE_MEMBERS, target)
        native = measurement.extract_selected(self.native, measurement.COMPOSED_NATIVE_MEMBERS, target)
        self.assertEqual(len(package), 10); self.assertEqual(len(native), 3)
        expected = set(measurement.COMPOSED_PACKAGE_MEMBERS.values()) | set(measurement.COMPOSED_NATIVE_MEMBERS.values())
        self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}, expected)
        for row in [*package.values(), *native.values()]:
            self.assertEqual(measurement.identity(target / row['target']), {k: row[k] for k in ('bytes', 'sha256')})
        with self.assertRaisesRegex(ValueError, 'selected-member-missing'):
            measurement.extract_selected(self.native, {'missing.json': 'native/missing.json'}, target)

    def test_native_job_must_pass_even_when_run_and_package_job_claim_success(self):
        jobs = copy.deepcopy(self.jobs); jobs[1]['conclusion'] = 'failure'
        output = self.root / 'not-published'
        with self.assertRaisesRegex(ValueError, 'source-matched-job'):
            measurement.composed_candidates(self.run, jobs, self.package_row, self.package,
                                             self.native_row, self.native, output)
        self.assertFalse(output.exists())

    def test_candidate_reader_failure_restores_lock_paths_and_publishes_nothing(self):
        before = measurement.provider.LOCK, measurement.qualified_inputs.LOCK
        output = self.root / 'not-published'
        def incomplete_measurement(package, native, stock_debug, destination, **kwargs):
            destination.mkdir()
            (destination / 'data-tools-provider.lock.json').write_bytes(b'{}\n')
            return {'fixture': 'deliberately incomplete; never native qualification'}
        with patch.object(measurement.composed_measurement, 'measure', side_effect=incomplete_measurement):
            with self.assertRaisesRegex(ValueError, 'server-data-tools-input-scope'):
                measurement.composed_candidates(self.run, self.jobs, self.package_row, self.package,
                                                 self.native_row, self.native, output)
        self.assertEqual((measurement.provider.LOCK, measurement.qualified_inputs.LOCK), before)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.root.glob('.not-published.stage-*')))


if __name__ == '__main__': unittest.main()
