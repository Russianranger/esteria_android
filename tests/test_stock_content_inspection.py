"""Source-shaped stock checks; synthetic bytes never qualify a real client."""
import base64
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
import io
from contextlib import redirect_stderr, redirect_stdout
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

    def test_ancillary_classification_matches_complete_client_provider_boundaries(self):
        for name in ('Data/common.MPQ', 'DATA/common-3.MpQ', 'data/expansion.mpq', 'Data/alternate.MPQ',
                     'Data/patch-HD.MPQ', 'Data/enUS/locale-enUS.MPQ', 'data/frFR/speech-frFR.MPQ',
                     'DATA/ruRU/patch-ruRU-X.MpQ', 'Data/patch-folder.MPQ/inner.MPQ'):
            self.assertTrue(stock.effective_provider_path(name), name)
        for name in ('uninstall.MPQ', 'Data/sound.MPQ', 'Data/development.MPQ',
                     'Data/wow-update-base-12340.MPQ', 'Data/enUS/backup/locale-enUS.MPQ',
                     'Data/enUS/wow-update-enUS-12340.MPQ', 'Data/not-a-locale/patch-not-a-locale-Z.MPQ'):
            self.assertFalse(stock.effective_provider_path(name), name)
        self.assertEqual(stock.imported_name('Installer/Información.MPQ'), 'Installer/Información.MPQ')
        for name in ('../bad.MPQ', 'Data/../bad.MPQ', '/bad.MPQ', 'Data\\bad.MPQ', 'Data/C:bad.MPQ'):
            with self.assertRaises(ValueError): stock.imported_name(name)

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
        self.encrypt_table = namespace['encrypt']
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

    def ancillary(self, name, raw=b'not an archive; the classical engine never opens this path'):
        path = self.source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        with (self.at / 'journal.tsv').open('a') as journal:
            journal.write(base64.b64encode(name.encode()).decode() + '\t' + str(len(raw)) + '\t0\t' +
                          hashlib.sha256(raw).hexdigest() + '\n')
        return path

    def inspect(self):
        return stock.inspect(self.source, self.tools, stock.CLIENT_REVISION, 'enUS', self.generation)

    def test_actual_reader_inspects_ui_dbcs_and_shader_inventory_without_claiming_authentication(self):
        report = self.inspect()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual(len(report['checks']['clientDbcs']), 238)
        self.assertFalse(report['runtimeSignatureValidation']); self.assertFalse(report['runtimeExecution'])

    def test_transient_android_pressure_never_publishes_failed_report_and_same_inputs_retry_succeeds(self):
        expected = self.inspect()
        report_path = self.root / 'stock-report.json'
        arguments = ['stock-inspection', '--source', str(self.source), '--tools', str(self.tools),
            '--report', str(report_path), '--client-revision', stock.CLIENT_REVISION,
            '--locale', 'enUS', '--generation', self.generation, '--android-low-memory']
        original_context = stock.world_io.android_policy
        now = [0.0]
        def sleep(delay): now[0] += delay
        def policy(available):
            return lambda *args, **kwargs: original_context(*args, **kwargs, clock=lambda: now[0],
                sleeper=sleep, memory_probe=lambda: available)
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', arguments), patch.object(stock.world_io, 'android_policy', side_effect=policy(100 << 20)), \
                redirect_stderr(stderr), redirect_stdout(stdout):
            self.assertEqual(stock.main(), stock.world_io.PAUSED_EXIT_CODE)
        self.assertFalse(report_path.exists(), 'Transient pressure must not poison the Android cached validation report')
        self.assertIn('ESTERIA_PREPARATION_PAUSED', stderr.getvalue())
        self.assertNotIn(str(self.source), stderr.getvalue())
        with patch.object(sys, 'argv', arguments), patch.object(stock.world_io, 'android_policy', side_effect=policy(4 << 30)), \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            self.assertEqual(stock.main(), 0)
        self.assertEqual(json.loads(report_path.read_text()), expected)
        self.assertTrue(json.loads(report_path.read_text())['passed'])

    def test_transient_pause_inside_ui_or_dbc_validation_bubbles_instead_of_becoming_bad_content(self):
        real_read = stock.Stack.read
        for paused_name in ('signaturefile', 'DBFilesClient\\ChrRaces.dbc'):
            def read(stack, name, maximum=64 << 20):
                if name == paused_name:
                    raise stock.world_io.PreparationPaused('Fixture transient memory pressure')
                return real_read(stack, name, maximum)
            with self.subTest(paused_name=paused_name), patch.object(stock.Stack, 'read', read), \
                    self.assertRaises(stock.world_io.PreparationPaused):
                self.inspect()

    def test_nonprovider_mpqs_are_recorded_without_opening_and_sources_are_preserved(self):
        names = ('Data/wow-update-base-12340.MPQ', 'Data/sound.MpQ', 'uninstall.MPQ',
                 'Data/enUS/backup/locale-enUS.MPQ', 'Installer/Información.MPQ',
                 'Data/installer.MPQ/help.txt', 'Data/installer.MPQ/assets/inner.MPQ')
        paths = [self.ancillary(name) for name in names]
        # An archive for another supported locale remains outside the current
        # stack, but is not classified as harmless to every supported locale.
        self.archive('Data/frFR/patch-frFR-X.MPQ', {'Interface\\Icons\\Generic.blp': b'unclassified'})
        report = self.inspect()
        self.assertTrue(report['passed'], report['errors'])
        self.assertEqual({row['path'] for row in report['exclusions']}, set(names))
        self.assertTrue(all('Ancillary archive or folder member' in row['reason'] for row in report['exclusions']))
        self.assertEqual(len(report['providers']), 3)
        self.assertEqual(report['unknownOverlays'], [])
        self.assertTrue(all(path.exists() for path in paths))
        # The later extractor planner also ignores these names and retains the
        # same effective stack; it never interprets the generation's data/
        # storage prefix as the client's Data/ provider directory.
        manifest = stock.order.plan(self.source, 'enUS', profile=dict(classical=True, trial=False,
            streaming=False, directAccess=False, retailVirtualProviders=False,
            parentDataVisible=False, installDataVisible=False))
        self.assertEqual({row['path'] for row in manifest['providers']},
            {row['path'] for row in report['providers']})

    def test_ancillary_source_changes_and_active_alternate_views_are_not_ignored(self):
        path = self.ancillary('Data/wow-update-base-12340.MPQ')
        path.write_bytes(b'changed size')
        with self.assertRaisesRegex(ValueError, 'ancillary archive differs.*Data/wow-update-base-12340.MPQ'):
            self.inspect()
        path.unlink()
        self.archive('Data/alternate.MPQ', {})
        with self.assertRaisesRegex(ValueError, 'alternate.MPQ archive views are unsupported'):
            self.inspect()

    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'JDK17 host tools unavailable')
    def test_public_folder_zip_imports_reach_real_reader_inspection_and_stock_selection(self):
        """Encrypted synthetic archives cross both real Java import routes.

        Imported journals are created by production GameDataImporter, then read
        by the exact client reader. No handcrafted journal is used for this
        pipeline; the source fixture's earlier journal stays outside its root.
        """
        repository = Path(__file__).resolve().parents[1]
        classes = self.root / 'java-classes'; classes.mkdir()
        sources = sorted((repository / 'core/src/main/java').rglob('*.java'))
        command = ['javac', '-encoding', 'UTF-8', '-d', str(classes),
                   *(str(path) for path in sources), str(repository / 'tests/StockImportReference.java')]
        compiled = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)

        def java(route, store, source, *extra):
            process = subprocess.run(['java', '-Xmx32m', '-cp', str(classes), 'StockImportReference',
                route, str(store), str(source), *(str(value) for value in extra)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
            return Path(process.stdout.strip())

        def pe_fixture():
            raw = bytearray(1024)
            def u16(at, value): struct.pack_into('<H', raw, at, value)
            def u32(at, value): struct.pack_into('<I', raw, at, value)
            u16(0, 0x5a4d); u32(0x3c, 0x80); u32(0x80, 0x4550)
            u16(0x84, 0x14c); u16(0x86, 1); u16(0x94, 224)
            optional = 0x98; u16(optional, 0x10b); u32(optional + 92, 16)
            u32(optional + 112, 0x1000); u32(optional + 116, 512)
            section = optional + 224
            for at, value in ((8, 512), (12, 0x1000), (16, 512), (20, 512)):
                u32(section + at, value)
            res = 512
            for at, identity, child in ((0, 16, 0x80000020), (32, 1, 0x80000040), (64, 1033, 96)):
                u16(res + at + 14, 1); u32(res + at + 16, identity); u32(res + at + 20, child)
            u32(res + 96, 0x1080); u32(res + 100, 92)
            data = res + 128; u16(data, 92); u16(data + 2, 52)
            key = 'VS_VERSION_INFO'.encode('utf-16-le'); raw[data + 6:data + 6 + len(key)] = key
            for at, value in ((40, 0xfeef04bd), (44, 0x10000), (48, 0x30003), (52, 0x53034)):
                u32(data + at, value)
            return raw

        def archive_source(root, destination):
            with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_STORED) as outgoing:
                for path in sorted(root.rglob('*')):
                    if path.is_file(): outgoing.write(path, path.relative_to(root).as_posix())
            return destination

        def inventory(root):
            return {path.relative_to(root).as_posix().casefold(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in root.rglob('*') if path.is_file()}

        (self.source / 'Wow.exe').write_bytes(pe_fixture())
        for name in ('common-2', 'common-3', 'expansion', 'lichking', 'patch', 'patch-2', 'patch-3'):
            self.archive('Data/' + name + '.MPQ', {})
        self.archive('Data/enUS/patch-enUS-3.MPQ', {})
        ancillary = ('Data/wow-update-base-12340.MPQ', 'Installer.MPQ', 'Data/installer.MPQ/help.txt')
        for name in ancillary: self.ancillary(name)
        wrapped_root = self.root / 'wrapped'; wrapped_root.mkdir()
        shutil.copytree(self.source, wrapped_root / 'ChromieCraft')
        (wrapped_root / 'README.txt').write_text('Client is inside ChromieCraft')
        metadata = wrapped_root / '__MACOSX/ChromieCraft/Data/._common.MPQ'
        metadata.parent.mkdir(parents=True); metadata.write_bytes(b'ignored ZIP metadata')
        mixed = self.root / 'mixed'; shutil.copytree(self.source, mixed)
        (mixed / 'Wow.exe').rename(mixed / 'wOw.ExE'); (mixed / 'Data').rename(mixed / 'dAtA')
        (mixed / 'dAtA/enUS').rename(mixed / 'dAtA/eNuS')
        (mixed / 'dAtA/common.MPQ').rename(mixed / 'dAtA/CoMmOn.mPq')
        (mixed / 'dAtA/eNuS/locale-enUS.MPQ').rename(mixed / 'dAtA/eNuS/LoCaLe-EnUs.mPq')
        reference, runs = None, []
        for label, original in (('direct', self.source), ('wrapped-with-metadata', wrapped_root), ('mixed-case', mixed)):
            zip_path = archive_source(original, self.root / (label + '.zip'))
            for route, input_path in (('folder', original), ('zip', zip_path)):
                with self.subTest(layout=label, route=route):
                    store = self.root / (label + '-' + route + '-store')
                    imported = java(route, store, input_path)
                    imported_before = inventory(imported)
                    generation = imported.parent.name
                    report = stock.inspect(imported, self.tools, stock.CLIENT_REVISION, 'enUS', generation)
                    self.assertTrue(report['passed'], report['errors'])
                    self.assertEqual({row['path'].casefold() for row in report['exclusions']},
                                     {name.casefold() for name in ancillary})
                    self.assertNotIn('__macosx/chromiecraft/data/._common.mpq', imported_before)
                    decisions = self.root / (label + '-' + route + '-exclusions.tsv')
                    decisions.write_text(''.join(base64.b64encode(row['path'].encode()).decode() + '\t' +
                        row['sha256'] + '\n' for row in report['exclusions']))
                    selected = java('select', store, imported, decisions,
                        hashlib.sha256(stock.storage.encoded(report)).hexdigest())
                    self.assertNotEqual(selected, imported)
                    self.assertEqual(inventory(imported), imported_before, 'original imported generation retained')
                    self.assertTrue(all(name.casefold() not in inventory(selected) for name in ancillary))
                    selected_report = stock.inspect(selected, self.tools, stock.CLIENT_REVISION, 'enUS', selected.parent.name)
                    self.assertTrue(selected_report['passed'], selected_report['errors'])
                    self.assertEqual(selected_report['exclusions'], [])
                    projected = inventory(selected)
                    if reference is None: reference = projected
                    else: self.assertEqual(projected, reference, 'folder/ZIP/wrapper/case projection equivalence')
                    manifest = stock.order.plan(selected, 'enUS', profile=dict(classical=True, trial=False,
                        streaming=False, directAccess=False, retailVirtualProviders=False,
                        parentDataVisible=False, installDataVisible=False))
                    self.assertEqual({row['path'].casefold() for row in manifest['providers']},
                                     {row['path'].casefold() for row in selected_report['providers']})
                    runs.append({'layout': label, 'route': route, 'importedFiles': len(imported_before),
                        'selectedFiles': len(projected), 'providers': len(report['providers']),
                        'clientDbcs': len(report['checks']['clientDbcs']), 'exclusions': len(report['exclusions'])})
        self.assertEqual(len(runs), 6)
        # A real active overlay is imported and reaches inspection, where it is
        # refused; it is not silently treated like the ancillary update archive.
        self.archive('Data/patch-Unknown.MPQ', {'Interface\\Icons\\Generic.blp': b'unclassified'})
        unknown_zip = archive_source(self.source, self.root / 'unknown.zip')
        for route, input_path in (('folder', self.source), ('zip', unknown_zip)):
            imported = java(route, self.root / ('unknown-' + route + '-store'), input_path)
            report = stock.inspect(imported, self.tools, stock.CLIENT_REVISION, 'enUS', imported.parent.name)
            self.assertFalse(report['passed'])
            self.assertEqual(report['unknownOverlays'][0]['path'], 'Data/patch-Unknown.MPQ')
            self.assertTrue((imported / 'Data/patch-Unknown.MPQ').exists())
        if os.environ.get('ESTERIA_STOCK_PIPELINE_EVIDENCE'):
            Path(os.environ['ESTERIA_STOCK_PIPELINE_EVIDENCE']).write_bytes(stock.storage.encoded({
                'scope': 'host Java public importer to exact client reader over encrypted synthetic MPQs',
                'clientRevision': stock.CLIENT_REVISION, 'routes': runs, 'unknownOverlayRoutesRejected': 2,
                'ownerClientData': False, 'androidExecution': False, 'worldEntry': False}))

    def test_compact_table_rows_members_locales_and_compressed_v1_match_pinned_reader(self):
        compact = stock.compact_mpq_class(self.reader)
        for compressed in (False, True):
            path = self.root / ('tables-' + str(compressed) + '.MPQ')
            members = [('sample.bin', b'neutral', 0), ('sample.bin', b'localized', 0x409),
                       ('other.bin', b'other payload', 0)]
            self.make_mpq(path, members, compressed=compressed)
            for high_words in (False, True) if compressed else (False,):
                if high_words:
                    raw = bytearray(path.read_bytes())
                    count = struct.unpack_from('<I', raw, 28)[0]
                    struct.pack_into('<Q', raw, 32, len(raw)); raw.extend(b'\0' * (2 * count))
                    path.write_bytes(raw)
                for locale in (0, 0x409, 0x40c):
                    original, packed = self.reader.mq.MPQ(path, locale), compact(path, locale)
                    try:
                        self.assertEqual(list(original.hash_table), list(packed.hash_table))
                        self.assertEqual(list(original.block_table), list(packed.block_table))
                        self.assertIsInstance(packed.hash_table, stock.PackedTable)
                        for name in ('sample.bin', 'other.bin', '(listfile)', 'absent.bin'):
                            self.assertEqual(original.find(name), packed.find(name))
                            self.assertEqual(original.read_file(name), packed.read_file(name))
                    finally:
                        original.close(); packed.close()

    def test_inplace_table_cipher_matches_pinned_decoder_including_partial_words(self):
        import io
        from types import SimpleNamespace
        for size in (0, 1, 3, 4, 5, 64, 4099):
            raw = bytes((i * 131 + 17) & 255 for i in range(size))
            for key in (0, 0xffffffff, self.reader.mq.hash_string('(hash table)', 3)):
                archive = SimpleNamespace(f=io.BytesIO(raw), path='synthetic-table')
                self.assertEqual(stock.read_decrypted_table(archive, len(raw), key, self.reader.mq.CT),
                                 self.reader.mq.decrypt(raw, key))
                if size:
                    with patch.object(stock.sys, 'byteorder', 'big'):
                        archive.f.seek(0)
                        self.assertEqual(stock.read_decrypted_table(archive, len(raw), key, self.reader.mq.CT),
                                         self.reader.mq.decrypt(raw, key))
        with self.assertRaisesRegex(ValueError, 'truncated MPQ data'):
            stock.read_decrypted_table(SimpleNamespace(f=io.BytesIO(b'x'), path='short'), 4, 0, self.reader.mq.CT)

    def test_table_bounds_fail_before_retained_growth_and_bad_headers_before_decode(self):
        with patch.object(stock, 'MAX_TABLE_ENTRIES', 1):
            with self.assertRaisesRegex(ValueError, 'memory bound before retaining'):
                self.inspect()
        compact = stock.compact_mpq_class(self.reader)
        path = self.root / 'bad-tables.MPQ'
        self.make_mpq(path, [('sample', b'payload', 0)])
        good = path.read_bytes()
        cases = []
        for at, value in ((24, 3), (24, self.reader.mq.MAX_TABLE_ENTRIES + 1), (16, 0), (20, 0)):
            raw = bytearray(good); struct.pack_into('<I', raw, at, value); cases.append(raw)
        cases.append(good[:-2])
        for raw in cases:
            path.write_bytes(raw)
            with patch.object(stock, 'read_decrypted_table') as decode:
                with self.assertRaises(ValueError):
                    stock.preflight_tables([path], self.reader, 'enUS')
                decode.assert_not_called()
            with self.assertRaises(ValueError) as original:
                self.reader.mq.MPQ(path, 0)
            with self.assertRaises(ValueError) as packed:
                compact(path, 0)
            self.assertEqual(str(packed.exception), str(original.exception))

    def test_stored_member_length_is_bounded_before_payload_read(self):
        from unittest.mock import Mock
        path = self.root / 'huge-stored-member.MPQ'
        self.make_mpq(path, [('sample.bin', b'x', 0)])
        raw = bytearray(path.read_bytes())
        original = self.reader.mq.MPQ(path, 0)
        try:
            index, start, count = original.find('sample.bin'), original.block_table_pos, original.block_table_size
        finally:
            original.close()
        blocks = bytearray(self.reader.mq.decrypt(raw[start:start + count * 16],
            self.reader.mq.hash_string('(block table)', 3)))
        struct.pack_into('<I', blocks, index * 16 + 4, 1 << 28)
        raw[start:start + count * 16] = self.encrypt_table(blocks, self.reader.mq.hash_string('(block table)', 3))
        physical_size = (1 << 28) + 4096
        struct.pack_into('<I', raw, 8, physical_size)
        with path.open('wb') as output:
            output.write(raw); output.truncate(physical_size)  # sparse fixture, no large allocation
        packed = stock.compact_mpq_class(self.reader)(path, 0)
        real_file = packed.f
        packed.f = Mock(wraps=real_file)
        try:
            with self.assertRaisesRegex(ValueError, 'bounded member and sector-table limit'):
                packed.read_file('sample.bin')
            packed.f.read.assert_not_called()
        finally:
            packed.close()

    def test_compact_stack_keeps_stock_optional_and_unknown_reports_identical(self):
        for state in ('stock', 'identified-optional', 'unknown-active'):
            if state == 'identified-optional':
                self.archive('Data/patch-renamed.MPQ', {'Esteria\\EsteriaNaga.bin':
                    struct.pack('<3I', 0x314D4845, 1, 0), 'DBFilesClient\\ChrRaces.dbc': b'excluded'})
            elif state == 'unknown-active':
                self.archive('Data/patch-Unknown.MPQ', {'Interface\\Icons\\Generic.blp': b'unknown'})
            compact_report = self.inspect()
            with patch.object(stock, 'compact_mpq_class', lambda reader: reader.mq.MPQ):
                original_report = self.inspect()
            self.assertEqual(compact_report, original_report, state)
            self.assertEqual(len(compact_report['checks']['clientDbcs']), 238)
            self.assertEqual(compact_report['passed'], state != 'unknown-active')

    def test_active_folder_provider_members_are_not_mistaken_for_ancillary(self):
        self.ancillary('Data/patch-folder.MPQ/inner.MPQ')
        pins = stock.importer_pins(self.source, self.generation)
        self.assertEqual(stock.ancillary_archives(self.source, pins), [])
        with self.assertRaisesRegex(ValueError, 'requires regular archive providers.*Data/patch-folder.MPQ'):
            self.inspect()

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
