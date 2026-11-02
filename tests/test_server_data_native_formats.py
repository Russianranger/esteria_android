"""Compiled pinned native declarations/readers versus bounded Python preflight.

The Detour implementation builds and loads a synthetic triangle. Other output
checks cover serialization headers only, not geographical/camera/model closure.
No owner assets, Android runtime, world entry or gameplay are qualified here.
"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from runtime import server_data_preflight as formats


FIXTURE = Path(__file__).resolve().parent / 'fixtures/native-formats-f35-471'
SERVER = 'f35f04d01689f034778e3474b3c820092f51e461'
CLIENT = '471ee42faadf4a97a1d0a86989cf1452621f2dc5'
SINGLE_FLOAT_GT = (
    'gtBarberShopCostBase', 'gtCombatRatings', 'gtChanceToMeleeCritBase',
    'gtChanceToMeleeCrit', 'gtChanceToSpellCritBase', 'gtChanceToSpellCrit',
    'gtNPCManaCostScaler', 'gtOCTRegenHP', 'gtRegenHPPerSpt', 'gtRegenMPPerSpt',
)


class NativeFormatSourceTests(unittest.TestCase):
    def test_exact_native_sources_and_client_readers_are_pinned(self):
        manifest = json.loads((FIXTURE / 'source-manifest.json').read_text())
        self.assertEqual(manifest['serverRevision'], SERVER)
        self.assertEqual(manifest['clientRevision'], CLIENT)
        self.assertFalse(manifest['worldQualified'])
        self.assertFalse(manifest['gameplayQualified'])
        self.assertEqual(len(manifest['files']), 48)
        for name, pin in manifest['files'].items():
            with self.subTest(name=name):
                self.assertNotIn('..', Path(name).parts)
                raw = (FIXTURE / name).read_bytes()
                self.assertEqual(len(raw), pin['bytes'])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), pin['sha256'])
                self.assertEqual(pin['revision'], CLIENT if name.startswith('client/') else SERVER)


class NativeFormatPreflightTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('c++')
        if not compiler:
            raise unittest.SkipTest('C++17 compiler required for pinned native reference execution')
        cls.temporary = tempfile.TemporaryDirectory(prefix='esteria-native-format-')
        cls.work = Path(cls.temporary.name)
        cls.output = cls.work / 'reference'
        server = FIXTURE / 'server'
        detour = server / 'deps/recastnavigation/Detour'
        includes = [FIXTURE, FIXTURE / 'client', FIXTURE / 'support',
                    server / 'src/common', server / 'src/common/DataStores', server / 'src/common/Collision',
                    server / 'src/common/Collision/Maps', server / 'src/tools/vmap4_extractor',
                    server / 'src/server/shared/DataStores', detour / 'Include']
        readers = sorted((FIXTURE / 'client/WoW/Source/DB/Rec').glob('*.cpp'))
        sources = [FIXTURE / 'native_format_writer.cpp', server / 'src/common/DataStores/DBCFileLoader.cpp', *readers,
                   *sorted((detour / 'Source').glob('*.cpp'))]
        command = [compiler, '-std=c++17', '-O1', '-Wall', '-Wextra', '-Wno-unused-parameter']
        command += [flag for include in includes for flag in ('-I', str(include))]
        command += [str(source) for source in sources] + ['-o', str(cls.work / 'native-format-writer')]
        built = subprocess.run(command, text=True, capture_output=True, timeout=90)
        if built.returncode:
            cls.temporary.cleanup()
            raise AssertionError('pinned native reference did not compile: ' + built.stderr[-12000:])
        executed = subprocess.run([str(cls.work / 'native-format-writer'), str(cls.output)],
                                  text=True, capture_output=True, timeout=20)
        if executed.returncode:
            cls.temporary.cleanup()
            raise AssertionError('pinned native reference failed: ' + executed.stderr[-12000:])
        cls.native = json.loads(executed.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def mutated(self, original, name, mutate):
        path = self.work / 'mutations' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = bytearray((self.output / original).read_bytes())
        mutate(raw)
        path.write_bytes(raw)
        return path

    def test_actual_native_sizes_and_detour_construction(self):
        self.assertEqual(self.native, {
            'mapHeaderBytes': 44, 'mmapHeaderBytes': 56, 'mmapIndexBytes': 28,
            'detourHeaderBytes': 100, 'cameraHeaderBytes': 304,
            'clientReadersExecuted': 12, 'clientTruncationsRejected': 12,
            'actualDetourTriangleBuiltAndLoaded': True, 'gameplayQualified': False,
            'serverPowerDisplayTwoPackedRowsLoaded': True,
            'serverGtSingleFloatProjectionRejected': True,
            'serverGtIndexedProjectionLoaded': True,
        })
        tile = (self.output / 'world/mmaps/0000000.mmtile').read_bytes()
        self.assertGreater(len(tile), 56 + self.native['detourHeaderBytes'])
        self.assertEqual(struct.unpack_from('<4I', tile), (0x4d4d4150, 7, 20, len(tile) - 56))
        self.assertEqual(struct.unpack_from('<2I', tile, 56), (0x444e4156, 7))
        self.assertEqual(struct.unpack_from('<4sI', (self.output / 'world/Cameras/reference.m2').read_bytes()),
                         (b'MD20', 264))

    def test_native_serialized_headers_are_accepted_and_classified(self):
        expected = {
            'maps/0000000.map': formats.check_map,
            'vmaps/000.vmtree': formats.check_vmap,
            'vmaps/000_00_00.vmtile': formats.check_vmap,
            'vmaps/reference.vmo': formats.check_vmap,
            'vmaps/GameObjectModels.dtree': formats.check_vmap,
            'mmaps/000.mmap': formats.check_mmap,
            'mmaps/0000000.mmtile': formats.check_mmtile,
            'Cameras/reference.m2': formats.check_camera,
        }
        for relative, checker in expected.items():
            with self.subTest(relative=relative):
                path = self.output / 'world' / relative
                self.assertIs(formats.data_file_checker(Path(relative).parts[0], path), checker)
                checker(path)

    def test_wrong_native_magic_versions_and_build_are_rejected(self):
        cases = [
            ('world/maps/0000000.map', formats.check_map, 0, b'XXXX'),
            ('world/maps/0000000.map', formats.check_map, 4, struct.pack('<I', 8)),
            ('world/maps/0000000.map', formats.check_map, 8, struct.pack('<I', 12341)),
            ('world/vmaps/GameObjectModels.dtree', formats.check_vmap, 0, b'VMAP_4.7'),
            ('world/mmaps/0000000.mmtile', formats.check_mmtile, 0, struct.pack('<I', 0)),
            ('world/mmaps/0000000.mmtile', formats.check_mmtile, 4, struct.pack('<I', 6)),
            ('world/mmaps/0000000.mmtile', formats.check_mmtile, 8, struct.pack('<I', 19)),
            ('world/Cameras/reference.m2', formats.check_camera, 0, b'MD21'),
        ]
        for index, (source, checker, offset, value) in enumerate(cases):
            with self.subTest(source=source, offset=offset):
                path = self.mutated(source, str(index) + Path(source).suffix,
                                    lambda raw: raw.__setitem__(slice(offset, offset + len(value)), value))
                with self.assertRaises(ValueError):
                    checker(path)

    def test_native_truncations_and_declared_tile_length_are_rejected(self):
        cases = [
            ('world/maps/0000000.map', formats.check_map, 43),
            ('world/vmaps/000.vmtree', formats.check_vmap, 7),
            ('world/mmaps/000.mmap', formats.check_mmap, 27),
            ('world/mmaps/0000000.mmtile', formats.check_mmtile, 55),
            ('world/Cameras/reference.m2', formats.check_camera, 7),
        ]
        for index, (source, checker, size) in enumerate(cases):
            with self.subTest(source=source):
                path = self.mutated(source, 'short-' + str(index), lambda raw: raw.__delitem__(slice(size, None)))
                with self.assertRaises(ValueError):
                    checker(path)
        tile = self.mutated('world/mmaps/0000000.mmtile', 'short-payload', lambda raw: raw.pop())
        with self.assertRaisesRegex(ValueError, 'payload length'):
            formats.check_mmtile(tile)
        extra = self.mutated('world/mmaps/000.mmap', 'extra-index', lambda raw: raw.extend(b'\0'))
        with self.assertRaisesRegex(ValueError, '28-byte'):
            formats.check_mmap(extra)

    def test_real_native_map_chunk_offsets_remain_checked(self):
        for name, offset, value in [('header-overlap', 12, 40), ('file-overrun', 16, 100000),
                                    ('chunk-overlap', 20, 44)]:
            with self.subTest(name=name):
                path = self.mutated('world/maps/0000000.map', name,
                                    lambda raw: struct.pack_into('<I', raw, offset, value))
                with self.assertRaises(ValueError):
                    formats.check_map(path)

    def test_all_ten_actual_generated_id_gt_readers_match_client_and_server_forms(self):
        for table in SINGLE_FLOAT_GT:
            for source, expected in [('client', (1, 4)), ('server', (2, 8))]:
                with self.subTest(table=table, source=source):
                    path = self.output / source / (table + '.dbc')
                    header = struct.unpack('<4s4I', path.read_bytes()[:20])
                    self.assertEqual(header[2:4], expected)
                    formats.check_dbc(path, content_profile='stock-3.3.5a')

    def test_native_explicit_id_gt_scalar_stays_two_fields(self):
        path = self.output / 'client/gtOCTClassCombatRatingScalar.dbc'
        formats.check_dbc(path, content_profile='stock-3.3.5a')
        wrong = self.work / 'gtOCTClassCombatRatingScalar.dbc'
        wrong.write_bytes((self.output / 'client/gtCombatRatings.dbc').read_bytes())
        with self.assertRaises(ValueError):
            formats.check_dbc(wrong, content_profile='stock-3.3.5a')

    def test_packed_client_power_display_and_server_projection_are_distinct(self):
        for source, expected in [('client', (6, 15)), ('server', (6, 24))]:
            with self.subTest(source=source):
                path = self.output / source / 'PowerDisplay.dbc'
                self.assertEqual(struct.unpack('<4s4I', path.read_bytes()[:20])[2:4], expected)
                formats.check_dbc(path, content_profile='stock-3.3.5a')

    def test_actual_server_loader_reads_two_packed_rgb_rows_and_refuses_single_field_gt_projection(self):
        raw = (self.output / 'server-reader/PowerDisplay-packed.dbc').read_bytes()
        self.assertEqual(struct.unpack_from('<4s4I', raw), (b'WDBC', 2, 6, 15, 1))
        self.assertEqual(len(raw), 20 + 2 * 15 + 1)
        self.assertEqual(struct.unpack_from('<3I3B', raw, 20), (7, 3, 0, 17, 99, 201))
        self.assertEqual(struct.unpack_from('<3I3B', raw, 35), (19, 11, 0, 255, 222, 111))
        self.assertTrue(self.native['serverPowerDisplayTwoPackedRowsLoaded'])
        self.assertTrue(self.native['serverGtSingleFloatProjectionRejected'])
        self.assertTrue(self.native['serverGtIndexedProjectionLoaded'])

    def test_compatibility_does_not_accept_arbitrary_gt_or_power_strides(self):
        for name, layouts in [('gtCombatRatings.dbc', [(1, 8), (2, 4), (3, 12)]),
                              ('PowerDisplay.dbc', [(6, 16), (6, 20), (5, 15)]),
                              ('Map.dbc', [(1, 4)])]:
            for fields, stride in layouts:
                with self.subTest(name=name, fields=fields, stride=stride):
                    path = self.work / name
                    path.write_bytes(struct.pack('<4s4I', b'WDBC', 1, fields, stride, 1) + b'\0' * (stride + 1))
                    with self.assertRaises(ValueError):
                        formats.check_dbc(path, content_profile='stock-3.3.5a')

    def test_native_dbc_truncation_and_declared_lengths_remain_checked(self):
        for name in ['gtCombatRatings.dbc', 'gtOCTClassCombatRatingScalar.dbc', 'PowerDisplay.dbc']:
            source = (self.output / 'client' / name).read_bytes()
            for size in [19, len(source) - 1, len(source) + 1]:
                with self.subTest(name=name, size=size):
                    path = self.work / name
                    path.write_bytes(source[:size] if size < len(source) else source + b'\0')
                    with self.assertRaises(ValueError):
                        formats.check_dbc(path, content_profile='stock-3.3.5a')

    def test_client_disk_compatibility_does_not_expand_custom_or_continuation_layouts(self):
        for name in ['gtCombatRatings.dbc', 'PowerDisplay.dbc']:
            client = self.output / 'client' / name
            with self.subTest(name=name, scope='custom'), self.assertRaises(ValueError):
                formats.check_dbc(client, content_profile='esteria-custom')
            continuation = self.work / (name + '1-reviewed')
            continuation.write_bytes(client.read_bytes())
            with self.subTest(name=name, scope='stock-continuation'), self.assertRaises(ValueError):
                formats.check_dbc(continuation, content_profile='stock-3.3.5a')
            continuation.write_bytes((self.output / 'server' / name).read_bytes())
            formats.check_dbc(continuation, content_profile='stock-3.3.5a')

    def test_full_reference_report_does_not_claim_gameplay(self):
        world = self.work / 'full-reference'
        shutil.copytree(self.output / 'world', world)
        shutil.copytree(self.output / 'client', world / 'dbc')
        report = formats.check_server_data(world, content_profile='stock-3.3.5a')
        self.assertTrue(report['checks_passed'], report['errors'])
        self.assertEqual(report['groups']['vmaps']['files_checked'], 4)
        self.assertFalse(report['gameplay_qualified'])


if __name__ == '__main__':
    unittest.main()
