"""Native gates, partial/final separation and actual debug-pair fixture checks."""
import contextlib
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_server_data_tools as qualify
from tests import test_package_server_data_tools as elf_fixtures


def identity(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class DataToolQualificationGuards(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='data-tool-cli-guards-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def test_non_native_cli_and_lookup_refuse_before_outputs(self):
        with patch.object(qualify.platform, 'machine', return_value='x86_64'):
            with self.assertRaisesRegex(ValueError, 'native-arm64'):
                qualify.cli(self.root, '0'*64, self.root/'cli')
            with self.assertRaisesRegex(ValueError, 'native-arm64'):
                qualify.lookup(self.root, '0'*64, self.root/'phase', '1'*64, self.root/'source', self.root/'lookup')
        self.assertFalse((self.root/'cli').exists()); self.assertFalse((self.root/'lookup').exists())

    def test_external_package_or_phase_sha_is_required_and_never_rebound(self):
        path = self.root/'receipt.json'; path.write_bytes(b'{"fixture":true}\n')
        expected = qualify.files.identity(path)['sha256']
        value, row = qualify.expected_receipt(path, expected)
        self.assertEqual(value, dict(fixture=True)); self.assertEqual(row['sha256'], expected)
        path.write_bytes(b'{"fixture":false}\n')
        with self.assertRaisesRegex(ValueError, 'sha256-differs'): qualify.expected_receipt(path, expected)
        for missing in (None, '', 'not-exact', 'A'*64):
            with self.assertRaisesRegex(ValueError, 'external-exact'): qualify.expected_receipt(path, missing)

    def test_fresh_output_refuses_existing_and_overlapping_input(self):
        existing = self.root/'existing'; existing.mkdir(); (existing/'keep').write_bytes(b'kept')
        with self.assertRaisesRegex(ValueError, 'output-exists-or-overlaps'):
            qualify.fresh_output(existing, ())
        with self.assertRaisesRegex(ValueError, 'output-exists-or-overlaps'):
            qualify.fresh_output(existing/'inside', (existing,))
        self.assertEqual((existing/'keep').read_bytes(), b'kept')

    def test_installed_file_modes_and_byte_identities_are_both_checked(self):
        install = self.root/'install'; install.mkdir(); path = install/'source.txt'; path.write_bytes(b'exact data')
        path.chmod(0o444); row = dict(qualify.files.identity(path), mode=0o444)
        verified = dict(receipt=dict(archiveFiles={'source.txt': row}))
        qualify.verify_install(install, verified); path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'installed-file-mode-changed'): qualify.verify_install(install, verified)
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'input-file-changed'): qualify.verify_install(install, verified)

    def phase_fixture(self):
        original, _ = qualify.original_cli.load_pin()
        programs = {name: dict(original=identity(b'old '+name.encode()), stripped=identity(name.encode()),
                              debug=identity(b'debug '+name.encode())) for name in qualify.package.PROGRAMS}
        config = identity(b'original yaml'); sid = identity(b'raw source seal'); rid = identity(b'raw composed package')
        required_runtime = qualify.package.stock.load_pin()['requiredServerRuntimeArchive']
        verified = dict(receiptIdentity=rid, receipt=dict(archive=identity(b'archive'), orderedSourceReceipt=sid,
            programPairs=programs), selected=dict(configuration=config, requiredServerRuntimeArchive=required_runtime))
        image = dict(formatVersion=1, scope='native-arm64-dependency-image-readback', runtimeArchive=required_runtime,
            actualImageMetadataAndElfHashesVerified=True, nativePythonExecuted=True,
            mysqlServerExecuted=False, databaseInitialized=False, esteriaServerExecuted=False,
            androidRuntimeQualified=False, gameplayQualified=False)
        cap = qualify.ordered.adaptation.load_pin()['contract']+qualify.ordered.CAPABILITY_SUFFIX+'\n'
        phase = dict(formatVersion=1, scope='native-arm64-composed-server-data-tools-cli-phase', phase='complete',
            qualificationSucceeded=True, originalStockConfigParsed=True, nativeOrderedLookupsQualified=False,
            emptyWorkingDirectoriesUnchanged=True, derivativeLoadedSegmentsAndDebugLinkVerified=True,
            packageReceipt=rid, runtimeArchive=identity(b'archive'), orderedSourceReceipt=sid,
            programs={n: r['stripped'] for n, r in programs.items()}, configuration=config,
            cases={r['name']: dict(exitCode=r['exitCode'], output='\n'.join(r['contains'])) for r in original['cliCases']},
            capabilities={name: dict(exitCode=0, output=cap) for name in qualify.package.ORDERED},
            referenceImageReadback=dict(identity=identity(json.dumps(image).encode()), receipt=image),
            **{name: False for name in qualify.package.FALSE_FLAGS})
        return phase, verified

    def test_reference_image_check_requires_external_sha_exact_archive_and_fresh_boundary(self):
        phase, verified = self.phase_fixture(); image = phase['referenceImageReadback']['receipt']
        path = self.root/'image-check.json'; path.write_text(json.dumps(image))
        accepted = qualify.accept_image_readback(path, qualify.files.identity(path)['sha256'], verified['selected'])
        self.assertEqual(accepted['receipt'], image)
        with self.assertRaisesRegex(ValueError, 'sha256-differs'):
            qualify.accept_image_readback(path, '0'*64, verified['selected'])
        for changed in (dict(mysqlServerExecuted=True), dict(nativePythonExecuted=False),
                        dict(runtimeArchive=dict(image['runtimeArchive'], sha256='0'*64))):
            invalid = copy.deepcopy(accepted); invalid['receipt'].update(changed)
            with self.assertRaisesRegex(ValueError, 'scope-or-boundary'):
                qualify.verify_image_binding(invalid, verified['selected'])

    def test_capability_and_cli_phase_cannot_claim_lookup_qualification(self):
        phase, verified = self.phase_fixture(); path = self.root/'phase.json'
        def save():
            path.write_text(json.dumps(phase)); return qualify.files.identity(path)['sha256']
        qualify.verify_phase(path, save(), verified)
        phase['nativeOrderedLookupsQualified'] = True
        with self.assertRaisesRegex(ValueError, 'complete-bound-cli-phase-required'):
            qualify.verify_phase(path, save(), verified)
        phase['nativeOrderedLookupsQualified'] = False; phase['cases'].pop(next(iter(phase['cases'])))
        with self.assertRaisesRegex(ValueError, 'all-original-cli-cases-required'):
            qualify.verify_phase(path, save(), verified)

    def test_partial_result_missing_skipped_or_expected_failures_never_suffices(self):
        valid = dict(scope='actual-ordered-reader-unittest-result', testNames=['fixture.test_a'], expectedTests=1,
            testsRun=1, failures=0, errors=0, skipped=0, expectedFailures=0, unexpectedSuccesses=0, wasSuccessful=True)
        qualify.verify_suite_result(valid)
        for changes in (dict(testsRun=0), dict(skipped=1), dict(failures=1), dict(errors=1), dict(expectedFailures=1),
                        dict(unexpectedSuccesses=1), dict(testNames=[]), dict(expectedTests=True), dict(wasSuccessful=False)):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, 'all-actual-reader-tests'):
                qualify.verify_suite_result(dict(valid, **changes))

    def test_typed_runner_counts_actual_host_unittest_execution_and_retains_refusals(self):
        class Passing(unittest.TestCase):
            def test_real_assertion(self): self.assertEqual(2+2, 4)
        class Skipped(unittest.TestCase):
            @unittest.skip('fixture refusal')
            def test_skipped(self): pass
        with contextlib.redirect_stderr(io.StringIO()):
            result = qualify.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Passing), self.root/'pass.json')
            self.assertEqual(result['testsRun'], 1); self.assertEqual(result['skipped'], 0)
            with self.assertRaisesRegex(ValueError, 'all-actual-reader-tests'):
                qualify.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(Skipped), self.root/'skip.json')
        self.assertEqual(json.loads((self.root/'skip.json').read_text())['skipped'], 1)
        self.assertFalse((self.root/qualify.FINAL_RECEIPT).exists())


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact local NDK ELF fixture not supplied')
class ActualDerivedDebugReadback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = elf_fixtures.RealOrderedPairDerivation
        cls.fixture.setUpClass()

    @classmethod
    def tearDownClass(cls): cls.fixture.tearDownClass()

    def test_actual_cross_compiled_pair_segments_crc_and_changed_debug_are_checked(self):
        with tempfile.TemporaryDirectory(dir=self.fixture.root) as name:
            root = Path(name); install = root/'install'; debug = root/'debug'; (install/'bin').mkdir(parents=True)
            (debug/'symbols').mkdir(parents=True)
            pairs = qualify.package.derive_ordered(self.fixture.payload, install, debug, self.fixture.objcopy,
                self.fixture.tool, self.fixture.expected)
            inventory = qualify.engine.write_archive(debug, root/qualify.package.DEBUG)
            verified = dict(strip=dict(programs=pairs, debugInventory=inventory))
            extracted = root/'extracted'; extracted.mkdir()
            qualify.verify_derived_debug(root, install, verified, extracted)
            self.assertEqual({p.name for p in extracted.iterdir()}, {n+'.debug' for n in qualify.package.ORDERED})
            changed = copy.deepcopy(verified)
            changed['strip']['programs'][qualify.package.ORDERED[0]]['loadedSegments'][0]['sha256'] = '0'*64
            other = root/'refused'; other.mkdir()
            with self.assertRaisesRegex(ValueError, 'loaded-segments-or-debug-sections-differ'):
                qualify.verify_derived_debug(root, install, changed, other)
            self.assertFalse((root/qualify.FINAL_RECEIPT).exists())


if __name__ == '__main__': unittest.main()
