#!/usr/bin/env python3
"""Normalize and read back a fresh, source-built emulator Wine rootfs.

This package contains no reconstructed client, game assets or initialized prefix.
The Android fixture consumes its exact measured archive in a later build step.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
try:
    from . import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/wine-probe/sources.lock.json'
MARKER = 'etc/esteria-wine-probe.json'
LIMITS = dict(entries=50000, memberBytes=512 * 1024**2, fileBytes=4 * 1024**3, pathBytes=4096)
IMAGES = {'wine': '/opt/wine/bin/wine', 'wineserver': '/opt/wine/bin/wineserver',
          'ntdllUnix': '/opt/wine/lib/wine/x86_64-unix/ntdll.so', 'python3': '/usr/bin/python3.11',
          **{name: '/opt/wine/lib/wine/x86_64-windows/' + name for name in
             ('kernel32.dll', 'ntdll.dll', 'msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'ws2_32.dll', 'wininet.dll')}}
INPUTS = ('runtime/wine-probe/sources.lock.json', 'runtime/wine-probe/Dockerfile',
          'runtime/wine-probe/Dockerfile.dockerignore', 'runtime/wine-probe/record_runtime.py',
          'runtime/wine-probe/capture_sources.py', 'runtime/bridges/debian.sources',
          'runtime/bridges/inrelease.SHA256SUMS', 'tools/package_android_wine_runtime.py',
          'tools/package_server_runtime.py', 'tools/prepare_runtime.py', 'tools/provider_server_runtime.py')
require = archives.require


def identity(path):
    with archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        return dict(bytes=size, sha256=archives.hash_stream(stream, size))


def metadata(raw):
    require(len(raw) <= 131072, 'wine-metadata-limit')
    value = json.loads(raw); lock_raw = LOCK.read_bytes(); lock = json.loads(lock_raw)
    require(value.get('formatVersion') == 1 and value.get('scope') == 'built-linux-x86-64-wine-probe' and
            value.get('architecture') == 'amd64', 'wine-runtime-scope')
    require(value.get('sourceLockSha256') == hashlib.sha256(lock_raw).hexdigest() and
            value.get('baseImage') == lock['baseImage']['reference'] and value.get('snapshot') == lock['snapshot']['id'] and
            value.get('wineRevision') == lock['wine']['revision'] and
            value.get('wineSourceArchiveSha256') == lock['wine']['sourceArchive']['sha256'], 'wine-runtime-source-selection')
    require(isinstance(value.get('wineVersion'), str) and
            re.fullmatch(r'wine-10\.13(?:[ -][^\r\n]{1,80})?', value['wineVersion']), 'wine-runtime-version')
    for key in ('prefixInitialized', 'clientIncluded', 'clientExecuted', 'androidRuntimeQualified', 'arm64Qualified', 'gameplayQualified'):
        require(value.get(key) is False, 'wine-runtime-build-overclaim:' + key)
    packages = value.get('packages', [])
    require(0 < len(packages) <= 512 and all(row['architecture'] in ('amd64', 'all') for row in packages), 'wine-package-inventory')
    source_packages = [dict(package=name, version=version) for name, version in sorted(
        {(row['sourcePackage'], row['sourceVersion']) for row in packages})]
    require(value.get('sourcePackages') == source_packages, 'wine-source-inventory')
    images = value.get('images', {}); require(set(images) == set(IMAGES), 'wine-image-inventory')
    components = {}
    for name, row in images.items():
        expected = IMAGES[name]
        require(row.get('path') == expected and type(row.get('bytes')) is int and
                64 <= row['bytes'] <= LIMITS['memberBytes'] and isinstance(row.get('sha256'), str) and
                re.fullmatch('[a-f0-9]{64}', row['sha256']), 'wine-image-identity')
        machine = dict(peMachine='0x8664') if expected.endswith('.dll') else dict(elfMachine=62, elfClass=2)
        require(all(row.get(key) == item for key, item in machine.items()), 'wine-image-architecture')
        components[expected[1:]] = {**{key: row[key] for key in ('bytes', 'sha256')}, **machine}
    components[MARKER] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return value, components


def fresh_export(source):
    """Reject real prefix/session state even if a forged marker says false.

    This is a streaming metadata preflight; the separate repacker still performs
    its full path/type/size checks and the emitted archive is independently read.
    """
    count = total = 0
    with packaging.docker_tar(source) as archive:
        for member in archive:
            count += 1; total += member.size
            require(count <= LIMITS['entries'] and 0 <= member.size <= LIMITS['memberBytes'] and
                    total <= LIMITS['fileBytes'], 'wine-input-inventory-limit')
            if member.name not in ('.', './'):
                name = archives.member_path(member.name)
                require(not re.match(r'^(?:root/\.wine|home/[^/]+/\.wine|work|prefix|client|session)(?:/|$)', name),
                        'wine-prefix-or-session-state:' + name)
            archive.members.clear()
    source.seek(0)


def build(export, measured, output):
    with archives.plain_file(measured) as stream: raw = stream.read(131073)
    value, components = metadata(raw)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'wine-runtime-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        archive = stage / 'wine-x86-64.tar.gz'
        with archives.plain_file(export) as incoming, archive.open('xb') as outgoing:
            require(os.fstat(incoming.fileno()).st_size <= 6 * 1024**3, 'wine-export-size-limit')
            fresh_export(incoming)
            counts = packaging.repack(incoming, outgoing)
            outgoing.flush(); os.fsync(outgoing.fileno())
        require(counts['entries'] <= LIMITS['entries'] and counts['fileBytes'] <= LIMITS['fileBytes'], 'wine-export-inventory-limit')
        contract = dict(markerPath=MARKER, marker=value, metadataFiles=['usr/lib/os-release'], components=components,
                        archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'], limits=LIMITS)
        with archive.open('rb') as stream: audit = archives.inspect_archive(stream, contract)
        require('ID=debian' in audit['metadata']['usr/lib/os-release'] and
                'VERSION_ID="12"' in audit['metadata']['usr/lib/os-release'], 'wine-runtime-distribution')
        links, copies, maximum = reserve.hardlink_budget(archive, LIMITS)
        physical = counts['fileBytes'] + copies
        require(physical <= LIMITS['fileBytes'], 'wine-copy-reserve-limit')
        release = audit['metadata']['usr/lib/os-release'].encode()
        components['usr/lib/os-release'] = dict(bytes=len(release), sha256=hashlib.sha256(release).hexdigest())
        proof = dict(formatVersion=1, scope='packaged-linux-x86-64-wine-probe-build-only',
                     archive=dict(file=archive.name, **identity(archive)), sourceLockSha256=identity(LOCK)['sha256'],
                     runtimeMetadataSha256=hashlib.sha256(raw).hexdigest(), sourceInputs={name: identity(ROOT / name) for name in INPUTS},
                     requiredFiles=components, archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'],
                     maximumHardLinkCopies=links, maximumHardLinkCopyBytes=copies, maximumPhysicalFileBytes=physical,
                     limits=dict(entries=counts['entries'], memberBytes=maximum, fileBytes=max(maximum, physical), pathBytes=4096, metadataBytes=16 * 1024**2),
                     archiveReadBack=True, sourceCompanionRequired=True, clientIncluded=False,
                     androidRuntimeQualified=False, arm64Qualified=False, gameplayQualified=False)
        for name, contents in {'package-receipt.json': (json.dumps(proof, sort_keys=True, indent=2) + '\n').encode(),
                               'runtime.json': raw, 'sources.lock.json': LOCK.read_bytes()}.items():
            (stage / name).write_bytes(contents)
        archives.sync_directory(stage); publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-export', type=Path, required=True)
    parser.add_argument('--runtime-metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(build(args.docker_export, args.runtime_metadata, args.output), indent=2))


if __name__ == '__main__': main()
