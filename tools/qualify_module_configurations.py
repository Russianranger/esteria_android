#!/usr/bin/env python3
"""Load the actual compiled world's module selection with the real ConfigMgr.

Private disposable config copies only; this never starts worldserver or MySQL.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_modules as modules, qualify_base_sql as base
from tools import qualify_dbimport as importer, render_server_config as config, verify_server_build as files
from runtime import mysql_bootstrap as db

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ('tests/module_configs_reference.cpp', 'tests/config_path_reference.cmake', 'tests/srp6_reference.cmake')
require = base.content.require


def source_binding(reference, server, install, compiled_path, compile_commands, lock_path):
    compiled, compiled_identity = modules.read_json(compiled_path)
    build, _ = importer.verify_install(install, compiled, lock_path)
    pin, lock_hash = base.locked_source(lock_path)
    require(any(row['path'].endswith('/0007-runtime-module-config-directory.patch') for row in pin['patches']),
            'reviewed module configuration directory adaptation required')
    fetch_sources.verify_checkout(server, pin, fetch_sources.patch_inputs(pin, lock_path.parent))
    inputs = {}
    for name in INPUTS:
        raw = subprocess.check_output(['git', 'show', build['integrationRevision'] + ':' + name],
                                      cwd=ROOT, env={'PATH': '/usr/bin:/bin', 'GIT_NO_LAZY_FETCH': '1'})
        require(len(raw) <= 128 * 1024, 'reference source size limit')
        expected = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        require(files.identity(ROOT / name) == expected, 'reference source differs from build revision')
        inputs[name] = expected
    expected_paths = {str((ROOT / INPUTS[0]).resolve()), str((server / 'src/common/Configuration/Config.cpp').resolve())}
    observed, identity = set(), {}
    with files.plain_file(compile_commands) as stream:
        for row in modules.json_array(stream, identity):
            path = Path(row['file'])
            if not path.is_absolute(): path = Path(row['directory']) / path
            path = str(path.resolve())
            if path in expected_paths:
                require(path not in observed, 'duplicate actual ConfigMgr/reference compile input')
                observed.add(path)
    require(observed == expected_paths and identity == compiled['compileCommands'],
            'actual ConfigMgr/reference compilation is not bound to selected server build')
    require(files.elf_header(reference, executable=True)['machine'] == 'AArch64', 'native ARM64 reference required')
    return compiled, dict(source=pin, sourceLockSha256=lock_hash, serverBuildId=build['buildId'],
        compiledModules=compiled_identity, compileCommands=identity, referenceInputs=inputs,
        executable=files.identity(reference))


def execute(reference, generation, names, run):
    require(names and len(names) <= 256 and len(names) == len(set(name.casefold() for name in names)) and
            all(re.fullmatch(r'[A-Za-z0-9_.-]+\.conf', name) for name in names), 'invalid exact module selection')
    require(not os.path.lexists(run), 'existing ConfigMgr fixture preserved')
    selected = ['worldserver.conf'] + ['modules/' + name for name in names]
    before = {name: files.identity(generation / name) for name in selected}
    require(sum(row['bytes'] for row in before.values()) <= 20 * 1024**2, 'selected configuration total bound')
    run.mkdir(mode=0o700)
    plan = run / 'reference.conf'
    config.write_private(plan, str(generation) + '\n' + ','.join(names) + '\n')
    log = run / 'reference-private.log'
    importer.run_importer(reference, plan, log, timeout=30)
    with files.plain_file(log) as stream: raw = stream.read(importer.LOG_LIMIT + 1)
    expected = ('ESTERIA_MODULE_CONFIG_REFERENCE_PASS files=' + str(len(names)) +
                ' reload=1 sourcePreserved=1').encode()
    require(len(raw) <= importer.LOG_LIMIT and raw.splitlines().count(expected) == 1,
            'actual ConfigMgr completion marker absent or ambiguous')
    require(all(files.identity(generation / name) == value for name, value in before.items()),
            'source configuration generation changed during reference')


def qualify(reference, server, install, inventory_path, compiled_path, compile_commands, lock_path, output):
    output = db.private_path(output)
    require(not os.path.lexists(output), 'existing module configuration qualification preserved')
    require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
            'native Linux ARM64 module configuration qualification required')
    compiled, proof = source_binding(reference, server, install, compiled_path, compile_commands, lock_path)
    output.mkdir(mode=0o700)
    state = output / 'state'
    prepared = config.render(server, state, output / 'unavailable-game-data', server, Path('/usr/bin/mysql'),
                             module_inventory=inventory_path, compiled_modules=compiled_path)
    require(prepared['module_configurations_complete'] is True, 'complete module templates not rendered')
    generation = state / 'config/generations' / prepared['generation']
    execute(reference, generation, compiled['configFiles'], output / 'run')
    return dict(formatVersion=1, scope='native-arm64-actual-ConfigMgr-compiled-world-module-selection',
        **proof, moduleConfigurationProof=files.identity(generation / 'module-configuration.json'),
        configFiles=compiled['configFiles'], moduleCount=len(compiled['configFiles']),
        allSelectedModulesParsed=True, reloadValuesVerified=True, sourceConfigurationPreserved=True,
        renderedPolicyValuesVerified=True, qualificationSucceeded=True,
        worldserverExecuted=False, moduleGameplayHooksQualified=False, sqlExecuted=False,
        playerbotsAiQualified=False, androidRuntimeQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('reference', 'server', 'install', 'inventory', 'compiled-modules', 'compile-commands', 'output', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    args = parser.parse_args()
    require(not os.path.lexists(args.evidence), 'existing public module configuration receipt preserved')
    try:
        result = qualify(args.reference.absolute(), args.server.absolute(), args.install.absolute(),
            args.inventory.absolute(), args.compiled_modules.absolute(), args.compile_commands.absolute(),
            args.lock.absolute(), args.output.absolute())
        config.write_private(args.evidence, json.dumps(result, indent=2, sort_keys=True) + '\n')
        print('Actual ConfigMgr module selection and reload passed; world/SQL were not started')
    except Exception as error:
        raise SystemExit('Module configuration qualification failed (' + type(error).__name__ + '); private fixture retained') from None


if __name__ == '__main__': main()
