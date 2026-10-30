import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import android_server_installation_setup as setup, mysql_bootstrap as db
from runtime import server_content as content, server_schema_setup as schema, server_update_setup as updates


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


if __name__=='__main__':unittest.main()
