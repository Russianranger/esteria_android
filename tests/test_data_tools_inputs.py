"""Small exact transfer/selection checks; no native programs are executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import prepare_server_data_tools as inputs


class DataToolInputs(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='data-tools-inputs-')
        self.addCleanup(temp.cleanup);self.root=Path(temp.name)

    def test_real_source_artifact_matches_both_committed_output_identities(self):
        pin=inputs.provider.load_source_qualification();row=inputs.source_artifact(pin)
        self.assertEqual(set(row['members']),{inputs.sources.SOURCE_ARCHIVE,inputs.sources.RECEIPT})
        for key, name in (('archive',inputs.sources.SOURCE_ARCHIVE),('receipt',inputs.sources.RECEIPT)):
            self.assertEqual(inputs.engine.identity(row['members'][name]),pin['actualOrderedSourceQualification'][key])
        for kind in ('hash','member','target','id'):
            changed=copy.deepcopy(pin);artifact=changed['orderedSourceArtifact']
            if kind=='hash':artifact['members'][inputs.sources.SOURCE_ARCHIVE]['sha256']='0'*64
            elif kind=='member':artifact['members']['unselected']={}
            elif kind=='target':artifact['members'][inputs.sources.RECEIPT]['target']='../outside'
            else:artifact['id']='../../unselected'
            with self.subTest(kind=kind),self.assertRaises(ValueError):inputs.source_artifact(changed)

    def test_stock_transfer_selects_only_original_extractor_runtime_receipt_and_debug(self):
        rows=inputs.stock_artifacts();self.assertEqual(set(rows),{'stockRuntime','stockDebug'})
        targets={item['target'] for row in rows.values() for item in row['members'].values()}
        self.assertEqual(targets,{'stock-package/package-receipt.json',
            'stock-package/server-extractors-runtime-arm64.tar.gz','stock-debug/stock-extractors-debug-arm64.tar.gz'})
        self.assertFalse(any('engine' in name or 'content' in name for row in rows.values() for name in row['members']))

    def test_pending_source_anchor_refuses_before_network_and_output(self):
        pin=json.loads(inputs.provider.LOCK.read_text())
        pin.update(state='pending-ordered-source-and-derived-native-cli',sourceCompanionComplete=False,
            nativeArgumentConfigQualified=False,originalNoticesPreserved=False,actualOrderedSourceQualification=None)
        for name in ('archive','archiveEntries','archiveFileBytes','packageReceipt','programPairs','nativeCliReceipt','files','toolSelection'):
            pin[name]=None
        lock=self.root/'pending.json';lock.write_text(json.dumps(pin));api=Mock();output=self.root/'preserved'
        with patch.object(inputs.provider,'LOCK',lock),self.assertRaisesRegex(ValueError,'real-ordered-source-qualification-required'):
            inputs.acquire(output,api)
        api.json.assert_not_called();api.download.assert_not_called();self.assertFalse(output.exists())

    def test_existing_source_preparation_output_is_preserved_before_extraction(self):
        acquired=self.root/'inputs';acquired.mkdir();output=self.root/'saved';output.mkdir();(output/'marker').write_bytes(b'keep')
        with patch.object(inputs.sources,'verify_original') as original,self.assertRaisesRegex(ValueError,'fixture-output-exists-or-overlaps'):
            inputs.fixture_source(acquired,output)
        original.assert_not_called();self.assertEqual((output/'marker').read_bytes(),b'keep')


if __name__=='__main__':unittest.main()
