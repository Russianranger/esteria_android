#!/usr/bin/env python3
"""Seal an internal four-provider APK with its verified corresponding sources.

This validates packaging only. It does not execute Android/client/server code,
qualify gameplay, or produce an update-compatible device-test candidate.
"""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import tarfile
import tempfile
import zipfile

try:
    from . import build_android_proot as proot_build, verify_android_proot as proot
    from . import provider_server_runtime as server, provider_guest_bridges as guest, provider_client_runtime as client
    from . import release_server_dependencies as server_release, release_guest_bridges as guest_release, release_client_inputs as client_release
except ImportError:
    import build_android_proot as proot_build, verify_android_proot as proot
    import provider_server_runtime as server, provider_guest_bridges as guest, provider_client_runtime as client
    import release_server_dependencies as server_release, release_guest_bridges as guest_release, release_client_inputs as client_release

ROOT = Path(__file__).resolve().parents[1]
require = client.require
identity = server_release.identity
NATIVE_FILES = {'lib/arm64-v8a/' + name for name in
                ('libproot.so', 'libproot-loader.so', 'libesteria_process.so', 'libesteria-presentation.so')}
NDK_NOTICES = {'NDK-28.2.13676358-NOTICE.txt': 'android-ndk-r28c/NOTICE',
               'LLVM-RUNTIME-NOTICE.txt': 'android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/NOTICE',
               'NDK-SYSROOT-NOTICE.txt': 'android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/sysroot/NOTICE'}
HELPER_SETS = {'database-setup': ('mysql_bootstrap.py', 'android_database_setup.py'),
               'database-service': ('mysql_bootstrap.py', 'mysql_service.py'),
               'server-schema': ('android_server_schema_setup.py', 'mysql_bootstrap.py', 'mysql_service.py',
                                 'server_content.py', 'server_schema_setup.py', 'server_schema_baseline.py',
                                 'server_schema_adaptations.py', 'server/appearance-schema-v1.sql',
                                 'server/appearance-schema.lock.json'),
               'server-installation': ('android_server_installation_setup.py', 'android_server_schema_setup.py',
                    'mysql_bootstrap.py', 'mysql_service.py', 'server_content.py', 'server_schema_setup.py',
                    'server_schema_baseline.py', 'server_schema_adaptations.py', 'server_update_setup.py',
                    'server_updater.py', 'server_playerbots_setup.py', 'owned_process_group.py', 'server_config.py', 'provision_local_realm.py',
                    'provision_local_account.py', 'server/appearance-schema-v1.sql', 'server/appearance-schema.lock.json',
                    'local-server.json'),
               'server-data': ('server_data_generation.py', 'server_data_preflight.py', 'shader_generation.py',
                    'extractor_order.py', 'owned_process_group.py')}


def ndk_notices(path):
    pin = json.loads(client.small(proot_build.LOCK))['ndk']
    require(identity(path) == {key: pin[key] for key in ('bytes', 'sha256')}, 'combined-ndk-archive-pin-mismatch')
    result = {}
    with client.archives.plain_file(path) as incoming, zipfile.ZipFile(incoming) as archive:
        for name, original in NDK_NOTICES.items():
            item = archive.getinfo(original)
            require(0 < item.file_size <= 4*1024**2, 'combined-original-notice-size-limit')
            with archive.open(item) as stream:
                result[name] = dict(bytes=item.file_size, sha256=client.archives.hash_stream(stream, item.file_size))
    return result


def verify_ndk_notices(archive, expected):
    require(set(expected) == set(NDK_NOTICES), 'combined-ndk-notice-inventory-mismatch')
    for name, proof in expected.items():
        item = archive.getinfo('assets/notices/' + name)
        require(item.file_size == proof['bytes'], 'combined-apk-toolchain-notice-size-mismatch')
        with archive.open(item) as stream:
            require(client.archives.hash_stream(stream, item.file_size) == proof['sha256'], 'combined-apk-toolchain-notice-hash-mismatch')


def helper_source_path(directory, name):
    require(directory in HELPER_SETS and name in HELPER_SETS[directory], 'combined-unknown-helper-source')
    return 'config/local-server.json' if (directory, name) == ('server-installation', 'local-server.json') else 'runtime/' + name


def verify_helpers(archive):
    def unique_fields(rows):
        result = {}
        for name, value in rows:
            require(name not in result, 'combined-apk-helper-manifest-mismatch')
            result[name] = value
        return result
    all_names = archive.namelist()
    for directory, names in HELPER_SETS.items():
        prefix = 'assets/' + directory + '/'
        actual = [name for name in all_names if name.startswith(prefix) and not name.endswith('/')]
        expected = {prefix + name for name in (*names, 'manifest.json')}
        require(len(actual) == len(set(actual)) and set(actual) == expected,
                'combined-apk-helper-inventory-mismatch')
        records = {}
        for name in names:
            source = ROOT / helper_source_path(directory, name)
            expected = client.small(source)
            info = archive.getinfo(prefix + name)
            require(info.file_size == len(expected) and archive.read(info) == expected,
                    'combined-apk-helper-source-mismatch')
            records[name] = dict(bytes=len(expected), sha256=hashlib.sha256(expected).hexdigest())
        manifest = archive.getinfo(prefix + 'manifest.json')
        require(manifest.file_size <= 16384, 'combined-apk-helper-manifest-mismatch')
        parsed = json.loads(archive.read(manifest), object_pairs_hook=unique_fields)
        require(type(parsed) is dict and type(parsed.get('formatVersion')) is int and
                type(parsed.get('files')) is dict and
                all(type(pin) is dict and type(pin.get('bytes')) is int for pin in parsed['files'].values()) and
                parsed == dict(formatVersion=1, files=records), 'combined-apk-helper-manifest-mismatch')


def apk_inventory(apk, notices):
    with client.archives.plain_file(apk) as incoming, zipfile.ZipFile(incoming) as archive:
        names = archive.namelist()
        require(len(names) == len(set(names)), 'combined-apk-duplicate-entry')
        native = {name for name in names if name.startswith('lib/') and not name.endswith('/')}
        require(native == NATIVE_FILES, 'combined-apk-native-inventory-mismatch')
        expected_assets = {'assets/proot/' + name for name in proot.NOTICES | {'build-evidence.json'}}
        expected_assets |= {'assets/' + server.ASSET_DIR + '/' + name for name in server.NAMES}
        expected_assets |= {'assets/' + guest.ASSET_DIR + '/' + name for name in guest.NAMES}
        expected_assets |= {client.ASSETS + '/' + name for name in (client.ARCHIVE, 'provider.json', 'NOTICE.txt')}
        expected_assets |= {'assets/' + directory + '/' + name for directory, names in HELPER_SETS.items()
                            for name in (*names, 'manifest.json')}
        expected_assets |= {'assets/' + name for name in ('sources.lock.json', 'runtime-sources.lock.json', 'x11-runtime.lock.json', 'runtime.properties',
            'notices/ESTERIA-GPL-3.0.txt', 'notices/FTA-MIT-LICENSE.txt', 'notices/LLVM-RUNTIME-NOTICE.txt',
            'notices/NDK-28.2.13676358-NOTICE.txt', 'notices/NDK-SYSROOT-NOTICE.txt')}
        require({name for name in names if name.startswith('assets/') and not name.endswith('/')} == expected_assets,
                'combined-apk-asset-inventory-mismatch')
        for target, source in [('assets/sources.lock.json', ROOT / 'sources.lock.json'),
                               ('assets/runtime-sources.lock.json', ROOT / 'runtime/runtime-sources.lock.json'),
                               ('assets/x11-runtime.lock.json', ROOT / 'runtime/bridges/x11-runtime.lock.json'),
                               ('assets/runtime.properties', ROOT / 'app/src/main/assets/runtime.properties')]:
            expected = client.small(source)
            info = archive.getinfo(target)
            require(info.file_size == len(expected) and archive.read(info) == expected,
                    'combined-apk-embedded-source-lock-mismatch')
        verify_helpers(archive)
        verify_ndk_notices(archive, notices)
    return sorted(native)


@contextmanager
def bounded_source_tar(stream, limits):
    """Allow the producer's PAX timestamps with bounded preallocation/readback.

    This source-only reader never extracts files. Runtime importers keep their
    stricter GNU format contract unchanged.
    """
    count = 0; max_pax = 16384
    class Info(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal count
            count += 1
            require(count <= limits['entries']*3, 'source-archive-header-limit')
            require(sum(len(k)+len(v) for k,v in archive.pax_headers.items()) <= max_pax, 'source-global-pax-limit')
            require(self.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.XHDTYPE,
                                  tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME), 'source-archive-type-rejected')
            if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                require(0 < self.size <= max_pax, 'source-pax-size-limit')
            elif self.type == tarfile.GNUTYPE_LONGNAME:
                require(0 < self.size <= limits['pathBytes']+1, 'source-longname-limit')
            return super()._proc_member(archive)

        def _proc_gnusparse_00(self, *args): raise ValueError('source-sparse-encoding-rejected')
        _proc_gnusparse_01 = _proc_gnusparse_00
        _proc_gnusparse_10 = _proc_gnusparse_00

    with gzip.GzipFile(fileobj=stream) as compressed:
        class Reader:
            total = 0
            def read(self, size):
                require(0 <= size <= client.archives.BUFFER, 'source-unbounded-read')
                data = compressed.read(size); self.total += len(data)
                require(self.total <= limits['fileBytes'] + limits['entries']*(max_pax+2048)+10240,
                        'source-expanded-byte-limit')
                return data
        reader = Reader()
        with tarfile.open(fileobj=reader, mode='r|', tarinfo=Info) as archive: yield archive
        while reader.read(client.archives.BUFFER): pass  # Verify gzip CRC/truncation too.


def proot_sources(path, provider):
    """Read back every retained original/recipe/object; never extract the tar."""
    pin = json.loads(client.small(proot_build.LOCK))
    evidence = client.small(provider / 'assets/proot/build-evidence.json')
    expected = {'original/' + name: digest for name, digest in pin['components'].items()}
    files = [ROOT / name for name in ('tools/build_android_proot.py', 'tools/android_elf.py',
                                     'tools/prepare_runtime.py', 'LICENSE')]
    tracked = subprocess.check_output(['git', 'ls-files', 'runtime/proot'], cwd=ROOT, text=True).splitlines()
    files += [ROOT / name for name in tracked]
    for item in files:
        require(not item.is_symlink(), 'proot-recipe-symlink-rejected')
        expected['esteria/' + str(item.relative_to(ROOT))] = identity(item)['sha256']
    expected['build-evidence.json'] = hashlib.sha256(evidence).hexdigest()
    seen = set(); inventory = {}; objects = []; total = 0
    limits = dict(entries=4096, memberBytes=16*1024**2, fileBytes=64*1024**2, pathBytes=1024, metadataBytes=1024**2)
    with client.archives.plain_file(path) as incoming, bounded_source_tar(incoming, limits) as archive:
        for item in archive:
            name = item.name
            require(name not in seen and str(PurePosixPath(name)) == name and not name.startswith('/') and
                    '\\' not in name and all(ord(c) >= 32 for c in name) and
                    all(part not in ('', '.', '..') for part in name.split('/')) and len(name.encode()) <= limits['pathBytes'],
                    'unsafe-or-duplicate-proot-source-path')
            seen.add(name)
            require(len(seen) <= limits['entries'] and not any(key.startswith('GNU.sparse') for key in item.pax_headers),
                    'source-entry-count-or-sparse-metadata')
            if item.isdir():
                require(any(key.startswith(name + '/') for key in expected) or name == 'talloc-build-objects' or
                        name.startswith('talloc-build-objects/'), 'unexpected-proot-source-directory')
                archive.members.clear(); continue
            require(item.isfile() and not item.issparse() and 0 < item.size <= limits['memberBytes'], 'proot-source-type-or-size-rejected')
            total += item.size; require(total <= limits['fileBytes'], 'source-file-byte-limit')
            is_object = name.startswith('talloc-build-objects/') and name.endswith('.o')
            require(name in expected or is_object, 'unexpected-proot-source-file')
            with archive.extractfile(item) as stream:
                header = stream.read(min(item.size, 20)); digest = hashlib.sha256(header)
                count = len(header)
                while block := stream.read(128*1024):
                    count += len(block); require(count <= item.size, 'proot-source-file-overflow'); digest.update(block)
            require(count == item.size, 'proot-source-file-truncated')
            value = digest.hexdigest()
            if is_object:
                require(len(header) >= 20 and header[:6] == b'\x7fELF\x02\x01' and
                        struct.unpack_from('<HH', header, 16) == (1, 183), 'talloc-object-not-arm64-relocatable')
                objects.append(name)
            else: require(value == expected[name], 'proot-source-file-identity-mismatch')
            inventory[name] = dict(bytes=item.size, sha256=value)
            archive.members.clear()
    require(set(expected).issubset(inventory) and any(name.endswith('/talloc.c.5.o') for name in objects),
            'proot-corresponding-source-or-relink-object-missing')
    return dict(archive=identity(path), files=inventory, relinkableArm64Objects=len(objects))


def copy_verified(source, destination, expected):
    with client.archives.plain_file(source) as incoming, destination.open('xb') as outgoing:
        require(os.fstat(incoming.fileno()).st_size == expected['bytes'], 'bundle-input-size-changed')
        require(client.archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
                'bundle-input-hash-changed')
        outgoing.flush(); os.fsync(outgoing.fileno())


def seal(args):
    require(not os.path.lexists(args.output), 'combined-output-exists; existing-artifacts-preserved')
    require(re.fullmatch('[0-9a-f]{40}', args.revision), 'exact-integration-revision-required')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    require(head == args.revision, 'integration-head-mismatch')
    subprocess.run(['git', 'diff', '--exit-code', '--quiet', 'HEAD'], cwd=ROOT, check=True)
    source_lock = json.loads(client.small(ROOT / 'sources.lock.json'))
    server_lock, server_pin = server_release.load_lock()
    guest_lock, guest_pin = guest_release.load_lock()
    client_lock, client_pin = client_release.load_lock()
    for lock in (server_lock, guest_lock, client_lock): require(lock.get('published'), 'durable-dependency-release-required')
    server_release.verify_candidate(args.server_release, server_lock, server_pin)
    server_release.validate_sources(args.server_release / server_release.SOURCE_ZIP, server_lock, server_pin,
                                    server_release.small_json(args.server_release / 'server-runtime.json'))
    guest_release.verify_candidate(args.guest_release, guest_lock, guest_pin)
    client_release.verify_candidate(args.client_release, client_lock, client_pin, args.client_source)
    source_proof = proot_sources(args.proot_sources, args.proot_provider)
    checks = dict(proot=proot.verify(args.proot_provider, args.apk), server=server.verify(args.server_provider, args.apk),
                  guest=guest.verify(args.guest_provider, args.apk),
                  client=client.run(args.client_release / client_release.ARTIFACT, args.client_source, args.client_provider, True, args.apk))
    notices = ndk_notices(args.ndk_archive)
    native = apk_inventory(args.apk, notices)
    client.archives.directory(args.output.parent, create=True)
    with tempfile.TemporaryDirectory(prefix='.combined-bundle-', dir=args.output.parent) as temporary:
        stage = Path(temporary); binary = stage / 'binary'; binary.mkdir(); companion = stage / 'sources'; companion.mkdir()
        copy_verified(args.apk, binary / 'esteria-unqualified-arm64.apk', identity(args.apk))
        entries = [(args.proot_sources, 'proot-corresponding-source.tar.gz'),
                   (args.server_release / server_release.SOURCE_ZIP, server_release.SOURCE_ZIP),
                   (args.server_release / server_release.SOURCE_MANIFEST, server_release.SOURCE_MANIFEST),
                   (args.client_release / client_release.SOURCE_ARCHIVE, client_release.SOURCE_ARCHIVE),
                   (args.client_release / client_release.SOURCE_RECEIPT, 'client-source-receipt.json'),
                   (args.guest_release / guest_release.ARCHIVE, guest_release.ARCHIVE)]
        for source, name in entries: copy_verified(source, companion / name, identity(source))
        for name, lock in [('server', server_lock), ('guest', guest_lock), ('client', client_lock)]:
            (companion / (name + '-release-receipt.json')).write_bytes(shared_encoded(lock['published']))
        integration = companion / 'integration-source.tar.gz'
        subprocess.run(['git', 'archive', '--format=tar.gz', '--output=' + str(integration.resolve()), args.revision], cwd=ROOT, check=True)
        source_inventory = {path.name: identity(path) for path in sorted(companion.iterdir())}
        receipt = dict(formatVersion=1, scope='source-verified-four-provider-arm64-apk-packaging-only',
            integrationRevision=args.revision, sourceLockSha256=identity(ROOT / 'sources.lock.json')['sha256'],
            clientRevision=source_lock['sources']['client']['commit'], serverRevision=source_lock['sources']['server']['commit'],
            apk=identity(binary / 'esteria-unqualified-arm64.apk'), apkNativeFiles=native, providerChecks=checks,
            ndkNotices=notices,
            prootCorrespondingSource=source_proof, correspondingSources=source_inventory,
            buildVariant='debug', persistentSigningQualified=False, wineIncluded=False, authWorldExecutablesIncluded=False,
            gameDataIncluded=False, androidExecutionQualified=False, gameLoginQualified=False,
            gameplayQualified=False, deviceTestCandidate=False)
        for output in (binary, companion):
            (output / 'combined-build.json').write_bytes(shared_encoded(receipt))
        # The two artifacts retain one identical receipt, binding every binary
        # and source companion even when downloaded independently.
        client.publish_directory(stage, args.output); client.archives.sync_directory(args.output.parent)
    return receipt


def shared_encoded(value): return server_release.encoded(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apk', 'proot-provider', 'server-provider', 'guest-provider', 'client-provider', 'proot-sources', 'ndk-archive',
                 'server-release', 'guest-release', 'client-release', 'client-source', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    result = seal(parser.parse_args())
    print(json.dumps({key: result[key] for key in ('scope', 'integrationRevision', 'apk', 'deviceTestCandidate')}, indent=2))


if __name__ == '__main__': main()
