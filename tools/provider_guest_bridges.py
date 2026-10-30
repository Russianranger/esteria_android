#!/usr/bin/env python3
"""Build an optional, exact-source guest bridge APK provider; never execute helpers."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import zipfile

try:
    from . import prepare_runtime as archives
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives
    from package_server_content import publish_directory
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from runtime.bridges.record_build import elf

LOCK = ROOT / 'runtime/bridges/android-provider.lock.json'
SHARE = 'share/esteria-bridges/'
ASSET_DIR = 'guest-bridges'
ASSET_ARCHIVE = 'guest-bridges-arm64.archive'
ARCHIVE_NAME = 'guest-bridges-arm64.tar.gz'
RECEIPT = SHARE + 'bridge-build.json'
SOURCE_LOCK = SHARE + 'corresponding-source/build-recipe/sources.lock.json'
BINARY_PATHS = {'esteria-x11-frame': 'bin/esteria-x11-frame', 'esteria-x11-input': 'bin/esteria-x11-input',
                'libasound_module_pcm_esteria.so': 'lib/alsa-lib/libasound_module_pcm_esteria.so'}
LIMITS = dict(entries=128, memberBytes=1024**2, fileBytes=2*1024**2, pathBytes=512, metadataBytes=128*1024)
NAMES = {'provider.json', ASSET_ARCHIVE, 'bridge-build.json', 'NOTICE.txt'}
ALSA_CONFIG = b'''# Per-session ALSA_CONFIG_PATH; this file does not change the Wine rootfs.
</usr/share/alsa/alsa.conf>
pcm_type.esteria { lib "/esteria-bridges/lib/alsa-lib/libasound_module_pcm_esteria.so" }
pcm.esteria { type esteria }
pcm.!default { type plug slave { pcm "esteria" format S16_LE rate 48000 channels 2 } }
'''
NOTICE = b'''Esteria ARM64 glibc guest display/input/audio helpers. Installation only.
The X11 helpers retain GPL-3.0 and the adapted PCM plugin its MIT notice.
libXtst is statically linked; its complete original source and Debian changes
are included with its copyright notice. Project sources and build recipes are
included. The source manifest and pinned build lock identify all direct build
inputs; the complete build-source companion remains the pinned CI artifact.
No Wine files, game content, saved state, or Android executables are replaced.
This package does not qualify Android execution, game rendering/input/audio,
or the source closure of the separately distributed Wine rootfs.
'''
GENERATED = {'etc/alsa-esteria.conf': ALSA_CONFIG, SHARE + 'NOTICE.txt': NOTICE}
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def read_small(path, limit=65536):
    with archives.plain_file(path) as stream: data = stream.read(limit + 1)
    require(len(data) <= limit, 'bridge-metadata-size-limit')
    return data


def safe_path(name):
    require(isinstance(name, str) and len(name.encode()) <= LIMITS['pathBytes'] and
            str(PurePosixPath(name)) == name and not name.startswith('/') and
            all(part not in ('', '.', '..') for part in name.split('/')) and
            '\\' not in name and all(ord(c) >= 32 for c in name), 'invalid-bridge-package-path')
    return name


def load_pin():
    pin = json.loads(read_small(LOCK))
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-guest-bridge-provider-inputs' and
            pin.get('androidRuntimeQualified') is False and 0 < len(pin['files']) <= 120, 'invalid-bridge-provider-pin')
    total = 0
    for name, row in pin['files'].items():
        safe_path(name);safe_path(row['zipEntry']);safe_path(row['payloadPath'])
        require(type(row['bytes']) is int and 0 <= row['bytes'] <= LIMITS['memberBytes'], 'bridge-file-size-limit')
        require(isinstance(row['sha256'], str) and len(row['sha256']) == 64 and
                all(c in '0123456789abcdef' for c in row['sha256']), 'invalid-bridge-file-hash')
        total += row['bytes']
    require(total <= LIMITS['fileBytes'] and not (pin['files'].keys() & GENERATED.keys()), 'bridge-package-size-or-name-limit')
    for rel, row in pin['repositoryInputs'].items():
        safe_path(rel)
        require(identity(read_small(ROOT / rel, LIMITS['memberBytes'])) == {k:row[k] for k in ('bytes', 'sha256')},
                'bridge-source-input-changed:' + rel)
        require(pin['files'][row['installedPath']]['sha256'] == row['sha256'], 'bridge-source-pin-disagreement')
    return pin


def validate_payload(payload, pin):
    require(set(payload) == set(pin['files']) | GENERATED.keys(), 'bridge-payload-file-set-mismatch')
    for path, row in pin['files'].items():
        require(identity(payload[path]) == {key:row[key] for key in ('bytes', 'sha256')}, 'bridge-file-identity-mismatch:' + path)
    require(all(payload[name] == data for name, data in GENERATED.items()), 'bridge-generated-file-mismatch')
    receipt = json.loads(payload[RECEIPT]); lock = json.loads(payload[SOURCE_LOCK])
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'linux-arm64-guest-bridge-build-only' and
            receipt.get('integrationRevision') == pin['integrationRevision'] and receipt.get('compiled') is True and
            receipt.get('inputLockSha256') == identity(payload[SOURCE_LOCK])['sha256'] and
            receipt.get('runtimeArchiveSha256') == lock['runtimeArchiveSha256'], 'bridge-build-receipt-mismatch')
    for flag in ('guestExecutionQualified', 'androidQualified', 'gameAudioQualified', 'presentationQualified', 'inputQualified'):
        require(receipt.get(flag) is False, 'bridge-build-scope-mismatch')
    require(receipt.get('selectedPackages') == {row['package']:row['version'] for row in lock['packages']}, 'bridge-build-package-mismatch')
    require(set(receipt['binaries']) == set(BINARY_PATHS), 'bridge-binary-set-mismatch')
    with tempfile.TemporaryDirectory(prefix='esteria-bridge-elf-') as temp:
        for name, path in BINARY_PATHS.items():
            file = Path(temp) / name;file.write_bytes(payload[path])
            require(elf(file) == receipt['binaries'][name], 'bridge-elf-receipt-mismatch:' + name)
    for name, row in receipt['sources'].items():
        installed = SHARE + 'corresponding-source/' + safe_path(name)
        require(installed in payload and identity(payload[installed]) == row and
                pin['repositoryInputs']['native/' + name]['installedPath'] == installed, 'bridge-project-source-mismatch')
    manifest = json.loads(payload[SHARE + 'corresponding-source/original-archives/SOURCE-MANIFEST.json'])
    expected = [dict(package=s['package'], version=s['version'], file=a['file'], bytes=a['bytes'], sha256=a['sha256'])
                for s in lock['sources'] for a in s['archives']]
    require(manifest.get('formatVersion') == 1 and manifest.get('scope') == 'original-archives-for-locked-direct-build-and-static-link-inputs' and
            manifest.get('completeGuestRootfsSourceClosure') is False and manifest.get('files') == expected, 'bridge-source-manifest-mismatch')
    xtst = [s for s in lock['sources'] if s['package'] == 'libxtst']
    require(len(xtst) == 1 and len(xtst[0]['archives']) == 3, 'bridge-static-source-set-mismatch')
    for row in xtst[0]['archives']:
        path = SHARE + 'corresponding-source/original-archives/' + safe_path(row['file'])
        require(path in payload and identity(payload[path]) == {k:row[k] for k in ('bytes', 'sha256')}, 'bridge-static-source-missing')
    return receipt


def read_artifact(path, pin):
    with archives.plain_file(path) as stream:
        require(os.fstat(stream.fileno()).st_size == pin['artifact']['bytes'] and
                archives.hash_stream(stream, pin['artifact']['bytes']) == pin['artifact']['sha256'], 'bridge-artifact-identity-mismatch')
        stream.seek(0)
        with zipfile.ZipFile(stream) as z:
            require(len(z.namelist()) == len(set(z.namelist())), 'duplicate-bridge-artifact-entry')
            payload = {}
            for path, row in pin['files'].items():
                info = z.getinfo(row['zipEntry'])
                require(info.file_size == row['bytes'], 'bridge-artifact-file-size-mismatch')
                with z.open(info) as file:
                    data = file.read(row['bytes'] + 1)
                require(len(data) == row['bytes'], 'bridge-artifact-file-size-mismatch')
                payload[path] = data
    payload.update(GENERATED)
    validate_payload(payload, pin)
    return payload


def read_payload(directory, pin):
    """Accept an exact rebuilt Docker export too; CI ZIP retention is not a dependency."""
    directory=archives.directory(directory)
    payload={name:read_small(directory/row['payloadPath'],row['bytes']) for name,row in pin['files'].items()}
    payload.update(GENERATED);validate_payload(payload,pin)
    return payload


def write_archive(path, payload):
    with path.open('xb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as tar:
                for name, data in sorted(payload.items()):
                    entry = tarfile.TarInfo(name);entry.size=len(data);entry.mode=0o755 if name in BINARY_PATHS.values() else 0o644
                    entry.uid=entry.gid=entry.mtime=0
                    tar.addfile(entry, io.BytesIO(data))
        raw.flush();os.fsync(raw.fileno())


def read_archive(path):
    payload = {};total = 0
    with archives.plain_file(path) as raw, archives.bounded_tar(raw, LIMITS) as tar:
        for entry in tar:
            name = safe_path(entry.name)
            require(entry.isfile() and name not in payload and entry.size <= LIMITS['memberBytes'] and len(payload) < LIMITS['entries'],
                    'bridge-archive-entry-rejected')
            total += entry.size;require(total <= LIMITS['fileBytes'], 'bridge-archive-file-limit')
            require(entry.mode == (0o755 if name in BINARY_PATHS.values() else 0o644) and entry.uid == entry.gid == entry.mtime == 0,
                    'bridge-archive-mode-mismatch')
            with tar.extractfile(entry) as incoming: data=incoming.read(entry.size + 1)
            require(len(data) == entry.size, 'bridge-archive-file-size-mismatch')
            payload[name]=data;tar.members.clear()
    return payload


def descriptor(archive, payload, pin):
    receipt = validate_payload(payload, pin)
    with archives.plain_file(archive) as stream:
        size=os.fstat(stream.fileno()).st_size
        require(0 < size <= LIMITS['fileBytes'], 'bridge-archive-size-limit')
        archive_pin=dict(file=ARCHIVE_NAME, bytes=size, sha256=archives.hash_stream(stream, size), assetPath=ASSET_DIR+'/'+ASSET_ARCHIVE)
    required={name:dict(identity(data), **({'elfMachine':183} if name in BINARY_PATHS.values() else {})) for name,data in sorted(payload.items())}
    total=sum(row['bytes'] for row in required.values())
    result=dict(formatVersion=1, scope='android-guest-bridge-install-only', packageKey='guest-bridges-arm64',
                archive=archive_pin, archiveEntries=len(payload), archiveFileBytes=total, requiredFiles=required, limits=LIMITS,
                freshSetupFreeBytes=size+total+LIMITS['metadataBytes']+(64<<20), inputLockSha256=identity(read_small(LOCK))['sha256'],
                bridgeBuildSha256=identity(payload[RECEIPT])['sha256'], sourceArtifact=pin['artifact'],
                integrationRevision=pin['integrationRevision'], requiredWineArchiveSha256=receipt['runtimeArchiveSha256'],
                guestMount='/esteria-bridges', alsaConfigPath='/esteria-bridges/etc/alsa-esteria.conf',
                helpers={name:'/esteria-bridges/'+path for name,path in BINARY_PATHS.items()},
                archiveVerified=True, elfAbiInspected=True, androidRuntimeQualified=False, gameAudioQualified=False,
                gameInputQualified=False, gamePresentationQualified=False)
    require(len(encoded(result)) <= 65536, 'bridge-descriptor-size-limit')
    return result


def build(artifact, output, payload_dir=None):
    pin=load_pin()
    require((artifact is None) != (payload_dir is None), 'choose-bridge-artifact-or-rebuilt-payload')
    payload=read_payload(payload_dir,pin) if payload_dir is not None else read_artifact(artifact,pin)
    output=Path(os.path.abspath(output));archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'bridge-provider-output-exists')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        assets=stage/'assets'/ASSET_DIR;assets.mkdir(parents=True,mode=0o700)
        write_archive(assets/ASSET_ARCHIVE,payload)
        proof=descriptor(assets/ASSET_ARCHIVE,read_archive(assets/ASSET_ARCHIVE),pin)
        (assets/'provider.json').write_bytes(encoded(proof));(assets/'bridge-build.json').write_bytes(payload[RECEIPT]);(assets/'NOTICE.txt').write_bytes(NOTICE)
        verify(stage);publish_directory(stage,output);archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def verify(provider, apk=None):
    pin=load_pin();assets=archives.directory(provider/'assets'/ASSET_DIR)
    require({p.name for p in assets.iterdir()} == NAMES,'bridge-provider-file-set-mismatch')
    payload=read_archive(assets/ASSET_ARCHIVE);expected=descriptor(assets/ASSET_ARCHIVE,payload,pin)
    require(read_small(assets/'provider.json') == encoded(expected) and read_small(assets/'NOTICE.txt') == NOTICE and
            read_small(assets/'bridge-build.json') == payload[RECEIPT], 'bridge-provider-metadata-mismatch')
    if apk:
        with archives.plain_file(apk) as stream, zipfile.ZipFile(stream) as z:
            names=z.namelist();require(len(names)==len(set(names)),'duplicate-apk-entry')
            require({n for n in names if n.startswith('assets/'+ASSET_DIR+'/')} == {'assets/'+ASSET_DIR+'/'+n for n in NAMES}, 'apk-bridge-file-set-mismatch')
            for name in NAMES:
                entry=z.getinfo('assets/'+ASSET_DIR+'/'+name);path=assets/name
                require(entry.file_size==path.stat().st_size,'apk-bridge-file-size-mismatch')
                if name==ASSET_ARCHIVE:require(entry.compress_type==zipfile.ZIP_STORED,'bridge-archive-must-be-uncompressed-in-apk')
                with z.open(entry) as incoming, archives.plain_file(path) as original:
                    require(archives.hash_stream(incoming,entry.file_size)==archives.hash_stream(original,entry.file_size),'apk-bridge-file-hash-mismatch')
    return dict(providerVerified=True,apkBytesVerified=apk is not None,archive=expected['archive'],archiveFileBytes=expected['archiveFileBytes'],androidRuntimeQualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='command',required=True)
    create=commands.add_parser('build');inputs=create.add_mutually_exclusive_group(required=True);inputs.add_argument('--artifact',type=Path);inputs.add_argument('--payload',type=Path);create.add_argument('--output',type=Path,required=True)
    check=commands.add_parser('verify');check.add_argument('--provider',type=Path,required=True);check.add_argument('--apk',type=Path)
    args=parser.parse_args();result=build(args.artifact,args.output,args.payload) if args.command=='build' else verify(args.provider,args.apk)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
