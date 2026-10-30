#!/usr/bin/env python3
"""Stage exact linked CI binaries and repack their source content without compiling.

The original six-patch build remains distinct from the current application lock.
This never starts a server, imports SQL, strips binaries or adopts saved state.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import fetch_sources, manifest_server_content as content, manifest_server_modules as modules
from tools import package_server_content as package, provider_client_runtime as zip_tools
from tools import qualify_base_sql as base, qualify_dbimport as importer, verify_server_build as files
from tools.release_server_dependencies import Github, API, encoded

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/compiled-reference.lock.json'
require = content.require
MAX_INSTALL = 8 * 1024**3
META = 16 * 1024**2


def load_pin():
    pin, identity = modules.read_json(LOCK)
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'exact-linked-server-build-requalification' and
            pin.get('repository') == 'Russianranger/esteria_android', 'invalid compiled reference scope')
    require(re.fullmatch('[a-f0-9]{40}', pin['integrationRevision']) and
            re.fullmatch('[a-f0-9]{64}', pin['sourceLockSha256']) and
            set(pin['artifacts']) == {'install', 'content', 'diagnostics'}, 'invalid compiled reference identity')
    require(files.identity(ROOT / 'runtime/server/sources.lock.json')['sha256'] == pin['runtimeSourceLockSha256'],
            'server dependency source lock changed; explicit requalification required')
    for row in pin['artifacts'].values():
        require(type(row['id']) is int and row['id'] > 0 and type(row['bytes']) is int and
                22 <= row['bytes'] < 2 * 1024**3 and re.fullmatch('[a-f0-9]{64}', row['sha256']),
                'invalid compiled artifact pin')
    return pin, identity


def verify_remote(api, pin):
    run = api.json('/actions/runs/' + str(pin['workflowRun']))
    # The original job failed AFTER verified linking. Requiring overall success
    # would mislabel this known input; its failure is explicit and exact.
    require(run.get('id') == pin['workflowRun'] and run.get('head_sha') == pin['integrationRevision'] and
            run.get('status') == 'completed' and run.get('conclusion') == 'failure', 'unexpected original workflow result')
    job = api.json('/actions/jobs/' + str(pin['job']))
    require(job.get('id') == pin['job'] and job.get('run_id') == pin['workflowRun'] and
            job.get('status') == 'completed' and job.get('conclusion') == 'failure', 'unexpected original build job')
    steps = {row['number']: row for row in job['steps']}
    for number in (12, 15, 16, 17, 18, 19, 20, 24, 25):
        require(steps.get(number, {}).get('conclusion') == 'success', 'original linked-build prerequisite did not pass')
    require(steps.get(21, {}).get('conclusion') == 'failure', 'original runtime failure scope changed')
    for row in pin['artifacts'].values():
        actual = api.json('/actions/artifacts/' + str(row['id']))
        require(actual.get('id') == row['id'] and actual.get('expired') is False and
                actual.get('size_in_bytes') == row['bytes'] and actual.get('digest') == 'sha256:' + row['sha256'] and
                actual.get('workflow_run', {}).get('id') == pin['workflowRun'] and
                actual.get('workflow_run', {}).get('head_sha') == pin['integrationRevision'],
                'compiled artifact GitHub identity changed')


@contextmanager
def bounded_zip(path):
    with files.plain_file(path) as stream:
        with zip_tools.checked_zip(stream, required=(), maximum_bytes=2 * 1024**3,
                                   maximum_entries=10000, maximum_directory=8 * 1024**2) as archive:
            members, total = {}, 0
            for item in archive.infolist():
                mode = stat.S_IFMT(item.external_attr >> 16)
                require(not item.is_dir() and mode in (0, stat.S_IFREG), 'nonregular build artifact member')
                require(0 <= item.file_size <= MAX_INSTALL, 'build artifact member size bound')
                total += item.file_size
                require(total <= MAX_INSTALL, 'build artifact expanded size bound')
                members[item.filename] = item
            yield archive, members


def unique_member(members, basename):
    names = [name for name in members if Path(name).name == basename]
    require(len(names) == 1, 'missing or ambiguous build metadata: ' + basename)
    return names[0]


def small_member(archive, members, basename, maximum=META):
    name = unique_member(members, basename)
    require(members[name].file_size <= maximum, 'build metadata size bound')
    with archive.open(members[name]) as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) == members[name].file_size, 'build metadata length mismatch')
    return raw


def write_new(path, raw, mode=0o444):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as output:
        output.write(raw)
    path.chmod(mode)


def extract_install(path, destination, pin):
    require(not os.path.lexists(destination), 'existing compiled install preserved')
    with bounded_zip(path) as (archive, members):
        raw = small_member(archive, members, 'server-build.json')
        build = json.loads(raw)
        require(build.get('schemaVersion') == 1 and build.get('architecture') == 'Linux-ARM64' and
                build.get('sourceCheckoutAndPatchesVerified') is True and
                build.get('hostLoaderSmoke', {}).get('qualified') is True and
                build.get('integrationRevision') == pin['integrationRevision'] and build.get('buildId') == pin['buildId'] and
                build.get('sourcesLock', {}).get('sha256') == pin['sourceLockSha256'], 'original build receipt mismatch')
        prefix = unique_member(members, 'server-build.json')[:-len('server-build.json')]
        declared = {row['path']: row for row in build['files']}
        require(len(declared) == len(build['files']) and len(declared) < files.MAX_FILES, 'invalid installed inventory')
        require(set(members) == {prefix + name for name in declared} | {prefix + 'server-build.json'},
                'original installed archive differs from build inventory')
        destination.mkdir(mode=0o700)
        for name, row in declared.items():
            content.safe_path(name)
            item = members[prefix + name]
            require(item.file_size == row['bytes'], 'installed member size differs from build receipt')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as incoming, target.open('xb') as outgoing:
                digest = zip_tools.archives.hash_stream(incoming, row['bytes'], outgoing)
            require(digest == row['sha256'], 'installed member hash differs from build receipt')
            target.chmod(0o555 if 'elf' in row else 0o444)
        write_new(destination / 'server-build.json', raw)
        require(files.identity(destination / 'sources.lock.json')['sha256'] == pin['sourceLockSha256'],
                'installed original source lock differs')
    return build


def original_metadata(archive_path, destination):
    with bounded_zip(archive_path) as (archive, members):
        for name in ('server-modules.json', 'server-content-manifest.json', 'package-receipt.json'):
            write_new(destination / name, small_member(archive, members, name))
        receipt, _ = modules.read_json(destination / 'package-receipt.json')
        archive_name = unique_member(members, 'server-content.tar.gz')
        item = members[archive_name]
        require(item.file_size == receipt['archive']['bytes'], 'original content archive size mismatch')
        with archive.open(item) as incoming:
            require(zip_tools.archives.hash_stream(incoming, item.file_size) == receipt['archive']['sha256'],
                    'original content archive hash mismatch')
    return receipt


def stage_diagnostics(archive_path, output, installed_lock, pin):
    locked = output / 'locked'
    original = installed_lock.read_bytes()
    require(hashlib.sha256(original).hexdigest() == pin['sourceLockSha256'], 'six-patch lock changed')
    document = json.loads(original)
    with bounded_zip(archive_path) as (archive, members):
        require(small_member(archive, members, 'sources.lock.json') == original, 'build diagnostics source lock differs')
        write_new(locked / 'sources.lock.json', original)
        for patch in document['sources']['server']['patches']:
            raw = small_member(archive, members, Path(patch['path']).name)
            require(hashlib.sha256(raw).hexdigest() == patch['sha256'], 'original source adaptation hash differs')
            content.safe_path(patch['path'])
            write_new(locked / patch['path'], raw)
        name = unique_member(members, 'compile_commands.json')
        require(members[name].file_size <= modules.MAX_COMMANDS, 'original compile commands size bound')
        target = output / 'compile_commands.json'
        with archive.open(members[name]) as incoming, target.open('xb') as outgoing:
            zip_tools.archives.hash_stream(incoming, members[name].file_size, outgoing)
        target.chmod(0o444)
    base.locked_source(locked / 'sources.lock.json')
    return locked / 'sources.lock.json'


def prepare(output, api=None):
    output = zip_tools.archives.directory(output.parent, create=True) / output.name
    require(not os.path.lexists(output), 'existing requalification staging preserved')
    pin, pin_identity = load_pin()
    api = api or Github(os.environ.get('GITHUB_TOKEN'))
    verify_remote(api, pin)
    output.mkdir(mode=0o700)
    downloads = output / 'downloads'; downloads.mkdir()
    # Each complete ZIP is hashed before any extraction; failures remain staged,
    # never become a preparation receipt, and never reach SQL execution.
    for name, row in pin['artifacts'].items():
        api.download(API + '/actions/artifacts/' + str(row['id']) + '/zip', downloads / (name + '.zip'), row)
    install = output / 'install'
    build = extract_install(downloads / 'install.zip', install, pin)
    lock_path = stage_diagnostics(downloads / 'diagnostics.zip', output, install / 'sources.lock.json', pin)
    original = original_metadata(downloads / 'content.zip', output / 'original-content')
    compiled, _ = modules.read_json(output / 'original-content/server-modules.json')
    observed = modules.verify(output / 'compile_commands.json', install, install / 'server-build.json')
    require(observed == compiled, 'rechecked module selection differs from original build')
    importer.verify_install(install, compiled, lock_path)
    original_manifest, original_id = modules.read_json(output / 'original-content/server-content-manifest.json')
    require(original.get('contentManifest') == original_id and original.get('source') == build['serverSource'] and
            original.get('sourceLockSha256') == pin['sourceLockSha256'] and
            original.get('compiledModules') == files.identity(output / 'original-content/server-modules.json') and
            original.get('moduleSelectionVerified') is True and original.get('archiveReadBackVerified') is True,
            'original source package provenance mismatch')
    package.validate_modules(compiled, original_manifest)
    # Exact input identities are retained in evidence. Reclaim only this new
    # invocation's validated ZIPs before source checkout and database fixtures.
    for name in pin['artifacts']:
        (downloads / (name + '.zip')).unlink()
    source = build['serverSource']
    fetch_sources.fetch('server', source, output / 'sources', lock_path.parent, False)
    server_path = output / 'sources/server'
    server = content.GitObjects(server_path, source['commit'], prefixes=content.SERVER_PREFIXES)
    eluna = content.GitObjects(server_path / content.ELUNA, source['submodules'][content.ELUNA])
    manifest = content.make_manifest(server, eluna, source, pin['sourceLockSha256'],
                                    compiled['enabledModules'], 'explicit-module-list', True)
    manifest_path = output / 'repacked-content-manifest.json'
    write_new(manifest_path, package.canonical(manifest))
    lua, lua_identity = modules.read_json(ROOT / 'runtime/server-lua-map.json')
    repacked = package.build_package(output / 'content', manifest, files.identity(manifest_path),
        compiled, files.identity(output / 'original-content/server-modules.json'), lua, lua_identity, server, eluna)
    require(repacked['source'] == original['source'] and repacked['sourceLockSha256'] == original['sourceLockSha256'],
            'repack changed selected server source')
    evidence = dict(formatVersion=1, scope='exact-linked-server-artifacts-staged-with-repacked-content',
        inputPinSha256=pin_identity['sha256'], originalInputs=pin, serverBuild=files.identity(install / 'server-build.json'),
        compiledModules=files.identity(output / 'original-content/server-modules.json'),
        originalContentReceipt=files.identity(output / 'original-content/package-receipt.json'),
        repackedContentReceipt=files.identity(output / 'content/package-receipt.json'),
        sourceLockSha256=pin['sourceLockSha256'], binariesChanged=False, recompiled=False,
        sourceContentRepacked=True, preparationSucceeded=True, sqlExecuted=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    write_new(output / 'preparation.json', encoded(evidence))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.output.absolute()), indent=2))
    except Exception as error:
        raise SystemExit('Server input preparation failed (' + type(error).__name__ + '); partial staging retained') from None


if __name__ == '__main__':
    main()
