#!/usr/bin/env python3
"""Create and independently verify an optional source-pinned shader APK provider."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile

try:
    from . import prepare_runtime as archives, package_shader_tools as bundle
    from .provider_client_runtime import checked_zip
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_shader_tools as bundle
    from provider_client_runtime import checked_zip
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/shaders/android-provider.lock.json'
ASSETS = 'shader-tools'
ARCHIVE = 'shader-tools-arm64.archive'
NAMES = {ARCHIVE, 'provider.json', 'bundle.json', 'NOTICE.txt'}
LIMITS = dict(entries=128, memberBytes=16 << 20, fileBytes=32 << 20, pathBytes=512, metadataBytes=256 << 10)
COMPILER = 'tools/bin/glslangValidator'
NOTICE = b'''Esteria offline shader tools for the separately pinned ARM64 glibc Wine guest.
Includes exact committed translator sources, measured glslang, original compiler
source archives and license notices. Application client PE revision is separate.
Packaging does not qualify Android shader generation, imported MPQ shaders or
game rendering. No game data, imported assets or persistent state is included.
'''
require = archives.require
encoded = bundle.encoded


def safe(name):
    require(type(name) is str and 0 < len(name.encode()) <= LIMITS['pathBytes'] and
            str(PurePosixPath(name)) == name and not name.startswith('/') and '\\' not in name and
            all(p not in ('', '.', '..') for p in name.split('/')) and all(ord(c) >= 32 for c in name),
            'shader-provider-path-invalid')
    return name


def load_pin():
    pin = json.loads(bundle.small(LOCK, 65536))
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-offline-shader-provider-inputs' and
            pin.get('nativeCompilerFixtureQualified') is True and
            all(pin.get(k) is False for k in ('androidQualified', 'gameAssetShadersQualified', 'gameplayQualified')),
            'shader-provider-input-scope')
    files = pin['files']; require(type(files) is dict and 1 <= len(files) < LIMITS['entries'], 'shader-provider-file-count')
    require({p for p in files if p.startswith('tools/')} ==
            {'tools/' + p for p in bundle.PYTHON} | {COMPILER, 'tools/shader-tools.json'}, 'shader-tool-closure-pin')
    for name, row in files.items():
        safe(name)
        require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and
                0 < row['bytes'] <= LIMITS['memberBytes'] and type(row['sha256']) is str and
                len(row['sha256']) == 64 and all(c in '0123456789abcdef' for c in row['sha256']), 'shader-provider-file-pin')
    helper = pin['helper']
    require(helper['source'] == 'runtime/shader_generation.py' and helper['installedPath'] == 'helpers/shader_generation.py' and
            helper['installedPath'] not in files and bundle.identity(ROOT / helper['source']) ==
            {k: helper[k] for k in ('bytes', 'sha256')}, 'shader-helper-source-changed')
    require(sum(r['bytes'] for r in files.values()) + helper['bytes'] <= LIMITS['fileBytes'], 'shader-provider-total-bound')
    return pin


def inventory(pin):
    return dict(pin['files'], **{pin['helper']['installedPath']: {k: pin['helper'][k] for k in ('bytes', 'sha256')}})


def validate_metadata(values, compiler, pin):
    report = json.loads(values['provenance/bundle.json'])
    manifest = json.loads(values['tools/shader-tools.json'])
    require(report['clientRevision'] == pin['clientRevision'] and
            report['integrationRevision'] == pin['compilerIntegrationRevision'] and
            report['buildReceiptSha256'] == pin['compilerBuildSha256'] and
            report['toolManifestSha256'] == pin['toolManifestSha256'] and
            report['wineRuntimeArchiveSha256'] == pin['requiredWineArchiveSha256'] and
            report['nativeCompilerFixtureQualified'] is True and
            all(report[k] is False for k in ('androidQualified', 'gameAssetShadersQualified', 'gameplayQualified')),
            'shader-bundle-receipt-mismatch')
    require(hashlib.sha256(values['provenance/bundle.json']).hexdigest() == pin['bundleReceiptSha256'] and
            hashlib.sha256(values['tools/shader-tools.json']).hexdigest() == pin['toolManifestSha256'], 'shader-bundle-pin-mismatch')
    expected = {name.removeprefix('tools/'): row for name, row in pin['files'].items()
                if name.startswith('tools/') and name != 'tools/shader-tools.json'}
    require(manifest == dict(formatVersion=1, clientRevision=pin['clientRevision'], files=expected), 'shader-manifest-closure-mismatch')
    require(bundle.measure_elf(compiler) == report['compiler'], 'shader-compiler-elf-mismatch')


def selected_files(directory, pin):
    directory = archives.directory(directory)
    found = set()
    for parent, folders, names in os.walk(directory, followlinks=False):
        for name in folders: archives.directory(Path(parent) / name)
        for name in names: found.add((Path(parent) / name).relative_to(directory).as_posix())
    require(found == set(pin['files']), 'shader-bundle-file-set-mismatch')
    files = {name: directory / name for name in found}
    files[pin['helper']['installedPath']] = ROOT / pin['helper']['source']
    for name, row in inventory(pin).items(): require(bundle.identity(files[name]) == row, 'shader-bundle-file-mismatch:' + name)
    validate_metadata({name: bundle.small(files[name]) for name in ('provenance/bundle.json', 'tools/shader-tools.json')}, files[COMPILER], pin)
    return files


def write_archive(path, files, pins):
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as tar:
                for name in sorted(files):
                    item = tarfile.TarInfo(name); item.size = pins[name]['bytes']; item.mode = 0o755 if name == COMPILER else 0o644
                    item.uid = item.gid = item.mtime = 0
                    with archives.plain_file(files[name]) as source: tar.addfile(item, source)
        raw.flush(); os.fsync(raw.fileno())


def verify_archive(path, pin):
    pins = inventory(pin); seen = []; values = {}
    with tempfile.TemporaryDirectory(prefix='esteria-shader-readback-') as temporary:
        compiler = Path(temporary) / 'glslangValidator'
        with archives.plain_file(path) as raw, archives.bounded_tar(raw, LIMITS) as tar:
            for item in tar:
                name = safe(item.name)
                require(name in pins and name not in seen and item.isfile() and item.size == pins[name]['bytes'] and
                        item.mode == (0o755 if name == COMPILER else 0o644) and item.uid == item.gid == item.mtime == 0,
                        'shader-archive-member-mismatch')
                digest = hashlib.sha256(); remaining = item.size; metadata = bytearray()
                output = compiler.open('xb') if name == COMPILER else None
                try:
                    with tar.extractfile(item) as source:
                        while remaining:
                            data = source.read(min(remaining, 65536)); require(data, 'shader-archive-truncated')
                            digest.update(data); remaining -= len(data)
                            if output: output.write(data)
                            if name in ('provenance/bundle.json', 'tools/shader-tools.json'):
                                metadata.extend(data); require(len(metadata) <= 65536, 'shader-metadata-bound')
                        require(not source.read(1), 'shader-archive-member-grew')
                finally:
                    if output: output.close()
                require(digest.hexdigest() == pins[name]['sha256'], 'shader-archive-file-identity-mismatch')
                if metadata: values[name] = bytes(metadata)
                seen.append(name); tar.members.clear()
        require(seen == sorted(pins), 'shader-archive-file-set-or-order-mismatch')
        validate_metadata(values, compiler, pin)
    return values


def descriptor(path, pin):
    archive = bundle.identity(path, LIMITS['fileBytes']); required = inventory(pin)
    required = {name: dict(row, **({'elfMachine': 183} if name == COMPILER else {})) for name, row in sorted(required.items())}
    total = sum(row['bytes'] for row in required.values())
    proof = dict(formatVersion=1, scope='android-shader-tools-install-only', packageKey='shader-tools-arm64',
        archive=dict(archive, file='shader-tools-arm64.tar.gz', assetPath=ASSETS + '/' + ARCHIVE),
        archiveEntries=len(required), archiveFileBytes=total, requiredFiles=required, limits=LIMITS,
        freshSetupFreeBytes=archive['bytes'] + total + LIMITS['metadataBytes'] + (64 << 20),
        inputLockSha256=bundle.identity(LOCK)['sha256'], clientRevision=pin['clientRevision'],
        compilerIntegrationRevision=pin['compilerIntegrationRevision'], compilerBuildSha256=pin['compilerBuildSha256'],
        bundleReceiptSha256=pin['bundleReceiptSha256'], toolManifestSha256=pin['toolManifestSha256'],
        helperSourceRevision=pin['helper']['revision'], requiredWineArchiveSha256=pin['requiredWineArchiveSha256'],
        guestMount='/esteria-shader-tools', archiveVerified=True, elfAbiInspected=True,
        nativeCompilerFixtureQualified=True, androidRuntimeQualified=False, gameAssetShadersQualified=False, gameplayQualified=False)
    require(len(encoded(proof)) <= 65536, 'shader-provider-descriptor-bound'); return proof


def build(directory, output):
    pin = load_pin(); files = selected_files(directory, pin)
    output = Path(os.path.abspath(output)); archives.directory(output.parent)
    require(not os.path.lexists(output), 'shader-provider-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.', dir=output.parent))
    try:
        assets = stage / 'assets' / ASSETS; assets.mkdir(parents=True)
        write_archive(assets / ARCHIVE, files, inventory(pin))
        values = verify_archive(assets / ARCHIVE, pin)
        proof = descriptor(assets / ARCHIVE, pin)
        for name, data in {'provider.json': encoded(proof), 'bundle.json': values['provenance/bundle.json'], 'NOTICE.txt': NOTICE}.items():
            bundle.write(assets / name, data)
        verify(stage)
        for path, _, _ in os.walk(stage, topdown=False): bundle.sync_directory(path)
        publish_directory(stage, output); bundle.sync_directory(output.parent); return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def verify(provider, apk=None):
    pin = load_pin(); assets = archives.directory(provider / 'assets' / ASSETS)
    require({p.name for p in assets.iterdir()} == NAMES, 'shader-provider-asset-set-mismatch')
    values = verify_archive(assets / ARCHIVE, pin); proof = descriptor(assets / ARCHIVE, pin)
    require(bundle.small(assets / 'provider.json', 65536) == encoded(proof) and
            bundle.small(assets / 'bundle.json') == values['provenance/bundle.json'] and
            bundle.small(assets / 'NOTICE.txt') == NOTICE, 'shader-provider-metadata-mismatch')
    if apk is not None:
        selected = {'assets/' + ASSETS + '/' + name for name in NAMES}
        with archives.plain_file(apk) as raw, checked_zip(raw, selected, maximum_entries=4096) as archive:
            require({name for name in archive.namelist() if name.startswith('assets/' + ASSETS + '/')} == selected,
                    'shader-apk-asset-set-mismatch')
            for name in NAMES:
                info = archive.getinfo('assets/' + ASSETS + '/' + name); source = assets / name
                require(info.file_size == source.stat().st_size, 'shader-apk-file-size-mismatch')
                if name == ARCHIVE: require(info.compress_type == zipfile.ZIP_STORED, 'shader-apk-archive-must-be-stored')
                with archive.open(info) as stream, archives.plain_file(source) as original:
                    require(archives.hash_stream(stream, info.file_size) == archives.hash_stream(original, info.file_size), 'shader-apk-file-hash-mismatch')
    return dict(providerVerified=True, apkBytesVerified=apk is not None, archive=proof['archive'], androidRuntimeQualified=False,
                gameAssetShadersQualified=False, gameplayQualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build'); create.add_argument('--bundle', type=Path, required=True); create.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify'); check.add_argument('--provider', type=Path, required=True); check.add_argument('--apk', type=Path)
    args = parser.parse_args(); result = build(args.bundle, args.output) if args.command == 'build' else verify(args.provider, args.apk)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
