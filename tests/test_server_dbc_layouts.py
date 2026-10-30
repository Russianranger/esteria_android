"""Known source-layout admission only; synthetic tables never qualify world data."""
import copy
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

from runtime import server_data_preflight as preflight
from tools import generate_server_dbc_layouts as generator


class ServerDbcLayouts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='server-dbc-layout-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def table(self, name, fields, stride, rows=1):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(struct.pack('<4s4I', b'WDBC', rows, fields, stride, 1) + b'\0' * (rows * stride + 1))
        return path

    def test_self_consistent_wrong_known_map_layout_refuses_with_a_header_only_read(self):
        path = self.table('Map.dbc', 1, 4)
        original = preflight.read_header
        with mock.patch.object(preflight, 'read_header', wraps=original) as reader:
            with self.assertRaisesRegex(ValueError, 'expects 66 fields and 264 record bytes, got 1/4'):
                preflight.check_dbc(path)
        reader.assert_called_once_with(path, 20)
        preflight.check_dbc(self.table('valid/Map.dbc', 66, 264))
        # Unknown custom tables get the existing structural check, not an
        # invented schema or an assertion that the server consumes their rows.
        preflight.check_dbc(self.table('UnknownCustom.dbc', 1, 4))

    def test_localized_and_standalone_continuation_tables_use_base_source_schema(self):
        preflight.check_dbc(self.table('enUS/ChrRaces.dbc', 69, 276))
        preflight.check_dbc(self.table('dbc-continuations/Map.dbc1-project', 66, 264))
        bad = self.table('dbc-continuations/Map.dbc2-project', 1, 4)
        with self.assertRaisesRegex(ValueError, 'pinned server DBC layout'):
            preflight.continuation_order(bad.parent, self.root / 'absent-base')

    def test_packed_byte_columns_and_native_pointer_width_do_not_change_disk_stride(self):
        preflight.check_dbc(self.table('CharStartOutfit.dbc', 77, 296))
        preflight.check_dbc(self.table('SpellItemEnchantmentCondition.dbc', 31, 64))
        preflight.check_dbc(self.table('CinematicCamera.dbc', 7, 28))
        for filename, fields, stride in [('CharStartOutfit.dbc', 77, 77 * 4),
                ('SpellItemEnchantmentCondition.dbc', 31, 31 * 4), ('CinematicCamera.dbc', 7, 32)]:
            with self.subTest(filename=filename), self.assertRaisesRegex(ValueError, 'record bytes'):
                preflight.check_dbc(self.table('wrong/' + filename, fields, stride))
        stores = '#define LOAD_DBC(store,file,sql) x\nDBCStorage<Example> sExample(Examplefmt);\n' \
            'LOAD_DBC(sExample, "Example.dbc", "example_dbc");\n'
        registry = '#define WXL_DBC(store,file) x\nWXL_DBC(sExample, "Example.dbc");\n'
        layouts, _ = generator.derive(stores, 'char constexpr Examplefmt[] = "nsbX";', registry)
        # s remains a four-byte on-disk string offset even on a 64-bit host;
        # b/X each occupy one input byte, unlike decoded struct sizing.
        self.assertEqual(layouts['example.dbc'], (4, 10, 'example_dbc'))

    def test_unknown_custom_base_and_continuation_still_require_identical_layouts(self):
        base = self.table('dbc/UnknownCustom.dbc', 1, 4)
        continuation = self.table('dbc-continuations/UnknownCustom.dbc1-test', 2, 8)
        with self.assertRaisesRegex(ValueError, 'differs from base'):
            preflight.continuation_order(continuation.parent, base.parent)

    def test_generated_inventory_is_present_only_and_preserves_sql_fallback_scope(self):
        self.assertEqual(len(preflight.DBC_LAYOUTS), 112)
        self.assertEqual(len(preflight.DBC_CONTINUATION_STORES), 111)
        self.assertNotIn('taxipathnode.dbc', preflight.DBC_CONTINUATION_STORES)
        self.assertTrue(all(row[2].endswith('_dbc') for row in preflight.DBC_LAYOUTS.values()))
        locked = json.loads((generator.ROOT / 'sources.lock.json').read_bytes())['sources']['server']
        self.assertEqual(preflight.DBC_LAYOUT_SOURCE['serverRevision'], locked['commit'])
        self.assertEqual(preflight.DBC_LAYOUT_SOURCE['serverPatches'], locked['patches'])
        self.assertEqual(set(preflight.DBC_LAYOUT_SOURCE['sourceFiles']), set(generator.SOURCE_FILES))
        for patch in locked['patches']:
            self.assertEqual(generator.identity((generator.ROOT / patch['path']).read_bytes())['sha256'], patch['sha256'])
        # No mandatory filename list is passed to check_dbc; other base stores
        # can be SQL-populated and their actual row coverage remains untested.
        preflight.check_dbc(self.table('Map.dbc', 66, 264, rows=0))

    def test_parser_ignores_disabled_loads_and_refuses_unrecognized_active_loads(self):
        stores = '#define LOAD_DBC(store,file,sql) x\nDBCStorage<Example> sExample(Examplefmt);\n' \
            'LOAD_DBC(sExample, "Example.dbc", "example_dbc");\n' \
            '// LOAD_DBC(sDisabled, "Disabled.dbc", "disabled_dbc");\n'
        formats = 'char constexpr Examplefmt[] = "ni";\n// char constexpr Disabledfmt[] = "l";\n'
        registry = '#define WXL_DBC(store,file) x\nWXL_DBC(sExample, "Example.dbc");\n'
        self.assertEqual(generator.derive(stores, formats, registry)[0], {'example.dbc': (2, 8, 'example_dbc')})
        for changed in (stores + 'LOAD_DBC(sUnknown, "Unknown.dbc", "unknown_dbc");\n',
                stores.replace('"example_dbc"', 'nullptr'), stores.replace('Examplefmt', 'Missingfmt')):
            with self.subTest(changed=changed[-80:]), self.assertRaises(ValueError):
                generator.derive(changed, formats, registry)

    def test_generator_reads_exact_git_blobs_and_refuses_modified_sources_or_patch(self):
        server = self.root / 'server'; server.mkdir()
        integration = self.root / 'integration'; integration.mkdir()
        stores = '#define LOAD_DBC(store,file,sql) x\nDBCStorage<Example> sExample(Examplefmt);\n' \
            'LOAD_DBC(sExample, "Example.dbc", "example_dbc");\n' \
            'if (dbTable) storage.LoadFromDB(dbTable, storage.GetFormat());\nif (storage.GetNumRows()) {}\n'
        content = {generator.STORES: stores, generator.FORMATS: 'char constexpr Examplefmt[] = "ni";\n',
            generator.REGISTRY: '#define WXL_DBC(store,file) x\nWXL_DBC(sExample, "Example.dbc");\n',
            generator.LOADER: "if (fmt[i - 1] == 'b' || fmt[i - 1] == 'X') fieldsOffset[i] += sizeof(uint8); "
                'else fieldsOffset[i] += sizeof(uint32);\n',
            generator.FIELD_TYPES: "FT_NA_BYTE = 'X', FT_BYTE = 'b'\n", generator.OVERLAY: '// test-only SQL fixture\n'}
        for name, value in content.items():
            path = server / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(server), '-c', 'user.name=TEST ONLY', '-c',
                'user.email=test@example.invalid', '-c', 'commit.gpgsign=false', *args], stderr=subprocess.DEVNULL)
        git('init'); git('add', '.'); git('commit', '-m', 'Test-only DBC declarations')
        selected = dict(url='https://github.com/Russianranger/EsteriaWoW.git',
            commit=git('rev-parse', 'HEAD').decode().strip(), patches=[])
        (integration / 'sources.lock.json').write_text(json.dumps(dict(sources=dict(server=selected))))
        block = generator.generated_block(server, integration)
        self.assertIn("'example.dbc': (2, 8, 'example_dbc')", block)
        self.assertEqual(generator.update(generator.START + generator.END, block), block)
        path = server / generator.FORMATS; path.write_text(content[generator.FORMATS] + '// local change\n')
        with self.assertRaisesRegex(ValueError, 'source-file-modified'): generator.generated_block(server, integration)
        path.write_text(content[generator.FORMATS])
        patch = integration / 'changed.patch'; patch.write_bytes(('--- a/' + generator.FORMATS + '\n+++ b/' + generator.FORMATS + '\n').encode())
        selected['patches'] = [dict(path=patch.name, sha256=generator.identity(patch.read_bytes())['sha256'])]
        (integration / 'sources.lock.json').write_text(json.dumps(dict(sources=dict(server=selected))))
        with self.assertRaisesRegex(ValueError, 'adaptation-needs-explicit-support'):
            generator.generated_block(server, integration)
        selected['patches'][0]['sha256'] = '0' * 64
        (integration / 'sources.lock.json').write_text(json.dumps(dict(sources=dict(server=selected))))
        with self.assertRaisesRegex(ValueError, 'patch-identity-differs'): generator.generated_block(server, integration)


if __name__ == '__main__': unittest.main()
