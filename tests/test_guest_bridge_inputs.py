import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from runtime.bridges.record_build import elf

ROOT = Path(__file__).resolve().parents[1]


class GuestBridgeInputs(unittest.TestCase):
    def test_exact_source_snapshot_and_primary_versions_match_recipe(self):
        directory = ROOT / 'runtime/bridges'
        lock = json.loads((directory / 'sources.lock.json').read_text())
        self.assertIn('FROM ' + lock['baseImageReference'], (directory / 'Dockerfile').read_text())
        self.assertEqual((directory / 'packages.txt').read_text().splitlines(),
                         [p['package'] + '=' + p['version'] for p in lock['packages']])
        self.assertEqual(len({p['package'] for p in lock['packages']}), len(lock['packages']))
        self.assertFalse(lock['androidQualified'])
        self.assertEqual(lock['architecture'], 'arm64')
        for release in lock['inRelease']:
            self.assertIn(release['sha256'] + '  snapshot.debian.org_archive_',
                          (directory / 'inrelease.SHA256SUMS').read_text())
        selected = {p['package']: p['version'] for p in lock['packages']}
        self.assertEqual(selected['libc6'], '2.36-9+deb12u14')
        self.assertEqual(selected['libasound2-dev'], '1.2.8-1+b1')
        self.assertEqual(selected['libxtst-dev'], '2:1.2.3-1.1')
        for item in lock['packages']:
            self.assertEqual(item['architecture'], 'arm64')
            self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
        xtst = next(source for source in lock['sources'] if source['package'] == 'libxtst')
        self.assertEqual(len(xtst['archives']), 3)
        for source in lock['sources']:
            for archive in source['archives']:
                self.assertGreater(archive['bytes'], 0)
                self.assertRegex(archive['sha256'], r'^[0-9a-f]{64}$')
                self.assertTrue(archive['url'].startswith('https://snapshot.debian.org/archive/'))
                self.assertNotIn('/', archive['file'])

    def test_elf_receipt_accepts_matching_arm64_glibc_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'esteria-x11-input'
            head = bytearray(64); head[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', head, 18, 183)
            executable.write_bytes(head)
            with patch('runtime.bridges.record_build.subprocess.check_output', side_effect=[
                    '(NEEDED) Shared library: [libX11.so.6]\n(NEEDED) Shared library: [libc.so.6]',
                    '[Requesting program interpreter: /lib/ld-linux-aarch64.so.1]',
                    'Name: GLIBC_2.17\nName: GLIBC_2.34']):
                result = elf(executable)
            self.assertEqual(result['maxGlibc'], '2.34')
            self.assertEqual(result['architecture'], 'arm64')
            self.assertEqual(result['needed'], ['libX11.so.6', 'libc.so.6'])

    def test_elf_receipt_rejects_wrong_architecture_loader_libraries_and_newer_abi(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'esteria-x11-input'
            head = bytearray(64); head[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', head, 18, 62)
            executable.write_bytes(head)
            with self.assertRaisesRegex(ValueError, 'not-elf64-arm64'):
                elf(executable)
            struct.pack_into('<H', head, 18, 183); executable.write_bytes(head)
            for values, error in [
                (['(NEEDED) Shared library: [libXtst.so.6]'], 'unexpected-guest-library'),
                (['(NEEDED) Shared library: [libc.so.6]\n(RUNPATH) [/tmp/build]'], 'unexpected-library-search-path'),
                (['(NEEDED) Shared library: [libc.so.6]', '[Requesting program interpreter: /system/bin/linker64]'], 'wrong-guest-interpreter'),
                (['(NEEDED) Shared library: [libc.so.6]', '[Requesting program interpreter: /lib/ld-linux-aarch64.so.1]',
                  'Name: GLIBC_2.39'], 'requires-glibc-newer-than-wine-rootfs')]:
                with patch('runtime.bridges.record_build.subprocess.check_output', side_effect=values):
                    with self.assertRaisesRegex(ValueError, error):
                        elf(executable)


if __name__ == '__main__':
    unittest.main()
