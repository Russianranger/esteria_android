"""Portable session orchestration/lock fixtures only; SQL/source phases are mocked.

Actual child/pipe/socket fixtures live in test_server_session_process. Neither
suite executes a real game server or qualifies schema/content/gameplay.
"""
from contextlib import contextmanager
from pathlib import Path
import os
import json
import tempfile
import unittest
from unittest.mock import patch

from runtime import server_session as session


class Connection:
    def __init__(self):
        self.locks = []

    def query(self, sql):
        if 'GET_LOCK(' in sql:
            self.locks.append(sql.split("'")[1]); return ['1']
        if 'RELEASE_LOCK(' in sql:
            self.locks.remove(sql.split("'")[1]); return ['1']
        raise AssertionError('No real source SQL is authorized in this orchestration fixture')


class ServerSessionPreparationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name);self.state = self.root / 'state';self.state.mkdir(mode=0o700)
        self.data = self.root / 'generation';self.data.mkdir();(self.data / 'receipt.json').write_text('TEST_ONLY')
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab';self.pin = dict(bytes=1,sha256='a'*64)
        self.verified = session.content.VerifiedContent(self.root/'content',self.root/'content/source',{}, {},
            dict(sourceLockSha256='b'*64),dict(receipt=self.pin))
        self.profile = json.loads((Path(__file__).parents[1] / 'config/local-server.json').read_bytes())
        self.connection = Connection();self.calls = [];self.lease = None
        self.bots = dict(playerbotsSchemaInitialized=True,exactSourceLedgerVerified=True,
                         preparedStatementCount=session.playerbots.STATEMENTS,mysqlUuid=self.uuid,journalIdentity=self.pin)
        self.patches = []
        self.mock(session,'_programs',lambda value:value)
        self.mock(session.data,'verify_completed',lambda *_,**__:{'inputs':{'serverRevision':session.realm.SERVER_REVISION}})
        self.mock(session.playerbots,'verify_completed',self.verify_bots)
        self.mock(session.config,'render_verified',self.render)
        self.mock(session.realm,'provision_verified',self.realm)
        self.mock(session.account,'provision_verified',self.account)
        self.mock(session.schema,'credential_identity',lambda *_:{'TEST_ONLY_CREDENTIAL_PIN':self.pin})
        self.mock(session.schema,'account_identity',lambda *_:self.pin)

    def mock(self, target, name, action):
        active=patch.object(target,name,side_effect=action);active.start();self.addCleanup(active.stop)

    def held(self):
        with self.assertRaises(session.db.BootstrapError):
            with session.db.state_lock(self.state):pass

    def verify_bots(self,*args,**kwargs):
        self.held();self.calls.append('actual-completed-PB-gate-mocked')
        self.assertEqual(set(self.connection.locks),{'esteria-local-bootstrap','esteria-local-realm','esteria-local-account'})
        return dict(self.bots)

    def render(self,*args,**kwargs):
        self.held();self.calls.append('new-config');self.assertEqual(args[2],self.data/'data')
        self.assertEqual(self.connection.locks,[])
        return dict(generation='c'*64,module_configurations_complete=True)

    def realm(self,*args,**kwargs):
        self.held();self.calls.append('verify-realm');self.assertTrue(kwargs['verify_only'])
        self.assertEqual(kwargs['data'],self.data/'data');self.lease=kwargs['state_lease']
        with session.db.state_scope(self.state,self.lease):pass
        return dict(operation='verified',mysqlUuid=self.uuid,configGeneration='c'*64)

    def account(self,*args,**kwargs):
        self.held();self.calls.append('verify-account');self.assertTrue(kwargs['verify_only'])
        self.assertIs(kwargs['state_lease'],self.lease)
        return dict(operation='verified-owned-account',mysqlUuid=self.uuid,configGeneration='c'*64)

    def prepare(self,**extra):
        args=dict(programs={name:dict(path=self.root/name,identity=self.pin) for name in ('authserver','worldserver')},
            data_generation=self.data,expected_data_inputs={'TEST_ONLY':True},profile=self.profile,mysql=Path('/usr/bin/mysql'),
            expected_uuid=self.uuid,verify_service=lambda:True)
        args.update(extra)
        return session.prepare(self.verified,self.connection,self.state,'8.0.46',**args)

    def test_real_state_lock_spans_completed_gate_new_config_and_verify_only_phases(self):
        with session.db.state_lock(self.state) as lease:
            prepared=self.prepare(state_lease=lease)
            self.assertIs(self.lease,lease)
            self.held()
        self.assertIsInstance(prepared,session.Prepared)
        self.assertEqual(self.calls,['actual-completed-PB-gate-mocked','new-config','verify-realm','verify-account'])
        self.assertEqual(self.connection.locks,[])
        self.assertEqual(prepared.mysql,Path('/usr/bin/mysql'))
        self.assertFalse(any(self.state.rglob('server-setup-complete.json')))
        self.assertFalse(any(self.state.rglob('ready.json')))

    def test_stale_real_state_lease_prevents_any_child_or_configuration_lock(self):
        with session.db.state_lock(self.state) as lease:
            prepared=self.prepare(state_lease=lease)
        owner=session.Session(prepared,self.connection,self.root,lambda:True)
        with self.assertRaises(session.db.BootstrapError):owner.start()
        self.assertIsNone(owner.auth);self.assertIsNone(owner.world);self.assertIsNone(owner.configuration_lease)
        with self.assertRaisesRegex(ValueError,'single-use'):owner.start()
        owner.close();self.assertTrue(owner.closed)

    def test_world_cleanup_failure_retains_auth_and_configuration_dependency(self):
        from unittest.mock import Mock, MagicMock
        with session.db.state_lock(self.state) as lease:
            prepared=self.prepare(state_lease=lease)
            owner=session.Session(prepared,self.connection,self.root,lambda:True)
            world=Mock(closed=False);world.stop.side_effect=OSError('TEST_ONLY_WORLD_REAP_FAILURE')
            auth=Mock(closed=False);configuration=MagicMock()
            owner.world=world;owner.auth=auth;owner.configuration_lease=configuration
            with self.assertRaisesRegex(OSError,'WORLD_REAP'):owner.close()
            self.assertFalse(owner.closed);auth.stop.assert_not_called();configuration.__exit__.assert_not_called()
            def world_stopped():world.closed=True
            def auth_stopped():auth.closed=True
            world.stop.side_effect=world_stopped;auth.stop.side_effect=auth_stopped
            with self.assertRaisesRegex(ValueError,'Earlier server cleanup'):owner.close()
            self.assertTrue(owner.closed);self.assertEqual(owner.failure,'OSError');configuration.__exit__.assert_called_once()

    def test_missing_or_wrong_same_instance_pb_gate_cannot_render_config_or_start_servers(self):
        for changes in (dict(playerbotsSchemaInitialized=False),dict(exactSourceLedgerVerified=False),
                        dict(preparedStatementCount=51),dict(mysqlUuid='11234567-89ab-4cde-8fab-0123456789ab')):
            self.calls.clear();saved=dict(self.bots);self.bots.update(changes)
            with self.assertRaisesRegex(ValueError,'playerbots schema'):
                self.prepare()
            self.assertEqual(self.calls,['actual-completed-PB-gate-mocked'])
            self.assertEqual(self.connection.locks,[]);self.bots=saved

    def test_preflight_or_cancellation_failure_never_reaches_source_setup(self):
        with patch.object(session.data,'verify_completed',side_effect=ValueError('TEST_ONLY_PREPARED_DATA_CHANGED')):
            with self.assertRaisesRegex(ValueError,'DATA_CHANGED'):self.prepare()
        self.assertEqual(self.calls,[])
        with self.assertRaisesRegex(ValueError,'cancelled'):
            self.prepare(cancelled=lambda:True)
        self.assertEqual(self.calls,[])

    def test_unsealed_profile_missing_service_and_unverified_prepared_capability_refused(self):
        with self.assertRaises((ValueError,session.db.BootstrapError)):
            self.prepare(profile=dict(self.profile,world_port=9999))
        with self.assertRaisesRegex(ValueError,'owned database'):
            self.prepare(verify_service=None)
        with self.assertRaisesRegex(ValueError,'actual verification'):
            session.Prepared(self.verified,self.state,'8.0.46',self.uuid,'c'*64,self.data,self.pin,{},self.profile,
                {},self.pin,self.pin,Path('/usr/bin/mysql'),None,None)
        self.assertEqual(self.calls,[])


class ServerSessionSelectionTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.path=Path(temporary.name)/'selection.json'
        pin=dict(bytes=1,sha256='a'*64)
        self.value=dict(formatVersion=1,scope=session.SELECTION_SCOPE,source=dict(commit=session.realm.SERVER_REVISION),
            sourceLockSha256='b'*64,activeProofSha256='c'*64,programs=dict(authserver=pin,worldserver=pin),dataInputs={})
        self.value.update({name:pin for name in ('compiledModules','originalBuild','contentReceipt','profile','setupReceipt','dataReceipt')})

    def read(self):
        self.path.write_text(json.dumps(self.value));return session.selected_inputs(self.path)

    def test_exact_public_source_pins_only_no_caller_qualification_or_executable_path(self):
        self.assertEqual(self.read(),self.value)
        self.value['gameplayQualified']=True
        with self.assertRaisesRegex(ValueError,'typed session selection'):self.read()
        del self.value['gameplayQualified']
        self.value['programs']['authserver']=dict(bytes=1,sha256='a'*64,path='/arbitrary/executable')
        with self.assertRaises(ValueError):self.read()

    def test_wrong_source_noninteger_format_and_extra_program_are_refused(self):
        self.value['source']=dict(commit='0'*40)
        with self.assertRaisesRegex(ValueError,'reviewed session'):self.read()
        self.value['source']=dict(commit=session.realm.SERVER_REVISION);self.value['formatVersion']=True
        with self.assertRaisesRegex(ValueError,'typed session selection'):self.read()
        self.value['formatVersion']=1;self.value['programs']['shell']=self.value['programs']['authserver']
        with self.assertRaisesRegex(ValueError,'Both selected'):self.read()


class SessionControlTests(unittest.TestCase):
    @contextmanager
    def control(self):
        read,write=os.pipe()
        try:
            active=session.Control(read)
            try:yield active,write
            finally:active.close()
        finally:os.close(read);os.close(write)

    def test_fixed_source_shutdown_partial_input_and_idle_are_bounded(self):
        with self.control() as (control,write):
            self.assertIsNone(control.read(0))
            os.write(write,b'server shut');self.assertIsNone(control.read(.1))
            os.write(write,b'down 1\n');self.assertEqual(control.read(.1),'command')

    def test_unknown_or_oversized_control_cannot_become_shell_or_sql(self):
        for command in (b'quit\n',b'server shutdown 0\n',b'x'*21):
            with self.control() as (control,write):
                os.write(write,command)
                with self.assertRaises(ValueError):control.read(.1)

    def test_owner_eof_is_not_an_explicit_console_command(self):
        read,write=os.pipe();control=session.Control(read)
        try:
            os.close(write);self.assertEqual(control.read(.1),'owner-eof')
        finally:control.close();os.close(read)


if __name__=='__main__':unittest.main()
