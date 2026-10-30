#!/usr/bin/env python3
"""Optional pinned KGSL driver and mandatory original-source companion; no execution."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile
import tempfile
import zipfile

try:
    from . import prepare_runtime as archives, package_shader_tools as files
    from .provider_client_runtime import checked_zip
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_shader_tools as files
    from provider_client_runtime import checked_zip
    from package_server_content import publish_directory
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from runtime.turnip.record_build import elf, validate_no_gpu

LOCK = ROOT / 'runtime/turnip/android-provider.lock.json'
PREFIX = 'out/turnip/payload/'
ASSETS = 'turnip'
ARCHIVE = 'turnip-arm64.archive'
SOURCE = 'turnip-original-build.zip'
NAMES = {ARCHIVE, 'provider.json', 'NOTICE.txt'}
BINARIES = {'lib/libvulkan_freedreno.so': True, 'bin/esteria-turnip-probe': False}
LIMITS = dict(entries=128, memberBytes=32 << 20, fileBytes=32 << 20, pathBytes=512, metadataBytes=256 << 10)
FALSE_FLAGS = ('hardwareQualified', 'androidQualified', 'x11PresentationQualified', 'gameplayQualified')
ICD = b'{"file_format_version":"1.0.0","ICD":{"library_path":"/esteria-turnip/lib/libvulkan_freedreno.so","api_version":"1.3.0"}}\n'
NOTICE = b'''Optional Mesa Turnip26.1.4 ARM64 glibc KGSL driver; installation only.
Native Linux ARM64 build and exact-ICD loading without a GPU passed. No Adreno,
Android, X11 presentation or gameplay execution is qualified by this package.
Original license notices, exact build recipe and component evidence are retained.
The mandatory adjacent source companion preserves the complete original build
artifact and every locked upstream/direct-build source archive. It is not copied
into the APK. Separate Wine rootfs source closure is not claimed here.
No Wine files, imported game content, settings or saves are replaced.
'''
GENERATED = {'etc/turnip-icd.json': ICD, 'NOTICE.txt': NOTICE}
require = archives.require
encoded = files.encoded


def artifact_prefix(pin):
    prefix = pin.get('artifactPrefix', PREFIX)
    require(prefix in (PREFIX, 'turnip/'), 'turnip-artifact-prefix')
    if prefix != PREFIX:
        require(pin['artifact'].get('workflowPath') in ('.github/workflows/wine-arm64-provider-candidate.yml',
                '.github/workflows/wine-arm64-provider-source-recovery.yml'),
                'turnip-selected-artifact-workflow')
    return prefix


def identity_bytes(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def safe(name):
    require(type(name) is str and 0 < len(name.encode()) <= LIMITS['pathBytes'] and
            str(PurePosixPath(name)) == name and not name.startswith('/') and '\\' not in name and
            all(p not in ('', '.', '..') for p in name.split('/')) and all(ord(c) >= 32 for c in name),
            'turnip-path-invalid')
    return name


def load_pin(input_lock=None):
    pin = json.loads(files.small(input_lock if input_lock is not None else LOCK, 65536))
    require(type(pin.get('formatVersion')) is int and pin['formatVersion'] == 1 and
            pin.get('scope') == 'measured-turnip-kgsl-provider-inputs' and pin.get('nativeNoGpuQualified') is True and
            all(pin.get(k) is False for k in FALSE_FLAGS) and re.fullmatch('[0-9a-f]{40}', pin['integrationRevision']),
            'turnip-input-scope')
    prefix = artifact_prefix(pin)
    require(type(pin['files']) is dict and 1 <= len(pin['files']) < LIMITS['entries'] - len(GENERATED), 'turnip-file-count')
    for name, row in pin['files'].items():
        safe(name); safe(row['zipEntry'])
        require(set(row) == {'bytes', 'sha256', 'zipEntry'} and type(row['bytes']) is int and
                0 < row['bytes'] <= LIMITS['memberBytes'] and re.fullmatch('[0-9a-f]{64}', row['sha256']) and
                row['zipEntry'].startswith(prefix), 'turnip-file-pin')
    require(not pin['files'].keys() & GENERATED.keys() and
            sum(r['bytes'] for r in pin['files'].values()) < LIMITS['fileBytes'], 'turnip-total-size')
    require(set(BINARIES) <= pin['files'].keys() and 0 < pin['artifact']['bytes'] <= 512 << 20 and
            re.fullmatch('[0-9a-f]{64}', pin['artifact']['sha256']) and
            re.fullmatch('[0-9a-f]{64}', pin['requiredWineArchiveSha256']), 'turnip-artifact-pin')
    return pin


def inventory(pin):
    return dict({name: {k: row[k] for k in ('bytes', 'sha256')} for name, row in pin['files'].items()},
                **{name: identity_bytes(data) for name, data in GENERATED.items()})


def validate_metadata(values, binaries, pin):
    build = json.loads(values['provenance/turnip-build.json'])
    lock = json.loads(values['provenance/build-recipe/sources.lock.json'])
    require(type(build.get('formatVersion')) is int and build['formatVersion'] == 1 and
            build.get('scope') == 'linux-arm64-turnip-kgsl-build-only' and build.get('compiled') is True and
            all(build.get(k) is False for k in FALSE_FLAGS) and build['integrationRevision'] == pin['integrationRevision'] and
            build['runtimeArchiveSha256'] == pin['requiredWineArchiveSha256'] == lock['runtimeArchiveSha256'] and
            build['inputLockSha256'] == identity_bytes(values['provenance/build-recipe/sources.lock.json'])['sha256'] and
            identity_bytes(values['provenance/turnip-build.json'])['sha256'] == pin['buildReceiptSha256'], 'turnip-build-identity')
    require(build['upstream'] == lock['upstream'] and build['selectedPackages'] ==
            {p['package']: p['version'] for p in lock['packages']}, 'turnip-build-inputs')
    for key, expected in {'vulkan-drivers': ['freedreno'], 'freedreno-kmds': ['kgsl'], 'platforms': ['x11'],
                          'gallium-drivers': [], 'llvm': 'disabled', 'glx': 'disabled', 'egl': 'disabled'}.items():
        require(build['mesonOptions'][key] == expected, 'turnip-mesa-options')
    for name, shared in BINARIES.items():
        require(elf(binaries[name], shared) == build['binaries'][name], 'turnip-actual-elf-differs')
    require('libdrm.so.2' not in build['binaries']['lib/libvulkan_freedreno.so']['needed'], 'turnip-driver-is-not-kgsl')
    for name, row in build['recipeSources'].items():
        require(identity_bytes(values['provenance/build-recipe/' + safe(name)]) == row, 'turnip-recipe-differs')
    for name, row in build['notices'].items():
        require(identity_bytes(values[safe(name)]) == row, 'turnip-notice-differs')
    probe = json.loads(values['provenance/no-gpu-probe.json']); validate_no_gpu(probe)
    qualified = json.loads(values['provenance/no-gpu-check.json'])
    require(type(qualified.get('formatVersion')) is int and qualified['formatVersion'] == 1 and
            qualified.get('scope') == 'pinned-linux-arm64-turnip-probe' and qualified.get('qualified') is True and
            all(qualified.get(k) is False for k in FALSE_FLAGS) and qualified['receipt'] == probe and
            qualified['sourceRevision'] == pin['integrationRevision'] and qualified['buildReceiptSha256'] == pin['buildReceiptSha256'] and
            qualified['driver'] == build['binaries']['lib/libvulkan_freedreno.so'] and
            qualified['probe'] == build['binaries']['bin/esteria-turnip-probe'], 'turnip-no-gpu-evidence-differs')
    return build, lock


def source_pins(lock):
    pins = list(lock['upstream'].values()) + [a for s in lock['sources'] for a in s['archives']]
    result = {}
    for row in pins:
        name = safe(row['file'])
        require('/' not in name and name not in result and type(row['bytes']) is int and
                0 < row['bytes'] <= 256 << 20 and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'turnip-source-pin')
        result[name] = {k: row[k] for k in ('bytes', 'sha256')}
    require(1 <= len(result) <= 256 and sum(p['bytes'] for p in result.values()) <= 512 << 20, 'turnip-source-bounds')
    return result


def zip_metadata(archive, row):
    item = archive.getinfo(row['zipEntry'])
    require(stat.S_ISREG(item.external_attr >> 16) and item.file_size == row['bytes'] and
            0 < row['bytes'] <= 1 << 20, 'turnip-source-metadata-bound')
    with archive.open(item) as source: raw = source.read(row['bytes'] + 1)
    require(identity_bytes(raw) == {k: row[k] for k in ('bytes', 'sha256')}, 'turnip-source-metadata-differs')
    return raw


def verify_sources(artifact, pin):
    require(files.identity(artifact, 512 << 20) == {k: pin['artifact'][k] for k in ('bytes', 'sha256')}, 'turnip-original-artifact-differs')
    selected = {row['zipEntry'] for row in pin['files'].values()}
    with archives.plain_file(artifact) as incoming, checked_zip(incoming, selected, maximum_entries=2048) as archive:
        lock_name = pin['files']['provenance/build-recipe/sources.lock.json']
        raw = zip_metadata(archive, lock_name)
        expected = source_pins(json.loads(raw)); base = artifact_prefix(pin) + 'corresponding-source/original-archives/'
        manifest_row = pin['files']['provenance/source-manifest.json']; raw = zip_metadata(archive, manifest_row)
        manifest = json.loads(raw)
        require(manifest == dict(formatVersion=1, scope='exact-upstream-and-direct-build-input-sources',
                completeGuestRootfsSourceClosure=False, files=expected), 'turnip-source-manifest-closure')
        require({n.removeprefix(base) for n in archive.namelist() if n.startswith(base)} ==
                set(expected) | {'SOURCE-MANIFEST.json'}, 'turnip-source-archive-closure')
        for name, row in sorted(expected.items()):
            item = archive.getinfo(base + name)
            require(stat.S_ISREG(item.external_attr >> 16) and item.file_size == row['bytes'], 'turnip-source-type-or-size')
            with archive.open(item) as source:
                require(archives.hash_stream(source, row['bytes']) == row['sha256'], 'turnip-source-bytes-differ')
    return dict(formatVersion=1, scope='turnip-original-source-companion', artifact=pin['artifact'],
                integrationRevision=pin['integrationRevision'], originalArchives=len(expected),
                originalArchiveBytes=sum(r['bytes'] for r in expected.values()), sourceManifestSha256=manifest_row['sha256'],
                allLockedOriginalSourcesVerified=True, completeGuestRootfsSourceClosure=False,
                hardwareQualified=False, androidQualified=False, gameplayQualified=False)


def write_archive(target, artifact, pin):
    pins = inventory(pin)
    with archives.plain_file(artifact) as incoming, checked_zip(incoming,
            {r['zipEntry'] for r in pin['files'].values()}, maximum_entries=2048) as archive, target.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as tar:
                for name in sorted(pins):
                    item = tarfile.TarInfo(name); item.size = pins[name]['bytes']; item.mode = 0o755 if name in BINARIES else 0o644
                    item.uid = item.gid = item.mtime = 0
                    if name in GENERATED:
                        tar.addfile(item, io.BytesIO(GENERATED[name]))
                    else:
                        entry = archive.getinfo(pin['files'][name]['zipEntry'])
                        require(stat.S_ISREG(entry.external_attr >> 16) and entry.file_size == item.size, 'turnip-original-member-type-or-size')
                        with archive.open(entry) as source: tar.addfile(item, source)
        raw.flush(); os.fsync(raw.fileno())


def verify_archive(path, pin):
    pins = inventory(pin); seen = []; values = {}; binaries = {}
    with tempfile.TemporaryDirectory(prefix='esteria-turnip-elf-') as temporary:
        with archives.plain_file(path) as raw, archives.bounded_tar(raw, LIMITS) as tar:
            for item in tar:
                name = safe(item.name)
                require(name in pins and name not in seen and item.isfile() and item.size == pins[name]['bytes'] and
                        item.mode == (0o755 if name in BINARIES else 0o644) and item.uid == item.gid == item.mtime == 0,
                        'turnip-package-member-differs')
                if name in BINARIES:
                    destination = Path(temporary) / Path(name).name; binaries[name] = destination
                    with tar.extractfile(item) as source, destination.open('xb') as output:
                        digest = archives.hash_stream(source, item.size, output)
                else:
                    require(item.size <= 4 << 20, 'turnip-metadata-bound')
                    with tar.extractfile(item) as source: data = source.read(item.size + 1)
                    require(len(data) == item.size, 'turnip-metadata-length'); values[name] = data
                    digest = hashlib.sha256(data).hexdigest()
                require(digest == pins[name]['sha256'], 'turnip-package-bytes-differ')
                seen.append(name); tar.members.clear()
        require(seen == sorted(pins), 'turnip-package-file-set-or-order')
        validate_metadata(values, binaries, pin)
    return values


def descriptor(path, pin, input_lock=None):
    archive = files.identity(path, LIMITS['fileBytes']); required = inventory(pin)
    required = {n: dict(row, **({'elfMachine': 183} if n in BINARIES else {})) for n, row in sorted(required.items())}
    total = sum(r['bytes'] for r in required.values())
    result = dict(formatVersion=1, scope='android-turnip-kgsl-install-only', packageKey='turnip-arm64',
        archive=dict(archive, file='turnip-arm64.tar.gz', assetPath=ASSETS + '/' + ARCHIVE), requiredFiles=required,
        archiveEntries=len(required), archiveFileBytes=total, limits=LIMITS,
        freshSetupFreeBytes=archive['bytes'] + total + LIMITS['metadataBytes'] + (64 << 20),
        inputLockSha256=files.identity(input_lock if input_lock is not None else LOCK)['sha256'], integrationRevision=pin['integrationRevision'],
        buildReceiptSha256=pin['buildReceiptSha256'], requiredWineArchiveSha256=pin['requiredWineArchiveSha256'],
        guestMount='/esteria-turnip', icdPath='/esteria-turnip/etc/turnip-icd.json',
        sourceCompanionArtifact=pin['artifact'], sourceCompanionRequired=True, archiveVerified=True,
        elfAbiInspected=True, nativeNoGpuQualified=True, hardwareQualified=False, androidRuntimeQualified=False,
        x11PresentationQualified=False, gameplayQualified=False)
    require(len(encoded(result)) <= 65536, 'turnip-descriptor-bound'); return result


def build(artifact, output, input_lock=None):
    pin = load_pin(input_lock); source_receipt = verify_sources(artifact, pin)
    output = Path(os.path.abspath(output)); archives.directory(output.parent)
    require(not os.path.lexists(output), 'turnip-provider-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        assets = stage / 'assets' / ASSETS; assets.mkdir(parents=True)
        sources = stage / 'sources'; sources.mkdir()
        with archives.plain_file(artifact) as source, (sources / SOURCE).open('xb') as destination:
            require(archives.hash_stream(source, pin['artifact']['bytes'], destination) == pin['artifact']['sha256'],
                    'turnip-source-companion-copy-differs')
            destination.flush(); os.fsync(destination.fileno())
        files.write(sources / 'source-receipt.json', encoded(source_receipt))
        write_archive(assets / ARCHIVE, sources / SOURCE, pin); verify_archive(assets / ARCHIVE, pin)
        proof = descriptor(assets / ARCHIVE, pin, input_lock)
        files.write(assets / 'provider.json', encoded(proof)); files.write(assets / 'NOTICE.txt', NOTICE)
        verify(stage,input_lock=input_lock)
        for directory, _, _ in os.walk(stage, topdown=False): files.sync_directory(directory)
        publish_directory(stage, output); files.sync_directory(output.parent); return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(provider, apk=None, input_lock=None):
    pin = load_pin(input_lock); provider = archives.directory(provider)
    require({p.name for p in provider.iterdir()} == {'assets', 'sources'}, 'turnip-provider-root-closure')
    require({p.name for p in archives.directory(provider / 'assets').iterdir()} == {ASSETS}, 'turnip-provider-assets-closure')
    assets = archives.directory(provider / 'assets' / ASSETS); sources = archives.directory(provider / 'sources')
    require({p.name for p in assets.iterdir()} == NAMES and
            {p.name for p in sources.iterdir()} == {SOURCE, 'source-receipt.json'}, 'turnip-provider-file-set')
    require(files.small(sources / 'source-receipt.json') == encoded(verify_sources(sources / SOURCE, pin)), 'turnip-source-receipt-differs')
    verify_archive(assets / ARCHIVE, pin); proof = descriptor(assets / ARCHIVE, pin, input_lock)
    require(files.small(assets / 'provider.json', 65536) == encoded(proof) and
            files.small(assets / 'NOTICE.txt') == NOTICE, 'turnip-provider-metadata-differs')
    if apk is not None:
        selected = {'assets/' + ASSETS + '/' + n for n in NAMES}
        with archives.plain_file(apk) as raw, checked_zip(raw, selected, maximum_bytes=2 << 30, maximum_entries=4096) as archive:
            require({n for n in archive.namelist() if n.startswith('assets/' + ASSETS + '/')} == selected, 'turnip-apk-asset-set')
            for name in NAMES:
                item = archive.getinfo('assets/' + ASSETS + '/' + name); path = assets / name
                require(item.file_size == path.stat().st_size and
                        (name != ARCHIVE or item.compress_type == zipfile.ZIP_STORED), 'turnip-apk-size-or-compression')
                with archive.open(item) as source, archives.plain_file(path) as original:
                    require(archives.hash_stream(source, item.file_size) == archives.hash_stream(original, item.file_size), 'turnip-apk-bytes')
    return dict(providerVerified=True, sourceCompanionVerified=True, apkBytesVerified=apk is not None,
                archive=proof['archive'], nativeNoGpuQualified=True, hardwareQualified=False, androidQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build'); create.add_argument('--artifact', type=Path, required=True); create.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('--provider', type=Path, required=True); check.add_argument('--apk', type=Path)
    for command in (create,check): command.add_argument('--input-lock',type=Path,help='explicit separately measured provider input lock')
    args = parser.parse_args(); print(json.dumps(build(args.artifact, args.output, args.input_lock) if args.command == 'build' else verify(args.provider, args.apk, args.input_lock), indent=2))


if __name__ == '__main__': main()
