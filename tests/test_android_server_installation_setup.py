import copy
from dataclasses import replace
from functools import partial
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import android_server_installation_setup as setup, mysql_bootstrap as db
from runtime import server_content as content, server_schema_setup as schema, server_update_setup as updates
from runtime import server_playerbots_setup as playerbots, server_schema_baseline as baseline, server_updater as updater
from tests import test_runtime_playerbots_setup as pb_fixture


class InstallationComposition(unittest.TestCase):
    """Phase orchestration fixture only; source/SQL/native execution is not claimed."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.state = self.root / 'state'; self.state.mkdir(mode=0o700)
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        db.atomic_json(self.state / 'database-bootstrap.json', dict(format=1, engine='mysql', version='8.0.46', uuid=self.uuid,
            datadir=str(self.state / 'database'), databases=list(db.DATABASES), application_schemas_populated=False))
        self.pin = dict(bytes=11, sha256='a' * 64)
        self.verified = content.VerifiedContent(self.root / 'content', self.root / 'content/source', {}, {},
            dict(sourceLockSha256='b' * 64, compiledModules=self.pin), dict(receipt=self.pin, files={'fixture': self.pin}))
        self.connection = object(); self.calls = []; self.leases = []; self.cancelled = False; self.service_checks = 0
        for name in (schema.JOURNAL, updates.JOURNAL, 'realm-loopback.json', 'local-account.json'):
            db.atomic_json(self.state / name, dict(testFixture=True))
        self.profile = dict(setup.configurations._LOCAL_PORTS, playerbots=dict(setup.configurations._BOT_POLICY))
        self.patch(setup.schema, 'initialize', self.baseline)
        self.patch(setup.updates, 'prepare', self.prepare_update)
        self.patch(setup.updates, 'apply', self.apply_update)
        self.patch(setup.configurations, 'render_verified', self.render)
        self.patch(setup.realm, 'provision_verified', self.realm)
        self.patch(setup.account, 'provision_verified', self.account)

    def patch(self, target, name, replacement):
        active = patch.object(target, name, side_effect=replacement); active.start(); self.addCleanup(active.stop)

    def record(self, name, kwargs):
        self.calls.append(name)
        if 'state_lease' in kwargs:
            lease = kwargs['state_lease']; self.leases.append(lease)
            with db.state_scope(self.state, lease): pass
        with self.assertRaises(db.BootstrapError):
            with db.state_lock(self.state): pass

    def baseline(self, *args, **kwargs): self.record('baseline', kwargs); return dict(baselineImportCompleted=True)
    def prepare_update(self, *args, **kwargs): self.calls.append('prepare-updater'); return object()
    def apply_update(self, *args, **kwargs):
        name = 'updater-repeat' if 'updater-first' in self.calls else 'updater-first'
        self.record(name, kwargs)
        return dict(operation='verified-completed-updater' if name.endswith('repeat') else 'applied',
            compiledUpdaterExecuted=name.endswith('first'), compiledUpdaterCompleted=True,
            sourceLedgersVerified=True, databaseSnapshots={'fixture': 'unchanged'})
    def render(self, *args, **kwargs): self.calls.append('config'); return dict(module_configurations_complete=True, lua_scripts_enabled=False,generation='c'*64)
    def realm(self, *args, **kwargs):
        verify = kwargs.get('verify_only', False); self.record('verify-realm' if verify else 'realm', kwargs)
        return dict(operation='verified' if verify else 'already-local', mysqlUuid=self.uuid, completedUpdaterVerified=True)
    def account(self, *args, **kwargs):
        verify = kwargs.get('verify_only', False); self.record('verify-account' if verify else 'account', kwargs)
        return dict(operation='verified-owned-account' if verify else 'created-owned-account', mysqlUuid=self.uuid, completedUpdaterVerified=True)
    def service(self): self.service_checks += 1; return True

    def run_compose(self, **extra):
        arguments = dict(program=self.root/'program',program_identity=self.pin,template=self.root/'template',template_identity=self.pin,
            original_build_identity=self.pin,mysql=Path('/usr/bin/mysql'),data=Path('/data'),profile=self.profile,
            apply_sql=lambda *_: self.fail('Phase mock must never execute real source SQL'), verify_service=self.service,
            expected_uuid=self.uuid,cancelled=lambda: self.cancelled)
        arguments.update(extra)
        return setup.compose(self.verified,self.connection,self.state,'8.0.46',**arguments)

    def test_available_phases_share_real_state_lease_and_never_make_complete_proof(self):
        with db.state_lock(self.state) as caller:
            result = self.run_compose(state_lease=caller)
            self.assertTrue(all(lease is caller for lease in self.leases))
            with self.assertRaises(db.BootstrapError):
                with db.state_lock(self.state): pass
        self.assertEqual(self.calls,['baseline','prepare-updater','updater-first','updater-repeat','config','realm','account','verify-realm','verify-account'])
        self.assertEqual(result['scope'],setup.SCOPE);self.assertTrue(result['sameRevisionReentryVerified'])
        for field in ('playerbotsSchemaVerified','completeSetupQualified','slotPromoted','gameplayQualified','worldserverExecuted'):
            self.assertFalse(result[field])
        self.assertEqual(result['pendingComponents'],['playerbots-schema'])
        self.assertFalse((self.state/'server-setup-complete.json').exists())
        self.assertEqual(json.loads((self.state/'server-installation-staged.json').read_bytes()),result)
        self.assertNotIn('password',json.dumps(result));self.assertNotIn('username',json.dumps(result))

    def test_cancel_after_updater_finishes_never_enters_config_or_account(self):
        original = self.apply_update
        def finished(*args,**kwargs):
            result = original(*args,**kwargs)
            self.cancelled = True
            return result
        with patch.object(setup.updates,'apply',side_effect=finished):
            with self.assertRaises(schema.SchemaCancelled): self.run_compose()
        self.assertEqual(self.calls,['baseline','prepare-updater','updater-first'])
        self.assertFalse((self.state/'server-installation-staged.json').exists())

    def test_before_work_cancel_does_not_take_lock_or_mutate_phase_journals(self):
        before = {path.name:path.read_bytes() for path in self.state.iterdir()}
        self.cancelled=True
        with self.assertRaises(schema.SchemaCancelled):self.run_compose()
        self.assertEqual(self.calls,[])
        self.assertEqual({path.name:path.read_bytes() for path in self.state.iterdir()},before)

    def test_failed_updater_or_reentry_prevents_account_mutation(self):
        for failure in ('updater-first','updater-repeat'):
            self.calls.clear()
            original = self.apply_update
            def apply(*args,**kwargs):
                result=original(*args,**kwargs)
                if self.calls[-1]==failure:result['sourceLedgersVerified']=False
                return result
            with self.subTest(phase=failure),patch.object(setup.updates,'apply',side_effect=apply):
                with self.assertRaises(db.BootstrapError):self.run_compose()
            self.assertNotIn('realm',self.calls);self.assertNotIn('account',self.calls)
            self.assertFalse((self.state/'server-installation-staged.json').exists())

    def test_wrong_instance_missing_service_and_unsealed_profile_fail_before_phase_work(self):
        for extra in (dict(expected_uuid='11234567-89ab-4cde-8fab-0123456789ab'),dict(verify_service=None),
                      dict(profile=dict(self.profile,auth_port=9000))):
            with self.subTest(extra=extra),self.assertRaises((db.BootstrapError,ValueError)):self.run_compose(**extra)
        self.assertEqual(self.calls,[])

    def test_changed_final_account_uuid_never_records_staged_success(self):
        original=self.account
        def account(*args,**kwargs):
            result=original(*args,**kwargs)
            if kwargs.get('verify_only'):result['mysqlUuid']='11234567-89ab-4cde-8fab-0123456789ab'
            return result
        with patch.object(setup.account,'provision_verified',side_effect=account):
            with self.assertRaises(db.BootstrapError):self.run_compose()
        self.assertFalse((self.state/'server-installation-staged.json').exists())


class InstallationSelection(unittest.TestCase):
    def test_selection_accepts_only_exact_public_pin_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'selection.json';pin=dict(bytes=1,sha256='a'*64)
            selected=dict(formatVersion=1,scope=setup.SELECTION_SCOPE,source={'commit':'b'*40},sourceLockSha256='c'*64,
                contentReceipt=pin,compiledModules=pin,program=pin,template=pin,originalBuild=pin,profile=pin)
            path.write_text(json.dumps(selected));self.assertEqual(setup.selection(path),selected)
            for changed in (dict(selected,programPath='/untrusted/executable'),dict(selected,formatVersion=True),
                            dict(selected,program=dict(bytes=65*1024**2,sha256='a'*64))):
                path.write_text(json.dumps(changed))
                with self.assertRaises(db.BootstrapError):setup.selection(path)
            path.write_text('{"formatVersion":1,"formatVersion":1}')
            with self.assertRaises(Exception):setup.selection(path)

    def test_playerbots_phase_requires_only_three_exact_helper_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'selection.json'; pin = dict(bytes=1, sha256='a' * 64)
            selected = dict(formatVersion=1, scope=setup.SELECTION_SCOPE, source={'commit':'b'*40}, sourceLockSha256='c'*64,
                contentReceipt=pin, compiledModules=pin, program=pin, template=pin, originalBuild=pin, profile=pin)
            path.write_text(json.dumps(selected))
            with self.assertRaises(db.BootstrapError): setup.selection(path, 'playerbots')
            helper = dict(executable=pin, buildReceipt=pin, nativeReceipt=pin)
            selected['playerbotsHelper'] = helper; path.write_text(json.dumps(selected))
            self.assertEqual(setup.selection(path, 'playerbots'), selected)
            with self.assertRaises(db.BootstrapError): setup.selection(path)
            for changed in (dict(helper, path='/untrusted'), dict(helper, nativeReceipt=dict(bytes=True,sha256='a'*64)),
                            dict(helper, executable=dict(bytes=65 << 20,sha256='a'*64)), {'executable':pin,'buildReceipt':pin}):
                path.write_text(json.dumps(dict(selected, playerbotsHelper=changed)))
                with self.assertRaises(db.BootstrapError): setup.selection(path, 'playerbots')
            with self.assertRaises(db.BootstrapError): setup.selection(path, 'unknown')


class InstallationPlayerbotsFinish(unittest.TestCase):
    """Real host child/private journals with SQL rows emulated; no native/phone claim."""
    def setUp(self):
        fixture = pb_fixture.RuntimePlayerbotsSetup(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        for name in ('root', 'state', 'connection', 'content', 'profile', 'data', 'mysql', 'uuid', 'helper', 'helper_receipt'):
            setattr(self, name, getattr(fixture, name))
        self.final_data = self.data / 'data'; self.calls = []; self.cancelled = False
        for name, method in (('provision_verified', self.realm),):
            active = patch.object(setup.realm, name, side_effect=method); active.start(); self.addCleanup(active.stop)
        active = patch.object(setup.account, 'provision_verified', side_effect=self.account)
        active.start(); self.addCleanup(active.stop)
        # Produce the authentic staged marker through the original coordinator.
        # Existing real baseline/core journals are verified, never rebuilt here.
        owner = fixture.owner
        setup.compose(self.content, self.connection, self.state, '8.0.46', program=owner.executable,
            program_identity=owner.program_pin, template=owner.template, template_identity=owner.template_pin,
            original_build_identity=self.content.compiled['serverBuild'], mysql=self.mysql, data=self.data,
            profile=self.profile, apply_sql=lambda *_: self.fail('Historical baseline must not apply SQL'),
            verify_service=lambda: True, expected_uuid=self.uuid)
        self.calls.clear(); self.staged = (self.state / setup.STAGED_REPORT).read_bytes()
        fixture.helper_document.update(phase='built-component', buildTarget='esteria_playerbots_database_reference',
            sqlExecuted=False, originalServerProgramsReplaced=False)
        fixture.write_helper_receipt()
        self.build_pin = baseline.file_identity(self.helper_receipt)
        self.helper_pin = baseline.file_identity(self.helper)
        self.native_path = self.root / 'host-fixture-native-proof.json'
        row = dict(scope=playerbots.SCOPE, mysqlUuid=self.uuid, mysqlVersion='8.0.46',
            originalBuild=self.content.compiled['serverBuild'], compiledModules=self.content.receipt['compiledModules'],
            contentReceipt=self.content.identities['receipt'], sourceLockSha256=self.content.receipt['sourceLockSha256'],
            helperBuildReceipt=self.build_pin, helperExecutable=self.helper_pin, preparedStatementCount=52,
            playerbotsSchemaInitialized=True, exactSourceLedgerVerified=True,
            coreSchemasLedgersCredentialsAccountPreserved=True, databaseSnapshot={'fixture': True})
        self.native = dict(formatVersion=1, scope='disposable-native-arm64-product-playerbots-schema', phase='complete',
            qualificationSucceeded=True, source=self.content.manifest['source'], mysqlUuid=self.uuid, mysqlVersion='8.0.46',
            originalBuild=row['originalBuild'], compiledModules=row['compiledModules'], contentReceipt=row['contentReceipt'],
            sourceLockSha256=row['sourceLockSha256'], helperBuildReceipt=self.build_pin, helperExecutable=self.helper_pin,
            preparedStatementCount=52, selectedSourceBaseFiles=29, selectedSourceUpdates=31,
            databaseSnapshot=row['databaseSnapshot'],
            playerbotsFirst=dict(row,compiledPlayerbotsLoaderExecuted=True),
            playerbotsCompletedReentry=dict(row,compiledPlayerbotsLoaderExecuted=False))
        for name in ('initializedNewInstance', 'productionCoreCompositionCompleted',
                'playerbotsDatabaseAndStatementsQualified', 'exactSourceUpdateLedgerVerified',
                'completedJournalReentryWithoutExecution', 'actualLoaderReentryVerified', 'restartPersistenceVerified',
                'fixtureProbeRemoved', 'finalFourSchemaProductVerification',
                'coreSchemasLedgersCredentialsAccountPreserved', 'cleanShutdownVerified'):
            self.native[name] = True
        for name in ('playerbotsAiQualified', 'botCharactersCreated', 'authserverExecuted', 'worldserverExecuted',
                'completeSetupQualified', 'slotPromoted', 'existingStateModified', 'schemaUpgradeQualified',
                'androidRuntimeQualified', 'gameplayQualified'):
            self.native[name] = False
        self.write_native()

    def write_native(self):
        self.native_path.write_text(json.dumps(self.native, sort_keys=True)); self.native_pin = baseline.file_identity(self.native_path)

    def local(self, kind, content, connection, state, version, **kwargs):
        with db.state_scope(state, kwargs['state_lease']), setup.realm.config_lock(state), setup.realm.named_locks(connection,
                ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            self.assertIs(content, self.content)
            self.assertTrue(kwargs['verify_service']())
            generation = setup.realm.active_config_verified(content, state, db.read_secret(state / 'accounts/database-secret'),
                profile=kwargs['profile'], data=kwargs['data'], mysql=kwargs['mysql'])
            completed = updates.verify_completed_update(content, connection, state, version,
                expected_uuid=self.uuid, verify_service=lambda: True)
            playerbots._owned_account(connection, state, db.read_receipt(state / 'database-bootstrap.json', version))
            self.assertTrue(completed['compiledUpdaterCompleted'])
        verifying = kwargs.get('verify_only', False)
        self.calls.append((kind, verifying))
        row = dict(formatVersion=1,
            scope=('owned-verified-content-local-realm-after-compiled-updater' if kind == 'realm' else
                   'owned-verified-content-local-account-after-compiled-updater-and-realm'),
            operation=('verified' if kind == 'realm' else 'verified-owned-account') if verifying else 'fixture-existing',
            mysqlUuid=self.uuid, mysqlVersion=version, sourceLockSha256=content.receipt['sourceLockSha256'],
            contentReceipt=content.identities['receipt'], compiledModules=content.receipt['compiledModules'],
            configGeneration=generation, completedUpdaterVerified=True, serverStarted=False,
            existingCredentialsReset=False, charactersCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
        db.atomic_json(state / ('realm-loopback.json' if kind == 'realm' else 'local-account.json'), row)
        return row

    def realm(self, *args, **kwargs): return self.local('realm', *args, **kwargs)
    def account(self, *args, **kwargs): return self.local('account', *args, **kwargs)

    def finish(self, **kwargs):
        entry = kwargs.pop('_entry', setup.finish_playerbots)
        arguments = dict(helper=self.helper, helper_identity=self.helper_pin, helper_receipt=self.helper_receipt,
            helper_receipt_identity=self.build_pin, native_receipt=self.native_path, native_receipt_identity=self.native_pin,
            mysql=self.mysql, data=self.final_data, staged_data=self.data, profile=self.profile, expected_uuid=self.uuid,
            verify_service=lambda: True, cancelled=lambda: self.cancelled)
        arguments.update(kwargs)
        self.fixture.real_runner = updater.run_importer
        with patch.object(updater, 'run_importer', side_effect=self.fixture.runner), \
                patch.object(schema, 'initialize', side_effect=AssertionError('Finish replayed source baseline')), \
                patch.object(updates, 'apply', side_effect=AssertionError('Finish replayed compiled updater')):
            return entry(self.content, self.connection, self.state, '8.0.46', **arguments)

    def test_public_finish_keeps_fixed_arm64_admission_before_prepare_and_after_real_host_child(self):
        calls = []; verify = setup._helper_inputs; prepare = playerbots.prepare
        def checked(*args, **kwargs):
            calls.append('arm64-proof'); return verify(*args, **kwargs)
        def prepared(*args, **kwargs):
            calls.append('real-preparation'); return prepare(*args, **kwargs)
        with patch.object(setup, '_helper_inputs', side_effect=checked), \
                patch.object(playerbots, 'prepare', side_effect=prepared):
            result = self.finish()
        self.assertEqual(calls, ['arm64-proof', 'real-preparation', 'arm64-proof'])
        self.assertEqual(len(self.fixture.runs), 1)
        self.assertTrue(result['fourSchemasVerified'])
        self.assertFalse(result['androidRuntimeQualified'])

    def test_private_kernel_rejects_foreign_preparation_before_config_transition_or_sql(self):
        plan = playerbots.prepare(self.content, self.helper, self.helper_receipt, self.build_pin['sha256'], self.mysql)
        foreign = dict(bytes=1, sha256='0' * 64)
        for changed in (object(), replace(plan, content=copy.copy(self.content)),
                replace(plan, executable=self.helper.with_name('foreign-helper')),
                replace(plan, executable_identity=foreign), replace(plan, helper_receipt_identity=foreign),
                replace(plan, mysql=self.mysql.with_name('foreign-mysql'))):
            with self.subTest(plan=type(changed).__name__), \
                    patch.object(playerbots, 'apply', side_effect=AssertionError('Foreign preparation reached SQL')) as apply:
                entry = partial(setup._finish_playerbots, prepare_helper=lambda: changed, verify_helper=lambda: None)
                with self.assertRaisesRegex(db.BootstrapError, 'Sealed playerbots helper selection differs'):
                    self.finish(_entry=entry)
                apply.assert_not_called()
            self.assertFalse((self.state / setup.FINISH_JOURNAL).exists())
            self.assertFalse((self.state / setup.VERIFIED_REPORT).exists())
            self.assertEqual((self.state / setup.STAGED_REPORT).read_bytes(), self.staged)
        self.assertFalse(self.fixture.runs)

    def test_private_kernel_rechecks_admitted_proofs_before_publishing_final_report(self):
        calls = []
        def checked():
            calls.append('proof')
            if len(calls) == 2: raise db.BootstrapError('fixture proof changed after helper')
            return setup._helper_inputs(self.content, self.helper, self.helper_pin, self.helper_receipt, self.build_pin,
                self.native_path, self.native_pin)
        entry = partial(setup._finish_playerbots, verify_helper=checked,
            prepare_helper=lambda: playerbots.prepare(self.content, self.helper, self.helper_receipt,
                self.build_pin['sha256'], self.mysql))
        with self.assertRaisesRegex(db.BootstrapError, 'proof changed after helper'):
            self.finish(_entry=entry)
        self.assertEqual(calls, ['proof', 'proof'])
        self.assertEqual(len(self.fixture.runs), 1)
        self.assertEqual(schema.private_journal(self.state / playerbots.JOURNAL)['phase'], 'complete')
        self.assertFalse((self.state / setup.VERIFIED_REPORT).exists())
        self.assertEqual((self.state / setup.STAGED_REPORT).read_bytes(), self.staged)
        resumed = self.finish()
        self.assertFalse(resumed['compiledPlayerbotsLoaderExecuted'])
        self.assertEqual(len(self.fixture.runs), 1)

    def test_real_host_child_and_reentry_keep_outer_lease_and_original_stage(self):
        private = {name:(self.state / name).read_bytes() for name in
                   (schema.JOURNAL, updates.JOURNAL, setup.account.JOURNAL, 'accounts/database-secret', 'accounts/database-root-secret')}
        with db.state_lock(self.state) as lease:
            first = self.finish(state_lease=lease)
            with self.assertRaises(db.BootstrapError):
                with db.state_lock(self.state): self.fail('Finish released caller lease')
            second = self.finish(state_lease=lease)
        self.assertTrue(first['compiledPlayerbotsLoaderExecuted']); self.assertFalse(second['compiledPlayerbotsLoaderExecuted'])
        self.assertEqual(len(self.fixture.runs), 1)
        self.assertEqual(self.calls, [('realm', True), ('account', True)] * 2)
        self.assertEqual((self.state / setup.STAGED_REPORT).read_bytes(), self.staged)
        self.assertEqual({name:(self.state/name).read_bytes() for name in private}, private)
        self.assertEqual(second['scope'], setup.VERIFIED_SCOPE)
        self.assertEqual(second['pendingComponents'], ['owned-clean-engine-stop'])
        for name in ('fourSchemasVerified', 'playerbotsSchemaVerified', 'localRealmVerified', 'localAccountVerified'):
            self.assertIs(second[name], True)
        for name in ('engineStopped', 'completeSetupQualified', 'slotPromoted', 'worldserverExecuted',
                     'serverDataQualified', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(second[name], False)
        self.assertEqual(json.loads((self.state/setup.VERIFIED_REPORT).read_bytes()), second)
        generation = setup.realm.active_config_verified(self.content, self.state, db.read_secret(self.state/'accounts/database-secret'),
            profile=self.profile, data=self.final_data, mysql=self.mysql)
        self.assertEqual(second['configGeneration'], generation)
        for secret in (self.fixture.intent['password'], self.fixture.intent['username'], self.fixture.intent['saltHex'], self.fixture.intent['verifierHex']):
            self.assertNotIn(secret, json.dumps(second))
        self.assertFalse(self.connection.locks)

    def test_cancel_before_work_or_after_config_transition_preserves_resumable_boundaries(self):
        self.cancelled = True
        with self.assertRaises(schema.SchemaCancelled): self.finish()
        self.assertFalse((self.state/setup.FINISH_JOURNAL).exists())
        self.cancelled = False
        def progress(event):
            if event['phase'] == 'installation-playerbots-configurations': self.cancelled = True
        with self.assertRaises(schema.SchemaCancelled): self.finish(progress=progress)
        self.assertTrue((self.state/setup.FINISH_JOURNAL).exists())
        self.assertFalse((self.state/playerbots.JOURNAL).exists()); self.assertFalse(self.fixture.runs)
        self.assertFalse((self.state/setup.VERIFIED_REPORT).exists())
        self.assertEqual((self.state/setup.STAGED_REPORT).read_bytes(), self.staged)
        self.cancelled = False; self.finish(); self.assertEqual(len(self.fixture.runs), 1)

    def test_cancel_after_pb_intent_finishes_unit_then_reentry_only_verifies(self):
        def progress(event):
            if event['phase'] == 'playerbots-schema-intent-committed': self.cancelled = True
        with self.assertRaises(schema.SchemaCancelled): self.finish(progress=progress)
        self.assertEqual(schema.private_journal(self.state/playerbots.JOURNAL)['phase'], 'complete')
        self.assertFalse((self.state/setup.VERIFIED_REPORT).exists()); self.assertEqual(len(self.fixture.runs), 1)
        self.cancelled = False; result = self.finish()
        self.assertFalse(result['compiledPlayerbotsLoaderExecuted']); self.assertEqual(len(self.fixture.runs), 1)

    def test_failed_pb_is_preserved_and_never_replayed_or_reported_verified(self):
        with patch.object(playerbots, 'run_loader', side_effect=RuntimeError('fixture private SQL failure')):
            with self.assertRaises(RuntimeError): self.finish()
        path = self.state/playerbots.JOURNAL; failed = path.read_bytes()
        self.assertEqual(json.loads(failed)['phase'], 'failed')
        with self.assertRaises(db.BootstrapError): self.finish()
        self.assertEqual(path.read_bytes(), failed); self.assertFalse((self.state/setup.VERIFIED_REPORT).exists())
        self.assertFalse(self.fixture.runs)

    def test_staged_pin_private_mode_core_account_and_config_drift_refuse_before_intent(self):
        stage = self.state/setup.STAGED_REPORT; original = stage.read_bytes()
        mutations = ('stage-source', 'stage-program', 'stage-mode', 'core-bytes', 'account-not-ready', 'config-bytes', 'public-receipt')
        for kind in mutations:
            core_path = self.state/updates.JOURNAL; core_raw = core_path.read_bytes()
            account_path = self.state/setup.account.JOURNAL; account_raw = account_path.read_bytes()
            generation = json.loads(original)['configGeneration']; config_path = self.state/'config/generations'/generation/'worldserver.conf'
            config_raw = config_path.read_bytes(); public_path = self.state/'local-account.json'; public_raw = public_path.read_bytes()
            value = json.loads(original)
            if kind == 'stage-source': value['sourceLockSha256'] = '0'*64; db.atomic_json(stage, value)
            elif kind == 'stage-program': value['selectedProgram'] = dict(bytes=1,sha256='0'*64); db.atomic_json(stage, value)
            elif kind == 'stage-mode': stage.chmod(0o644)
            elif kind == 'core-bytes': core_path.write_bytes(core_raw+b' ')
            elif kind == 'account-not-ready': db.atomic_json(account_path, dict(self.fixture.intent,phase='pending'))
            elif kind == 'config-bytes': config_path.write_bytes(config_raw+b' ')
            else: public_path.write_bytes(public_raw+b' ')
            with self.subTest(kind=kind), self.assertRaises((db.BootstrapError, ValueError)): self.finish()
            self.assertFalse((self.state/setup.VERIFIED_REPORT).exists()); self.assertFalse(self.fixture.runs)
            self.assertFalse((self.state/setup.FINISH_JOURNAL).exists())
            stage.write_bytes(original); stage.chmod(0o600); core_path.write_bytes(core_raw)
            account_path.write_bytes(account_raw); config_path.write_bytes(config_raw); public_path.write_bytes(public_raw)
            setup.configurations.render_verified(self.content,self.state,self.data,self.mysql,profile=self.profile)

    def test_three_outer_pins_and_native_source_or_statement_drift_fail_before_transition(self):
        for name in ('helper_identity', 'helper_receipt_identity', 'native_receipt_identity'):
            with self.subTest(pin=name), self.assertRaises(db.BootstrapError):
                self.finish(**{name:dict(bytes=1,sha256='0'*64)})
        for name, value in (('qualificationSucceeded', False), ('sourceLockSha256', '0'*64),
                            ('preparedStatementCount', True), ('helperBuildReceipt', dict(bytes=1,sha256='0'*64)),
                            ('worldserverExecuted', True), ('scope', 'disposable-native-x64-measured-setup-four-schema-sql')):
            original = copy.deepcopy(self.native); self.native[name] = value; self.write_native()
            with self.subTest(field=name), self.assertRaises(db.BootstrapError): self.finish()
            self.native = original; self.write_native()
        self.assertFalse((self.state/setup.FINISH_JOURNAL).exists()); self.assertFalse(self.fixture.runs)

    def test_run_routes_only_fixed_helper_files_and_keeps_default_core_phase(self):
        programs = self.root / 'programs'; service_session = self.root / 'service-session'; service_session.mkdir(mode=0o700)
        pin = dict(bytes=1, sha256='d' * 64)
        base_selection = dict(formatVersion=1, scope=setup.SELECTION_SCOPE, source=self.content.manifest['source'],
            sourceLockSha256=self.content.receipt['sourceLockSha256'], contentReceipt=self.content.identities['receipt'],
            compiledModules=self.content.receipt['compiledModules'], program=self.fixture.owner.program_pin,
            template=self.fixture.owner.template_pin, originalBuild=self.content.compiled['serverBuild'], profile=pin)
        build = dict(serverSource=self.content.manifest['source'], sourcesLock=dict(sha256=self.content.receipt['sourceLockSha256']))
        for phase in ('core', 'playerbots'):
            session = self.root / ('session-' + phase); session.mkdir(mode=0o700)
            selected = copy.deepcopy(base_selection)
            if phase == 'playerbots': selected['playerbotsHelper'] = dict(executable=self.helper_pin,
                buildReceipt=self.build_pin, nativeReceipt=self.native_pin)
            def read_json(path, maximum):
                values = {'selection.json':(selected, pin), 'server-modules.json':(self.content.compiled,selected['compiledModules']),
                    'server-build.json':(build,selected['originalBuild']), 'profile.json':(self.profile,pin),
                    'content-receipt.json':(self.content.receipt,selected['contentReceipt'])}
                return values[path.name]
            def finished(*args, **kwargs):
                self.assertEqual(kwargs['helper'],programs/'helpers/playerbots-schema')
                self.assertEqual(kwargs['helper_receipt'],programs/'provenance/playerbots-helper-build.json')
                self.assertEqual(kwargs['native_receipt'],programs/'provenance/playerbots-native-sql.json')
                self.assertEqual(kwargs['data'],self.data/'data'); self.assertEqual(kwargs['staged_data'],self.data)
                with db.state_scope(self.state,kwargs['state_lease']): pass
                return dict(scope=setup.VERIFIED_SCOPE)
            with patch.object(setup.owner,'read_json',side_effect=read_json), \
                    patch.object(setup.packaged,'verify',return_value=self.content), \
                    patch.object(db,'Mysql') as mysql_context, \
                    patch.object(setup,'compose',return_value=dict(scope=setup.SCOPE)) as core, \
                    patch.object(setup,'finish_playerbots',side_effect=finished) as finish:
                mysql_context.return_value.__enter__.return_value = self.connection
                kwargs = {} if phase == 'core' else dict(phase=phase)
                result = setup.run(self.state,session,self.content.root,session/'content-receipt.json',programs,
                    service_session,self.mysql,self.data,self.root/'profile.json','8.0.46','1'*32,'2'*32,self.uuid,**kwargs)
                self.assertEqual(core.call_count,int(phase=='core')); self.assertEqual(finish.call_count,int(phase=='playerbots'))
                self.assertEqual(result['scope'],setup.SCOPE if phase=='core' else setup.VERIFIED_SCOPE)
                self.assertEqual(json.loads((session/'result.json').read_bytes()),result)

    def test_transition_binding_or_live_completed_schema_drift_cannot_be_adopted(self):
        self.finish(); report = (self.state/setup.VERIFIED_REPORT).read_bytes()
        path = self.state/setup.FINISH_JOURNAL; before = path.read_bytes()
        intent = json.loads(before); intent['binding']['helperNativeReceipt']['sha256'] = '0'*64
        db.atomic_json(path,intent)
        with self.assertRaises(db.BootstrapError): self.finish()
        path.write_bytes(before); self.connection.columns.append('changed live column')
        with self.assertRaises(db.BootstrapError): self.finish()
        self.assertEqual((self.state/setup.VERIFIED_REPORT).read_bytes(), report); self.assertEqual(len(self.fixture.runs),1)


if __name__=='__main__':unittest.main()
