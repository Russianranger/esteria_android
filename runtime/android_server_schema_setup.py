#!/usr/bin/env python3
"""Prepare the pinned source baseline on an already owned Android MySQL service.

No engine is started or stopped here. The Java caller retains its service lease
and process handle throughout this operation. Only fixed provider locations and
an operation-private selection file are accepted by the command-line entrypoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import sys
import time

try:
    from . import mysql_bootstrap as db, mysql_service as service
    from . import server_content as content, server_schema_setup as schema
except ImportError:
    import mysql_bootstrap as db
    import mysql_service as service
    import server_content as content
    import server_schema_setup as schema

MAX_SELECTION = 128 * 1024
MAX_LOG = 1024 * 1024
DATABASES = {'auth': 'acore_auth', 'world': 'acore_world',
             'characters': 'acore_characters', 'playerbots': 'acore_playerbots'}


def read_json(path, maximum):
    raw = service.read_plain(path, maximum)
    def pairs(rows):
        result = {}
        for key, value in rows:
            service.require(key not in result, 'duplicate schema operation metadata')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    service.require(type(value) is dict, 'invalid schema operation metadata')
    return value, dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def selection(path):
    selected, _ = read_json(path, MAX_SELECTION)
    service.require(set(selected) == {'formatVersion', 'scope', 'source', 'sourceLockSha256',
                    'contentReceipt', 'compiledModules'} and type(selected['formatVersion']) is int and selected['formatVersion'] == 1 and
                    selected['scope'] == 'android-owned-server-schema-selection',
                    'invalid schema selection scope')
    for key in ('contentReceipt', 'compiledModules'):
        value = selected[key]
        service.require(type(value) is dict and set(value) == {'bytes', 'sha256'} and
                        type(value['bytes']) is int and 0 < value['bytes'] <= content.MAX_METADATA and
                        type(value['sha256']) is str and re.fullmatch('[a-f0-9]{64}', value['sha256']),
                        'invalid schema selection identity')
    service.require(type(selected['sourceLockSha256']) is str and
                    re.fullmatch('[a-f0-9]{64}', selected['sourceLockSha256']), 'invalid source lock selection')
    return selected


def live_service(connection, state, service_session, version, operation, uuid):
    ready, _ = read_json(service_session / 'ready.json', 16384)
    service.require(ready.get('formatVersion') == 1 and ready.get('scope') == 'owned-local-mysql-live-service' and
                    ready.get('operationId') == operation and ready.get('uuid') == uuid and
                    ready.get('version') == version and ready.get('datadir') == str(state / 'database') and
                    ready.get('bindAddress') == '127.0.0.1' and ready.get('port') == db.PORT and
                    ready.get('databases') == list(db.DATABASES) and
                    ready.get('liveSqlAuthenticated') is True and ready.get('ownedEngineIdentityVerified') is True and
                    ready.get('applicationSchemaUpdatesQualified') is False and ready.get('gameplayQualified') is False,
                    'live database service receipt differs')
    expected = db.read_receipt(state / 'database-bootstrap.json', version)
    service.require(expected['uuid'] == uuid and expected['datadir'] == str(state / 'database') and
                    db.datadir_uuid(state / 'database') == uuid, 'database service instance differs')
    db.check_receipt(expected, db.identity(connection, version))
    db.check_listener(connection, None)
    service.require(connection.query('SELECT CURRENT_USER()') in
                    (['esteria@127.0.0.1'], ['esteria@localhost']), 'unexpected schema database account')
    service.require(connection.query('SELECT @@pid_file') == [str(service_session / 'mysql.pid')],
                    'database is not the owned service instance')
    pid = service.read_plain(service_session / 'mysql.pid', 32).strip()
    service.require(re.fullmatch(b'[1-9][0-9]{0,9}', pid), 'invalid owned service process identity')


def limit_sql_log():
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG, MAX_LOG))
    signal.signal(signal.SIGXFSZ, signal.SIG_DFL)


def apply_file(mysql, options, database, path, session, index):
    """Stream a selected SQL file to MySQL; never retain the archive/file in RAM.

    Cancellation after SQL begins is deferred until that file finishes. SQL may
    auto-commit; errors/timeouts retain the durable in-flight schema journal.
    """
    service.require(database in DATABASES and 0 <= index < 40000, 'invalid schema SQL selection')
    path = db.private_path(Path(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        info = os.fstat(source.fileno())
        service.require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                        info.st_size <= content.MAX_PAYLOAD, 'invalid selected SQL file')
        command = [str(mysql), '--defaults-file=' + str(options), '--protocol=TCP', '--host=127.0.0.1',
                   '--port=' + str(db.PORT), '--connect-timeout=3', '--skip-reconnect',
                   '--default-character-set=utf8', '--max-allowed-packet=1GB', '--local-infile=0', DATABASES[database]]
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'MYSQL_TEST_LOGIN_FILE': os.devnull}
        log = session / ('sql-' + str(index) + '-private.log')
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as diagnostic:
            process = subprocess.Popen(command, stdin=source, stdout=diagnostic, stderr=subprocess.STDOUT,
                                       env=environment, preexec_fn=limit_sql_log)
            try:
                code = process.wait(timeout=300)
            except subprocess.TimeoutExpired as error:
                process.kill(); process.wait(timeout=5)
                raise service.ServiceError('schema SQL timed out; partial state retained') from error
            finally:
                if process.poll() is None:
                    process.kill(); process.wait(timeout=5)
        service.require(code == 0, 'schema SQL failed; partial state and private diagnostics retained')


class Progress:
    def __init__(self, session):
        self.path = session / 'progress.json'
        self.last = None
        self.time = 0

    def __call__(self, event):
        now = time.monotonic()
        phase = event['phase']
        if phase != self.last or phase.startswith('schema-file') or now - self.time >= .5:
            db.atomic_json(self.path, event)
            self.last, self.time = phase, now


def run(state, session, content_root, receipt, compiled_path, service_session, mysql, version,
        operation, service_operation, uuid, *, interrupted=lambda: False):
    db.exact_version(version)
    service.require(re.fullmatch('[a-f0-9]{32}', operation) and
                    re.fullmatch('[a-f0-9]{32}', service_operation) and
                    re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid),
                    'invalid schema operation identity')
    for path in (state, session, service_session): service.plain_directory(path)
    service.require(session != state and not session.is_relative_to(state) and not state.is_relative_to(session),
                    'schema operation overlaps persistent database storage')
    if interrupted() or os.path.lexists(session / 'cancel'):
        raise schema.SchemaCancelled('schema operation cancelled before work')
    selected = selection(session / 'selection.json')
    compiled, identity = read_json(compiled_path, content.MAX_METADATA)
    service.require(identity == selected['compiledModules'], 'compiled schema module identity differs')
    _, identity = read_json(receipt, content.MAX_METADATA)
    service.require(identity == selected['contentReceipt'], 'schema content receipt identity differs')
    cancelled = lambda: interrupted() or os.path.lexists(session / 'cancel')
    progress = Progress(session)
    verified = content.verify(content_root, receipt, selected['contentReceipt']['sha256'],
        selected['source'], selected['sourceLockSha256'], compiled, progress=progress, cancelled=cancelled)
    secret = service.read_plain(state / 'accounts/database-secret', 66).strip()
    service.require(re.fullmatch(b'[a-f0-9]{64}', secret), 'invalid existing schema database credential')
    password = secret.decode('ascii'); secret = None
    with db.option_file(session, 'esteria', password) as options:
        password = None
        with db.Mysql(mysql, options) as connection:
            live_service(connection, state, service_session, version, service_operation, uuid)
            count = [0]
            def apply(database, path):
                live_service(connection, state, service_session, version, service_operation, uuid)
                apply_file(mysql, options, database, path, session, count[0])
                count[0] += 1
                live_service(connection, state, service_session, version, service_operation, uuid)
            result = schema.initialize(verified, connection, state, version, apply,
                                      progress=progress, cancelled=cancelled)
            live_service(connection, state, service_session, version, service_operation, uuid)
    report = dict(result, operationId=operation, serviceOperationId=service_operation,
                  ownedServiceIdentityVerified=True, contentFilesVerified=len(verified.identities['files']),
                  databaseServiceStarted=False, databaseServiceStopped=False)
    db.atomic_json(session / 'result.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--operation-id', required=True)
    parser.add_argument('--service-operation-id', required=True)
    parser.add_argument('--instance-uuid', required=True)
    args = parser.parse_args()
    stopped = [False]
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stopped.__setitem__(0, True))
    try:
        service.require(re.fullmatch('[a-f0-9]{32}', args.operation_id) and
                        re.fullmatch('[a-f0-9]{32}', args.service_operation_id), 'invalid schema operation identity')
        session = Path('/work/schema-operations') / args.operation_id
        run(Path('/work/state'), session, Path('/esteria-server-content'), session / 'content-receipt.json',
            Path('/esteria-server-programs/provenance/server-modules.json'),
            Path('/work/mysql-sessions') / args.service_operation_id, Path('/usr/bin/mysql'),
            args.expected_version, args.operation_id, args.service_operation_id, args.instance_uuid,
            interrupted=lambda: stopped[0])
        print('Local source baseline prepared; compiled updater and gameplay remain separate gates')
        return 0
    except Exception as error:
        kind = type(error).__name__
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}', kind): kind = 'Exception'
        print('Local schema setup failed (' + kind + '); database and private diagnostics retained', file=sys.stderr)
        return 2 if isinstance(error, (schema.SchemaCancelled, content.ContentCancelled)) else 1


if __name__ == '__main__': raise SystemExit(main())
