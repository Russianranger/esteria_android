import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import package_combined_android as bundle


class CombinedPackageGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_existing_output_preserves_everything_before_validation(self):
        output = self.root / 'existing'; output.mkdir(); marker = output / 'save'; marker.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'existing-artifacts-preserved'):
            bundle.seal(SimpleNamespace(output=output))
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_final_apk_requires_exact_arm64_native_set(self):
        path = self.root / 'test-only-not-an-apk.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in bundle.NATIVE_FILES | {'lib/x86_64/debug-test.so'}: archive.writestr(name, b'unexecuted fixture')
        with self.assertRaisesRegex(ValueError, 'native-inventory'):
            bundle.apk_inventory(path, {})

    def test_verified_copy_never_replaces_existing_output_or_accepts_wrong_bytes(self):
        source = self.root / 'source'; source.write_bytes(b'actual original')
        target = self.root / 'target'; target.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError): bundle.copy_verified(source, target, bundle.identity(source))
        self.assertEqual(target.read_bytes(), b'preserve')
        wrong = dict(bytes=source.stat().st_size, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'hash-changed'):
            bundle.copy_verified(source, self.root / 'partial', wrong)

    def fixture(self, extra=None, missing_object=False, wrong_object=False, changed_recipe=False, pax=None):
        # Synthetic ELF header only, never executable or build qualification.
        repo = self.root / 'repository'; repo.mkdir()
        component = b'original fixture source'
        pin = dict(components={'source.tar.gz': hashlib.sha256(component).hexdigest()})
        paths = ['tools/build_android_proot.py', 'tools/android_elf.py', 'tools/prepare_runtime.py', 'LICENSE',
                 'runtime/proot/sources.lock.json', 'runtime/proot/README.md']
        for name in paths:
            destination = repo / name; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((json.dumps(pin) if name.endswith('.json') else 'fixture recipe ' + name).encode())
        provider = self.root / 'provider'; (provider / 'assets/proot').mkdir(parents=True)
        (provider / 'assets/proot/build-evidence.json').write_bytes(b'{}\n')
        payload = {'original/source.tar.gz': component, 'build-evidence.json': b'{}\n'}
        payload.update({'esteria/' + name: (repo / name).read_bytes() for name in paths})
        if changed_recipe: payload['esteria/LICENSE'] = b'changed'
        if not missing_object:
            header = bytearray(20); header[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<HH', header, 16, 1, 62 if wrong_object else 183)
            payload['talloc-build-objects/talloc.c.5.o'] = bytes(header)
        if extra: payload[extra] = b'private fixture data'
        archive_path = self.root / 'sources.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as archive:
            for name, data in payload.items():
                item = tarfile.TarInfo(name); item.size = len(data)
                if pax is not None: item.pax_headers = pax
                archive.addfile(item, io.BytesIO(data))
        return repo, provider, archive_path

    def audit(self, **kwargs):
        repo, provider, archive_path = self.fixture(**kwargs)
        with (patch.object(bundle, 'ROOT', repo), patch.object(bundle.proot_build, 'LOCK', repo / 'runtime/proot/sources.lock.json'),
              patch.object(bundle.subprocess, 'check_output', return_value='runtime/proot/sources.lock.json\nruntime/proot/README.md\n')):
            return bundle.proot_sources(archive_path, provider)

    def test_originals_recipes_and_relinkable_arm64_objects_are_all_read_back(self):
        proof = self.audit(pax={'mtime': '1780058300.123456'})
        self.assertEqual(proof['relinkableArm64Objects'], 1)
        self.assertIn('original/source.tar.gz', proof['files'])
        self.assertIn('esteria/LICENSE', proof['files'])

    def test_private_extra_is_rejected_even_if_builder_directory_contained_it(self):
        with self.assertRaisesRegex(ValueError, 'unexpected-proot-source-file'):
            self.audit(extra='esteria/runtime/proot/private-signing-key')

    def test_oversized_pax_is_rejected_before_metadata_allocation(self):
        with self.assertRaisesRegex(ValueError, 'pax-size-limit'):
            self.audit(pax={'comment': 'x' * 20000})

    def test_same_size_modified_toolchain_notice_is_rejected(self):
        path = self.root / 'notices.zip'; expected = {}
        with zipfile.ZipFile(path, 'w') as archive:
            for name in bundle.NDK_NOTICES:
                original = b'exact original notice'
                expected[name] = dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest())
                archive.writestr('assets/notices/' + name, b'X' * len(original))
        with zipfile.ZipFile(path) as archive, self.assertRaisesRegex(ValueError, 'notice-hash-mismatch'):
            bundle.verify_ndk_notices(archive, expected)

    def test_missing_relinkable_object_wrong_machine_and_modified_recipe_fail(self):
        for options in (dict(missing_object=True), dict(wrong_object=True), dict(changed_recipe=True)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                previous = self.root; self.root = Path(temporary)
                try:
                    with self.assertRaises(ValueError): self.audit(**options)
                finally: self.root = previous


if __name__ == '__main__': unittest.main()
