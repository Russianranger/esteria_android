#!/usr/bin/env python3
"""Render complete immutable local configurations from verified server content.

No Git, build tools or SQL processes are required. The caller supplies a sealed
local profile and verified content; old generations and credentials are preserved.
The host adapter uses the same generation implementation, including legacy mode.
"""
from __future__ import annotations

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

try:
    from . import server_content as packaged
except ImportError:
    import server_content as packaged

MAIN_CONFIG_TEMPLATES = ('src/server/apps/authserver/authserver.conf.dist',
                         'src/server/apps/worldserver/worldserver.conf.dist')
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


def _validate_modules(compiled, inventory):
    if compiled.get('formatVersion') != 1 or compiled.get('scope') != 'compiled-server-module-selection' or \
            compiled.get('generatedListsMatchInstalledBinaries') is not True or \
            compiled.get('source') != inventory['source'] or \
            compiled.get('sourceLockSha256') != inventory['sourceLockSha256'] or \
            sorted(compiled['enabledModules']) != inventory['enabledModules'] or \
            set(compiled.get('binaries', {})) != {'worldserver', 'dbimport'}:
        raise ValueError('Compiled module selection differs from verified source inventory')
    templates = sorted(Path(path).name[:-5] for module in inventory['modules'] for path in module['configTemplates'])
    if sorted(compiled['configFiles']) != templates:
        raise ValueError('Compiled config list differs from inventory')


def _module_configurations(server, inventory, compiled, inventory_identity, compiled_identity, bots, main_templates):
    """Render checked templates using metadata identities supplied by each adapter."""
    if inventory.get('formatVersion') != 1 or inventory.get('scope') != 'source-content-inventory' or \
            inventory.get('contentSha256Complete') is not True or \
            not re.fullmatch('[0-9a-f]{64}', inventory.get('sourceLockSha256', '')):
        raise ValueError('Source-verified content inventory required for module configuration')
    _validate_modules(compiled, inventory)
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
             'inventorySha256': inventory_identity['sha256'],
             'compiledSelectionSha256': compiled_identity['sha256'],
             'configFiles': names, 'sourceTemplates': source_files,
             'moduleStartupQualified': False, 'gameplayQualified': False}
    return files, proof


def _render(server: Path, state: Path, data: Path, sql_source: Path, mysql_client: Path,
            *, profile: dict, module_preparer=None) -> dict:
    for path in (state, data, sql_source, mysql_client):
        if not path.is_absolute():
            raise ValueError('All runtime paths must be absolute in the runtime namespace')
        quoted(path)
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
        if module_preparer is not None:
            module_files, module_proof = module_preparer(bots, main_templates)
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


_LOCAL_PORTS = {'database_port': 13306, 'auth_port': 3724, 'world_port': 8085, 'client_build': 12340}
_BOT_POLICY = {
    'AiPlayerbot.Enabled': 1, 'AiPlayerbot.RandomBotAutologin': 0, 'AiPlayerbot.MinRandomBots': 0,
    'AiPlayerbot.MaxRandomBots': 0, 'AiPlayerbot.RandomBotAccountCount': 0,
    'AiPlayerbot.AddClassAccountPoolSize': 0, 'AiPlayerbot.MaxAddedBots': 4,
    'AiPlayerbot.BotAutologin': 0, 'AiPlayerbot.AllowAccountBots': 1,
    'AiPlayerbot.RandomBotGuildCount': 0, 'AiPlayerbot.RandomBotArenaTeam2v2Count': 0,
    'AiPlayerbot.RandomBotArenaTeam3v3Count': 0, 'AiPlayerbot.RandomBotArenaTeam5v5Count': 0,
    'AiPlayerbot.CommandServerPort': 0,
}


def _sealed_profile(profile):
    if not isinstance(profile, dict) or any(type(profile.get(key)) is not int or profile[key] != value
                                            for key, value in _LOCAL_PORTS.items()):
        raise ValueError('Explicit sealed local endpoint profile required')
    bots = profile.get('playerbots')
    if not isinstance(bots, dict) or set(bots) != set(_BOT_POLICY) or any(
            type(bots[key]) is not int or bots[key] != value for key, value in _BOT_POLICY.items()):
        raise ValueError('Explicit sealed controlled-playerbots profile required')
    return dict(_LOCAL_PORTS, playerbots=dict(bots))


def render_verified(content, state: Path, data: Path, mysql: Path, *, profile: dict) -> dict:
    """Render every selected module using a real verified extracted generation.

    The caller keeps that generation immutable and its runtime/session stopped.
    Metadata and source template bytes are rechecked before any activation. This
    API has no legacy or partial-module mode and executes no database/server.
    """
    if not isinstance(content, packaged.VerifiedContent) or content.source != content.root / 'source':
        raise ValueError('Verified extracted server content required')
    profile = _sealed_profile(profile)
    documents, identities = {}, {}
    for name, expected in (('content-manifest', content.manifest), ('compiled-modules', content.compiled)):
        relative = 'metadata/' + name + '.json'
        raw = bounded_plain(content.root / relative, (16 if name == 'content-manifest' else 1) << 20)
        identity = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        if identity != content.identities['files'].get(relative) or identity != content.receipt['archiveFiles'].get(relative):
            raise ValueError('Verified module metadata changed before configuration rendering')
        document = json.loads(raw)
        if document != expected:
            raise ValueError('Verified module metadata object differs from extracted content')
        documents[name], identities[name] = document, identity
    inventory, compiled = documents['content-manifest'], documents['compiled-modules']
    _validate_modules(compiled, inventory)
    prepare = lambda bots, main: _module_configurations(content.source, inventory, compiled,
        identities['content-manifest'], identities['compiled-modules'], bots, main)
    return _render(content.source, state, data, content.source, mysql, profile=profile, module_preparer=prepare)
