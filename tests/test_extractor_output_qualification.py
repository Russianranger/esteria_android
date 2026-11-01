"""Admission fixtures only; genuine shipped-ELF execution is the ARM64 job."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools import qualify_extractor_output as q


class OutputReceiptAdmission(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.revision = '8' * 40
        pin = q.provider.load_pin(sealed=True)
        image = dict(formatVersion=1, scope='native-arm64-dependency-image-readback',
            runtimeArchive=pin['requiredServerRuntimeArchive'], actualImageMetadataAndElfHashesVerified=True,
            nativePythonExecuted=True, mysqlServerExecuted=False, databaseInitialized=False,
            esteriaServerExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
        path = self.root / 'dependency-image-check.json'
        path.write_text(json.dumps(image))
        old = b'Extracting dbc files...\nFatal Error: Could not create directory ' + b'a' * 127 + b'/dbc/ check your permissions'
        logs = dict(legacyAbsolute=old, relativeFresh=b'Extracting dbc files...\nExtracted 4 DBC files\nExtracting maps...\n',
            relativeExisting=b'Extracting dbc files...\nExtracted 1 DBC files\nExtracting maps...\n')
        for name, raw in logs.items():
            (self.root / (name + '.log')).write_bytes(raw)
        cases = dict(legacyAbsolute=dict(exitStatus=1, outputArgumentBytes=180, truncatedArgumentBytes=127,
            equivalentMkdirErrno=2, nativeTruncatedPathErrorMatched=True, intendedOutputAbsent=True,
            log=q.identity(self.root / 'legacyAbsolute.log')))
        for name in ('relativeFresh', 'relativeExisting'):
            cases[name] = dict(exitStatus=0, outputOperand='.', cwdBytes=180, outputs=q.expected_outputs(),
                outputDirectories=['Cameras', 'dbc', 'maps'], inputBytesUnchanged=True,
                misdirectedDirectoryAbsent=True, log=q.identity(self.root / (name + '.log')))
        self.value = dict(formatVersion=1, scope=q.SCOPE, appRevision=self.revision,
            providerInputLock=q.identity(q.provider.LOCK), runtimeArchive=q.provider.identity(pin['archive']),
            shippedMapExtractor=q.provider.identity(pin['files']['bin/map_extractor']),
            sourceIdentities={name: q.identity(q.ROOT / name) for name in q.SOURCES},
            referenceImageReadback=dict(identity=q.identity(path), receipt=image),
            fixtureInputs=q.expected_inputs(), expectedOutputs=q.expected_outputs(), cases=cases,
            productionExecuteAndMemoryPolicyUsed=True, **{name: False for name in q.FALSE_FLAGS})

    def write_receipt(self, value=None):
        (self.root / 'native-output.json').write_text(json.dumps(value or self.value))

    def test_closed_receipt_and_retained_logs_are_admitted_without_execution_claim_from_test(self):
        self.write_receipt()
        self.assertEqual(q.verify_result(self.root, self.revision), self.value)
        self.assertEqual(len(self.value['expectedOutputs']), 5)
        self.assertFalse(self.value['mapTilesConverted'])

    def test_missing_case_boolean_exit_long_operand_and_wrong_directory_are_refused(self):
        mutations = [
            lambda v: v['cases'].pop('legacyAbsolute'),
            lambda v: v['cases']['relativeFresh'].update(exitStatus=False),
            lambda v: v['cases']['legacyAbsolute'].update(outputArgumentBytes=127),
            lambda v: v['cases']['relativeFresh'].update(outputOperand='/long/absolute/path'),
            lambda v: v['cases']['relativeExisting'].update(outputDirectories=['dbc']),
            lambda v: v['cases']['legacyAbsolute'].update(equivalentMkdirErrno=13),
            lambda v: v['cases']['relativeExisting'].update(misdirectedDirectoryAbsent=False),
        ]
        for change in mutations:
            value = copy.deepcopy(self.value); change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                q.verify_receipt(value, self.revision)

    def test_changed_source_provider_elf_input_and_output_hashes_are_refused(self):
        for target in ('source', 'provider', 'elf', 'input', 'output'):
            value = copy.deepcopy(self.value)
            if target == 'source': value['sourceIdentities']['runtime/server_data_generation.py']['sha256'] = '0' * 64
            elif target == 'provider': value['providerInputLock']['sha256'] = '0' * 64
            elif target == 'elf': value['shippedMapExtractor']['sha256'] = '0' * 64
            elif target == 'input': value['fixtureInputs']['Data/common.MPQ']['sha256'] = '0' * 64
            else: value['cases']['relativeFresh']['outputs']['dbc/Map.dbc']['sha256'] = '0' * 64
            with self.subTest(target=target), self.assertRaises(ValueError):
                q.verify_receipt(value, self.revision)

    def test_qualification_boundary_extra_fields_and_foreign_source_are_refused(self):
        for name in q.FALSE_FLAGS:
            value = copy.deepcopy(self.value); value[name] = True
            with self.subTest(name=name), self.assertRaises(ValueError):
                q.verify_receipt(value, self.revision)
        for change in (lambda v: v.update(extra=True), lambda v: v.update(formatVersion=True),
                       lambda v: v.update(productionExecuteAndMemoryPolicyUsed=False)):
            value = copy.deepcopy(self.value); change(value)
            with self.assertRaises(ValueError): q.verify_receipt(value, self.revision)
        with self.assertRaises(ValueError): q.verify_receipt(self.value, '9' * 40)

    def test_changed_retained_log_even_with_relabelled_hash_and_extra_members_refuse(self):
        self.write_receipt()
        path = self.root / 'relativeFresh.log'; path.write_bytes(b'usage only')
        self.value['cases']['relativeFresh']['log'] = q.identity(path); self.write_receipt()
        with self.assertRaisesRegex(ValueError, 'conversion-log'):
            q.verify_result(self.root, self.revision)
        (self.root / 'extra').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'roster'):
            q.verify_result(self.root, self.revision)


@unittest.skipUnless(os.environ.get('ESTERIA_EXTRACTOR_SOURCE'),
    'exact libmpq host bridge is optional; real shipped-ELF conversion is mandatory in the native job')
class SyntheticMpqBridge(unittest.TestCase):
    def test_tiny_encrypted_table_fixture_is_read_by_the_original_libmpq_bridge(self):
        from tests.test_extractor_order import RealArchiveReader
        RealArchiveReader.setUpClass()
        self.addCleanup(RealArchiveReader.tearDownClass)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); game = root / 'inputs'; (game / 'Data/enUS').mkdir(parents=True)
            for name, members in (('Data/common.MPQ', q.fixture_members()),
                    ('Data/enUS/locale-enUS.MPQ', {}), ('Data/enUS/speech-enUS.MPQ', {})):
                (game / name).write_bytes(q.synthetic_mpq(members))
            wire = q.data.order.wire(q.data.order.plan(game, 'enUS', profile=q.data.PROFILE))
            path = root / 'order.tsv'; path.write_bytes(wire)
            for name, expected in q.fixture_members().items():
                result = subprocess.run([str(RealArchiveReader.executable), '--esteria-order', str(path),
                    '--esteria-input-root', str(game), '--esteria-order-sha256', hashlib.sha256(wire).hexdigest(),
                    '--esteria-order-probe', name], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                self.assertEqual(value['bytes'], len(expected))
                self.assertEqual(value['sha256'], hashlib.sha256(expected).hexdigest())


if __name__ == '__main__':
    unittest.main()
