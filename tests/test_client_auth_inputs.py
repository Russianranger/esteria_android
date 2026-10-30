import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile
from tools import prepare_client_auth_inputs as inputs


class Inputs(unittest.TestCase):
    def setUp(self):self.pin,_=inputs.load_pin()

    def receipt(self):
        return dict(formatVersion=1,scope='native-linux-arm64-wine-component-fixtures',
            **{key:True for key in inputs.SCOPES},processNamespaceExited=True,namespaceExit=0,
            **{key:False for key in ('androidRuntimeQualified','gameInitializationStarted','renderingQualified',
                'audioQualified','gameLoginQualified','serverRuntimeIncluded')},
            client=dict(sourceRevision=self.pin['sourceRevision'],buildId=self.pin['buildId'],
                clientManifestSha256=self.pin['clientManifestSha256']))

    def test_partial_scopes_abnormal_cleanup_and_wrong_client_are_rejected(self):
        good=self.receipt();inputs.validate_receipt(good,self.pin)
        for key in inputs.SCOPES:
            for value in (False,1,None):
                with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                    inputs.validate_receipt(dict(good,**{key:value}),self.pin)
        for key,value in (('namespaceExit',False),('namespaceExit',137),('formatVersion',True),
                          ('gameInitializationStarted',True),('processNamespaceExited',False)):
            with self.subTest(key=key),self.assertRaises(ValueError):inputs.validate_receipt(dict(good,**{key:value}),self.pin)
        wrong=copy.deepcopy(good);wrong['client']['sourceRevision']='a'*40
        with self.assertRaises(ValueError):inputs.validate_receipt(wrong,self.pin)

    def test_exact_receipt_bytes_required_before_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'evidence.zip';raw=json.dumps(self.receipt()).encode()
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(self.pin['wineEvidence']['receiptPath'],raw)
            pin=copy.deepcopy(self.pin);pin['wineEvidence'].update(bytes=path.stat().st_size,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),receiptSha256=hashlib.sha256(raw).hexdigest())
            self.assertEqual(inputs.evidence(path,pin),raw)
            pin['wineEvidence']['receiptSha256']='0'*64
            with mock.patch.object(inputs.json,'loads',side_effect=AssertionError('Must not parse unverified receipt')):
                with self.assertRaises(ValueError):inputs.evidence(path,pin)
            pin['wineEvidence']['bytes']+=1
            with self.assertRaises(ValueError):inputs.evidence(path,pin)

    def test_remote_failed_run_or_different_artifact_cannot_be_substituted(self):
        run=dict(id=self.pin['workflowRun'],head_sha=self.pin['sourceRevision'],status='completed',conclusion='success')
        rows={}
        for key,prefix in (('clientArtifact','client-ARM64-'),('wineEvidence','linux-arm64-wine-')):
            p=self.pin[key];rows['/actions/artifacts/'+str(p['id'])]=dict(id=p['id'],name=prefix+self.pin['sourceRevision'],
                expired=False,size_in_bytes=p['bytes'],digest='sha256:'+p['sha256'],
                workflow_run=dict(id=self.pin['workflowRun'],head_sha=self.pin['sourceRevision']))
        rows['/actions/runs/'+str(self.pin['workflowRun'])]=run
        api=mock.Mock();api.json.side_effect=lambda key:rows[key]
        inputs.verify_remote(api,self.pin)
        run['conclusion']='failure'
        with self.assertRaises(ValueError):inputs.verify_remote(api,self.pin)
        run['conclusion']='success';rows['/actions/artifacts/'+str(self.pin['clientArtifact']['id'])]['expired']=True
        with self.assertRaises(ValueError):inputs.verify_remote(api,self.pin)

    def test_existing_inputs_preserved_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);(path/'sentinel').write_bytes(b'preserve')
            api=mock.Mock()
            with self.assertRaises(ValueError):inputs.prepare(path,api)
            api.json.assert_not_called();self.assertEqual((path/'sentinel').read_bytes(),b'preserve')


if __name__=='__main__':unittest.main()
