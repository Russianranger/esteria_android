"""Source-bound local auth/world session over an already owned database.

No initialization, migration, SQL replay, account reset or game-client launch.
Format-checked assets permit an internal loader attempt, never a world/gameplay
qualification. The caller retains MySQL and all immutable providers until both
owned servers and diagnostic workers are confirmed stopped.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import sys
import time

try:
    from . import mysql_bootstrap as db, server_content as content, server_schema_setup as schema
    from . import server_schema_baseline as baseline, server_config as config
    from . import provision_local_realm as realm, provision_local_account as account
    from . import server_playerbots_setup as playerbots, server_data_generation as data
    from . import server_session_process as processes, android_server_schema_setup as owner, mysql_service as service
except ImportError:
    import mysql_bootstrap as db
    import server_content as content
    import server_schema_setup as schema
    import server_schema_baseline as baseline
    import server_config as config
    import provision_local_realm as realm
    import provision_local_account as account
    import server_playerbots_setup as playerbots
    import server_data_generation as data
    import server_session_process as processes
    import android_server_schema_setup as owner
    import mysql_service as service

require = processes.require
SCOPE = 'owned-local-auth-world-session-not-gameplay-qualified'
SELECTION_SCOPE = 'android-owned-auth-world-selection'
_PREPARED_CAPABILITY = object()


@dataclass(frozen=True)
class Prepared:
    """Created only by prepare's actual source/schema/data/config verification."""
    content: content.VerifiedContent
    state: Path
    version: str
    uuid: str
    generation: str
    data_root: Path
    data_receipt: dict
    programs: dict
    profile: dict
    credential_identity: dict
    account_identity: dict
    playerbots_identity: dict
    mysql: Path
    state_lease: object = field(repr=False, compare=False)
    _capability: object = field(repr=False, compare=False)

    def __post_init__(self):
        require(self._capability is _PREPARED_CAPABILITY, 'Prepared session must come from actual verification')


def _programs(programs):
    require(type(programs) is dict and set(programs) == {'authserver', 'worldserver'},
            'Both fixed selected server programs required')
    result = {}
    for name, selected in programs.items():
        require(type(selected) is dict and set(selected) == {'path', 'identity'}, 'Selected server identity required')
        path, identity = Path(selected['path']), selected['identity']
        require(path.is_absolute() and type(identity) is dict and set(identity) == {'bytes', 'sha256'} and
                type(identity['bytes']) is int and 0 < identity['bytes'] <= 64 << 20 and
                type(identity['sha256']) is str and re.fullmatch('[a-f0-9]{64}', identity['sha256']) and
                baseline.file_identity(path) == identity and os.access(path, os.X_OK), 'Selected server program bytes changed')
        with path.open('rb') as source:
            header = source.read(64)
        require(len(header) == 64 and header[:7] == b'\x7fELF\x02\x01\x01' and header[18:20] == b'\xb7\x00',
                'Selected ARM64 server ELF required')
        result[name] = dict(path=path, identity=dict(identity))
    return result


def prepare(verified, connection, state, version, *, programs, data_generation, expected_data_inputs,
            profile, mysql, expected_uuid, verify_service, state_lease=None, cancelled=lambda: False):
    """Verify actual four-schema ownership before preparing session config.

    Caller holds the database's live service lease. Complete promotion is a
    separate typed application gate; a boolean/format-only asset receipt cannot
    replace this actual PB/update ledger and account verification.
    """
    require(isinstance(verified, content.VerifiedContent) and callable(verify_service) and
            type(expected_data_inputs) is dict and isinstance(expected_uuid, str) and
            re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', expected_uuid),
            'Verified content, prepared data selection and owned database required')
    db.exact_version(version); state = db.private_path(Path(state)); profile = config.sealed_profile(profile)
    require(not cancelled() and verify_service() is not False, 'Owned session preparation cancelled or database changed')
    selected = _programs(programs)
    data_root = data.storage.canonical(Path(data_generation))
    expected_generation = hashlib.sha256(data.storage.encoded(expected_data_inputs)).hexdigest()
    checked_data = data.verify_completed(data_root, expected_data_inputs, expected_generation=expected_generation)
    require(checked_data['inputs']['serverRevision'] == realm.SERVER_REVISION, 'Prepared data server source differs')
    with db.state_scope(state, state_lease) as lease:
        # Verify the real completed compiled loader first. Missing fourth-schema
        # proof must not change any active configuration or start any process.
        with realm.named_locks(connection, ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account')):
            bots = playerbots.verify_completed(verified, connection, state, version,
                expected_uuid=expected_uuid, verify_service=verify_service, cancelled=cancelled)
        require(bots.get('playerbotsSchemaInitialized') is True and bots.get('exactSourceLedgerVerified') is True and
                bots.get('preparedStatementCount') == playerbots.STATEMENTS and bots.get('mysqlUuid') == expected_uuid,
                'Completed same-instance playerbots schema required')
        # Whole prepared-generation mount: the actual server DataDir is its
        # data child. This changes generated configs only, never setup journals.
        rendered = config.render_verified(verified, state, data_root / 'data', Path(mysql), profile=profile)
        require(rendered.get('module_configurations_complete') is True, 'Complete source module configuration required')
        common = dict(profile=profile, data=data_root / 'data', mysql=Path(mysql), expected_uuid=expected_uuid,
                      verify_service=verify_service, verify_only=True, state_lease=lease)
        checked_realm = realm.provision_verified(verified, connection, state, version, **common)
        checked_account = account.provision_verified(verified, connection, state, version, **common)
        generation = rendered['generation']
        require(checked_realm.get('operation') == 'verified' and checked_account.get('operation') == 'verified-owned-account' and
                all(row.get('mysqlUuid') == expected_uuid and row.get('configGeneration') == generation
                    for row in (checked_realm, checked_account)), 'Owned realm/account runtime context differs')
        require(not cancelled() and verify_service() is not False, 'Session ownership changed during preparation')
        return Prepared(verified, state, version, expected_uuid, generation, data_root,
            baseline.file_identity(data_root / 'receipt.json'), selected, profile,
            schema.credential_identity(state), schema.account_identity(state), bots['journalIdentity'], Path(mysql), lease, _PREPARED_CAPABILITY)


class Control:
    """Only the exact source shutdown line or owner EOF; bounded nonblocking IO."""
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.blocking = os.get_blocking(descriptor)
        os.set_blocking(descriptor, False)
        self.selector = selectors.DefaultSelector()
        try:
            self.selector.register(descriptor, selectors.EVENT_READ)
        except BaseException:
            self.selector.close(); os.set_blocking(descriptor, self.blocking); raise
        self.buffer = b''

    def read(self, timeout=.1):
        if not self.selector.select(timeout):
            return None
        block = os.read(self.descriptor, 21)
        if not block:
            require(not self.buffer, 'Incomplete server control line')
            return 'owner-eof'
        self.buffer += block
        require(len(self.buffer) <= len(processes.WORLD_SHUTDOWN), 'Oversized server control line')
        if b'\n' not in self.buffer:
            return None
        require(self.buffer == processes.WORLD_SHUTDOWN, 'Unsupported server control command')
        return 'command'

    def close(self):
        self.selector.close(); os.set_blocking(self.descriptor, self.blocking)


class Session:
    """Retained before child launch. Caller holds state/config/DB leases through close."""
    def __init__(self, prepared, connection, operation, verify_service):
        require(isinstance(prepared, Prepared) and callable(verify_service), 'Verified prepared session required')
        self.prepared, self.connection = prepared, connection
        self.operation, self.verify_service = Path(operation), verify_service
        require(self.operation.is_absolute(), 'Private session operation required')
        self.auth = self.world = None
        self.ready = self.closed = self.started = False
        self.failure = None
        self.configuration_lease = None

    def _check(self, *, world_ready=False):
        selected = self.prepared
        # Reusing this actual lease validates it; it never acquires a new lock
        # after the originating installation/session scope has ended.
        with db.state_scope(selected.state, selected.state_lease):
            pass
        require(self.verify_service() is not False, 'Owned database service changed during server session')
        require(schema.credential_identity(selected.state) == selected.credential_identity and
                schema.account_identity(selected.state) == selected.account_identity and
                baseline.file_identity(selected.state / playerbots.JOURNAL) == selected.playerbots_identity,
                'Private server session credentials/account/schema context changed')
        require(self.connection.query(realm.ROW_SQL) == [realm.EXPECTED_ROW], 'Local realm endpoint changed during session')
        if world_ready:
            require(self.connection.query('SELECT `flag` FROM `acore_auth`.`realmlist` WHERE `id`=1') == ['0'],
                    'Owned realm is not online for this server build')
        for child in (self.auth, self.world):
            if child is not None:
                require(child.alive() and child.error is None, 'Owned server or diagnostic worker exited')

    def _await(self, condition, deadline, cancelled):
        while True:
            require(not cancelled(), 'Owned server startup cancelled')
            self._check()
            if condition():
                return
            require(time.monotonic() < deadline, 'Owned server readiness deadline exceeded')
            time.sleep(.05)

    def start(self, *, timeout=180, cancelled=lambda: False):
        require(not self.started and self.auth is None and self.world is None and not self.closed and 0 < timeout <= 600,
                'Server session startup is single-use and bounded')
        self.started = True
        selected = self.prepared
        self._check()
        require(baseline.file_identity(selected.data_root / 'receipt.json') == selected.data_receipt,
                'Prepared data receipt changed before launch')
        self.configuration_lease = realm.config_lock(selected.state)
        self.configuration_lease.__enter__()
        password = db.read_secret(selected.state / 'accounts/database-secret')
        require(realm.active_config_verified(selected.content, selected.state, password,
            profile=selected.profile, data=selected.data_root / 'data', mysql=selected.mysql) == selected.generation,
            'Prepared runtime configuration changed before launch')
        password = None
        _programs(selected.programs)
        self._check(); deadline = time.monotonic() + timeout
        configurations = selected.state / 'config/generations' / selected.generation
        self.auth = processes.ServerChild('authserver', selected.programs['authserver']['path'],
            configurations / 'authserver.conf', selected.state / 'run/authserver', self.operation / 'authserver.log')
        self.auth.start()
        self._await(lambda: processes.owns_loopback_listener(self.auth.group, 3724), deadline, cancelled)
        require(processes.auth_challenge(), 'Auth source challenge callback failed')
        require(processes.owns_loopback_listener(self.auth.group, 3724), 'Auth listener changed during protocol probe')
        self._check()
        self.world = processes.ServerChild('worldserver', selected.programs['worldserver']['path'],
            configurations / 'worldserver.conf', selected.state / 'run/worldserver', self.operation / 'worldserver.log')
        self.world.start()
        self._await(lambda: processes.owns_loopback_listener(self.world.group, 8085), deadline, cancelled)
        require(processes.world_challenge(), 'World source protocol challenge failed')
        require(processes.owns_loopback_listener(self.world.group, 8085), 'World listener changed during protocol probe')
        before = self.world.info_counter(); self.world.send_world(processes.WORLD_INFO)
        self._await(lambda: self.world.info_counter() > before, deadline, cancelled)
        self._check(world_ready=True)
        self.ready = True
        return dict(formatVersion=1, scope=SCOPE, mysqlUuid=selected.uuid, mysqlVersion=selected.version,
            configGeneration=selected.generation, dataReceipt=selected.data_receipt,
            contentReceipt=selected.content.identities['receipt'], sourceLockSha256=selected.content.receipt['sourceLockSha256'],
            ownedAuthListenerVerified=True, ownedWorldListenerVerified=True, liveSqlAuthenticated=True,
            authChallengeProcessed=True,
            worldChallengeVerified=True, worldConsoleLoopVerified=True,
            characterPersistenceQualified=False, botAiQualified=False, androidRuntimeQualified=False, gameplayQualified=False)

    def monitor(self):
        require(self.ready and not self.closed, 'Ready owned server session required')
        self._check(world_ready=True)
        require(processes.owns_loopback_listener(self.auth.group, 3724) and
                processes.owns_loopback_listener(self.world.group, 8085), 'Owned listener identity changed during session')

    def close(self):
        self.ready = False
        if self.closed:
            require(self.failure is None, 'Earlier server session cleanup failure remains unresolved')
            return
        error = None
        # Do not stop auth or release dependencies while world remains unreaped.
        for child in (self.world, self.auth):
            if child is None:
                continue
            try:
                child.stop()
            except Exception as failure:
                self.failure = self.failure or type(failure).__name__
                if not child.closed:
                    raise
                error = error or failure
        if self.configuration_lease is not None:
            self.configuration_lease.__exit__(None, None, None)
            self.configuration_lease = None
        self.closed = True
        if error is not None:
            self.failure = self.failure or type(error).__name__
            raise error
        require(self.failure is None, 'Earlier server cleanup failure remains visible after retry')


class StopRequested(ValueError):
    pass


def selected_inputs(path):
    selected, _ = owner.read_json(path, 128 << 10)
    expected = {'formatVersion', 'scope', 'source', 'sourceLockSha256', 'compiledModules', 'originalBuild',
                'contentReceipt', 'profile', 'setupReceipt', 'activeProofSha256', 'programs', 'dataInputs', 'dataReceipt'}
    require(type(selected) is dict and set(selected) == expected and type(selected['formatVersion']) is int and
            selected['formatVersion'] == 1 and selected['scope'] == SELECTION_SCOPE,
            'Exact typed session selection required')
    require(type(selected['source']) is dict and selected['source'].get('commit') == realm.SERVER_REVISION,
            'Selected server source differs from the reviewed session')
    for name in ('sourceLockSha256', 'activeProofSha256'):
        require(type(selected[name]) is str and re.fullmatch('[a-f0-9]{64}', selected[name]), 'Invalid session source/proof identity')
    for name in ('compiledModules', 'originalBuild', 'contentReceipt', 'profile', 'setupReceipt', 'dataReceipt'):
        data.pin(selected[name])
    require(type(selected['programs']) is dict and set(selected['programs']) == {'authserver', 'worldserver'},
            'Both selected server program identities required')
    for pin in selected['programs'].values():
        data.pin(pin)
    require(type(selected['dataInputs']) is dict, 'Explicit verified data input selection required')
    return selected


def run(state, operation_root, content_root, receipt_path, programs_root, service_session, data_root,
        profile_path, mysql, version, operation, service_operation, uuid, *, descriptor=0, interrupted=lambda: False):
    """Fixed guest entrypoint under a retained application database lease.

    On an exceptional reap failure the actual execution mechanism keeps retrying
    its known children. It never writes stopped.json or releases the state/config
    leases while a child or diagnostic worker remains active.
    """
    require(re.fullmatch('[a-f0-9]{32}', operation) and re.fullmatch('[a-f0-9]{32}', service_operation),
            'Invalid server session operation identity')
    db.exact_version(version)
    for path in (state, operation_root, service_session):
        service.plain_directory(Path(path))
    require(state != operation_root and not state.is_relative_to(operation_root) and not operation_root.is_relative_to(state),
            'Session operation must be separate from database state')
    selected = selected_inputs(operation_root / 'selection.json')
    require(baseline.file_identity(state / 'server-setup-complete.json') == selected['setupReceipt'],
            'Promoted complete setup receipt changed')
    compiled, pin = owner.read_json(programs_root / 'provenance/server-modules.json', content.MAX_METADATA)
    require(pin == selected['compiledModules'], 'Session compiled-module selection differs')
    build, pin = owner.read_json(programs_root / 'provenance/server-build.json', content.MAX_METADATA)
    require(pin == selected['originalBuild'] and compiled.get('serverBuild') == pin and
            build.get('serverSource') == selected['source'] and
            build.get('sourcesLock', {}).get('sha256') == selected['sourceLockSha256'], 'Session original server source differs')
    profile, pin = owner.read_json(profile_path, 65536)
    require(pin == selected['profile'], 'Bundled sealed server profile changed')
    require(baseline.file_identity(receipt_path) == selected['contentReceipt'] and
            baseline.file_identity(data_root / 'receipt.json') == selected['dataReceipt'], 'Selected content/data receipt changed')
    selected_programs = {name: dict(path=programs_root / 'bin' / name, identity=pin)
                         for name, pin in selected['programs'].items()}
    control = Control(descriptor); stop_reason = [None]
    def requested():
        if stop_reason[0] is None:
            stop_reason[0] = 'signal' if interrupted() else control.read(0)
        return stop_reason[0] is not None
    def check_stop():
        if requested():
            raise StopRequested('Owned server stop requested')
    current = None; failure = None; reported = None
    try:
        verified = content.verify(content_root, receipt_path, selected['contentReceipt']['sha256'], selected['source'],
            selected['sourceLockSha256'], compiled, cancelled=requested)
        password = db.read_secret(state / 'accounts/database-secret')
        with db.state_scope(state) as lease, db.option_file(operation_root, 'esteria', password) as options:
            password = None
            connection = service.LiveConnection(mysql, options, None, check_stop)
            try:
                def verify_service():
                    owner.live_service(connection, state, service_session, version, service_operation, uuid)
                    return True
                prepared = prepare(verified, connection, state, version, programs=selected_programs,
                    data_generation=data_root, expected_data_inputs=selected['dataInputs'], profile=profile, mysql=mysql,
                    expected_uuid=uuid, verify_service=verify_service, state_lease=lease, cancelled=requested)
                current = Session(prepared, connection, operation_root, verify_service)
                try:
                    reported = dict(current.start(cancelled=requested), operationId=operation, serviceOperationId=service_operation,
                                    activeProofSha256=selected['activeProofSha256'])
                    db.atomic_json(operation_root / 'ready.json', reported)
                    while not requested():
                        current.monitor()
                        reason = control.read(.5)
                        if reason is not None:
                            stop_reason[0] = reason
                except Exception as error:
                    if not isinstance(error, StopRequested) and not requested():
                        failure = type(error).__name__
                finally:
                    # Reap failures do not turn into a fake clean exit. Keep the
                    # real guest alive and its database/config dependencies held.
                    while not current.closed:
                        try:
                            current.close()
                        except Exception as error:
                            failure = failure or type(error).__name__
                            if not current.closed:
                                time.sleep(.1)
            finally:
                connection.close()
    except Exception as error:
        if not isinstance(error, StopRequested):
            failure = failure or type(error).__name__
    finally:
        control.close()
    auth_clean = current is not None and current.auth is not None and current.auth.shutdown_acknowledged
    world_clean = current is not None and current.world is not None and current.world.shutdown_acknowledged
    result = dict(formatVersion=1, scope='owned-local-auth-world-stopped', operationId=operation,
        serviceOperationId=service_operation, mysqlUuid=uuid, mysqlVersion=version,
        activeProofSha256=selected['activeProofSha256'], stopReason=stop_reason[0] or 'failure',
        readyBeforeStop=reported is not None, ownedChildrenStopped=current is None or current.closed,
        worldConsoleShutdownAcknowledged=world_clean, authSourceSignalShutdownAcknowledged=auth_clean,
        failureType=failure, databaseStopped=False, databaseRemoved=False,
        characterPersistenceQualified=False, botAiQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    db.atomic_json(operation_root / 'stopped.json', result)
    require(stop_reason[0] == 'command' and failure is None and auth_clean and world_clean,
            'Local server session did not acknowledge clean source shutdown')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('expected-version', 'operation-id', 'service-operation-id', 'instance-uuid'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(); stopped = [False]
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.__setitem__(0, True))
    try:
        require(re.fullmatch('[a-f0-9]{32}', args.operation_id) and re.fullmatch('[a-f0-9]{32}', args.service_operation_id),
                'Invalid server session operation identity')
        operation = Path('/work/server-sessions') / args.operation_id
        run(Path('/work/state'), operation, Path('/esteria-server-content'), operation / 'content-receipt.json',
            Path('/esteria-server-programs'), Path('/work/mysql-sessions') / args.service_operation_id,
            Path('/esteria-data'), Path(__file__).parent / 'local-server.json', Path('/usr/bin/mysql'),
            args.expected_version, args.operation_id, args.service_operation_id, args.instance_uuid,
            interrupted=lambda: stopped[0])
        print('Owned local auth/world stopped; character/bot persistence and gameplay remain unqualified')
        return 0
    except Exception as error:
        print('Owned local server session failed (' + type(error).__name__ + '); database and private diagnostics retained')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
