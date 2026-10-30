import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from tools import prepare_server_requalification as stage


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class RequalificationGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pin, _ = stage.load_pin()

    def archive(self, name, members):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for filename, raw in members.items():
                archive.writestr(filename, raw)
        return path

    def installed(self, *, corrupt=False, extra=False, duplicate=False):
        lock = b'fixture original lock\n'; binary = b'fixture binary\0'
        pin = dict(self.pin, sourceLockSha256=hashlib.sha256(lock).hexdigest())
        build = dict(schemaVersion=1, architecture='Linux-ARM64', sourceCheckoutAndPatchesVerified=True,
            hostLoaderSmoke={'qualified': True}, integrationRevision=pin['integrationRevision'],
            buildId=pin['buildId'], sourcesLock=identity(lock), files=[
                dict(path='sources.lock.json', **identity(lock)),
                dict(path='bin/authserver', **identity(binary), elf={'machine': 'AArch64'})])
        if duplicate: build['files'].append(copy.deepcopy(build['files'][0]))
        members = {'server-build.json': json.dumps(build).encode(), 'sources.lock.json': lock,
                   'bin/authserver': b'changed binary\0' if corrupt else binary}
        if extra: members['accounts/private-secret'] = b'never accepted'
        return self.archive('install.zip', members), pin, binary

    def remote(self):
        run = dict(id=self.pin['workflowRun'], head_sha=self.pin['integrationRevision'], status='completed', conclusion='failure')
        job = dict(id=self.pin['job'], run_id=self.pin['workflowRun'], status='completed', conclusion='failure',
            steps=[dict(number=n, conclusion='failure' if n == 21 else 'success') for n in (12,15,16,17,18,19,20,21,24,25)])
        artifacts = {row['id']: dict(id=row['id'], expired=False, size_in_bytes=row['bytes'], digest='sha256:'+row['sha256'],
            workflow_run={'id': self.pin['workflowRun'], 'head_sha': self.pin['integrationRevision']})
            for row in self.pin['artifacts'].values()}
        api = Mock()
        def request(path):
            if path.startswith('/actions/runs/'): return run
            if path.startswith('/actions/jobs/'): return job
            return artifacts[int(path.rsplit('/', 1)[1])]
        api.json.side_effect = request
        return api, run, job, artifacts

    def test_exact_failed_runtime_job_is_accepted_only_after_all_link_and_package_gates(self):
        api, run, job, artifacts = self.remote()
        stage.verify_remote(api, self.pin)
        job['steps'][2]['conclusion'] = 'failure'
        with self.assertRaisesRegex(ValueError, 'prerequisite did not pass'):
            stage.verify_remote(api, self.pin)
        api.download.assert_not_called()

    def test_substituted_revision_or_artifact_digest_is_rejected_before_download(self):
        api, run, job, artifacts = self.remote()
        run['head_sha'] = '0' * 40
        with self.assertRaisesRegex(ValueError, 'workflow result'):
            stage.verify_remote(api, self.pin)
        run['head_sha'] = self.pin['integrationRevision']
        next(iter(artifacts.values()))['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(ValueError, 'GitHub identity changed'):
            stage.verify_remote(api, self.pin)
        api.download.assert_not_called()

    def test_real_zip_extract_preserves_every_byte_and_restores_executable_mode(self):
        archive, pin, binary = self.installed()
        target = self.root / 'install'
        stage.extract_install(archive, target, pin)
        self.assertEqual((target / 'bin/authserver').read_bytes(), binary)
        self.assertEqual((target / 'bin/authserver').stat().st_mode & 0o777, 0o555)
        with self.assertRaisesRegex(ValueError, 'existing compiled install preserved'):
            stage.extract_install(archive, target, pin)
        self.assertEqual((target / 'bin/authserver').read_bytes(), binary)

    def test_changed_binary_is_rejected_and_partial_fixture_retained(self):
        archive, pin, _ = self.installed(corrupt=True)
        with self.assertRaisesRegex(ValueError, 'member hash differs'):
            stage.extract_install(archive, self.root / 'partial', pin)
        self.assertTrue((self.root / 'partial').exists())

    def test_extra_private_tree_and_duplicate_declared_paths_cannot_enter_install(self):
        for keyword in ('extra', 'duplicate'):
            with self.subTest(keyword=keyword):
                archive, pin, _ = self.installed(**{keyword: True})
                with self.assertRaises(ValueError): stage.extract_install(archive, self.root / keyword, pin)
                self.assertFalse((self.root / keyword).exists())

    def test_bounded_zip_refuses_special_files_and_metadata_ambiguity(self):
        archive = self.root / 'fifo.zip'
        info = zipfile.ZipInfo('pipe'); info.create_system = 3; info.external_attr = (stat.S_IFIFO | 0o600) << 16
        with zipfile.ZipFile(archive, 'w') as z: z.writestr(info, b'')
        with self.assertRaisesRegex(ValueError, 'nonregular'):
            with stage.bounded_zip(archive): pass
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            stage.unique_member({'a/receipt.json': None, 'b/receipt.json': None}, 'receipt.json')

    def test_existing_output_never_downloads_or_changes_saved_bytes(self):
        output = self.root / 'existing'; output.mkdir(); saved = output / 'saved'; saved.write_bytes(b'preserve')
        api = Mock()
        with patch.object(stage, 'load_pin') as load, self.assertRaisesRegex(ValueError, 'staging preserved'):
            stage.prepare(output, api)
        load.assert_not_called(); api.json.assert_not_called(); api.download.assert_not_called()
        self.assertEqual(saved.read_bytes(), b'preserve')


if __name__ == '__main__': unittest.main()
