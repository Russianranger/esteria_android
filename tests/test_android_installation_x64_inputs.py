"""Read-only gate/schema fixtures only: no native SQL or Android qualification.

The future positive-shaped JSON below is synthetic metadata for mutation tests.
Underlying measured input admission is explicitly patched only in those tests;
the committed real selection remains disabled and makes no runtime claim.
"""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import android_installation_x64_inputs as inputs


def pin(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class AndroidInstallationX64Inputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lock = self.root / 'selection.json'
        self.pending = dict(formatVersion=1, scope=inputs.SCOPE, repository='Russianranger/esteria_android',
            enabled=False, state=inputs.PENDING, nativeSql=None, provider=None,
            **{name: False for name in inputs.FALSE_FLAGS})

    def load(self, value, *, required=False):
        self.lock.write_text(json.dumps(value))
        with patch.object(inputs, 'LOCK', self.lock): return inputs.load_pin(require_enabled=required)

    def test_real_pending_lock_refuses_required_mode_before_underlying_input_admission(self):
        self.assertEqual(inputs.load_pin(), self.pending)
        with patch.object(inputs.native, 'load_pin') as native, \
                self.assertRaisesRegex(ValueError, 'measured-native-sql-and-provider-required'):
            inputs.load_pin(require_enabled=True)
        native.assert_not_called()

    def test_pending_selection_cannot_smuggle_unmeasured_provider_or_runtime_claim(self):
        for change in (dict(enabled=1), dict(nativeSql={}), dict(provider=pin(b'unmeasured')),
                dict(state=inputs.MEASURED), dict(androidRuntimeQualified=True), dict(sqlExecuted=True),
                dict(extra='unrecognized'), dict(scope='android-server-programs-install-only')):
            with self.subTest(change=change), patch.object(inputs.native, 'load_pin') as native:
                with self.assertRaises(ValueError): self.load(dict(self.pending, **change))
                native.assert_not_called()

    def test_inspection_creates_no_output_and_duplicate_metadata_fields_refuse(self):
        self.assertEqual(self.load(self.pending), self.pending)
        self.assertEqual({path.name for path in self.root.iterdir()}, {'selection.json'})
        self.lock.write_text('{"formatVersion":1,"formatVersion":1}')
        with patch.object(inputs, 'LOCK', self.lock), self.assertRaisesRegex(ValueError, 'duplicate-field'):
            inputs.load_pin()

    def fixture(self):
        """Schema-only identities; never used as measured native artifacts."""
        native_selection = self.root / inputs.NATIVE_SELECTION
        native_selection.parent.mkdir(parents=True, exist_ok=True)
        native_selection.write_bytes(b'{"fixtureOnly":true}\n')
        identity = pin(native_selection.read_bytes()); same = pin(b'synthetic source-bound metadata')
        loader = pin(b'synthetic captured loader identity')
        executable = lambda name: dict(**pin(name.encode()), original=pin(('original-' + name).encode()),
            pairedDebug=pin(('debug-' + name).encode()), elf=dict(machine=62))
        build = dict(executables={name: executable(name) for name in ('dbimport', 'playerbots-schema')}, libraries={
            'lib64/ld-linux-x86-64.so.2': dict(**loader, elf=dict(machine=62)),
            'usr/lib/x86_64-linux-gnu/libc.so.6': dict(**pin(b'synthetic libc'), elf=dict(machine=62))})
        native = dict(enabled=True, build=dict(producer=dict(workflowRun=111, job=222, integrationRevision='a' * 40),
            buildReceipt=same, librarySourceReadback=pin(b'synthetic complete source receipt')))
        mysql = dict(files={'provider/assets/mysql-probe/mysql-x86-64.archive': pin(b'synthetic mysql archive')})
        mysql_proof = dict(expectedMysqlSqlVersion='8.0.46-0ubuntu0.24.04.4')
        content = dict(receipt=pin(b'synthetic original content receipt'), compiledModules=pin(b'synthetic original modules'),
            originalBuild=pin(b'synthetic original arm64 packaging build'), serverSource=dict(commit='f' * 40),
            serverBuildSourceLock=pin(b'synthetic archived server source lock'))
        uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        invocations = {name: dict(path='/sql-work/fixture/invocations/' + name,
            invocation=pin(('synthetic-native-script-' + name).encode()),
            actualExecutable={key: build['executables'][name][key] for key in ('bytes', 'sha256')}, loader=loader,
            invocationIsOriginalElf=False, originalElfBytesChanged=False) for name in build['executables']}
        report = dict(formatVersion=1, scope=inputs.sql.SCOPE, phase='complete',
            inputSelection=identity, buildProducer=native['build']['producer'],
            actualX64BuildReceipt=native['build']['buildReceipt'],
            actualX64LibrarySourceReadback=native['build']['librarySourceReadback'],
            originalMysqlArchive=mysql['files']['provider/assets/mysql-probe/mysql-x86-64.archive'],
            mysqlVersion=mysql_proof['expectedMysqlSqlVersion'], contentReceipt=content['receipt'],
            compiledModules=content['compiledModules'], contentOriginBuild=content['originalBuild'],
            source=content['serverSource'], sourceLockSha256=content['serverBuildSourceLock']['sha256'],
            contentOriginIsOriginalArm64Packaging=True, originalArm64ReceiptReusedForX64Qualification=False,
            selectedSourceBaseFiles=29, selectedSourceUpdates=31, preparedStatementCount=52, mysqlUuid=uuid,
            checkedInvocations=invocations, databaseSnapshot=dict(syntheticSchemaOnly=True),
            actualLoaderReentry=dict(exitCode=0, preparedStatementCount=52),
            **{name: True for name in inputs.POSITIVE_SQL_FLAGS}, **{name: False for name in inputs.sql.FALSE_FLAGS})
        report['playerbotsFirst'] = dict(scope=inputs.sql.playerbots.SCOPE, mysqlUuid=uuid, mysqlVersion=report['mysqlVersion'],
            helperBuildReceipt=native['build']['buildReceipt'], helperExecutable=invocations['playerbots-schema']['invocation'],
            originalBuild=content['originalBuild'], compiledModules=content['compiledModules'],
            sourceLockSha256=content['serverBuildSourceLock']['sha256'], contentReceipt=content['receipt'], preparedStatementCount=52,
            databaseSnapshot=report['databaseSnapshot'], compiledPlayerbotsLoaderExecuted=True,
            playerbotsSchemaInitialized=True, exactSourceLedgerVerified=True, coreSchemasLedgersCredentialsAccountPreserved=True)
        return native_selection, native, (build, mysql, mysql_proof, content), report

    def checked(self, report, native, context, path):
        with patch.object(inputs, '_context', return_value=context), patch.object(inputs.native, 'LOCK', path):
            return inputs.validate_native_sql(report, native)

    def test_native_positive_shape_binds_original_elf_and_distinct_native_invocation_metadata(self):
        path, native, context, report = self.fixture()
        self.assertEqual(self.checked(report, native, context, path), report)
        self.assertNotEqual(report['checkedInvocations']['playerbots-schema']['invocation'],
            report['checkedInvocations']['playerbots-schema']['actualExecutable'])

    def test_context_uses_original_frozen_mysql_metadata_without_current_owner_source_adoption(self):
        path, native, context, report = self.fixture()
        build, mysql, mysql_proof, content = context
        native['build']['actualEvidence'] = dict(path='runtime/evidence/fixture-build.json')
        native['mysql'] = dict(fullReadbackEvidence=dict(path='runtime/evidence/fixture-mysql.json'))
        native['serverContent'] = dict(releaseSelection=dict(path='runtime/evidence/fixture-release.json'))
        content_path = self.root / inputs.CONTENT_SELECTION; content_path.parent.mkdir(parents=True)
        raw = json.dumps(content).encode(); content_path.write_bytes(raw)
        records = {
            'runtime/evidence/fixture-build.json': dict(actualBuildReceipt=build, actualLibrarySourceReadback={}),
            'runtime/evidence/fixture-mysql.json': dict(actualCiEvidence=dict(providerVerification=mysql_proof)),
            'runtime/evidence/fixture-release.json': dict(selectedInputs={inputs.CONTENT_SELECTION: pin(raw)})}
        with patch.object(inputs, 'ROOT', self.root), \
                patch.object(inputs.native, 'record', side_effect=lambda row: records[row['path']]), \
                patch.object(inputs.native, 'validate_build', return_value=build) as build_guard, \
                patch.object(inputs.native, 'validate_source_readback') as source_guard, \
                patch.object(inputs.frozen_mysql, 'input_selection', return_value=mysql) as frozen, \
                patch.object(inputs.native.mysql, 'load_pin', side_effect=AssertionError('Current-source consumer must not admit historical inputs')):
            self.assertEqual(inputs._context(native), context)
            build_guard.assert_called_once_with(build, native)
            source_guard.assert_called_once_with({}, native)
            frozen.assert_called_once_with()

    def test_missing_sql_reentry_restart_or_stop_and_unexpected_runtime_claims_refuse(self):
        path, native, context, report = self.fixture()
        for name in inputs.POSITIVE_SQL_FLAGS:
            with self.subTest(missing=name), self.assertRaisesRegex(ValueError, 'positive-native-sql-required'):
                self.checked(dict(report, **{name: False}), native, context, path)
        for name in inputs.sql.FALSE_FLAGS:
            with self.subTest(claim=name), self.assertRaisesRegex(ValueError, 'positive-native-sql-required'):
                self.checked(dict(report, **{name: True}), native, context, path)
        for name in ('authserverExecuted', 'worldserverExecuted', 'botCharactersCreated', 'characterPersistenceQualified'):
            with self.subTest(claim=name), self.assertRaisesRegex(ValueError, 'unexpected-native-runtime-claim'):
                self.checked(dict(report, **{name: True}), native, context, path)

    def test_arm_receipt_or_foreign_native_selection_source_content_mysql_and_statement_count_refuse(self):
        path, native, context, report = self.fixture()
        for name, changed in (('scope', 'disposable-native-arm64-product-playerbots-schema'),
                ('inputSelection', pin(b'foreign native selection')), ('buildProducer', dict(workflowRun=1)),
                ('actualX64BuildReceipt', pin(b'foreign build')), ('actualX64LibrarySourceReadback', pin(b'foreign sources')),
                ('originalMysqlArchive', pin(b'foreign mysql')), ('mysqlVersion', '8.0.45'),
                ('contentReceipt', pin(b'foreign content')), ('compiledModules', pin(b'foreign modules')),
                ('sourceLockSha256', '0' * 64), ('originalArm64ReceiptReusedForX64Qualification', True),
                ('preparedStatementCount', 52.0), ('selectedSourceBaseFiles', 28), ('selectedSourceUpdates', 30)):
            with self.subTest(field=name), self.assertRaises(ValueError):
                self.checked(dict(report, **{name: changed}), native, context, path)

    def test_wrong_elf_machine_loader_debug_pair_or_script_relabel_refuse(self):
        path, native, context, report = self.fixture()
        for kind in ('elf', 'library', 'loader', 'debug', 'script-is-elf', 'exe-bytes', 'helper-is-elf'):
            changed = copy.deepcopy(report); selection = copy.deepcopy(context)
            if kind == 'elf': selection[0]['executables']['dbimport']['elf']['machine'] = 183
            elif kind == 'library': selection[0]['libraries']['usr/lib/x86_64-linux-gnu/libc.so.6']['elf']['machine'] = 183
            elif kind == 'loader': changed['checkedInvocations']['dbimport']['loader'] = pin(b'foreign loader')
            elif kind == 'debug': selection[0]['executables']['dbimport']['pairedDebug']['bytes'] = 0
            elif kind == 'script-is-elf': changed['checkedInvocations']['dbimport']['invocationIsOriginalElf'] = True
            elif kind == 'exe-bytes': changed['checkedInvocations']['dbimport']['actualExecutable'] = pin(b'foreign original ELF')
            else: changed['playerbotsFirst']['helperExecutable'] = changed['checkedInvocations']['playerbots-schema']['actualExecutable']
            with self.subTest(kind=kind), self.assertRaises(ValueError): self.checked(changed, native, selection, path)

    def test_bad_loader_reentry_or_different_live_snapshot_cannot_claim_native_sql(self):
        path, native, context, report = self.fixture()
        for changed in (dict(report, actualLoaderReentry=dict(exitCode=1, preparedStatementCount=52)),
                dict(report, actualLoaderReentry=dict(exitCode=0, preparedStatementCount=51)),
                dict(report, databaseSnapshot=dict(foreign=True)), dict(report, failureClass='RuntimeError')):
            with self.assertRaises(ValueError): self.checked(changed, native, context, path)

    def measured(self):
        path, native, context, report = self.fixture()
        def save(name, value):
            file = self.root / name; file.parent.mkdir(parents=True, exist_ok=True)
            raw = (json.dumps(value, sort_keys=True) + '\n').encode(); file.write_bytes(raw)
            return dict(path=name, **pin(raw))
        qualification = save('runtime/evidence/synthetic-native-sql.json', report)
        producer = dict(workflowRun=333, job=444, integrationRevision='b' * 40)
        artifact = dict(id=555, **pin(b'synthetic artifact metadata only'))
        native_row = dict(inputSelection=dict(path=inputs.NATIVE_SELECTION, **pin(path.read_bytes())),
            producer=producer, evidenceArtifact=artifact, qualification=qualification)
        observed = dict(formatVersion=1, scope='independent-native-x64-four-schema-sql-readback',
            workflow=dict(id=333, job=444, headSha='b' * 40, status='completed', conclusion='success'),
            artifactMetadataOnly=artifact, qualificationIdentity={key: qualification[key] for key in ('bytes', 'sha256')},
            inputSelection=pin(path.read_bytes()), actualQualification=report,
            allArtifactZipBytesReadBack=True, everyArtifactMemberCrcAndSha256Verified=True,
            qualificationSourceInputsMatchExactGitBlobs=True,
            androidRuntimeQualified=False, productionArm64ProviderQualified=False, worldserverQualified=False,
            playerbotsAiQualified=False, gameplayQualified=False)
        native_row['readback'] = save('runtime/evidence/synthetic-native-readback.json', observed)
        selected = dict(self.pending, enabled=True, state=inputs.MEASURED, nativeSql=native_row,
            provider=pin(b'independently measured synthetic descriptor metadata'))
        return path, native, context, report, observed, selected

    def test_future_measured_schema_requires_underlying_enabled_admission_and_exact_readback(self):
        path, native, context, report, observed, selected = self.measured()
        with patch.object(inputs, 'ROOT', self.root), patch.object(inputs.native, 'LOCK', path), \
                patch.object(inputs.native, 'load_pin', return_value=native) as admit, \
                patch.object(inputs, '_context', return_value=context):
            self.assertEqual(self.load(selected, required=True), selected)
            admit.assert_called_once_with(require_enabled=True)

    def test_foreign_pending_or_changed_readback_never_adopts_positive_shaped_receipt(self):
        path, native, context, report, observed, selected = self.measured()
        readback = self.root / selected['nativeSql']['readback']['path']
        for kind in ('failed-job', 'foreign-head', 'untyped-job', 'missing-member-readback', 'wrong-artifact', 'wrong-receipt'):
            changed = copy.deepcopy(observed)
            if kind == 'failed-job': changed['workflow']['conclusion'] = 'failure'
            elif kind == 'foreign-head': changed['workflow']['headSha'] = 'c' * 40
            elif kind == 'untyped-job': changed['workflow']['job'] = 444.0
            elif kind == 'missing-member-readback': changed['everyArtifactMemberCrcAndSha256Verified'] = False
            elif kind == 'wrong-artifact': changed['artifactMetadataOnly']['id'] += 1
            else: changed['actualQualification']['mysqlUuid'] = '11234567-89ab-4cde-8fab-0123456789ab'
            raw = json.dumps(changed).encode(); readback.write_bytes(raw)
            candidate = copy.deepcopy(selected); candidate['nativeSql']['readback'].update(pin(raw))
            with self.subTest(kind=kind), patch.object(inputs, 'ROOT', self.root), \
                    patch.object(inputs.native, 'LOCK', path), patch.object(inputs.native, 'load_pin', return_value=native), \
                    patch.object(inputs, '_context', return_value=context), \
                    self.assertRaisesRegex(ValueError, 'independent-native-readback-required'):
                self.load(candidate, required=True)

    def test_record_path_identity_and_provider_extra_authority_fields_refuse(self):
        path = self.root / 'runtime/evidence/record.json'; path.parent.mkdir(parents=True); path.write_bytes(b'{}')
        row = dict(path='runtime/evidence/record.json', **pin(b'{}'))
        with patch.object(inputs, 'ROOT', self.root):
            self.assertEqual(inputs.record(row), {})
            path.write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError, 'record-changed'): inputs.record(row)
            for name in ('../outside.json', 'runtime/../outside.json', 'runtime/evidence\\outside.json'):
                with self.assertRaisesRegex(ValueError, 'record-path'): inputs.record(dict(row, path=name))
        selected = dict(self.pending, enabled=True, state=inputs.MEASURED,
            provider=dict(pin(b'descriptor'), callerPath='/untrusted/provider'))
        with self.assertRaisesRegex(ValueError, 'exact-identity-required'): self.load(selected, required=True)


if __name__ == '__main__': unittest.main()
