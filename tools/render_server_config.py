#!/usr/bin/env python3
"""Render versioned local-only MySQL 8 / Esteria configurations.

No database is initialized or migrated here. The runtime installer must package
MySQL 8, pinned server SQL/modules/Lua, and perform authenticated bootstrap before
launch. Generation is atomic: old config remains active if rendering fails.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile

PROFILE = Path(__file__).resolve().parents[1] / 'config/local-server.json'


def quoted(value: str | Path) -> str:
    value = str(value)
    if any(character in value for character in ('\x00', '\r', '\n', '"', '\\', ';')):
        raise ValueError('Configuration paths must not contain control characters, quotes, backslashes or semicolons')
    return '"' + value + '"'


def overlay(template: str, settings: dict[str, str | int]) -> str:
    remaining = dict(settings)
    seen = set()
    result = []
    for line in template.splitlines():
        match = re.match(r'^\s*([A-Za-z0-9_.]+)\s*=', line)
        if match and match[1] in settings:
            key = match[1]
            if key in seen:
                raise ValueError(f'Duplicate upstream configuration key: {key}')
            seen.add(key)
            line = f'{key} = {remaining.pop(key)}'
        result.append(line)
    if remaining:
        raise ValueError('Pinned template is missing keys: ' + ', '.join(sorted(remaining)))
    return '\n'.join(result) + '\n'


def write_private(path: Path, content: str) -> None:
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def render(server: Path, state: Path, data: Path, sql_source: Path, mysql_client: Path) -> dict:
    for path in (state, data, sql_source, mysql_client):
        if not path.is_absolute():
            raise ValueError('All runtime paths must be absolute in the runtime namespace')
        quoted(path)
    profile = json.loads(PROFILE.read_text())
    state.mkdir(parents=True, exist_ok=True)
    for name in ('config', 'accounts', 'database', 'logs', 'run'):
        (state / name).mkdir(mode=0o700, exist_ok=True)
    with (state / 'config/.render.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        secret_path = state / 'accounts/database-secret'
        if not secret_path.exists():
            write_private(secret_path, secrets.token_hex(32) + '\n')
        secret = secret_path.read_text().strip()
        if not re.fullmatch(r'[a-f0-9]{64}', secret):
            raise ValueError('Existing database secret is invalid; refusing replacement')
        os.chmod(secret_path, 0o600)
        # Connection strings deliberately contain semicolons, unlike paths.
        def database_info(name):
            return '"' + f'127.0.0.1;{profile["database_port"]};esteria;{secret};{name}' + '"'
        common = {'BindIP': quoted('127.0.0.1'), 'LogsDir': quoted(state / 'logs'),
                  'SourceDirectory': quoted(sql_source), 'MySQLExecutable': quoted(mysql_client),
                  'LoginDatabaseInfo': database_info('acore_auth'),
                  'LoginDatabase.WorkerThreads': 1, 'LoginDatabase.SynchThreads': 1}
        auth = common | {'RealmServerPort': profile['auth_port']}
        world = common | {'WorldServerPort': profile['world_port'], 'DataDir': quoted(data),
                          'WorldDatabaseInfo': database_info('acore_world'),
                          'CharacterDatabaseInfo': database_info('acore_characters'),
                          'WorldDatabase.WorkerThreads': 1, 'WorldDatabase.SynchThreads': 1,
                          'CharacterDatabase.WorkerThreads': 1, 'CharacterDatabase.SynchThreads': 1,
                          'Console.Enable': 1, 'Ra.Enable': 0, 'SOAP.Enabled': 0,
                          'Network.Threads': 1, 'MapUpdate.Threads': 1}
        bots = profile['playerbots'] | {'PlayerbotsDatabaseInfo': database_info('acore_playerbots')}
        files = {
            'authserver.conf': overlay((server / 'src/server/apps/authserver/authserver.conf.dist').read_text(), auth),
            'worldserver.conf': overlay((server / 'src/server/apps/worldserver/worldserver.conf.dist').read_text(), world),
            'modules/playerbots.conf': overlay((server / 'modules/mod-playerbots/conf/playerbots.conf.dist').read_text(), bots),
        }
        socket = state / 'run/mysql.sock'
        if len(os.fsencode(socket)) > 100:
            raise ValueError('MySQL socket path exceeds portable Unix socket path limit; use a shorter runtime mount')
        files['mysql.cnf'] = f'''# Generated local MySQL 8 profile; persistent data is never deleted.
[mysqld]
bind-address=127.0.0.1
port={profile['database_port']}
mysqlx=OFF
skip-name-resolve
socket={quoted(socket)}
pid-file={quoted(state / 'run/mysql.pid')}
datadir={quoted(state / 'database')}
log-error={quoted(state / 'logs/mysql.log')}
max-connections=24
innodb-buffer-pool-size=128M
innodb-log-buffer-size=8M
innodb-flush-log-at-trx-commit=1
max-allowed-packet=64M
tmp-table-size=16M
max-heap-table-size=16M
performance-schema=OFF
[client]
protocol=TCP
host=127.0.0.1
port={profile['database_port']}
user=esteria
password={secret}
'''
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        generations = state / 'config/generations'
        generations.mkdir(exist_ok=True)
        destination = generations / digest
        if not destination.exists():
            temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=generations))
            try:
                for name, content in files.items():
                    path = temporary / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    write_private(path, content)
                os.rename(temporary, destination)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        else:
            # Do not reuse a generation if a previous manual edit or corruption changed it.
            for name, content in files.items():
                if (destination / name).read_text() != content:
                    raise ValueError('Existing configuration generation changed; refusing activation')
        temporary_link = state / 'config/.current-next'
        temporary_link.unlink(missing_ok=True)
        temporary_link.symlink_to(Path('generations') / digest, target_is_directory=True)
        os.replace(temporary_link, state / 'config/current')
        descriptor = os.open(state / 'config', os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return {'generation': digest, 'config': str(state / 'config/current'),
                'database_initialized': False, 'runtime_validated': False,
                'auth_port': profile['auth_port'], 'world_port': profile['world_port'],
                'database_port': profile['database_port'], 'bot_limit': profile['playerbots']['AiPlayerbot.MaxAddedBots']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--sql-source', required=True, type=Path)
    parser.add_argument('--mysql-client', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.server, args.state_root, args.data_root, args.sql_source, args.mysql_client), indent=2))


if __name__ == '__main__':
    main()
