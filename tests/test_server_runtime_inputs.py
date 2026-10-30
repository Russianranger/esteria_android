import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from runtime.server.record_runtime import elf_identity, package_inventory, source_inventory
from runtime.server.capture_sources import source_selector


ROOT = Path(__file__).resolve().parents[1] / 'runtime/server'


class ServerRuntimeInputs(unittest.TestCase):
    def test_package_inventory_preserves_source_version_and_architecture(self):
        text = ('mysql-client-core-8.0\t8.0.46-0ubuntu0.24.04.4\tarm64\tmysql-8.0\t8.0.46-0ubuntu0.24.04.4\n'
                'libmysqlclient21:arm64\t8.0.46-0ubuntu0.24.04.4\tarm64\tmysql-8.0\t8.0.46-0ubuntu0.24.04.4\n'
                'ca-certificates\t20240203\tall\t\t\n')
        inventory = package_inventory(text)
        self.assertEqual(len(inventory), 3)
        sources = source_inventory(inventory)
        self.assertEqual(len(sources), 2)
        self.assertIn({'package': 'mysql-8.0', 'version': '8.0.46-0ubuntu0.24.04.4'}, sources)
        self.assertIn({'package': 'ca-certificates', 'version': '20240203'}, sources)
        for invalid in ('', text + text, text.replace('\tarm64\t', '\tamd64\t')):
            with self.assertRaises(ValueError):
                package_inventory(invalid)

    def test_source_selection_cannot_become_an_apt_option_or_unpinned_request(self):
        self.assertEqual(source_selector({'package': 'mysql-8.0', 'version': '8.0.46-0ubuntu0.24.04.4'}),
                         'mysql-8.0=8.0.46-0ubuntu0.24.04.4')
        for name, version in (('--allow-unauthenticated', '1'), ('mysql-8.0', ''), ('mysql-8.0', 'latest'),
                              ('pkg', '1;touch /tmp/x'), ('../pkg', '1')):
            with self.assertRaises(ValueError):
                source_selector({'package': name, 'version': version})

    def test_elf_probe_rejects_host_architecture_and_records_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'executable'
            data = bytearray(64)
            data[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<H', data, 18, 183)
            path.write_bytes(data)
            result = elf_identity(path)
            self.assertEqual(result['sha256'], hashlib.sha256(data).hexdigest())
            struct.pack_into('<H', data, 18, 62)
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                elf_identity(path)

    def test_recipe_uses_verified_snapshot_and_exact_mysql_source_pins(self):
        lock = json.loads((ROOT / 'sources.lock.json').read_text())
        docker = (ROOT / 'Dockerfile').read_text()
        self.assertIn('FROM ' + lock['baseImage']['reference'], docker)
        checks = (ROOT / 'inrelease.SHA256SUMS').read_text()
        sources = (ROOT / 'ubuntu.sources').read_text()
        self.assertIn('URIs: ' + lock['snapshot']['uri'], sources)
        for release in lock['snapshot']['inRelease']:
            self.assertIn(release['sha256'] + '  snapshot.ubuntu.com_ubuntu_' + lock['snapshot']['id'] +
                          '_dists_' + release['suite'] + '_InRelease', checks)
        self.assertEqual(len(lock['mysql']['sourceArchives']), 3)
        self.assertEqual(len(lock['mysql']['binaryPackages']), 3)
        for package in lock['mysql']['binaryPackages']:
            self.assertIn(package['package'] + '=' + package['version'], docker)
            self.assertIn(package['sha256'] + '  ' + package['file'],
                          (ROOT / 'mysql-binaries.SHA256SUMS').read_text())
        for item in lock['mysql']['sourceArchives'] + lock['mysql']['binaryPackages']:
            self.assertRegex(item['sha256'], '^[0-9a-f]{64}$')
            self.assertGreater(item['bytes'], 0)
            self.assertTrue(item['url'].startswith(lock['snapshot']['uri'] + '/pool/main/m/mysql-8.0/'))
        self.assertFalse(lock['runtimeQualified'])
        self.assertFalse(lock['mysql']['runtimeVersionVerified'])


if __name__ == '__main__':
    unittest.main()
