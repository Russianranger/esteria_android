#!/usr/bin/env python3
"""Reusable exact source baseline without Git, Docker or build-tool imports.

The caller supplies authenticated ownership and a verified content manifest. This
helper never adopts an existing or partially initialized database, synthesizes
updater ledger rows, discovers arbitrary module bases, or retries a failed import.
"""
from pathlib import Path
import hashlib
import os
import stat

SUPPORTED_SERVER = 'f35f04d01689f034778e3474b3c820092f51e461'
BASE_COUNTS = {'auth': 22, 'characters': 108, 'world': 309}
BASE_ROOTS = {name: 'data/sql/base/db_' + name for name in BASE_COUNTS}
DB_ORDER = ('auth', 'characters', 'world', 'playerbots')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_identity(path, *, check=None):
    if check is not None: check()
    path = Path(path).absolute()
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), 'linked or invalid schema source parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 4 * 1024**3, 'invalid schema source file')
        digest = hashlib.sha256(); count = 0
        for block in iter(lambda: stream.read(128 * 1024), b''):
            if check is not None: check()
            count += len(block); require(count <= before.st_size, 'schema source grew')
            digest.update(block)
        after = os.fstat(stream.fileno())
        require(count == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'schema source changed')
    return dict(bytes=count, sha256=digest.hexdigest())


def empty_databases(connection):
    for database in DB_ORDER:
        require(not connection.query('SHOW TABLES FROM `acore_' + database + '`'),
                'nonempty database preserved; base SQL must never be replayed: ' + database)

DATABASES = ('auth', 'characters', 'world')
NEMESIS_MODULE = 'mod-nemesis-system'
NEMESIS_BASE = 'modules/mod-nemesis-system/data/sql/db-characters/base/nemesis_system.sql'
NEMESIS_IDENTITY = dict(bytes=3511,
    sha256='011af71320bd68d81f38f5e28b83b85b5be07b6f08f7c798429d71ea7a66b793',
    gitBlob='30eaf2801e7688213a0aac5d410028193bd621d2')
NEMESIS_TABLES = ('character_nemesis', 'character_nemesis_monthly_kills')
CUSTOM_RACE_DDL = 'data/sql/updates/pending_db_world/rev_20260929001000000.sql'
CUSTOM_RACE_IDENTITY = dict(bytes=1642,
    sha256='315941b5af6763f24dde75a704761fd7750eee375aebaa0de63c5971843042ed',
    gitBlob='d39f0b23d7e9ed5af26e01e609d1ee3e74ef4ef3')
CUSTOM_RACE_TABLES = ('custom_race_start_skill', 'custom_race_start_skill_exclude',
                      'custom_race_start_spell', 'custom_race_start_spell_exclude')


def selected_plan(source, manifest, *, counts=None, identity=file_identity,
                  nemesis_identity=None, custom_race_identity=None):
    """Verify every selected byte before the first SQL statement can execute."""
    require(manifest.get('source', {}).get('commit') == SUPPORTED_SERVER and
            manifest.get('contentSha256Complete') is True, 'verified pinned source content required')
    counts = BASE_COUNTS if counts is None else counts
    nemesis_identity = NEMESIS_IDENTITY if nemesis_identity is None else nemesis_identity
    custom_race_identity = CUSTOM_RACE_IDENTITY if custom_race_identity is None else custom_race_identity
    plan = {}
    identities = {}
    for database in DATABASES:
        root = BASE_ROOTS[database]
        expected = sorted(path for path in manifest['files']
                          if str(Path(path).parent) == root and path.endswith('.sql'))
        require(len(expected) == counts[database] and
                manifest['databases'][database]['base'] == expected,
                'exact pinned immediate core base order required: ' + database)
        plan[database] = expected
        for path in expected:
            row = manifest['files'][path]
            identities[path] = {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}
    prerequisites = []
    if NEMESIS_MODULE in manifest['enabledModules']:
        row = manifest['files'].get(NEMESIS_BASE, {})
        require({key: row.get(key) for key in nemesis_identity} == nemesis_identity,
                'documented nemesis source prerequisite changed')
        require(any(row == dict(path=NEMESIS_BASE, state='MODULE', origin=NEMESIS_MODULE)
                    for row in manifest['databases']['characters']['updateOrder']),
                'nemesis prerequisite is absent from the actual updater selection')
        identities[NEMESIS_BASE] = nemesis_identity
        prerequisites.append(dict(database='characters', path=NEMESIS_BASE,
                                  tables=list(NEMESIS_TABLES), source=nemesis_identity))
    # The pinned pending updates mix epoch and calendar revision names. The
    # compiled lexicographic order reaches Sethrak's DML before this pure DDL.
    # Import the unchanged idempotent creator only on this new empty instance;
    # the compiled updater must still execute and record the canonical file.
    row = manifest['files'].get(CUSTOM_RACE_DDL, {})
    require({key: row.get(key) for key in custom_race_identity} == custom_race_identity,
            'canonical custom race source prerequisite changed')
    require(any(row == dict(path=CUSTOM_RACE_DDL, state='PENDING', origin='base-updates_include')
                for row in manifest['databases']['world']['updateOrder']),
            'custom race prerequisite is absent from the actual updater selection')
    identities[CUSTOM_RACE_DDL] = custom_race_identity
    schema_prerequisites = [dict(database='world', path=CUSTOM_RACE_DDL,
                                tables=list(CUSTOM_RACE_TABLES), source=custom_race_identity)]
    for path, row in identities.items():
        require(identity(source / path) == {key: row[key] for key in ('bytes', 'sha256')},
                'baseline source bytes differ before initialization: ' + path)
    return plan, prerequisites, schema_prerequisites, identities


def initialize(connection, source, manifest, apply, **contracts):
    """Apply source SQL only after every database is proven empty; no resume mode.

    `apply(database_name, source_path)` must use the caller's owned authenticated
    engine. Its exception aborts this invocation and leaves the partial fixture.
    The unmodified core bases include their original ledgers. Only the compiled
    updater records subsequent canonical module/update hashes.
    """
    plan, prerequisites, schema_prerequisites, identities = selected_plan(source, manifest, **contracts)
    empty_databases(connection)  # Includes playerbots, before ANY SQL.
    completed = []
    for database in DATABASES:
        require(not connection.query('SHOW TABLES FROM `acore_' + database + '`'),
                'database changed before baseline phase; preserve fixture')
        for path in plan[database]:
            apply(database, source / path)
            completed.append(path)
        expected = sorted(Path(path).stem for path in plan[database])
        require(sorted(connection.query('SHOW TABLES FROM `acore_' + database + '`')) == expected,
                'source core baseline table set differs: ' + database)
    for item in prerequisites + schema_prerequisites:
        current = connection.query('SHOW TABLES FROM `acore_' + item['database'] + '`')
        require(not set(item['tables']).intersection(current),
                'existing prerequisite tables preserved')
        apply(item['database'], source / item['path'])
        completed.append(item['path'])
        require(sorted(connection.query('SHOW TABLES FROM `acore_' + item['database'] + '`')) ==
                sorted(current + item['tables']), 'documented prerequisite table set differs')
    require(not connection.query('SHOW TABLES FROM `acore_playerbots`'),
            'unregistered playerbots database must stay empty')
    return dict(scope='fresh-owned-source-baseline-before-compiled-updates', coreBaseOrder=plan,
                documentedModulePrerequisites=prerequisites, sourceSchemaPrerequisites=schema_prerequisites,
                appliedFiles=completed,
                sourceFiles=identities, syntheticUpdaterLedgerRowsWritten=False,
                compiledAutoPopulationQualified=False, existingStateModified=False,
                baselineImportCompleted=True)
