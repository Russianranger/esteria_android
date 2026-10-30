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
import stat
import shutil
import tempfile

PROFILE = Path(__file__).resolve().parents[1] / 'config/local-server.json'
MODULE_OVERRIDES = {
    'mod_azeroth_plex.conf': {'AzerothPlex.Enable': 0, 'AzerothPlex.BindAddress': '"127.0.0.1"'},
    'mod_battlemon.conf': {'Battlemon.Sidecar.Enable': 0, 'Battlemon.Sidecar.Bind': '"127.0.0.1"'},
    'ChatTransmitter.conf': {'ChatTransmitter.Enabled': 0},
    'mod_esteria_chat.conf': {'EsteriaChat.Enable': 0},
    'mod_launcher_api.conf': {'LauncherApi.Enable': 0, 'LauncherApi.Bind': '"127.0.0.1"'},
}


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


def disable_unqualified_lua(template: str) -> str:
    # ElunaConfig.cpp at the pinned submodule reads this key with default=true;
    # the main .dist omits it. Enabling Lua requires a separately qualified map.
    key = 'Eluna.Enabled'
    if re.search(r'^\s*Eluna\.Enabled\s*=', template, re.M):
        return overlay(template, {key: 0})
    return template + '\n# No qualified local Lua script package selected.\nEluna.Enabled = 0\n'


def write_private(path: Path, content: str) -> None:
    with path.open('x', encoding='utf-8') as stream:
        os.chmod(path, 0o600)
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def bounded_plain(path: Path, limit: int) -> bytes:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise ValueError('Configuration input contains a symbolic link')
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError('Configuration input is not a bounded regular file')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Configuration input grew beyond its bound')
    return raw


def plain_directory(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() or not current.is_dir():
            raise ValueError('Configuration directory contains a link or non-directory')


def module_configurations(server: Path, inventory_path: Path, compiled_path: Path, bots: dict,
                          main_templates: dict) -> tuple[dict, dict]:
    """Read an already source/binary-verified package's exact template selection.

    The caller verifies the installed content package and binary receipts first;
    these local metadata files are bindings, not independent signatures.
    """
    try:
        from .package_server_content import validate_modules
        from .manifest_server_content import MAIN_CONFIG_TEMPLATES
    except ImportError:
        from package_server_content import validate_modules
        from manifest_server_content import MAIN_CONFIG_TEMPLATES
    inventory_raw = bounded_plain(inventory_path.absolute(), 16 << 20)
    compiled_raw = bounded_plain(compiled_path.absolute(), 1 << 20)
    inventory, compiled = json.loads(inventory_raw), json.loads(compiled_raw)
    if inventory.get('formatVersion') != 1 or inventory.get('scope') != 'source-content-inventory' or \
            inventory.get('contentSha256Complete') is not True or \
            not re.fullmatch('[0-9a-f]{64}', inventory.get('sourceLockSha256', '')):
        raise ValueError('Source-verified content inventory required for module configuration')
    validate_modules(compiled, inventory)
    names = compiled['configFiles']
    if not isinstance(names, list) or not 1 <= len(names) <= 512 or \
            any(not isinstance(name, str) or not re.fullmatch('[A-Za-z0-9_.-]+\\.conf', name) for name in names) or \
            len({name.casefold() for name in names}) != len(names) or 'playerbots.conf' not in names:
        raise ValueError('Invalid or ambiguous complete module config list')
    files, source_files, total = {}, {}, 0
    for name in MAIN_CONFIG_TEMPLATES:
        raw = main_templates[name]
        pin = inventory['files'].get(name, {})
        if type(pin.get('bytes')) is not int or len(raw) != pin['bytes'] or \
                hashlib.sha256(raw).hexdigest() != pin.get('sha256'):
            raise ValueError('Main configuration template differs from verified source inventory')
        source_files[name] = {'bytes': len(raw), 'sha256': pin['sha256']}
    for module in inventory['modules']:
        module_name = module['name']
        if not re.fullmatch('[A-Za-z0-9_-]+', module_name):
            raise ValueError('Unsafe module name')
        for name in module['configTemplates']:
            if not re.fullmatch(re.escape('modules/' + module_name + '/conf/') + r'[A-Za-z0-9_.-]+\.conf\.dist', name):
                raise ValueError('Module template path does not match its module')
            basename = Path(name).name[:-5]
            destination = 'modules/' + basename
            if destination in files:
                raise ValueError('Duplicate module configuration destination')
            pin = inventory['files'][name]
            raw = bounded_plain(server.absolute() / name, 4 << 20)
            total += len(raw)
            if total > 16 << 20 or type(pin.get('bytes')) is not int or len(raw) != pin['bytes'] or \
                    hashlib.sha256(raw).hexdigest() != pin.get('sha256'):
                raise ValueError('Module template differs from verified source inventory')
            text = raw.decode('utf-8')
            settings = bots if basename == 'playerbots.conf' else MODULE_OVERRIDES.get(basename)
            files[destination] = overlay(text, settings) if settings is not None else text
            source_files[name] = {'bytes': len(raw), 'sha256': pin['sha256']}
    if sorted(name[len('modules/'):] for name in files) != sorted(names):
        raise ValueError('Not every compiled module configuration was prepared')
    proof = {'formatVersion': 1, 'scope': 'prepared-module-configurations-not-startup-qualified',
             'sourceLockSha256': inventory['sourceLockSha256'],
             'inventorySha256': hashlib.sha256(inventory_raw).hexdigest(),
             'compiledSelectionSha256': hashlib.sha256(compiled_raw).hexdigest(),
             'configFiles': names, 'sourceTemplates': source_files,
             'moduleStartupQualified': False, 'gameplayQualified': False}
    return files, proof


def render(server: Path, state: Path, data: Path, sql_source: Path, mysql_client: Path,
           *, module_inventory: Path | None = None, compiled_modules: Path | None = None) -> dict:
    if (module_inventory is None) != (compiled_modules is None):
        raise ValueError('Both source and compiled module selections are required')
    for path in (state, data, sql_source, mysql_client):
        if not path.is_absolute():
            raise ValueError('All runtime paths must be absolute in the runtime namespace')
        quoted(path)
    profile = json.loads(PROFILE.read_text())
    state.mkdir(parents=True, exist_ok=True)
    plain_directory(state)
    for name in ('config', 'accounts', 'database', 'logs', 'run', 'run/authserver', 'run/worldserver'):
        (state / name).mkdir(mode=0o700, exist_ok=True)
        plain_directory(state / name)
    lock_fd = os.open(state / 'config/.render.lock', os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    if not stat.S_ISREG(os.fstat(lock_fd).st_mode):
        os.close(lock_fd)
        raise ValueError('Configuration lock is not a regular file')
    with os.fdopen(lock_fd, 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        secret_path = state / 'accounts/database-secret'
        if not secret_path.exists():
            write_private(secret_path, secrets.token_hex(32) + '\n')
        secret = bounded_plain(secret_path, 66).decode('ascii').strip()
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
        auth = common | {'RealmServerPort': profile['auth_port'], 'TempDir': quoted(state / 'run/authserver')}
        world = common | {'WorldServerPort': profile['world_port'], 'DataDir': quoted(data),
                          'TempDir': quoted(state / 'run/worldserver'),
                          'WorldDatabaseInfo': database_info('acore_world'),
                          'CharacterDatabaseInfo': database_info('acore_characters'),
                          'WorldDatabase.WorkerThreads': 1, 'WorldDatabase.SynchThreads': 1,
                          'CharacterDatabase.WorkerThreads': 1, 'CharacterDatabase.SynchThreads': 1,
                          'Console.Enable': 1, 'Ra.Enable': 0, 'SOAP.Enabled': 0,
                          'Wintergrasp.DeferShutdownTimer': 0,
                          'Network.Threads': 1, 'MapUpdate.Threads': 1}
        bots = profile['playerbots'] | {'PlayerbotsDatabaseInfo': database_info('acore_playerbots')}
        main_templates = {name: bounded_plain(server.absolute() / name, 4 << 20) for name in (
            'src/server/apps/authserver/authserver.conf.dist', 'src/server/apps/worldserver/worldserver.conf.dist')}
        files = {
            'authserver.conf': overlay(main_templates['src/server/apps/authserver/authserver.conf.dist'].decode('utf-8'), auth),
            'worldserver.conf': overlay(main_templates['src/server/apps/worldserver/worldserver.conf.dist'].decode('utf-8'), world),
            'modules/playerbots.conf': overlay(bounded_plain(server.absolute() / 'modules/mod-playerbots/conf/playerbots.conf.dist', 4 << 20).decode('utf-8'), bots),
        }
        files['worldserver.conf'] = disable_unqualified_lua(files['worldserver.conf'])
        module_proof = None
        if module_inventory is not None:
            module_files, module_proof = module_configurations(server, module_inventory, compiled_modules, bots, main_templates)
            files.update(module_files)
            files['module-configuration.json'] = json.dumps(module_proof, sort_keys=True, indent=2) + '\n'
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
        plain_directory(generations)
        destination = generations / digest
        if not destination.exists():
            temporary = Path(tempfile.mkdtemp(prefix='.pending-', dir=generations))
            try:
                for name, content in files.items():
                    path = temporary / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    write_private(path, content)
                for directory in (temporary / 'modules', temporary):
                    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
                os.rename(temporary, destination)
                descriptor = os.open(generations, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        else:
            # Do not reuse a generation if a previous manual edit or corruption changed it.
            plain_directory(destination)
            actual = set()
            for folder, dirs, children in os.walk(destination, followlinks=False):
                if Path(folder).relative_to(destination) not in (Path('.'), Path('modules')):
                    raise ValueError('Existing configuration generation directory set changed')
                for child in dirs + children:
                    if (Path(folder) / child).is_symlink():
                        raise ValueError('Existing configuration generation contains a link')
                actual.update((Path(folder) / child).relative_to(destination).as_posix() for child in children)
                if len(actual) > len(files):
                    raise ValueError('Existing configuration generation file set changed; refusing activation')
            if actual != set(files):
                raise ValueError('Existing configuration generation file set changed; refusing activation')
            for name, content in files.items():
                expected = content.encode('utf-8')
                if bounded_plain(destination / name, len(expected)) != expected:
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
                'module_configurations_complete': module_proof is not None,
                'module_startup_qualified': False,
                'lua_scripts_enabled': False,
                'auth_port': profile['auth_port'], 'world_port': profile['world_port'],
                'database_port': profile['database_port'], 'bot_limit': profile['playerbots']['AiPlayerbot.MaxAddedBots']}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', required=True, type=Path)
    parser.add_argument('--state-root', required=True, type=Path)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--sql-source', required=True, type=Path)
    parser.add_argument('--mysql-client', required=True, type=Path)
    parser.add_argument('--module-inventory', type=Path)
    parser.add_argument('--compiled-modules', type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.server, args.state_root, args.data_root, args.sql_source, args.mysql_client,
                           module_inventory=args.module_inventory, compiled_modules=args.compiled_modules), indent=2))


if __name__ == '__main__':
    main()
