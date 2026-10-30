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
except ImportError:
    import prepare_runtime as archives
    import qualify_base_sql as base
    import package_server_content as package
    import manifest_server_modules as modules
    import render_server_config as config
    import verify_server_build as files
    import initialize_server_schema as baseline
from runtime import mysql_bootstrap as db
from runtime import provision_local_realm as realm
from runtime import server_schema_adaptations as adaptations
from runtime import server_content as product_content
from runtime import server_updater as product_updater
from runtime import server_schema_setup as product_schema
from runtime import server_update_setup as product_setup
from runtime import server_config as product_config
from runtime import provision_local_account as account
from runtime.owned_process_group import OwnedGroup

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


def select_install(install, compiled, lock_path, engine_derivative_receipt=None):
    """Keep original provenance and select derived program identities explicitly."""
    if engine_derivative_receipt is not None:
        from tools import verify_server_engine_runtime as derivative
        return derivative.verify_install(install, compiled, lock_path, engine_derivative_receipt)
    build, template = verify_install(install, compiled, lock_path)
    programs = {Path(row['path']).name: {key: row[key] for key in ('bytes', 'sha256')}
                for row in build['files'] if row['path'] in ('bin/authserver', 'bin/worldserver', 'bin/dbimport')}
    return build, template, programs, None


def verify_runtime_content(extracted, content_directory, receipt_sha256, lock_path, manifest, compiled):
    """Exercise the phone's no-Git consumer using the installed-bound selection."""
    source, lock_sha = base.locked_source(lock_path)
    verified = product_content.verify(extracted, content_directory / 'package-receipt.json', receipt_sha256,
                                      source, lock_sha, compiled)
    require(verified.manifest == manifest and verified.compiled == compiled,
            'runtime content consumer differs from verified native selection')
    return verified


# The same primitives are used by native qualification and the product runtime.
# Keep public names, signatures and OwnedGroup identity for existing callers.
render_importer = product_updater.render_importer
run_importer = product_updater.run_importer
expected_updates = product_updater.expected_updates
schema_snapshot = product_updater.schema_snapshot


def packaged_updater_log(state, journal):
    """Retain the actual product child's bounded tail in the existing exporter."""
    operation = Path(journal.get('invocation', ''))
    require(operation.parent == state / 'run' and re.fullmatch('updater-[a-f0-9]{32}', operation.name),
            'product updater private operation path differs')
    source = operation / 'logs/updater-private.log'
    run = journal.get('run', {})
    require(type(run.get('diagnosticBytes')) is int and 0 <= run['diagnosticBytes'] <= LOG_LIMIT and
            re.fullmatch('[a-f0-9]{64}', run.get('diagnosticSha256', '')),
            'product updater diagnostic identity missing')
    with product_updater.plain_file(source) as incoming:
        info = os.fstat(incoming.fileno())
        require(info.st_nlink == 1 and info.st_uid == os.geteuid() and not info.st_mode & 0o077,
                'shared or nonprivate product updater diagnostic refused')
        raw = incoming.read(LOG_LIMIT + 1)
    require(len(raw) == run['diagnosticBytes'] and hashlib.sha256(raw).hexdigest() == run['diagnosticSha256'],
            'product updater diagnostic changed')
    target = db.private_path(state / 'logs/dbimport-first.log')
    with target.open('xb') as outgoing:
        os.fchmod(outgoing.fileno(), 0o600)
        outgoing.write(raw); outgoing.flush(); os.fsync(outgoing.fileno())


def run_packaged_updater(verified, install, template, template_identity, programs, mysql, version,
                         state, connection, options, lease, verify_service, evidence):
    """Exercise real product journals before qualification-only probe tables."""
    proofs = []
    prepared = product_schema.initialize(verified, connection, state, version,
        lambda database, sql: base.apply_base(mysql, options, 'acore_' + database,
                                              sql, state / 'logs/sql-client.log'),
        state_lease=lease, on_baseline_complete=proofs.append)
    require(len(proofs) == 1 and proofs[0].get('baselineImportCompleted') is True and
            prepared.get('operation') == 'initialized-source-baseline',
            'product baseline did not produce its actual first-import proof')
    evidence['sourceBaseline'] = proofs[0]
    evidence['packagedRuntimeBaseline'] = prepared
    evidence['compiledUpdaterAttempted'] = True
    plan = product_setup.prepare(verified, install / 'bin/dbimport', programs['dbimport'], template,
        template_identity, mysql, original_build_identity=verified.compiled['serverBuild'])
    try:
        executed = product_setup.apply(plan, connection, state, version,
                                        state_lease=lease, verify_service=verify_service)
    finally:
        journal_path = state / product_setup.JOURNAL
        if os.path.lexists(journal_path):
            observed = product_schema.private_journal(journal_path)
            evidence['compiledUpdaterExecuted'] = observed.get('compiledUpdaterExecuted') is True
    require(executed.get('compiledUpdaterExecuted') is True and executed.get('compiledUpdaterCompleted') is True and
            executed.get('sourceLedgersVerified') is True, 'product compiled updater did not complete')
    journal = product_schema.private_journal(state / product_setup.JOURNAL)
    require(journal.get('phase') == 'complete' and journal.get('run', {}).get('exitCode') == 0,
            'product compiled updater journal is incomplete')
    packaged_updater_log(state, journal)
    evidence['firstUpdater'] = journal['run']
    evidence['packagedRuntimeUpdater'] = executed
    repeated = product_setup.apply(plan, connection, state, version,
                                    state_lease=lease, verify_service=verify_service)
    require(repeated.get('compiledUpdaterExecuted') is False and repeated.get('sourceLedgersVerified') is True,
            'product completed repeat replayed or failed ledger verification')
    evidence['packagedRuntimeUpdaterReentry'] = repeated
    checked = product_setup.verify_completed_update(verified, connection, state, version,
        expected_uuid=executed['mysqlUuid'], verify_service=verify_service)
    require(checked.get('compiledUpdaterExecuted') is False and checked.get('sourceLedgersVerified') is True,
            'product read-only completed verifier failed')
    evidence['packagedRuntimeUpdaterReadOnly'] = checked


def provision_packaged_runtime(verified, connection, state, version, mysql, data, lease, verify_service):
    """Compose actual product configuration/realm/account on the same instance."""
    profile = json.loads(config.PROFILE.read_bytes())
    rendered = product_config.render_verified(verified, state, data, mysql, profile=profile)
    require(rendered.get('module_configurations_complete') is True,
            'product configuration omitted compiled module files')
    bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
    arguments = dict(profile=profile, data=data, mysql=mysql, expected_uuid=bootstrap['uuid'],
                     verify_service=verify_service, state_lease=lease)
    local_realm = realm.provision_verified(verified, connection, state, version, **arguments)
    local_account = account.provision_verified(verified, connection, state, version, **arguments)
    require(local_realm.get('completedUpdaterVerified') is True and local_realm.get('sqlEndpointVerified') is True and
            local_account.get('completedUpdaterVerified') is True and local_account.get('credentialsPrivate') is True,
            'product realm or account composition did not verify its owned updater')
    after_account = product_setup.verify_completed_update(verified, connection, state, version,
        expected_uuid=bootstrap['uuid'], verify_service=verify_service)
    require(after_account.get('compiledUpdaterExecuted') is False and after_account.get('sourceLedgersVerified') is True,
            'product updater verifier rejected the subsequently owned account')
    return dict(scope='actual-product-config-updater-realm-account-before-native-probe-tables',
        configuration=rendered, realm=local_realm, account=local_account,
        updaterAfterAccount=after_account, mysqlUuid=bootstrap['uuid'],
        androidRuntimeQualified=False, gameplayQualified=False)


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


def run(install, content_directory, receipt_sha256, lock_path, mysql, mysqld, version, output,
        *, engine_derivative_receipt=None):
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
        build, template, programs, derivative = select_install(install, compiled, lock_path, engine_derivative_receipt)
        template_rows = [row for row in build['files'] if row['path'] == template.relative_to(install).as_posix()]
        require(len(template_rows) == 1, 'selected updater template is absent from original build receipt')
        template_identity = {key: template_rows[0][key] for key in ('bytes', 'sha256')}
        verified = verify_runtime_content(output / 'content', content_directory, receipt_sha256,
                                          lock_path, manifest, compiled)
        evidence['packagedRuntimeContent'] = dict(scope='actual-immutable-content-no-git-runtime-consumer',
            contentReceipt=verified.identities['receipt'], sourceLockSha256=receipt['sourceLockSha256'],
            files=len(verified.identities['files']),
            bytes=sum(row['bytes'] for row in verified.identities['files'].values()),
            installedBuildAndModuleSelectionChecked=True, allPackagedBytesReadBack=True,
            sqlExecutedByVerifier=False, androidRuntimeQualified=False, gameplayQualified=False)
        # Validate the separate integration SQL/audit contract before starting
        # an engine. Original packaged SQL and ledger expectations stay exact.
        adaptations.prepare(manifest)
        if derivative is not None:
            evidence['engineDerivative'] = derivative
        evidence.update(source=receipt['source'], sourceLockSha256=receipt['sourceLockSha256'],
                        serverBuildId=build['buildId'], compiledModules=compiled['enabledModules'])
        source = verified.source
        expected = {name: expected_updates(source, manifest, name) for name in DATABASES}
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state) as lease:
            db.initialize(mysqld, mysql, state, version)
            evidence['initializedNewInstance'] = True
            configuration = render_importer(template, source, state, mysql, password)
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-base-engine.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                        'another operation owns fixture instance')
                base.empty_databases(connection)
                def verify_service():
                    require(capture.process.poll() is None, 'owned qualification MySQL service exited')
                    db.check_receipt(db.read_receipt(state / 'database-bootstrap.json', version),
                                     db.identity(connection, version))
                run_packaged_updater(verified, install, template, template_identity, programs, mysql, version,
                                     state, connection, options, lease, verify_service, evidence)
                evidence['compiledUpdaterCompleted'] = True
                schema_snapshot(connection, expected)
                evidence['coreModuleUpdatesQualified'] = True
                evidence['packagedRuntimeProvisioning'] = provision_packaged_runtime(verified, connection, state,
                    version, mysql, output / 'unavailable-game-data', lease, verify_service)
                account_journal = (state / account.JOURNAL).read_bytes()
                bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
                token = hashlib.sha256(base.canonical_identity(receipt['archive'])).hexdigest()
                markers(connection, token, create=True)
                before = schema_snapshot(connection, expected)
                require(files.identity(install / 'bin/dbimport') == programs['dbimport'],
                        'selected dbimport identity changed before reentry')
                evidence['secondUpdater'] = run_importer(install / 'bin/dbimport', configuration, state / 'logs/dbimport-second.log')
                markers(connection, token)
                require(schema_snapshot(connection, expected) == before, 'same-revision updater changed table/ledger set')
                require((state / account.JOURNAL).read_bytes() == account_journal,
                        'same-revision updater changed the private product account journal')
                account.configure_account(connection, state, bootstrap, verify_only=True)
                evidence['packagedAccountPreservedAcrossUpdater'] = True
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
                require((state / account.JOURNAL).read_bytes() == account_journal,
                        'restart changed the private product account journal')
                account.configure_account(connection, state, bootstrap, verify_only=True)
                evidence['packagedAccountPreservedAfterRestart'] = True
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
    parser.add_argument('--engine-derivative-receipt', type=Path)
    args = parser.parse_args()
    evidence = run(args.install, args.content, args.content_receipt_sha256, args.lock, args.mysql,
                   args.mysqld, args.expected_version, args.output,
                   engine_derivative_receipt=args.engine_derivative_receipt)
    print(json.dumps(evidence, sort_keys=True))


if __name__ == '__main__':
    main()
