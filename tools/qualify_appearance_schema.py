#!/usr/bin/env python3
"""Actual native MySQL storage/restart gate for the explicit empty adaptation.

Uses only a fresh disposable instance. This is binary table persistence, not
client wire parsing, original SQL qualification, characters, assets or gameplay.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import tarfile

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import qualify_base_sql as base, manifest_server_modules as modules, verify_server_build as files
from runtime import mysql_bootstrap as db, server_schema_adaptations as adaptation

require = base.content.require
GUID = 4294967280
MAX_METADATA = 16 * 1024**2


def selected_manifest(content, receipt_sha256, lock_path):
    receipt, identity = modules.read_json(content / 'package-receipt.json')
    pin, lock_sha = base.locked_source(lock_path)
    require(identity['sha256'] == receipt_sha256 and receipt.get('formatVersion') == 1 and
            receipt.get('scope') == 'immutable-server-source-content-package' and receipt.get('source') == pin and
            receipt.get('sourceLockSha256') == lock_sha and receipt.get('moduleSelectionVerified') is True and
            receipt.get('archiveReadBackVerified') is True, 'verified content receipt required for appearance gate')
    archive = content / 'server-content.tar.gz'
    require(files.identity(archive) == receipt['archive'], 'appearance source-content archive changed')
    target = 'metadata/content-manifest.json'; expected = receipt['archiveFiles'][target]
    require(0 < expected['bytes'] <= MAX_METADATA, 'appearance manifest size bound')
    with files.plain_file(archive) as incoming, tarfile.open(fileobj=incoming, mode='r|gz') as stream:
        for number, member in enumerate(stream):
            require(number < files.MAX_FILES, 'appearance content entry count bound')
            if member.name != target: continue
            require(member.isfile() and member.size == expected['bytes'], 'appearance manifest member differs')
            with stream.extractfile(member) as source: raw = source.read(MAX_METADATA + 1)
            require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) ==
                    {key: expected[key] for key in ('bytes', 'sha256')}, 'appearance manifest bytes differ')
            manifest = json.loads(raw)
            require(manifest.get('source') == pin and manifest.get('sourceLockSha256') == lock_sha and
                    manifest.get('contentSha256Complete') is True, 'appearance manifest source differs')
            return manifest, identity
    raise ValueError('appearance source manifest missing')


def schemas(connection, tables):
    result = {}
    for name, length in zip(tables, (49, 132)):
        table = '`acore_characters`.`' + name + '`'
        rows = connection.query("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COLUMN_KEY FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA='acore_characters' AND TABLE_NAME='" + name + "' ORDER BY ORDINAL_POSITION")
        require(rows == ['guid\tint unsigned\tNO\tPRI', 'data\tbinary(' + str(length) + ')\tNO\t'],
                'source-derived appearance field contract differs')
        require(connection.query("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='acore_characters' "
                "AND TABLE_NAME='" + name + "'") == ['InnoDB'], 'appearance table must use transactional InnoDB')
        require(connection.query("SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE EVENT_OBJECT_SCHEMA='acore_characters' "
                "AND EVENT_OBJECT_TABLE='" + name + "'") == ['0'], 'appearance triggers are unsupported')
        result[name] = dict(columns=rows, engine='InnoDB', binaryBytes=length)
    return result


def payload(length, alternate=False):
    raw = bytes((index * 73 + 181) % 256 for index in range(length))
    # Both values deliberately contain NUL/high bytes; payload validity is not
    # claimed, because this gate exercises raw MySQL binary transport only.
    return (bytes([0, 255, 128]) + raw[3:])[::-1] if alternate else bytes([0, 255, 128]) + raw[3:]


def rows(connection, table, expected):
    require(connection.query('SELECT guid,OCTET_LENGTH(data),HEX(data) FROM `acore_characters`.`' + table + '` ORDER BY guid') ==
            [str(guid) + '\t' + str(len(data)) + '\t' + data.hex().upper() for guid, data in sorted(expected.items())],
            'appearance binary rows differ')


def qualify(content, receipt_sha256, lock_path, mysql, mysqld, version, output):
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native Linux ARM64 appearance storage qualification required')
    db.exact_version(version); output = db.private_path(output)
    require(not os.path.lexists(output), 'existing appearance qualification preserved')
    manifest, content_receipt = selected_manifest(content, receipt_sha256, lock_path)
    plan = adaptation.prepare(manifest)  # All audited identities before an engine or SQL.
    output.mkdir(mode=0o700); state = output / 'private-state'; state.mkdir(mode=0o700)
    evidence = dict(formatVersion=1, scope='native-arm64-source-derived-appearance-binary-storage-only',
        qualificationSucceeded=False, adaptation=plan.proof, contentReceipt=content_receipt,
        binaryRoundtripVerified=False, replaceReadDeleteVerified=False, cleanRestartPersistenceVerified=False,
        fixtureRowsRemoved=False, originalSourceSchemasQualified=False, cppWirePayloadParsingQualified=False,
        characterCreationQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    capture = None
    try:
        password = db.read_secret(state / 'accounts/database-secret', create=True)
        with db.state_lock(state):
            bootstrap = db.initialize(mysqld, mysql, state, version)
            evidence['mysqlVersion'] = version; evidence['mysqlUuid'] = bootstrap['uuid']
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/appearance-first-engine.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(connection.query("SELECT GET_LOCK('esteria-local-bootstrap',0)") == ['1'], 'appearance instance busy')
                base.empty_databases(connection)
                base.apply_base(mysql, options, 'acore_characters', plan.sql_path, state / 'logs/appearance-sql-private.log')
                require(sorted(connection.query('SHOW TABLES FROM `acore_characters`')) == sorted(plan.tables),
                        'appearance adaptation created unexpected tables')
                evidence['schemas'] = schemas(connection, plan.tables)
                evidence['adaptation'] = dict(plan.proof, sqlExecuted=True, exactEmptyTableAdditionVerified=True)
                for table, length in zip(plan.tables, (49, 132)):
                    first, second = payload(length), payload(length, True)
                    rows(connection, table, {})
                    for value in (first, second):
                        connection.query('REPLACE INTO `acore_characters`.`' + table + '` (guid,data) VALUES (' +
                                         str(GUID) + ',UNHEX(\'' + value.hex() + '\'))')
                        rows(connection, table, {GUID: value})
                    connection.query('REPLACE INTO `acore_characters`.`' + table + '` (guid,data) VALUES (' +
                                     str(GUID + 1) + ',UNHEX(\'' + first.hex() + '\'))')
                    rows(connection, table, {GUID: second, GUID + 1: first})
                    connection.query('DELETE FROM `acore_characters`.`' + table + '` WHERE guid=' + str(GUID + 1))
                    rows(connection, table, {GUID: second})
                evidence['binaryRoundtripVerified'] = evidence['replaceReadDeleteVerified'] = True
            base.stop_owned(capture); capture = None
            capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/appearance-restart-engine.log')
            base.wait_owned(mysql, state, version, capture)
            with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
                require(schemas(connection, plan.tables) == evidence['schemas'], 'appearance schema changed on restart')
                for table, length in zip(plan.tables, (49, 132)):
                    rows(connection, table, {GUID: payload(length, True)})
                    connection.query('DELETE FROM `acore_characters`.`' + table + '` WHERE guid=' + str(GUID))
                    rows(connection, table, {})
                evidence['cleanRestartPersistenceVerified'] = evidence['fixtureRowsRemoved'] = True
            base.stop_owned(capture); capture = None
            evidence['qualificationSucceeded'] = True
            return evidence
    except Exception as error:
        evidence['failureClass'] = type(error).__name__
        locations = []; current = error.__traceback__
        while current is not None:
            if current.tb_frame.f_code.co_filename == __file__:
                locations.append(current.tb_frame.f_code.co_name + ':' + str(current.tb_lineno))
            current = current.tb_next
        evidence['failureLocations'] = locations[-6:]
        raise
    finally:
        try:
            if capture is not None: base.stop_owned(capture)
        finally:
            db.atomic_json(output / 'appearance-qualification.json', evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('content', 'lock', 'mysql', 'mysqld', 'output'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--content-receipt-sha256', required=True); parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        result = qualify(args.content, args.content_receipt_sha256, args.lock, args.mysql, args.mysqld,
                         args.expected_version, args.output)
        print(json.dumps(result, indent=2)); return 0
    except Exception:
        print('Appearance binary storage qualification failed; private state/logs preserved', file=sys.stderr)
        return 1


if __name__ == '__main__': raise SystemExit(main())
