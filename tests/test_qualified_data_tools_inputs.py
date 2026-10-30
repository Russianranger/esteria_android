"""Qualified data4 input closure and failure-before-output preservation."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import prepare_data_tools_provider as inputs
from tools import measure_server_data_tools as measure


class QualifiedDataToolsInputs(unittest.TestCase):
    def test_exact_artifacts_select_only_qualified_runtime_source_debug_and_native_receipts(self):
        pin=inputs.load_pin()
        self.assertEqual(pin['providerInputLock'],inputs.files.identity(inputs.provider.LOCK))
        package=pin['artifacts']['package'];native=pin['artifacts']['native']
        self.assertEqual(package['workflowRun'],41103915829)
        self.assertEqual(len(package['members']),10);self.assertEqual(len(native['members']),3)
        self.assertEqual(package['members']['data-tools-package/server-data-tools-runtime-arm64.tar.gz']['sha256'],
            inputs.provider.load_pin(sealed=True)['archive']['sha256'])
        self.assertNotIn('worldserver', '\n'.join(package['members']))

    def test_mutated_provider_binding_or_duplicate_or_foreign_target_refuse(self):
        pin=inputs.load_pin()
        with tempfile.TemporaryDirectory() as name:
            lock=Path(name)/'lock.json'
            for change in ('provider','duplicate','unsafe','scope'):
                invalid=copy.deepcopy(pin)
                if change=='provider':invalid['providerInputLock']['sha256']='0'*64
                elif change=='scope':invalid['gameplayQualified']=True
                else:
                    rows=list(invalid['artifacts']['package']['members'].values())
                    rows[0]['target']=rows[1]['target'] if change=='duplicate' else '../foreign'
                lock.write_text(json.dumps(invalid))
                with self.subTest(change=change),patch.object(inputs,'LOCK',lock),self.assertRaises(ValueError):inputs.load_pin()

    def test_failed_build_preserves_existing_output_before_creating_provider(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);source=root/'missing-inputs';source.mkdir();out=root/'saves';out.mkdir()
            (out/'keep').write_bytes(b'persistent')
            with self.assertRaises((ValueError,FileNotFoundError)):inputs.build(source,out)
            self.assertEqual((out/'keep').read_bytes(),b'persistent')
            self.assertEqual({p.name for p in out.iterdir()},{'keep'})

    def test_measurement_never_accepts_implicit_package_or_native_receipt_hash(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/'receipt.json';path.write_text('{}')
            for expected in (None,'','floating','A'*64):
                with self.subTest(expected=expected),self.assertRaisesRegex(ValueError,'external-exact'):
                    measure.qualify.expected_receipt(path,expected)

if __name__=='__main__':unittest.main()
