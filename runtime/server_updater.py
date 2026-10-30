"""Shared compiled-updater primitives; no Git, Docker or engine startup.

Callers verify exact content, executable/template identities, authenticated engine
ownership and durable operation intent before using these primitives. This module
starts only the selected updater child and owns its complete process group. Raw
output remains a bounded private tail; it establishes no gameplay qualification.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import time

try:
    from . import server_config as config, server_schema_baseline as baseline
    from .owned_process_group import OwnedGroup
except ImportError:
    import server_config as config
    import server_schema_baseline as baseline
    from owned_process_group import OwnedGroup

require = baseline.require
DATABASES = ('auth', 'characters', 'world')
DATABASE_PORT = 13306
LOG_LIMIT = 256 * 1024
CHUNK = 128 * 1024


@contextmanager
def plain_file(path):
    """Same regular-file and ancestor contract as the native artifact reader."""
    path = Path(path).absolute()
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), 'symlinked-or-invalid-parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'not-a-regular-file')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            yield stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def canonical_identity(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8')


def render_importer(template, source, state, mysql, password):
    run = state / 'run/dbimport'
    run.mkdir(mode=0o700)
    settings = {'SourceDirectory': config.quoted(source), 'MySQLExecutable': config.quoted(mysql),
                'LogsDir': config.quoted(state / 'logs'), 'TempDir': config.quoted(run),
                'Updates.EnableDatabases': 7, 'Updates.AllowedModules': '"all"',
                'Updates.AutoSetup': 0, 'Updates.Redundancy': 1, 'Updates.AllowRehash': 1,
                'Updates.ArchivedRedundancy': 0, 'Updates.CleanDeadRefMaxCount': 0,
                'Database.Reconnect.Attempts': 1, 'Database.Reconnect.Seconds': 1,
                'Logger.root': '4,Console'}
    for label, database in (('Login', 'auth'), ('Character', 'characters'), ('World', 'world')):
        settings[label + 'DatabaseInfo'] = f'"127.0.0.1;{DATABASE_PORT};esteria;{password};acore_{database}"'
        settings[label + 'Database.WorkerThreads'] = settings[label + 'Database.SynchThreads'] = 1
    text = config.overlay(template.read_text(), settings)
    path = run / 'dbimport.conf'
    config.write_private(path, text)
    return path


def run_importer(executable, configuration, log, *, timeout=1800, on_started=None):
    """Own the whole updater/mysql child process group; retain a bounded private tail."""
    command = [str(executable), '--config', str(configuration)]
    environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                   'AC_DISABLE_INTERACTIVE': '1', 'MYSQL_TEST_LOGIN_FILE': os.devnull}
    descriptor = os.open(log, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    tail = bytearray()
    child = None
    group = None
    try:
        child = subprocess.Popen(command, cwd=configuration.parent, env=environment, umask=0o077,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
        group = OwnedGroup(child)
        if on_started is not None:
            on_started()
        deadline = time.monotonic() + timeout
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(time.monotonic() < deadline, 'owned dbimport timed out; partial fixture preserved')
                for key, _ in selector.select(.2):
                    block = os.read(key.fd, 8192)
                    if not block:
                        selector.unregister(key.fd)
                        continue
                    tail.extend(block)
                    if len(tail) > LOG_LIMIT:
                        del tail[:-LOG_LIMIT]
            exit_code = group.wait(timeout=max(.01, deadline - time.monotonic()))
        require(exit_code == 0, 'compiled dbimport failed (exit ' + str(exit_code) + '); partial fixture preserved')
        return {'exitCode': exit_code, 'diagnosticBytes': len(tail),
                'diagnosticSha256': hashlib.sha256(tail).hexdigest()}
    finally:
        try:
            if group is not None:
                group.stop()
        finally:
            if child is not None and child.stdout:
                child.stdout.close()
            with os.fdopen(descriptor, 'wb') as output:
                output.write(tail)
                output.flush()
                os.fsync(output.fileno())


def expected_updates(source, manifest, database):
    result = {}
    for item in manifest['databases'][database]['updateOrder']:
        path = item['path']
        digest = hashlib.sha1()
        with plain_file(source / path) as stream:
            while block := stream.read(CHUNK):
                digest.update(block)
        name = Path(path).name
        require(name not in result, 'duplicate SQL basename in updater expectation')
        result[name] = (digest.hexdigest(), item['state'])
    return result


def core_schema_snapshot(connection, expected):
    """Read the three registered core pools without adopting a fourth schema."""
    result = {}
    for name in DATABASES:
        tables = connection.query('SHOW TABLES FROM `acore_' + name + '`')
        require('updates' in tables and 'updates_include' in tables, 'compiled updater did not create its ledger')
        rows = connection.query('SELECT name,hash,state FROM `acore_' + name + '`.`updates` ORDER BY name')
        entries = {}
        for row in rows:
            fields = row.split('\t')
            require(len(fields) == 3 and fields[0] not in entries, 'invalid or duplicate update ledger entry')
            entries[fields[0]] = (fields[1].lower(), fields[2])
        for filename, (digest, state) in expected[name].items():
            require(filename in entries, 'source update missing from applied ledger: ' + name + '/' + filename)
            observed = entries[filename]
            # Pinned source intentionally skips archived hash redundancy by default.
            require(observed[1] == state and (state == 'ARCHIVED' or observed[0] == digest),
                    'source update ledger/hash differs: ' + name + '/' + filename)
        result[name] = {'tableCount': len(tables), 'tablesSha256': hashlib.sha256(canonical_identity(tables)).hexdigest(),
                        'ledgerRows': len(rows), 'ledgerSha256': hashlib.sha256(canonical_identity(rows)).hexdigest(),
                        'sourceUpdateNamesVerified': len(expected[name])}
    return result


def schema_snapshot(connection, expected):
    """Default dbimport gate retains the empty, unregistered fourth-pool guard."""
    result = core_schema_snapshot(connection, expected)
    require(not connection.query('SHOW TABLES FROM `acore_playerbots`'),
            'dbimport unexpectedly modified the unregistered playerbots database')
    return result
