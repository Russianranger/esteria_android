"""Explicit, empty source-derived schemas for one pinned fresh server profile.

The caller owns/authenticates its engine and holds its exclusive session lease.
Original packaged SQL and updater ledgers are unchanged. This module uses only
the standard library and the shared baseline; it never looks for a C++ checkout.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

try:
    from . import server_schema_baseline as baseline
except ImportError:
    import server_schema_baseline as baseline

SERVER = 'f35f04d01689f034778e3474b3c820092f51e461'
SOURCE_LOCKS = frozenset(('5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1',
                          'dbbf8983cfa2b429f7dd0c3308a2795ffbecd29e8019adf35348447e1eab41b0'))
SQL_PATH = Path(__file__).resolve().parent / 'server/appearance-schema-v1.sql'
LOCK_PATH = SQL_PATH.with_name('appearance-schema.lock.json')
SQL_IDENTITY = dict(bytes=790, sha256='8e35e8e41d74979eaa98f6f2d824d831b73f63a4a6b2f573b869484b2ff15d46')
LOCK_IDENTITY = dict(bytes=7783, sha256='6ccf5e363ec3daa5c37cbbe753d29a7e6b5d10f18eef407b700fc0d67985428d')
TABLES = ('character_body_shape', 'character_retail_look')
SIZES = {'character_body_shape': 49, 'character_retail_look': 132}
require = baseline.require


@dataclass(frozen=True)
class Preparation:
    sql_path: Path
    tables: tuple[str, ...]
    proof: dict


def _metadata():
    require(baseline.file_identity(SQL_PATH) == SQL_IDENTITY, 'Source-derived appearance SQL changed')
    require(baseline.file_identity(LOCK_PATH) == LOCK_IDENTITY, 'Source-derived appearance audit metadata changed')
    def pairs(rows):
        value = {}
        for name, row in rows:
            require(name not in value, 'Duplicate appearance audit metadata field')
            value[name] = row
        return value
    descriptor = os.open(LOCK_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'Nonregular appearance audit metadata')
        raw = stream.read(128 * 1024 + 1)
    require(len(raw) <= 128 * 1024 and
            dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) == LOCK_IDENTITY,
            'Appearance audit metadata bound or identity changed')
    value = json.loads(raw, object_pairs_hook=pairs)
    require(value.get('formatVersion') == 1 and value.get('scope') == 'source-derived-empty-character-appearance-schema' and
            value.get('sourceDerived') is True and value.get('canonicalOriginal') is False and
            value.get('serverRevision') == SERVER and value.get('sql', {}).get('identity') == SQL_IDENTITY and
            set(value.get('supportedSourceSelections', {})) == SOURCE_LOCKS and
            value.get('tables') == {name: dict(guid='INT UNSIGNED NOT NULL', data='BINARY(' + str(SIZES[name]) + ') NOT NULL',
                                             primaryKey=['guid']) for name in TABLES},
            'Unsupported source-derived appearance schema metadata')
    return value


def prepare(manifest):
    """Validate the separate adaptation before SQL; no database or source writes."""
    require(isinstance(manifest, dict) and manifest.get('formatVersion') == 1 and
            manifest.get('scope') == 'source-content-inventory' and manifest.get('contentSha256Complete') is True and
            isinstance(manifest.get('source'), dict) and manifest['source'].get('commit') == SERVER and
            manifest.get('sourceLockSha256') in SOURCE_LOCKS, 'Unsupported source-derived appearance source selection')
    metadata = _metadata()
    require(manifest['source'] == metadata['supportedSourceSelections'][manifest['sourceLockSha256']],
            'Appearance source object differs from its exact source lock')
    proof = dict(formatVersion=1, scope=metadata['scope'], adaptationId=metadata['adaptationId'],
        sourceDerived=True, canonicalOriginal=False, freshEmptyInstanceOnly=True,
        serverSource=manifest['source'], sourceLockSha256=manifest['sourceLockSha256'],
        sqlIdentity=dict(SQL_IDENTITY), metadataIdentity=dict(LOCK_IDENTITY),
        sourceBindings=metadata['sourceBindings'], analogyBindings=metadata['analogyBindings'],
        tables=metadata['tables'], originalSourceFilesUnchanged=True,
        updaterLedgerRowsWritten=False, rowsSeeded=False, sqlExecuted=False,
        exactEmptyTableAdditionVerified=False, existingSaveUpgradesQualified=False,
        worldserverExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
    return Preparation(SQL_PATH, TABLES, proof)


def initialize(connection, source, manifest, apply, *, baseline_initializer=baseline.initialize):
    """Run unchanged canonical baseline, then the separate two-table adaptation.

    Any partial import remains refused on re-entry by the global empty guard.
    ``apply(database, path)`` must use the caller's already owned/authenticated
    engine; this function starts no processes and generates no account/content.
    """
    prepared = prepare(manifest)
    baseline.empty_databases(connection)
    original = baseline_initializer(connection, source, manifest, apply)
    require(original.get('baselineImportCompleted') is True and
            'sourceDerivedAdaptations' not in original, 'Unchanged original source baseline required')
    current = connection.query('SHOW TABLES FROM `acore_characters`')
    require(not set(prepared.tables).intersection(current), 'Existing appearance tables preserved; adaptation is fresh-only')
    require(prepare(manifest) == prepared, 'Appearance adaptation changed during source baseline')
    apply('characters', prepared.sql_path)
    require(sorted(connection.query('SHOW TABLES FROM `acore_characters`')) == sorted(current + list(prepared.tables)),
            'Source-derived appearance table addition differs')
    for name in prepared.tables:
        require(connection.query('SELECT COUNT(*) FROM `acore_characters`.`' + name + '`') == ['0'],
                'Source-derived appearance adaptation must create empty tables only')
    proof = dict(prepared.proof, sqlExecuted=True, exactEmptyTableAdditionVerified=True)
    return dict(original, sourceDerivedAdaptations=[proof])
