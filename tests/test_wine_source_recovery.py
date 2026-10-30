import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import recover_wine_provider_sources as recovery


class WineSourceRecovery(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.original=self.root/'original.zip';self.output=self.root/'recovered';self.raw=b'# exact fixture\n'
        data=io.BytesIO()
        with tarfile.open(fileobj=data,mode='w') as tar:
            item=tarfile.TarInfo(recovery.SOURCE);item.size=len(self.raw);tar.addfile(item,io.BytesIO(self.raw))
        self.data={recovery.INTEGRATION:data.getvalue(),'turnip/bin/fixture':b'original binary fixture',
            'turnip/turnip-build.json':recovery.measured.encoded(dict(compiled=True,
            integrationRevision=recovery.measured.PRODUCER,runtimeArchiveSha256=recovery.measured.RUNTIME,
            recipeSources={'.dockerignore':recovery.measured.byte_identity(self.raw)}))}
        self.write_zip(self.original,self.data)
        m=recovery.measured
        run=dict(id=m.RUN,head_sha=m.PRODUCER,head_branch='android/client-server',path=m.WORKFLOW,
            event='push',status='completed',conclusion='success',repository={'full_name':m.REPOSITORY},head_repository={'full_name':m.REPOSITORY})
        self.run_path=self.root/'run.json';self.run_path.write_text(json.dumps(run))
        self.api=dict(id=12,name='unqualified-native-arm64-new-wine-turnip-'+m.PRODUCER,expired=False,
            size_in_bytes=self.original.stat().st_size,digest='sha256:'+hashlib.sha256(self.original.read_bytes()).hexdigest(),
            workflow_run=dict(id=m.RUN,head_sha=m.PRODUCER,head_branch='android/client-server'))
        self.api_path=self.root/'artifact.json';self.api_path.write_text(json.dumps(self.api))
        selected=patch.object(m,'git_exact',return_value=self.raw);selected.start();self.addCleanup(selected.stop)

    def write_zip(self,path,items):
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in items.items():
                item=zipfile.ZipInfo(name);item.external_attr=(stat.S_IFREG|0o644)<<16;archive.writestr(item,raw)

    def recover(self):return recovery.recover(self.run_path,self.api_path,self.original,self.output)

    def test_only_producer_pinned_retained_source_added_all_original_bytes_readback(self):
        original=self.original.read_bytes();proof=self.recover()
        self.assertEqual(self.original.read_bytes(),original)
        for name,raw in self.data.items():self.assertEqual((self.output/name).read_bytes(),raw)
        self.assertEqual((self.output/recovery.MISSING).read_bytes(),self.raw)
        self.assertTrue(proof['originalMemberBytesUnchanged']);self.assertFalse(proof['binariesRebuilt'])
        complete=self.root/'complete.zip';self.write_zip(complete,{p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()})
        self.assertEqual(recovery.verify(self.original,complete,proof['originalArtifact']),proof)

    def test_recovered_artifact_cannot_change_binary_or_add_unrelated_file(self):
        proof=self.recover();items={p.relative_to(self.output).as_posix():p.read_bytes() for p in self.output.rglob('*') if p.is_file()}
        for key,value in (('turnip/bin/fixture',b'changed binary'),('unrelated',b'extra')):
            changed=dict(items);changed[key]=value;path=self.root/'bad.zip';self.write_zip(path,changed)
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'original-members-differ'):
                recovery.verify(self.original,path,proof['originalArtifact'])

    def test_git_source_and_actual_build_receipt_must_agree(self):
        with patch.object(recovery.measured,'git_exact',return_value=b'wrong'):
            with self.assertRaisesRegex(ValueError,'producer-recipe-hash'):self.recover()
        changed=copy.deepcopy(self.data);changed[recovery.INTEGRATION]=b'not a tar'
        self.write_zip(self.original,changed)
        self.api.update(size_in_bytes=self.original.stat().st_size,digest='sha256:'+hashlib.sha256(self.original.read_bytes()).hexdigest());self.api_path.write_text(json.dumps(self.api))
        with self.assertRaises((ValueError,tarfile.ReadError)):self.recover()
        self.assertFalse(self.output.exists())

    def test_changed_original_hash_and_existing_output_are_refused_before_extraction(self):
        self.original.write_bytes(self.original.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'artifact-size'):self.recover()
        self.output.mkdir();(self.output/'save').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'output-exists'):self.recover()
        self.assertEqual((self.output/'save').read_bytes(),b'keep')

    def test_later_source_only_artifact_has_distinct_successful_api_identity(self):
        m=recovery.measured;head='b'*40
        run=dict(id=34,head_sha=head,head_branch='android/client-server',path=recovery.WORKFLOW,event='push',
            status='completed',conclusion='success',repository={'full_name':m.REPOSITORY},head_repository={'full_name':m.REPOSITORY})
        api=dict(id=56,name='source-complete-native-arm64-new-wine-turnip-'+m.PRODUCER+'-'+head,expired=False,
            size_in_bytes=self.original.stat().st_size,digest='sha256:'+hashlib.sha256(self.original.read_bytes()).hexdigest(),
            workflow_run=dict(id=34,head_sha=head,head_branch='android/client-server'))
        value=m.source_recovery_metadata(run,api,self.original)
        self.assertEqual(value['runId'],34);self.assertNotEqual(value['runId'],m.RUN)
        self.assertEqual(value['sourceRecoveryRevision'],head);self.assertEqual(value['workflowPath'],recovery.WORKFLOW)
        cases=[('run','conclusion','failure'),('run','path',m.WORKFLOW),('api','expired',True),
               ('api','digest','sha256:'+'0'*64),('api','name','relabelled-original')]
        for kind,key,replacement in cases:
            r,a=copy.deepcopy(run),copy.deepcopy(api);(r if kind=='run' else a)[key]=replacement
            with self.subTest(kind=kind,key=key),self.assertRaises(ValueError):
                m.source_recovery_metadata(r,a,self.original)


if __name__=='__main__':unittest.main()
