#!/usr/bin/env python3
"""Exercise the production fourth-schema journal using a real native helper.

Always creates a new disposable SQL instance. Original content and core program
receipts stay unchanged; this is a separate source-built database-loader gate,
without playerbot AI, world startup, save adoption or Android qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_base_sql as base, qualify_dbimport as importer, verify_server_build as files
from runtime import mysql_bootstrap as db, server_schema_setup as schema, server_schema_baseline as baseline
from runtime import server_playerbots_setup as playerbots, server_update_setup as updater
from runtime import provision_local_realm as realm, provision_local_account as account, server_config as config
from runtime import android_server_installation_setup as installation

require = files.require
SCOPE = 'disposable-native-arm64-product-playerbots-schema'


def public_record(value):
    """Exclude credential-derived configuration digests from nested public proofs."""
    if isinstance(value, dict):
        return {key: public_record(item) for key, item in value.items() if key != 'configGeneration'}
    if isinstance(value, list): return [public_record(item) for item in value]
    return value


def probe(connection, token, *, create=False):
    require(re.fullmatch('[a-f0-9]{64}', token), 'Invalid disposable playerbots marker')
    if create:
        connection.query('CREATE TABLE `acore_playerbots`.`esteria_playerbots_probe` '
            '(id INT PRIMARY KEY, token BINARY(32) NOT NULL) ENGINE=InnoDB')
        connection.query("INSERT INTO `acore_playerbots`.`esteria_playerbots_probe` VALUES (1,UNHEX('" + token + "'))")
    require(connection.query('SELECT HEX(token) FROM `acore_playerbots`.`esteria_playerbots_probe` WHERE id=1') == [token.upper()],
            'Disposable playerbots persistence marker changed')


def identities(state):
    """Only file identities leave the fixture, never credential/account contents."""
    return {name: baseline.file_identity(state / name) for name in
        (schema.JOURNAL, updater.JOURNAL, playerbots.JOURNAL, account.JOURNAL, 'local-account.json',
         'realm-loopback.json', 'server-installation-staged.json',
         'accounts/database-secret', 'accounts/database-root-secret')}


def verify_product(verified, connection, state, version, mysql, data, profile, expected_uuid, service, lease):
    common = dict(profile=profile, data=data, mysql=mysql, expected_uuid=expected_uuid,
                  verify_service=service, state_lease=lease, verify_only=True)
    pb = playerbots.verify_completed(verified, connection, state, version,
                                    expected_uuid=expected_uuid, verify_service=service)
    core = updater.verify_completed_update(verified, connection, state, version,
                                          expected_uuid=expected_uuid, verify_service=service)
    local_realm = realm.provision_verified(verified, connection, state, version, **common)
    local_account = account.provision_verified(verified, connection, state, version, **common)
    require(core.get('playerbots') == pb and local_realm.get('operation') == 'verified' and
            local_account.get('operation') == 'verified-owned-account', 'Completed four-schema product verification failed')
    return dict(playerbots=pb, updater=core, realm=local_realm, account=local_account)


def run(install, content, content_receipt_sha256, lock_path, mysql, mysqld, version, output,
        helper, helper_receipt, helper_receipt_sha256, *, engine_derivative_receipt):
    db.exact_version(version)
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'Playerbots schema qualification requires native Linux ARM64')
    paths = (install, content, lock_path, mysql, mysqld, output, helper, helper_receipt, engine_derivative_receipt)
    require(all(isinstance(path, Path) and path.is_absolute() for path in paths), 'Absolute explicit playerbots gate inputs required')
    output = db.private_path(output)
    require(not os.path.lexists(output), 'Existing playerbots fixture preserved; choose a fresh output')
    output.mkdir(parents=True, mode=0o700)
    state = output / 'private-state'; state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope=SCOPE, mysqlVersion=version, phase='verify-inputs',
        qualificationSucceeded=False, initializedNewInstance=False, productionCoreCompositionCompleted=False,
        playerbotsDatabaseAndStatementsQualified=False, exactSourceUpdateLedgerVerified=False,
        completedJournalReentryWithoutExecution=False, actualLoaderReentryVerified=False,
        restartPersistenceVerified=False, fixtureProbeRemoved=False, finalFourSchemaProductVerification=False,
        coreSchemasLedgersCredentialsAccountPreserved=False, cleanShutdownVerified=False,
        playerbotsAiQualified=False, botCharactersCreated=False, authserverExecuted=False,
        worldserverExecuted=False, completeSetupQualified=False, slotPromoted=False,
        existingStateModified=False, schemaUpgradeQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    capture = None
    try:
        receipt, manifest, compiled = importer.unpack_content(content, content_receipt_sha256, lock_path, output / 'content')
        build, template, programs, derivative = importer.select_install(install, compiled, lock_path, engine_derivative_receipt)
        rows = [row for row in build['files'] if row['path'] == template.relative_to(install).as_posix()]
        require(len(rows) == 1, 'Original updater template identity absent')
        template_identity = {key: rows[0][key] for key in ('bytes', 'sha256')}
        verified = importer.verify_runtime_content(output / 'content', content, content_receipt_sha256,
                                                  lock_path, manifest, compiled)
        plan = playerbots.prepare(verified, helper, helper_receipt, helper_receipt_sha256, mysql)
        evidence.update(source=receipt['source'], sourceLockSha256=receipt['sourceLockSha256'],
            originalBuild=verified.compiled['serverBuild'], originalBuildId=build['buildId'],
            compiledModules=receipt['compiledModules'], contentReceipt=verified.identities['receipt'],
            helperBuildReceipt=plan.helper_receipt_identity, helperExecutable=plan.executable_identity,
            engineDerivative=derivative, selectedSourceBaseFiles=playerbots.BASE_COUNT,
            selectedSourceUpdates=playerbots.UPDATE_COUNT, preparedStatementCount=playerbots.STATEMENTS,
            packagedRuntimeContent=dict(files=len(verified.identities['files']),
                bytes=sum(row['bytes'] for row in verified.identities['files'].values()),
                allPackagedBytesReadBack=True, noGitRuntimeConsumer=True))
        profile = json.loads((Path(__file__).resolve().parents[1] / 'config/local-server.json').read_bytes())
        data = output / 'unavailable-game-data'
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state) as lease:
            evidence['phase'] = 'initialize-owned-mysql'
            db.initialize(mysqld, mysql, state, version)
            evidence['initializedNewInstance'] = True
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/playerbots-mysql-private.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                        'Another operation owns the fresh fixture')
                base.empty_databases(connection)
                bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
                uuid = bootstrap['uuid']; evidence['mysqlUuid'] = uuid
                def service():
                    require(capture is not None and capture.process.poll() is None, 'Owned fixture service exited')
                    db.check_receipt(bootstrap, db.identity(connection, version))
                evidence['phase'] = 'production-core-composition'
                staged = installation.compose(verified, connection, state, version,
                    program=install / 'bin/dbimport', program_identity=programs['dbimport'],
                    template=template, template_identity=template_identity,
                    original_build_identity=verified.compiled['serverBuild'], mysql=mysql, data=data, profile=profile,
                    apply_sql=lambda name, sql: base.apply_base(mysql, options, 'acore_' + name,
                                                               sql, state / 'logs/sql-client.log'),
                    verify_service=service, expected_uuid=uuid, state_lease=lease)
                require(staged.get('scope') == installation.SCOPE and staged.get('playerbotsSchemaVerified') is False and
                        staged.get('completeSetupQualified') is False and staged.get('mysqlUuid') == uuid,
                        'Core composition must remain explicitly pending fourth schema')
                evidence['productionCoreCompositionCompleted'] = True
                evidence['productionCoreComposition'] = dict(staged)
                # Configuration generation is credential-derived and stays private.
                evidence['productionCoreComposition'].pop('configGeneration', None)
                evidence['phase'] = 'production-playerbots-initialization'
                arguments = dict(profile=profile, data=data, expected_uuid=uuid, verify_service=service, state_lease=lease)
                first = playerbots.apply(plan, connection, state, version, **arguments)
                require(first.get('compiledPlayerbotsLoaderExecuted') is True, 'Fresh production helper did not execute')
                evidence['playerbotsFirst'] = first
                after_first, before_core = identities(state), playerbots.preserved_core(connection)
                before_pb = playerbots.snapshot(connection, plan.expected)
                repeated = playerbots.apply(plan, connection, state, version, **arguments)
                require(repeated.get('compiledPlayerbotsLoaderExecuted') is False and identities(state) == after_first,
                        'Completed production playerbots reentry replayed or changed a journal')
                evidence['playerbotsCompletedReentry'] = repeated
                evidence['completedJournalReentryWithoutExecution'] = True
                evidence['productBeforeNativeProbe'] = verify_product(verified, connection, state, version,
                    mysql, data, profile, uuid, service, lease)
                before_files = identities(state)
                require(all(before_files[name] == identity for name, identity in after_first.items()
                    if name not in ('local-account.json', 'realm-loopback.json')) and
                    playerbots.preserved_core(connection) == before_core,
                    'Product verification changed invariant journals, credentials or core rows')
                # An explicit disposable table proves actual storage persistence;
                # no product verifier runs until it has been removed again.
                evidence['phase'] = 'actual-loader-reentry-with-disposable-probe'
                token = hashlib.sha256((helper_receipt_sha256 + uuid).encode()).hexdigest()
                probe(connection, token, create=True)
                operation = state / 'run/native-playerbots-reentry'; operation.mkdir(mode=0o700)
                configuration, _ = playerbots.render_configuration(verified, state, mysql, data, profile, operation)
                updater._hash(helper, plan.executable_identity)
                evidence['actualLoaderReentry'] = playerbots.run_loader(helper, configuration, operation / 'helper-private.log')
                probe(connection, token)
                require(playerbots.preserved_core(connection) == before_core and identities(state) == before_files,
                        'Actual helper reentry changed private core or product files')
                evidence['actualLoaderReentryVerified'] = True
            base.stop_owned(capture); capture = None
            evidence['phase'] = 'restart-owned-mysql'
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/playerbots-mysql-restart-private.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                        'Another operation owns restarted fixture')
                probe(connection, token)
                require(playerbots.preserved_core(connection) == before_core and identities(state) == before_files,
                        'Clean restart changed core account/ledgers/credentials/journals')
                evidence['restartPersistenceVerified'] = True
                connection.query('DROP TABLE `acore_playerbots`.`esteria_playerbots_probe`')
                require(playerbots.snapshot(connection, plan.expected) == before_pb,
                        'Playerbots source schema differs after removing disposable probe')
                evidence['fixtureProbeRemoved'] = True
                evidence['phase'] = 'final-four-schema-product-verification'
                evidence['productAfterRestart'] = verify_product(verified, connection, state, version,
                    mysql, data, profile, uuid, service, lease)
                require(identities(state) == before_files and playerbots.preserved_core(connection) == before_core,
                        'Final product verification changed owned private state')
                evidence.update(finalFourSchemaProductVerification=True, exactSourceUpdateLedgerVerified=True,
                    coreSchemasLedgersCredentialsAccountPreserved=True, playerbotsDatabaseAndStatementsQualified=True,
                    databaseSnapshot=before_pb, productFileIdentities={name: row for name, row in before_files.items()
                        if not name.startswith('accounts/')})
            base.stop_owned(capture); capture = None
            evidence.update(cleanShutdownVerified=True, qualificationSucceeded=True, phase='complete')
        return public_record(evidence)
    except BaseException as error:
        evidence.update(qualificationSucceeded=False, failurePhase=evidence['phase'],
                        failureClass=type(error).__name__, phase='failed')
        raise
    finally:
        try:
            if capture is not None:
                try: base.stop_owned(capture)
                except BaseException as error:
                    evidence.update(qualificationSucceeded=False, cleanupFailureClass=type(error).__name__)
                    raise
        finally:
            # Only typed records are public; SQL/log/credential/account bytes stay private.
            db.atomic_json(output / 'qualification.json', public_record(evidence))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('install', 'content', 'lock', 'mysql', 'mysqld', 'output', 'helper', 'helper-receipt', 'engine-derivative-receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('content-receipt-sha256', 'helper-receipt-sha256', 'expected-version'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = run(args.install, args.content, args.content_receipt_sha256, args.lock, args.mysql, args.mysqld,
        args.expected_version, args.output, args.helper, args.helper_receipt, args.helper_receipt_sha256,
        engine_derivative_receipt=args.engine_derivative_receipt)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__': main()
