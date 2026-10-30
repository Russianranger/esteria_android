#!/usr/bin/env python3
"""Package the source-matched reconstructed ARM64 client; no game data or stock EXE."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import types
import zipfile

try:
    from . import prepare_runtime as archives, fetch_sources
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, fetch_sources
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
PIN = ROOT / 'runtime/client/android-provider.lock.json'
SOURCE_LOCK = ROOT / 'sources.lock.json'
ASSETS = 'assets/client-runtime'
ARCHIVE = 'client-arm64.archive'
MARKER = 'client-runtime.json'
LOCAL_ACCOUNT_CAPABILITIES = {'local_account_handoff': {
    'version': 1, 'flag': '--local-login', 'requires': ['--local-offline'],
    'filename': 'Esteria-local-login.bin', 'format': 'ESTLOGN1', 'bytes': 57,
    'endpoint': '127.0.0.1:3724',
}}
META_LIMIT = 2 * 1024**2
BINARIES = ('WowClient64.exe', 'XvidDecoder.dll')
SELECTED = {
    **{'bin/Win/ARM64/' + name: 'bin/' + name for name in BINARIES},
    'bin/Win/ARM64/client-build.json': 'metadata/client-build.json',
    'build/client/generated/limits/limits.json': 'metadata/limits.json',
    'build/client/Tools/XvidDecoder/Xvid-1.3.7-LICENSE.txt': 'notices/Xvid-1.3.7-LICENSE.txt',
    'ThirdParty/xvidcore/licenses/xvid.txt': 'notices/ThirdParty/xvidcore/licenses/xvid.txt',
}
NOTICE = b'''Reconstructed Esteria Windows ARM64 client for an explicitly selected local Wine runtime.
This package contains WowClient64.exe and its matching XvidDecoder.dll, not stock Wow.exe.
Client repository source and protocol revision are recorded in client-runtime.json.
Original component license notices are retained without relicensing them.
The pinned client checkout has no top-level LICENSE; this package does not assign one.
FMOD Sound System, copyright Firelight Technologies Pty, Ltd. See its original notice.
Xvid 1.3.7 source, adapter and exact build recipe are identified in source-recipes/.
Preserve corresponding sources and notices with distributions; CI artifacts expire.
No imported game data, account, database, shader output or persistent state is included.
Binary packaging does not qualify Android startup, game initialization or gameplay.
'''
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def capabilities(parser):
    """Older measured clients retain byte-identical providers and gain no capability."""
    if not hasattr(parser, 'CAPABILITIES'):return None
    require(encoded(parser.CAPABILITIES) == encoded(LOCAL_ACCOUNT_CAPABILITIES),
            'unsupported-client-capabilities')
    return parser.CAPABILITIES


def small(path, maximum=META_LIMIT):
    with archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size <= maximum, 'client-metadata-size-limit')
        data = stream.read(maximum + 1)
    require(len(data) <= maximum, 'client-metadata-size-limit')
    return data


def identity(path):
    with archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        return dict(bytes=size, sha256=archives.hash_stream(stream, size))


def verify_identity(path, pin):
    with archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size == pin['bytes'], 'client-provider-size-mismatch:' + path.name)
        require(archives.hash_stream(stream, pin['bytes']) == pin['sha256'], 'client-provider-hash-mismatch:' + path.name)


def checked_zip(stream, required=SELECTED, maximum_bytes=512 * 1024**2, maximum_entries=1024,
                maximum_directory=META_LIMIT):
    """Bound the central directory before ZipFile allocates its member list."""
    size = os.fstat(stream.fileno()).st_size
    require(22 <= size <= maximum_bytes, 'client-artifact-size-limit')
    stream.seek(max(0, size - 65557));tail = stream.read(65557)
    offset = tail.rfind(b'PK\x05\x06')
    require(offset >= 0 and len(tail) - offset >= 22, 'missing-zip-directory')
    disk, first_disk, disk_entries, entries, length, start, comment = struct.unpack_from('<4H2IH', tail, offset + 4)
    require(disk == first_disk == 0 and disk_entries == entries and 0 < entries <= maximum_entries and
            length <= maximum_directory and start + length == size - len(tail) + offset and
            offset + 22 + comment == len(tail), 'client-zip-directory-limit-or-layout')
    archive = zipfile.ZipFile(stream)
    try:
        infos = archive.infolist()
        require(len(infos) == entries, 'client-zip-entry-count')
        seen = set()
        for entry in infos:
            name = entry.filename
            require(name not in seen and 0 < len(name.encode()) <= 4096 and '\\' not in name and
                    not name.startswith('/') and all(part not in ('', '.', '..') for part in name.rstrip('/').split('/')),
                    'client-zip-unsafe-or-duplicate-path')
            mode = entry.external_attr >> 16
            require(not stat.S_ISLNK(mode) and not entry.flag_bits & 1 and
                    entry.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'client-zip-unsupported-entry')
            seen.add(name)
        require(set(required) <= seen, 'client-artifact-selected-file-missing')
        return archive
    except Exception:
        archive.close();raise


def copy_selected(archive, tree):
    for original, name in SELECTED.items():
        entry = archive.getinfo(original)
        maximum = 64 * 1024**2 if name.startswith('bin/') else META_LIMIT
        require(0 < entry.file_size <= maximum, 'client-selected-member-size-limit')
        target = tree / name;target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(entry) as incoming, target.open('xb') as output:
            remaining = entry.file_size
            while remaining:
                chunk = incoming.read(min(remaining, archives.BUFFER))
                require(bool(chunk), 'truncated-client-member');output.write(chunk);remaining -= len(chunk)
            require(not incoming.read(1), 'client-member-size-changed')


def source_blob(source, revision, name):
    # Read committed blobs rather than ignored working-tree or generated files.
    spec = revision + ':' + name
    length = int(fetch_sources.run('git', 'cat-file', '-s', spec, cwd=source))
    require(0 < length <= META_LIMIT, 'client-source-file-size-limit')
    data = subprocess.check_output(['git', 'show', spec], cwd=source)
    require(len(data) == length, 'client-source-file-size-changed')
    return data


def no_delay_imports(path):
    # The pinned PE parser validates PE32+ header bounds first. Until a delay
    # import parser is supplied, refuse such images rather than omit dependencies.
    with archives.plain_file(path) as stream:
        stream.seek(60);offset = struct.unpack('<I', stream.read(4))[0]
        stream.seek(offset + 24 + 108);count = struct.unpack('<I', stream.read(4))[0]
        if count > 13:
            stream.seek(offset + 24 + 112 + 13 * 8)
            require(stream.read(8) == bytes(8), 'client-delay-imports-not-supported')


def prepare(artifact, source, tree, pin, source_bytes):
    lock = json.loads(source_bytes);source_pin = lock['sources']['client']
    require(source_pin['commit'] == pin['sourceRevision'] and not source_pin['patches'] and
            not source_pin['submodules'], 'client-source-pin-mismatch')
    fetch_sources.verify_checkout(source, source_pin, [])
    require(lock['compatibility'] == dict(base_client_build=12340, extended_limits=True,
            container_slots=254, quest_log_slots=25, client_class_capacity=32), 'client-protocol-lock-mismatch')
    with archives.plain_file(artifact) as stream:
        before = os.fstat(stream.fileno())
        require(0 < pin['artifact']['bytes'] <= 512 * 1024**2 and before.st_size == pin['artifact']['bytes'],
                'client-artifact-size-mismatch')
        require(archives.hash_stream(stream, before.st_size) == pin['artifact']['sha256'], 'client-artifact-identity-mismatch')
        with checked_zip(stream) as archive:copy_selected(archive, tree)
        after = os.fstat(stream.fileno())
        require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'client-artifact-changed-during-read')
    build_bytes = small(tree / 'metadata/client-build.json');manifest = json.loads(build_bytes)
    require(hashlib.sha256(build_bytes).hexdigest() == pin['buildManifestSha256'], 'client-build-manifest-pin-mismatch')
    parser = types.ModuleType('pinned_client_manifest')
    parser_source = source_blob(source, pin['sourceRevision'], 'Tools/RuntimeManifest/generate.py')
    exec(compile(parser_source, 'pinned-client/Tools/RuntimeManifest/generate.py', 'exec'), parser.__dict__)
    actual = [parser.inspect_file(tree / 'bin' / name, 'ARM64', name.endswith('.dll')) for name in BINARIES]
    expected = dict(schema_version=1, component='esteria-reconstructed-client', evidence='build-only',
                    architecture='ARM64', source_revision=pin['sourceRevision'], build_id=pin['buildId'],
                    protocol=dict(parser.PROTOCOL), descriptor_manifest=parser.descriptor_info(tree / 'metadata/limits.json'),
                    files=actual)
    selected_capabilities = capabilities(parser)
    if selected_capabilities is not None:expected['capabilities'] = selected_capabilities
    require(encoded(manifest) == encoded(expected), 'client-build-manifest-differs-from-actual-images')
    for name in BINARIES:no_delay_imports(tree / 'bin' / name)
    imports = sorted({name.casefold() for image in actual for name in image['imports']})
    require('xviddecoder.dll' in imports, 'client-local-codec-import-missing')
    tracked = fetch_sources.run('git', 'ls-tree', '-r', '--name-only', pin['sourceRevision'], cwd=source).splitlines()
    notices = [name for name in tracked if re.fullmatch(r'(?:license|copying|notice|copyright)(?:[._-].*)?',
                                                        PurePosixPath(name).name, re.I)]
    notices += ['ThirdParty/zlib/README', 'ThirdParty/freetype/docs/FTL.txt', 'ThirdParty/freetype/docs/GPL.txt',
                'ThirdParty/freetype/src/autohint/CatharonLicense.txt']
    require(len(set(notices)) <= 128, 'client-notice-count-limit')
    recipes = ['cmake/XvidPortable.cmake', 'Tools/XvidDecoder/CMakeLists.txt', 'Tools/XvidDecoder/XvidDecoder.cpp',
               'Tools/XvidDecoder/XvidDecoder.def', 'Tools/RuntimeManifest/generate.py']
    for prefix, names in [('notices', sorted(set(notices))), ('source-recipes', recipes)]:
        for name in names:
            target = tree / prefix / name;target.parent.mkdir(parents=True, exist_ok=True)
            # The legacy bundled Xvid notice is also in the build artifact.
            data = source_blob(source, pin['sourceRevision'], name)
            if target.exists():require(small(target) == data, 'artifact-source-notice-mismatch')
            else:target.write_bytes(data)
    (tree / 'NOTICE.txt').write_bytes(NOTICE)
    (tree / 'metadata/sources.lock.json').write_bytes(source_bytes)
    wine = json.loads(small(archives.DEFAULT_LOCK))['packages']['wine-arm64']
    marker = dict(formatVersion=1, scope='packaged-reconstructed-windows-arm64-client',
        source=source_pin, sourceLockSha256=hashlib.sha256(source_bytes).hexdigest(), inputArtifact=pin,
        buildId=pin['buildId'], protocol=manifest['protocol'], executable='bin/WowClient64.exe',
        runtimeDlls=['bin/XvidDecoder.dll'], directWineImports=[name for name in imports if name != 'xviddecoder.dll'],
        delayImportsAbsent=True, peImportsVerified=True, completeDynamicImportClosureQualified=False,
        requiredExternalContent=['build-12340-effective-Data', 'matching-Esteria-catalogs', 'generated-VulkanShaders'],
        mutableSessionPaths=['WTF', 'Cache', 'Logs', 'Screenshots', 'WowClient_crash.log', 'EsteriaDecomp.log'],
        requiredWineRuntime=dict(archiveSha256=wine['archive']['sha256'], manifestSha256=wine['manifest']['sha256']),
        windowsCompatibilityRuntimeRequired=True, androidRuntimeQualified=False, gameInitializationQualified=False,
        gameLoginQualified=False)
    if selected_capabilities is not None:marker['capabilities'] = selected_capabilities
    (tree / MARKER).write_bytes(encoded(marker))
    inventory = {str(path.relative_to(tree)): identity(path) for path in sorted(tree.rglob('*')) if path.is_file()}
    for image in actual:
        inventory['bin/' + image['name']].update(peMachine='0xaa64')
    return marker, inventory


def write_archive(path, tree, inventory):
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as tar:
                for name, pin in sorted(inventory.items()):
                    item = tarfile.TarInfo(name);item.size = pin['bytes'];item.mode = 0o444
                    with archives.plain_file(tree / name) as incoming:tar.addfile(item, incoming)
        raw.flush();os.fsync(raw.fileno())


def audit(path, inventory):
    limits = dict(entries=len(inventory), memberBytes=max(pin['bytes'] for pin in inventory.values()),
                  fileBytes=sum(pin['bytes'] for pin in inventory.values()), pathBytes=4096)
    seen = set()
    with archives.plain_file(path) as raw, archives.bounded_tar(raw, limits) as tar:
        for item in tar:
            require(item.name in inventory and item.name not in seen and item.isfile() and not item.issparse() and
                    item.mode == 0o444 and item.mtime == item.uid == item.gid == 0 and not item.uname and not item.gname,
                    'client-provider-archive-member-mismatch')
            pin = inventory[item.name];require(item.size == pin['bytes'], 'client-provider-member-size')
            with tar.extractfile(item) as incoming:
                require(archives.hash_stream(incoming, item.size) == pin['sha256'], 'client-provider-member-hash')
            seen.add(item.name);tar.members.clear()
    require(seen == set(inventory), 'client-provider-member-missing')
    return limits


def verify_apk(apk, assets):
    names = {ARCHIVE, 'provider.json', 'NOTICE.txt'}
    prefix = ASSETS + '/'
    with archives.plain_file(apk) as stream, checked_zip(stream, {prefix + name for name in names},
            maximum_bytes=2 * 1024**3, maximum_entries=32768, maximum_directory=16 * 1024**2) as archive:
        require({name for name in archive.namelist() if name.startswith(prefix)} == {prefix + name for name in names},
                'apk-client-provider-set-mismatch')
        for name in names:
            entry = archive.getinfo(prefix + name);expected = identity(assets / name)
            require(entry.file_size == expected['bytes'], 'apk-client-asset-size-mismatch')
            if name == ARCHIVE:require(entry.compress_type == zipfile.ZIP_STORED, 'client-archive-must-be-uncompressed-in-apk')
            with archive.open(entry) as incoming:
                require(archives.hash_stream(incoming, entry.file_size) == expected['sha256'], 'apk-client-asset-hash-mismatch')


def run(artifact, source, output, verify=False, apk=None):
    require(apk is None or verify, 'apk-check-requires-verified-provider')
    pin_bytes = small(PIN);pin = json.loads(pin_bytes)
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-reconstructed-client-provider-inputs' and
            pin.get('androidRuntimeQualified') is False, 'invalid-client-provider-pin')
    source_bytes = small(SOURCE_LOCK);fetch_sources.load_lock(SOURCE_LOCK)
    output = Path(os.path.abspath(output));archives.directory(output.parent, create=True)
    if not verify:require(not os.path.lexists(output), 'client-provider-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.client-provider-', dir=output.parent))
    try:
        tree = stage / 'tree';tree.mkdir()
        marker, inventory = prepare(artifact, source, tree, pin, source_bytes)
        provider = stage / 'provider';assets = provider / ASSETS;assets.mkdir(parents=True)
        archive = assets / ARCHIVE;write_archive(archive, tree, inventory)
        limits = audit(archive, inventory)
        proof = dict(formatVersion=1, scope='android-reconstructed-client-install-only', packageKey='client-arm64',
            archive=dict(identity(archive), assetPath='client-runtime/' + ARCHIVE),
            inputLockSha256=hashlib.sha256(pin_bytes).hexdigest(), sourceRevision=pin['sourceRevision'],
            sourceLockSha256=marker['sourceLockSha256'], buildId=pin['buildId'], protocol=marker['protocol'],
            requiredWineRuntime=marker['requiredWineRuntime'],
            requiredWineArchiveSha256=marker['requiredWineRuntime']['archiveSha256'],
            requiredFiles=inventory, archiveEntries=len(inventory), archiveFileBytes=limits['fileBytes'],
            limits=dict(limits, metadataBytes=16 * 1024**2), maximumHardLinkCopies=0, maximumHardLinkCopyBytes=0,
            maximumPhysicalFileBytes=limits['fileBytes'],
            freshSetupFreeBytes=archive.stat().st_size + limits['fileBytes'] + 80 * 1024**2,
            archiveVerified=True, peHeadersAndDirectImportsVerified=True, completeDynamicImportClosureQualified=False,
            androidRuntimeQualified=False, gameInitializationQualified=False, gameLoginQualified=False)
        if 'capabilities' in marker:proof['capabilities'] = marker['capabilities']
        require(len(encoded(proof)) <= META_LIMIT, 'client-provider-metadata-limit')
        (assets / 'provider.json').write_bytes(encoded(proof))
        (assets / 'NOTICE.txt').write_bytes(NOTICE)
        if verify:
            actual_assets = archives.directory(output / ASSETS)
            require({p.name for p in actual_assets.iterdir()} == {ARCHIVE, 'provider.json', 'NOTICE.txt'},
                    'unexpected-client-provider-file')
            for name in (ARCHIVE, 'provider.json', 'NOTICE.txt'):
                verify_identity(actual_assets / name, identity(assets / name))
            audit(actual_assets / ARCHIVE, inventory)
            if apk is not None:verify_apk(apk, actual_assets)
        else:
            publish_directory(provider, output);archives.sync_directory(output.parent)
        return proof
    finally:
        shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('build', 'verify'))
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--client-source', type=Path, required=True)
    parser.add_argument('--provider', type=Path, required=True)
    parser.add_argument('--apk', type=Path, help='verify exact embedded asset inventory and bytes; verify command only')
    args = parser.parse_args()
    print(json.dumps(run(args.artifact, args.client_source, args.provider, args.command == 'verify', args.apk), indent=2))


if __name__ == '__main__':main()
