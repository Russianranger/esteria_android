import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('check_assets', Path(__file__).resolve().parents[1] / 'tools/check_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


class AssetPreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, path, data):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
        return file

    def test_dbc_continuation_uses_wdbc_and_lengths(self):
        file = self.write('dbc/ChrRaces.dbc1-Esteria', struct.pack('<4s4I', b'WDBC', 2, 1, 4, 1) + b'\0' * 9)
        assets.check_dbc(file)
        file.write_bytes(file.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'declared length'):
            assets.check_dbc(file)

    def test_old_map_and_wrong_client_build_rejected(self):
        for version, build in [(8, 12340), (9, 11723)]:
            file = self.write('maps/0000000.map', struct.pack('<4s10I', b'MAPS', version, build, *([0] * 8)))
            with self.assertRaisesRegex(ValueError, 'expected MAPS'):
                assets.check_map(file)

    def test_map_chunks_cannot_overlap_or_point_outside_file(self):
        file = self.write('maps/0000000.map', struct.pack('<4s10I', b'MAPS', 9, 12340, 44, 8, 48, 8, 0, 0, 0, 0) + b'\0' * 12)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            assets.check_map(file)
        file.write_bytes(struct.pack('<4s10I', b'MAPS', 9, 12340, 44, 100, *([0] * 6)))
        with self.assertRaisesRegex(ValueError, 'outside'):
            assets.check_map(file)

    def test_mmtile_version_and_payload_length_checked(self):
        header = struct.pack('<4I', 0x4D4D4150, 7, 20, 4) + b'\0' * 40
        file = self.write('mmaps/0000000.mmtile', header + b'abcd')
        assets.check_mmtile(file)
        file.write_bytes(header + b'abc')
        with self.assertRaisesRegex(ValueError, 'payload length'):
            assets.check_mmtile(file)

    def test_complete_synthetic_format_set_is_not_gameplay_qualification(self):
        self.write('dbc/ChrRaces.dbc1-Esteria', struct.pack('<4s4I', b'WDBC', 0, 1, 4, 1) + b'\0')
        self.write('maps/0000000.map', struct.pack('<4s10I', b'MAPS', 9, 12340, *([0] * 8)))
        self.write('vmaps/000.vmtree', b'VMAP_4.8')
        self.write('mmaps/000.mmap', b'\0' * 28)
        self.write('Cameras/test.m2', b'MD20' + struct.pack('<I', 264))
        report = assets.check_server_data(self.root)
        self.assertTrue(report['checks_passed'], report)
        self.assertFalse(report['gameplay_qualified'])
        self.assertEqual(report['groups']['dbc']['files_checked'], 1)

    def test_empty_and_symlink_directories_fail(self):
        self.assertFalse(assets.check_server_data(self.root)['checks_passed'])
        source = self.write('source/test.dbc', b'WDBC')
        try:
            (self.root / 'dbc').symlink_to(source.parent, target_is_directory=True)
        except OSError:
            self.skipTest('symlinks unavailable')
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            list(assets.files_bounded(self.root / 'dbc'))


if __name__ == '__main__':
    unittest.main()
