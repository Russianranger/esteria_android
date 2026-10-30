#!/usr/bin/env python3
"""Qualify four-database logical backup/restore in TWO NEW disposable instances.

Never accepts an existing application state or an imported SQL backup. The pinned
base harness is the sole source creator. Private SQL, credentials and state stay
in the fresh output tree; only qualification.json is suitable for publication.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import struct
import subprocess
import sys
import threading

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime import mysql_bootstrap as db
from runtime import android_database_setup as android_setup
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm
from tools import manifest_server_content as content
from tools import qualify_base_sql as base
from tools import qualify_local_account as account_fixture_tools
from tools.render_server_config import render

ROOT = Path(__file__).resolve().parents[1]
MAX_DUMP = 4 * 1024 ** 3
MAX_LOG = 64 * 1024
ENVIRONMENT = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'MYSQL_TEST_LOGIN_FILE': os.devnull}


def identity_file(path, maximum=MAX_DUMP):
    """Hash a bounded regular private input without following a link or FIFO."""
    path = db.private_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        content.require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and
                        0 < before.st_size <= maximum, 'invalid backup file type/size/ownership')
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            block = stream.read(min(65536, remaining))
            content.require(block, 'backup input truncated')
            remaining -= len(block)
            digest.update(block)
        after = os.fstat(stream.fileno())
        content.require(not stream.read(1) and
                        (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                        (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'backup input changed')
    return dict(bytes=before.st_size, sha256=digest.hexdigest())


def verify_tools(mysql, mysqld, mysqldump, version):
    raw = (ROOT / 'runtime/mysql-backup-tools.lock.json').read_bytes()
    pin = json.loads(raw)
    source_raw = (ROOT / 'runtime/server/sources.lock.json').read_bytes()
    source = json.loads(source_raw)
    content.require(pin['formatVersion'] == 1 and version == pin['mysqlVersion'] and
                    hashlib.sha256(source_raw).hexdigest() == pin['runtimeSourceLockSha256'] and
                    source['mysql']['expectedRuntimeVersion'] == version and
                    any(row['package'] == 'mysql-client-core-8.0' and row['sha256'] == pin['clientPackageSha256']
                        for row in source['mysql']['binaryPackages']), 'backup tool source pins differ')
    for name, path in [('mysql', mysql), ('mysqld', mysqld), ('mysqldump', mysqldump)]:
        selected = pin['images'][name]
        content.require(str(path) == selected['path'] and identity_file(path, 64 * 1024 ** 2) ==
                        {key: selected[key] for key in ('bytes', 'sha256')}, 'backup executable hash mismatch')
        with path.open('rb') as stream:
            header = stream.read(64)
        content.require(header[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H', header, 18)[0] == 183,
                        'backup tools must be the pinned ARM64 ELF')
    return dict(lockSha256=hashlib.sha256(raw).hexdigest(), images=pin['images'])


def run_private(command, incoming, outgoing, log, timeout=900):
    """Drain stderr with a bounded private tail; never print SQL on failure."""
    process = subprocess.Popen(base.bounded_file_command(command, MAX_DUMP), stdin=incoming,
                               stdout=outgoing, stderr=subprocess.PIPE, env=ENVIRONMENT, start_new_session=True)
    tail = bytearray()
    read_errors = []
    def drain():
        try:
            while block := process.stderr.read(8192):
                tail.extend(block)
                if len(tail) > MAX_LOG:
                    del tail[:-MAX_LOG]
        except OSError as error:
            read_errors.append(type(error).__name__)
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
        content.require(process.returncode == 0, 'private backup SQL process failed')
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        reader.join(timeout=5)
        content.require(not reader.is_alive(), 'private backup diagnostic pipe did not finish')
        process.stderr.close()
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(tail)
            stream.flush(); os.fsync(stream.fileno())
        content.require(not read_errors, 'private backup diagnostic read failed')


def socket_arguments(options, state):
    return ['--defaults-file=' + str(options), '--protocol=SOCKET',
            '--socket=' + str(state / 'run/mysql.sock'), '--connect-timeout=3']


def dump_arguments(executable, options, state):
    return [str(executable), *socket_arguments(options, state), '--single-transaction', '--quick',
            '--skip-lock-tables', '--no-tablespaces', '--set-gtid-purged=OFF', '--hex-blob',
            '--routines', '--events', '--triggers', '--default-character-set=utf8mb4',
            '--order-by-primary', '--skip-comments', '--skip-dump-date', '--skip-add-locks',
            '--skip-disable-keys', '--column-statistics=0', '--databases', *db.DATABASES]


@contextmanager
def owned_admin(mysql, state, version):
    password = db.read_secret(state / 'accounts/database-root-secret')
    receipt = db.read_receipt(state / 'database-bootstrap.json', version)
    with db.option_file(state, 'root', password) as options, db.Mysql(
            mysql, options, state / 'run/mysql.sock') as connection:
        db.check_receipt(receipt, db.identity(connection, version))
        content.require(connection.query('SELECT CURRENT_USER()') == ['root@localhost'],
                        'unexpected backup administrator')
        yield connection, options


def dump(mysql, mysqldump, state, version, target):
    content.require(not target.exists(), 'existing backup preserved')
    partial = target.with_name(target.name + '.partial')
    with owned_admin(mysql, state, version) as (connection, options):
        # The harness owns every writer. Retain the global read lock as well:
        # single-transaction alone does not protect nontransactional tables/DDL.
        connection.query('FLUSH TABLES WITH READ LOCK')
        try:
            descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as stream:
                run_private(dump_arguments(mysqldump, options, state), subprocess.DEVNULL, stream,
                            target.with_name(target.name + '.private-log'))
                stream.flush(); os.fsync(stream.fileno())
            result = identity_file(partial)
            # No replacement, including if another name appeared after checking.
            os.link(partial, target)
            partial.unlink()
            db.sync_directory(target.parent)
            return result
        finally:
            connection.query('UNLOCK TABLES')


def restore(mysql, state, version, backup, expected):
    content.require(identity_file(backup) == expected, 'backup digest mismatch before restore')
    with owned_admin(mysql, state, version) as (connection, options):
        # Check ALL schemas before executing any SQL. This is only a fresh target,
        # never an update, overwrite, or repair operation on existing game data.
        base.empty_databases(connection)
        with backup.open('rb') as stream:
            run_private([str(mysql), *socket_arguments(options, state), '--skip-reconnect',
                         '--binary-mode=1', '--local-infile=0', '--default-character-set=utf8mb4',
                         '--max-allowed-packet=1GB'], stream, subprocess.DEVNULL,
                        state / 'logs/restore.private-log')


def probe_snapshot(connection, intent):
    account.match_account(account.selected_account(connection, intent['username']), intent)
    probes = {name: connection.query('SELECT id,HEX(payload),HEX(note),nullable_value FROM `' + name +
                                    '`.`esteria_backup_probe` ORDER BY id') for name in db.DATABASES}
    trackers = connection.query('SELECT realmid,acctid,numchars FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
    tables = {name: connection.query('SHOW TABLES FROM `' + name + '`') for name in db.DATABASES}
    return dict(probes=probes, trackers=trackers, tables=tables)


def run(mysql, mysqld, mysqldump, fixture, expected, source_lock, output, version, *,
        account_fixture, account_fixture_sha256):
    db.exact_version(version)
    output = db.private_path(output)
    content.require(not output.exists(), 'existing backup qualification preserved; use a fresh directory')
    tools = verify_tools(mysql, mysqld, mysqldump, version)
    output.mkdir(mode=0o700, parents=True)
    evidence = dict(formatVersion=1, scope='disposable-native-arm64-four-database-logical-backup',
        mysqlVersion=version, tools=tools, fixtureManifestSha256=expected,
        accountFixtureManifestSha256=account_fixture_sha256,
        accountSourceVerified=False, sourceConfigurationRendered=False, sourceAccountProvisioned=False,
        qualificationSucceeded=False, sourceBaseSqlQualified=False, fullDumpRestored=False,
        setupWrapperFreshAndRepeatQualified=False,
        canonicalDumpMatched=False, ownedCredentialRowsRestored=False, restartPersistenceVerified=False,
        existingStateModified=False, existingSaveRestoreQualified=False, applicationJournalRebindingQualified=False,
        schemaUpgradeQualified=False, gameCharacterSaveQualified=False, playerbotsRuntimeQualified=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    capture = None
    try:
        evidence['phase'] = 'verify-account-source-and-configuration-templates'
        verified_account_source = output / 'verified-account-source'
        account_manifest = account_fixture_tools.copy_fixture(
            account_fixture, account_fixture_sha256, source_lock, verified_account_source)
        evidence['accountSourceVerified'] = True
        evidence['phase'] = 'create-new-source-from-verified-bases'
        # Sole source creator: no option permits attaching this test to live data.
        source_result = base.run(mysql, mysqld, fixture, expected, source_lock, output / 'source', version)
        content.require(source_result['qualificationSucceeded'], 'base SQL qualification did not complete')
        evidence['sourceBaseSqlQualified'] = True
        evidence['source'] = source_result['source']
        evidence['sourceLockSha256'] = source_result['sourceLockSha256']
        content.require(account_manifest['source'] == source_result['source'] and
                        account_manifest['sourceLockSha256'] == source_result['sourceLockSha256'],
                        'account configuration and base SQL source identities differ')
        source = output / 'source/private-state'
        evidence['phase'] = 'render-source-configuration-with-existing-database-secret'
        secret_path = source / 'accounts/database-secret'
        existing_secret = secret_path.read_bytes()
        render(verified_account_source, source, output / 'unavailable-game-data',
               output / 'source/verified-source', mysql)
        content.require(secret_path.read_bytes() == existing_secret,
                        'configuration rendering changed existing database credentials')
        evidence['sourceConfigurationRendered'] = True
        evidence['phase'] = 'start-owned-source-database'
        capture = db.EngineCapture(base.engine_command(mysqld, source), source / 'logs/mysql-backup-engine.log')
        base.wait_owned(mysql, source, version, capture)
        evidence['phase'] = 'provision-source-local-realm'
        realm.provision(mysql, source, version)
        evidence['phase'] = 'provision-source-local-account'
        account.provision(mysql, source, version)
        evidence['sourceAccountProvisioned'] = True
        journal_bytes = (source / account.JOURNAL).read_bytes()
        original = db.read_receipt(source / 'database-bootstrap.json', version)
        intent = account.read_intent(source / account.JOURNAL, original)
        with owned_admin(mysql, source, version) as (connection, _):
            for name in db.DATABASES:
                connection.query('CREATE TABLE `' + name + '`.`esteria_backup_probe` '
                                 '(id INT PRIMARY KEY,payload VARBINARY(512),note VARCHAR(50),nullable_value INT NULL) '
                                 'ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci')
                connection.query('INSERT INTO `' + name + '`.`esteria_backup_probe` VALUES '
                                 "(1,UNHEX('000aff275c00ff'),CONVERT(UNHEX('d0add181d182d0b5d180d0b8d18ff09f8fa0') USING utf8mb4),NULL),"
                                 "(2,UNHEX(''),'',12340)")
            expected_rows = probe_snapshot(connection, intent)
        evidence['phase'] = 'dump-quiescent-source'
        backup = output / 'private-backup.sql'
        backup_identity = dump(mysql, mysqldump, source, version, backup)
        base.stop_owned(capture); capture = None
        evidence['phase'] = 'create-separate-empty-restore-instance'
        destination = output / 'restore-state'; destination.mkdir(mode=0o700)
        setup_report = android_setup.setup(destination, mysql, mysqld, version)
        preserved = {name: (destination / name).read_bytes() for name in (
            'accounts/database-secret', 'accounts/database-root-secret', 'database-bootstrap.json')}
        repeated = android_setup.setup(destination, mysql, mysqld, version)
        content.require(setup_report['operation'] == 'initialized' and repeated['operation'] == 'already-initialized' and
                        setup_report['uuid'] == repeated['uuid'] and
                        all((destination / name).read_bytes() == value for name, value in preserved.items()),
                        'setup wrapper repeat changed private credentials or instance')
        evidence['setupWrapperFreshAndRepeatQualified'] = True
        restored_receipt = db.read_receipt(destination / 'database-bootstrap.json', version)
        content.require(original['uuid'] != restored_receipt['uuid'] and original['datadir'] != restored_receipt['datadir'],
                        'restore must use a distinct new instance')
        capture = db.EngineCapture(base.engine_command(mysqld, destination), destination / 'logs/mysql-restore-engine.log')
        base.wait_owned(mysql, destination, version, capture)
        evidence['phase'] = 'restore-verified-private-dump'
        restore(mysql, destination, version, backup, backup_identity)
        evidence['fullDumpRestored'] = True
        with owned_admin(mysql, destination, version) as (connection, _):
            content.require(probe_snapshot(connection, intent) == expected_rows, 'restored account/tracker/probe/table mismatch')
        evidence['ownedCredentialRowsRestored'] = True
        evidence['phase'] = 'compare-complete-canonical-sql'
        content.require(dump(mysql, mysqldump, destination, version, output / 'private-restored.sql') == backup_identity,
                        'full logical SQL changed after restoration')
        evidence['canonicalDumpMatched'] = True
        evidence['phase'] = 'restart-restored-instance'
        base.stop_owned(capture); capture = None
        capture = db.EngineCapture(base.engine_command(mysqld, destination), destination / 'logs/mysql-restore-restart-engine.log')
        base.wait_owned(mysql, destination, version, capture)
        with owned_admin(mysql, destination, version) as (connection, _):
            content.require(probe_snapshot(connection, intent) == expected_rows, 'restored restart changed data')
        content.require(dump(mysql, mysqldump, destination, version, output / 'private-restarted.sql') == backup_identity,
                        'full logical SQL changed after restart')
        base.stop_owned(capture); capture = None
        evidence['phase'] = 'recheck-original-state-preservation'
        capture = db.EngineCapture(base.engine_command(mysqld, source), source / 'logs/mysql-backup-restart-engine.log')
        base.wait_owned(mysql, source, version, capture)
        account.provision(mysql, source, version, verify_only=True)
        with owned_admin(mysql, source, version) as (connection, _):
            content.require(probe_snapshot(connection, intent) == expected_rows and
                            (source / account.JOURNAL).read_bytes() == journal_bytes, 'source state changed during restore')
        base.stop_owned(capture); capture = None
        evidence.update(restartPersistenceVerified=True, qualificationSucceeded=True, phase='complete',
                        databaseCount=4, tableCounts={key: len(value) for key, value in expected_rows['tables'].items()},
                        privateDumpBytes=backup_identity['bytes'])
        # No dump/account hashes or rows are exported. Full SQL remains private.
        return evidence
    finally:
        if capture is not None:
            try:
                base.stop_owned(capture)
            except BaseException:
                evidence['qualificationSucceeded'] = False
        db.atomic_json(output / 'qualification.json', evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--fixture-sha256', required=True)
    parser.add_argument('--account-fixture', type=Path, required=True)
    parser.add_argument('--account-fixture-sha256', required=True)
    parser.add_argument('--mysql', type=Path, default=Path('/usr/bin/mysql'))
    parser.add_argument('--mysqld', type=Path, default=Path('/usr/sbin/mysqld'))
    parser.add_argument('--mysqldump', type=Path, default=Path('/usr/bin/mysqldump'))
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run(args.mysql, args.mysqld, args.mysqldump, args.fixture, args.fixture_sha256,
                     args.lock, args.output, args.expected_version,
                     account_fixture=args.account_fixture, account_fixture_sha256=args.account_fixture_sha256)
        print(json.dumps(result, indent=2))
        return 0
    except BaseException:
        print('Backup qualification failed; all SQL, credentials and state remain private', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
