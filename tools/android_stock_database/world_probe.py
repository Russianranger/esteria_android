"""Observe the selected Android worldserver up to its first real map request in a disposable empty fixture."""
import hashlib
import os
from pathlib import Path
import time

from runtime import mysql_bootstrap as storage
from runtime import server_schema_baseline as baseline
from runtime import server_session_process as processes
from stock_world_observation import observations


def observe(state, configuration, destination, sha256, size, verify_sql):
    output = destination / 'world-observation.json'
    start = time.monotonic()
    proof = dict(scope='disposable Android stock four-schema worldserver loader with empty data directory',
                 gameSessionExecuted=False, dataReceiptUsed=False, startingAreaLoaded=False,
                 worldReadyQualified=False, worldEntryQualified=False, physicalThor=False,
                 dataMount='/esteria-data', dataFiles=0, dataBytes=0)

    def record(phase, **details):
        proof.update(phase=phase, elapsedSeconds=round(time.monotonic()-start, 3), **details)
        storage.atomic_json(output, proof)

    record('verify-owned-inputs')
    empty = Path('/esteria-data')
    if not empty.is_dir() or any(empty.iterdir()):
        raise ValueError('The empty-data observer requires the explicit empty data mount')
    program = Path('/esteria-server-programs/bin/worldserver')
    if baseline.file_identity(program) != dict(bytes=int(size), sha256=sha256):
        raise ValueError('The selected worldserver changed')
    verify_sql()
    file_log = state / 'logs/Server.log'
    previous = state / 'logs/Server-before-android-world.log'
    if os.path.lexists(file_log):
        if not file_log.is_file() or file_log.is_symlink() or os.path.lexists(previous):
            raise ValueError('Expected a unique regular installer log')
        file_log.rename(previous)
    log = destination / 'world-private.log'
    child = processes.ServerChild('worldserver', program, configuration / 'worldserver.conf',
                                  state / 'run/worldserver', log)
    code = None
    try:
        child.start()
        record('native-worldserver-started', worldserverSha256=sha256)
        code = child.group.wait(120)
    finally:
        try:
            child.stop()
        except ValueError:
            # Production rejects this input-induced nonzero exit as a clean shutdown.
            # Accept only the already-terminated, genuinely observed original process.
            if not (code is not None and child.closed and child.group and child.group.closed
                    and child.process.returncode == code and not child.group.forced and child.error is None):
                raise

    if not child.closed or child.group.forced or child.error is not None or child.observed != child.stored:
        raise ValueError('Incomplete native process cleanup or truncated loader diagnostics')
    raw = log.read_bytes()
    if file_log.is_file() and not file_log.is_symlink():
        if file_log.stat().st_size > processes.LOG_LIMIT:
            raise ValueError('Oversized native loader log')
        raw += file_log.read_bytes()
    events = observations(raw)
    verify_sql()
    expected = (code == 1 and events['startingAreaDataRequired'] and not events['dataStoresEntered']
                and set(events['databasePoolsOpened']) == {'acore_auth','acore_world','acore_characters','acore_playerbots'})
    record('starting-area-map-required' if expected else 'unexpected-native-loader-boundary',
           nativeExit=code, originalChildReaped=True, mysqlStillAuthenticated=True,
           privateDiagnosticSha256=hashlib.sha256(raw).hexdigest(), **events)
    return proof
