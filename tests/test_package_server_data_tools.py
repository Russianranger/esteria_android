"""Composition/refusal tests; tiny ELF fixtures are compiled, never executed."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import package_server_data_tools as package


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.chmod(0o600)
    path.write_bytes(raw)
    return identity(raw)


class DataToolGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='data-tools-package-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def test_pending_real_source_anchor_refuses_before_output_or_tool_execution(self):
        pin = json.loads(package.provider.LOCK.read_text())
        pin.update(state='pending-ordered-source-and-derived-native-cli', actualOrderedSourceQualification=None,
                   sourceCompanionComplete=False, nativeArgumentConfigQualified=False, originalNoticesPreserved=False)
        for name in ('archive', 'archiveEntries', 'archiveFileBytes', 'packageReceipt', 'programPairs',
                     'nativeCliReceipt', 'files', 'toolSelection'): pin[name] = None
        lock = self.root/'pending.lock.json'; lock.write_text(json.dumps(pin))
        output = self.root/'not-created'/'package'
        with patch.object(package.provider, 'LOCK', lock), \
             patch.object(package.engine.elf, 'verify_tool') as tool, \
             patch.object(package.engine.elf, 'derive') as derive:
            with self.assertRaisesRegex(ValueError, 'real-ordered-source-qualification-required'):
                package.build(self.root/'payload', self.root/'sources', self.root/'stock',
                              self.root/'ndk.zip', self.root/'objcopy', output)
        tool.assert_not_called(); derive.assert_not_called(); self.assertFalse(output.parent.exists())

    def test_existing_output_is_preserved_before_any_input_derivation(self):
        output = self.root/'preserved'; output.mkdir(); marker = output/'keep'; marker.write_bytes(b'kept')
        roots = [self.root/name for name in ('payload', 'sources', 'stock')]
        for path in roots: path.mkdir()
        # Only the negative fresh-output boundary is exercised; no fixture is
        # promoted to a positive source, stock package or native qualification.
        with patch.object(package.provider, 'load_source_qualification', return_value={}), \
             patch.object(package.sources, 'load_pin', return_value={}), \
             patch.object(package.stock, 'load_pin', return_value={}), \
             patch.object(package.engine.elf, 'derive') as derive:
            with self.assertRaisesRegex(ValueError, 'output-exists-or-overlaps'):
                package.build(*roots, self.root/'ndk', self.root/'objcopy', output)
        derive.assert_not_called(); self.assertEqual(marker.read_bytes(), b'kept')

    def test_boolean_only_source_receipt_and_changed_output_anchor_refuse(self):
        directory = self.root/'ordered-sources'; directory.mkdir()
        archive = directory/package.SOURCE_ARCHIVE; archive.write_bytes(b'not a qualified source archive')
        qualified_identity = identity(b'raw native receipt'); observed = identity(b'raw observed graph')
        measured = dict(nativeBuild=dict(receipt=qualified_identity, dependencyObservation=observed))
        sealed = dict(formatVersion=1, scope='complete-ordered-extractor-corresponding-source-companion')
        for flag in ('archiveReadbackVerified', 'orderedSourceCompanionComplete', 'originalNativeReceiptUnchanged',
                     'fullBaseAndApprovedOverlayVerified', 'actualTargetDependencyObservationVerified',
                     'integrationRecipesAllReadFromNativeGitBlobs'): sealed[flag] = True
        for flag in ('newNativeCompilationPerformed', 'globalServerPatchListChanged', 'serverProgramsReplaced',
                     'worldQualified', 'androidRuntimeQualified', 'clientMpqConversionQualified',
                     'customEsteriaDataLoadOrderQualified', 'gameplayQualified', 'originalNativeSourceCompanionComplete'):
            sealed[flag] = False
        receipt_identity = write(directory/package.SOURCE_RECEIPT, json.dumps(sealed).encode())
        anchor = dict(archive=package.files.identity(archive), receipt=receipt_identity,
                      nativeBuild=qualified_identity, dependencyObservation=observed)
        with self.assertRaisesRegex(ValueError, 'native-or-original-binding'):
            package.verify_ordered_sources(directory, dict(actualOrderedSourceQualification=anchor), measured, {}, qualified_identity)
        archive.write_bytes(b'changed source archive')
        with self.assertRaisesRegex(ValueError, 'source-anchor-changed'):
            package.verify_ordered_sources(directory, dict(actualOrderedSourceQualification=anchor), measured, {}, qualified_identity)

    def test_six_selected_files_bind_both_revisions_yaml_and_raw_source_receipt(self):
        runtime = self.root/'runtime'; source_id = write(runtime/'provenance'/package.SOURCE_RECEIPT, b'raw source receipt')
        for name in package.PROGRAMS: write(runtime/'bin'/name, ('selected fixture '+name).encode())
        config_id = write(runtime/package.CONFIG, b'exact original config\n')
        selected = dict(configuration=config_id, serverRevision='a'*40, clientRevision='b'*40)
        selection = package.tool_selection(selected, runtime, source_id)
        self.assertEqual(set(selection['files']), {'bin/'+name for name in package.PROGRAMS} |
                         {package.CONFIG, 'provenance/'+package.SOURCE_RECEIPT})
        self.assertEqual(selection['serverRevision'], 'a'*40); self.assertEqual(selection['clientRevision'], 'b'*40)
        self.assertEqual(selection['orderedSourceReceipt'], source_id)
        write(runtime/package.CONFIG, b'changed configuration')
        with self.assertRaisesRegex(ValueError, 'source-receipt-or-yaml-selection'):
            package.tool_selection(selected, runtime, source_id)

    def test_full_creation_recipe_snapshot_retains_own_code_tool_pins_and_integration_license(self):
        recipes = package.recipe_files()
        required = {'tools/package_server_data_tools.py', 'tests/test_package_server_data_tools.py',
            'tools/server_engine_elf.py', 'tools/owned_process_group.py', 'runtime/server/engine-strip.lock.json',
            'runtime/server/ordered-tools-inputs.lock.json', 'runtime/server/data-tools-provider.lock.json',
            'runtime/server/extractors-provider.lock.json', 'sources.lock.json', 'LICENSE'}
        self.assertTrue(required <= recipes.keys())
        self.assertFalse(any(name.startswith('runtime/evidence/') or '.git' in Path(name).parts for name in recipes))
        self.assertEqual(recipes['LICENSE'][1], package.INTEGRATION_LICENSE)
        for path, row in recipes.values(): self.assertEqual(package.files.identity(path), row)


class StockComposition(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='data-tool-stock-copy-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name); self.stock_tree = self.root/'stock'
        self.selected = dict(files={}, noticeFiles=[])
        names = {'bin/'+name for name in package.PROGRAMS} | {package.CONFIG} | package.stock.PROVENANCE
        names |= {'notices/source/LICENSE-'+str(n) for n in range(66)}
        for name in sorted(names):
            raw = ('synthetic stock bytes '+name+'\n').encode(); row = write(self.stock_tree/name, raw)
            self.selected['files'][name] = dict(row, mode=0o555 if name.startswith('bin/') else 0o444)
            (self.stock_tree/name).chmod(self.selected['files'][name]['mode'])
            if name.startswith('notices/'): self.selected['noticeFiles'].append(name)
        self.archive = self.root/'stock.tar.gz'; package.engine.write_archive(self.stock_tree, self.archive)

    def test_all_raw_notices_yaml_stock_pair_and_original_metadata_survive(self):
        extracted = self.root/'extracted'; package.extract_stock(self.archive, extracted, self.selected)
        runtime, debug = self.root/'runtime', self.root/'debug'
        package.copy_stock_runtime(extracted, runtime, debug, self.selected)
        self.assertEqual({p.name for p in (runtime/'bin').iterdir()}, set(package.STOCK))
        self.assertFalse((runtime/'bin/map_extractor').exists()); self.assertFalse((debug/'symbols').exists())
        self.assertEqual(package.files.identity(runtime/package.CONFIG),
                         package.identity(self.selected['files'][package.CONFIG]))
        for name in self.selected['noticeFiles']:
            for directory in (runtime, debug):
                self.assertEqual(package.files.identity(directory/name), package.identity(self.selected['files'][name]))
        for name in package.stock.PROVENANCE:
            for directory in (runtime, debug):
                self.assertEqual(package.files.identity(directory/'provenance/stock'/Path(name).name),
                                 package.identity(self.selected['files'][name]))

    def test_changed_raw_notice_and_missing_notice_are_refused(self):
        name = self.selected['noticeFiles'][0]; write(self.stock_tree/name, b'changed raw notice')
        with self.assertRaisesRegex(ValueError, 'copy-readback-mismatch'):
            package.copy_stock_runtime(self.stock_tree, self.root/'runtime', self.root/'debug', self.selected)
        broken = copy.deepcopy(self.selected); broken['noticeFiles'].pop()
        with self.assertRaisesRegex(ValueError, 'stock-notice-file-set'):
            package.copy_stock_runtime(self.stock_tree, self.root/'second-runtime', self.root/'second-debug', broken)


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact local NDK toolchain fixture not supplied')
class RealOrderedPairDerivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='data-tools-elf-fixture-')
        cls.root = Path(cls.temporary.name); cls.payload = cls.root/'payload'; (cls.payload/'bin').mkdir(parents=True)
        cls.toolchain = Path(os.environ['ESTERIA_NDK_TOOLCHAIN']).resolve(strict=True)
        cls.objcopy = cls.toolchain/'llvm-objcopy'; cls.tool = dict(executable=package.files.identity(cls.objcopy))
        cls.expected = {}
        for number, name in enumerate(package.ORDERED):
            source = cls.root/(name+'.c'); source.write_text('volatile int marker='+str(number+17)+'; void _start(void){for(;;)marker++;}\n')
            binary = cls.payload/'bin'/name
            subprocess.run([str(cls.toolchain/'clang'), '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-g',
                '-Wl,--build-id=sha1', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(source), '-o', str(binary)],
                check=True, capture_output=True, timeout=30)
            cls.expected[name] = package.files.identity(binary)

    @classmethod
    def tearDownClass(cls): cls.temporary.cleanup()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=self.root); self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name); self.runtime = self.directory/'runtime'; self.debug = self.directory/'debug'
        (self.runtime/'bin').mkdir(parents=True); (self.debug/'symbols').mkdir(parents=True)

    def test_only_ordered_pair_is_derived_and_both_loaded_bytes_and_debug_links_match(self):
        pairs = package.derive_ordered(self.payload, self.runtime, self.debug, self.objcopy, self.tool, self.expected)
        self.assertEqual(set(pairs), set(package.ORDERED))
        self.assertEqual({p.name for p in (self.runtime/'bin').iterdir()}, set(package.ORDERED))
        self.assertEqual({p.name for p in (self.debug/'symbols').iterdir()}, {name+'.debug' for name in package.ORDERED})
        for name, pair in pairs.items():
            self.assertEqual(pair['original'], self.expected[name]); self.assertTrue(pair['runtimeBytesPreserved'])
            self.assertTrue(pair['debugLinkVerified']); self.assertFalse(pair['serverExecuted'])
            self.assertEqual(package.engine.elf.verify_pair(self.payload/'bin'/name, self.runtime/'bin'/name,
                             self.debug/'symbols'/(name+'.debug')), pair)
        # Archiving the pair never puts runtime executables in its debug file.
        rows = package.engine.write_archive(self.debug, self.directory/package.DEBUG)
        self.assertEqual(set(rows), {'symbols/'+name+'.debug' for name in package.ORDERED})
        self.assertNotIn('provenance/'+package.STRIP_RECEIPT, rows)

    def test_wrong_original_identity_refuses_before_creating_either_derivative(self):
        wrong = copy.deepcopy(self.expected); wrong[package.ORDERED[0]]['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'exact-ordered-pair-selection'):
            package.derive_ordered(self.payload, self.runtime, self.debug, self.objcopy, self.tool, wrong)
        self.assertEqual(list((self.runtime/'bin').iterdir()), []); self.assertEqual(list((self.debug/'symbols').iterdir()), [])


if __name__ == '__main__': unittest.main()
