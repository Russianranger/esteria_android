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


def _active_generation(state, password):
    """Resolve and validate one contained generation without repository policy reads."""
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
    return digest, files


def active_config(state, password):
    """Host policy adapter; existing CLI/source gates remain unchanged."""
    digest, _files = _active_generation(state, password)
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


def verified_sources(content, requirements):
    """Recheck source-bound bytes without a checkout, Git, or a ROOT lookup."""
    try:
        from . import server_content as packaged, server_schema_baseline as baseline
    except ImportError:
        import server_content as packaged
        import server_schema_baseline as baseline
    require(isinstance(content, packaged.VerifiedContent) and content.source == content.root / 'source',
            'Verified extracted provisioning content required')
    require(content.manifest.get('source') == content.receipt.get('source') == content.compiled.get('source') and
            content.manifest['source'].get('commit') == SERVER_REVISION and
            content.manifest.get('sourceLockSha256') == content.receipt.get('sourceLockSha256') ==
            content.compiled.get('sourceLockSha256'), 'Provisioning source selection differs')
    for name, expected in (('content-manifest', content.manifest), ('compiled-modules', content.compiled)):
        relative = 'metadata/' + name + '.json'
        pin = content.identities['files'].get(relative)
        require(pin == content.receipt['archiveFiles'].get(relative) and
                baseline.file_identity(content.root / relative) == pin and
                json.loads(read_text(content.root / relative, 16 * 1024**2)) == expected,
                'Provisioning metadata changed after content verification')
    for name, digest in requirements.items():
        require(isinstance(name, str) and re.fullmatch('[A-Za-z0-9_]+', name) and
                isinstance(digest, str) and re.fullmatch('[a-f0-9]{64}', digest), 'Invalid provisioning source schema pin')
        relative = 'data/sql/base/db_auth/' + name + '.sql'
        pin = content.manifest['files'].get(relative)
        require(isinstance(pin, dict) and pin.get('sha256') == digest,
                'Reviewed provisioning source schema differs')
        identity = {key: pin[key] for key in ('bytes', 'sha256')}
        archive = content.receipt['archiveFiles'].get('source/' + relative, {})
        require(identity == content.identities['files'].get('source/' + relative) and
                identity == {key: archive.get(key) for key in identity} and
                baseline.file_identity(content.source / relative) == identity,
                'Packaged provisioning source schema changed')


def active_config_verified(content, state, password, *, profile, data, mysql):
    """Compare every private config byte with the source/policy renderer; no ROOT."""
    try:
        from . import server_config as configurations
    except ImportError:
        import server_config as configurations
    expected = configurations.expected_private_files_verified(content, state, Path(data), Path(mysql),
        profile=profile, secret=password)
    digest, files = _active_generation(state, password)
    require(files == expected, 'Active complete configuration differs from verified source and local policy')
    require(settings(files['worldserver.conf'], ('Expansion',)) == {'Expansion': '2'},
            'Local runtime provisioning requires reviewed expansion 2')
    return digest


@contextmanager
def named_locks(connection, names):
    """Release only this invocation's acquisitions on a caller-owned connection."""
    acquired = []
    try:
        for name in names:
            require(name in ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account'),
                    'Unexpected provisioning lock name')
            require(connection.query("SELECT GET_LOCK('" + name + "',0)") == ['1'],
                    'Another operation owns local provisioning')
            acquired.append(name)
        yield
    finally:
        failed = False
        for name in reversed(acquired):
            try:
                failed = connection.query("SELECT RELEASE_LOCK('" + name + "')") != ['1'] or failed
            except Exception:
                failed = True
        require(not failed, 'Provisioning SQL lock release failed; owned service retained')


@contextmanager
def _verified_context(content, connection, state, version, *, profile, data, mysql, expected_uuid, verify_service,
                     account_schemas=None, account_lock=False, state_lease=None):
    """Caller retains its live engine/service lease. This helper owns no process.

    The completed compiled-updater verifier is read-only and inherits these
    state/bootstrap locks; it never releases them or imports host tooling.
    """
    try:
        from . import server_schema_setup as schema, server_schema_baseline as baseline, server_update_setup as updates
    except ImportError:
        import server_schema_setup as schema
        import server_schema_baseline as baseline
        import server_update_setup as updates
    db.exact_version(version)
    require(callable(verify_service) and isinstance(expected_uuid, str) and
            re.fullmatch('[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', expected_uuid),
            'Explicit live service verifier and instance UUID required')
    require(Path(state).is_absolute(), 'Absolute owned provisioning state required')
    state = db.private_path(Path(state))
    require(account_schemas is None or set(account_schemas) == {'account', 'realmcharacters'},
            'Only reviewed account schema sources may extend realm provisioning')
    requirements = {'realmlist': SCHEMA_SHA256} | (account_schemas or {})
    verified_sources(content, requirements)
    with db.state_scope(state, state_lease), config_lock(state):
        receipt = db.read_receipt(state / 'database-bootstrap.json', version)
        require(receipt['uuid'] == expected_uuid and receipt['datadir'] == str(state / 'database') and
                db.datadir_uuid(state / 'database') == expected_uuid, 'Provisioning instance identity changed')
        credentials = schema.credential_identity(state)
        password = db.read_secret(state / 'accounts/database-secret')
        generation = active_config_verified(content, state, password, profile=profile, data=data, mysql=mysql)
        locks = ('esteria-local-bootstrap', 'esteria-local-realm') + (('esteria-local-account',) if account_lock else ())
        with named_locks(connection, locks):
            require(verify_service() is not False, 'Owned provisioning service changed')
            db.check_receipt(receipt, db.identity(connection, version)); db.check_listener(connection, None)
            require(connection.query('SELECT CURRENT_USER()') in (['esteria@127.0.0.1'], ['esteria@localhost']),
                    'Unexpected authenticated provisioning account')
            completed = updates.verify_completed_update(content, connection, state, version,
                expected_uuid=expected_uuid, verify_service=verify_service)
            updater_identity = baseline.file_identity(state / updates.JOURNAL)
            yield receipt, generation, completed
            require(baseline.file_identity(state / updates.JOURNAL) == updater_identity and
                    schema.credential_identity(state) == credentials and
                    active_config_verified(content, state, password, profile=profile, data=data, mysql=mysql) == generation,
                    'Updater journal, credentials or configuration changed during provisioning')
            verified_sources(content, requirements)
            db.check_receipt(receipt, db.identity(connection, version)); db.check_listener(connection, None)
            require(verify_service() is not False, 'Owned provisioning service changed')


def provision_verified(content, connection, state, version, *, profile, data, mysql, expected_uuid, verify_service, verify_only=False, state_lease=None):
    """Provision only realm 1 after the real owned updater/ledger gate completes."""
    try:
        from . import server_schema_setup as schema
    except ImportError:
        import server_schema_setup as schema
    state = Path(state)
    with _verified_context(content, connection, state, version, profile=profile, data=data, mysql=mysql, expected_uuid=expected_uuid,
                          verify_service=verify_service, state_lease=state_lease) as (receipt, generation, completed):
        account_before = schema.account_identity(state)
        check_schema(connection)
        operation = configure_row(connection, verify_only=verify_only)
        require(schema.account_identity(state) == account_before, 'Private account intent changed during realm provisioning')
    evidence = dict(formatVersion=1, scope='owned-verified-content-local-realm-after-compiled-updater',
        operation=operation, mysqlUuid=receipt['uuid'], mysqlVersion=version, serverRevision=SERVER_REVISION,
        sourceLockSha256=content.receipt['sourceLockSha256'], contentReceipt=content.identities['receipt'],
        compiledModules=content.receipt['compiledModules'], configGeneration=generation,
        sourceRealmlistSha256=SCHEMA_SHA256, realmId=REALM_ID, address=LOOPBACK, localAddress=LOOPBACK,
        localSubnetMask=SUBNET, worldPort=WORLD_PORT, authPort=AUTH_PORT, clientBuild=CLIENT_BUILD,
        sqlEndpointVerified=True, completedUpdaterVerified=completed['compiledUpdaterCompleted'],
        serverStarted=False, gameSchemaSetQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    db.atomic_json(state / 'realm-loopback.json', evidence)
    return evidence


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
