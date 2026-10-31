"""Provenance, artifact and refusal guards; synthetic fixtures are not game proof."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import publish_detached_non_custom as publication


TEST_APP = 'a' * 40
TEST_RUN = 41211099991
TEST_JOB = 124566099991


class Api:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def json(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return copy.deepcopy(self.rows[path])


class PublicationGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, value):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def selected(self):
        for name in (publication.RECIPE, 'sources.lock.json'):
            self.write(name, {'synthetic': True})
        self.write(publication.RECEIPT, self.signing_receipt())
        self.write('app/stock-signing.lock.json', self.signing_lock())
        value = dict(formatVersion=1, scope=publication.SCOPE, repository=publication.REPOSITORY,
            branch='non-custom', appRevision=TEST_APP,
            packageRunId=TEST_RUN, packageJobId=TEST_JOB,
            packageWorkflow=publication.PACKAGE_WORKFLOW, packageArtifact=dict(id=111,
                name='unsigned-local-game-profile-release-arm64-' + TEST_APP,
                bytes=100, sha256='a' * 64), nativeSqlRunId=41211099999, nativeSqlJobId=124566099999,
            nativeSqlRevision='b' * 40, nativeSqlWorkflow=publication.SQL_WORKFLOW,
            nativeSqlArtifact=dict(id=222, name='server-installation-native-evidence-' + 'b' * 40,
                bytes=100, sha256='b' * 64), signatureRecipe=publication.identity(self.root / publication.RECIPE),
            signingReceipt=publication.identity(self.root / publication.RECEIPT),
            sourceLock=publication.identity(self.root / 'sources.lock.json'),
            stockSigningLock=publication.identity(self.root / 'app/stock-signing.lock.json'))
        return value

    def signing_lock(self):
        return dict(formatVersion=1, purpose='persistent-development',
            packageId=publication.signing.STOCK_PACKAGE, certificateSha256='1' * 64,
            lastPublished=dict(versionCode=1, apkSha256='f' * 64))

    def signing_receipt(self):
        return dict(formatVersion=1, scope='apk-signature-and-update-identity', qualificationOnly=False,
            persistentSigningIdentityVerified=True, inputApkSha256='b' * 64, publicSigningLockSha256='a' * 64,
            previousPublished=self.signing_lock()['lastPublished'],
            signedApk=dict(packageId=publication.signing.STOCK_PACKAGE, certificateSha256='1' * 64,
                versionCode=2, versionName='0.1.0-non-custom.2', debuggable=False),
            payloadPreserved=True, sdkBuildToolsVersion='35.0.0', actualInstallOverQualified=False,
            gameplayQualified=False, deviceCandidateQualified=False)

    def test_selection_cannot_choose_another_repository_workflow_app_or_failed_native_run(self):
        value = self.selected()
        path = self.write('selection.json', value)
        with patch.object(publication, 'ROOT', self.root):
            self.assertEqual(publication.selection(path), value)
            for key, changed in (('repository', 'other/repo'), ('appRevision', 'not-a-full-commit'),
                    ('packageWorkflow', '.github/workflows/mock.yml'), ('packageRunId', True),
                    ('nativeSqlWorkflow', '.github/workflows/mock.yml'),
                    ('nativeSqlRunId', publication.FAILED_SQL_RUN)):
                altered = dict(value, **{key: changed}); self.write('selection.json', altered)
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'fixed-producer-boundary'):
                    publication.selection(path)
            self.write('selection.json', value)
            (self.root / publication.RECIPE).write_text('changed public signature')
            with self.assertRaisesRegex(ValueError, 'local-file-identity'):
                publication.selection(path)

    def test_recorded_release_baseline_retires_old_publisher_and_preserves_frozen_metadata(self):
        value = self.selected()
        path = self.write('selection.json', value)
        recipe = (self.root / publication.RECIPE).read_bytes()
        receipt = (self.root / publication.RECEIPT).read_bytes()
        lock_path = self.root / 'app/stock-signing.lock.json'
        lock = json.loads(lock_path.read_text())
        lock['lastPublished'] = dict(versionCode=2, apkSha256='e' * 64)
        self.write('app/stock-signing.lock.json', lock)
        with patch.object(publication, 'ROOT', self.root):
            # The historical selection retains its original lock
            # hash. Updating the official ledger intentionally retires its replay.
            with self.assertRaisesRegex(ValueError, 'local-file-identity'):
                publication.selection(path)
            # Rebinding the ledger hash cannot replay the retired update.
            value['stockSigningLock'] = publication.identity(lock_path)
            self.write('selection.json', value)
            with self.assertRaisesRegex(ValueError, 'stock-update-baseline'):
                publication.selection(path)
        self.assertEqual((self.root / publication.RECIPE).read_bytes(), recipe)
        self.assertEqual((self.root / publication.RECEIPT).read_bytes(), receipt)

    def test_update_identity_requires_same_certificate_package_exact_prior_and_increasing_integer_version(self):
        lock = self.signing_lock()
        receipt = self.signing_receipt()
        application = publication.application_identity(receipt, lock)
        self.assertEqual(application, dict(packageId=publication.signing.STOCK_PACKAGE,
            versionCode=2, versionName='0.1.0-non-custom.2'))
        mutations = [
            lambda v: v['signedApk'].update(certificateSha256='2' * 64),
            lambda v: v['signedApk'].update(packageId='io.github.russianranger.esteria'),
            lambda v: v['signedApk'].update(versionCode=True),
            lambda v: v['signedApk'].update(versionCode=1, versionName='0.1.0-non-custom.1'),
            lambda v: v['signedApk'].update(versionCode=0, versionName='0.1.0-non-custom.0'),
            lambda v: v['signedApk'].update(versionName='other-version'),
            lambda v: v.update(previousPublished=None),
            lambda v: v['previousPublished'].update(apkSha256='e' * 64),
            lambda v: v['previousPublished'].update(versionCode=True),
        ]
        for index, mutate in enumerate(mutations):
            altered = copy.deepcopy(receipt); mutate(altered)
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'stock-update-'):
                publication.application_identity(altered, lock)
        first = copy.deepcopy(receipt)
        first['previousPublished'] = None
        first['signedApk'].update(versionCode=1, versionName='0.1.0-non-custom.1')
        self.assertEqual(publication.application_identity(first, dict(lock, lastPublished=None))['versionCode'], 1)
        with self.assertRaisesRegex(ValueError, 'stock-update-baseline'):
            publication.application_identity(first, lock)

    def test_version_three_update_remains_bound_to_exact_version_two_baseline(self):
        lock = self.signing_lock()
        lock['lastPublished'] = dict(versionCode=2, apkSha256='e' * 64)
        receipt = self.signing_receipt()
        receipt['previousPublished'] = copy.deepcopy(lock['lastPublished'])
        receipt['signedApk'].update(versionCode=3, versionName='0.1.0-non-custom.3')
        self.assertEqual(publication.application_identity(receipt, lock)['versionCode'], 3)
        # A matching certificate cannot reuse the prior update or substitute a
        # different previous APK. Each historical version retains its baseline.
        receipt['signedApk'].update(versionCode=2, versionName='0.1.0-non-custom.2')
        with self.assertRaisesRegex(ValueError, 'stock-update-baseline'):
            publication.application_identity(receipt, lock)
        receipt['signedApk'].update(versionCode=3, versionName='0.1.0-non-custom.3')
        receipt['previousPublished']['apkSha256'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'stock-update-baseline'):
            publication.application_identity(receipt, lock)

    def run_rows(self):
        run = dict(id=TEST_RUN, repository=dict(full_name=publication.REPOSITORY),
            head_repository=dict(full_name=publication.REPOSITORY), head_sha=TEST_APP,
            head_branch='non-custom', path=publication.PACKAGE_WORKFLOW, status='completed',
            conclusion='success', event='push', run_attempt=1)
        job = dict(id=TEST_JOB, run_id=TEST_RUN, name='package',
            head_sha=TEST_APP, status='completed', conclusion='success',
            steps=[dict(name='actual required build', status='completed', conclusion='success')])
        return run, job

    def test_successful_run_does_not_admit_skipped_job_step_wrong_sha_or_other_branch(self):
        run, job = self.run_rows()
        def check(run, job):
            api = Api({'/actions/runs/' + str(TEST_RUN): run,
                '/actions/runs/' + str(TEST_RUN) + '/jobs?per_page=100': dict(jobs=[job])})
            return publication.verify_run(api, TEST_RUN, TEST_JOB,
                publication.PACKAGE_WORKFLOW, 'package', ('actual required build',), TEST_APP)
        self.assertTrue(check(run, job)['requiredJobAndStepsSucceeded'])
        for changed in (dict(run, head_sha='f' * 40), dict(run, head_branch='main'), dict(run, conclusion='failure')):
            with self.assertRaisesRegex(ValueError, 'required-run-not-successful'): check(changed, job)
        skipped = copy.deepcopy(job); skipped['steps'][0]['conclusion'] = 'skipped'
        with self.assertRaisesRegex(ValueError, 'required-step-not-executed'): check(run, skipped)
        with self.assertRaisesRegex(ValueError, 'required-job-not-successful'): check(run, dict(job, conclusion='skipped'))

    def test_native_diagnostic_rerun_must_preserve_all_production_source_and_profile_bytes(self):
        revision = 'b' * 40
        rows = dict(status='ahead', merge_base_commit=dict(sha=TEST_APP), ahead_by=1,
            files=[dict(filename='tools/qualify_server_installation.py', status='modified')])
        path = '/compare/' + TEST_APP + '...' + revision
        self.assertTrue(publication.verify_sql_source_equivalence(Api({path: rows}), TEST_APP, revision)[
            'productionRuntimeProfileAndProviderInputsUnchanged'])
        for name in ('runtime/server_config.py', 'config/local-server.json', 'sources.lock.json',
                '.github/workflows/server-installation-native.yml', 'app/src/main/java/Changed.java'):
            changed = dict(rows, files=[dict(filename=name, status='modified')])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'production-source-changed'):
                publication.verify_sql_source_equivalence(Api({path: changed}), TEST_APP, revision)
        changed = dict(rows, merge_base_commit=dict(sha='f' * 40))
        with self.assertRaisesRegex(ValueError, 'source-ancestry'):
            publication.verify_sql_source_equivalence(Api({path: changed}), TEST_APP, revision)

    def test_artifact_requires_exact_run_digest_size_and_source(self):
        selected = dict(id=123, name='exact', bytes=10, sha256='1' * 64)
        row = dict(id=123, name='exact', size_in_bytes=10, digest='sha256:' + '1' * 64, expired=False,
            workflow_run=dict(id=TEST_RUN, head_sha=TEST_APP, head_branch='non-custom'))
        path = '/actions/artifacts/123'
        publication.verify_artifact(Api({path: row}), selected, TEST_RUN, TEST_APP)
        for key, changed in (('digest', 'sha256:' + '2' * 64), ('expired', True), ('size_in_bytes', 11)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'artifact-provenance'):
                publication.verify_artifact(Api({path: dict(row, **{key: changed})}), selected, TEST_RUN, TEST_APP)

    def test_inspect_derives_real_metadata_fields_and_reports_missing_local_inputs(self):
        def metadata(name, run_id, revision, artifact_id):
            return dict(id=artifact_id, name=name + revision, size_in_bytes=123, digest='sha256:' + 'e' * 64,
                expired=False, workflow_run=dict(id=run_id, head_sha=revision, head_branch='non-custom'))
        package = self.write('package.json', metadata('unsigned-local-game-profile-release-arm64-', TEST_RUN, TEST_APP, 123))
        native = self.write('native.json', metadata('server-installation-native-evidence-', TEST_RUN + 1, TEST_APP, 456))
        with patch.object(publication, 'ROOT', self.root):
            result = publication.inspect_metadata(package, native, TEST_JOB, TEST_JOB + 1)
            self.assertFalse(result['selectionComplete'])
            self.assertEqual(result['selection']['packageArtifact']['id'], 123)
            self.assertEqual(result['selection']['nativeSqlRunId'], TEST_RUN + 1)
            self.assertEqual(result['missingLocalInputs'], [publication.RECIPE, publication.RECEIPT,
                'sources.lock.json', 'app/stock-signing.lock.json'])
            self.assertFalse(result['liveWorkflowAndSdkQualificationPerformed'])
            self.selected()
            result = publication.inspect_metadata(package, native, TEST_JOB, TEST_JOB + 1)
            self.assertTrue(result['selectionComplete'])
            self.assertEqual(result['missingLocalInputs'], [])
            self.assertEqual(result['selection']['sourceLock'], publication.identity(self.root / 'sources.lock.json'))
        schema = publication.schema()
        self.assertEqual(schema['applicationPolicy']['packageId'], publication.signing.STOCK_PACKAGE)
        self.assertEqual(schema['properties']['packageRunId'], dict(type='integer', minimum=1))

    def test_artifact_traversal_extra_files_and_existing_outputs_are_preserved(self):
        names = ['app/app-release-unsigned.apk', 'proof/coherent-release-apk.json',
            'proof/release-manifest.json', 'proof/unsigned-release-package.json']
        for mutation in ('none', 'traversal', 'extra'):
            path = self.root / (mutation + '.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                for name in names: archive.writestr(name, b'fixture')
                if mutation == 'traversal': archive.writestr('../escape', b'fixture')
                if mutation == 'extra': archive.writestr('unapproved.py', b'fixture')
            output = self.root / ('out-' + mutation)
            if mutation == 'none':
                publication.extract_package(path, output)
                self.assertEqual({p.name for p in output.iterdir()}, {Path(n).name for n in names})
                with self.assertRaisesRegex(ValueError, 'extraction-output-exists'):
                    publication.extract_package(path, output)
                self.assertEqual((output / 'app-release-unsigned.apk').read_bytes(), b'fixture')
            else:
                with self.assertRaises(ValueError): publication.extract_package(path, output)
                self.assertFalse(output.exists())

    def sql_zip(self, mutate=None):
        value = dict(formatVersion=1, scope='disposable-native-arm64-owned-installation-finish-and-stop',
            phase='complete', contentProfile='stock-3.3.5a', sqlSelectionPolicy=publication.STOCK_SQL_POLICY)
        value.update({name: True for name in ('qualificationSucceeded', 'initializedNewInstance',
            'productionCoreCompositionCompleted', 'productionFinishPlayerbotsExecuted', 'nestedDataDirectoryConfigurationVerified',
            'completedFinishReentryWithoutExecution', 'restartPersistenceVerified', 'restartedFinishReentryWithoutExecution',
            'productionReadyAndStoppedAcknowledgmentsVerified', 'sourcePrivateJournalsAccountCredentialsPreserved',
            'nativeSqlSetupReceiptVerified', 'cleanShutdownVerified')})
        value.update({name: False for name in ('compilerExecuted', 'javaCoordinatorExecuted', 'authserverExecuted',
            'worldserverExecuted', 'serverDataQualified', 'playerbotsAiQualified', 'androidRuntimeQualified', 'gameplayQualified')})
        value['stockWorldSql'] = dict(contentProfile='stock-3.3.5a', stockRaceClassMapOutfitSqlOverlaysEmpty=True,
            humanWarriorNorthshireStartVerified=True, actualFileDbcRowsLoaded=False, worldStartupExecuted=False, gameplayQualified=False)
        if mutate: mutate(value)
        raw = json.dumps(value).encode()
        env = dict(formatVersion=1, scope='native-installation-finish-and-clean-stop-environment', integrationRevision=TEST_APP,
            privateSqlLogsExported=False, files={'native-installation-qualification.json': dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())})
        path = self.root / 'sql.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('native-installation-qualification.json', raw)
            archive.writestr('environment-receipt.json', json.dumps(env))
        return path

    def test_native_success_requires_actual_sql_policy_restart_and_same_environment_source(self):
        proof = publication.verify_native_sql(self.sql_zip(), TEST_APP)
        self.assertTrue(proof['actualNativeSqlSetupAndRestartVerified'])
        self.assertFalse(proof['worldserverExecuted'])
        for field in ('restartPersistenceVerified', 'nativeSqlSetupReceiptVerified', 'qualificationSucceeded'):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'native-sql-not-qualified'):
                publication.verify_native_sql(self.sql_zip(lambda v: v.update({field: False})), TEST_APP)
        with self.assertRaisesRegex(ValueError, 'native-sql-not-qualified'):
            publication.verify_native_sql(self.sql_zip(lambda v: v.update(sqlSelectionPolicy='stock-world-source-selection-v1')), TEST_APP)
        with self.assertRaisesRegex(ValueError, 'native-stock-sql-closure'):
            publication.verify_native_sql(self.sql_zip(lambda v: v['stockWorldSql'].update(humanWarriorNorthshireStartVerified=False)), TEST_APP)
        with self.assertRaisesRegex(ValueError, 'native-sql-source-binding'):
            publication.verify_native_sql(self.sql_zip(), 'c' * 40)

    def test_unsigned_proof_requires_full_provider_flags_exact_source_and_integer_version(self):
        source = self.write('sources.lock.json', dict(synthetic='engine-pins-not-runtime-evidence'))
        directory = self.root / 'unsigned'; directory.mkdir()
        apk = directory / 'app-release-unsigned.apk'
        with zipfile.ZipFile(apk, 'w') as archive:
            archive.writestr('assets/sources.lock.json', source.read_bytes())
            archive.writestr('classes.dex', b'synthetic-not-an-Android-client')
        observed = publication.identity(apk)
        manifest = dict(packageId=publication.signing.STOCK_PACKAGE, versionCode=2,
            versionName='0.1.0-non-custom.2', debuggable=False, minSdk=26, targetSdk=35)
        application = dict(packageId=manifest['packageId'], versionCode=2, versionName=manifest['versionName'])
        package = dict(formatVersion=1, scope='unsigned-nondebug-local-game-profile-release-packaging-only',
            integrationRevision=TEST_APP, apk=observed, manifest=manifest)
        package.update({name: True for name in ('completeProviderAndSourceBytesVerified', 'unsignedSignatureStructureVerified',
            'debugReferenceArtifactRetainedSeparately', 'sourceAndPairedDebugCompanionsRetainedSeparately')})
        package.update({name: False for name in ('privateSigningPerformed', 'persistentSigningQualified',
            'releaseInstallationQualified', 'androidExecutionQualified', 'hardwareQualified', 'commonMainQualified',
            'gameLoginQualified', 'localWorldReadinessQualified', 'playerbotsAiQualified', 'gameplayQualified', 'deviceTestCandidate')})
        selected = dict(appRevision=TEST_APP, sourceLock=publication.identity(source))
        cohort = dict(formatVersion=1, scope='source-and-paired-debug-verified-local-game-profile-apk-bytes',
            apk=observed, serverProfile='local-game', completeAssetInventoryVerified=True,
            exactCurrentHelperClosureVerified=True, deviceTestCandidate=False,
            selectedInputs={'sources.lock.json': selected['sourceLock']})
        def write():
            for name, value in (('unsigned-release-package.json', package), ('release-manifest.json', manifest),
                    ('coherent-release-apk.json', cohort)):
                (directory / name).write_text(json.dumps(value))
        write()
        with patch.object(publication, 'ROOT', self.root), patch.object(publication.signing, 'manifest', return_value=manifest):
            self.assertEqual(publication.verify_unsigned(directory, selected, {}, application), observed)
            package['formatVersion'] = True; write()
            with self.assertRaisesRegex(ValueError, 'unsigned-package-proof'):
                publication.verify_unsigned(directory, selected, {}, application)
            package['formatVersion'] = 1; cohort['exactCurrentHelperClosureVerified'] = False; write()
            with self.assertRaisesRegex(ValueError, 'complete-cohort-proof'):
                publication.verify_unsigned(directory, selected, {}, application)

    def test_original_signing_receipt_must_bind_exact_unsigned_and_pinned_public_lock(self):
        selected = dict(stockSigningLock=dict(bytes=1, sha256='a' * 64))
        unsigned = dict(bytes=1, sha256='b' * 64)
        receipt = self.signing_receipt()
        publication.verify_signing_receipt(receipt, selected, unsigned, self.signing_lock())
        for key, value in (('qualificationOnly', True), ('inputApkSha256', 'c' * 64), ('publicSigningLockSha256', 'd' * 64),
                ('persistentSigningIdentityVerified', False), ('formatVersion', True)):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'original-signing-receipt'):
                publication.verify_signing_receipt(dict(receipt, **{key: value}), selected, unsigned, self.signing_lock())

    def test_existing_tag_is_never_replaced_or_used_for_another_release(self):
        tag = 'non-custom-v0.1.0-non-custom.1'
        api = Api({'/git/ref/tags/' + tag: dict(object=dict(sha='a' * 40))})
        with self.assertRaisesRegex(ValueError, 'existing-tag-or-release-preserved'):
            publication.publish(api, self.root / 'absent', dict(tag=tag, appRevision=TEST_APP))
        self.assertEqual(len(api.calls), 1)
        self.assertFalse(self.root.joinpath('absent').exists())

    def test_failed_upload_leaves_only_new_draft_and_retains_its_identity(self):
        tag = 'non-custom-v0.1.0-non-custom.1'
        directory = self.root / 'publication'; (directory / 'release').mkdir(parents=True)
        (directory / 'release/RELEASE-NOTES.md').write_text('synthetic staging fixture')
        (directory / 'release/Esteria-Stock-3.3.5a-arm64.apk').write_bytes(b'synthetic staging fixture')
        class FailedUpload(Api):
            def upload(self, release_id, name, path, expected):
                self.calls.append(('upload', dict(releaseId=release_id, name=name)))
                raise ValueError('synthetic-upload-failure')
        api = FailedUpload({'/git/ref/tags/' + tag: None, '/releases/tags/' + tag: None,
            '/releases': dict(id=12345, draft=True, prerelease=True, tag_name=tag)})
        with self.assertRaisesRegex(ValueError, 'synthetic-upload-failure'):
            publication.publish(api, directory, dict(tag=tag, appRevision=TEST_APP))
        draft = json.loads((directory / 'publication-draft.json').read_text())
        self.assertEqual(draft['releaseId'], 12345)
        self.assertEqual(draft['appRevision'], TEST_APP)
        self.assertTrue(draft['draft']); self.assertFalse(draft['published'])
        self.assertFalse((directory / 'published-release.json').exists())
        self.assertFalse(any(arguments.get('method') in ('DELETE', 'PATCH') for _, arguments in api.calls))


if __name__ == '__main__':
    unittest.main()
