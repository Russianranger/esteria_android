"""Exact source transfer tests; fixtures do not assert native qualification."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_ordered_extractor_sources as inputs


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class OrderedSourceInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='ordered-source-inputs-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.members = {'bin/' + name: ('synthetic ' + name).encode() for name in inputs.seal.TARGETS}
        self.members['build/dependency-observation/observation.json'] = b'{"fixture":true}\n'
        self.qualified = dict(phase='complete', integrationRevision='a' * 40,
            scope='native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups',
            actualTargetCompileSucceeded=True, sourceCompanionComplete=False,
            payloadFiles={name: identity(raw) for name, raw in self.members.items()})
        raw = inputs.engine.canonical(self.qualified)
        self.native = dict(workflowRun=12, job=34, integrationRevision='a' * 40, receipt=identity(raw),
            dependencyObservation=identity(self.members['build/dependency-observation/observation.json']),
            programs={name: identity(self.members['bin/' + name]) for name in inputs.seal.TARGETS})
        self.members['ordered-build.json'] = raw

    def artifact(self, changes=None):
        path = self.root / 'artifact.zip'
        members = dict(self.members); members.update(changes or {})
        with zipfile.ZipFile(path, 'w') as archive:
            for name, raw in members.items(): archive.writestr(name, raw)
        self.native['payloadArtifact'] = dict(id=56, **inputs.files.identity(path))
        return path

    def test_complete_payload_is_read_back_and_only_two_fixed_programs_are_executable(self):
        output = self.root / 'output'; output.mkdir()
        path = self.artifact()
        actual = inputs.extract_payload(path, output, dict(nativeBuild=self.native))
        self.assertEqual(actual, self.qualified)
        for name, raw in self.members.items():
            staged = output / 'payload' / name
            self.assertEqual(staged.read_bytes(), raw)
            self.assertEqual(staged.stat().st_mode & 0o777, 0o555 if name.startswith('bin/') else 0o444)

    def test_unknown_member_and_changed_member_cannot_be_extracted_as_qualified_input(self):
        for changed, message in (({'extra': b'unknown'}, 'complete-file-set'),
                                 ({'bin/map_extractor': b'changed bytes'}, 'zip-member')):
            path = self.artifact(changed); output = self.root / ('out-' + message); output.mkdir()
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, message):
                inputs.extract_payload(path, output, dict(nativeBuild=self.native))

    def test_changed_zip_or_unbound_native_receipt_refuses(self):
        path = self.artifact(); output = self.root / 'output'; output.mkdir()
        with path.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'zip-identity'):
            inputs.extract_payload(path, output, dict(nativeBuild=self.native))
        path = self.artifact({'ordered-build.json': b'{}'})
        with self.assertRaisesRegex(ValueError, 'receipt-identity'):
            inputs.extract_payload(path, output, dict(nativeBuild=self.native))

    def test_native_run_and_selected_job_must_both_be_successful_and_same_revision(self):
        run = dict(id=12, head_sha='a' * 40, status='completed', conclusion='success')
        job = dict(id=34, run_id=12, status='completed', conclusion='success')
        api = Mock(); api.json.side_effect = [run, job]
        inputs.verify_native_remote(api, self.native)
        for bad_run, bad_job in ((dict(run, head_sha='b' * 40), job),
                                 (run, dict(job, run_id=13)), (run, dict(job, conclusion='failure'))):
            api.json.side_effect = [bad_run, bad_job]
            with self.assertRaisesRegex(ValueError, 'run-or-job-not-successful'):
                inputs.verify_native_remote(api, self.native)

    def test_explicit_pending_pin_refuses_before_any_download_or_output(self):
        api = Mock(); output = self.root / 'preserved'
        pin = json.loads(inputs.seal.LOCK.read_text()); pin['state'] = 'pending-native-dependency-capture'
        lock = self.root / 'pending.lock.json'; lock.write_text(json.dumps(pin))
        with patch.object(inputs.seal, 'LOCK', lock), self.assertRaisesRegex(ValueError, 'measured-input-pin-required'):
            inputs.acquire(output, api)
        api.json.assert_not_called(); api.download.assert_not_called()
        self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
