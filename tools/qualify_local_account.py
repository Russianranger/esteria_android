#!/usr/bin/env python3
"""Qualify owned local accounts in a NEW disposable MySQL instance, never saves.

Stages the pinned22 auth bases and three actual source configuration templates.
This tests account transactions/persistence/SRP verifiers, not network login,
module updates, world schemas, existing-save upgrades, or Android execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime import mysql_bootstrap as db
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm
from tools import qualify_base_sql as base
from tools import manifest_server_content as content
from tools import package_server_content as package
from tools.render_server_config import render

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('account account_access account_banned account_muted autobroadcast autobroadcast_locale build_info '
          'ip_banned logs logs_ip_actions motd motd_localized rbac_account_permissions rbac_default_permissions '
          'rbac_linked_permissions rbac_permissions realmcharacters realmlist secret_digest updates updates_include uptime').split()
SQL = ['data/sql/base/db_auth/' + name + '.sql' for name in TABLES]
TEMPLATES = ['src/server/apps/authserver/authserver.conf.dist', 'src/server/apps/worldserver/worldserver.conf.dist',
             'modules/mod-playerbots/conf/playerbots.conf.dist']
INPUTS = SQL + TEMPLATES
MAX_BYTES = 32 * 1024 ** 2


def prepare(server_path, lock_path, output, allow_fetch=False):
    output = db.private_path(output)
    content.require(not output.exists(), 'existing account fixture preserved; use a new directory')
    pin, lock_hash = base.locked_source(lock_path)
    source = content.GitObjects(server_path, pin['commit'], allow_fetch,
                               prefixes=('data/sql/base/db_auth', 'src/server/apps', 'modules/mod-playerbots/conf'))
    content.require(sorted(p for p in source.files if p.startswith('data/sql/base/db_auth/')) == sorted(SQL),
                    'pinned account base set changed')
    identities = source.identities(INPUTS, True)
    content.require(sum(row['bytes'] for row in identities.values()) <= MAX_BYTES, 'account fixture size bound')
    output.mkdir(parents=True, mode=0o700)
    reader = package.GitBatch(source)
    try:
        for path in INPUTS:
            target = output / 'source' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = reader.blob(identities[path])
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
            with os.fdopen(fd, 'wb') as destination:
                while stream.remaining:
                    destination.write(stream.read(min(content.CHUNK, stream.remaining)))
                destination.flush()
                os.fsync(destination.fileno())
            reader.finish_blob(stream)
    finally:
        reader.close()
    content.require(base.locked_source(lock_path) == (pin, lock_hash), 'source lock changed during staging')
    manifest = dict(formatVersion=1, scope='pinned-local-account-fixture', source=pin,
                    sourceLockSha256=lock_hash, files=identities)
    db.atomic_json(output / 'account-fixture.json', manifest)
    return hashlib.sha256((output / 'account-fixture.json').read_bytes()).hexdigest()


def copy_fixture(fixture, expected, lock_path, destination):
    fixture = db.private_path(fixture)
    manifest_path = db.private_path(fixture / 'account-fixture.json')
    metadata = manifest_path.stat()
    content.require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= 64 * 1024, 'account manifest size/type')
    raw = manifest_path.read_bytes()
    content.require(re.fullmatch('[0-9a-f]{64}', expected) and hashlib.sha256(raw).hexdigest() == expected,
                    'account fixture manifest digest mismatch')
    manifest = json.loads(raw)
    pin, lock_hash = base.locked_source(lock_path)
    content.require(manifest.get('formatVersion') == 1 and manifest.get('scope') == 'pinned-local-account-fixture' and
                    manifest.get('source') == pin and manifest.get('sourceLockSha256') == lock_hash and
                    set(manifest.get('files', {})) == set(INPUTS), 'account fixture provenance mismatch')
    rows = manifest['files']
    content.require(all(type(row.get('bytes')) is int and 0 <= row['bytes'] <= MAX_BYTES and
                        re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')) and
                        re.fullmatch('[0-9a-f]{40}', row.get('gitBlob', '')) for row in rows.values()) and
                    sum(row['bytes'] for row in rows.values()) <= MAX_BYTES, 'account fixture identity/size bound')
    for name, expected_hash in [('account', account.ACCOUNT_SCHEMA_SHA256), ('realmcharacters', account.TRACKER_SCHEMA_SHA256),
                                ('realmlist', realm.SCHEMA_SHA256)]:
        content.require(rows['data/sql/base/db_auth/' + name + '.sql']['sha256'] == expected_hash,
                        'account helper schema provenance differs')
    for path in INPUTS:
        row = rows[path]
        source = db.private_path(fixture / 'source' / path)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        sha = hashlib.sha256()
        blob = hashlib.sha1(('blob ' + str(row['bytes']) + '\0').encode())
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with os.fdopen(descriptor, 'rb') as incoming:
            observed = os.fstat(incoming.fileno())
            content.require(stat.S_ISREG(observed.st_mode) and observed.st_size == row['bytes'], 'account source type/size')
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
            with os.fdopen(fd, 'wb') as outgoing:
                remaining = row['bytes']
                while remaining:
                    block = incoming.read(min(content.CHUNK, remaining))
                    content.require(block, 'truncated account source')
                    remaining -= len(block)
                    sha.update(block); blob.update(block); outgoing.write(block)
                content.require(not incoming.read(1), 'account source grew')
                outgoing.flush(); os.fsync(outgoing.fileno())
        content.require(sha.hexdigest() == row['sha256'] and blob.hexdigest() == row['gitBlob'], 'account source hash mismatch')
    return manifest


def fail_expected(action, message):
    try:
        action()
    except db.BootstrapError:
        return
    raise ValueError(message)


def qualify_rows(mysql, state, version, connection):
    """Only called on this harness's freshly initialized disposable instance."""
    def invoke(verify=False):
        return account.provision(mysql, state, version, verify_only=verify)
    content.require(connection.query('SELECT COUNT(*) FROM acore_auth.account') == ['0'], 'auth fixture unexpectedly contains accounts')
    # Orphan privilege rows must never be inherited through numeric id reuse.
    connection.query('INSERT INTO acore_auth.account_access (id,gmlevel,RealmID) VALUES (1,3,-1)')
    fail_expected(invoke, 'new account inherited orphan administrative access')
    content.require(connection.query('SELECT COUNT(*) FROM acore_auth.account') == ['0'] and
                    connection.query('SELECT id,gmlevel,RealmID FROM acore_auth.account_access') == ['1\t3\t-1'],
                    'orphan rejection changed existing auth state')
    first = invoke()
    content.require(first['operation'] == 'created-owned-account', 'fresh account was not created')
    bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
    journal_path = state / account.JOURNAL
    completed = journal_path.read_bytes()
    journal = account.read_intent(journal_path, bootstrap)
    account_id = journal['accountId']
    rows = account.selected_account(connection, journal['username'])
    account.match_account(rows, journal)
    # This is an unrelated account/realm fixture, not a playerbot or character.
    connection.query("INSERT INTO acore_auth.account (username,salt,verifier) VALUES ('UNRELATED',UNHEX('" + '11' * 32 + "'),UNHEX('" + '22' * 32 + "'))")
    connection.query('UPDATE acore_auth.realmcharacters SET numchars=3 WHERE realmid=1 AND acctid=' + str(account_id))
    connection.query('INSERT INTO acore_auth.realmcharacters VALUES (2,' + str(account_id) + ',5)')
    snapshot = connection.query('SELECT id,username,HEX(salt),HEX(verifier),expansion,Flags FROM acore_auth.account ORDER BY id')
    trackers = connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
    content.require(invoke()['operation'] == 'verified-owned-account' and invoke(True)['operation'] == 'verified-owned-account',
                    'repeat account verification failed')
    content.require(journal_path.read_bytes() == completed, 'repeat changed persistent credentials')
    # Simulate the durable intent surviving an unknown successful COMMIT.
    db.atomic_json(journal_path, journal | {'phase': 'pending', 'accountId': None})
    content.require(invoke()['operation'] == 'recovered-owned-commit', 'interrupted committed account not recovered')
    content.require(journal_path.read_bytes() == completed, 'recovery changed original private credentials')
    # A second installation's private intent with a colliding name cannot adopt.
    collision = account.new_intent(bootstrap)
    collision['username'] = journal['username']
    collision['verifierHex'] = account.verifier(collision['username'], collision['password'], bytes.fromhex(collision['saltHex'])).hex()
    db.atomic_json(journal_path, collision)
    fail_expected(invoke, 'colliding account credentials were accepted')
    db.atomic_json(journal_path, journal)
    # Never repair a missing owned tracker. Roll back this test-only deletion.
    connection.query('DELETE FROM acore_auth.realmcharacters WHERE realmid=1 AND acctid=' + str(account_id))
    fail_expected(invoke, 'missing tracker was repaired')
    content.require(connection.query('SELECT COUNT(*) FROM acore_auth.realmcharacters WHERE realmid=1 AND acctid=' + str(account_id)) == ['0'],
                    'missing tracker was changed')
    connection.query('INSERT INTO acore_auth.realmcharacters VALUES (1,' + str(account_id) + ',3)')
    # Drift in schema must fail before account SQL modification.
    connection.query('ALTER TABLE acore_auth.account ADD account_qualification_drift INT')
    fail_expected(invoke, 'schema drift was accepted')
    connection.query('ALTER TABLE acore_auth.account DROP COLUMN account_qualification_drift')
    connection.query('ALTER TABLE acore_auth.account MODIFY username VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL DEFAULT \'\'')
    fail_expected(invoke, 'username column collation drift was accepted')
    connection.query('ALTER TABLE acore_auth.account MODIFY username VARCHAR(32) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT \'\'')
    connection.query('ALTER TABLE acore_auth.account DROP INDEX idx_username, ADD UNIQUE INDEX idx_username (username(16))')
    fail_expected(invoke, 'username prefix index drift was accepted')
    connection.query('ALTER TABLE acore_auth.account DROP INDEX idx_username, ADD UNIQUE INDEX idx_username (username)')
    content.require(connection.query('SELECT id,username,HEX(salt),HEX(verifier),expansion,Flags FROM acore_auth.account ORDER BY id') == snapshot,
                    'account state changed during repeat/recovery/failure tests')
    content.require(connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid') == trackers,
                    'character tracker state changed')
    content.require(connection.query('SELECT id,gmlevel,RealmID FROM acore_auth.account_access') == ['1\t3\t-1'],
                    'unrelated orphan permission row changed')
    return snapshot, trackers, completed


def run(mysql, mysqld, fixture, expected, lock_path, output, version):
    db.exact_version(version)
    content.require(mysql.is_absolute() and mysqld.is_absolute(), 'absolute MySQL binaries required')
    output = db.private_path(output)
    content.require(not output.exists(), 'existing qualification preserved; use a fresh directory')
    output.mkdir(mode=0o700, parents=True)
    state = output / 'private-state'; state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope='disposable-native-MySQL-owned-account', mysqlVersion=version,
        fixtureManifestSha256=expected, qualificationSucceeded=False, authBaseSqlLoaded=False,
        ownedAccountCreated=False, repeatPreservedCredentials=False, interruptedCommitRecovered=False,
        collisionAndSchemaDriftRejected=False, restartPersistenceVerified=False,
        compiledAuthserverExecuted=False, authProtocolQualified=False, moduleUpdatesApplied=False,
        existingSaveUpgradesQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    capture = None
    try:
        evidence['phase'] = 'verify-source-fixture'
        manifest = copy_fixture(fixture, expected, lock_path, output / 'verified-source')
        evidence['source'] = manifest['source']; evidence['sourceLockSha256'] = manifest['sourceLockSha256']
        evidence['phase'] = 'render-source-config-and-initialize'
        render(output / 'verified-source', state, output / 'data', output / 'verified-source', mysql)
        password = db.read_secret(state / 'accounts/database-secret')
        with db.state_lock(state):
            db.initialize(mysqld, mysql, state, version)
        capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-base-engine.log')
        base.wait_owned(mysql, state, version, capture)
        evidence['phase'] = 'load-empty-auth-bases'
        with db.state_lock(state), db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            base.empty_databases(connection)
            for path in SQL:
                base.apply_base(mysql, options, 'acore_auth', output / 'verified-source' / path, state / 'logs/sql-client.log')
            content.require(sorted(connection.query('SHOW TABLES FROM acore_auth')) == sorted(TABLES), 'unexpected auth base table set')
            evidence['authBaseSqlLoaded'] = True
        evidence['phase'] = 'provision-loopback-realm'
        realm.provision(mysql, state, version)
        evidence['phase'] = 'qualify-owned-account-transactions'
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            snapshot, trackers, journal = qualify_rows(mysql, state, version, connection)
        evidence.update(ownedAccountCreated=True, repeatPreservedCredentials=True, interruptedCommitRecovered=True,
                        collisionAndSchemaDriftRejected=True)
        evidence['phase'] = 'restart-and-verify-account-persistence'
        base.stop_owned(capture); capture = None
        capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-base-restart-engine.log')
        base.wait_owned(mysql, state, version, capture)
        account.provision(mysql, state, version, verify_only=True)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            content.require(connection.query('SELECT id,username,HEX(salt),HEX(verifier),expansion,Flags FROM acore_auth.account ORDER BY id') == snapshot and
                            connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid') == trackers and
                            (state / account.JOURNAL).read_bytes() == journal, 'account persistence changed after restart')
            for name in ('world', 'characters', 'playerbots'):
                content.require(not connection.query('SHOW TABLES FROM acore_' + name), 'account setup touched unrelated schema')
        evidence['restartPersistenceVerified'] = True
        base.stop_owned(capture); capture = None
        evidence['qualificationSucceeded'] = True
        evidence['phase'] = 'complete'
        return evidence
    finally:
        if capture is not None:
            try:
                base.stop_owned(capture)
            except BaseException:
                evidence['qualificationSucceeded'] = False
        # Account-bearing SQL stderr remains private even on error. Engine logs
        # never contain SQL statements; export only its bounded setup/restart tails.
        base.export_diagnostics(state, output, False)
        db.atomic_json(output / 'qualification.json', evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='operation', required=True)
    prepare_cmd = commands.add_parser('prepare')
    prepare_cmd.add_argument('--server', type=Path, required=True)
    prepare_cmd.add_argument('--allow-source-fetch', action='store_true')
    qualify = commands.add_parser('qualify')
    qualify.add_argument('--fixture', type=Path, required=True)
    qualify.add_argument('--fixture-sha256', required=True)
    qualify.add_argument('--mysql', type=Path, required=True)
    qualify.add_argument('--mysqld', type=Path, required=True)
    qualify.add_argument('--expected-version', required=True)
    for command in (prepare_cmd, qualify):
        command.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.server, args.lock, args.output, args.allow_source_fetch) if args.operation == 'prepare' else run(
            args.mysql, args.mysqld, args.fixture, args.fixture_sha256, args.lock, args.output, args.expected_version)
        print(json.dumps(result, indent=2))
        return 0
    except BaseException:
        print('Account qualification failed; private fixture retained and no credentials exported', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
