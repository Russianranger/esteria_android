#!/usr/bin/env python3
"""Qualify real portable installation finish and production MySQL stop receipts.

Fresh disposable native ARM64 SQL only. This runs no compiler, authserver,
worldserver, Java coordinator, Android process or slot-promotion implementation.
Private SQL logs, configuration generations and account/credential bytes stay
inside the exclusively owned fixture.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import subprocess
import sys
import time

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_base_sql as base, qualify_dbimport as importer, verify_server_build as files
from tools import prepare_server_installation_inputs as inputs, package_playerbots_helper as candidate
from runtime import android_server_installation_setup as installation, android_server_schema_setup as adapter
from runtime import mysql_bootstrap as db, mysql_service as service, server_schema_setup as schema
from runtime import server_schema_baseline as baseline, server_update_setup as updater, server_playerbots_setup as playerbots
from runtime import provision_local_account as account, provision_local_realm as realm, server_config as config
from runtime.owned_process_group import OwnedGroup

SCOPE = 'disposable-native-arm64-owned-installation-finish-and-stop'
COMPLETE_SCOPE = 'owned-server-installation-four-schemas-cleanly-stopped'
ROOT = Path(__file__).resolve().parents[1]
_ORIGINAL_OWNER = OwnedGroup
require = files.require
PRIVATE_FILES = (schema.JOURNAL, updater.JOURNAL, playerbots.JOURNAL, account.JOURNAL,
    installation.STAGED_REPORT, installation.FINISH_JOURNAL, 'database-bootstrap.json',
    'accounts/database-secret', 'accounts/database-root-secret')
JOURNAL_FIELDS = dict(sourceBaselineJournal=schema.JOURNAL, compiledUpdaterJournal=updater.JOURNAL,
    playerbotsSchemaJournal=playerbots.JOURNAL, localAccountJournal=account.JOURNAL,
    stagedInstallationReceipt=installation.STAGED_REPORT, playerbotsFinishJournal=installation.FINISH_JOURNAL)


def public_record(value):
    if isinstance(value, dict):
        return {key: public_record(item) for key, item in value.items()
                if key not in ('configGeneration', 'stagedConfigGeneration', 'finalConfigGeneration',
                               'localAccountJournal', 'accountJournal', 'credentials')}
    if isinstance(value, list): return [public_record(item) for item in value]
    return value


def worker_command(state, session, mysql, mysqld, version, operation):
    return [sys.executable, '-B', '-s', '-E', str(Path(__file__).resolve()), '--service-worker',
        '--state', str(state), '--session', str(session), '--mysql', str(mysql), '--mysqld', str(mysqld),
        '--expected-version', version, '--operation-id', operation]


def stopped_document(value, operation, version, uuid):
    require(type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
            value.get('scope') == 'owned-local-mysql-stopped' and value.get('operationId') == operation and
            value.get('version') == version and value.get('uuid') == uuid and value.get('stopReason') == 'command' and
            all(value.get(name) is True for name in ('engineStarted', 'readyBeforeStop', 'cleanEngineExit')) and
            all(value.get(name) is False for name in ('dataRemoved', 'characterPersistenceQualified', 'gameplayQualified')),
            'Actual production owned service clean-stop acknowledgment differs')


def public_service_receipt(session, name, value):
    require(name in ('ready.json', 'stopped.json') and schema.private_journal(session / name) == value,
            'Production service receipt changed before public projection')
    fields = ('formatVersion', 'scope', 'operationId', 'version', 'uuid') + (
        ('bindAddress', 'port', 'liveSqlAuthenticated', 'ownedEngineIdentityVerified',
         'applicationSchemaUpdatesQualified', 'gameplayQualified') if name == 'ready.json' else
        ('stopReason', 'engineStarted', 'readyBeforeStop', 'cleanEngineExit', 'dataRemoved',
         'characterPersistenceQualified', 'gameplayQualified'))
    return dict({field: value[field] for field in fields}, receiptIdentity=baseline.file_identity(session / name))


class ServiceProcess:
    """Own the production service worker and its entire inherited process group."""
    def __init__(self, state, sessions, mysql, mysqld, version):
        self.state, self.version = state, version
        self.operation = secrets.token_hex(16); self.session = sessions / self.operation
        self.session.mkdir(mode=0o700)
        self.group = self.process = None; self.ready = None
        log = state / 'logs' / ('service-' + self.operation + '-private.log')
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            process = subprocess.Popen(worker_command(state, self.session, mysql, mysqld, version, self.operation),
                stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT, start_new_session=True, umask=0o077,
                env=dict(PATH='/usr/bin:/bin', LANG='C.UTF-8', LC_ALL='C.UTF-8', MYSQL_TEST_LOGIN_FILE=os.devnull))
        self.process = process
        try:
            self.group = OwnedGroup(process)
        except BaseException:
            # A construction failure may clean up only after the original
            # owner independently validates this still-unreaped group leader.
            try: _ORIGINAL_OWNER(process).stop(graceful_timeout=0)
            finally: process.stdin.close()
            raise

    def wait_ready(self, uuid, timeout=100):
        deadline = time.monotonic() + timeout
        while True:
            require(self.group.observe() is None, 'Production service exited before readiness')
            if os.path.lexists(self.session / 'ready.json'):
                ready = schema.private_journal(self.session / 'ready.json')
                require(type(ready.get('formatVersion')) is int and ready['formatVersion'] == 1 and
                        ready.get('scope') == 'owned-local-mysql-live-service' and ready.get('operationId') == self.operation and
                        ready.get('version') == self.version and ready.get('uuid') == uuid and
                        ready.get('datadir') == str(self.state / 'database') and ready.get('bindAddress') == '127.0.0.1' and
                        type(ready.get('port')) is int and ready['port'] == db.PORT and
                        ready.get('databases') == list(db.DATABASES) and ready.get('liveSqlAuthenticated') is True and
                        ready.get('ownedEngineIdentityVerified') is True and
                        ready.get('applicationSchemaUpdatesQualified') is False and ready.get('gameplayQualified') is False,
                        'Production service ready acknowledgment differs')
                self.ready = ready
                return ready
            require(time.monotonic() < deadline, 'Production service readiness timed out')
            time.sleep(.05)

    def verify(self, connection, uuid):
        require(self.ready is not None and self.group.observe() is None, 'Retained production service is unavailable')
        adapter.live_service(connection, self.state, self.session, self.version, self.operation, uuid)
        require(self.group.observe() is None, 'Production service exited during live verification')
        return True

    def stop(self, uuid, timeout=30):
        require(self.ready is not None and self.group.observe() is None, 'Ready owned service required before normal shutdown')
        try:
            self.process.stdin.write(b'shutdown\n'); self.process.stdin.flush()
            status = self.group.wait(timeout)
            reaped, forced = self.group.stop(graceful_timeout=0)
            require(status == reaped == 0 and forced is False, 'Production service did not exit cleanly')
            value = schema.private_journal(self.session / 'stopped.json')
            stopped_document(value, self.operation, self.version, uuid)
            return value
        finally:
            if self.group.closed: self.process.stdin.close()

    def close(self):
        try:
            if self.group is not None and not self.group.closed: self.group.stop(graceful_timeout=25)
        finally:
            if self.process is not None: self.process.stdin.close()


def worker(state, session, mysql, mysqld, version, operation, control_fd):
    stopped = [False]
    for number in (signal.SIGINT, signal.SIGTERM): signal.signal(number, lambda *_: stopped.__setitem__(0, True))
    try:
        value = service.serve(state, session, mysql, mysqld, version, operation, control_fd, lambda: stopped[0])
        return 0 if value.get('stopReason') == 'command' else 1
    except Exception as error:
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind): kind = 'Exception'
        print('Owned native service failed (' + kind + '); private diagnostics retained', file=sys.stderr)
        return 1


def private_identities(state):
    return {name: baseline.file_identity(state / name) for name in PRIVATE_FILES}


def _complete_fields(value, helper, version, uuid, operation):
    require(type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
            value.get('scope') == COMPLETE_SCOPE and value.get('mysqlUuid') == uuid and value.get('mysqlVersion') == version and
            value.get('serviceOperationId') == operation and value.get('pendingComponents') == [],
            'Bound native SQL completion receipt differs')
    require(all(value.get(name) is True for name in ('baselineComplete', 'compiledUpdaterCompleted', 'sourceLedgersVerified',
                'sameRevisionReentryVerified', 'localRealmVerified', 'localAccountVerified', 'ownedServiceIdentityVerified',
                'fourSchemasVerified', 'playerbotsSchemaVerified', 'engineStopped', 'cleanEngineStopped',
                'databaseServiceStopped', 'completeSetupQualified')) and
            all(value.get(name) is False for name in ('slotPromoted', 'databaseServiceStarted', 'authserverExecuted',
                'worldserverExecuted', 'serverDataQualified', 'playerbotsAiQualified', 'botCharactersCreated',
                'androidRuntimeQualified', 'gameplayQualified')), 'Unexpected native SQL completion qualification scope')
    for name in ('helperExecutable', 'helperBuildReceipt', 'helperNativeReceipt'):
        require(value.get(name) == helper[name], 'Native SQL completion helper selection differs')


def _complete_files(state, session, value, version, uuid, operation):
    for field, name in JOURNAL_FIELDS.items():
        schema.private_journal(state / name)
        require(value.get(field) == baseline.file_identity(state / name), 'Native SQL completion private journal differs')
    require(value.get('fourSchemaReceipt') == baseline.file_identity(state / installation.VERIFIED_REPORT) and
            value.get('stoppedReceipt') == baseline.file_identity(session / 'stopped.json'),
            'Native SQL completion verification/stop receipt binding differs')
    stopped_document(schema.private_journal(session / 'stopped.json'), operation, version, uuid)


def validate_complete(state, session, expected, helper, version, uuid, operation):
    """Check one private SQL-only completion against the real stopped ack/files."""
    value = schema.private_journal(state / 'server-setup-complete.json')
    require(value == expected, 'Bound native SQL completion receipt changed')
    _complete_fields(value, helper, version, uuid, operation)
    _complete_files(state, session, value, version, uuid, operation)
    return value


def complete_sql_receipt(state, session, verified, helper, version, uuid, operation):
    require(schema.private_journal(state / installation.VERIFIED_REPORT) == verified and
            verified.get('scope') == installation.VERIFIED_SCOPE and verified.get('mysqlUuid') == uuid and
            verified.get('mysqlVersion') == version and verified.get('engineStopped') is False and
            verified.get('completeSetupQualified') is False and verified.get('compiledPlayerbotsLoaderExecuted') is False,
            'Fresh live four-schema receipt required immediately before clean shutdown')
    stopped_document(schema.private_journal(session / 'stopped.json'), operation, version, uuid)
    path = state / 'server-setup-complete.json'
    require(not os.path.lexists(path), 'Existing native SQL completion preserved')
    complete = dict(copy.deepcopy(verified), scope=COMPLETE_SCOPE, completeSetupQualified=True, engineStopped=True,
        cleanEngineStopped=True, databaseServiceStopped=True, pendingComponents=[], serviceOperationId=operation,
        fourSchemaReceipt=baseline.file_identity(state / installation.VERIFIED_REPORT),
        stoppedReceipt=baseline.file_identity(session / 'stopped.json'))
    _complete_fields(complete, helper, version, uuid, operation)
    _complete_files(state, session, complete, version, uuid, operation)
    db.atomic_json(path, complete)
    return validate_complete(state, session, complete, helper, version, uuid, operation)


def run(prepared, mysql, mysqld, version, output):
    db.exact_version(version)
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'Native installation finish qualification requires Linux ARM64')
    require(all(isinstance(path, Path) and path.is_absolute() for path in (prepared, mysql, mysqld, output)),
            'Explicit absolute native installation paths required')
    output = db.private_path(output)
    require(not os.path.lexists(output), 'Existing native installation fixture preserved')
    output.mkdir(mode=0o700, parents=True)
    state = output / 'state'; state.mkdir(mode=0o700)
    sessions = output / 'mysql-sessions'; sessions.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope=SCOPE, phase='verify-inputs', mysqlVersion=version,
        qualificationSucceeded=False, initializedNewInstance=False, productionCoreCompositionCompleted=False,
        productionFinishPlayerbotsExecuted=False, nestedDataDirectoryConfigurationVerified=False,
        completedFinishReentryWithoutExecution=False, restartPersistenceVerified=False,
        restartedFinishReentryWithoutExecution=False, productionReadyAndStoppedAcknowledgmentsVerified=False,
        sourcePrivateJournalsAccountCredentialsPreserved=False, nativeSqlSetupReceiptVerified=False,
        cleanShutdownVerified=False, compilerExecuted=False, javaCoordinatorExecuted=False,
        completeSetupQualified=False, slotPromoted=False, existingStateModified=False,
        authserverExecuted=False, worldserverExecuted=False, serverDataQualified=False,
        playerbotsAiQualified=False, botCharactersCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
    owned = None
    try:
        pin, pin_identity, original = inputs.load_pin()
        candidate_root = prepared / 'candidate'
        candidate_proof = candidate.verify(candidate_root, pin['members']['candidate/candidate-pin.json']['sha256'])
        require(candidate_proof['helper']['executable'] == original['executable'] and
                candidate_proof['helper']['buildReceipt'] == original['helperBuildReceipt'] and
                candidate_proof['helper']['nativeSqlReceipt'] == original['nativeSqlReceipt'], 'Measured helper selection differs')
        runtime = prepared / 'runtime-inputs'; transfer = runtime / 'transfer'
        install, content, lock_path = runtime / 'install', transfer / 'engine-inputs/content', transfer / 'engine-inputs/locked/sources.lock.json'
        receipt, manifest, compiled = importer.unpack_content(content, inputs.runtime.CONTENT_RECEIPT['sha256'], lock_path, output / 'content')
        build, template, programs, derivative = importer.select_install(install, compiled, lock_path,
            transfer / 'server-engine-package/package-receipt.json')
        rows = [row for row in build['files'] if row['path'] == template.relative_to(install).as_posix()]
        require(len(rows) == 1, 'Exact original updater template required')
        verified = importer.verify_runtime_content(output / 'content', content, inputs.runtime.CONTENT_RECEIPT['sha256'], lock_path, manifest, compiled)
        helper_root = candidate_root / 'runtime'
        helper = helper_root / candidate.HELPER
        helper_pins = dict(helperExecutable=original['executable'], helperBuildReceipt=original['helperBuildReceipt'],
                           helperNativeReceipt=original['nativeSqlReceipt'])
        arguments = dict(helper=helper, helper_identity=helper_pins['helperExecutable'],
            helper_receipt=helper_root / candidate.BUILD, helper_receipt_identity=helper_pins['helperBuildReceipt'],
            native_receipt=helper_root / candidate.NATIVE, native_receipt_identity=helper_pins['helperNativeReceipt'],
            mysql=mysql, profile=json.loads((ROOT / 'config/local-server.json').read_bytes()))
        evidence.update(inputLock=pin_identity, registeredCandidate=dict(producer=pin['producer'], artifact=pin['artifact'],
                candidatePin=pin['members']['candidate/candidate-pin.json']), source=receipt['source'],
            sourceLockSha256=receipt['sourceLockSha256'], contentReceipt=verified.identities['receipt'],
            compiledModules=receipt['compiledModules'], originalBuild=verified.compiled['serverBuild'],
            engineDerivative=derivative, **helper_pins)
        # No game assets are fabricated: these are explicit configuration paths.
        data = output / 'unavailable-game-data'; final_data = data / 'data'
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        evidence['phase'] = 'initialize-owned-mysql'
        with db.state_lock(state): db.initialize(mysqld, mysql, state, version)
        bootstrap = db.read_receipt(state / 'database-bootstrap.json', version); uuid = bootstrap['uuid']
        evidence.update(initializedNewInstance=True, mysqlUuid=uuid)
        owned = ServiceProcess(state, sessions, mysql, mysqld, version); owned.wait_ready(uuid)
        evidence['firstReadyReceipt'] = public_service_receipt(owned.session, 'ready.json', owned.ready)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection, db.state_lock(state) as lease:
            live = lambda: owned.verify(connection, uuid)
            evidence['phase'] = 'production-core-composition'
            staged = installation.compose(verified, connection, state, version, program=install / 'bin/dbimport',
                program_identity=programs['dbimport'], template=template,
                template_identity={key: rows[0][key] for key in ('bytes', 'sha256')},
                original_build_identity=verified.compiled['serverBuild'], mysql=mysql, data=data, profile=arguments['profile'],
                apply_sql=lambda name, sql: base.apply_base(mysql, options, 'acore_' + name, sql, state / 'logs/sql-private.log'),
                verify_service=live, expected_uuid=uuid, state_lease=lease)
            require(staged['scope'] == installation.SCOPE and staged['playerbotsSchemaVerified'] is False,
                    'Initial composition must remain pending playerbots')
            stock_sql = updater.stock_world_sql_snapshot(connection)
            update_journal = schema.private_journal(state / updater.JOURNAL)
            require(update_journal.get('binding', {}).get('contentProfile') == config.CONTENT_PROFILE and
                    update_journal['binding'].get('sqlSelectionPolicy') == updater.STOCK_SQL_POLICY and
                    update_journal.get('stockWorldSql') == stock_sql,
                    'Actual completed stock SQL policy or live content closure differs')
            selected_world = updater._stock_selection(verified)['world']
            evidence.update(contentProfile=config.CONTENT_PROFILE, stockWorldSql=stock_sql,
                sqlSelectionPolicy=updater.STOCK_SQL_POLICY,
                selectedWorldUpdateCount=len(selected_world),
                excludedCustomWorldUpdateCount=len(verified.manifest['databases']['world']['updateOrder']) - len(selected_world),
                selectedSourcePathsSha256=update_journal['binding']['selectedSourcePathsSha256'])
            evidence.update(productionCoreCompositionCompleted=True, productionCoreComposition=staged)
            immutable = {name: baseline.file_identity(state / name) for name in
                (schema.JOURNAL, updater.JOURNAL, account.JOURNAL, installation.STAGED_REPORT,
                 'accounts/database-secret', 'accounts/database-root-secret')}
            core_rows = playerbots.preserved_core(connection)
            finish_args = dict(arguments, data=final_data, staged_data=data, expected_uuid=uuid,
                               verify_service=live, state_lease=lease)
            evidence['phase'] = 'production-installation-finish'
            first = installation.finish_playerbots(verified, connection, state, version, **finish_args)
            require(first['compiledPlayerbotsLoaderExecuted'] is True and first['fourSchemasVerified'] is True and
                    first['playerbotsSchemaVerified'] is True and first['configGeneration'] != staged['configGeneration'],
                    'Actual fresh installation finish or nested configuration transition missing')
            generation = realm.active_config_verified(verified, state, password, profile=arguments['profile'], data=final_data, mysql=mysql)
            world = realm.generation_files(state / 'config/generations' / generation)['worldserver.conf']
            require(realm.settings(world, ('DataDir',)) == {'DataDir': config.quoted(final_data)},
                    'Final complete configuration must select the nested data directory')
            evidence.update(productionFinishPlayerbotsExecuted=True, nestedDataDirectoryConfigurationVerified=True,
                            playerbotsFirstFinish=first)
            stable = private_identities(state)
            require(all(stable[name] == row for name, row in immutable.items()) and
                    playerbots.preserved_core(connection) == core_rows, 'Finish changed original private/core/account state')
            evidence['phase'] = 'completed-installation-finish-reentry'
            repeated = installation.finish_playerbots(verified, connection, state, version, **finish_args)
            require(repeated['compiledPlayerbotsLoaderExecuted'] is False and repeated['compiledUpdaterExecuted'] is False and
                    repeated['playerbotsDatabaseSnapshot'] == first['playerbotsDatabaseSnapshot'] and
                    private_identities(state) == stable and playerbots.preserved_core(connection) == core_rows,
                    'Completed finish reentry replayed or changed private state')
            evidence.update(completedFinishReentryWithoutExecution=True, completedFinishReentry=repeated)
        evidence['phase'] = 'production-first-clean-stop'
        stopped = owned.stop(uuid)
        evidence['firstStoppedReceipt'] = public_service_receipt(owned.session, 'stopped.json', stopped); owned = None
        owned = ServiceProcess(state, sessions, mysql, mysqld, version); owned.wait_ready(uuid)
        evidence['restartedReadyReceipt'] = public_service_receipt(owned.session, 'ready.json', owned.ready)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection, db.state_lock(state) as lease:
            live = lambda: owned.verify(connection, uuid)
            evidence['phase'] = 'restart-completed-installation-verification'
            require(private_identities(state) == stable and playerbots.preserved_core(connection) == core_rows,
                    'Production restart changed private journals/account/credentials/core rows')
            final = installation.finish_playerbots(verified, connection, state, version,
                **dict(arguments, data=final_data, staged_data=data, expected_uuid=uuid, verify_service=live, state_lease=lease))
            require(final['compiledPlayerbotsLoaderExecuted'] is False and final['compiledUpdaterExecuted'] is False and
                    final['playerbotsDatabaseSnapshot'] == first['playerbotsDatabaseSnapshot'] and
                    final['databaseSnapshots'] == first['databaseSnapshots'] and
                    private_identities(state) == stable and playerbots.preserved_core(connection) == core_rows,
                    'Restarted completion differs or replayed execution')
            evidence.update(restartPersistenceVerified=True, restartedFinishReentryWithoutExecution=True,
                            restartedFinishReentry=final)
        evidence['phase'] = 'production-final-clean-stop'
        final_session, final_operation = owned.session, owned.operation
        stopped = owned.stop(uuid)
        evidence['finalStoppedReceipt'] = public_service_receipt(owned.session, 'stopped.json', stopped); owned = None
        require(private_identities(state) == stable, 'Clean production stop changed private setup bindings')
        evidence['phase'] = 'bound-sql-setup-receipt'
        complete = complete_sql_receipt(state, final_session, final, helper_pins, version, uuid, final_operation)
        require(private_identities(state) == stable, 'Completion receipt changed original private setup state')
        evidence.update(nativeSqlSetupReceiptVerified=True, nativeSqlSetupReceipt=complete,
            nativeSqlSetupReceiptIdentity=baseline.file_identity(state / 'server-setup-complete.json'),
            productionReadyAndStoppedAcknowledgmentsVerified=True, sourcePrivateJournalsAccountCredentialsPreserved=True,
            cleanShutdownVerified=True, qualificationSucceeded=True, phase='complete')
        return public_record(evidence)
    except BaseException as error:
        evidence.update(qualificationSucceeded=False, failurePhase=evidence['phase'], failureClass=type(error).__name__, phase='failed')
        raise
    finally:
        try:
            if owned is not None:
                try: owned.close()
                except BaseException as error:
                    evidence.update(qualificationSucceeded=False, cleanupFailureClass=type(error).__name__)
                    raise
        finally: db.atomic_json(output / 'qualification.json', public_record(evidence))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--service-worker', action='store_true')
    for name in ('prepared', 'output', 'state', 'session', 'mysql', 'mysqld'): parser.add_argument('--' + name, type=Path)
    parser.add_argument('--expected-version', required=True); parser.add_argument('--operation-id')
    args = parser.parse_args()
    if args.service_worker:
        require(args.state is not None and args.session is not None and args.mysql is not None and args.mysqld is not None and
                isinstance(args.operation_id, str) and re.fullmatch('[a-f0-9]{32}', args.operation_id), 'Invalid owned service worker selection')
        return worker(args.state, args.session, args.mysql, args.mysqld, args.expected_version, args.operation_id, sys.stdin.fileno())
    require(args.prepared is not None and args.output is not None and args.mysql is not None and args.mysqld is not None,
            'Explicit prepared native installation inputs required')
    print(json.dumps(run(args.prepared, args.mysql, args.mysqld, args.expected_version, args.output), sort_keys=True))
    return 0


if __name__ == '__main__': raise SystemExit(main())
