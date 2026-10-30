import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import types
import unittest
import warnings
from unittest.mock import patch
import zipfile

from tools import provider_client_runtime as provider
from tools import package_client_sources as sources


class ClientProviderBounds(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_only_exact_source_advertised_handoff_capability_is_packaged(self):
        self.assertIsNone(provider.capabilities(types.SimpleNamespace()))
        expected = copy.deepcopy(provider.LOCAL_ACCOUNT_CAPABILITIES)
        self.assertEqual(expected, provider.capabilities(types.SimpleNamespace(CAPABILITIES=expected)))
        for key, bad in [('version', True), ('bytes', 57.0), ('flag', '--other'), ('endpoint', 'remote:3724'),
                         ('filename', '../Esteria-local-login.bin'), ('requires', [])]:
            value = copy.deepcopy(expected);value['local_account_handoff'][key] = bad
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'unsupported-client-capabilities'):
                provider.capabilities(types.SimpleNamespace(CAPABILITIES=value))

    def test_runtime_override_preserves_raw_identity_and_rejects_wrong_schema_pins_or_environment(self):
        default_raw, default, wine = provider.runtime_selection()
        self.assertEqual(default_raw, provider.archives.DEFAULT_LOCK.read_bytes())
        self.assertEqual(wine, default['packages']['wine-arm64'])
        value = dict(formatVersion=1, packages={'wine-arm64': dict(
            marker={'architecture': 'arm64'}, archive=dict(file='wine.tar.gz', bytes=32, sha256='a' * 64,
                url='https://example.com/wine.tar.gz'), manifest=dict(file='wine.json', bytes=16, sha256='b' * 64,
                url='https://example.com/wine.json'), wineEnvironment={'WINE_ANDROID_PRIVATE_PE_COPY': '1'})})
        path = self.root / 'runtime.json'; path.write_text('\n' + json.dumps(value))
        raw, lock, selected = provider.runtime_selection(path)
        self.assertEqual(raw, path.read_bytes()); self.assertEqual(lock, value)
        self.assertEqual(selected, value['packages']['wine-arm64'])
        changes = [lambda v: v.update(formatVersion=True), lambda v: v.update(packages=[]),
            lambda v: v['packages']['wine-arm64']['marker'].update(architecture='x64'),
            lambda v: v['packages']['wine-arm64']['archive'].update(bytes=True),
            lambda v: v['packages']['wine-arm64']['archive'].update(file='../wine.tar.gz'),
            lambda v: v['packages']['wine-arm64']['archive'].update(sha256=0),
            lambda v: v['packages']['wine-arm64']['manifest'].update(bytes=provider.META_LIMIT + 1),
            lambda v: v['packages']['wine-arm64']['manifest'].update(sha256='bad'),
            lambda v: v['packages']['wine-arm64']['manifest'].update(file='wine.tar.gz', url='https://example.com/wine.tar.gz'),
            lambda v: v['packages']['wine-arm64']['archive'].update(url='http://example.com/wine.tar.gz'),
            lambda v: v['packages']['wine-arm64']['archive'].update(url='https://user:private@example.com/wine.tar.gz'),
            lambda v: v['packages']['wine-arm64']['archive'].update(url='https://example.com/wine.tar.gz?token=private'),
            lambda v: v['packages']['wine-arm64']['archive'].update(url='https://example.com/other'),
            lambda v: v['packages']['wine-arm64'].update(wineEnvironment={'WINE_ANDROID_PRIVATE_PE_COPY': 1}),
            lambda v: v['packages']['wine-arm64'].update(wineEnvironment={'LD_PRELOAD': '/unmeasured.so'})]
        for change in changes:
            altered = copy.deepcopy(value); change(altered); path.write_text(json.dumps(altered))
            with self.subTest(change=change), self.assertRaises(ValueError): provider.runtime_selection(path)
        # URL-free measured candidate locks are usable; an override is not a download.
        for item in value['packages']['wine-arm64'].values():
            if type(item) is dict: item.pop('url', None)
        for environment in ({}, {'WINE_ANDROID_PRIVATE_PE_COPY': '1'}):
            value['packages']['wine-arm64']['wineEnvironment'] = environment
            path.write_text(json.dumps(value)); self.assertEqual(provider.runtime_selection(path)[1], value)

    def test_provider_cli_passes_optional_runtime_without_changing_omitted_selection(self):
        args = ['provider_client_runtime.py', 'build', '--artifact', '/client.zip', '--client-source', '/source',
                '--provider', '/provider']
        with patch.object(sys, 'argv', args), patch.object(provider, 'run', return_value={}) as run, redirect_stdout(io.StringIO()):
            provider.main(); self.assertIsNone(run.call_args.args[-1])
        with patch.object(sys, 'argv', args + ['--runtime-lock', '/runtime.json']), \
             patch.object(provider, 'run', return_value={}) as run, redirect_stdout(io.StringIO()):
            provider.main(); self.assertEqual(run.call_args.args[-1], Path('/runtime.json'))

    def archive(self, extra=None):
        path = self.root / 'fixture.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in provider.SELECTED:archive.writestr(name, b'fixture')
            if extra is not None:archive.writestr(extra, b'extra')
        return path

    def test_directory_is_bounded_before_zip_member_allocation(self):
        path = self.archive()
        data = bytearray(path.read_bytes());at = data.rfind(b'PK\x05\x06')
        struct.pack_into('<I', data, at + 12, provider.META_LIMIT + 1);path.write_bytes(data)
        with path.open('rb') as stream, patch.object(provider.zipfile, 'ZipFile', side_effect=AssertionError('must reject first')):
            with self.assertRaisesRegex(ValueError, 'directory-limit'):provider.checked_zip(stream)

    def test_links_traversal_and_duplicate_names_are_rejected(self):
        link = zipfile.ZipInfo('linked');link.external_attr = (stat.S_IFLNK | 0o777) << 16
        for extra in ('../outside', '/absolute', 'bin\\bad', link):
            with self.subTest(extra=extra):
                with self.archive(extra).open('rb') as stream:
                    with self.assertRaises(ValueError):provider.checked_zip(stream)
        with self.archive().open('rb') as stream, provider.checked_zip(stream) as archive:
            self.assertEqual(set(archive.namelist()), set(provider.SELECTED))
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            path = self.archive(next(iter(provider.SELECTED)))
        with path.open('rb') as stream:
            with self.assertRaisesRegex(ValueError, 'duplicate-path'):provider.checked_zip(stream)

    def test_large_compressed_selected_member_rejected_before_open(self):
        with self.archive().open('rb') as stream, provider.checked_zip(stream) as archive:
            archive.getinfo('bin/Win/ARM64/WowClient64.exe').file_size = 64 * 1024**2 + 1
            with patch.object(archive, 'open', side_effect=AssertionError('must reject before decompression')):
                with self.assertRaisesRegex(ValueError, 'member-size-limit'):provider.copy_selected(archive, self.root / 'tree')

    def test_delay_imports_require_an_explicit_future_parser(self):
        data = bytearray(512);struct.pack_into('<I', data, 60, 64);struct.pack_into('<I', data, 64 + 24 + 108, 16)
        path = self.root / 'image';path.write_bytes(data);provider.no_delay_imports(path)
        struct.pack_into('<II', data, 64 + 24 + 112 + 13 * 8, 4096, 32);path.write_bytes(data)
        with self.assertRaisesRegex(ValueError, 'delay-imports-not-supported'):provider.no_delay_imports(path)

    def test_verification_size_checked_before_hashing(self):
        path = self.root / 'growing';path.write_bytes(b'longer-than-pin')
        with patch.object(provider.archives, 'hash_stream', side_effect=AssertionError('must reject size first')):
            with self.assertRaisesRegex(ValueError, 'size-mismatch'):provider.verify_identity(path, dict(bytes=1, sha256='0'*64))

    def test_apk_checks_exact_assets_bytes_and_uncompressed_runtime_archive(self):
        assets = self.root / 'assets';assets.mkdir()
        for name in (provider.ARCHIVE, 'provider.json', 'NOTICE.txt'):(assets / name).write_bytes(b'fixture-' + name.encode())
        for case in ('good', 'compressed', 'extra', 'changed'):
            apk = self.root / (case + '.apk')
            with zipfile.ZipFile(apk, 'w') as archive:
                archive.writestr('AndroidManifest.xml', b'fixture')
                for path in assets.iterdir():
                    data = path.read_bytes()
                    if case == 'changed' and path.name == 'NOTICE.txt':data = b'x' * len(data)
                    archive.writestr(provider.ASSETS + '/' + path.name, data,
                        compress_type=zipfile.ZIP_DEFLATED if case == 'compressed' else zipfile.ZIP_STORED)
                if case == 'extra':archive.writestr(provider.ASSETS + '/unexpected', b'x')
            if case == 'good':provider.verify_apk(apk, assets)
            else:
                with self.subTest(case=case), self.assertRaises(ValueError):provider.verify_apk(apk, assets)


@unittest.skipUnless(os.environ.get('ESTERIA_CLIENT_ARTIFACT') and os.environ.get('ESTERIA_CLIENT_SOURCE'),
                     'requires exact measured client artifact and pinned source checkout')
class MeasuredClientProvider(unittest.TestCase):
    def test_actual_binary_package_reproduces_preserves_output_and_rejects_tampering(self):
        artifact = Path(os.environ['ESTERIA_CLIENT_ARTIFACT']);source = Path(os.environ['ESTERIA_CLIENT_SOURCE'])
        with tempfile.TemporaryDirectory() as raw:
            output = Path(raw) / 'provider'
            proof = provider.run(artifact, source, output)
            self.assertEqual(proof, provider.run(artifact, source, output, verify=True))
            files = proof['requiredFiles']
            self.assertEqual([name for name in files if name.startswith('bin/')], ['bin/WowClient64.exe', 'bin/XvidDecoder.dll'])
            self.assertFalse(any(name.lower().endswith('.pdb') or 'test_' in name for name in files))
            for name in ('bin/WowClient64.exe', 'bin/XvidDecoder.dll'):self.assertEqual(files[name]['peMachine'], '0xaa64')
            self.assertIn('notices/ThirdParty/freetype/docs/FTL.txt', files)
            self.assertFalse(proof['androidRuntimeQualified']);self.assertFalse(proof['gameInitializationQualified'])
            package = output / provider.ASSETS / provider.ARCHIVE
            original = provider.identity(package)
            with self.assertRaisesRegex(ValueError, 'output-exists'):provider.run(artifact, source, output)
            self.assertEqual(original, provider.identity(package))
            with package.open('r+b') as stream:stream.seek(100);stream.write(b'changed')
            with self.assertRaisesRegex(ValueError, 'hash-mismatch'):provider.run(artifact, source, output, verify=True)
            wrong = copy.deepcopy(json.loads(provider.small(provider.PIN)));wrong['artifact']['sha256'] = '0'*64
            tree = Path(raw) / 'wrong';tree.mkdir()
            with self.assertRaisesRegex(ValueError, 'artifact-identity-mismatch'):
                provider.prepare(artifact, source, tree, wrong, provider.small(provider.SOURCE_LOCK))

    @unittest.skipUnless(os.environ.get('ESTERIA_XVID_SOURCE'), 'requires unchanged pinned upstream Xvid archive')
    def test_source_companion_preserves_complete_client_and_exact_upstream_inputs(self):
        source = Path(os.environ['ESTERIA_CLIENT_SOURCE']);xvid = Path(os.environ['ESTERIA_XVID_SOURCE'])
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw);wrong = root / 'wrong.tar.gz';wrong.write_bytes(b'not pinned upstream source')
            with self.assertRaisesRegex(ValueError, 'xvid-source-hash-mismatch'):sources.build(source, wrong, root / 'bad')
            self.assertFalse((root / 'bad').exists())
            first = sources.build(source, xvid, root / 'first')
            second = sources.build(source, xvid, root / 'second')
            self.assertEqual(first, second)
            self.assertGreater(first['members']['client-source.tar']['bytes'], 100 * 1024**2)
            self.assertEqual(first['xvid']['sha256'], 'abbdcbd39555691dd1c9b4d08f0a031376a3b211652c0d8b3b8aa9be1303ce2d')
            self.assertTrue(first['archiveReadBack']);self.assertFalse(first['androidRuntimeQualified'])
            with self.assertRaisesRegex(ValueError, 'output-exists'):sources.build(source, xvid, root / 'first')


if __name__ == '__main__':unittest.main()
