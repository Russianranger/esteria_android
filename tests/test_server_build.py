import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_server_build as verifier


DYNAMIC = '''Dynamic section at offset 0x100 contains 4 entries:
 0x0000000000000001 (NEEDED)             Shared library: [libc.so.6]
 0x0000000000000001 (NEEDED)             Shared library: [libstdc++.so.6]
 0x000000000000001d (RUNPATH)            Library runpath: [$ORIGIN/../lib]
Version definition section '.gnu.version_d' contains 1 entry:
  0x0000: Rev: 1 Flags: BASE Index: 1 Cnt: 1 Name: GLIBC_99.0
Version needs section '.gnu.version_r' contains 2 entries:
  000000: Version: 1 File: libc.so.6 Cnt: 2
  0x0010:   Name: GLIBC_2.34  Flags: none Version: 3
  0x0020:   Name: GLIBC_2.9  Flags: none Version: 2
  0x0030: Version: 1 File: libstdc++.so.6 Cnt: 1
  0x0040:   Name: GLIBCXX_3.4.32  Flags: none Version: 4
'''


def elf(machine=183, interpreter=b'/lib/ld-linux-aarch64.so.1\0'):
    data = bytearray(256)
    data[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', data, 16, 3, machine, 1)
    struct.pack_into('<Q', data, 32, 64)
    struct.pack_into('<HHH', data, 52, 64, 56, 2)
    struct.pack_into('<IIQQQQQQ', data, 64, 1, 5, 0, 0, 0, 256, 256, 4096)
    struct.pack_into('<IIQQQQQQ', data, 120, 3, 4, 192, 0, 0, len(interpreter), len(interpreter), 1)
    data[192:192 + len(interpreter)] = interpreter
    return bytes(data)


class ServerBuildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def binary(self, name='binary', **options):
        path = self.root / name
        path.write_bytes(elf(**options))
        path.chmod(0o755)
        return path

    def test_aarch64_header_and_interpreter_require_real_executable_shape(self):
        path = self.binary()
        result = verifier.elf_header(path, executable=True)
        self.assertEqual(result['machine'], 'AArch64')
        self.assertEqual(result['interpreter'], '/lib/ld-linux-aarch64.so.1')
        for data in (elf(machine=62), elf(interpreter=b'/system/bin/linker64\0'), b'not ELF',
                     elf()[:100]):
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                verifier.elf_header(path, executable=True)
        path.write_bytes(elf())
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'mode'):
            verifier.elf_header(path, executable=True)

    def test_elf_segment_and_program_header_bounds(self):
        path = self.binary()
        for offset, fmt, value in ((32, '<Q', 255), (56, '<H', 0), (64 + 32, '<Q', 999), (120 + 32, '<Q', 9000)):
            data = bytearray(elf())
            struct.pack_into(fmt, data, offset, value)
            path.write_bytes(data)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                verifier.elf_header(path)

    def test_version_requirements_ignore_exports_and_use_numeric_glibc_order(self):
        result = verifier.dynamic_metadata(DYNAMIC)
        self.assertEqual(result['maximumGlibcVersionRequired'], 'GLIBC_2.34')
        self.assertEqual(result['needed'], ['libc.so.6', 'libstdc++.so.6'])
        self.assertEqual(result['versionRequirements']['libstdc++.so.6'], ['GLIBCXX_3.4.32'])
        self.assertEqual(result['runpath'], ['$ORIGIN/../lib'])
        self.assertFalse(result['dependencyClosureQualified'])
        with self.assertRaisesRegex(ValueError, 'duplicate-needed'):
            verifier.dynamic_metadata(DYNAMIC + '  (NEEDED) Shared library: [libc.so.6]\n')

    def test_symlinks_and_unbounded_install_inventory_are_rejected(self):
        package = self.root / 'package'
        package.mkdir()
        (package / 'linked').symlink_to(self.binary())
        with self.assertRaises(ValueError):
            verifier.installed_files(package)
        with self.assertRaises((ValueError, OSError)):
            verifier.identity(package / 'linked')
        (package / 'linked').unlink()
        (package / 'data').write_bytes(b'data')
        with patch.object(verifier, 'MAX_FILES', 0), self.assertRaisesRegex(ValueError, 'count-limit'):
            verifier.installed_files(package)

    def test_hashing_streams_large_inputs_and_metadata_limits_are_real(self):
        path = self.root / 'large'
        block = b'fixture' * 10000
        digest = hashlib.sha256()
        with path.open('wb') as output:
            for _ in range(200):
                output.write(block)
                digest.update(block)
        self.assertEqual(verifier.identity(path), {'bytes': len(block) * 200, 'sha256': digest.hexdigest()})
        with patch.object(verifier, 'MAX_FILE', 10), self.assertRaisesRegex(ValueError, 'size-limit'):
            verifier.identity(path)

    def test_diagnostic_process_output_timeout_and_failure_are_bounded(self):
        self.assertEqual(verifier.bounded_command([sys.executable, '-c', 'print("ok")']), 'ok\n')
        for code, options in (('print("x" * 100000)', {'limit': 100}),
                              ('import time;time.sleep(10)', {'timeout': 0.05}),
                              ('raise SystemExit(3)', {})):
            with self.subTest(code=code), self.assertRaises(ValueError):
                verifier.bounded_command([sys.executable, '-c', code], **options)

    def fixture(self):
        install, server = self.root / 'install', self.root / 'server'
        (install / 'bin').mkdir(parents=True)
        for name in verifier.REQUIRED_APPS + verifier.REQUIRED_TOOLS:
            path = install / 'bin' / name
            path.write_bytes(elf())
            path.chmod(0o755)
        lock = json.loads((verifier.ROOT / 'sources.lock.json').read_text())
        lock['sources']['server']['patches'] = []
        lock['sources']['server']['submodules'] = {}
        lock_path = self.root / 'sources.lock.json'
        lock_path.write_text(json.dumps(lock))
        (install / 'sources.lock.json').write_bytes(lock_path.read_bytes())
        for name in ('src/server/apps/CMakeLists.txt', 'src/tools/CMakeLists.txt',
                     'src/cmake/macros/ConfigureApplications.cmake', 'src/cmake/macros/ConfigureTools.cmake'):
            path = server / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic CMake source')
        for parent, names in (('src/server/apps', verifier.REQUIRED_APPS), ('src/tools', verifier.REQUIRED_TOOLS)):
            for name in names:
                (server / parent / name).mkdir()
        cache = self.root / 'CMakeCache.txt'
        cache.write_text('APPS_BUILD:STRING=all\nTOOLS_BUILD:STRING=all\nSCRIPTS:STRING=static\n'
                         'MODULES:STRING=static\nLUA_VERSION:STRING=lua52\nELUNA:BOOL=ON\n'
                         'LUA_STATIC:BOOL=ON\nCMAKE_BUILD_TYPE:STRING=RelWithDebInfo\n')
        packages, host = install / 'build-packages.txt', install / 'build-host.txt'
        packages.write_text('synthetic\t1.0\n')
        host.write_text('synthetic ARM host\n')
        return install, server, lock_path, cache, packages, host

    def test_complete_manifest_is_explicitly_build_only_and_does_not_execute_payload(self):
        inputs = self.fixture()
        commands = []
        def read(command, **kwargs):
            commands.append(command)
            self.assertEqual(command[0], 'readelf')
            return 'GNU readelf fixture\n' if '--version' in command else DYNAMIC
        with patch.object(verifier.fetch_sources, 'verify_checkout') as checkout, \
             patch.object(verifier.fetch_sources, 'run', return_value='a' * 40), \
             patch.object(verifier, 'bounded_command', side_effect=read):
            report = verifier.verify(*inputs, 'a' * 40, '123.1')
        checkout.assert_called_once()
        self.assertEqual(len(report['requiredExecutables']), 7)
        self.assertEqual(report['evidence'], 'build-only')
        self.assertFalse(report['serverStarted'])
        self.assertFalse(report['hostLoaderSmoke']['requested'])
        self.assertFalse(report['androidRuntimeQualified'])
        self.assertFalse(report['runtimeDependencyClosureQualified'])
        self.assertEqual(len(commands), 8)

    def test_missing_target_wrong_pin_and_disabled_options_prevent_manifest(self):
        inputs = self.fixture()
        with patch.object(verifier.fetch_sources, 'verify_checkout'), \
             patch.object(verifier.fetch_sources, 'run', return_value='b' * 40), \
             self.assertRaisesRegex(ValueError, 'revision-mismatch'):
            verifier.verify(*inputs, 'a' * 40, '123.1')
        (inputs[0] / 'bin' / 'worldserver').unlink()
        with patch.object(verifier.fetch_sources, 'verify_checkout'), \
             patch.object(verifier.fetch_sources, 'run', return_value='a' * 40), \
             self.assertRaisesRegex(ValueError, 'extractor-missing'):
            verifier.verify(*inputs, 'a' * 40, '123.1')
        with inputs[3].open('a') as output:
            output.write('APP_WORLDSERVER:STRING=disabled\n')
        with self.assertRaisesRegex(ValueError, 'disabled-application'):
            verifier.cmake_options(inputs[3])


if __name__ == '__main__':
    unittest.main()
