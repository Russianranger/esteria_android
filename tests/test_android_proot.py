import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest import mock
import zipfile

from tools import android_elf, build_android_proot as builder, verify_android_proot as verifier
from tools import qualify_proot_ownership as ownership


def elf(loader=False):
    data = bytearray(512 if loader else 1024)
    data[:7] = b'\x7fELF\x02\x01\x01'
    segments = [(1, 5, 0, 0, 0, 512, 512, 16384)]
    if not loader:
        segments += [(1, 6, 512, 0x4200, 0, 512, 512, 16384),
                     (2, 6, 600, 0x4258, 0, 80, 80, 8),
                     (3, 4, 400, 400, 0, 21, 21, 1)]
        data[400:421] = b'/system/bin/linker64\0'
        data[800:817] = b'libc.so\0libdl.so\0'
        for i, pair in enumerate([(1, 0), (1, 8), (5, 0x4320), (10, 17), (0, 0)]):
            struct.pack_into('<qQ', data, 600 + i * 16, *pair)
    segments.append((0x6474e551, 6, 0, 0, 0, 0, 0, 16))
    struct.pack_into('<HHIQQ', data, 16, 2 if loader else 3, 183, 1, 384, 64)
    struct.pack_into('<HHH', data, 52, 64, 56, len(segments))
    for i, segment in enumerate(segments):
        struct.pack_into('<IIQQQQQQ', data, 64 + i * 56, *segment)
    return bytes(data)


class AndroidElf(unittest.TestCase):
    def test_bionic_pie_and_freestanding_loader_have_distinct_contracts(self):
        tracer = android_elf.inspect(elf())
        loader = android_elf.inspect(elf(True), loader=True)
        self.assertEqual(tracer['interpreter'], '/system/bin/linker64')
        self.assertEqual(sorted(tracer['needed']), ['libc.so', 'libdl.so'])
        self.assertEqual(loader['needed'], [])
        self.assertEqual(loader['type'], 'EXEC')
        for data, is_loader in [(elf(), True), (elf(True), False)]:
            with self.assertRaises(ValueError): android_elf.inspect(data, loader=is_loader)

    def test_bad_architecture_stack_entry_bounds_and_alignment_fail(self):
        changes = [(18, '<H', 62), (24, '<Q', 20000), (64 + 4, '<I', 7),
                   (64 + 48, '<Q', 4096), (64 + 32, '<Q', 20000),
                   (64 + 4 * 56 + 4, '<I', 7)]
        for offset, fmt, value in changes:
            data = bytearray(elf()); struct.pack_into(fmt, data, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): android_elf.inspect(data)

    def test_interpreter_dynamic_dependencies_and_search_paths_fail(self):
        wrong_interp = bytearray(elf()); wrong_interp[400:421] = b'/different/linker64\0\0'
        with self.assertRaises(ValueError): android_elf.inspect(wrong_interp)
        for tag, val in [(1, 999), (29, 0), (14, 0), (5, 0xFFFF)]:
            data = bytearray(elf()); struct.pack_into('<qQ', data, 600, tag, val)
            with self.subTest(tag=tag), self.assertRaises(ValueError): android_elf.inspect(data)


class AndroidProot(unittest.TestCase):
    def test_cleanup_accepts_only_the_expected_mapped_fixture_identity(self):
        fixture, loader = Path('/owned/fixture'), Path('/owned/loader')
        maps = '1000-2000 r-xp 00000000 01:01 1 /owned/fixture\n'
        self.assertTrue(ownership.fixture_identity(loader, maps, fixture, loader))
        self.assertTrue(ownership.fixture_identity(fixture, maps, fixture, loader))
        self.assertFalse(ownership.fixture_identity(Path('/unrelated'), maps, fixture, loader))
        self.assertFalse(ownership.fixture_identity(loader, maps.replace('r-xp', 'rw-p'), fixture, loader))
        self.assertFalse(ownership.fixture_identity(loader, maps.replace('/owned/fixture', '/other/fixture'), fixture, loader))
        self.assertFalse(ownership.fixture_identity(loader, maps + ' ' * (128 * 1024), fixture, loader))

    def test_recipe_changes_are_exact_and_cannot_silently_drift(self):
        self.assertEqual(builder.replace_exact('foo foo', 'foo', 'bar', 2), 'bar bar')
        with self.assertRaises(ValueError): builder.replace_exact('foo foo', 'foo', 'bar')
        with self.assertRaises(ValueError): builder.replace_exact('other', 'foo', 'bar')
        for value in ('/root/x', '../x', 'a/../x', 'a\\x', 'x\0'):
            with self.assertRaises(ValueError): builder.safe_name(value)

    def test_source_components_require_exact_members_and_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); archive = root / 'sources.tar.gz'; output = root / 'out'; output.mkdir()
            with tarfile.open(archive, 'w:gz') as tar:
                entry = tarfile.TarInfo('launcher-source/input'); entry.size = 5
                tar.addfile(entry, io.BytesIO(b'hello'))
            with self.assertRaises(ValueError): builder.recover_sources(archive, output, {'input': '0' * 64})
            builder.recover_sources(archive, output, {'input': hashlib.sha256(b'hello').hexdigest()})
            self.assertEqual((output / 'input').read_bytes(), b'hello')
            with self.assertRaises(ValueError): builder.recover_sources(archive, root / 'unused', {'missing': '0' * 64})

    def test_ndk_extraction_rejects_escape_and_duplicate_members(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); path = root / 'ndk.zip'
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/../../../../../../escape', b'bad')
            with self.assertRaises(ValueError): builder.extract_ndk(path, root / 'out')
            with zipfile.ZipFile(path, 'w') as archive:
                entry = zipfile.ZipInfo('android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/bad')
                entry.external_attr = 0o120777 << 16
                archive.writestr(entry, '/etc/passwd')
            with self.assertRaises(ValueError): builder.extract_ndk(path, root / 'out2')

    def test_provider_and_apk_hashes_preserve_exact_pinned_payloads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); native = root / 'provider/jniLibs/arm64-v8a'; native.mkdir(parents=True)
            assets = root / 'provider/assets/proot'; assets.mkdir(parents=True)
            pin = json.loads(builder.LOCK.read_text())
            payloads = {}
            for name in verifier.NAMES:
                data = elf('loader' in name); (native / name).write_bytes(data)
                payloads[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                                      elf=android_elf.inspect(data, loader='loader' in name))
            pin['expectedPayloads'] = {name: {k: item[k] for k in ('bytes', 'sha256')} for name, item in payloads.items()}
            lock = root / 'lock.json'; lock.write_text(json.dumps(pin))
            proof = dict(formatVersion=1, scope='android-arm64-proot-build-only', sourceArchiveSha256=pin['source']['sha256'],
                sourceComponents=pin['components'], ownershipPatchSha256=pin['ownershipPatch']['sha256'],
                ndkArchiveSha256=pin['ndk']['sha256'], ndkVersion=pin['ndk']['version'], sourceLockSha256=builder.digest(lock),
                builderSha256=builder.digest(Path(builder.__file__)), elfValidatorSha256=builder.digest(Path(android_elf.__file__)),
                androidApi=26, buildJobs=1, payloads=payloads, androidBridgeBuilt=True,
                androidBridgeExecuted=False, androidRuntimeQualified=False, gameLoginQualified=False)
            (assets / 'build-evidence.json').write_text(json.dumps(proof))
            for name in verifier.NOTICES: (assets / name).write_text('test notice ' * 20)
            apk = root / 'test.apk'
            with zipfile.ZipFile(apk, 'w') as archive:
                for path in native.iterdir(): archive.write(path, 'lib/arm64-v8a/' + path.name)
                for path in assets.iterdir(): archive.write(path, 'assets/proot/' + path.name)
            with mock.patch.object(builder, 'LOCK', lock):
                self.assertTrue(verifier.verify(root / 'provider', apk)['apkBytesVerified'])
                original = apk.read_bytes()
                with zipfile.ZipFile(apk, 'a') as archive: archive.writestr('lib/arm64-v8a/libunknown.so', elf())
                with self.assertRaisesRegex(ValueError, 'unexpected-apk-native-payload'): verifier.verify(root / 'provider', apk)
                apk.write_bytes(original)
                changed = copy.deepcopy(proof); changed['androidRuntimeQualified'] = True
                with self.assertRaises(ValueError): verifier.validate_proof(changed)
                with (native / 'libproot.so').open('ab') as stream: stream.write(b'changed')
                with self.assertRaises(ValueError): verifier.verify(root / 'provider', apk)


if __name__ == '__main__':
    unittest.main()
