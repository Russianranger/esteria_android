#!/usr/bin/env python3
"""Package a freshly built x86_64 dependency image for the opt-in Android MySQL test.

This never changes or accepts the production ARM64 provider. A Docker export is
normalized by the existing bounded rootfs packager, then independently read back.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
try:
    from . import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/mysql-probe/sources.lock.json'
ASSET = 'mysql-probe'
ARCHIVE = 'mysql-x86-64.archive'
MARKER = 'etc/esteria-mysql-probe.json'
SCOPE = 'android-13-x86-64-mysql-probe-build-only'
LIMITS = dict(entries=40000, memberBytes=256 * 1024**2, fileBytes=2 * 1024**3, pathBytes=4096)
INPUTS = ('runtime/mysql-probe/Dockerfile', 'runtime/mysql-probe/Dockerfile.dockerignore',
          'app/mysql-probe.gradle', 'app/src/androidTest/java/io/github/russianranger/esteria/runtime/MySqlExecutionTest.java',
          'tools/qualify_android_mysql.py', 'runtime/mysql-probe/record_runtime.py',
          'runtime/mysql-probe/guest_check.py', 'runtime/mysql-probe/mysql-binaries.SHA256SUMS',
          'runtime/server/ubuntu.sources', 'runtime/server/inrelease.SHA256SUMS', 'runtime/server/capture_sources.py',
          'runtime/mysql_bootstrap.py', 'runtime/android_database_setup.py',
          'tools/build_android_mysql_probe.py', 'tools/verify_android_mysql_probe.py',
          'tools/package_server_runtime.py', 'tools/prepare_runtime.py')
NAMES = {ARCHIVE, 'provider.json', 'runtime.json', 'sources.lock.json', 'guest_check.py', 'NOTICE.txt'}
NOTICE = b'''Emulator-only x86_64 Ubuntu24.04 / MySQL8 / Python3 fixture.
No production ARM64 provider identity or readiness is granted by this package.
Original copyright notices are retained in rootfs usr/share/doc. MySQL is GPL2;
all component notices and exact corresponding-source companions must accompany
redistribution. CI separately exports all installed package source archives plus
the exact recipe, bootstrap and test sources. No game data or database is packaged.
'''
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def identity(path):
    with archives.plain_file(path) as source:
        size = os.fstat(source.fileno()).st_size
        return dict(bytes=size, sha256=archives.hash_stream(source, size))


def metadata(raw):
    require(len(raw) <= 65536, 'mysql-probe-metadata-limit')
    value = json.loads(raw)
    lock_raw = LOCK.read_bytes(); lock = json.loads(lock_raw)
    require(value.get('formatVersion') == 1 and value.get('scope') == 'built-linux-x86-64-mysql-probe' and
            value.get('architecture') == 'amd64', 'mysql-probe-target')
    require(value.get('sourceLockSha256') == hashlib.sha256(lock_raw).hexdigest() and
            value.get('baseImage') == lock['baseImage']['reference'] and value.get('snapshot') == lock['snapshot']['id'] and
            value.get('expectedMysqlSqlVersion') == lock['mysql']['expectedRuntimeVersion'], 'mysql-probe-source-selection')
    for key in ('databaseInitialized', 'serverIncluded', 'serverExecuted', 'androidRuntimeQualified', 'gameLoginQualified'):
        require(value.get(key) is False, 'mysql-probe-overclaimed-image:' + key)
    packages = value.get('packages', [])
    require(0 < len(packages) <= 512 and all(row['architecture'] in ('amd64', 'all') for row in packages), 'mysql-probe-package-inventory')
    selected = {row['package'].split(':')[0]: row['version'] for row in packages}
    require(all(selected.get(row['package']) == row['version'] for row in lock['mysql']['binaryPackages']), 'mysql-probe-version-pins')
    images = value.get('images', {})
    require(set(images) == {'mysql', 'mysqld', 'python3'}, 'mysql-probe-image-inventory')
    components = {}
    for name, row in images.items():
        expected = {'mysql': '/usr/bin/mysql', 'mysqld': '/usr/sbin/mysqld', 'python3': '/usr/bin/python3.12'}[name]
        require(row['path'] == expected and row['elfMachine'] == 62 and
                type(row['bytes']) is int and 64 <= row['bytes'] <= LIMITS['memberBytes'], 'mysql-probe-executable-contract')
        require(isinstance(row['sha256'], str) and re.fullmatch('[a-f0-9]{64}', row['sha256']), 'mysql-probe-executable-hash')
        components[expected[1:]] = {**{key: row[key] for key in ('bytes', 'sha256')}, 'elfMachine': 62, 'elfClass': 2}
    components[MARKER] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return value, components


def contract(value, components, entries, file_bytes):
    return dict(markerPath=MARKER, marker=value, metadataFiles=['usr/lib/os-release'], components=components,
                archiveEntries=entries, archiveFileBytes=file_bytes, limits=LIMITS)


def build(export, measured, output):
    raw = reserve.read_small(measured); value, components = metadata(raw)
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'mysql-probe-output-exists')
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        assets = temporary / 'assets' / ASSET; assets.mkdir(parents=True)
        target = assets / ARCHIVE
        with archives.plain_file(export) as incoming, target.open('xb') as outgoing:
            require(os.fstat(incoming.fileno()).st_size <= 3 * 1024**3, 'mysql-probe-export-size-limit')
            counts = packaging.repack(incoming, outgoing)
            outgoing.flush(); os.fsync(outgoing.fileno())
        require(counts['entries'] <= LIMITS['entries'] and counts['fileBytes'] <= LIMITS['fileBytes'], 'mysql-probe-export-inventory-limit')
        with target.open('rb') as incoming:
            audit = archives.inspect_archive(incoming, contract(value, components, counts['entries'], counts['fileBytes']))
        require('ID=ubuntu' in audit['metadata']['usr/lib/os-release'] and 'VERSION_ID="24.04"' in audit['metadata']['usr/lib/os-release'], 'mysql-probe-distribution')
        links, copies, maximum = reserve.hardlink_budget(target, LIMITS)
        physical = counts['fileBytes'] + copies
        require(physical <= LIMITS['fileBytes'], 'mysql-probe-copy-reserve-limit')
        os_release = audit['metadata']['usr/lib/os-release'].encode()
        components['usr/lib/os-release'] = dict(bytes=len(os_release), sha256=hashlib.sha256(os_release).hexdigest())
        proof = dict(formatVersion=1, scope=SCOPE, architecture='x86_64', packageKey='mysql-probe-x86-64',
                     archive={**identity(target), 'assetPath': ASSET + '/' + ARCHIVE, 'file': 'mysql-x86-64.tar.gz'},
                     sourceLockSha256=hashlib.sha256(LOCK.read_bytes()).hexdigest(), runtimeMetadataSha256=hashlib.sha256(raw).hexdigest(),
                     sourceInputs={name: identity(ROOT / name) for name in INPUTS}, requiredFiles=components,
                     expectedMysqlSqlVersion=value['expectedMysqlSqlVersion'], archiveEntries=counts['entries'],
                     archiveFileBytes=counts['fileBytes'], maximumHardLinkCopies=links, maximumHardLinkCopyBytes=copies,
                     maximumPhysicalFileBytes=physical,
                     limits=dict(entries=counts['entries'], memberBytes=maximum, fileBytes=max(maximum, physical), pathBytes=4096, metadataBytes=16 * 1024**2),
                     archiveReadBack=True, androidMysqlQualified=False, productionAdapterQualified=False, arm64Qualified=False,
                     serverSchemasQualified=False, gameplayQualified=False, sourceCompanionRequired=True)
        require(len(encoded(proof)) <= 65536, 'mysql-probe-provider-metadata-limit')
        for name, data in {'provider.json': encoded(proof), 'runtime.json': raw, 'sources.lock.json': LOCK.read_bytes(),
                           'guest_check.py': (ROOT / 'runtime/mysql-probe/guest_check.py').read_bytes(), 'NOTICE.txt': NOTICE}.items():
            (assets / name).write_bytes(data)
        archives.sync_directory(assets)
        publish_directory(temporary, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if temporary.exists(): shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-export', type=Path, required=True)
    parser.add_argument('--runtime-metadata', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.docker_export, args.runtime_metadata, args.output), indent=2))


if __name__ == '__main__': main()
