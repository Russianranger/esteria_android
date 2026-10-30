#!/usr/bin/env python3
"""Exact source baseline for a new, exclusively owned empty server instance.

The caller supplies authenticated ownership and a verified content manifest. This
helper never adopts an existing or partially initialized database, synthesizes
updater ledger rows, discovers arbitrary module bases, or retries a failed import.
"""
from pathlib import Path

from tools import qualify_base_sql as base, verify_server_build as files

DATABASES = ('auth', 'characters', 'world')
NEMESIS_MODULE = 'mod-nemesis-system'
NEMESIS_BASE = 'modules/mod-nemesis-system/data/sql/db-characters/base/nemesis_system.sql'
NEMESIS_IDENTITY = dict(bytes=3511,
    sha256='011af71320bd68d81f38f5e28b83b85b5be07b6f08f7c798429d71ea7a66b793',
    gitBlob='30eaf2801e7688213a0aac5d410028193bd621d2')
NEMESIS_TABLES = ('character_nemesis', 'character_nemesis_monthly_kills')
require = base.content.require


def selected_plan(source, manifest):
    """Verify every selected byte before the first SQL statement can execute."""
    require(manifest.get('source', {}).get('commit') == base.content.SUPPORTED_SERVER and
            manifest.get('contentSha256Complete') is True, 'verified pinned source content required')
    plan = {}
    identities = {}
    for database in DATABASES:
        root = base.content.DATABASES[database][1]
        expected = sorted(path for path in manifest['files']
                          if str(Path(path).parent) == root and path.endswith('.sql'))
        require(len(expected) == base.BASE_COUNTS[database] and
                manifest['databases'][database]['base'] == expected,
                'exact pinned immediate core base order required: ' + database)
        plan[database] = expected
        for path in expected:
            row = manifest['files'][path]
            identities[path] = {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}
    prerequisites = []
    if NEMESIS_MODULE in manifest['enabledModules']:
        row = manifest['files'].get(NEMESIS_BASE, {})
        require({key: row.get(key) for key in NEMESIS_IDENTITY} == NEMESIS_IDENTITY,
                'documented nemesis source prerequisite changed')
        require(any(row == dict(path=NEMESIS_BASE, state='MODULE', origin=NEMESIS_MODULE)
                    for row in manifest['databases']['characters']['updateOrder']),
                'nemesis prerequisite is absent from the actual updater selection')
        identities[NEMESIS_BASE] = NEMESIS_IDENTITY
        prerequisites.append(dict(database='characters', path=NEMESIS_BASE,
                                  tables=list(NEMESIS_TABLES), source=NEMESIS_IDENTITY))
    for path, row in identities.items():
        require(files.identity(source / path) == {key: row[key] for key in ('bytes', 'sha256')},
                'baseline source bytes differ before initialization: ' + path)
    return plan, prerequisites, identities


def initialize(connection, source, manifest, apply):
    """Apply source SQL only after every database is proven empty; no resume mode.

    `apply(database_name, source_path)` must use the caller's owned authenticated
    engine. Its exception aborts this invocation and leaves the partial fixture.
    The unmodified core bases include their original ledgers. Only the compiled
    updater records subsequent canonical module/update hashes.
    """
    plan, prerequisites, identities = selected_plan(source, manifest)
    base.empty_databases(connection)  # Includes playerbots, before ANY SQL.
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
    for item in prerequisites:
        current = connection.query('SHOW TABLES FROM `acore_' + item['database'] + '`')
        require(not set(item['tables']).intersection(current),
                'existing module prerequisite tables preserved')
        apply(item['database'], source / item['path'])
        completed.append(item['path'])
        require(sorted(connection.query('SHOW TABLES FROM `acore_' + item['database'] + '`')) ==
                sorted(current + item['tables']), 'documented prerequisite table set differs')
    require(not connection.query('SHOW TABLES FROM `acore_playerbots`'),
            'unregistered playerbots database must stay empty')
    return dict(scope='fresh-owned-source-baseline-before-compiled-updates', coreBaseOrder=plan,
                documentedModulePrerequisites=prerequisites, appliedFiles=completed,
                sourceFiles=identities, syntheticUpdaterLedgerRowsWritten=False,
                compiledAutoPopulationQualified=False, existingStateModified=False,
                baselineImportCompleted=True)
