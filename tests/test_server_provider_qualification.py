"""Exact input/manifest guards; fixtures never qualify a native server or APK."""
import copy
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock,patch
import zipfile

from tools import qualify_server_providers as qualification


def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class ProviderQualificationGuards(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='server-provider-inputs-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)

    def test_inputs_pin_retained_derivatives_not_full_original_install(self):
        pin=qualification.load_pin()
        self.assertEqual(len(pin['artifacts']),5)
        self.assertGreater(pin['artifacts']['engineDebug']['bytes'],1024**3)
        self.assertTrue(all(r['id']!=12966255548 for r in pin['artifacts'].values()))
        targets=[m['target'] for r in pin['artifacts'].values() for m in r['members'].values()]
        self.assertEqual(len(targets),len(set(targets)))
        self.assertFalse(pin['androidRuntimeQualified']);self.assertFalse(pin['gameplayQualified'])

    def test_final_profile_requires_exact_current_apk_source_helper_closure(self):
        from tools import package_combined_android as combined
        output=self.root/'providers';output.mkdir();apk=self.root/'profile.apk'
        with ExitStack() as stack:
            for module,_ in qualification.COMPONENTS.values():
                stack.enter_context(patch.object(module,'verify',return_value={'verified':True}))
            with zipfile.ZipFile(apk,'w'):
                pass
            with self.assertRaisesRegex(ValueError,'helper-inventory'):
                qualification.verify_final(output,self.root/'dependencies',apk)
            with zipfile.ZipFile(apk,'w') as archive:
                for directory,names in combined.HELPER_SETS.items():
                    records={}
                    for name in names:
                        raw=(combined.ROOT/combined.helper_source_path(directory,name)).read_bytes()
                        archive.writestr('assets/'+directory+'/'+name,raw);records[name]=identity(raw)
                    archive.writestr('assets/'+directory+'/manifest.json',json.dumps({'formatVersion':1,'files':records}))
            receipt=qualification.verify_final(output,self.root/'dependencies',apk)
            self.assertTrue(receipt['exactSourceHelperClosureVerified'])
            self.assertEqual(receipt['helperFiles']['server-data'],5)
            self.assertFalse(receipt['androidGuestExecuted'])

    def test_wrong_remote_revision_or_zip_digest_refuses_before_extraction(self):
        pin=qualification.load_pin()['artifacts']['native'];api=Mock()
        api.json.return_value=dict(id=pin['id'],expired=False,size_in_bytes=pin['bytes'],digest='sha256:'+pin['sha256'],
            workflow_run=dict(id=pin['workflowRun'],head_sha=pin['integrationRevision']))
        qualification.verify_remote(api,pin)
        api.json.return_value['workflow_run']['head_sha']='0'*40
        with self.assertRaisesRegex(ValueError,'remote-artifact-changed'):qualification.verify_remote(api,pin)
        path=self.root/'changed.zip';path.write_bytes(b'not the pinned ZIP')
        with patch.object(qualification.remote,'bounded_zip') as opened:
            with self.assertRaisesRegex(ValueError,'downloaded-zip-changed'):
                qualification.extract_selected(path,self.root,pin)
        opened.assert_not_called()

    def test_selected_zip_member_hash_and_required_names_are_independent_of_zip_hash(self):
        path=self.root/'fixture.zip';raw=b'actual selected fixture bytes'
        with zipfile.ZipFile(path,'w') as archive:archive.writestr('package/member',raw)
        row=dict(qualification.files.identity(path),members={'package/member':dict(target='selected/member',**identity(raw))})
        qualification.extract_selected(path,self.root,row)
        self.assertEqual((self.root/'selected/member').read_bytes(),raw)
        wrong=copy.deepcopy(row);wrong['members']['package/member']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'member-hash'):
            qualification.extract_selected(path,self.root/'wrong',wrong)
        wrong=copy.deepcopy(row);wrong['members']['missing']=wrong['members'].pop('package/member')
        with self.assertRaisesRegex(ValueError,'member-missing'):
            qualification.extract_selected(path,self.root/'missing',wrong)

    def test_existing_outputs_and_disk_floor_refuse_before_network(self):
        output=self.root/'existing';output.mkdir();(output/'saved').write_bytes(b'keep');api=Mock()
        with self.assertRaisesRegex(ValueError,'inputs-preserved'):qualification.acquire(output,api)
        with patch.object(qualification.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(10,9,1)):
            with self.assertRaisesRegex(ValueError,'16-GiB'):qualification.acquire(self.root/'new',api)
        api.json.assert_not_called();api.download.assert_not_called();self.assertFalse((self.root/'new').exists())
        self.assertEqual((output/'saved').read_bytes(),b'keep')

    def test_java_manifest_uses_stable_archived_server_identity_and_exact_component_pins(self):
        provider=self.root/'provider';assets=provider/'assets/server-programs';assets.mkdir(parents=True)
        proof=dict(packageKey='server-programs-arm64',serverBuildSourceLockSha256='1'*64,appSourceLockSha256='2'*64,
            archive=dict(file='original.tar.gz',assetPath='server-programs/server-programs.archive',bytes=100,sha256='3'*64),
            archiveEntries=2,archiveFileBytes=20,limits=dict(entries=10,memberBytes=100,fileBytes=100,pathBytes=512,metadataBytes=1024),
            requiredFiles={'bin/tool':dict(bytes=20,sha256='4'*64,elfMachine=183)})
        (assets/'provider.json').write_text(json.dumps(proof));manifest=self.root/'plan.tsv'
        result=qualification.java_manifest(provider,manifest)
        lines=manifest.read_text().splitlines();self.assertEqual(lines[0].split('\t')[2],'1'*64)
        self.assertEqual(lines[1].split('\t'),['F','bin/tool','20','4'*64,'183','0'])
        self.assertEqual(result['archive'],str(assets/'server-programs.archive'))


if __name__=='__main__':unittest.main()
