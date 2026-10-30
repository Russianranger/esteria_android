#!/usr/bin/env python3
"""Reassert and verify only the local realm row after ALL source/module updates.

This is neither a schema loader nor server readiness. It requires the already
owned/authenticated MySQL instance, exact realmlist schema, and an intact active
configuration generation. Existing non-network fields and other realms remain.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

try:
    from . import mysql_bootstrap as db
except ImportError:
    import mysql_bootstrap as db

ROOT = Path(__file__).resolve().parents[1]
SERVER_REVISION = 'f35f04d01689f034778e3474b3c820092f51e461'
SCHEMA_SHA256 = 'b5c6d72b407dddb070a2ee497aa0500175c02f1a5288ee2716513821de71e78c'
CONFIG_FILES = ('authserver.conf', 'worldserver.conf', 'modules/playerbots.conf', 'mysql.cnf')
MAX_CONFIG = 2 * 1024 * 1024
MAX_MODULE_CONFIG = 4 * 1024 * 1024
MAX_GENERATION_CONFIG = 20 * 1024 * 1024
REALM_ID, WORLD_PORT, AUTH_PORT, CLIENT_BUILD = 1, 8085, 3724, 12340
LOOPBACK, SUBNET = '127.0.0.1', '255.255.255.255'
EXPECTED_ROW = f'{REALM_ID}\t{LOOPBACK}\t{LOOPBACK}\t{SUBNET}\t{WORLD_PORT}\t{CLIENT_BUILD}'
COLUMNS = (
    ('id', 'int unsigned', 'NO', '<NULL>', 'auto_increment'),
    ('name', 'varchar(32)', 'NO', '', ''),
    ('address', 'varchar(255)', 'NO', '127.0.0.1', ''),
    ('localAddress', 'varchar(255)', 'NO', '127.0.0.1', ''),
    ('localSubnetMask', 'varchar(255)', 'NO', '255.255.255.0', ''),
    ('port', 'smallint unsigned', 'NO', '8085', ''),
    ('icon', 'tinyint unsigned', 'NO', '0', ''),
    ('flag', 'tinyint unsigned', 'NO', '2', ''),
    ('timezone', 'tinyint unsigned', 'NO', '0', ''),
    ('allowedSecurityLevel', 'tinyint unsigned', 'NO', '0', ''),
    ('population', 'float', 'NO', '0', ''),
    ('gamebuild', 'int unsigned', 'NO', '12340', ''),
)
ROW_SQL = ('SELECT `id`,`address`,`localAddress`,`localSubnetMask`,`port`,`gamebuild` '
           'FROM `acore_auth`.`realmlist` WHERE `id`=1')


def require(condition, message):
    if not condition:
        raise db.BootstrapError(message)


def read_text(path, maximum=MAX_CONFIG):
    path = db.private_path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, 'Configuration must be an unshared regular file')
        require(before.st_size <= maximum, 'Configuration exceeds metadata bound')
        raw = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Configuration changed while reading')
    require(len(raw) == before.st_size and len(raw) <= maximum, 'Configuration exceeds metadata bound')
    return raw.decode('utf-8')


def settings(text, selected):
    result = {}
    for line in text.splitlines():
        match = re.match(r'^\s*([A-Za-z0-9_.]+)\s*=\s*(.*?)\s*$', line)
        if match and match[1] in selected:
            require(match[1] not in result, 'Duplicate local endpoint configuration key')
            result[match[1]] = match[2]
    require(set(result) == set(selected), 'Missing required local endpoint configuration key')
    return result


def generation_files(directory):
    """Read the exact legacy or complete-module generation without following links."""
    directory = db.private_path(directory)
    require(stat.S_ISDIR(directory.lstat().st_mode), 'Configuration generation must be a directory')
    proof_name = 'module-configuration.json'
    files = {}
    if os.path.lexists(directory / proof_name):
        files[proof_name] = read_text(directory / proof_name)
        def pairs(rows):
            result = {}
            for name, value in rows:
                require(name not in result, 'Duplicate module configuration proof field')
                result[name] = value
            return result
        proof = json.loads(files[proof_name], object_pairs_hook=pairs)
        require(isinstance(proof, dict) and type(proof.get('formatVersion')) is int and
                proof['formatVersion'] == 1 and
                proof.get('scope') == 'prepared-module-configurations-not-startup-qualified' and
                isinstance(proof.get('sourceLockSha256'), str) and
                re.fullmatch('[0-9a-f]{64}', proof['sourceLockSha256']) and
                proof.get('moduleStartupQualified') is False and proof.get('gameplayQualified') is False and
                all(value is False for name, value in proof.items() if name.endswith('Qualified')),
                'Invalid prepared module configuration proof')
        names = proof.get('configFiles')
        require(isinstance(names, list) and 1 <= len(names) <= 512 and
                all(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_.-]+\.conf', name) for name in names) and
                len(names) == len({name.casefold() for name in names}) and 'playerbots.conf' in names,
                'Invalid or ambiguous module configuration file selection')
        expected = {'authserver.conf', 'worldserver.conf', 'mysql.cnf', proof_name} | {
            'modules/' + name for name in names}
    else:
        expected = set(CONFIG_FILES)

    def scan():
        seen = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if entry.name == 'modules':
                    require(stat.S_ISDIR(info.st_mode), 'Configuration modules must be an unlinked directory')
                    with os.scandir(db.private_path(directory / entry.name)) as modules:
                        for module in modules:
                            name = 'modules/' + module.name
                            info = module.stat(follow_symlinks=False)
                            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and name in expected,
                                    'Configuration generation has an unexpected module file, link or directory')
                            seen.add(name)
                            require(len(seen) <= len(expected), 'Configuration generation file count exceeds bound')
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and entry.name in expected,
                            'Configuration generation has an unexpected file, link or directory')
                    seen.add(entry.name)
        require(seen == expected, 'Configuration generation file set differs from its declared selection')

    scan()
    total = len(files.get(proof_name, '').encode('utf-8'))
    for name in sorted(expected - set(files)):
        maximum = MAX_MODULE_CONFIG if name.startswith('modules/') else MAX_CONFIG
        files[name] = read_text(directory / name, maximum)
        total += len(files[name].encode('utf-8'))
        require(total <= MAX_GENERATION_CONFIG, 'Configuration generation exceeds total metadata bound')
    scan()
    return files


def active_config(state, password):
    """Resolve only the renderer's contained generation pointer, not arbitrary links."""
    current = state / 'config/current'
    db.private_path(current.parent)
    require(current.is_symlink(), 'No active rendered configuration generation')
    target = os.readlink(current)
    require(re.fullmatch(r'generations/[0-9a-f]{64}', target), 'Invalid active configuration pointer')
    directory = db.private_path(current.parent / target)
    files = generation_files(directory)
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    require(digest == target.split('/')[1], 'Active configuration generation has changed')
    auth = settings(files['authserver.conf'], ('BindIP', 'RealmServerPort', 'LoginDatabaseInfo'))
    world = settings(files['worldserver.conf'], ('BindIP', 'RealmID', 'WorldServerPort', 'LoginDatabaseInfo'))
    connection = f'"127.0.0.1;{db.PORT};esteria;{password};acore_auth"'
    require(auth == {'BindIP': '"127.0.0.1"', 'RealmServerPort': str(AUTH_PORT), 'LoginDatabaseInfo': connection},
            'Auth configuration is not the owned loopback endpoint')
    require(world == {'BindIP': '"127.0.0.1"', 'RealmID': str(REALM_ID),
                      'WorldServerPort': str(WORLD_PORT), 'LoginDatabaseInfo': connection},
            'World configuration is not local realm 1 on port 8085')
    profile = json.loads(read_text(ROOT / 'config/local-server.json'))
    require(all(profile.get(key) == value for key, value in
                (('database_port', db.PORT), ('auth_port', AUTH_PORT), ('world_port', WORLD_PORT),
                 ('client_build', CLIENT_BUILD))), 'Local endpoint policy changed; realm provisioning needs review')
    lock = json.loads(read_text(ROOT / 'sources.lock.json'))
    require(lock.get('sources', {}).get('server', {}).get('commit') == SERVER_REVISION and
            lock.get('compatibility', {}).get('base_client_build') == CLIENT_BUILD,
            'Server/schema source pin changed; realm provisioning needs review')
    return digest


@contextmanager
def config_lock(state):
    path = db.private_path(state / 'config/.render.lock')
    with path.open('a') as stream:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise db.BootstrapError('Configuration rendering is in progress') from error
        yield


def check_schema(connection):
    require(connection.query("SELECT ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA='acore_auth' "
                             "AND TABLE_NAME='realmlist'") == ['InnoDB'],
            'Matching InnoDB realmlist table must be loaded before realm provisioning')
    columns = connection.query("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COALESCE(COLUMN_DEFAULT,'<NULL>'),EXTRA "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA='acore_auth' AND TABLE_NAME='realmlist' "
        "ORDER BY ORDINAL_POSITION")
    require(columns == ['\t'.join(column) for column in COLUMNS], 'Unexpected realmlist schema; refusing modification')
    indexes = connection.query("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME "
        "FROM information_schema.STATISTICS WHERE TABLE_SCHEMA='acore_auth' AND TABLE_NAME='realmlist' "
        "ORDER BY INDEX_NAME,SEQ_IN_INDEX")
    require(sorted(indexes) == sorted(['PRIMARY\t0\t1\tid', 'idx_name\t0\t1\tname']),
            'Unexpected realmlist keys; refusing modification')
    require(connection.query("SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE EVENT_OBJECT_SCHEMA='acore_auth' "
                             "AND EVENT_OBJECT_TABLE='realmlist'") == ['0'],
            'Realmlist triggers require review before local provisioning')


def configure_row(connection, *, verify_only=False):
    """Caller owns instance locks and has verified the exact existing schema."""
    connection.query('START TRANSACTION')
    try:
        before = connection.query(ROW_SQL + ' FOR UPDATE')
        require(len(before) <= 1, 'Realm primary key is not unique')
        if verify_only:
            require(before == [EXPECTED_ROW], 'Local realm endpoint changed; reassert it after all SQL updates')
            operation = 'verified'
        elif not before:
            connection.query("INSERT INTO `acore_auth`.`realmlist` "
                "(`id`,`name`,`address`,`localAddress`,`localSubnetMask`,`port`,`gamebuild`) "
                "VALUES (1,'Esteria','127.0.0.1','127.0.0.1','255.255.255.255',8085,12340)")
            operation = 'inserted-local-row'
        elif before == [EXPECTED_ROW]:
            operation = 'already-local'
        else:
            # Deliberately no REPLACE/UPSERT: a name-key collision must not affect
            # another realm, and unrelated settings/characters are never reset.
            connection.query("UPDATE `acore_auth`.`realmlist` SET `address`='127.0.0.1',"
                "`localAddress`='127.0.0.1',`localSubnetMask`='255.255.255.255',`port`=8085,`gamebuild`=12340 "
                "WHERE `id`=1")
            operation = 'reasserted-local-row'
        require(connection.query(ROW_SQL) == [EXPECTED_ROW], 'Realm endpoint did not match before commit')
        connection.query('COMMIT')
    except BaseException:
        try:
            connection.query('ROLLBACK')
        except (db.BootstrapError, OSError):
            pass
        raise
    require(connection.query(ROW_SQL) == [EXPECTED_ROW], 'Realm endpoint changed after commit')
    return operation


def provision(mysql, state, version, *, verify_only=False):
    db.exact_version(version)
    state = db.private_path(state)
    require(mysql.is_absolute(), 'MySQL executable path must be absolute')
    # Shared with bootstrap: never run concurrently with initialization/recovery.
    with db.state_lock(state), config_lock(state):
        receipt = db.read_receipt(state / 'database-bootstrap.json', version)
        password = db.read_secret(state / 'accounts/database-secret')
        generation = active_config(state, password)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            observed = db.identity(connection, version)
            db.check_receipt(receipt, observed)
            db.check_listener(connection, None)
            require(connection.query('SELECT CURRENT_USER()') in
                    (['esteria@127.0.0.1'], ['esteria@localhost']), 'Unexpected authenticated database account')
            for name in ('esteria-local-bootstrap', 'esteria-local-realm'):
                require(connection.query(f"SELECT GET_LOCK('{name}', 0)") == ['1'],
                        'Another operation owns the local MySQL instance')
            check_schema(connection)
            operation = configure_row(connection, verify_only=verify_only)
            db.check_receipt(receipt, db.identity(connection, version))
        require(active_config(state, password) == generation, 'Configuration changed during realm provisioning')
        evidence = {'format': 1, 'operation': operation, 'mysqlVersion': version, 'mysqlUuid': receipt['uuid'],
            'serverRevision': SERVER_REVISION, 'sourceRealmlistSha256': SCHEMA_SHA256,
            'configGeneration': generation, 'realmId': REALM_ID, 'address': LOOPBACK,
            'localAddress': LOOPBACK, 'localSubnetMask': SUBNET, 'worldPort': WORLD_PORT,
            'authPort': AUTH_PORT, 'clientBuild': CLIENT_BUILD, 'sqlEndpointVerified': True,
            'scope': 'local-realm-row-only-after-caller-completed-all-updates',
            'serverStarted': False, 'gameSchemaSetQualified': False, 'gameplayQualified': False}
        db.atomic_json(state / 'realm-loopback.json', evidence)
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('provision', 'verify'))
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--mysql', type=Path, required=True)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        result = provision(args.mysql, args.state_root, args.expected_version, verify_only=args.operation == 'verify')
        print(json.dumps(result, indent=2))
        return 0
    except (db.BootstrapError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f'Local realm provisioning failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
