"""Source-shaped stock checks; synthetic bytes never qualify a real client."""
import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import stock_content_inspection as stock


class MemoryStack:
    def __init__(self, files): self.files = files
    def read(self, name, maximum=64 << 20):
        name = name.replace('\\', '/')
        if name not in self.files: raise ValueError('missing essential stock member: ' + name)
        raw = self.files[name]
        if len(raw) > maximum: raise ValueError('size bound')
        return 'Data/patch.MPQ', raw


class StockContentChecks(unittest.TestCase):
    def test_signed_ui_closure_requires_real_includes_but_ignores_comments(self):
        files = {'Interface/GlueXML/GlueXML.toc': b'## Interface: 30300\r\nGlue.xml\r\n',
                 'Interface/GlueXML/GlueXML.toc.sig': b's' * 276,
                 'Interface/GlueXML/Glue.xml': b'<Ui><!-- <Include file="not-shipped.xml"/> -->'
                         b'<Include file="..\\SharedXML\\Shared.xml"/><Script file="Glue.lua"/></Ui>',
                 'Interface/GlueXML/Glue.lua': b'function StockGlue() end',
                 'Interface/SharedXML/Shared.xml': b'<Ui/>'}
        result = stock.inspect_ui(MemoryStack(files), 'Interface/GlueXML/GlueXML.toc')
        self.assertEqual(result['files'], 4)
        self.assertFalse(result['rsaAuthenticated']); self.assertFalse(result['runtimeDigestValidated'])
        del files['Interface/GlueXML/Glue.lua']
        with self.assertRaisesRegex(ValueError, 'missing essential stock member: Interface/GlueXML/Glue.lua'):
            stock.inspect_ui(MemoryStack(files), 'Interface/GlueXML/GlueXML.toc')

    def test_signature_structure_missing_file_recursion_and_escape_are_precise(self):
        files = {'Interface/FrameXML/FrameXML.toc': b'Main.xml\n',
                 'Interface/FrameXML/FrameXML.toc.sig': b's' * 275,
                 'Interface/FrameXML/Main.xml': b'<Ui/>'}
        with self.assertRaisesRegex(ValueError, '276 bytes'):
            stock.inspect_ui(MemoryStack(files), 'Interface/FrameXML/FrameXML.toc')
        files['Interface/FrameXML/Main.xml'] = b'<Ui><Include file="Main.xml"/></Ui>'
        with self.assertRaisesRegex(ValueError, 'recursive'):
            stock.inspect_ui(MemoryStack(files), 'Interface/FrameXML/FrameXML.toc')
        for name in ('../../outside.lua', '/etc/passwd', 'C:\\bad'):
            with self.assertRaises(ValueError): stock.virtual_name(name)

    def test_dbc_layout_length_and_real_row_sentinels_are_independent(self):
        layout = stock.CLIENT_DBC_LAYOUTS['DBFilesClient\\ChrRaces.dbc']
        good = struct.pack('<4s4I', b'WDBC', 1, *layout, 1) + struct.pack('<I', 1) + b'\0' * (layout[1] - 4) + b'\0'
        self.assertEqual(stock.inspect_dbc(good, 'DBFilesClient\\ChrRaces.dbc', layout)['records'], 1)
        for bad in (good[:-1], good[:20] + b'\0' * (len(good) - 20),
                    struct.pack('<4s4I', b'WDBC', 1, 1, 4, 1) + b'\1\0\0\0\0'):
            with self.assertRaisesRegex(ValueError, 'layout|sentinel'):
                stock.inspect_dbc(bad, 'DBFilesClient\\ChrRaces.dbc', layout)

    def test_source_derived_stores_and_standard_patches_remain_explicit(self):
        self.assertEqual(stock.CLIENT_DBC_LAYOUT_SOURCE['storeCount'], 238)
        self.assertEqual(stock.CLIENT_DBC_LAYOUT_SOURCE['fileCount'], 479)
        self.assertEqual(stock.CLIENT_DBC_LAYOUTS['DBFilesClient\\CharStartOutfit.dbc'], (77, 296))
        for name in ('Data/patch.MPQ', 'Data/patch-2.MPQ', 'Data/patch-3.MPQ',
                     'Data/enUS/patch-enUS.MPQ', 'Data/enUS/patch-enUS-2.MPQ', 'Data/enUS/patch-enUS-3.MPQ'):
            self.assertTrue(stock.standard_provider(name, 'enUS'))
        self.assertFalse(stock.standard_provider('Data/patch-Z.MPQ', 'enUS'))
        self.assertFalse(stock.standard_provider('Data/patch-HD.MPQ', 'enUS'))


@unittest.skipUnless(os.environ.get('ESTERIA_CLIENT_SOURCE'), 'exact selected client shader reader source not supplied')
class RealPinnedMpqInspection(unittest.TestCase):
    """Actual pinned MPQ reader over encrypted-table synthetic archives, no game."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source_root = Path(os.environ['ESTERIA_CLIENT_SOURCE']).resolve()
        self.tools = self.root / 'tools'; self.tools.mkdir()
        client_tools = self.source_root / 'Tools/VulkanShaders'
        for name in stock.storage.TOOL_FILES:
            target = self.tools / name; target.parent.mkdir(parents=True, exist_ok=True)
            if name == 'bin/glslangValidator': target.write_text('#!/bin/false\n'); target.chmod(0o700)
            else: shutil.copyfile(client_tools / name, target)
        (self.tools / 'shader-tools.json').write_bytes(stock.storage.encoded({'formatVersion': 1,
            'clientRevision': stock.CLIENT_REVISION,
            'files': {name: stock.storage.identity(self.tools / name, 64 << 20) for name in stock.storage.TOOL_FILES}}))
        self.reader, _ = stock.load_reader(self.tools, stock.CLIENT_REVISION)
        with patch.dict('sys.modules', {'bls': __import__('_esteria_verified_stock_bls')}), patch.object(sys, 'dont_write_bytecode', True):
            namespace = {'__name__': '_stock_mpq_fixture_builder', '__file__': str(client_tools / 'tests/test_archive.py')}
            fixture_source = (client_tools / 'tests/test_archive.py').read_text().replace('] * 32', '] * (1 << max(5, (len(records) * 2).bit_length()))')
            exec(compile(fixture_source, 'source-derived-variable-table-fixture', 'exec'), namespace)
        self.make_mpq = namespace['make_mpq']
        self.generation = 'a' * 64; self.at = self.root / 'game/generations' / self.generation
        self.source = self.at / 'data'; self.source.mkdir(parents=True)
        self.files = {'signaturefile': b'2\r\n2\r\nRELEASE\r\nsynthetic-not-signed',
            'Interface\\GlueXML\\GlueXML.toc': b'Glue.xml\r\n',
            'Interface\\GlueXML\\GlueXML.toc.sig': b's' * 276,
            'Interface\\GlueXML\\Glue.xml': b'<Ui/>',
            'Interface\\FrameXML\\FrameXML.toc': b'Frame.xml\r\n',
            'Interface\\FrameXML\\FrameXML.toc.sig': b's' * 276,
            'Interface\\FrameXML\\Frame.xml': b'<Ui/>',
            'Interface\\FrameXML\\Bindings.xml': b'<Bindings/>',
            'Shaders\\Vertex\\vs_3_0\\Synthetic.bls': b'not translated',
            'Shaders\\Pixel\\ps_3_0\\Synthetic.bls': b'not translated'}
        for name, layout in stock.CLIENT_DBC_LAYOUTS.items():
            sentinel = stock.SENTINELS.get(name.rsplit('\\', 1)[-1], 0)
            self.files[name] = struct.pack('<4s4I', b'WDBC', 1, *layout, 1) + sentinel.to_bytes(layout[1], 'little') + b'\0'
        self.archive('Data/common.MPQ', self.files)
        self.archive('Data/enUS/locale-enUS.MPQ', {})
        self.archive('Data/enUS/speech-enUS.MPQ', {})

    def archive(self, name, members):
        path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True)
        self.make_mpq(path, [(name, raw, 0) for name, raw in members.items()])
        with (self.at / 'journal.tsv').open('a') as journal:
            journal.write(base64.b64encode(name.encode()).decode() + '\t' + str(path.stat().st_size) + '\t0\t' +
                          hashlib.sha256(path.read_bytes()).hexdigest() + '\n')

    def inspect(self):
        return stock.inspect(self.source, self.tools, stock.CLIENT_REVISION, 'enUS', self.generation)

    def test_actual_reader_inspects_ui_dbcs_and_shader_inventory_without_claiming_authentication(self):
        report = self.inspect()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(len(report['checks']['clientDbcs']), 238)
        self.assertFalse(report['runtimeSignatureValidation']); self.assertFalse(report['runtimeExecution'])

    def test_unknown_patch_is_not_removed_or_labelled_optional_by_filename(self):
        self.archive('Data/patch-Z.MPQ', {'Interface\\Icons\\Generic.blp': b'unclassified'})
        report = self.inspect()
        self.assertFalse(report['passed']); self.assertEqual(report['exclusions'], [])
        self.assertEqual(report['unknownOverlays'][0]['path'], 'Data/patch-Z.MPQ')
        self.assertTrue((self.source / 'Data/patch-Z.MPQ').exists())

    def test_content_identified_esteria_overlay_is_excluded_and_ordinary_patches_remain(self):
        for name in ('Data/patch.MPQ', 'Data/patch-2.MPQ', 'Data/patch-3.MPQ', 'Data/enUS/patch-enUS-3.MPQ'):
            self.archive(name, {})
        self.archive('Data/patch-renamed.MPQ', {'Esteria\\EsteriaNaga.bin': struct.pack('<3I', 0x314D4845, 1, 0),
            'DBFilesClient\\ChrRaces.dbc': b'incompatible-overlay'})
        report = self.inspect()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual([row['path'] for row in report['exclusions']], ['Data/patch-renamed.MPQ'])
        self.assertEqual(len(report['providers']), 8)
        self.assertEqual(report['checks']['clientDbcs']['DBFilesClient\\ChrRaces.dbc']['provider'], 'Data/common.MPQ')

    def test_actual_reader_reports_corrupt_winning_stock_dbc_and_missing_ui(self):
        self.archive('Data/patch-3.MPQ', {'DBFilesClient\\ChrRaces.dbc': b'bad'})
        report = self.inspect(); self.assertFalse(report['passed'])
        self.assertTrue(any('truncated stock DBC: DBFilesClient\\ChrRaces.dbc' in error for error in report['errors']))


if __name__ == '__main__': unittest.main()
