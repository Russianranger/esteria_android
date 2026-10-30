#!/usr/bin/env python3
"""Verify source-pinned Android PRoot provider and optional APK bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

try:
    from . import android_elf, android_jni_elf, build_android_proot as builder, prepare_runtime as packages
except ImportError:
    import android_elf
    import android_jni_elf
    import build_android_proot as builder
    import prepare_runtime as packages


NAMES = {'libproot.so', 'libproot-loader.so'}
NOTICES = {'proot-COPYING.txt', 'talloc-COPYING.txt', 'GNU-GPL-3.txt', 'FTA-MIT-LICENSE.txt', 'NOTICE.txt'}


def validate_proof(proof):
    pin = json.loads(builder.LOCK.read_text())
    packages.require(proof.get('formatVersion') == 1 and proof.get('scope') == 'android-arm64-proot-build-only' and
        proof.get('sourceArchiveSha256') == pin['source']['sha256'] and proof.get('sourceComponents') == pin['components'] and
        proof.get('ownershipPatchSha256') == pin['ownershipPatch']['sha256'] and
        proof.get('ndkArchiveSha256') == pin['ndk']['sha256'] and proof.get('ndkVersion') == pin['ndk']['version'] and
        proof.get('sourceLockSha256') == builder.digest(builder.LOCK) and
        proof.get('builderSha256') == builder.digest(Path(builder.__file__)) and
        proof.get('elfValidatorSha256') == builder.digest(Path(android_elf.__file__)) and
        proof.get('androidApi') == 26 and proof.get('buildJobs') == 1 and
        proof.get('androidBridgeBuilt') is True and proof.get('androidBridgeExecuted') is False and
        proof.get('androidRuntimeQualified') is False and proof.get('gameLoginQualified') is False and
        set(proof.get('payloads', {})) == NAMES and
        {name: {key: item.get(key) for key in ('bytes', 'sha256')}
         for name, item in proof.get('payloads', {}).items()} == pin['expectedPayloads'], 'provider-provenance-mismatch')


def validate_payload(data, name, proof):
    identity = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                    elf=android_elf.inspect(data, loader=name == 'libproot-loader.so'))
    packages.require(identity == proof['payloads'][name], 'provider-payload-identity-mismatch')


def verify(provider, apk=None):
    bridges = {}
    provider = packages.directory(provider)
    native = packages.directory(provider / 'jniLibs/arm64-v8a')
    assets = packages.directory(provider / 'assets/proot')
    packages.require({p.name for p in native.iterdir()} == NAMES and
                     {p.name for p in assets.iterdir()} == NOTICES | {'build-evidence.json'}, 'unexpected-provider-file')
    with packages.plain_file(assets / 'build-evidence.json') as stream:
        raw = stream.read(65537)
    packages.require(len(raw) <= 65536, 'provider-metadata-limit')
    proof = json.loads(raw)
    validate_proof(proof)
    for name in NAMES:
        with packages.plain_file(native / name) as stream:
            data = stream.read(16 * 1024 * 1024 + 1)
        validate_payload(data, name, proof)
    for name in NOTICES:
        with packages.plain_file(assets / name) as stream:
            data = stream.read(128 * 1024 + 1)
        packages.require(100 <= len(data) <= 128 * 1024, 'missing-or-oversized-notice')
    if apk:
        with packages.plain_file(apk) as stream, zipfile.ZipFile(stream) as archive:
            names = archive.namelist()
            packages.require(len(names) == len(set(names)), 'duplicate-apk-entry')
            native_paths = {n for n in names if n.startswith('lib/')}
            expected = {'lib/arm64-v8a/' + n for n in NAMES}
            optional = {'lib/arm64-v8a/' + n for n in android_jni_elf.DEPENDENCIES}
            packages.require(expected <= native_paths <= expected | optional, 'unexpected-apk-native-payload')
            for path in native_paths - expected:
                entry = archive.getinfo(path)
                packages.require(entry.file_size <= 16 * 1024 * 1024, 'apk-jni-size-limit')
                data = archive.read(entry); name = path.rsplit('/', 1)[1]
                bridges[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), elf=android_jni_elf.inspect(data,name))
            if bridges:
                for label, source in [('FTA-MIT-LICENSE.txt',builder.ROOT / 'native/process-owner/FTA-MIT-LICENSE.txt'),
                                      ('ESTERIA-GPL-3.0.txt',builder.ROOT / 'LICENSE')]:
                    entry = archive.getinfo('assets/notices/' + label)
                    packages.require(entry.file_size <= 128 * 1024 and archive.read(entry) == source.read_bytes(), 'apk-native-notice-mismatch')
            for name in NAMES:
                entry = archive.getinfo('lib/arm64-v8a/' + name)
                packages.require(entry.file_size <= 16 * 1024 * 1024, 'apk-elf-size-limit')
                validate_payload(archive.read(entry), name, proof)
            for path in assets.iterdir():
                entry = archive.getinfo('assets/proot/' + path.name)
                packages.require(entry.file_size <= 128 * 1024 and archive.read(entry) == path.read_bytes(),
                                 'apk-provider-metadata-mismatch')
    return dict(androidBridgeBuilt=True, androidBridgeExecuted=False,
                androidRuntimeQualified=False, apkBytesVerified=apk is not None,
                sourceBuiltJniBridges=bridges,
                payloads={name: value['sha256'] for name, value in proof['payloads'].items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', type=Path, required=True)
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.provider, args.apk), sort_keys=True))


if __name__ == '__main__':
    main()
