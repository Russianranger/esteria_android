"""Small synthetic transfers only; no large download, compiler, helper or SQL."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_playerbots_helper as prepare


def identity(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class HelperAcquisition(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.recipe = b'name: Exact source-owned workflow fixture\n'
        self.recovery = dict(identity(self.recipe),
            gitBlob=hashlib.sha1(b'blob ' + str(len(self.recipe)).encode() + b'\0' + self.recipe).hexdigest(),
            integrationPath='.github/workflows/playerbots-schema.yml', integrationRevision='6' * 40)

    def zip(self, name, members):
        path = self.root / name
        with zipfile.ZipFile(path, 'w') as archive:
            for member, raw in members.items(): archive.writestr(member, raw)
        return path, prepare.files.identity(path)

    def remote(self, pin):
        producer = pin['producer']
        return [dict(id=producer['workflowRun'], head_sha=producer['integrationRevision'],
            status='completed', conclusion='success')] + [dict(id=pin[field]['id'], expired=False,
            size_in_bytes=pin[field]['bytes'], digest='sha256:' + pin[field]['sha256'],
            workflow_run=dict(id=producer['workflowRun'], head_sha=producer['integrationRevision']))
            for field in ('helperArtifact', 'evidenceArtifact')]

    def blob_responses(self):
        return [dict(type='file', path=self.recovery['integrationPath'], sha=self.recovery['gitBlob'], size=len(self.recipe)),
            dict(sha=self.recovery['gitBlob'], size=len(self.recipe), encoding='base64',
                 content=base64.b64encode(self.recipe).decode() + '\n')]

    def test_measured_lock_is_current_bound_and_declares_only_exact_omitted_recipe(self):
        pin, lock_identity = prepare.load_pin()
        self.assertEqual(lock_identity, prepare.files.identity(prepare.LOCK))
        self.assertEqual(len(pin['helperFiles']), 40)
        self.assertEqual(set(pin['recoveredRecipes']), {prepare.RECIPE})
        self.assertEqual(pin['producer']['workflowRun'], 41076505231)
        self.assertIs(pin['originalHelperArtifactComplete'], False)
        changed = copy.deepcopy(pin); changed['productionActivated'] = True
        with patch.object(prepare.candidate.modules, 'read_json', return_value=(changed, lock_identity)), \
                self.assertRaisesRegex(ValueError, 'input-scope-differs'): prepare.load_pin()

    def test_wrong_remote_run_artifact_or_existing_output_precedes_download(self):
        pin, pin_identity = prepare.load_pin(); api = Mock()
        for index in range(3):
            rows = self.remote(pin)
            if index == 0: rows[0]['head_sha'] = '0' * 40
            else: rows[index]['digest'] = 'sha256:' + '0' * 64
            api.json.side_effect = rows
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'producer-result|remote-artifact'):
                prepare.verify_remote(api, pin)
            api.download.assert_not_called()
        output = self.root / 'existing'; output.mkdir(); (output / 'saved').write_bytes(b'preserved')
        with patch.object(prepare, 'load_pin', return_value=(pin, pin_identity)), \
                self.assertRaisesRegex(ValueError, 'preparation-preserved'): prepare.prepare(output, api)
        self.assertEqual((output / 'saved').read_bytes(), b'preserved'); api.download.assert_not_called()

    def test_full_zip_pin_exact_members_and_fixed_permission_restoration(self):
        members = {'bin/playerbots-schema': b'fixture bytes, never executed', 'helper-build.json': b'fixture receipt'}
        path, artifact = self.zip('helper.zip', members)
        rows = {name: identity(raw) for name, raw in members.items()}; rows[prepare.RECIPE] = identity(self.recipe)
        output = self.root / 'payload'
        self.assertEqual(prepare.extract_selected(path, artifact, rows, output, approved_missing=[prepare.RECIPE]), {prepare.RECIPE})
        self.assertEqual((output / 'bin/playerbots-schema').stat().st_mode & 0o777, 0o555)
        self.assertEqual((output / 'helper-build.json').stat().st_mode & 0o777, 0o444)
        for name, raw in members.items(): self.assertEqual((output / name).read_bytes(), raw)
        with self.assertRaisesRegex(ValueError, 'zip-pin-differs'):
            prepare.extract_selected(path, dict(artifact, sha256='0' * 64), rows, self.root / 'not-created')
        self.assertFalse((self.root / 'not-created').exists())

    def test_extra_unapproved_missing_case_collision_and_symlink_members_refuse(self):
        path, artifact = self.zip('extra.zip', {'extra': b'raw'})
        with self.assertRaisesRegex(ValueError, 'unexpected-zip-member'):
            prepare.extract_selected(path, artifact, {'expected': identity(b'raw')}, self.root / 'extra-output')
        path, artifact = self.zip('missing.zip', {'helper-build.json': b'raw'})
        with self.assertRaisesRegex(ValueError, 'missing-member-not-approved'):
            prepare.extract_selected(path, artifact, {'helper-build.json': identity(b'raw'), 'unapproved': identity(b'raw')},
                                     self.root / 'missing-output', approved_missing=[prepare.RECIPE])
        with self.assertRaisesRegex(ValueError, 'case-collision'):
            prepare.safe_inventory({'path': identity(b'a'), 'PATH': identity(b'b')})
        path = self.root / 'link.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            item = zipfile.ZipInfo('link'); item.create_system = 3
            item.external_attr = (stat.S_IFLNK | 0o777) << 16; archive.writestr(item, '/outside')
        with self.assertRaises(ValueError):
            prepare.extract_selected(path, prepare.files.identity(path), {'link': identity(b'/outside')}, self.root / 'link-output')
        self.assertFalse((self.root / 'link-output').exists())

    def test_recovery_requires_original_commit_path_and_exact_base64_git_blob(self):
        payload = self.root / 'payload'; payload.mkdir(); api = Mock(); api.json.side_effect = self.blob_responses()
        proof = prepare.recover_recipe(api, payload, prepare.RECIPE, self.recovery)
        self.assertEqual((payload / prepare.RECIPE).read_bytes(), self.recipe)
        self.assertTrue(proof['originalCommitPathVerified']); self.assertTrue(proof['sourceOnlyRecovery'])
        self.assertEqual(api.json.call_args_list[0].args, ('/contents/.github/workflows/playerbots-schema.yml?ref=' + '6' * 40,))
        self.assertEqual(api.json.call_args_list[1].args, ('/git/blobs/' + self.recovery['gitBlob'],))
        with self.assertRaisesRegex(ValueError, 'existing-recovery-preserved'):
            prepare.recover_recipe(api, payload, prepare.RECIPE, self.recovery)
        for kind in ('path', 'blob-sha', 'bytes', 'base64'):
            other = self.root / kind; other.mkdir(); rows = self.blob_responses()
            if kind == 'path': rows[0]['sha'] = '0' * 40
            elif kind == 'blob-sha': rows[1]['sha'] = '0' * 40
            elif kind == 'bytes': rows[1]['content'] = base64.b64encode(b'changed source').decode()
            else: rows[1]['content'] = 'not base64 !'
            api.json.side_effect = rows
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'commit-path|blob-metadata|blob-identity|base64-invalid'):
                prepare.recover_recipe(api, other, prepare.RECIPE, self.recovery)
            self.assertFalse((other / prepare.RECIPE).exists())

    def test_native_copy_is_exact_from_pinned_evidence_zip(self):
        raw = b'{"scope":"host fixture only"}\n'
        path, artifact = self.zip('evidence.zip', {'native-sql-qualification.json': raw, 'ignored.log': b'public build log'})
        output = self.root / 'native.json'
        prepare.extract_native(path, artifact, identity(raw), output)
        self.assertEqual(output.read_bytes(), raw); self.assertEqual(output.stat().st_mode & 0o777, 0o444)
        with self.assertRaisesRegex(ValueError, 'native-proof-hash-differs'):
            prepare.extract_native(path, artifact, dict(identity(raw), sha256='0' * 64), self.root / 'bad-native')

    def test_full_mocked_acquisition_records_recovery_outside_payload_and_reverifies_candidate(self):
        helper = {'bin/playerbots-schema': b'host fixture bytes', 'helper-build.json': b'fixture build receipt'}
        helper_zip, helper_identity = self.zip('helper.zip', helper)
        native = b'{"hostFixture":true}\n'
        evidence_zip, evidence_identity = self.zip('evidence.zip', {'native-sql-qualification.json': native})
        pin = dict(producer=dict(workflowRun=1, integrationRevision='6' * 40),
            helperArtifact=dict(helper_identity, id=2), evidenceArtifact=dict(evidence_identity, id=3),
            helperFiles={name: identity(raw) for name, raw in helper.items()} | {prepare.RECIPE: identity(self.recipe)},
            recoveredRecipes={prepare.RECIPE: self.recovery}, helperBuildReceipt=identity(helper['helper-build.json']),
            nativeSqlReceipt=identity(native), executable=identity(helper['bin/playerbots-schema']))
        api = Mock(); api.json.side_effect = self.remote(pin) + self.blob_responses()
        def download(url, target, expected):
            shutil.copyfile(helper_zip if '/2/' in url else evidence_zip, target)
        api.download.side_effect = download
        value = dict(scope='synthetic optional candidate', productionActivated=False, runtimeFiles={}, companionFiles={})
        def build(payload, build_sha, receipt, native_sha, output):
            self.assertFalse((payload / 'acquisition.json').exists())
            self.assertEqual((payload / prepare.RECIPE).read_bytes(), self.recipe)
            output.mkdir(); (output / 'candidate-pin.json').write_bytes(prepare.encoded(value)); return value
        output = self.root / 'prepared'
        with patch.object(prepare, 'load_pin', return_value=(pin, identity(b'input lock fixture'))), \
                patch.object(prepare.shutil, 'disk_usage', return_value=shutil._ntuple_diskusage(2 << 30, 0, 2 << 30)), \
                patch.object(prepare.candidate, 'build', side_effect=build) as build_call, \
                patch.object(prepare.candidate, 'verify', return_value=value) as verify:
            proof = prepare.prepare(output, api)
        self.assertEqual(build_call.call_count, 1); verify.assert_called_once()
        acquired = json.loads((output / 'acquisition.json').read_bytes())
        self.assertFalse(acquired['originalHelperArtifactComplete'])
        self.assertEqual(acquired['extractedOriginalHelperFiles'], 2)
        self.assertEqual(set(acquired['recoveredRecipes']), {prepare.RECIPE})
        self.assertTrue(proof['candidateAllBytesVerified']); self.assertFalse(proof['productionActivated'])
        self.assertFalse(proof['sourceCompanionComplete']); self.assertFalse(proof['helperOrServerExecutedHere'])
        self.assertTrue(proof['candidateArchive']['fileModesPreserved'])
        self.assertFalse((output / 'inputs/helperArtifact.zip').exists())
        self.assertFalse((output / 'inputs/evidenceArtifact.zip').exists())

    def test_mode_preserving_candidate_archive_is_deterministic_and_rejects_corrupt_footer(self):
        root = self.root / 'candidate'; root.mkdir()
        helper, recipe = b'host fixture helper, never executed', b'name: hidden source recipe fixture\n'
        values = {'runtime/helpers/playerbots-schema': (helper, 0o555),
            'companion/build-payload/recipes/.github/workflows/source.yml': (recipe, 0o444)}
        for name, (raw, mode) in values.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw); path.chmod(mode)
        proof = dict(runtimeFiles={'helpers/playerbots-schema': dict(identity(helper), mode=0o555)},
            companionFiles={'build-payload/recipes/.github/workflows/source.yml': dict(identity(recipe), mode=0o444)})
        raw = prepare.encoded(proof); (root / 'candidate-pin.json').write_bytes(raw); pin = identity(raw)
        one, two = self.root / 'one.tar.gz', self.root / 'two.tar.gz'
        first = prepare.write_candidate_archive(root, proof, pin, one)
        second = prepare.write_candidate_archive(root, proof, pin, two)
        self.assertEqual(one.read_bytes(), two.read_bytes()); self.assertEqual(first['sha256'], second['sha256'])
        with tarfile.open(one, 'r:gz') as archive:
            members = archive.getmembers(); self.assertEqual(len(members), 3)
            for item in members:
                self.assertTrue(item.isfile()); self.assertEqual((item.uid, item.gid, item.mtime), (0, 0, 0))
                self.assertEqual((item.uname, item.gname), ('', ''))
                self.assertEqual(item.mode, 0o555 if item.name.startswith('runtime/') else 0o444)
            self.assertEqual(archive.extractfile('companion/build-payload/recipes/.github/workflows/source.yml').read(), recipe)
        inventory = {'runtime/' + name: row for name, row in proof['runtimeFiles'].items()} | {
            'companion/' + name: row for name, row in proof['companionFiles'].items()} | {
            'candidate-pin.json': dict(pin, mode=0o444)}
        broken = bytearray(one.read_bytes()); broken[-8] ^= 1
        bad = self.root / 'bad.tar.gz'; bad.write_bytes(broken)
        with self.assertRaises(OSError): prepare.candidate.programs.engine.verify_archive(bad, inventory)


if __name__ == '__main__': unittest.main()
