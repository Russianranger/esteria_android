#!/usr/bin/env python3
"""Bind an isolated real DatabaseLoader reference to the verified ARM64 build.

The reference is qualification glue, never an installed application component.
This command does not execute the reference or initialize a database.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

try:
    from . import fetch_sources
    from . import manifest_server_modules as modules
    from . import qualify_base_sql as base
    from . import qualify_dbimport as importer
    from . import verify_server_build as files
except ImportError:
    import fetch_sources
    import manifest_server_modules as modules
    import qualify_base_sql as base
    import qualify_dbimport as importer
    import verify_server_build as files

require = base.content.require
ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('tests/playerbots_database_reference.cpp', 'tests/playerbots_database_reference.cmake',
          'tests/srp6_reference.cmake')
DATABASE_INPUTS = ('src/server/database/Database/DatabaseLoader.cpp',
                   'src/server/database/Database/Implementation/PlayerbotsDatabase.cpp',
                   'src/server/database/Updater/DBUpdater.cpp')
PATH_PATCH = 'patches/server/0007-runtime-module-config-directory.patch'


def playerbots_definition(row):
    arguments = row.get('arguments')
    if arguments is None:
        require(isinstance(row.get('command'), str), 'missing compiler command')
        arguments = shlex.split(row['command'], posix=True)
    require(isinstance(arguments, list) and all(isinstance(value, str) for value in arguments),
            'invalid compiler arguments')
    definitions = []
    for index, argument in enumerate(arguments):
        for prefix in ('-D', '-U'):
            value = arguments[index + 1] if argument == prefix and index + 1 < len(arguments) else (
                argument[2:] if argument.startswith(prefix) else '')
            if value.split('=', 1)[0] == 'MOD_PLAYERBOTS':
                definitions.append((prefix, value))
    require(definitions in ([('-D', 'MOD_PLAYERBOTS')], [('-D', 'MOD_PLAYERBOTS=1')]),
            'actual database/reference command must enable MOD_PLAYERBOTS exactly once')


def commands(path, server, root):
    selected, identity = {}, {}
    expected = {str((server / name).resolve()): name for name in DATABASE_INPUTS}
    expected[str((root / INPUTS[0]).resolve())] = INPUTS[0]
    with files.plain_file(path) as stream:
        for row in modules.json_array(stream, identity):
            name = row.get('file')
            require(isinstance(name, str), 'compile input filename required')
            file = Path(name)
            if not file.is_absolute():
                require(isinstance(row.get('directory'), str), 'relative compile input needs directory')
                file = Path(row['directory']) / file
            key = expected.get(str(file.resolve()))
            if key is not None:
                require(key not in selected, 'duplicate database/reference compile input')
                playerbots_definition(row)
                selected[key] = True
    require(set(selected) == set(DATABASE_INPUTS) | {INPUTS[0]}, 'missing real database/reference compile input')
    return identity


def source_inputs(root, revision):
    require(re.fullmatch('[0-9a-f]{40}', revision), 'full integration source revision required')
    result = {}
    for name in INPUTS:
        raw = subprocess.check_output(['git', 'show', revision + ':' + name], cwd=root,
                                      env={'PATH': '/usr/bin:/bin', 'GIT_NO_LAZY_FETCH': '1'})
        require(len(raw) <= 128 * 1024, 'reference source size limit')
        expected = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
        require(files.identity(root / name) == expected, 'reference source differs from integration revision')
        result[name] = expected
    return result


def verify(executable, server, install, compiled_path, compile_commands, lock_path, *, root=ROOT):
    compiled, compiled_identity = modules.read_json(compiled_path)
    build, _ = importer.verify_install(install, compiled, lock_path)
    pin, lock_hash = base.locked_source(lock_path)
    require('mod-playerbots' in compiled.get('enabledModules', []) and
            'playerbots.conf' in compiled.get('configFiles', []), 'compiled playerbots module/config is absent')
    require(any(item['path'] == PATH_PATCH for item in pin['patches']),
            'source-backed runtime module directory adaptation required')
    fetch_sources.verify_checkout(server, pin, fetch_sources.patch_inputs(pin, lock_path.parent))
    inputs = source_inputs(root, build['integrationRevision'])
    command_identity = commands(compile_commands, server, root)
    require(command_identity == compiled['compileCommands'], 'reference and server compile command inventories differ')
    elf = files.elf_header(executable, executable=True)
    elf.update(files.dynamic_metadata(files.bounded_command(['readelf', '--wide', '--dynamic', '--version-info', str(executable)])))
    return dict(formatVersion=1, scope='build-only-playerbots-database-reference',
        source=pin, sourceLockSha256=lock_hash, integrationRevision=build['integrationRevision'],
        serverBuild=compiled['serverBuild'], compiledModules=compiled_identity,
        compileCommands=command_identity, referenceInputs=inputs,
        executable=files.identity(executable), elf=elf,
        actualDatabaseSourcesAndDefinitionVerified=True, databaseExecuted=False,
        playerbotsAiQualified=False, worldserverQualified=False, androidRuntimeQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('executable', 'server', 'install', 'compiled-modules', 'compile-commands', 'output'):
        parser.add_argument('--' + argument, type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    args = parser.parse_args()
    require(not args.output.exists(), 'existing reference receipt preserved')
    result = verify(args.executable, args.server, args.install, args.compiled_modules, args.compile_commands, args.lock)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write('\n')
    print('Verified isolated ARM64 playerbots DatabaseLoader reference; SQL not executed')


if __name__ == '__main__':
    main()
