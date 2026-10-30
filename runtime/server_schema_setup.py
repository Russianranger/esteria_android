#!/usr/bin/env python3
"""Journal a fresh source baseline on the caller's owned, authenticated engine.

Consumes verified immutable packaged content, never Git or Docker. This helper
does not start MySQL, the updater, authserver or worldserver. The application
must retain its exclusive service/session lease around this entire operation.
DDL can commit before interruption: any in-flight/partial journal is preserved
and refused on re-entry, never replayed over partial tables or player saves.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat

try:
    from . import mysql_bootstrap as db, server_content as packaged, server_schema_baseline as baseline
    from . import server_schema_adaptations as adaptations
except ImportError:
    import mysql_bootstrap as db
    import server_content as packaged
    import server_schema_baseline as baseline
    import server_schema_adaptations as adaptations

JOURNAL = '.server-schema-initialization.json'
ACCOUNT = 'accounts/local-player.json'
APPEARANCE_PATH = 'integration/appearance-schema-v1.sql'
MAX_JOURNAL = 1024 * 1024


class SchemaCancelled(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise db.BootstrapError(message)


def checkpoint(cancelled):
    if cancelled is not None and cancelled():
        raise SchemaCancelled('Schema setup cancelled at a file boundary; state preserved')


def private_journal(path):
    path = db.private_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and info.st_nlink == 1 and
                not info.st_mode & 0o077, 'Schema journal must be an owned, unshared private file')
        raw = stream.read(MAX_JOURNAL + 1)
    require(len(raw) <= MAX_JOURNAL, 'Schema journal exceeds bound')
    def pairs(rows):
        result = {}
        for name, value in rows:
            require(name not in result, 'Duplicate schema journal field')
            result[name] = value
        return result
    result = json.loads(raw, object_pairs_hook=pairs)
    require(type(result) is dict, 'Invalid schema journal')
    return result


def credential_identity(state):
    # Read the existing credential contract; never create/reset either secret.
    for name in ('database-secret', 'database-root-secret'):
        db.read_secret(state / 'accounts' / name)
    return {name: baseline.file_identity(state / 'accounts' / name)
            for name in ('database-secret', 'database-root-secret')}


def account_identity(state):
    path = state / ACCOUNT
    return baseline.file_identity(path) if os.path.lexists(path) else None


def result(content, bootstrap, operation, applied, appearance_proofs):
    return dict(formatVersion=1, scope='owned-packaged-content-source-baseline-only',
        operation=operation, mysqlUuid=bootstrap['uuid'], mysqlVersion=bootstrap['version'],
        contentReceipt=content.identities['receipt'], sourceLockSha256=content.receipt['sourceLockSha256'],
        compiledModules=content.receipt['compiledModules'], appliedFiles=len(applied),
        sourceDerivedAdaptations=appearance_proofs,
        baselineImportCompleted=True, liveSchemaReadinessVerified=False,
        compiledUpdaterExecuted=False, gameSchemasQualified=False, existingSaveUpgradesQualified=False,
        playerbotsRuntimeQualified=False, authserverExecuted=False, worldserverExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False)


def initialize(content, connection, state, version, apply, *, progress=None, cancelled=None):
    """Apply exact bases/prerequisites; `apply(database, path)` runs owned SQL.

    `content` must come from server_content.verify with application/engine pins.
    The caller supplies the already owned service and one persistent connection;
    this function independently authenticates its version/UUID/path/user/endpoint.
    Cancellation is immediate before SQL and between files. An executing file
    must finish or fail through its owner's bounded process lifecycle.
    """
    require(isinstance(content, packaged.VerifiedContent), 'Verified immutable server content required')
    checkpoint(cancelled)
    state = db.private_path(Path(state))
    identity = lambda path: baseline.file_identity(path, check=lambda: checkpoint(cancelled))
    plan, modules, schemas, identities = baseline.selected_plan(content.source, content.manifest, identity=identity)
    appearance = adaptations.prepare(content.manifest)
    paths = [path for database in baseline.DATABASES for path in plan[database]]
    paths += [row['path'] for row in modules + schemas]
    paths.append(APPEARANCE_PATH)
    identities[APPEARANCE_PATH] = appearance.proof['sqlIdentity']
    require(len(paths) == len(set(paths)), 'Duplicate source baseline path')
    checkpoint(cancelled)
    with db.state_lock(state):
        bootstrap = db.read_receipt(state / 'database-bootstrap.json', version)
        require(bootstrap['datadir'] == str(state / 'database') and
                db.datadir_uuid(state / 'database') == bootstrap['uuid'], 'Persistent database identity changed')
        db.check_receipt(bootstrap, db.identity(connection, version))
        db.check_listener(connection, None)
        require(connection.query('SELECT CURRENT_USER()') in
                (['esteria@127.0.0.1'], ['esteria@localhost']), 'Unexpected schema database account')
        require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'],
                'Another operation owns the schema instance')
        try:
            credentials = credential_identity(state)
            account = account_identity(state)
            binding = dict(mysqlUuid=bootstrap['uuid'], mysqlVersion=version, datadir=bootstrap['datadir'],
                contentReceipt=content.identities['receipt'], sourceLockSha256=content.receipt['sourceLockSha256'],
                compiledModules=content.receipt['compiledModules'], credentials=credentials, paths=paths,
                sourceDerivedAdaptation={key: appearance.proof[key] for key in
                    ('adaptationId', 'sqlIdentity', 'metadataIdentity', 'sourceLockSha256')})
            journal_path = state / JOURNAL
            if os.path.lexists(journal_path):
                journal = private_journal(journal_path)
                require(journal.get('formatVersion') == 1 and journal.get('binding') == binding,
                        'Schema source, credential or instance identity changed; no upgrades or adoption')
                if journal.get('phase') == 'baseline-complete':
                    require(journal.get('completed') == paths and journal.get('pending') is None,
                            'Invalid completed baseline journal')
                    expected_proofs = [dict(appearance.proof, sqlExecuted=True, exactEmptyTableAdditionVerified=True)]
                    require(journal.get('sourceDerivedAdaptations') == expected_proofs,
                            'Completed source-derived adaptation proof differs')
                    # Historical completion only. Canonical updater readiness
                    # and live-save schema upgrades remain separate gates.
                    return result(content, bootstrap, 'already-prepared', paths, expected_proofs)
                require(journal.get('phase') == 'prepared' and journal.get('completed') == [] and
                        journal.get('pending') is None, 'Partial schema setup preserved; replay is refused')
                require(account is None, 'Existing account journal preserved; prepared schema adoption refused')
            else:
                require(account is None, 'Existing account journal preserved; fresh schema adoption refused')
                baseline.empty_databases(connection)
                checkpoint(cancelled)
                journal = dict(formatVersion=1, binding=binding, phase='prepared', completed=[], pending=None)
                db.atomic_json(journal_path, journal)
            baseline.empty_databases(connection)
            checkpoint(cancelled)
            def import_file(database, path):
                checkpoint(cancelled)
                relative = APPEARANCE_PATH if path == appearance.sql_path else path.relative_to(content.source).as_posix()
                require(relative == paths[len(journal['completed'])] and
                        identity(path) == {key: identities[relative][key] for key in ('bytes', 'sha256')},
                        'Selected source changed before SQL')
                journal.update(phase='importing', pending=dict(database=database, path=relative))
                db.atomic_json(journal_path, journal)  # Durable intent before auto-committing DDL.
                if progress is not None:
                    progress(dict(phase='schema-file-started', path=relative,
                                  files=len(journal['completed']), totalFiles=len(paths)))
                # Durable intent commits us to finish this file. A cancellation
                # arriving now is observed before the next file, never between
                # intent and SQL (which would strand an untouched database).
                apply(database, path)
                require(credential_identity(state) == credentials and account_identity(state) == account,
                        'Credential or account journal changed during schema initialization')
                journal['completed'].append(relative); journal['pending'] = None
                db.atomic_json(journal_path, journal)
                if progress is not None:
                    progress(dict(phase='schema-file-complete', path=relative,
                                  files=len(journal['completed']), totalFiles=len(paths)))
            proof = adaptations.initialize(connection, content.source, content.manifest, import_file,
                baseline_initializer=lambda connection, source, manifest, apply:
                    baseline.initialize(connection, source, manifest, apply, identity=identity))
            require(journal['completed'] == paths and proof['baselineImportCompleted'] is True,
                    'Incomplete source baseline import')
            journal.update(phase='baseline-complete', pending=None,
                           sourceDerivedAdaptations=proof['sourceDerivedAdaptations'])
            db.atomic_json(journal_path, journal)
            return result(content, bootstrap, 'initialized-source-baseline', paths, proof['sourceDerivedAdaptations'])
        finally:
            require(connection.query("SELECT RELEASE_LOCK('esteria-local-bootstrap')") == ['1'],
                    'Schema operation lock release failed; state preserved')
