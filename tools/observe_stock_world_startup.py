"""Observe the normal packaged worldserver up to its first content dependency on disposable stock SQL."""
import json
import os
import re
import socket
import time
from pathlib import Path

from runtime import mysql_bootstrap as db, provision_local_realm as realm, server_content, server_session_process as processes
from tools.prepare_runtime import require
from tools.verify_server_build import identity


def observations(raw):
    pools = {b'acore_auth', b'acore_characters', b'acore_world', b'acore_playerbots'}
    opened = sorted(name.decode() for name in pools if b"DatabasePool '" + name + b"' opened successfully" in raw)
    missing_tiles = sorted(set(match.decode() for match in re.findall(rb'(?i)(?<![A-Za-z0-9])([0-9]{7,9}\.map)\b', raw)))
    return dict(databasePoolsOpened=opened, configuredFileRead=b'Using configuration file' in raw,
                worldInformationStarted=b'Loading World Information...' in raw, worldVersionLoaded=b'Version DB world:' in raw,
                startingAreaDataRequired=b'Failed to find map files for starting areas' in raw,
                mapFilesNamed=missing_tiles[:16], dataStoresEntered=b'Initialize Data Stores...' in raw,
                databasePoolFailed=b'There were errors opening the MySQL connections' in raw,
                preparedStatementError=b'Error in mysql_stmt_prepare' in raw or b'STMT ERROR' in raw,
                mysqlErrorCodes=sorted(set(x.decode() for x in re.findall(rb'\bMY-[0-9]{6}\b', raw)))[:24],
                missingSharedLibraries=b'error while loading shared libraries' in raw,
                missingSqlTable=b"doesn't exist" in raw and b'Table ' in raw, unknownSqlColumn=b'Unknown column' in raw,
                mysqlConnectionFailed=b"Can't connect to" in raw,
                configErrors=b'Invalid or missing configuration file' in raw or b'Error loading config' in raw)


def observe(package, selected, state, database, uuid, configuration, evidence):
    started = time.monotonic()
    proof = dict(scope='normal-packaged-worldserver-before-stock-starting-area-data',
                 environment='native Linux ARM64 on a disposable fully installed four-schema database',
                 gameSessionExecuted=False, worldserverExecuted=False, worldReadyQualified=False, worldEntryQualified=False,
                 gameplayQualified=False, dataReceiptUsed=False, dryRun=False, phase='verify-owned-inputs')
    def record(phase, **details):
        proof.update(phase=phase, elapsedSeconds=round(time.monotonic()-started, 3), **details)
        db.atomic_json(evidence, proof)
    record('verify-owned-inputs')
    source = json.loads((package / 'server-programs.json').read_bytes())['requiredFiles']['bin/worldserver']
    expected = {field: source[field] for field in ('bytes', 'sha256')}
    binary = package / 'server-programs/bin/worldserver'
    require(identity(binary) == expected and [n for _, n in socket.if_nameindex()] == ['lo'], 'selected isolated worldserver required')
    data = Path('/esteria-data')
    require(data.is_dir() and not list(data.iterdir()), 'expected an empty dedicated observation mount')
    verified = server_content.verify(package / 'server-content', package / 'content-receipt.json',
        selected['contentReceipt']['sha256'], selected['source'], selected['sourceLockSha256'],
        json.loads((package / 'server-programs/provenance/server-modules.json').read_bytes()))
    mysql = Path('/usr/bin/mysql')
    profile = json.loads((package / 'local-server.json').read_bytes())
    password = db.read_secret(state / 'accounts/database-secret')
    with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as sql:
        with db.state_lock(state), realm.config_lock(state):
            require(database.verify(sql, uuid) and realm.active_config_verified(verified, state, password,
                profile=profile, data=data / 'data', mysql=mysql) == configuration.name,
                    'same live database and source configuration required')
            conf = configuration / 'worldserver.conf'
            log = state / 'logs/world-bootstrap-stdout.log'
            file_log = state / 'logs/Server.log'
            # The installation helper already uses Server.log. Keep its private bytes before
            # the native world logger opens Server.log in its configured truncate mode.
            if os.path.lexists(file_log):
                previous = file_log.with_name('Server-before-world-observation.log')
                require(file_log.is_file() and not file_log.is_symlink() and not os.path.lexists(previous),
                        'isolated regular installer log required')
                file_log.rename(previous)
            child = processes.ServerChild('worldserver', binary, conf, state / 'run/worldserver', log)
            native_start = time.monotonic()
            exit_code = None
            try:
                child.start()
                record('native-worldserver-running', worldserverExecuted=True, worldserverSha256=expected['sha256'])
                exit_code = child.group.wait(120)
            finally:
                try:
                    child.stop()
                except ValueError:
                    # This observation expects the actual program to exit unsuccessfully for missing world data.
                    # The production owner continues to reject this as a clean session shutdown.
                    if not (exit_code is not None and child.closed and child.group and child.group.closed and
                            child.process.returncode == exit_code and not child.group.forced and child.error is None):
                        raise
            require(child.closed and not child.group.forced and child.error is None and child.observed == child.stored,
                    'native diagnostic process or logs incomplete')
            raw = log.read_bytes()
            if file_log.is_file() and not file_log.is_symlink():
                require(file_log.stat().st_size <= processes.LOG_LIMIT, 'bounded native file log required')
                raw += file_log.read_bytes()
            events = observations(raw)
            expected_boundary = exit_code == 1 and events['startingAreaDataRequired'] and not events['dataStoresEntered']
            record('stock-starting-area-map-gate' if expected_boundary else 'unexpected-native-startup-boundary',
                   nativeExit=exit_code, nativeElapsedSeconds=round(time.monotonic()-native_start, 3), nativeProcessReaped=True,
                   mysqlStillAuthenticated=database.verify(sql, uuid), **events)
            return expected_boundary
