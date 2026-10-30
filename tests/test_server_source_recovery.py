"""Recover retained metadata by hashes; never synthesize a new native build pass."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import recover_server_source_retention as recovery


def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class SourceRecoveryGuards(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='source-retention-recovery-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)

    def test_exact_original_pin_cannot_claim_a_new_build(self):
        pin=recovery.load_pin()
        self.assertEqual(pin['workflowRun'],41051669638)
        self.assertEqual(pin['archive']['sha256'],'9f76881f06a7c998e0dba9d4a226c623021ed6ad8b87074aa7a861eafbb96d80')
        self.assertFalse(pin['fullServerCompilationPerformed']);self.assertFalse(pin['newNativeQualificationClaimed'])
        changed=copy.deepcopy(pin);changed['fullServerCompilationPerformed']=True
        with patch.object(recovery.engine.modules,'read_json',return_value=(changed,{})):
            with self.assertRaisesRegex(ValueError,'qualification-claim'):recovery.load_pin()

    def remote(self):
        pin=recovery.load_pin()
        run=dict(id=pin['workflowRun'],head_sha=pin['integrationRevision'],status='completed',conclusion='failure')
        job=dict(id=pin['job'],run_id=pin['workflowRun'],status='completed',conclusion='failure',
            steps=[dict(number=n,conclusion='failure' if n==10 else 'success') for n in range(3,12)])
        row=pin['evidenceArtifact']
        artifact=dict(id=row['id'],expired=False,size_in_bytes=row['bytes'],digest='sha256:'+row['sha256'],
            workflow_run=dict(id=pin['workflowRun'],head_sha=pin['integrationRevision']))
        api=Mock();api.json.side_effect=lambda name:run if '/runs/' in name else job if '/jobs/' in name else artifact
        return pin,api,run,job,artifact

    def test_remote_requires_successful_full_build_and_only_retention_failure(self):
        pin,api,run,job,artifact=self.remote();recovery.verify_remote(api,pin)
        next(r for r in job['steps'] if r['number']==8)['conclusion']='failure'
        with self.assertRaisesRegex(ValueError,'not-retention-only'):recovery.verify_remote(api,pin)
        pin,api,run,job,artifact=self.remote();artifact['workflow_run']['head_sha']='0'*40
        with self.assertRaisesRegex(ValueError,'artifact-changed'):recovery.verify_remote(api,pin)
        api.download.assert_not_called()

    def test_existing_evidence_is_preserved_before_network(self):
        output=self.root/'saved';output.mkdir();marker=output/'keep';marker.write_bytes(b'kept')
        api=Mock()
        with self.assertRaisesRegex(ValueError,'evidence-preserved'):recovery.acquire(output,api)
        api.json.assert_not_called();api.download.assert_not_called();self.assertEqual(marker.read_bytes(),b'kept')

    def test_x64_does_not_claim_native_recovery(self):
        with patch.object(recovery.platform,'machine',return_value='x86_64'):
            with self.assertRaisesRegex(ValueError,'native-arm64'):recovery.recover(self.root,self.root,self.root,self.root)

    def test_every_origin_and_changed_generated_bytes_are_checked(self):
        roots={n:self.root/n for n in ('integration','acquired','prepared','protocol','evidence','output')}
        names={'recipes/LICENSE':('integration','LICENSE'),'inputs/acquisition.json':('evidence','acquisition.json'),
            'inputs/source-inputs/archive.tar.gz':('acquired','source-inputs/archive.tar.gz'),
            'preparation/provenance/receipt.json':('prepared','provenance/receipt.json'),
            'protocol/limits.json':('protocol','limits.json'),'qualification/qualification.json':('evidence','qualification.json'),
            'new-build/compile_commands.json':('output','build/compile_commands.json'),
            'new-build/generated/revision.h':('output','build/revision.h')}
        rows={}
        for name,(root,path) in names.items():
            target=roots[root]/path;target.parent.mkdir(parents=True,exist_ok=True)
            raw=('synthetic '+name).encode();target.write_bytes(raw);rows[name]=dict(identity(raw),mode=0o444)
        plan=self.root/'plan';plan.write_bytes(b'plan');rows['rebuild-plan.json']=dict(identity(b'plan'),mode=0o444)
        kwargs=dict(roots,plan=plan);sealed=dict(archiveFiles=rows)
        selected=recovery.selected_files(sealed,**kwargs);self.assertEqual(set(selected),set(rows))
        (roots['output']/'build/compile_commands.json').write_bytes(b'changed configure result')
        with self.assertRaisesRegex(ValueError,'not-byte-identical:new-build/compile_commands.json'):
            recovery.selected_files(sealed,**kwargs)
        sealed['archiveFiles']={'unknown/member':dict(identity(b'anything'),mode=0o444)}
        with self.assertRaisesRegex(ValueError,'unrecognized'):recovery.selected_files(sealed,**kwargs)

    def test_original_fixed_rebuild_plan_bytes_are_reproduced(self):
        raw=recovery.engine.canonical(recovery.rebuild_plan())
        self.assertEqual(identity(raw),dict(bytes=970,sha256='83546bcb588fa241c2c32b477e8530fff000f641114b12119c89ebec1f779be8'))

    def test_final_compressed_archive_must_match_before_original_receipts_are_published(self):
        source=self.root/'source.txt';source.write_bytes(b'synthetic source, no compiler or qualification')
        selected={'inputs/source.txt':source}
        expected_path=self.root/'expected.tar.gz'
        inventory=recovery.isolated.write_source_archive(expected_path,selected)
        sealed=dict(archive=dict(file=recovery.isolated.SOURCE_ARCHIVE,**recovery.files.identity(expected_path)),archiveFiles=inventory)
        evidence=self.root/'proof';evidence.mkdir()
        for name in ('qualification.json','sealed-source-receipt.json'):(evidence/name).write_bytes(b'{"synthetic":true}\n')
        receipt_identities={name:recovery.files.identity(evidence/name) for name in ('qualification.json','sealed-source-receipt.json')}
        output=self.root/'published';recovery.publish_exact(selected,sealed,evidence,output,receipt_identities)
        self.assertEqual((output/'qualification.json').read_bytes(),(evidence/'qualification.json').read_bytes())
        self.assertEqual(recovery.files.identity(output/sealed['archive']['file']),recovery.files.identity(expected_path))
        changed=copy.deepcopy(sealed);changed['archive']['sha256']='0'*64
        failed=self.root/'refused'
        with self.assertRaisesRegex(ValueError,'not-byte-identical-to-original'):
            recovery.publish_exact(selected,changed,evidence,failed,receipt_identities)
        self.assertFalse((failed/'qualification.json').exists());self.assertFalse((failed/'sealed-source-receipt.json').exists())
        (evidence/'qualification.json').write_bytes(b'{"changed":true}\n')
        changed_receipt=self.root/'changed-original-receipt'
        with self.assertRaisesRegex(ValueError,'changed|identity|differ|mismatch'):
            recovery.publish_exact(selected,sealed,evidence,changed_receipt,receipt_identities)
        self.assertFalse((changed_receipt/'qualification.json').exists())


if __name__=='__main__':unittest.main()
