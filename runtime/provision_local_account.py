#!/usr/bin/env python3
"""Create one privately owned local player after schemas/updates and realm setup.

Never resets/adopts an existing account, creates a character, or grants privileges.
Credentials live only in accounts/local-player.json and SQL stdin, never argv or
the returned evidence. An interrupted commit is recovered using the durable
intent's exact random salt/verifier; a completed missing account is not recreated.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys

try:
    from . import mysql_bootstrap as db
    from . import provision_local_realm as realm
except ImportError:
    import mysql_bootstrap as db
    import provision_local_realm as realm

N = int('894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7', 16)
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
ACCOUNT_SCHEMA_SHA256 = '0d4e185018ab52b6cbb87ef6f2554e4bc1ae2a8394f0d219ba37631e1661f35a'
TRACKER_SCHEMA_SHA256 = 'ce6b1c44b436373414ed816ee2f14bf2cbf8736d6dd13da8831fea0c10c043e8'
JOURNAL = 'accounts/local-player.json'
require = realm.require

# Reviewed against the exact source CREATE TABLEs. Timestamp spelling is
# normalized below because MySQL reports CURRENT_TIMESTAMP as current_timestamp().
COLUMNS = {
    'account': (
        ('id', 'int unsigned', 'NO', '<NULL>', 'auto_increment'),
        ('username', 'varchar(32)', 'NO', '', ''),
        ('salt', 'binary(32)', 'NO', '<NULL>', ''),
        ('verifier', 'binary(32)', 'NO', '<NULL>', ''),
        ('session_key', 'binary(40)', 'YES', '<NULL>', ''),
        ('totp_secret', 'varbinary(128)', 'YES', '<NULL>', ''),
        ('email', 'varchar(255)', 'NO', '', ''),
        ('reg_mail', 'varchar(255)', 'NO', '', ''),
        ('joindate', 'timestamp', 'NO', 'current_timestamp', 'default_generated'),
        ('last_ip', 'varchar(15)', 'NO', '127.0.0.1', ''),
        ('last_attempt_ip', 'varchar(15)', 'NO', '127.0.0.1', ''),
        ('failed_logins', 'int unsigned', 'NO', '0', ''),
        ('locked', 'tinyint unsigned', 'NO', '0', ''),
        ('lock_country', 'varchar(2)', 'NO', '00', ''),
        ('last_login', 'timestamp', 'YES', '<NULL>', ''),
        ('online', 'int unsigned', 'NO', '0', ''),
        ('expansion', 'tinyint unsigned', 'NO', '2', ''),
        ('Flags', 'int unsigned', 'NO', '0', ''),
        ('mutetime', 'bigint', 'NO', '0', ''),
        ('mutereason', 'varchar(255)', 'NO', '', ''),
        ('muteby', 'varchar(50)', 'NO', '', ''),
        ('locale', 'tinyint unsigned', 'NO', '0', ''),
        ('os', 'varchar(3)', 'NO', '', ''),
        ('recruiter', 'int unsigned', 'NO', '0', ''),
        ('totaltime', 'int unsigned', 'NO', '0', ''),
    ),
    'realmcharacters': (
        ('realmid', 'int unsigned', 'NO', '0', ''),
        ('acctid', 'int unsigned', 'NO', '<NULL>', ''),
        ('numchars', 'tinyint unsigned', 'NO', '0', ''),
    ),
}
INDEXES = {
    'account': ['PRIMARY\t0\t1\tid', 'idx_username\t0\t1\tusername'],
    'realmcharacters': ['PRIMARY\t0\t1\trealmid', 'PRIMARY\t0\t2\tacctid', 'acctid\t1\t1\tacctid'],
}


def verifier(username, password, salt):
    """AccountMgr normalization followed by the pinned SRP6/BigNumber byte order."""
    require(isinstance(username, str) and isinstance(password, str) and
            0 < len(username) <= 17 and 0 < len(password) <= 16, 'Invalid local credential length')
    require(len(salt) == 32, 'Invalid SRP salt length')
    upper = lambda value: ''.join(chr(ord(c) - 32) if 'a' <= c <= 'z' else c for c in value)
    digest = hashlib.sha1((upper(username) + ':' + upper(password)).encode('utf-8')).digest()
    exponent = int.from_bytes(hashlib.sha1(salt + digest).digest(), 'little')
    return pow(7, exponent, N).to_bytes(32, 'little')


def new_intent(receipt):
    username = 'EST' + secrets.token_hex(7).upper()
    password = ''.join(secrets.choice(ALPHABET) for _ in range(16))
    salt = secrets.token_bytes(32)
    return dict(formatVersion=1, serverRevision=realm.SERVER_REVISION, mysqlUuid=receipt['uuid'],
                mysqlVersion=receipt['version'], phase='pending', accountId=None, realmId=1, expansion=2,
                username=username, password=password, saltHex=salt.hex(),
                verifierHex=verifier(username, password, salt).hex())


def validate_intent(intent, receipt):
    require(isinstance(intent, dict) and set(intent) == {
        'formatVersion', 'serverRevision', 'mysqlUuid', 'mysqlVersion', 'phase', 'accountId',
        'realmId', 'expansion', 'username', 'password', 'saltHex', 'verifierHex'}, 'Invalid private account intent')
    require(intent['formatVersion'] == 1 and intent['serverRevision'] == realm.SERVER_REVISION and
            intent['mysqlUuid'] == receipt['uuid'] and intent['mysqlVersion'] == receipt['version'] and
            intent['realmId'] == 1 and intent['expansion'] == 2, 'Private account ownership identity changed')
    require(intent['phase'] in ('pending', 'ready') and
            ((intent['phase'] == 'pending' and intent['accountId'] is None) or
             (intent['phase'] == 'ready' and type(intent['accountId']) is int and 0 < intent['accountId'] < 2**32)),
            'Invalid private account completion state')
    require(isinstance(intent['username'], str) and re.fullmatch('EST[0-9A-F]{14}', intent['username']) and
            isinstance(intent['password'], str) and re.fullmatch('[' + ALPHABET + ']{16}', intent['password']) and
            all(isinstance(intent[k], str) and re.fullmatch('[0-9a-f]{64}', intent[k])
                for k in ('saltHex', 'verifierHex')), 'Invalid private account credentials; preserving them')
    require(hmac.compare_digest(verifier(intent['username'], intent['password'],
                                        bytes.fromhex(intent['saltHex'])).hex(), intent['verifierHex']),
            'Private account credentials disagree; preserving them')


def read_intent(path, receipt):
    path = db.private_path(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        require(stat.S_ISREG(metadata.st_mode) and metadata.st_uid == os.geteuid() and
                metadata.st_nlink == 1 and not metadata.st_mode & 0o077,
                'Private account intent must be an owned, unshared mode-0600 regular file')
        raw = stream.read(8193)
    require(len(raw) <= 8192, 'Private account intent exceeds metadata bound')
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise db.BootstrapError('Invalid private account intent; preserving it') from error
    validate_intent(result, receipt)
    return result


def check_schema(connection):
    for table, expected in COLUMNS.items():
        where = "TABLE_SCHEMA='acore_auth' AND TABLE_NAME='" + table + "'"
        require(connection.query('SELECT ENGINE,TABLE_COLLATION FROM information_schema.TABLES WHERE ' + where)
                == ['InnoDB\tutf8mb4_unicode_ci'], 'Expected source account tables must be loaded first')
        rows = connection.query("SELECT COLUMN_NAME,COLUMN_TYPE,IS_NULLABLE,COALESCE(COLUMN_DEFAULT,'<NULL>'),"
                                "LOWER(EXTRA),COALESCE(COLLATION_NAME,'<NULL>') FROM information_schema.COLUMNS WHERE " + where + ' ORDER BY ORDINAL_POSITION')
        normalized = []
        for row in rows:
            parts = row.split('\t')
            require(len(parts) == 6, 'Unexpected account column metadata')
            if parts[0] == 'joindate' and parts[3].lower() in ('current_timestamp', 'current_timestamp()'):
                parts[3] = 'current_timestamp'
            normalized.append(tuple(parts))
        with_collation = [column + ('utf8mb4_unicode_ci' if column[1].startswith('varchar(') else '<NULL>',) for column in expected]
        require(normalized == with_collation, 'Unexpected account schema; refusing modification')
        indexes = connection.query("SELECT INDEX_NAME,NON_UNIQUE,SEQ_IN_INDEX,COLUMN_NAME,COALESCE(SUB_PART,'<NULL>') "
                                   'FROM information_schema.STATISTICS WHERE ' + where + ' ORDER BY INDEX_NAME,SEQ_IN_INDEX')
        require(sorted(indexes) == sorted(value + '\t<NULL>' for value in INDEXES[table]), 'Unexpected account keys; refusing modification')
        require(connection.query("SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE EVENT_OBJECT_SCHEMA='acore_auth' "
                                 "AND EVENT_OBJECT_TABLE='" + table + "'") == ['0'], 'Account triggers require review')
        require(connection.query('SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE '
                                 "CONSTRAINT_SCHEMA='acore_auth' AND TABLE_NAME='" + table + "'") == ['0'],
                'Account foreign keys require review')


def selected_account(connection, username, *, lock=False):
    # Only generated, validated uppercase ASCII names reach this SQL interpolation.
    require(re.fullmatch('EST[0-9A-F]{14}', username), 'Unsafe private account name')
    return connection.query('SELECT id,username,LOWER(HEX(salt)),LOWER(HEX(verifier)) '
                            "FROM acore_auth.account WHERE username='" + username + "'" + (' FOR UPDATE' if lock else ''))


def match_account(rows, intent):
    require(len(rows) == 1, 'Owned local account is missing or ambiguous; preserving database')
    parts = rows[0].split('\t')
    require(len(parts) == 4 and re.fullmatch('[1-9][0-9]{0,9}', parts[0]), 'Unexpected owned account identity')
    account_id = int(parts[0])
    require(account_id < 2**32 and parts[1] == intent['username'] and
            hmac.compare_digest(parts[2], intent['saltHex']) and
            hmac.compare_digest(parts[3], intent['verifierHex']) and
            (intent['accountId'] is None or account_id == intent['accountId']),
            'Existing account is not the exact owned account; refusing adoption or password reset')
    return account_id


def reject_orphan_state(connection, account_id):
    """A newly allocated numeric id must not inherit old permissions or saves.

    Core auth bases are required. Empty character schemas are accepted only for
    the isolated auth qualification phase; present core character/account tables
    are checked read-only. This does not qualify arbitrary module schemas.
    """
    for table, column in [('account_access', 'id'), ('rbac_account_permissions', 'accountId'),
                          ('account_banned', 'id'), ('account_muted', 'guid'), ('realmcharacters', 'acctid')]:
        require(not connection.query('SELECT `' + column + '` FROM acore_auth.`' + table + '` WHERE `' + column + '`=' +
                                     str(account_id) + ' LIMIT 1 FOR UPDATE'),
                'New account id has preexisting auth state; refusing inheritance')
    present = connection.query("SELECT TABLE_NAME FROM information_schema.TABLES WHERE TABLE_SCHEMA='acore_characters'")
    required = {'characters', 'account_data', 'account_instance_times', 'account_tutorial'}
    require(not present or required.issubset(present), 'Partially loaded character schema; complete all updates first')
    if present:
        for table in sorted(required):
            column = 'account' if table == 'characters' else 'accountId'
            require(not connection.query('SELECT `' + column + '` FROM acore_characters.`' + table + '` WHERE `' + column + '`=' +
                                         str(account_id) + ' LIMIT 1 FOR UPDATE'),
                    'New account id has preexisting character state; refusing inheritance')


def configure_account(connection, state, receipt, *, verify_only=False):
    """Caller verified schemas and owns instance/config locks. No secret is returned."""
    path = db.private_path(state / JOURNAL)
    existing_intent = path.exists()
    require(existing_intent or not verify_only, 'No owned local account to verify')
    intent = read_intent(path, receipt) if existing_intent else new_intent(receipt)
    validate_intent(intent, receipt)
    connection.query('START TRANSACTION')
    try:
        require(connection.query(realm.ROW_SQL + ' FOR UPDATE') == [realm.EXPECTED_ROW],
                'Local realm endpoint changed; complete realm provisioning first')
        before = selected_account(connection, intent['username'], lock=True)
        if not existing_intent:
            require(not before, 'Generated account name already exists; preserving existing account')
            # fsync precedes SQL: unknown commit outcomes can be recovered without
            # changing credentials or creating a second account.
            db.atomic_json(path, intent)
        if not before:
            require(not verify_only and intent['phase'] == 'pending',
                    'Completed local account is missing; refusing recreation')
            connection.query('INSERT INTO acore_auth.account '
                '(username,salt,verifier,expansion,reg_mail,email,joindate) VALUES ('
                "'" + intent['username'] + "',UNHEX('" + intent['saltHex'] + "'),UNHEX('" + intent['verifierHex'] + "'),2,'','',NOW())")
            account_id = match_account(selected_account(connection, intent['username']), intent)
            reject_orphan_state(connection, account_id)
            connection.query('INSERT INTO acore_auth.realmcharacters (realmid,acctid,numchars) VALUES (1,' + str(account_id) + ',0)')
            operation = 'created-owned-account'
        else:
            account_id = match_account(before, intent)
            operation = 'verified-owned-account' if intent['phase'] == 'ready' else 'recovered-owned-commit'
            require(not verify_only or intent['phase'] == 'ready', 'Pending account requires recovery before verification')
        counts = connection.query('SELECT numchars FROM acore_auth.realmcharacters WHERE realmid=1 AND acctid=' + str(account_id) + ' FOR UPDATE')
        require(len(counts) == 1 and re.fullmatch('[0-9]{1,3}', counts[0]) and int(counts[0]) <= 255,
                'Owned realm character tracker is missing; refusing repair')
        connection.query('COMMIT')
    except BaseException:
        try:
            connection.query('ROLLBACK')
        except (db.BootstrapError, OSError):
            pass
        raise
    match_account(selected_account(connection, intent['username']), intent)
    if intent['phase'] != 'ready':
        db.atomic_json(path, intent | {'phase': 'ready', 'accountId': account_id})
    return operation


def provision(mysql, state, version, *, verify_only=False):
    db.exact_version(version)
    state = db.private_path(state)
    require(mysql.is_absolute(), 'MySQL executable path must be absolute')
    with db.state_lock(state), realm.config_lock(state):
        receipt = db.read_receipt(state / 'database-bootstrap.json', version)
        password = db.read_secret(state / 'accounts/database-secret')
        generation = realm.active_config(state, password)
        world = realm.read_text(state / 'config/generations' / generation / 'worldserver.conf')
        require(realm.settings(world, ('Expansion',)) == {'Expansion': '2'}, 'Local account requires reviewed expansion 2')
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            db.check_receipt(receipt, db.identity(connection, version))
            db.check_listener(connection, None)
            require(connection.query('SELECT CURRENT_USER()') in (['esteria@127.0.0.1'], ['esteria@localhost']),
                    'Unexpected authenticated database account')
            for name in ('esteria-local-bootstrap', 'esteria-local-realm', 'esteria-local-account'):
                require(connection.query("SELECT GET_LOCK('" + name + "',0)") == ['1'], 'Another operation owns local account setup')
            realm.check_schema(connection)
            check_schema(connection)
            operation = configure_account(connection, state, receipt, verify_only=verify_only)
            db.check_receipt(receipt, db.identity(connection, version))
        require(realm.active_config(state, password) == generation, 'Configuration changed during account provisioning')
        evidence = dict(formatVersion=1, operation=operation, serverRevision=realm.SERVER_REVISION,
            mysqlVersion=version, configGeneration=generation, realmId=1, expansion=2,
            sourceAccountSha256=ACCOUNT_SCHEMA_SHA256, sourceTrackerSha256=TRACKER_SCHEMA_SHA256,
            scope='one-owned-account-after-caller-completed-all-updates-and-local-realm',
            credentialsPrivate=True, existingCredentialsReset=False, charactersCreated=False,
            authProtocolQualified=False, gameplayQualified=False)
        db.atomic_json(state / 'local-account.json', evidence)
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('provision', 'verify'))
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--mysql', required=True, type=Path)
    parser.add_argument('--expected-version', required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(provision(args.mysql, args.state_root, args.expected_version,
                                   verify_only=args.operation == 'verify'), indent=2))
        return 0
    except (db.BootstrapError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
        # Do not expose JSON parse excerpts, SQL fragments, passwords or verifiers.
        print('Local account setup failed; private state was preserved for diagnosis', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
