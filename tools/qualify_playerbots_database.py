#!/usr/bin/env python3
"""Qualify the real playerbots DatabaseLoader in a new disposable server fixture.

The existing compiled dbimport/auth harness is the sole creator of the instance.
This loads the fourth schema and real prepared statements, never playerbot AI.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_authserver as auth
from tools import qualify_dbimport as importer
from tools import qualify_base_sql as base
from tools import render_server_config as config
from tools import manifest_server_modules as modules
from tools import verify_server_build as files
from tools import verify_playerbots_reference as reference
from runtime import mysql_bootstrap as db
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm

require = base.content.require
MARKER = b'ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements='


def verify_reference(executable, receipt_path, expected_sha256, install, lock_path):
    require(executable.is_absolute() and receipt_path.is_absolute(), 'absolute reference/receipt paths required')
    receipt, identity = modules.read_json(receipt_path)
    pin, lock_hash = base.locked_source(lock_path)
    require(re.fullmatch('[a-f0-9]{64}', expected_sha256) and identity['sha256'] == expected_sha256,
            'reference receipt digest mismatch')
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'build-only-playerbots-database-reference' and
            receipt.get('source') == pin and receipt.get('sourceLockSha256') == lock_hash and
            receipt.get('actualDatabaseSourcesAndDefinitionVerified') is True and
            receipt.get('databaseExecuted') is False and receipt.get('elf', {}).get('machine') == 'AArch64',
            'reference build/source provenance mismatch')
    require(any(item['path'] == reference.PATH_PATCH for item in pin['patches']),
            'runtime module configuration adaptation is not pinned')
    require(files.identity(executable) == receipt['executable'] and
            files.identity(install / 'server-build.json') == receipt['serverBuild'],
            'reference executable or server build changed')
    require(set(receipt.get('referenceInputs', {})) == set(reference.INPUTS), 'reference source inventory differs')
    for path, expected in receipt['referenceInputs'].items():
        require(files.identity(reference.ROOT / path) == expected, 'reference source bytes differ from verified build')
    return receipt


def render_configuration(state, generation):
    source = state / 'config/generations' / generation
    target = state / 'run/playerbots-reference'
    target.mkdir(mode=0o700)
    (target / 'modules').mkdir(mode=0o700)
    world = config.overlay((source / 'worldserver.conf').read_text(), {
        'Updates.AutoSetup': 0, 'Updates.EnableDatabases': 7, 'Updates.Redundancy': 1,
        'Updates.AllowRehash': 1, 'Updates.ArchivedRedundancy': 0, 'Updates.CleanDeadRefMaxCount': 0,
        'Database.Reconnect.Attempts': 1, 'Database.Reconnect.Seconds': 1,
        'Logger.root': '4,Console'})
    bots = config.overlay((source / 'modules/playerbots.conf').read_text(), {
        'Playerbots.Updates.EnableDatabases': 1, 'PlayerbotsDatabase.WorkerThreads': 1,
        'PlayerbotsDatabase.SynchThreads': 1})
    config.write_private(target / 'worldserver.conf', world)
    config.write_private(target / 'modules/playerbots.conf', bots)
    return target / 'worldserver.conf'


def preserved_core(connection):
    # Private comparison only. Auth credentials/session values are never exported.
    result = {}
    for name in importer.DATABASES:
        result[name] = dict(tables=connection.query('SHOW TABLES FROM `acore_' + name + '`'),
            ledger=connection.query('SELECT * FROM `acore_' + name + '`.`updates` ORDER BY name'),
            probe=connection.query('SELECT * FROM `acore_' + name + '`.`esteria_dbimport_probe` ORDER BY id'))
    # mysql --batch --raw is line-based; binary SRP fields may contain invalid
    # UTF-8/newlines. Encode every audited account column for private comparison.
    columns = ','.join('HEX(`' + row[0] + '`)' for row in account.COLUMNS['account'])
    result['accounts'] = connection.query('SELECT ' + columns + ' FROM acore_auth.account ORDER BY id')
    result['trackers'] = connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
    result['realm'] = connection.query(realm.ROW_SQL)
    return result


def playerbots_snapshot(connection, expected):
    tables = connection.query('SHOW TABLES FROM acore_playerbots')
    require('updates' in tables and 'updates_include' in tables, 'playerbots updater ledger is absent')
    rows = connection.query('SELECT name,hash,state FROM acore_playerbots.updates ORDER BY name')
    ledger = {}
    for row in rows:
        parts = row.split('\t')
        require(len(parts) == 3 and parts[0] not in ledger, 'invalid/duplicate playerbots update ledger')
        ledger[parts[0]] = (parts[1].lower(), parts[2])
    # This selected source has no archived or external/custom updates. Requiring
    # equality also rejects unexpected SQL execution, not only missing updates.
    require(ledger == expected, 'playerbots ledger does not exactly match selected source SQL')
    return dict(tableCount=len(tables), tablesSha256=hashlib.sha256(base.canonical_identity(tables)).hexdigest(),
                updateCount=len(rows), ledgerSha256=hashlib.sha256(base.canonical_identity(rows)).hexdigest())


def run_reference(executable, configuration, log):
    result = importer.run_importer(executable, configuration, log)
    with files.plain_file(log) as stream:
        output = stream.read(importer.LOG_LIMIT + 1)
    require(len(output) <= importer.LOG_LIMIT, 'reference private diagnostic bound')
    matches = re.findall(re.escape(MARKER) + rb'([1-9][0-9]{0,3}) mysqlClientLibrary=([^\r\n ]+)\r?\n', output)
    require(len(matches) == 1, 'actual loader/prepared-statements completion marker missing')
    return dict(exitCode=result['exitCode'], preparedStatementCount=int(matches[0][0]))


def marker(connection, token, *, create=False):
    require(re.fullmatch('[a-f0-9]{64}', token), 'invalid disposable persistence marker')
    if create:
        connection.query('CREATE TABLE acore_playerbots.esteria_reference_probe '
                         '(id INT PRIMARY KEY, token CHAR(64) CHARACTER SET utf8mb4 '
                         'COLLATE utf8mb4_general_ci NOT NULL) ENGINE=InnoDB')
        connection.query("INSERT INTO acore_playerbots.esteria_reference_probe VALUES (1,'" + token + "')")
    require(connection.query('SELECT token FROM acore_playerbots.esteria_reference_probe WHERE id=1') == [token],
            'playerbots disposable persistence marker changed')


def run(install, content, content_sha256, lock_path, mysql, mysqld, version, output,
        executable, receipt_path, receipt_sha256):
    output = db.private_path(output)
    require(not output.exists(), 'existing fixture preserved; playerbots qualification requires a new instance')
    receipt = verify_reference(executable, receipt_path, receipt_sha256, install, lock_path)
    qualified_auth = auth.run(install, content, content_sha256, lock_path, mysql, mysqld, version, output)
    require(qualified_auth['qualificationSucceeded'], 'fresh compiled updater/auth qualification failed')
    evidence = dict(formatVersion=1, scope='disposable-native-arm64-playerbots-database-loader',
        referenceReceiptSha256=receipt_sha256, source=receipt['source'], sourceLockSha256=receipt['sourceLockSha256'],
        serverBuild=receipt['serverBuild'], authQualificationSha256=files.identity(output / 'auth-qualification.json')['sha256'],
        qualificationSucceeded=False, playerbotsDatabaseAndStatementsQualified=False,
        exactSourceUpdateLedgerVerified=False, sameRevisionReentryVerified=False, restartPersistenceVerified=False,
        coreTableSetsLedgersAccountsAndSessionPreserved=False, loopbackRealmReasserted=False,
        playerbotsAiQualified=False, botCharactersCreated=False, worldserverQualified=False,
        existingStateModified=False, schemaUpgradeQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    state = output / 'private-state'
    capture = None
    try:
        verify_reference(executable, receipt_path, receipt_sha256, install, lock_path)
        manifest, _ = modules.read_json(output / 'content/metadata/content-manifest.json')
        compiled, compiled_identity = modules.read_json(output / 'content/metadata/compiled-modules.json')
        require(compiled_identity == receipt['compiledModules'] and
                compiled['compileCommands'] == receipt['compileCommands'], 'reference build/module receipt mismatch')
        plan = manifest['databases']['playerbots']
        require(plan['executionOrderQualified'] is True and plan['updateOrder'] and
                all(row['state'] == 'RELEASED' for row in plan['updateOrder']), 'playerbots SQL plan requires new audit')
        expected = importer.expected_updates(output / 'content/source', manifest, 'playerbots')
        password = db.read_secret(state / 'accounts/database-secret')
        generation = realm.active_config(state, password)
        configuration = render_configuration(state, generation)
        journal_bytes = (state / account.JOURNAL).read_bytes()
        token = receipt_sha256
        evidence['phase'] = 'start-owned-mysql'
        capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/playerbots-mysql-private.log')
        base.wait_owned(mysql, state, version, capture)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            require(not connection.query('SHOW TABLES FROM acore_playerbots'), 'nonempty playerbots schema preserved')
            before = preserved_core(connection)
            evidence['phase'] = 'load-playerbots-bases-updates-and-statements'
            evidence['firstReference'] = run_reference(executable, configuration, state / 'logs/playerbots-first.private-log')
            playerbots_snapshot(connection, expected)
            evidence['playerbotsDatabaseAndStatementsQualified'] = True
            evidence['exactSourceUpdateLedgerVerified'] = True
            marker(connection, token, create=True)
            baseline = playerbots_snapshot(connection, expected)
            require(preserved_core(connection) == before, 'playerbots loader modified core schemas or account/session data')
            evidence['phase'] = 'same-revision-playerbots-reentry'
            evidence['secondReference'] = run_reference(executable, configuration, state / 'logs/playerbots-second.private-log')
            marker(connection, token)
            require(playerbots_snapshot(connection, expected) == baseline and preserved_core(connection) == before,
                    'playerbots reentry changed schema/ledger or core data')
            evidence['sameRevisionReentryVerified'] = True
        # Last updater in this database-only qualification. The actual world
        # startup will still need its own post-module loopback realm gate.
        realm.provision(mysql, state, version)
        evidence['loopbackRealmReasserted'] = True
        base.stop_owned(capture); capture = None
        evidence['phase'] = 'restart-and-verify-all-preservation-markers'
        capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/playerbots-restart-private.log')
        base.wait_owned(mysql, state, version, capture)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            marker(connection, token)
            require(playerbots_snapshot(connection, expected) == baseline and preserved_core(connection) == before,
                    'playerbots restart changed schema/ledger or core data')
        account.provision(mysql, state, version, verify_only=True)
        require((state / account.JOURNAL).read_bytes() == journal_bytes, 'owned account journal changed')
        base.stop_owned(capture); capture = None
        evidence.update(qualificationSucceeded=True, phase='complete', restartPersistenceVerified=True,
                        coreTableSetsLedgersAccountsAndSessionPreserved=True, databaseSnapshot=baseline)
        return evidence
    finally:
        if capture is not None:
            try:
                base.stop_owned(capture)
            except BaseException:
                evidence['qualificationSucceeded'] = False
        # SQL/log text remains private, including errors that may contain rows.
        db.atomic_json(output / 'playerbots-qualification.json', evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('install', 'content', 'mysql', 'mysqld', 'output', 'reference', 'reference-receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=base.content.ROOT / 'sources.lock.json')
    parser.add_argument('--content-receipt-sha256', required=True)
    parser.add_argument('--reference-receipt-sha256', required=True)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        result = run(args.install, args.content, args.content_receipt_sha256, args.lock, args.mysql, args.mysqld,
                     args.expected_version, args.output, args.reference, args.reference_receipt,
                     args.reference_receipt_sha256)
        print(json.dumps(result, indent=2)); return 0
    except BaseException:
        print('Playerbots database qualification failed; private fixture retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
