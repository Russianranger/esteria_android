#!/usr/bin/env python3
"""Qualify authentic base SQL in a NEW disposable, owned MySQL instance only.

This mirrors only DBUpdater::Populate's sorted, empty-database base phase.
It does not emulate update ledgers, apply module updates or qualify saved games.
Existing output directories are never adopted, retried, cleared or upgraded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from . import fetch_sources
    from . import manifest_server_content as content
    from . import package_server_content as package
except ImportError:
    import fetch_sources
    import manifest_server_content as content
    import package_server_content as package
from runtime import mysql_bootstrap as db

BASE_COUNTS = {'auth': 22, 'characters': 108, 'world': 309, 'playerbots': 29}
DB_ORDER = ('auth', 'characters', 'world', 'playerbots')
MAX_SQL_LOG = 64 * 1024
MAX_BASE_BYTES = 2 * 1024 ** 3
MAX_MANIFEST_BYTES = 1024 ** 2


def empty_databases(connection):
    for name in DB_ORDER:
        rows = connection.query('SHOW TABLES FROM `acore_' + name + '`')
        content.require(not rows, 'nonempty database preserved; base SQL must never be replayed: ' + name)


def load_bases(connection, plan, apply):
    empty_databases(connection)  # All four checked BEFORE the first SQL file.
    for name in DB_ORDER:
        content.require(not connection.query('SHOW TABLES FROM `acore_' + name + '`'),
                        'database changed before base phase; preserve fixture')
        for source in plan[name]:
            apply(name, source)


def source_plan(server):
    result = {}
    for name, (_, directory, _) in content.DATABASES.items():
        paths = sorted(path for path in server.files if path.startswith(directory + '/') and
                       '/' not in path[len(directory) + 1:] and path.endswith('.sql'))
        content.require(len(paths) == BASE_COUNTS[name], 'pinned base file set changed: ' + name)
        content.require(all(re.fullmatch(r'[A-Za-z0-9_]+', Path(path).stem) for path in paths),
                        'unsupported base table filename')
        result[name] = paths
    return result


def stage_sources(server, output):
    plan = source_plan(server)
    selected = [path for name in DB_ORDER for path in plan[name]]
    identities = server.identities(selected, True)
    content.require(sum(row['bytes'] for row in identities.values()) <= MAX_BASE_BYTES, 'base input size limit')
    reader = package.GitBatch(server)
    try:
        for path in selected:
            target = output / path
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = reader.blob(identities[path])
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
            with os.fdopen(fd, 'wb') as destination:
                while stream.remaining:
                    destination.write(stream.read(min(content.CHUNK, stream.remaining)))
                destination.flush()
                os.fsync(destination.fileno())
            reader.finish_blob(stream)
    finally:
        reader.close()
    return plan, identities


def locked_source(lock_path):
    lock_bytes = lock_path.read_bytes()
    lock = fetch_sources.load_lock(lock_path)
    pin = lock['sources']['server']
    content.require(pin['commit'] == content.SUPPORTED_SERVER, 'unreviewed server base SQL revision')
    content.validate_patch_contract(pin, lock_path.parent)
    return pin, hashlib.sha256(lock_bytes).hexdigest()


def prepare(server_path, lock_path, output, allow_fetch=False):
    """Host-only Git access; the engine image needs only these verified SQL bytes."""
    output = db.private_path(output)
    content.require(not output.exists(), 'existing SQL fixture preserved; use a new output directory')
    pin, lock_hash = locked_source(lock_path)
    output.mkdir(parents=True, mode=0o700)
    server = content.GitObjects(server_path, pin['commit'], allow_fetch,
        prefixes=('data/sql/base', 'modules/mod-playerbots/data/sql/playerbots/base'))
    plan, identities = stage_sources(server, output / 'source')
    content.require(locked_source(lock_path) == (pin, lock_hash), 'source lock changed during staging')
    manifest = dict(formatVersion=1, scope='pinned-base-SQL-fixture', source=pin,
                    sourceLockSha256=lock_hash, baseOrder=plan, baseSources=identities)
    db.atomic_json(output / 'base-fixture.json', manifest)
    return hashlib.sha256((output / 'base-fixture.json').read_bytes()).hexdigest()


def copy_fixture(fixture, expected_hash, lock_path, destination):
    """Verify every byte before starting MySQL, then use private staged copies."""
    fixture = db.private_path(fixture)
    manifest_path = db.private_path(fixture / 'base-fixture.json')
    metadata = manifest_path.stat()
    content.require(stat.S_ISREG(metadata.st_mode) and metadata.st_size <= MAX_MANIFEST_BYTES,
                    'base fixture manifest type/size limit')
    data = manifest_path.read_bytes()
    content.require(re.fullmatch('[0-9a-f]{64}', expected_hash) and
                    hashlib.sha256(data).hexdigest() == expected_hash, 'base fixture manifest digest mismatch')
    manifest = json.loads(data)
    pin, lock_hash = locked_source(lock_path)
    content.require(manifest.get('formatVersion') == 1 and manifest.get('scope') == 'pinned-base-SQL-fixture' and
                    manifest.get('source') == pin and manifest.get('sourceLockSha256') == lock_hash,
                    'base fixture source provenance mismatch')
    plan, identities = manifest['baseOrder'], manifest['baseSources']
    content.require(set(plan) == set(DB_ORDER), 'base fixture database set mismatch')
    content.require(isinstance(identities, dict), 'invalid base source identities')
    total = 0
    selected = []
    for name in DB_ORDER:
        directory = content.DATABASES[name][1]
        paths = plan[name]
        content.require(isinstance(paths, list) and len(paths) == BASE_COUNTS[name] and
                        paths == sorted(set(paths)), 'base fixture order/count mismatch: ' + name)
        for path in paths:
            content.require(isinstance(path, str) and path.startswith(directory + '/') and
                            re.fullmatch('[A-Za-z0-9_]+[.]sql', path[len(directory) + 1:]),
                            'unsafe base SQL fixture path')
            row = identities[path]
            content.require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= MAX_BASE_BYTES and
                            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')) and
                            re.fullmatch('[0-9a-f]{40}', row.get('gitBlob', '')), 'invalid base source identity')
            total += row['bytes']
            selected.append(path)
    content.require(total <= MAX_BASE_BYTES and set(selected) == set(identities), 'base source set/size mismatch')
    for path in selected:
        source = db.private_path(fixture / 'source' / path)
        row = identities[path]
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        blob_digest = hashlib.sha1(('blob ' + str(row['bytes']) + '\0').encode())
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            observed = os.fstat(stream.fileno())
            content.require(stat.S_ISREG(observed.st_mode) and observed.st_size == row['bytes'],
                            'base fixture file type/size mismatch: ' + path)
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
            remaining = row['bytes']
            with os.fdopen(fd, 'wb') as out:
                while remaining:
                    block = stream.read(min(content.CHUNK, remaining))
                    content.require(block, 'truncated base SQL source: ' + path)
                    remaining -= len(block)
                    digest.update(block)
                    blob_digest.update(block)
                    out.write(block)
                content.require(not stream.read(1), 'base SQL source grew during verification')
                out.flush()
                os.fsync(out.fileno())
            content.require(digest.hexdigest() == row['sha256'] and blob_digest.hexdigest() == row['gitBlob'],
                            'base SQL source hash mismatch: ' + path)
    return manifest


def bounded_output():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_SQL_LOG, MAX_SQL_LOG))


def apply_base(mysql, options, database, sql, log):
    command = [str(mysql), '--defaults-file=' + str(options), '--protocol=TCP', '--host=127.0.0.1',
               '--port=' + str(db.PORT), '--connect-timeout=3', '--skip-reconnect',
               '--default-character-set=utf8', '--max-allowed-packet=1GB', '--local-infile=0', database]
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'MYSQL_TEST_LOGIN_FILE': os.devnull}
    with sql.open('rb') as source, log.open('wb') as diagnostic:
        os.chmod(log, 0o600)
        result = subprocess.run(command, stdin=source, stdout=diagnostic, stderr=subprocess.STDOUT,
                                env=environment, timeout=300, preexec_fn=bounded_output)
    content.require(result.returncode == 0, 'base SQL client failed for ' + sql.name +
                    ' (exit ' + str(result.returncode) + '); private bounded SQL log retained')


def engine_command(mysqld, state):
    command = [str(mysqld), '--no-defaults', '--datadir=' + str(state / 'database'),
               '--port=' + str(db.PORT), '--bind-address=127.0.0.1', '--mysqlx=OFF',
               '--secure-file-priv=NULL', '--socket=' + str(state / 'run/mysql.sock'),
               '--pid-file=' + str(state / 'run/mysql.pid'), '--innodb-buffer-pool-size=128M',
               '--max-allowed-packet=1GB', '--performance-schema=OFF']
    if os.geteuid() == 0:
        command.append('--user=root')
    return command


def stop_owned(capture):
    process = capture.process
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.wait(timeout=5)
                raise ValueError('owned MySQL did not stop cleanly; fixture is preserved') from error
        content.require(process.returncode == 0, 'owned MySQL shutdown/startup failed; fixture is preserved')
    finally:
        capture.finish()


def wait_owned(mysql, state, version, capture):
    deadline = time.monotonic() + 90
    while True:
        content.require(capture.process.poll() is None, 'owned MySQL exited before authenticated readiness')
        try:
            db.verify(mysql, state, version)
            return
        except db.BootstrapError:
            content.require(time.monotonic() < deadline, 'owned MySQL did not become ready')
            time.sleep(.2)


def schema_tables(connection, plan):
    counts = {}
    for name in DB_ORDER:
        tables = connection.query('SHOW TABLES FROM `acore_' + name + '`')
        expected = sorted(Path(path).stem for path in plan[name])
        content.require(sorted(tables) == expected, 'base schema table set differs from source files: ' + name)
        counts[name] = len(tables)
    return counts


def export_diagnostics(state, output, failed):
    """Export only bounded engine logs and a redacted SQL failure, never state/options."""
    secrets = []
    for name in ('database-secret', 'database-root-secret'):
        path = state / 'accounts' / name
        if path.is_file():
            value = path.read_text().strip()
            if value:
                secrets.append(value)
    names = ('mysql-initialize-engine.log', 'mysql-bootstrap-engine.log',
             'mysql-base-engine.log', 'mysql-base-restart-engine.log')
    if failed:
        names += ('sql-client.log',)
    for name in names:
        log = state / 'logs' / name
        if log.is_file():
            with log.open('rb') as stream:
                text = stream.read(MAX_SQL_LOG).decode('utf-8', errors='replace')
            for secret in secrets:
                text = text.replace(secret, '[redacted]')
            target = output / ('sql-failure.txt' if name == 'sql-client.log' else name)
            target.write_text(text)
            os.chmod(target, 0o600)


def run(mysql, mysqld, fixture, fixture_hash, lock_path, output, version):
    db.exact_version(version)
    content.require(mysql.is_absolute() and mysqld.is_absolute(), 'absolute MySQL executable paths required')
    output = db.private_path(output)
    content.require(not output.exists(), 'existing fixture preserved; use a new output directory')
    pin, lock_hash = locked_source(lock_path)
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    state = output / 'private-state'
    state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope='disposable-host-MySQL-base-SQL-only', source=pin,
        sourceLockSha256=lock_hash, fixtureManifestSha256=fixture_hash, mysqlVersion=version,
        initializedNewInstance=False, baseSqlLoaded=False, restartPersistenceVerified=False,
        qualificationSucceeded=False,
        compiledUpdaterExecuted=False, moduleUpdatesApplied=False, playerbotsRuntimeQualified=False,
        databaseUpgradeQualified=False, existingStateModified=False, gameSchemasQualified=False,
        androidRuntimeQualified=False, gameplayQualified=False, completedFiles=[])
    capture = None
    try:
        prepared = copy_fixture(fixture, fixture_hash, lock_path, output / 'verified-source')
        plan, identities = prepared['baseOrder'], prepared['baseSources']
        evidence['baseSources'] = identities
        evidence['baseOrder'] = plan
        content.require(locked_source(lock_path) == (pin, lock_hash), 'source lock changed before fixture initialization')
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state):
            db.initialize(mysqld, mysql, state, version)
            evidence['initializedNewInstance'] = True
            capture = db.EngineCapture(engine_command(mysqld, state), state / 'logs/mysql-base-engine.log')
            wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                content.require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                                'fixture instance is owned by another operation')
                def apply(name, source):
                    evidence['activeFile'] = source
                    apply_base(mysql, options, 'acore_' + name, output / 'verified-source' / source,
                               state / 'logs/sql-client.log')
                    evidence['completedFiles'].append(source)
                    if len(evidence['completedFiles']) % 25 == 0:
                        print(json.dumps({'baseFilesCompleted': len(evidence['completedFiles']),
                                          'totalBaseFiles': sum(BASE_COUNTS.values())}), flush=True)
                load_bases(connection, plan, apply)
                evidence['tableCounts'] = schema_tables(connection, plan)
                evidence['baseSqlLoaded'] = True
                token = hashlib.sha256(canonical_identity(identities)).hexdigest()
                for name in DB_ORDER:
                    connection.query('CREATE TABLE `acore_' + name + '`.`esteria_base_probe` '
                                     '(id INT PRIMARY KEY, token CHAR(64) NOT NULL) ENGINE=InnoDB')
                    connection.query("INSERT INTO `acore_" + name + "`.`esteria_base_probe` VALUES (1,'" + token + "')")
            stop_owned(capture)
            capture = None
            capture = db.EngineCapture(engine_command(mysqld, state), state / 'logs/mysql-base-restart-engine.log')
            wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                for name in DB_ORDER:
                    content.require(connection.query('SELECT token FROM `acore_' + name + '`.`esteria_base_probe` WHERE id=1') == [token],
                                    'base SQL persistence marker changed after restart')
                    tables = connection.query('SHOW TABLES FROM `acore_' + name + '`')
                    content.require(sorted(tables) == sorted([Path(p).stem for p in plan[name]] + ['esteria_base_probe']),
                                    'schema table set changed after restart')
                evidence['restartPersistenceVerified'] = True
            stop_owned(capture)
            capture = None
        evidence.pop('activeFile', None)
        evidence['qualificationSucceeded'] = True
        return evidence
    except BaseException as error:
        evidence['failure'] = str(error)
        raise
    finally:
        try:
            if capture is not None:
                try:
                    stop_owned(capture)
                except BaseException as error:
                    evidence['qualificationSucceeded'] = False
                    evidence['shutdownFailure'] = str(error)
                    raise
        finally:
            db.atomic_json(output / 'qualification.json', evidence)
            export_diagnostics(state, output, bool(evidence.get('failure') or evidence.get('shutdownFailure')))


def canonical_identity(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    staging = commands.add_parser('prepare', help='Host-only exact Git SQL preparation; runs no database')
    staging.add_argument('--server', type=Path, required=True)
    staging.add_argument('--allow-source-fetch', action='store_true')
    qualification = commands.add_parser('qualify', help='New disposable MySQL fixture only; requires no Git')
    qualification.add_argument('--fixture', type=Path, required=True)
    qualification.add_argument('--fixture-sha256', required=True)
    qualification.add_argument('--mysql', type=Path, required=True)
    qualification.add_argument('--mysqld', type=Path, required=True)
    qualification.add_argument('--expected-version', required=True)
    for command in (staging, qualification):
        command.add_argument('--output', type=Path, required=True)
        command.add_argument('--lock', type=Path, default=content.ROOT / 'sources.lock.json')
    args = parser.parse_args()
    if args.command == 'prepare':
        print(prepare(args.server, args.lock, args.output, args.allow_source_fetch))
        return
    evidence = run(args.mysql, args.mysqld, args.fixture, args.fixture_sha256, args.lock,
                   args.output, args.expected_version)
    print(json.dumps({key: evidence[key] for key in ('scope', 'baseSqlLoaded', 'restartPersistenceVerified',
                                                    'compiledUpdaterExecuted', 'databaseUpgradeQualified')}))


if __name__ == '__main__':
    main()
