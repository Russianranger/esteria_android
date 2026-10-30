import copy
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_runtime as runtime


class Response(io.BytesIO):
    def __init__(self, data, length=None, url='https://example.invalid/runtime'):
        super().__init__(data)
        self.headers = {} if length is None else {'Content-Length': str(length)}
        self.url = url
        self.maximum_read = 0

    def geturl(self):
        return self.url

    def read(self, amount=-1):
        if amount < 0 or amount > runtime.BUFFER:
            raise AssertionError('unbounded download read')
        self.maximum_read = max(self.maximum_read, amount)
        return super().read(amount)


def pin(name, data):
    return dict(file=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                url='https://example.invalid/' + name)


def elf(machine=183):
    data = bytearray(64)
    data[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', data, 18, machine)
    return bytes(data)


class RuntimePackages(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.cache = self.work / 'cache'
        self.cache.mkdir()
        self.stage = self.work / 'installed'

    def fixture(self, extra=(), wine=None):
        wine = elf() if wine is None else wine
        marker = dict(format=2, architecture='arm64', runtime='synthetic-only')
        members = [
            ('etc/marker.json', json.dumps(marker).encode()),
            ('etc/packages.txt', b'libc6\t2.36-example\n'),
            ('usr/lib/os-release', b'ID=debian\nVERSION_ID="12"\n'),
            ('opt/wine/bin/wine', wine),
            ('opt/wine/lib/wine/aarch64-windows/msvcp140.dll', b'synthetic-module'),
        ] + list(extra)
        data = io.BytesIO()
        size = 0
        with tarfile.open(fileobj=data, mode='w:gz') as archive:
            for name, content in members:
                item = tarfile.TarInfo(name)
                item.mode = 0o755
                if isinstance(content, bytes):
                    item.size = len(content)
                    size += item.size
                    archive.addfile(item, io.BytesIO(content))
                else:
                    item.type, item.linkname = content
                    archive.addfile(item)
        archive_pin = pin('runtime.tar.gz', data.getvalue())
        (self.cache / archive_pin['file']).write_bytes(data.getvalue())
        manifest = dict(marker, **{k: archive_pin[k] for k in ('file', 'bytes', 'sha256')})
        manifest_bytes = json.dumps(manifest).encode()
        manifest_pin = pin('manifest.json', manifest_bytes)
        (self.cache / manifest_pin['file']).write_bytes(manifest_bytes)
        return dict(archive=archive_pin, manifest=manifest_pin, marker=marker, markerPath='etc/marker.json',
                    metadataFiles=['etc/packages.txt', 'usr/lib/os-release'],
                    archiveEntries=len(members), archiveFileBytes=size,
                    limits=dict(entries=100, memberBytes=4 * 1024**2, fileBytes=8 * 1024**2, pathBytes=4096),
                    components={'opt/wine/bin/wine': dict(bytes=len(wine), sha256=hashlib.sha256(wine).hexdigest(),
                                                          elfMachine=183, elfClass=2)}, sourceArchives=[])

    def test_streaming_download_and_valid_cache_reuse(self):
        data = b'x' * (runtime.BUFFER * 3 + 19)
        expected = pin('data.tar.gz', data)
        response = Response(data, len(data))
        target = runtime.fetch(expected, self.cache, opener=lambda *a, **k: response)
        self.assertEqual(target.read_bytes(), data)
        self.assertLessEqual(response.maximum_read, runtime.BUFFER)
        with patch.object(runtime, 'urlopen', side_effect=AssertionError('network must not run')):
            runtime.fetch(expected, self.cache, opener=runtime.urlopen)

    def test_failed_downloads_leave_no_published_or_partial_file(self):
        expected = pin('data.tar.gz', b'abcdef')
        for response in (Response(b'abc'), Response(b'abcdefg'), Response(b'abcdeg'),
                         Response(b'abcdef', 7), Response(b'abcdef', 6, 'http://example.invalid/data')):
            with self.subTest(response=response):
                with self.assertRaises(ValueError):
                    runtime.fetch(expected, self.cache, opener=lambda *a, **k: response)
                self.assertEqual(list(self.cache.iterdir()), [])

    def test_existing_cache_and_symlinks_are_not_overwritten(self):
        target = self.cache / 'data.tar.gz'
        target.write_bytes(b'previous')
        with self.assertRaises(ValueError):
            runtime.fetch(pin(target.name, b'new'), self.cache)
        self.assertEqual(target.read_bytes(), b'previous')
        target.unlink()
        target.symlink_to(self.work / 'absent')
        with self.assertRaises(OSError):
            runtime.fetch(pin(target.name, b'new'), self.cache)
        self.assertTrue(target.is_symlink())

    def test_audit_and_stage_preserve_contained_links_without_execution(self):
        package = self.fixture([
            ('usr/bin/wine', (tarfile.SYMTYPE, '/opt/wine/bin/wine')),
            ('wine-hardlink', (tarfile.LNKTYPE, 'opt/wine/bin/wine')),
        ])
        report = runtime.prepare(package, self.cache)
        self.assertFalse(report['archiveExtracted'])
        result = runtime.prepare(package, self.cache, self.stage)
        self.assertTrue(result['stagedFilesReadBack'])
        self.assertEqual((self.stage / 'rootfs/usr/bin/wine').read_bytes(), elf())
        self.assertEqual(os.readlink(self.stage / 'rootfs/usr/bin/wine'), '../../opt/wine/bin/wine')
        self.assertEqual((self.stage / 'rootfs/wine-hardlink').stat().st_ino,
                         (self.stage / 'rootfs/opt/wine/bin/wine').stat().st_ino)
        self.assertEqual(json.loads((self.stage / 'package-receipt.json').read_text()), result)
        self.assertFalse(result['androidRuntimeQualified'])
        self.assertFalse(result['wineExecuted'])
        self.assertFalse(result['serverRuntimeIncluded'])
        self.assertIsNone(result['runtimeDependencies']['vcruntime140.dll'])
        self.assertTrue(result['runtimeDependencies']['msvcp140.dll'])

    def test_paths_links_duplicates_and_special_files_fail_closed(self):
        cases = [
            [('../outside', b'x')], [('/absolute', b'x')], [('path\\name', b'x')],
            [('foo', (tarfile.SYMTYPE, '/bar')), ('foo/child', b'x')],
            [('foo/child', b'x'), ('foo', (tarfile.SYMTYPE, '/bar'))],
            [('hard', (tarfile.LNKTYPE, '../../escape'))],
            [('sym', (tarfile.SYMTYPE, '../escape'))],
            [('ambiguous', (tarfile.SYMTYPE, 'maybe-symlink/../target'))],
            [('foo', b'x'), ('foo', b'y')],
            [('fifo', (tarfile.FIFOTYPE, ''))],
            [('hard', (tarfile.LNKTYPE, 'unknown'))],
        ]
        for extra in cases:
            with self.subTest(extra=extra):
                package = self.fixture(extra)
                with self.assertRaises(ValueError):
                    runtime.prepare(package, self.cache, self.stage)
                self.assertFalse(self.stage.exists())
                self.assertEqual(list(self.work.glob('.installed.stage-*')), [])
                self.assertFalse((self.work / 'outside').exists())

    def test_bounded_metadata_and_inventory_fail_before_publication(self):
        package = self.fixture()
        for field, value in [('archiveEntries', 99), ('archiveFileBytes', 1)]:
            invalid = copy.deepcopy(package)
            invalid[field] = value
            with self.assertRaises(ValueError):
                runtime.prepare(invalid, self.cache, self.stage)
            self.assertFalse(self.stage.exists())
        package['limits']['memberBytes'] = 8
        with self.assertRaisesRegex(ValueError, 'member-size-limit'):
            runtime.prepare(package, self.cache, self.stage)

    def test_wrong_component_architecture_fails_even_with_matching_hash(self):
        package = self.fixture(wine=elf(machine=62))
        with self.assertRaisesRegex(ValueError, 'component-elf-mismatch'):
            runtime.prepare(package, self.cache, self.stage)
        self.assertFalse(self.stage.exists())

    def test_oversized_gnu_metadata_is_rejected_before_decoding(self):
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode='w:gz', format=tarfile.GNU_FORMAT) as archive:
            item = tarfile.TarInfo('././@LongLink')
            item.type = tarfile.GNUTYPE_LONGNAME
            item.size = 8192
            archive.addfile(item, io.BytesIO(b'x' * 8192))
        data.seek(0)
        with self.assertRaisesRegex(ValueError, 'extended-header-limit'):
            with runtime.bounded_tar(data, dict(entries=5, fileBytes=1024, pathBytes=4096)) as archive:
                list(archive)

    def test_existing_destination_and_interrupted_staging_preserve_data(self):
        package = self.fixture()
        self.stage.mkdir()
        sentinel = self.stage / 'saved-character'
        sentinel.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'destination-exists'):
            runtime.prepare(package, self.cache, self.stage)
        self.assertEqual(sentinel.read_bytes(), b'keep')
        other = self.work / 'new-install'
        with patch.object(runtime, 'read_member', side_effect=OSError('simulated interrupted read')):
            with self.assertRaises(OSError):
                runtime.prepare(package, self.cache, other)
        self.assertFalse(other.exists())
        self.assertEqual(list(self.work.glob('.new-install.stage-*')), [])
        self.assertEqual(sentinel.read_bytes(), b'keep')

    def test_archive_identity_and_manifest_disagreement(self):
        package = self.fixture()
        archive = self.cache / package['archive']['file']
        data = bytearray(archive.read_bytes())
        data[-1] ^= 1
        archive.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'package-hash-mismatch'):
            runtime.prepare(package, self.cache, self.stage)
        package = self.fixture()
        package['marker']['unexpected'] = True
        with self.assertRaisesRegex(ValueError, 'manifest-mismatch'):
            runtime.prepare(package, self.cache, self.stage)

    def test_source_metadata_and_direct_import_availability_are_only_static_evidence(self):
        package = self.fixture()
        manifest = self.work / 'client-build.json'
        manifest.write_text(json.dumps(dict(schema_version=1, evidence='build-only', architecture='ARM64',
                                           source_revision='a' * 40, files=[dict(imports=[
                                               'MSVCP140.dll', 'VCRUNTIME140_1.dll',
                                               'api-ms-win-crt-runtime-l1-1-0.dll'])])))
        result = runtime.prepare(package, self.cache, imports=manifest)
        self.assertEqual(result['clientImports']['directImportsPresentAsFiles'], ['msvcp140.dll'])
        self.assertEqual(len(result['clientImports']['directImportsWithoutFiles']), 2)
        self.assertIn('libc6', result['metadata']['etc/packages.txt'])
        self.assertFalse(result['gameLoginQualified'])

    def test_checked_in_lock_has_exact_archives_and_separate_server_scope(self):
        lock = json.loads(runtime.DEFAULT_LOCK.read_text())
        package = lock['packages']['wine-arm64']
        for expected in [package['archive'], package['manifest']] + package['sourceArchives']:
            runtime.pin_identity(expected)
            self.assertEqual(expected['url'].split('/')[-1], expected['file'])
        self.assertFalse(lock['server']['sharesWineRootfs'])
        self.assertFalse(package['abi']['directAndroidExec'])
        self.assertEqual(package['components']['opt/wine/lib/wine/aarch64-windows/ntdll.dll']['peMachine'], '0xaa64')


if __name__ == '__main__':
    unittest.main()
