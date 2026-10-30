#!/usr/bin/env python3
"""Verify the isolated x86_64 MySQL APK provider and exact accompanying PRoot bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
try:
    from . import build_android_mysql_probe as builder, verify_android_proot_probe as proot
    from . import prepare_runtime as archives, provider_server_runtime as reserve
except ImportError:
    import build_android_mysql_probe as builder, verify_android_proot_probe as proot
    import prepare_runtime as archives, provider_server_runtime as reserve

require = archives.require
MAX_APK = 512 * 1024**2


def verify(provider, proot_provider, apk=None):
    proot.verify(proot_provider)
    assets = archives.directory(provider / 'assets' / builder.ASSET)
    require({path.name for path in assets.iterdir()} == builder.NAMES, 'mysql-probe-provider-inventory')
    proof_raw = reserve.read_small(assets / 'provider.json'); proof = json.loads(proof_raw)
    require(proof.get('formatVersion') == 1 and proof.get('scope') == builder.SCOPE and
            proof.get('architecture') == 'x86_64' and proof.get('packageKey') == 'mysql-probe-x86-64', 'mysql-probe-provider-target')
    require(proof.get('archiveReadBack') is True and proof.get('sourceCompanionRequired') is True, 'mysql-probe-build-evidence')
    for key in ('androidMysqlQualified', 'productionAdapterQualified', 'arm64Qualified', 'serverSchemasQualified', 'gameplayQualified'):
        require(proof.get(key) is False, 'mysql-probe-build-overclaim')
    expected_inputs = {name: builder.identity(builder.ROOT / name) for name in builder.INPUTS}
    require(proof.get('sourceInputs') == expected_inputs, 'mysql-probe-source-inputs-changed')
    lock = reserve.read_small(assets / 'sources.lock.json')
    raw = reserve.read_small(assets / 'runtime.json'); value, components = builder.metadata(raw)
    require(lock == builder.LOCK.read_bytes() and proof.get('sourceLockSha256') == hashlib.sha256(lock).hexdigest() and
            proof.get('runtimeMetadataSha256') == hashlib.sha256(raw).hexdigest(), 'mysql-probe-metadata-identity')
    require(reserve.read_small(assets / 'NOTICE.txt') == builder.NOTICE and
            reserve.read_small(assets / 'guest_check.py') == (builder.ROOT / 'runtime/mysql-probe/guest_check.py').read_bytes(), 'mysql-probe-payload-source')
    archive = assets / builder.ARCHIVE; pin = proof['archive']
    require(pin.get('file') == 'mysql-x86-64.tar.gz' and pin.get('assetPath') == 'mysql-probe/' + builder.ARCHIVE and
            type(pin.get('bytes')) is int and 1 <= pin['bytes'] < MAX_APK - 32 * 1024**2 and
            builder.identity(archive) == {key: pin[key] for key in ('bytes', 'sha256')}, 'mysql-probe-archive-identity')
    with archives.plain_file(archive) as source:
        audit = archives.inspect_archive(source, builder.contract(value, components, proof['archiveEntries'], proof['archiveFileBytes']))
    release = audit['metadata']['usr/lib/os-release'].encode()
    require(b'ID=ubuntu' in release and b'VERSION_ID="24.04"' in release, 'mysql-probe-distribution')
    components['usr/lib/os-release'] = dict(bytes=len(release), sha256=hashlib.sha256(release).hexdigest())
    require(proof['requiredFiles'] == components and proof['expectedMysqlSqlVersion'] == value['expectedMysqlSqlVersion'], 'mysql-probe-components')
    links, copies, maximum = reserve.hardlink_budget(archive, builder.LIMITS)
    physical = proof['archiveFileBytes'] + copies
    require(proof['maximumHardLinkCopies'] == links and proof['maximumHardLinkCopyBytes'] == copies and
            proof['maximumPhysicalFileBytes'] == physical and physical <= builder.LIMITS['fileBytes'] and
            proof['limits'] == dict(entries=proof['archiveEntries'], memberBytes=maximum, fileBytes=max(maximum, physical),
                                    pathBytes=4096, metadataBytes=16 * 1024**2), 'mysql-probe-physical-bounds')
    if apk:
        require(0 < apk.stat().st_size <= MAX_APK, 'mysql-probe-apk-size-limit')
        with zipfile.ZipFile(apk) as package:
            names = package.namelist(); require(len(names) <= 10000 and len(names) == len(set(names)), 'mysql-probe-apk-entry-limit')
            expected = {'assets/mysql-probe/' + name: assets / name for name in builder.NAMES}
            for path in proot_provider.rglob('*'):
                if path.is_file():
                    relative = path.relative_to(proot_provider).as_posix()
                    expected[relative.replace('jniLibs/', 'lib/', 1)] = path
            natives = {name for name in names if name.startswith('lib/') and not name.endswith('/')}
            jni = {'lib/x86_64/libesteria_process.so', 'lib/x86_64/libesteria_probe_process.so'}
            require(natives == {'lib/x86_64/' + name for name in proot.builder.NATIVE_PINS} | jni, 'mysql-probe-apk-native-inventory')
            for name in jni:
                require(64 <= package.getinfo(name).file_size <= 16 * 1024**2, 'mysql-probe-owner-size-limit')
                proot.elf(package.read(name), 'owner')
            selected = {name for name in names if name.startswith(('assets/mysql-probe/', 'assets/proot-probe/')) and not name.endswith('/')}
            require(selected == {name for name in expected if name.startswith('assets/')}, 'mysql-probe-apk-asset-inventory')
            for name, source in expected.items():
                item = package.getinfo(name); pin = builder.identity(source)
                require(item.file_size == pin['bytes'], 'mysql-probe-apk-size-mismatch')
                if name == 'assets/mysql-probe/' + builder.ARCHIVE:
                    require(item.compress_type == zipfile.ZIP_STORED, 'mysql-probe-archive-must-be-stored')
                with package.open(item) as stream:
                    require(archives.hash_stream(stream, pin['bytes']) == pin['sha256'], 'mysql-probe-apk-bytes-mismatch')
            # Verify the exact production helper assets rather than embedding a modified probe copy.
            for directory, names in {'database-setup': {'mysql_bootstrap.py', 'android_database_setup.py'},
                                     'database-service': {'mysql_bootstrap.py', 'mysql_service.py'}}.items():
                helper_manifest = package.getinfo('assets/' + directory + '/manifest.json')
                require(helper_manifest.file_size <= 16384, 'mysql-probe-helper-manifest-limit')
                helpers = json.loads(package.read(helper_manifest))
                require(type(helpers) is dict and type(helpers.get('formatVersion')) is int and
                        helpers['formatVersion'] == 1 and type(helpers.get('files')) is dict and
                        set(helpers['files']) == names, 'mysql-probe-helper-set')
                for name, pin in helpers['files'].items():
                    source = builder.ROOT / 'runtime' / name
                    require(type(pin) is dict and type(pin.get('bytes')) is int and
                            pin == builder.identity(source), 'mysql-probe-helper-source-mismatch')
                    entry = package.getinfo('assets/' + directory + '/' + name)
                    require(entry.file_size == pin['bytes'] and entry.file_size <= 131072 and
                            package.read(entry) == source.read_bytes(), 'mysql-probe-helper-apk-mismatch')
    return dict(providerVerified=True, apkVerified=apk is not None, scope=builder.SCOPE,
                archive=proof['archive'], expectedMysqlSqlVersion=proof['expectedMysqlSqlVersion'],
                androidMysqlQualified=False, productionAdapterQualified=False, arm64Qualified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', type=Path, required=True)
    parser.add_argument('--proot-provider', type=Path, required=True)
    parser.add_argument('--apk', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.provider, args.proot_provider, args.apk), indent=2))


if __name__ == '__main__': main()
