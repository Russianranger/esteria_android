"""Concrete metadata policy: one empty draft, no adoption or upload authority."""
import copy
import hashlib
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import create_local_server_draft as draft


class LocalServerDraftCreation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='draft-metadata-policy-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.pin = draft.load_pin(); self.body = 'TEST_ONLY measured draft body\n'
        self.pin['measurementFiles']['release-body.txt'] = draft.digest(self.body.encode())
        self.context = dict(repository=draft.REPOSITORY, ref='refs/heads/android/client-server',
            event='push', run=456, revision='b' * 40)

    def release(self, **changes):
        row = dict(id=123, tag_name=draft.TAG, target_commitish=self.pin['targetCommit'], draft=True,
            prerelease=True, name=draft.NAME, body=self.body, author=dict(login='github-actions[bot]'))
        row.update(changes); return row

    def api(self):
        api = mock.Mock(); api.json.side_effect = [None, [], self.release(), self.release(), None, []]
        return api

    def test_committed_request_is_explicit_and_matches_twelve_measured_assets(self):
        pin = draft.load_pin()
        self.assertEqual(pin['workflowRun'], 41113370383)
        self.assertEqual(pin['targetCommit'], '7e498c50cdf55027e679d63e31f0a5e4b117f934')
        self.assertEqual(pin['state'], 'creation-authorized')
        self.assertEqual(len(pin['assets']), 12)
        self.assertEqual(sum(row['bytes'] for row in pin['assets'].values()), 1783413529)
        self.assertGreater(pin['candidateArtifact']['bytes'], 512 << 20)
        self.assertLess(pin['measurementArtifact']['bytes'], 1 << 20)

    def test_create_writes_only_one_draft_post_and_never_uploads_or_claims_ui_or_payload_execution(self):
        api = self.api(); receipt = draft.create(api, self.pin, self.body, self.context)
        writes = [call for call in api.json.call_args_list if call.kwargs.get('method')]
        self.assertEqual(writes, [mock.call('/releases', method='POST', value=dict(tag_name=draft.TAG,
            target_commitish=self.pin['targetCommit'], name=draft.NAME, body=self.body,
            draft=True, prerelease=True, make_latest='false'))])
        api.upload.assert_not_called(); api.download.assert_not_called()
        self.assertEqual(receipt['releaseId'], 123)
        self.assertEqual(receipt['metadataCreatedBy'], 'github-actions-token')
        self.assertFalse(receipt['draftUiInspected'])
        self.assertFalse(receipt['candidateAssetBytesReverifiedHere'])
        self.assertTrue(all(receipt[name] is False for name in (*draft.FALSE_FLAGS, 'releaseUploaded', 'releasePublished')))

    def test_existing_tag_or_matching_release_is_refused_without_adoption_or_mutation(self):
        for responses, reason in (([dict(object=dict(type='commit', sha=self.pin['targetCommit']))], 'existing-tag-refused'),
                ([None, [self.release()]], 'existing-release-refused')):
            with self.subTest(reason=reason):
                api = mock.Mock(); api.json.side_effect = responses
                with self.assertRaisesRegex(ValueError, reason): draft.create(api, self.pin, self.body, self.context)
                self.assertTrue(all(not call.kwargs.get('method') for call in api.json.call_args_list))
                api.upload.assert_not_called()

    def test_wrong_body_branch_repository_or_event_fails_before_any_network(self):
        contexts = [dict(self.context, repository='unrelated/repository'), dict(self.context, ref='refs/heads/main'),
            dict(self.context, event='pull_request'), dict(self.context, run=0), dict(self.context, revision='main')]
        for context in contexts:
            with self.subTest(context=context):
                api = mock.Mock()
                with self.assertRaisesRegex(ValueError, 'authorized-workflow-context-required'):
                    draft.create(api, self.pin, self.body, context)
                api.json.assert_not_called()
        api = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'exact-measured-body-required'):
            draft.create(api, self.pin, self.body + 'changed', self.context)
        api.json.assert_not_called()

    def test_changed_created_metadata_is_refused_without_repair_or_second_mutation(self):
        cases = [dict(target_commitish='main'), dict(body='changed'), dict(draft=False), dict(prerelease=False),
            dict(tag_name='other'), dict(id=999), dict(name='other'), dict(author=dict(login='someone-else'))]
        for changes in cases:
            with self.subTest(changes=changes):
                api = mock.Mock(); api.json.side_effect = [None, [], self.release(), self.release(**changes)]
                with self.assertRaisesRegex(ValueError, 'stored-metadata-differs'):
                    draft.create(api, self.pin, self.body, self.context)
                self.assertEqual(len([call for call in api.json.call_args_list if call.kwargs.get('method')]), 1)
                api.upload.assert_not_called()

    def test_concurrent_wrong_tag_and_nonempty_draft_fail_without_deletion_or_replacement(self):
        for responses, reason in (([None, [], self.release(), self.release(),
                dict(object=dict(type='commit', sha='f' * 40))], 'existing-tag-refused'),
                ([None, [], self.release(), self.release(), None, [dict(name='foreign')]], 'must-have-no-assets')):
            with self.subTest(reason=reason):
                api = mock.Mock(); api.json.side_effect = responses
                with self.assertRaisesRegex(ValueError, reason): draft.create(api, self.pin, self.body, self.context)
                self.assertEqual(len([call for call in api.json.call_args_list if call.kwargs.get('method')]), 1)

    def test_prior_explicit_receipt_only_authorizes_read_only_numeric_id_verification(self):
        receipt = draft.create(self.api(), self.pin, self.body, self.context)
        api = mock.Mock(); api.json.side_effect = [dict(id=456, head_sha='b' * 40,
            path=draft.WORKFLOW, repository=dict(full_name=draft.REPOSITORY)), self.release(), None, []]
        result = draft.verify_created(api, self.pin, self.body, receipt)
        self.assertEqual(result['releaseId'], 123); self.assertFalse(result['mutationsPerformed'])
        self.assertTrue(all(not call.kwargs.get('method') for call in api.json.call_args_list))
        self.assertIn(mock.call('/releases/123'), api.json.call_args_list)
        changed = copy.deepcopy(receipt); changed['selection']['sha256'] = 'f' * 64
        api = mock.Mock()
        with self.assertRaisesRegex(ValueError, 'explicit-prior-receipt-required'):
            draft.verify_created(api, self.pin, self.body, changed)
        api.json.assert_not_called()

    def test_changed_prior_numeric_id_or_creator_run_is_refused_read_only(self):
        receipt = draft.create(self.api(), self.pin, self.body, self.context)
        for responses, reason in (([dict(id=456, head_sha='c' * 40, path=draft.WORKFLOW,
                repository=dict(full_name=draft.REPOSITORY))], 'prior-workflow-differs'),
                ([dict(id=456, head_sha='b' * 40, path=draft.WORKFLOW,
                repository=dict(full_name=draft.REPOSITORY)), self.release(id=999)], 'stored-metadata-differs')):
            api = mock.Mock(); api.json.side_effect = responses
            with self.assertRaisesRegex(ValueError, reason): draft.verify_created(api, self.pin, self.body, receipt)
            self.assertTrue(all(not call.kwargs.get('method') for call in api.json.call_args_list))

    def measurement_fixture(self):
        pin = copy.deepcopy(self.pin)
        names = set(pin['assets']) - {'release-manifest.json', 'SHA256SUMS'}
        files = {name: draft.digest(('TEST_ONLY ' + name).encode()) for name in names}
        lock = dict(formatVersion=1, scope='local-server-source-debug-provider-write-once-prerelease',
            repository=draft.REPOSITORY, tag=draft.TAG, targetCommit=pin['targetCommit'],
            state='measured-unbound', ownedDraftReleaseId=None, selectedInputs={}, recipeInputs={}, files=files)
        manifest = draft.engine.canonical(dict(formatVersion=1, scope=lock['scope'], targetCommit=lock['targetCommit'],
            tag=draft.TAG, selectedInputs=lock['selectedInputs'], assets=files))
        assets = dict(files, **{'release-manifest.json': draft.digest(manifest)})
        sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(assets.items())).encode()
        assets['SHA256SUMS'] = draft.digest(sums); pin['assets'] = assets
        lock_raw = draft.engine.canonical(lock)
        measurement = dict(formatVersion=1, scope='complete-local-server-publication-candidate-readback',
            targetCommit=pin['targetCommit'], assets=assets, measuredLock=draft.digest(lock_raw),
            allCandidateAssetBytesReadBack=True, allOriginalSourceAndPairedDebugVerified=True,
            originalNestedArchiveBytesPreserved=True, releaseUploaded=False, releasePublished=False,
            **{name: False for name in draft.FALSE_FLAGS})
        raw = {'measured-release.lock.json': lock_raw, 'measurement.json': draft.engine.canonical(measurement),
            'release-body.txt': self.body.encode(), 'failure-context.json': b'{}\n'}
        directory = self.root / 'measurement'; directory.mkdir()
        for name, value in raw.items(): (directory / name).write_bytes(value)
        pin['measurementFiles'] = {name: draft.digest(value) for name, value in raw.items()}
        selection = dict(lock=lock, body=self.body, assets=sorted(assets))
        return pin, directory, selection

    def test_measurement_binds_lock_body_all_twelve_assets_and_manifest_sums_without_large_payload_download(self):
        pin, directory, selection = self.measurement_fixture()
        with mock.patch.object(draft, 'frozen_selection', return_value=selection):
            self.assertEqual(draft.validate_measurement(self.root, directory, pin), self.body)
            pin['assets']['SHA256SUMS']['sha256'] = 'f' * 64
            with self.assertRaisesRegex(ValueError, 'candidate-or-body-differs'):
                draft.validate_measurement(self.root, directory, pin)

    def test_changed_measured_member_or_symlink_fails_before_executing_frozen_recipe(self):
        pin, directory, _ = self.measurement_fixture()
        (directory / 'release-body.txt').write_text('changed')
        with mock.patch.object(draft, 'frozen_selection') as frozen:
            with self.assertRaisesRegex(ValueError, 'measurement-file-differs'):
                draft.validate_measurement(self.root, directory, pin)
        frozen.assert_not_called()
        (directory / 'release-body.txt').unlink()
        (directory / 'release-body.txt').symlink_to(directory / 'measurement.json')
        with self.assertRaises((ValueError, OSError)): draft.validate_measurement(self.root, directory, pin)

    def test_remote_producer_and_both_artifacts_must_match_before_small_download(self):
        api = mock.Mock(); api.json.return_value = dict(id=self.pin['workflowRun'], head_sha=self.pin['targetCommit'],
            status='completed', conclusion='failure', repository=dict(full_name=draft.REPOSITORY),
            path='.github/workflows/preserve-local-server-components.yml')
        with self.assertRaisesRegex(ValueError, 'successful-exact-producer-required'):
            draft.acquire_measurement(api, self.root, self.pin)
        api.download.assert_not_called()

    def test_only_small_measurement_zip_is_downloaded_and_every_member_crc_and_identity_is_read(self):
        pin, directory, _ = self.measurement_fixture()
        archive = self.root / 'synthetic.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for source in directory.iterdir(): zipped.write(source, source.name)
        pin['measurementArtifact'].update(draft.digest(archive.read_bytes()))
        run = dict(id=pin['workflowRun'], head_sha=pin['targetCommit'], status='completed', conclusion='success',
            repository=dict(full_name=draft.REPOSITORY), path='.github/workflows/preserve-local-server-components.yml')
        artifacts = [dict(id=pin[key]['id'], name=pin[key]['name'], expired=False, size_in_bytes=pin[key]['bytes'],
            digest='sha256:' + pin[key]['sha256'], workflow_run=dict(id=pin['workflowRun'], head_sha=pin['targetCommit']))
            for key in ('measurementArtifact', 'candidateArtifact')]
        destination = self.root / 'remote'; destination.mkdir()
        api = mock.Mock(); api.json.side_effect = [run, *artifacts]
        api.download.side_effect = lambda _url, target, _expected: shutil.copyfile(archive, target)
        output = draft.acquire_measurement(api, destination, pin)
        self.assertEqual({p.name: draft.digest(p.read_bytes()) for p in output.iterdir()}, pin['measurementFiles'])
        api.download.assert_called_once_with(draft.transport.API + '/actions/artifacts/' +
            str(pin['measurementArtifact']['id']) + '/zip', destination / 'measurement.zip', pin['measurementArtifact'])
        run = dict(api.json.return_value, conclusion='success')
        expected = self.pin['measurementArtifact']
        artifact = dict(id=expected['id'], name=expected['name'], expired=False, size_in_bytes=expected['bytes'],
            digest='sha256:' + expected['sha256'], workflow_run=dict(id=self.pin['workflowRun'], head_sha=self.pin['targetCommit']))
        api = mock.Mock(); api.json.side_effect = [run, artifact, dict(artifact, id=self.pin['candidateArtifact']['id'])]
        with self.assertRaisesRegex(ValueError, 'exact-retained-artifacts-required'):
            draft.acquire_measurement(api, self.root, self.pin)
        api.download.assert_not_called()

    def test_workflow_write_scope_is_separate_and_push_only_explicit_request(self):
        raw = (draft.ROOT / draft.WORKFLOW).read_text()
        self.assertIn('contents: write', raw)
        self.assertIn('actions: read', raw)
        self.assertIn('runtime/server-components-publication/draft-creation.lock.json', raw)
        self.assertEqual(raw.count('persist-credentials: false'), 3)
        self.assertNotIn('pull_request_target', raw)
        self.assertNotIn('git push', raw)
        self.assertNotIn('gh release', raw)


if __name__ == '__main__': unittest.main()
