#!/usr/bin/env python3
"""Build/verify an optional APK asset provider from exact measured server bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

try:
    from . import prepare_runtime as archives, package_server_runtime as runtime
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_server_runtime as runtime
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/android-provider.lock.json'
SOURCE_LOCK = ROOT / 'runtime/server/sources.lock.json'
ASSET_DIR = 'server-runtime'
DESCRIPTOR = 'provider.json'
ASSET_ARCHIVE = 'server-runtime-arm64.archive'
METADATA_LIMIT = 65536
NAMES = {DESCRIPTOR, ASSET_ARCHIVE, 'package-receipt.json', 'server-runtime.json', 'sources.lock.json', 'NOTICE.txt'}
NOTICE = b'''Esteria local server dependency runtime; Android execution is not qualified.
Linux ARM64 Ubuntu 24.04 guest dependencies; separate from the Debian Wine guest.
Includes MySQL8, Python3 and shared libraries, not authserver/worldserver or saves.
Original copyright/license notices are retained in rootfs usr/share/doc.
MySQL is GPL-2.0 with component notices; all dependencies retain their licenses.
Distributions must retain the corresponding-source/recipe companion identified
in provider.json and runtime/server/android-provider.lock.json. Actions artifacts
expire; preserve originals with a release. No game data is included here.
'''
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def verify_file(path, pin):
    with archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size == pin['bytes'] and
                archives.hash_stream(stream, pin['bytes']) == pin['sha256'], 'provider-input-identity-mismatch:' + path.name)


def read_small(path):
    with archives.plain_file(path) as stream:
        data = stream.read(METADATA_LIMIT + 1)
    require(len(data) <= METADATA_LIMIT, 'provider-metadata-size-limit')
    return data


def hardlink_budget(path, limits):
    regular, links, maximum = {}, [], 1
    with archives.plain_file(path) as stream, archives.bounded_tar(stream, limits) as tar:
        for item in tar:
            if item.isfile():
                regular[item.name] = item.size
                maximum = max(maximum, item.size)
            elif item.islnk():
                links.append(archives.link_target(item.name, item.linkname, True, limits['pathBytes']))
            tar.members.clear()
    require(all(target in regular for target in links), 'provider-hardlink-target-missing')
    return len(links), sum(regular[target] for target in links), maximum


def descriptor(package, pin, asset_archive=False):
    """Input receipt is independently hash-pinned; it is never its own authority."""
    for name, key in [('package-receipt.json', 'packageReceipt'), ('server-runtime.json', 'runtimeMetadata'),
                      ('sources.lock.json', 'sourceLock')]:
        verify_file(package / name, pin[key])
    source_bytes = read_small(SOURCE_LOCK)
    require(dict(bytes=len(source_bytes), sha256=hashlib.sha256(source_bytes).hexdigest()) == pin['sourceLock'],
            'provider-source-lock-changed; rebuild-and-review-new-package')
    receipt_bytes = read_small(package / 'package-receipt.json')
    receipt = json.loads(receipt_bytes)
    metadata_bytes = read_small(package / 'server-runtime.json')
    metadata = json.loads(metadata_bytes)
    components = runtime.validate_metadata(metadata_bytes, metadata, source_bytes, json.loads(source_bytes))
    require(receipt.get('scope') == 'packaged-linux-arm64-server-dependencies' and receipt.get('formatVersion') == 1 and
            receipt.get('archiveReadBack') is True and receipt.get('archive') == pin['archive'] and
            receipt.get('archiveEntries') == pin['archiveEntries'] and receipt.get('archiveFileBytes') == pin['archiveFileBytes'] and
            receipt.get('components') == components, 'provider-package-contract-mismatch')
    for key in ('databaseInitialized', 'serverIncluded', 'serverExecuted', 'androidRuntimeQualified', 'gameLoginQualified'):
        require(receipt.get(key) is False, 'provider-scope-mismatch')
    require(receipt['limits'] == runtime.LIMITS, 'unexpected-runtime-package-limits')
    archive = package / (ASSET_ARCHIVE if asset_archive else pin['archive']['file'])
    verify_file(archive, pin['archive'])
    contract = dict(markerPath=runtime.MARKER, marker=metadata, metadataFiles=['usr/lib/os-release'], components=components,
                    archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'], limits=receipt['limits'])
    with archives.plain_file(archive) as stream:
        audit = archives.inspect_archive(stream, contract)
    count, copy_bytes, member = hardlink_budget(archive, receipt['limits'])
    physical = pin['archiveFileBytes'] + copy_bytes
    require(physical <= receipt['limits']['fileBytes'], 'physical-hardlink-copy-reserve-exceeds-limit')
    os_release = audit['metadata']['usr/lib/os-release'].encode()
    components['usr/lib/os-release'] = dict(bytes=len(os_release), sha256=hashlib.sha256(os_release).hexdigest())
    bounds = dict(entries=pin['archiveEntries'], memberBytes=member, fileBytes=max(member, physical),
                  pathBytes=4096, metadataBytes=16 * 1024**2)
    result = dict(formatVersion=1, scope='android-server-runtime-install-only', packageKey='server-arm64',
                  archive=dict(pin['archive'], assetPath=ASSET_DIR + '/' + ASSET_ARCHIVE),
                  archiveEntries=pin['archiveEntries'], archiveFileBytes=pin['archiveFileBytes'], requiredFiles=components,
                  limits=bounds, maximumHardLinkCopies=count, maximumHardLinkCopyBytes=copy_bytes,
                  maximumPhysicalFileBytes=physical,
                  freshSetupFreeBytes=pin['archive']['bytes'] + physical + bounds['metadataBytes'] + 64 * 1024**2,
                  inputLockSha256=hashlib.sha256(read_small(LOCK)).hexdigest(),
                  sourceLockSha256=pin['sourceLock']['sha256'], runtimeMetadataSha256=pin['runtimeMetadata']['sha256'],
                  packageReceiptSha256=pin['packageReceipt']['sha256'], sourceCompanion=pin['sourceCompanion'],
                  archiveVerified=True, elfHeaderMachineValidated=True, completeElfClosureQualified=False,
                  androidRuntimeQualified=False, serverIncluded=False, gameLoginQualified=False)
    require(len(encoded(result)) <= METADATA_LIMIT, 'provider-descriptor-too-large')
    return result


def load_pin():
    pin = json.loads(read_small(LOCK))
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-server-runtime-provider-inputs' and
            pin.get('androidRuntimeQualified') is False and pin['archive']['file'] == 'server-runtime-arm64.tar.gz', 'invalid-provider-pin')
    return pin


def build(package, output):
    pin = load_pin()
    proof = descriptor(package, pin)
    output = Path(os.path.abspath(output));archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'provider-output-exists')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        assets = stage / 'assets' / ASSET_DIR;assets.mkdir(parents=True, mode=0o700)
        for name in NAMES - {DESCRIPTOR, 'NOTICE.txt'}:
            with archives.plain_file(package / (pin['archive']['file'] if name == ASSET_ARCHIVE else name)) as incoming, (assets / name).open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing, archives.BUFFER);outgoing.flush();os.fsync(outgoing.fileno())
        (assets / DESCRIPTOR).write_bytes(encoded(proof));(assets / 'NOTICE.txt').write_bytes(NOTICE)
        verify(stage)
        publish_directory(stage, output)
        archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(provider, apk=None):
    assets = archives.directory(provider / 'assets' / ASSET_DIR)
    require({p.name for p in assets.iterdir()} == NAMES, 'unexpected-server-provider-file')
    expected = descriptor(assets, load_pin(), asset_archive=True)
    require(read_small(assets / DESCRIPTOR) == encoded(expected) and read_small(assets / 'NOTICE.txt') == NOTICE,
            'provider-descriptor-or-notice-mismatch')
    if apk:
        with archives.plain_file(apk) as stream, zipfile.ZipFile(stream) as z:
            names = z.namelist();require(len(names) == len(set(names)), 'duplicate-apk-entry')
            selected = {name for name in names if name.startswith('assets/' + ASSET_DIR + '/')}
            require(selected == {'assets/' + ASSET_DIR + '/' + name for name in NAMES}, 'apk-server-provider-set-mismatch')
            for name in NAMES:
                entry = z.getinfo('assets/' + ASSET_DIR + '/' + name)
                source = assets / name
                require(entry.file_size == source.stat().st_size, 'apk-server-asset-size-mismatch')
                if name == ASSET_ARCHIVE:
                    require(entry.compress_type == zipfile.ZIP_STORED, 'server-archive-must-be-uncompressed-in-apk')
                with z.open(entry) as incoming, archives.plain_file(source) as original:
                    require(archives.hash_stream(incoming, entry.file_size) == archives.hash_stream(original, entry.file_size),
                            'apk-server-asset-hash-mismatch')
    return dict(providerVerified=True, apkBytesVerified=apk is not None, archive=expected['archive'],
                maximumPhysicalFileBytes=expected['maximumPhysicalFileBytes'], androidRuntimeQualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('build');create.add_argument('--package',type=Path,required=True);create.add_argument('--output',type=Path,required=True)
    check=commands.add_parser('verify');check.add_argument('--provider',type=Path,required=True);check.add_argument('--apk',type=Path)
    args=parser.parse_args();result=build(args.package,args.output) if args.command=='build' else verify(args.provider,args.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
