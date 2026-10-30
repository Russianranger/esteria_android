#!/usr/bin/env python3
"""Run the exact compiled updater against a NEW disposable MySQL instance.

Consumes the verified immutable server-content package, never a live save path.
Exercises auth/characters/world only; playerbots requires its world-server hook.
There is deliberately no dry-run, recovery/retry or saved-state promotion mode.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import subprocess
import sys
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from . import prepare_runtime as archives
    from . import qualify_base_sql as base
    from . import package_server_content as package
    from . import manifest_server_modules as modules
    from . import render_server_config as config
    from . import verify_server_build as files
    from . import initialize_server_schema as baseline
    from .owned_process_group import OwnedGroup
except ImportError:
    import prepare_runtime as archives
    import qualify_base_sql as base
    import package_server_content as package
    import manifest_server_modules as modules
    import render_server_config as config
    import verify_server_build as files
    import initialize_server_schema as baseline
    from owned_process_group import OwnedGroup
from runtime import mysql_bootstrap as db
from runtime import provision_local_realm as realm

require = base.content.require
DATABASES = ('auth', 'characters', 'world')
LOG_LIMIT = 256 * 1024


def unpack_content(directory, expected_receipt_sha256, lock_path, destination):
    receipt, identity = modules.read_json(directory / 'package-receipt.json')
    require(re.fullmatch('[0-9a-f]{64}', expected_receipt_sha256) and
            identity['sha256'] == expected_receipt_sha256, 'content package receipt digest mismatch')
    pin, lock_hash = base.locked_source(lock_path)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'immutable-server-source-content-package' and
            receipt.get('source') == pin and receipt.get('sourceLockSha256') == lock_hash and
            receipt.get('moduleSelectionVerified') is True and receipt.get('archiveReadBackVerified') is True,
            'source and compiled-module verified content package required')
    inventory = receipt['archiveFiles']
    require(isinstance(inventory, dict) and 1 <= len(inventory) <= files.MAX_FILES, 'content package file count bound')
    total = 0
    for path, row in inventory.items():
        base.content.safe_path(path)
        require(type(row.get('bytes')) is int and 0 <= row['bytes'] <= package.MAX_TOTAL and
                re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'invalid archive member identity')
        total += row['bytes']
    require(total <= package.MAX_TOTAL + 4 * package.METADATA, 'content package size bound')
    archive_path = db.private_path(directory / 'server-content.tar.gz')
    require(files.identity(archive_path) == receipt['archive'], 'content archive differs from receipt')
    require(not destination.exists(), 'existing extracted source preserved')
    destination.mkdir(mode=0o700)
    seen = set()
    with files.plain_file(archive_path) as compressed:
        with archives.bounded_tar(compressed, dict(entries=files.MAX_FILES, pathBytes=4096,
                fileBytes=package.MAX_TOTAL + 4 * package.METADATA)) as archive:
            for item in archive:
                base.content.safe_path(item.name)
                require(item.isfile() and item.name in inventory and item.name not in seen,
                        'unexpected/link/duplicate archive member')
                row = inventory[item.name]
                require(item.size == row['bytes'] and item.uid == item.gid == item.mtime == 0 and
                        item.mode == 0o644 and not item.uname and not item.gname,
                        'archive member metadata differs from package contract')
                path = destination / item.name
                path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o400)
                digest, remaining = hashlib.sha256(), row['bytes']
                with os.fdopen(descriptor, 'wb') as out, archive.extractfile(item) as stream:
                    while remaining:
                        block = stream.read(min(base.content.CHUNK, remaining))
                        require(block, 'short content archive member')
                        remaining -= len(block)
                        digest.update(block)
                        out.write(block)
                    require(not stream.read(1), 'content archive member exceeds expected size')
                    out.flush()
                    os.fsync(out.fileno())
                require(digest.hexdigest() == row['sha256'], 'content archive member digest mismatch')
                seen.add(item.name)
    require(seen == set(inventory), 'content archive incomplete')
    manifest, _ = modules.read_json(destination / 'metadata/content-manifest.json')
    compiled, _ = modules.read_json(destination / 'metadata/compiled-modules.json')
    lua, _ = modules.read_json(destination / 'metadata/lua-map.json')
    require(manifest.get('source') == pin and manifest.get('sourceLockSha256') == lock_hash and
            manifest.get('contentSha256Complete') is True, 'content inventory source mismatch')
    require(package.validate_modules(compiled, manifest), 'compiled module selection missing')
    payload = package.select_payload(manifest, package.validate_lua(lua, manifest))
    expected_payload = {entry[2] for entry in payload}
    require(expected_payload == {path for path in inventory if not path.startswith('metadata/')},
            'package payload differs from source-selected SQL/config/notices/Lua')
    for origin, path, target in payload:
        row = manifest['files' if origin == 'server' else 'elunaFiles'][path]
        expected = {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}
        expected.update(origin=origin, source=path)
        require(inventory[target] == expected,
                'archive payload identity differs from source inventory')
    for name in DATABASES:
        plan = manifest['databases'][name]
        require(plan['executionOrderQualified'] is True and plan['updateOrder'] is not None,
                'ambiguous source SQL discovery')
    return receipt, manifest, compiled


def verify_install(install, compiled, lock_path):
    build, identity = modules.read_json(install / 'server-build.json')
    pin, lock_hash = base.locked_source(lock_path)
    require(identity == compiled['serverBuild'] and build.get('schemaVersion') == 1 and
            build.get('architecture') == 'Linux-ARM64' and build.get('sourceCheckoutAndPatchesVerified') is True and
            build.get('serverSource') == pin and build.get('sourcesLock', {}).get('sha256') == lock_hash,
            'server build provenance differs from compiled-module receipt')
    listed = {entry['path']: entry for entry in build['files']}
    require(len(listed) == len(build['files']) and len(listed) <= files.MAX_FILES, 'duplicate/oversize installed file list')
    # Check every installed ELF, including any private shared libraries, before execution.
    for name, row in listed.items():
        base.content.safe_path(name)
        if 'elf' in row:
            require(row['elf'].get('machine') == 'AArch64', 'non-ARM64 installed ELF')
            require(files.identity(install / name) == {key: row[key] for key in ('bytes', 'sha256')},
                    'installed ELF digest differs from build receipt')
    for target in ('dbimport', 'worldserver'):
        row = listed.get('bin/' + target, {})
        require(row.get('elf', {}).get('machine') == 'AArch64', 'required compiled executable missing')
        require({key: row[key] for key in ('bytes', 'sha256')} ==
                {key: compiled['binaries'][target][key] for key in ('bytes', 'sha256')},
                'installed executable differs from compiled module receipt')
    templates = [name for name in listed if Path(name).name == 'dbimport.conf.dist']
    require(len(templates) == 1, 'exact installed dbimport template required')
    template = templates[0]
    require(files.identity(install / template) == {key: listed[template][key] for key in ('bytes', 'sha256')},
            'installed dbimport template differs from build receipt')
    return build, install / template


def render_importer(template, source, state, mysql, password):
    run = state / 'run/dbimport'
    run.mkdir(mode=0o700)
    settings = {'SourceDirectory': config.quoted(source), 'MySQLExecutable': config.quoted(mysql),
                'LogsDir': config.quoted(state / 'logs'), 'TempDir': config.quoted(run),
                'Updates.EnableDatabases': 7, 'Updates.AllowedModules': '"all"',
                'Updates.AutoSetup': 0, 'Updates.Redundancy': 1, 'Updates.AllowRehash': 1,
                'Updates.ArchivedRedundancy': 0, 'Updates.CleanDeadRefMaxCount': 0,
                'Database.Reconnect.Attempts': 1, 'Database.Reconnect.Seconds': 1,
                'Logger.root': '4,Console'}
    for label, database in (('Login', 'auth'), ('Character', 'characters'), ('World', 'world')):
        settings[label + 'DatabaseInfo'] = f'"127.0.0.1;{db.PORT};esteria;{password};acore_{database}"'
        settings[label + 'Database.WorkerThreads'] = settings[label + 'Database.SynchThreads'] = 1
    text = config.overlay(template.read_text(), settings)
    path = run / 'dbimport.conf'
    config.write_private(path, text)
    return path


def run_importer(executable, configuration, log, *, timeout=1800, on_started=None):
    """Own the whole updater/mysql child process group; retain a bounded private tail."""
    command = [str(executable), '--config', str(configuration)]
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'AC_DISABLE_INTERACTIVE': '1', 'MYSQL_TEST_LOGIN_FILE': os.devnull}
    descriptor = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    tail = bytearray()
    child = None
    group = None
    try:
        child = subprocess.Popen(command, cwd=configuration.parent, env=environment, umask=0o077,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        group = OwnedGroup(child)
        if on_started is not None:
            on_started()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, 'owned dbimport timed out; partial fixture preserved')
                for key, _ in selector.select(.2):
                    block = os.read(key.fd, 8192)
                    if not block:
                        selector.unregister(key.fd)
                        continue
                    tail.extend(block)
                    if len(tail) > LOG_LIMIT:
                        del tail[:-LOG_LIMIT]
            exit_code = group.wait(timeout=max(.01, deadline - time.monotonic()))
        require(exit_code == 0, 'compiled dbimport failed (exit ' + str(exit_code) + '); partial fixture preserved')
        return {'exitCode': exit_code, 'diagnosticBytes': len(tail),
                'diagnosticSha256': hashlib.sha256(tail).hexdigest()}
    finally:
        try:
            if group is not None:
                group.stop()
        finally:
            if child is not None and child.stdout:
                child.stdout.close()
            with os.fdopen(descriptor, 'wb') as output:
                output.write(tail)
                output.flush()
                os.fsync(output.fileno())


def expected_updates(source, manifest, database):
    result = {}
    for item in manifest['databases'][database]['updateOrder']:
        path = item['path']
        digest = hashlib.sha1()
        with files.plain_file(source / path) as stream:
            while block := stream.read(base.content.CHUNK):
                digest.update(block)
        name = Path(path).name
        require(name not in result, 'duplicate SQL basename in updater expectation')
        result[name] = (digest.hexdigest(), item['state'])
    return result


def schema_snapshot(connection, expected):
    result = {}
    for name in DATABASES:
        tables = connection.query('SHOW TABLES FROM `acore_' + name + '`')
        require('updates' in tables and 'updates_include' in tables, 'compiled updater did not create its ledger')
        rows = connection.query('SELECT name,hash,state FROM `acore_' + name + '`.`updates` ORDER BY name')
        entries = {}
        for row in rows:
            fields = row.split('\t')
            require(len(fields) == 3 and fields[0] not in entries, 'invalid or duplicate update ledger entry')
            entries[fields[0]] = (fields[1].lower(), fields[2])
        for filename, (digest, state) in expected[name].items():
            require(filename in entries, 'source update missing from applied ledger: ' + name + '/' + filename)
            observed = entries[filename]
            # Pinned source intentionally skips archived hash redundancy by default.
            require(observed[1] == state and (state == 'ARCHIVED' or observed[0] == digest),
                    'source update ledger/hash differs: ' + name + '/' + filename)
        result[name] = {'tableCount': len(tables), 'tablesSha256': hashlib.sha256(base.canonical_identity(tables)).hexdigest(),
                        'ledgerRows': len(rows), 'ledgerSha256': hashlib.sha256(base.canonical_identity(rows)).hexdigest(),
                        'sourceUpdateNamesVerified': len(expected[name])}
    require(not connection.query('SHOW TABLES FROM `acore_playerbots`'),
            'dbimport unexpectedly modified the unregistered playerbots database')
    return result


def markers(connection, token, *, create=False):
    for name in DATABASES:
        table = '`acore_' + name + '`.`esteria_dbimport_probe`'
        if create:
            connection.query('CREATE TABLE ' + table + ' (id INT PRIMARY KEY, '
                             'token CHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci NOT NULL) ENGINE=InnoDB')
            connection.query("INSERT INTO " + table + " VALUES (1,'" + token + "')")
        require(connection.query('SELECT token FROM ' + table + ' WHERE id=1') == [token],
                'disposable state marker changed during same-revision updater/restart')


def redact_importer_logs(state, output):
    passwords = [db.read_secret(state / 'accounts' / name) for name in
                 ('database-secret', 'database-root-secret') if (state / 'accounts' / name).is_file()]
    for name in ('dbimport-first.log', 'dbimport-second.log'):
        path = state / 'logs' / name
        if path.is_file():
            with path.open('rb') as stream:
                text = stream.read(LOG_LIMIT).decode('utf-8', errors='replace')
            for password in passwords:
                text = text.replace(password, '[redacted]')
            config.write_private(output / name, text)


def run(install, content_directory, receipt_sha256, lock_path, mysql, mysqld, version, output):
    db.exact_version(version)
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'compiled updater qualification requires native Linux ARM64')
    require(all(path.is_absolute() for path in (install, content_directory, mysql, mysqld)),
            'absolute artifact/engine paths required')
    output = db.private_path(output)
    require(not output.exists(), 'existing fixture preserved; use a new output directory')
    output.mkdir(parents=True, mode=0o700)
    os.chmod(output, 0o700)
    state = output / 'private-state'
    state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope='disposable-native-ARM64-compiled-dbimport', mysqlVersion=version,
        contentReceiptSha256=receipt_sha256, qualificationSucceeded=False, initializedNewInstance=False,
        compiledUpdaterAttempted=False, compiledUpdaterExecuted=False, compiledUpdaterCompleted=False,
        compiledAutoPopulationQualified=False,
        coreModuleUpdatesQualified=False, sameRevisionReentryVerified=False,
        restartPersistenceVerified=False, playerbotsDatabaseUntouched=False, playerbotsRuntimeQualified=False,
        postAllServicesRealmGateQualified=False, existingStateModified=False, databaseUpgradeQualified=False,
        gameSchemasQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    capture = None
    try:
        receipt, manifest, compiled = unpack_content(content_directory, receipt_sha256, lock_path, output / 'content')
        build, template = verify_install(install, compiled, lock_path)
        evidence.update(source=receipt['source'], sourceLockSha256=receipt['sourceLockSha256'],
                        serverBuildId=build['buildId'], compiledModules=compiled['enabledModules'])
        source = output / 'content/source'
        expected = {name: expected_updates(source, manifest, name) for name in DATABASES}
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state):
            db.initialize(mysqld, mysql, state, version)
            evidence['initializedNewInstance'] = True
            configuration = render_importer(template, source, state, mysql, password)
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-base-engine.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                        'another operation owns fixture instance')
                base.empty_databases(connection)
                evidence['sourceBaseline'] = baseline.initialize(connection, source, manifest,
                    lambda database, sql: base.apply_base(mysql, options, 'acore_' + database,
                                                          sql, state / 'logs/sql-client.log'))
                evidence['compiledUpdaterAttempted'] = True
                evidence['firstUpdater'] = run_importer(install / 'bin/dbimport', configuration,
                    state / 'logs/dbimport-first.log',
                    on_started=lambda: evidence.update(compiledUpdaterExecuted=True))
                evidence['compiledUpdaterCompleted'] = True
                schema_snapshot(connection, expected)
                evidence['coreModuleUpdatesQualified'] = True
                token = hashlib.sha256(base.canonical_identity(receipt['archive'])).hexdigest()
                markers(connection, token, create=True)
                before = schema_snapshot(connection, expected)
                evidence['secondUpdater'] = run_importer(install / 'bin/dbimport', configuration, state / 'logs/dbimport-second.log')
                markers(connection, token)
                require(schema_snapshot(connection, expected) == before, 'same-revision updater changed table/ledger set')
                evidence['sameRevisionReentryVerified'] = True
                # Component check only; the final application gate also awaits playerbots/world startup.
                realm.check_schema(connection)
                evidence['fixtureRealmOperation'] = realm.configure_row(connection)
                evidence['loopbackRealmVerifiedAfterDbimport'] = True
                evidence['databaseSnapshots'] = before
            base.stop_owned(capture)
            capture = None
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-base-restart-engine.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                markers(connection, token)
                require(schema_snapshot(connection, expected) == before, 'database schema/ledger changed after clean restart')
                realm.check_schema(connection)
                realm.configure_row(connection, verify_only=True)
                evidence['restartPersistenceVerified'] = True
                evidence['playerbotsDatabaseUntouched'] = True
            base.stop_owned(capture)
            capture = None
        evidence['qualificationSucceeded'] = True
        return evidence
    except BaseException as error:
        evidence['failure'] = str(error)
        raise
    finally:
        try:
            if capture is not None:
                try:
                    base.stop_owned(capture)
                except BaseException as error:
                    evidence['qualificationSucceeded'] = False
                    evidence['shutdownFailure'] = str(error)
                    raise
        finally:
            db.atomic_json(output / 'qualification.json', evidence)
            base.export_diagnostics(state, output, bool(evidence.get('failure') or evidence.get('shutdownFailure')))
            redact_importer_logs(state, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--content', type=Path, required=True)
    parser.add_argument('--content-receipt-sha256', required=True)
    parser.add_argument('--lock', type=Path, default=base.content.ROOT / 'sources.lock.json')
    parser.add_argument('--mysql', type=Path, required=True)
    parser.add_argument('--mysqld', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    evidence = run(args.install, args.content, args.content_receipt_sha256, args.lock, args.mysql,
                   args.mysqld, args.expected_version, args.output)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    main()
