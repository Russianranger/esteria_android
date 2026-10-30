#!/usr/bin/env python3
"""Normalize a fresh source-built ARM64 Wine candidate without selecting it in the app.

The measured output lock is for explicit native qualification with prepare_runtime.
It never changes the existing production runtime or executes guest code.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import tempfile
from urllib.parse import urlsplit

try:
    from . import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, package_server_runtime as packaging, provider_server_runtime as reserve
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / 'runtime/wine-arm64'
LOCK = SOURCE_DIR / 'sources.lock.json'
MARKER = 'etc/esteria-wine-arm64.json'
ARCHIVE = 'wine-arm64.tar.gz'
MANIFEST = 'wine-arm64.manifest.json'
ICD = 'usr/share/vulkan/icd.d/lvp_icd.aarch64.json'
ALSA = 'usr/share/alsa/alsa.conf'
NOTICE_ROOT = 'usr/share/doc/esteria-wine-arm64/'
LIMITS = dict(entries=50000, memberBytes=512 * 1024**2, fileBytes=4 * 1024**3, pathBytes=4096)
RECORDER = runpy.run_path(str(SOURCE_DIR / 'record_runtime.py'))
IMAGES, DATA = RECORDER['IMAGES'], RECORDER['DATA']
INPUTS = ('runtime/wine-probe/android-private-pe-copy.patch', 'runtime/wine-probe/apply_adaptations.py',
          'runtime/wine-probe/capture_sources.py', 'runtime/bridges/debian.sources',
          'runtime/bridges/inrelease.SHA256SUMS', 'tools/owned_process_group.py',
          'tools/package_wine_arm64_candidate.py', 'tools/package_server_runtime.py',
          'tools/provider_server_runtime.py', 'tools/prepare_runtime.py', 'tools/package_server_content.py')
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def identity(path):
    with archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        return dict(bytes=size, sha256=archives.hash_stream(stream, size))


def checked_identity(value, maximum, reason):
    require(type(value) is dict and set(value) == {'bytes', 'sha256'} and
            type(value.get('bytes')) is int and 0 < value['bytes'] <= maximum and
            type(value.get('sha256')) is str and re.fullmatch('[a-f0-9]{64}', value['sha256']), reason)
    return dict(value)


def source_archives(lock):
    result = [lock['wine']['sourceArchive'], lock['fex']['archive'], lock['toolchain']['archive']]
    require(len({item['file'] for item in result}) == 3, 'candidate-source-archive-duplicates')
    for item in result:
        archives.pin_identity(item)
        url = urlsplit(item['url'])
        require(url.scheme == 'https' and url.hostname and not url.username and not url.password and
                not url.fragment and not url.query, 'candidate-source-archive-url')
    return result


def metadata(raw):
    require(0 < len(raw) <= archives.MAX_METADATA, 'candidate-runtime-metadata-limit')
    value = json.loads(raw)
    lock_raw = LOCK.read_bytes(); lock = json.loads(lock_raw)
    require(type(value) is dict and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
            value.get('scope') == 'source-built-native-arm64-wine-candidate' and
            value.get('architecture') == 'arm64', 'candidate-runtime-scope')
    require(lock.get('formatVersion') == 1 and lock.get('architecture') == 'arm64' and
            lock.get('scope') == 'source-owned-native-linux-arm64-wine-candidate-build-inputs' and
            lock.get('runtimeQualified') is False, 'candidate-source-lock-scope')
    source_archives(lock)
    expected = dict(sourceLockSha256=hashlib.sha256(lock_raw).hexdigest(), baseImage=lock['baseImage']['reference'],
                    snapshot=lock['snapshot']['id'], wineRevision=lock['wine']['revision'],
                    wineSourceArchiveSha256=lock['wine']['sourceArchive']['sha256'],
                    fexRevision=lock['fex']['revision'], fexSourceArchiveSha256=lock['fex']['archive']['sha256'],
                    toolchainArchiveSha256=lock['toolchain']['archive']['sha256'],
                    privatePeCopyProfile=lock['wine']['androidPrivatePeCopy'])
    require(all(value.get(key) == item for key, item in expected.items()), 'candidate-runtime-source-selection')
    require(expected['privatePeCopyProfile']['environment'] == {'WINE_ANDROID_PRIVATE_PE_COPY': '1'},
            'candidate-private-image-profile')
    require(type(value.get('wineVersion')) is str and
            re.fullmatch(r'wine-10\.13(?:[ -][^\r\n]{1,80})?', value['wineVersion']), 'candidate-wine-version')
    for flag in ('prefixInitialized', 'clientIncluded', 'androidQualified', 'gameplayQualified'):
        require(value.get(flag) is False, 'candidate-runtime-build-overclaim:' + flag)
    for flag in ('clientExecuted', 'arm64Qualified', 'androidRuntimeQualified', 'graphicsQualified',
                 'audioQualified', 'authenticationQualified', 'commonMainStarted', 'assetsLoaded'):
        require(flag not in value or value[flag] is False, 'candidate-runtime-build-overclaim:' + flag)
    packages = value.get('packages')
    require(type(packages) is list and 0 < len(packages) <= 512, 'candidate-package-inventory')
    fields = ('package', 'version', 'architecture', 'sourcePackage', 'sourceVersion')
    for row in packages:
        require(type(row) is dict and set(row) == set(fields) and
                all(type(row[key]) is str and row[key] and '\t' not in row[key] and '\n' not in row[key] and
                    '\r' not in row[key] for key in fields), 'candidate-package-record')
        require(re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::(?:arm64|all))?', row['package']) and
                re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', row['sourcePackage']) and
                all(re.fullmatch(r'[0-9][0-9A-Za-z.+:~_-]*', row[key]) for key in ('version', 'sourceVersion')),
                'candidate-package-selector')
    parsed = RECORDER['package_inventory']('\n'.join('\t'.join(row[key] for key in fields) for row in packages))
    require(packages == parsed and value.get('sourcePackages') == RECORDER['source_inventory'](packages),
            'candidate-package-source-inventory')
    images = value.get('images', {})
    require(type(images) is dict and set(images) == set(IMAGES), 'candidate-image-inventory')
    components = {}
    for name, (path, allowed) in IMAGES.items():
        row = images[name]
        keys = {'path', 'bytes', 'sha256'} | ({'peMachine'} if allowed is not None else {'elfMachine', 'elfClass'})
        require(type(row) is dict and set(row) == keys and row['path'] == path, 'candidate-image-path-or-fields')
        pin = checked_identity({key: row[key] for key in ('bytes', 'sha256')}, LIMITS['memberBytes'],
                               'candidate-image-identity')
        require(pin['bytes'] >= 64, 'candidate-image-too-small')
        if allowed is not None:
            require(row['peMachine'] in [hex(machine) for machine in allowed], 'candidate-image-pe-architecture')
            pin['peMachine'] = row['peMachine']
        else:
            require(type(row['elfMachine']) is int and row['elfMachine'] == 183 and
                    type(row['elfClass']) is int and row['elfClass'] == 2, 'candidate-image-elf-architecture')
            pin.update(elfMachine=183, elfClass=2)
        components[path[1:]] = pin
    data = value.get('data', {})
    require(type(data) is dict and set(data) == set(DATA), 'candidate-data-inventory')
    for name, row in data.items():
        components[name] = checked_identity(row, 262144, 'candidate-data-identity')
    notices = value.get('notices', {})
    require(type(notices) is dict and 3 <= len(notices) <= 4096, 'candidate-notice-inventory')
    for name, row in notices.items():
        require(type(name) is str and archives.member_path(name) == name and name.startswith(NOTICE_ROOT),
                'candidate-notice-path')
        components[name] = checked_identity(row, 4 * 1024**2, 'candidate-notice-identity')
    require(sum(row['bytes'] for row in notices.values()) <= 32 * 1024**2 and
            any(name.startswith(NOTICE_ROOT + 'fex/') for name in notices) and
            any(name.startswith(NOTICE_ROOT + 'toolchain/') for name in notices), 'candidate-notice-categories')
    require(notices.get(NOTICE_ROOT + 'COPYING.LIB', {}).get('sha256') == lock['wine']['licenseFileSha256'],
            'candidate-wine-license')
    for name, pin in {NOTICE_ROOT + 'fex/LICENSE': lock['licenses']['fex-license'],
                      **{NOTICE_ROOT + 'toolchain/' + name: pin
                         for name, pin in lock['toolchain']['bundledNotices'].items()}}.items():
        require(notices.get(name) == {key: pin[key] for key in ('bytes', 'sha256')}, 'candidate-original-notice')
    icd = value.get('softwareGraphicsIcd')
    require(type(icd) is dict and set(icd) == {'ICD', 'file_format_version'} and
            icd['file_format_version'] == '1.0.0' and type(icd['ICD']) is dict and
            set(icd['ICD']) == {'api_version', 'library_path'} and
            type(icd['ICD']['api_version']) is str and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', icd['ICD']['api_version']) and
            icd['ICD']['library_path'] == images['lavapipe']['path'], 'candidate-lavapipe-icd')
    components[MARKER] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return value, components


def fresh_export(source):
    count = total = 0
    with packaging.docker_tar(source) as archive:
        for member in archive:
            count += 1; total += member.size
            require(count <= LIMITS['entries'] and 0 <= member.size <= LIMITS['memberBytes'] and
                    total <= LIMITS['fileBytes'], 'candidate-input-inventory-limit')
            if member.name not in ('.', './'):
                name = archives.member_path(member.name)
                require(not re.match(r'^(?:root/\.wine|home/[^/]+/\.wine|work|prefix|client|session|'
                                     r'esteria-qualification|private-pe-[A-Za-z0-9_-]+)(?:/|$)', name),
                        'wine-prefix-or-session-state:' + name)
            archive.members.clear()
    source.seek(0)


def source_inputs():
    paths = [*INPUTS, *[str(path.relative_to(ROOT)) for path in sorted(SOURCE_DIR.iterdir()) if path.is_file()]]
    require(len(paths) == len(set(paths)), 'candidate-source-input-duplicates')
    result = {name: identity(ROOT / name) for name in sorted(paths)}
    result['runtime/wine-arm64/sources.lock.json'] = identity(LOCK)
    return result


def build(export, measured, output):
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'candidate-runtime-output-exists')
    with archives.plain_file(measured) as stream:
        raw = stream.read(archives.MAX_METADATA + 1)
    value, components = metadata(raw)
    lock_raw = LOCK.read_bytes(); lock = json.loads(lock_raw)
    require(hashlib.sha256(lock_raw).hexdigest() == value['sourceLockSha256'], 'candidate-source-lock-changed')
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        archive = stage / ARCHIVE
        with archives.plain_file(export) as incoming, archive.open('xb') as outgoing:
            require(os.fstat(incoming.fileno()).st_size <= packaging.MAX_INPUT, 'candidate-export-size-limit')
            fresh_export(incoming)
            counts = packaging.repack(incoming, outgoing)
            outgoing.flush(); os.fsync(outgoing.fileno())
        require(counts['entries'] <= LIMITS['entries'] and counts['fileBytes'] <= LIMITS['fileBytes'],
                'candidate-export-inventory-limit')
        contract = dict(markerPath=MARKER, marker=value, metadataFiles=['usr/lib/os-release', ICD], components=components,
                        archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'], limits=LIMITS)
        with archive.open('rb') as stream:
            audit = archives.inspect_archive(stream, contract)
        require('ID=debian' in audit['metadata']['usr/lib/os-release'] and
                'VERSION_ID="12"' in audit['metadata']['usr/lib/os-release'], 'candidate-runtime-distribution')
        require(json.loads(audit['metadata'][ICD]) == value['softwareGraphicsIcd'], 'candidate-actual-icd-mismatch')
        links, copies, maximum = reserve.hardlink_budget(archive, LIMITS)
        physical = counts['fileBytes'] + copies
        require(physical <= LIMITS['fileBytes'], 'candidate-copy-reserve-limit')
        archive_pin = dict(file=ARCHIVE, **identity(archive))
        manifest_raw = encoded(dict(value, **archive_pin))
        package = dict(status='separate-source-built-native-arm64-candidate', archive=archive_pin,
                       manifest=dict(file=MANIFEST, bytes=len(manifest_raw), sha256=hashlib.sha256(manifest_raw).hexdigest()),
                       markerPath=MARKER, marker=value, metadataFiles=['usr/lib/os-release'], components=components,
                       archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'], limits=LIMITS,
                       sourceArchives=source_archives(lock), wineEnvironment={'WINE_ANDROID_PRIVATE_PE_COPY': '1'})
        def image_component(name):
            return value['images'][name]['path'][1:], components[value['images'][name]['path'][1:]]
        graphics = dict(status='separate-software-reference-only', runtimeArchiveSha256=archive_pin['sha256'],
                        icdPath=ICD, icdLibrary=value['softwareGraphicsIcd']['ICD']['library_path'],
                        icdApiVersion=value['softwareGraphicsIcd']['ICD']['api_version'],
                        expectedAdapterPrefix='Vulkan adapter: llvmpipe',
                        components=dict([image_component(name) for name in ('lavapipe', 'vulkanLoader', 'wineVulkan')] +
                                        [(ICD, components[ICD])]))
        audio = dict(formatVersion=1, runtimeArchiveSha256=archive_pin['sha256'],
                     components=dict([image_component(name) for name in ('asound', 'wineAlsa', 'winealsa.drv')] +
                                     [(ALSA, components[ALSA])]))
        candidate = dict(formatVersion=1, scope='separate-native-arm64-wine-candidate',
                         packages={'wine-arm64': package}, softwareGraphics=graphics, softwareAudio=audio,
                         androidQualified=False, arm64Qualified=False, gameplayQualified=False)
        candidate_raw = encoded(candidate)
        require(len(candidate_raw) <= archives.MAX_METADATA and len(manifest_raw) <= archives.MAX_METADATA,
                'candidate-lock-or-manifest-size-limit')
        inputs = source_inputs()
        require(inputs['runtime/wine-arm64/sources.lock.json']['sha256'] == value['sourceLockSha256'],
                'candidate-source-lock-changed')
        proof = dict(formatVersion=1, scope='packaged-source-built-native-arm64-wine-candidate', archive=archive_pin,
                     sourceLockSha256=value['sourceLockSha256'], runtimeMetadataSha256=hashlib.sha256(raw).hexdigest(),
                     sourceInputs=inputs, candidateLockSha256=hashlib.sha256(candidate_raw).hexdigest(),
                     requiredFiles=components, archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'],
                     maximumHardLinkCopies=links, maximumHardLinkCopyBytes=copies, maximumPhysicalFileBytes=physical,
                     installLimits=dict(entries=counts['entries'], memberBytes=maximum, fileBytes=max(maximum, physical),
                                        pathBytes=4096, metadataBytes=archives.MAX_METADATA),
                     runtimeNoticesVerified=len(value['notices']), archiveReadBack=True, sourceCompanionRequired=True,
                     clientIncluded=False, androidQualified=False, arm64Qualified=False, gameplayQualified=False)
        files = {'runtime.json': raw, 'sources.lock.json': lock_raw, MANIFEST: manifest_raw,
                 'candidate-runtime.lock.json': candidate_raw, 'package-build-receipt.json': encoded(proof)}
        for name, data in files.items():
            (stage / name).write_bytes(data)
        archives.sync_directory(stage); publish_directory(stage, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('docker-export', 'runtime-metadata', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.docker_export, args.runtime_metadata, args.output), indent=2))


if __name__ == '__main__':
    main()
