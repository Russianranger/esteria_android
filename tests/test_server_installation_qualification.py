"""Host metadata/owned-child fixtures, never native SQL or phone qualification."""
import copy
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from tools import qualify_server_installation as setup


class InstallationQualification(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='est-install-native-');self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.state=self.root/'state';self.state.mkdir(mode=0o700)
        (self.state/'logs').mkdir(mode=0o700);self.sessions=self.root/'sessions';self.sessions.mkdir(mode=0o700)
        self.session=self.sessions/('1'*32);self.session.mkdir(mode=0o700)
        self.uuid='01234567-89ab-4cde-8fab-0123456789ab';self.version='8.0.46-0ubuntu0.24.04.4';self.operation='1'*32
        self.helper={name:dict(bytes=7,sha256=letter*64) for name,letter in
                     (('helperExecutable','a'),('helperBuildReceipt','b'),('helperNativeReceipt','c'))}

    def stopped(self):
        return dict(formatVersion=1,scope='owned-local-mysql-stopped',operationId=self.operation,version=self.version,
            uuid=self.uuid,stopReason='command',engineStarted=True,readyBeforeStop=True,cleanEngineExit=True,
            dataRemoved=False,characterPersistenceQualified=False,gameplayQualified=False)

    def verified(self):
        row=dict(formatVersion=1,scope=setup.installation.VERIFIED_SCOPE,mysqlUuid=self.uuid,mysqlVersion=self.version,
            configGeneration='e'*64,pendingComponents=['owned-clean-engine-stop'],compiledPlayerbotsLoaderExecuted=False,**self.helper)
        for name in ('baselineComplete','compiledUpdaterCompleted','sourceLedgersVerified','sameRevisionReentryVerified',
                'localRealmVerified','localAccountVerified','ownedServiceIdentityVerified','fourSchemasVerified','playerbotsSchemaVerified'):
            row[name]=True
        for name in ('engineStopped','completeSetupQualified','slotPromoted','databaseServiceStarted','databaseServiceStopped',
                'authserverExecuted','worldserverExecuted','serverDataQualified','playerbotsAiQualified','botCharactersCreated',
                'androidRuntimeQualified','gameplayQualified','compiledUpdaterExecuted'):
            row[name]=False
        for field,name in setup.JOURNAL_FIELDS.items():
            (self.state/name).parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            setup.db.atomic_json(self.state/name,dict(hostMetadataFixtureOnly=True,field=field))
            row[field]=setup.baseline.file_identity(self.state/name)
        setup.db.atomic_json(self.state/setup.installation.VERIFIED_REPORT,row)
        setup.db.atomic_json(self.session/'stopped.json',self.stopped())
        return row

    def test_public_evidence_removes_config_and_private_account_bindings_recursively(self):
        original=dict(configGeneration='secret-derived',nested=[dict(stagedConfigGeneration='old',finalConfigGeneration='new',
            localAccountJournal=dict(sha256='private'),accountJournal='private',credentials='private',gameplayQualified=False)])
        self.assertEqual(setup.public_record(original),dict(nested=[dict(gameplayQualified=False)]))
        self.assertIn('configGeneration',original)

    def test_failure_context_excludes_exception_messages_locals_and_journal_private_fields(self):
        secret = 'fixture-private-password-DO-NOT-EXPORT'
        setup.db.atomic_json(self.state / setup.updater.JOURNAL, dict(phase='failed',
            compiledUpdaterExecuted=True, credentials=secret, invocation='/private/' + secret))
        try:
            raise setup.db.BootstrapError(secret)
        except setup.db.BootstrapError as error:
            value = setup.safe_failure_context(error, self.state)
        encoded = json.dumps(value)
        self.assertNotIn(secret, encoded); self.assertNotIn('/private/', encoded)
        self.assertEqual(value['failureReasonCode'], 'unclassified-static-boundary')
        self.assertEqual(value['ownedOperationStages'], dict(updater=dict(phase='failed', compiledUpdaterExecuted=True)))
        try:
            setup.updater.stock_world_sql_snapshot(Mock(query=lambda _: ['1\t0\t0\t0']))
        except setup.db.BootstrapError as error:
            value = setup.safe_failure_context(error, self.state)
        self.assertEqual(value['failureReasonCode'], 'stock-race-class-map-outfit-overlay-nonempty')
        self.assertTrue(any(row['source'] == 'runtime/server_update_setup.py' and
                            row['function'] == 'stock_world_sql_snapshot' for row in value['failureSourceFrames']))

    def test_stop_ack_requires_actual_same_operation_version_uuid_and_clean_flags(self):
        row=self.stopped();setup.stopped_document(row,self.operation,self.version,self.uuid)
        changes=(('operationId','2'*32),('version','8.0.46'),('uuid','11234567-89ab-4cde-8fab-0123456789ab'),
            ('stopReason','owner-signal'),('engineStarted',False),('readyBeforeStop',False),('cleanEngineExit','true'),
            ('dataRemoved',True),('gameplayQualified',True),('formatVersion',True))
        for name,value in changes:
            with self.subTest(field=name),self.assertRaises(ValueError):
                setup.stopped_document(dict(row,**{name:value}),self.operation,self.version,self.uuid)

    def test_service_public_receipts_select_only_fixed_fields_and_bind_full_private_bytes(self):
        for name in ('ready.json','stopped.json'):
            value = self.stopped() if name == 'stopped.json' else dict(formatVersion=1,scope='owned-local-mysql-live-service',
                operationId=self.operation,version=self.version,uuid=self.uuid,bindAddress='127.0.0.1',port=13306,
                liveSqlAuthenticated=True,ownedEngineIdentityVerified=True,applicationSchemaUpdatesQualified=False,gameplayQualified=False)
            value.update(datadir='/private/runtime/database',pid=1234,enginePid=5678,processIdentity='private-fixture',
                         unknownPrivateField='private-fixture')
            setup.db.atomic_json(self.session/name,value)
            projected=setup.public_service_receipt(self.session,name,value)
            self.assertEqual(projected['receiptIdentity'],setup.baseline.file_identity(self.session/name))
            for field in ('datadir','pid','enginePid','processIdentity','unknownPrivateField'): self.assertNotIn(field,projected)
            self.assertNotIn('/private/',json.dumps(projected));self.assertNotIn('private-fixture',json.dumps(projected))
            changed=dict(value,uuid='11234567-89ab-4cde-8fab-0123456789ab')
            with self.assertRaisesRegex(ValueError,'changed before public'):setup.public_service_receipt(self.session,name,changed)

    def test_private_sql_completion_binds_four_journals_and_actual_ack_without_phone_claim(self):
        verified=self.verified();before={name:(self.state/name).read_bytes() for name in setup.JOURNAL_FIELDS.values()}
        result=setup.complete_sql_receipt(self.state,self.session,verified,self.helper,self.version,self.uuid,self.operation)
        self.assertEqual(result['scope'],setup.COMPLETE_SCOPE);self.assertTrue(result['completeSetupQualified'])
        self.assertTrue(result['cleanEngineStopped']);self.assertFalse(result['slotPromoted'])
        self.assertFalse(result['androidRuntimeQualified']);self.assertFalse(result['gameplayQualified'])
        self.assertEqual({name:(self.state/name).read_bytes() for name in before},before)
        self.assertEqual(result['fourSchemaReceipt'],setup.baseline.file_identity(self.state/setup.installation.VERIFIED_REPORT))
        self.assertEqual(result['stoppedReceipt'],setup.baseline.file_identity(self.session/'stopped.json'))
        with self.assertRaisesRegex(ValueError,'Existing'):setup.complete_sql_receipt(self.state,self.session,verified,self.helper,self.version,self.uuid,self.operation)
        path=self.state/setup.playerbots.JOURNAL;path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'journal'):setup.validate_complete(self.state,self.session,result,self.helper,self.version,self.uuid,self.operation)

    def test_false_schema_or_changed_ack_refuses_before_completion_marker(self):
        for kind in ('false-schema','wrong-stop','wrong-helper','changed-journal'):
            verified=self.verified();helper=copy.deepcopy(self.helper)
            if kind=='false-schema':
                verified['fourSchemasVerified']=False;setup.db.atomic_json(self.state/setup.installation.VERIFIED_REPORT,verified)
            elif kind=='wrong-stop':setup.db.atomic_json(self.session/'stopped.json',dict(self.stopped(),readyBeforeStop=False))
            elif kind=='wrong-helper':helper['helperNativeReceipt']['sha256']='0'*64
            else:
                path=self.state/setup.schema.JOURNAL;path.write_bytes(path.read_bytes()+b' ')
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                setup.complete_sql_receipt(self.state,self.session,verified,helper,self.version,self.uuid,self.operation)
            self.assertFalse((self.state/'server-setup-complete.json').exists())

    def test_native_arch_and_existing_output_refuse_before_input_or_sql_use(self):
        output=self.root/'new'
        with patch.object(setup.platform,'machine',return_value='x86_64'),patch.object(setup.db,'initialize') as initialize, \
                patch.object(setup.inputs,'load_pin') as load,self.assertRaisesRegex(ValueError,'Linux ARM64'):
            setup.run(self.root,Path('/usr/bin/mysql'),Path('/usr/sbin/mysqld'),self.version,output)
        initialize.assert_not_called();load.assert_not_called();self.assertFalse(output.exists())
        output.mkdir();(output/'sentinel').write_bytes(b'preserve')
        with patch.object(setup.platform,'machine',return_value='aarch64'),patch.object(setup.inputs,'load_pin') as load, \
                self.assertRaisesRegex(ValueError,'Existing'):
            setup.run(self.root,Path('/usr/bin/mysql'),Path('/usr/sbin/mysqld'),self.version,output)
        load.assert_not_called();self.assertEqual((output/'sentinel').read_bytes(),b'preserve')

    def test_worker_delegates_actual_production_service_without_initialization(self):
        with patch.object(setup.service,'serve',return_value=dict(stopReason='command')) as serve, \
                patch.object(setup.signal,'signal'),patch.object(setup.db,'initialize') as initialize:
            self.assertEqual(setup.worker(self.state,self.session,Path('/mysql'),Path('/mysqld'),self.version,self.operation,17),0)
            args=serve.call_args.args;self.assertEqual(args[:7],(self.state,self.session,Path('/mysql'),Path('/mysqld'),self.version,self.operation,17))
            self.assertFalse(args[7]());initialize.assert_not_called()

    def fixture_command(self, *, exit_code=0, descendant=False, wrong_uuid=False):
        # This child emulates only the control/receipt protocol. It is explicitly
        # not production service, engine readiness or native SQL evidence.
        source='''import json,os,pathlib,sys,time,signal
state,session,version,operation=map(str,sys.argv[1:]);state=pathlib.Path(state);session=pathlib.Path(session)
uuid="UUID"
def write(name,value):
 path=session/name;path.write_text(json.dumps(value));path.chmod(0o600)
ready=dict(formatVersion=1,scope="owned-local-mysql-live-service",operationId=operation,version=version,uuid=uuid,
 datadir=str(state/"database"),bindAddress="127.0.0.1",port=13306,databases=["acore_auth","acore_world","acore_characters","acore_playerbots"],
 liveSqlAuthenticated=True,ownedEngineIdentityVerified=True,applicationSchemaUpdatesQualified=False,gameplayQualified=False)
DESCENDANT
write("ready.json",ready)
assert sys.stdin.buffer.readline()==b"shutdown\\n"
write("stopped.json",dict(formatVersion=1,scope="owned-local-mysql-stopped",operationId=operation,version=version,uuid=uuid,
 stopReason="command",engineStarted=True,readyBeforeStop=True,cleanEngineExit=True,dataRemoved=False,characterPersistenceQualified=False,gameplayQualified=False))
raise SystemExit(EXIT)
'''.replace('UUID','11234567-89ab-4cde-8fab-0123456789ab' if wrong_uuid else self.uuid).replace('EXIT',str(exit_code))
        code='''pid=os.fork()
if pid==0:
 signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60);raise SystemExit(0)
(session/"descendant.pid").write_text(str(pid))''' if descendant else ''
        source=source.replace('DESCENDANT',code)
        return lambda state,session,mysql,mysqld,version,operation:[sys.executable,'-c',source,str(state),str(session),version,operation]

    def test_real_host_child_control_stop_and_descendant_cleanup_keep_owned_leader(self):
        with patch.object(setup,'worker_command',side_effect=self.fixture_command(descendant=True)):
            owned=setup.ServiceProcess(self.state,self.sessions,Path('/mysql'),Path('/mysqld'),self.version)
        self.addCleanup(owned.close)
        ready=owned.wait_ready(self.uuid,timeout=3);self.assertEqual(ready['uuid'],self.uuid)
        self.assertIsNone(owned.process.returncode)
        child=int((owned.session/'descendant.pid').read_text())
        stopped=owned.stop(self.uuid,timeout=3)
        self.assertTrue(stopped['cleanEngineExit']);self.assertTrue(owned.group.closed);self.assertEqual(owned.process.returncode,0)
        self.assertFalse(owned.group.forced)
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            try: status=Path('/proc/'+str(child)+'/stat').read_text().split(') ',1)[1][0]
            except FileNotFoundError:break
            if status=='Z':break
            time.sleep(.01)
        else:self.fail('Owned descendant remained running after leader exited')
        log=self.state/'logs'/('service-'+owned.operation+'-private.log')
        self.assertEqual(log.stat().st_mode&0o777,0o600)

    def test_nonzero_child_and_wrong_ready_identity_never_establish_clean_stop(self):
        with patch.object(setup,'worker_command',side_effect=self.fixture_command(exit_code=2)):
            owned=setup.ServiceProcess(self.state,self.sessions,Path('/mysql'),Path('/mysqld'),self.version)
        try:
            owned.wait_ready(self.uuid,timeout=3)
            with self.assertRaisesRegex(ValueError,'exit cleanly'):owned.stop(self.uuid,timeout=3)
        finally:owned.close()
        with patch.object(setup,'worker_command',side_effect=self.fixture_command(wrong_uuid=True)):
            owned=setup.ServiceProcess(self.state,self.sessions,Path('/mysql'),Path('/mysqld'),self.version)
        try:
            with self.assertRaisesRegex(ValueError,'ready acknowledgment'):owned.wait_ready(self.uuid,timeout=3)
        finally:owned.close()


if __name__=='__main__':unittest.main()
