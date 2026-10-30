#!/usr/bin/env python3
"""Fresh-fixture MySQL readiness/persistence probe; never a production service launcher.

Run only after the unchanged Android bootstrap wrapper creates this owned test
instance. No credential, SQL text, datadir or database content is exported.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import mysql_bootstrap as bootstrap

STATE = Path('/work/state')
OWNER = Path('/work/.mysql-probe-owner')
MARKER = STATE / '.android-mysql-probe-marker.json'
TABLE = 'acore_characters.esteria_android_probe'


def require(ok, message):
    if not ok:
        raise bootstrap.BootstrapError(message)


def owned_fixture():
    bootstrap.private_path(OWNER)
    require(OWNER.is_file() and OWNER.stat().st_size == 65, 'Missing disposable fixture owner')
    require(re.fullmatch('[a-f0-9]{64}\n', OWNER.read_text()) is not None, 'Invalid disposable fixture owner')
    return OWNER.read_text().strip()


def secret_identity():
    return {name: hashlib.sha256(bootstrap.read_secret(STATE / 'accounts' / name).encode()).hexdigest()
            for name in ('database-secret', 'database-root-secret')}


def check(mode, expected_version, operation):
    owner = owned_fixture()
    bootstrap.exact_version(expected_version)
    require(mode in ('seed', 'verify') and re.fullmatch('[a-f0-9]{32}', operation), 'Invalid probe operation')
    with bootstrap.state_lock(STATE):
        receipt = bootstrap.read_receipt(STATE / 'database-bootstrap.json', expected_version)
        require(receipt['datadir'] == str(STATE / 'database') and
                bootstrap.datadir_uuid(STATE / 'database') == receipt['uuid'], 'Fixture UUID/datadir mismatch')
        secrets_before = secret_identity()
        if mode == 'seed':
            require(not MARKER.exists(), 'Seed operation already recorded; preserve fixture')
            marker = dict(owner=owner, uuid=receipt['uuid'], version=expected_version,
                          nonce=secrets.token_hex(32), credentialIdentities=secrets_before)
        else:
            bootstrap.private_path(MARKER)
            require(MARKER.is_file() and MARKER.stat().st_size <= 4096, 'Missing private persistence marker')
            marker = json.loads(MARKER.read_text())
            require(marker.get('owner') == owner and marker.get('uuid') == receipt['uuid'] and
                    marker.get('version') == expected_version and marker.get('credentialIdentities') == secrets_before and
                    re.fullmatch('[a-f0-9]{64}', marker.get('nonce', '')), 'Persistence marker identity changed')
        run = bootstrap.private_path(STATE / 'run')
        socket = run / 'probe.sock'
        pid = run / 'probe.pid'
        require(not socket.exists() and not pid.exists(), 'Prior probe instance requires ownership inspection')
        config = run / ('probe-' + operation + '.cnf')
        descriptor = os.open(bootstrap.private_path(config), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            output.write('[mysqld]\nskip-networking\nmysqlx=OFF\nsecure-file-priv=NULL\n'
                         'datadir=/work/state/database\nsocket=/work/state/run/probe.sock\n'
                         'pid-file=/work/state/run/probe.pid\ninnodb-buffer-pool-size=128M\n'
                         'performance-schema=OFF\ngeneral-log=OFF\nslow-query-log=OFF\n')
            output.flush(); os.fsync(output.fileno())
        command = ['/usr/sbin/mysqld', '--defaults-file=' + str(config)]
        if os.geteuid() == 0:
            command.append('--user=root')
        capture = bootstrap.EngineCapture(command, STATE / 'logs' / ('probe-' + operation + '.log'))
        process = capture.process
        try:
            ready = False
            with bootstrap.option_file(STATE, 'root', bootstrap.read_secret(STATE / 'accounts/database-root-secret')) as options:
                deadline = time.monotonic() + 150
                while time.monotonic() < deadline:
                    require(process.poll() is None, 'Owned fixture engine exited before readiness')
                    try:
                        with bootstrap.Mysql(Path('/usr/bin/mysql'), options, socket) as connection:
                            bootstrap.check_receipt(receipt, bootstrap.identity(connection, expected_version))
                            require(connection.query('SELECT CURRENT_USER()') == ['root@localhost'], 'Unexpected fixture administrator')
                            require(connection.query('SELECT @@skip_networking') == ['1'], 'Fixture enabled MySQL networking')
                            require(connection.query("SELECT COUNT(*) FROM information_schema.PLUGINS WHERE PLUGIN_NAME='mysqlx' AND PLUGIN_STATUS='ACTIVE'") == ['0'], 'Fixture enabled MySQLX networking')
                        ready = True
                        break
                    except bootstrap.BootstrapError:
                        time.sleep(0.1)
                require(ready, 'Owned fixture SQL authentication timed out')
                bootstrap.verify_application(Path('/usr/bin/mysql'), STATE, expected_version, receipt, socket)
                with bootstrap.Mysql(Path('/usr/bin/mysql'), options, socket) as connection:
                    names = ','.join("'" + name + "'" for name in bootstrap.DATABASES)
                    tables = connection.query('SELECT TABLE_SCHEMA,TABLE_NAME FROM information_schema.TABLES '
                                              'WHERE TABLE_SCHEMA IN (' + names + ') ORDER BY TABLE_SCHEMA,TABLE_NAME')
                    require(tables == ([] if mode == 'seed' else ['acore_characters\testeria_android_probe']),
                            'Fixture contains unrelated application tables')
                    if mode == 'seed':
                        connection.query('CREATE TABLE ' + TABLE + ' (id INT PRIMARY KEY, marker BINARY(32) NOT NULL) ENGINE=InnoDB')
                        connection.query('INSERT INTO ' + TABLE + " VALUES (1,UNHEX('" + marker['nonce'] + "'))")
                    observed = connection.query('SELECT id,LOWER(HEX(marker)) FROM ' + TABLE)
                    require(observed == ['1\t' + marker['nonce']], 'Persistent probe row differs')
                    require(process.poll() is None, 'Owned fixture exited during verification')
        finally:
            try:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=90)
                    except subprocess.TimeoutExpired as error:
                        process.kill(); process.wait(timeout=5)
                        raise bootstrap.BootstrapError('Fixture failed clean shutdown') from error
            finally:
                capture.finish()
        require(process.returncode == 0 and capture.error is None, 'Engine shutdown or diagnostic capture failed')
        require(not socket.exists() and not pid.exists(), 'Clean shutdown left live instance markers')
        require(secret_identity() == secrets_before, 'Persistent credentials changed')
        if mode == 'seed':
            bootstrap.atomic_json(MARKER, marker)
        return dict(formatVersion=1, scope='android-mysql-owned-fixture-sql', operation=mode,
                    version=expected_version, uuid=receipt['uuid'], datadir=receipt['datadir'],
                    rootSqlAuthenticated=True, applicationSqlAuthenticated=True, socketOnly=True,
                    instanceIdentityVerified=True, persistentMarkerVerified=True, credentialsPreserved=True,
                    cleanShutdown=True, restoredAfterRestart=mode == 'verify',
                    productionAdapterQualified=False, arm64Qualified=False, serverSchemasQualified=False,
                    worldserverQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operation', choices=('seed', 'verify'), required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--operation-id', required=True)
    args = parser.parse_args()
    try:
        require(re.fullmatch('[a-f0-9]{32}', args.operation_id), 'Invalid operation identity')
        output = bootstrap.private_path(Path('/work/probe-results') / (args.operation_id + '.json'))
        require(not output.exists(), 'Probe result already exists')
        result = check(args.operation, args.expected_version, args.operation_id)
        bootstrap.atomic_json(output, result)
        print('PASS: owned MySQL fixture authenticated, persisted and stopped (' + args.operation + ')')
        return 0
    except Exception as error:
        print('MySQL fixture failed (' + type(error).__name__ + '); private state retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
