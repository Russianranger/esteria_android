"""Host metadata/real ZIP/transaction fixtures; no SQL or Android execution."""
import copy
import json
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import android_installation_x64_provider_artifacts as artifacts


class InstallationProviderArtifacts(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)

    def pending(self):
        return dict(formatVersion=1,scope=artifacts.SCOPE,repository='Russianranger/esteria_android',enabled=False,
            state='pending-actual-provider-artifact-measurement',producer=None,productArtifact=None,evidenceArtifact=None,
            measurementEvidence=None,providerDescriptor=None,productManifest=None,**{name:False for name in artifacts.FALSE_FLAGS})

    def test_real_pending_selection_cannot_create_output_or_use_network(self):
        actual=artifacts.load_pin();self.assertIs(type(actual['enabled']),bool)
        lock=self.root/'pending.json';lock.write_text(json.dumps(self.pending()))
        with patch.object(artifacts,'LOCK',lock),patch.object(artifacts.gate.frozen_mysql,'inspect') as frozen,patch.object(artifacts.remote,'Github') as network, \
                self.assertRaisesRegex(ValueError,'actual-artifact-measurements-required'):
            artifacts.acquire(self.root/'output',self.root/'source')
        frozen.assert_not_called();network.assert_not_called();self.assertFalse((self.root/'output').exists())

    def test_pending_artifact_fields_or_runtime_claims_refuse(self):
        pending=self.pending();lock=self.root/'lock.json'
        for change in (dict(productArtifact={}),dict(enabled=1),dict(sqlExecuted=True),dict(state='measured-provider-artifacts'),dict(extra=True)):
            lock.write_text(json.dumps(dict(pending,**change)))
            with patch.object(artifacts,'LOCK',lock),self.assertRaises(ValueError):artifacts.load_pin()

    def test_positive_shaped_transport_requires_independent_provider_and_producer_readback(self):
        # Schema-only metadata. Underlying real Android/native admission is
        # explicitly patched; no measured component or positive lock is made.
        scalar=artifacts.provider.identity_bytes(b'synthetic artifact identity')
        pin=dict(self.pending(),enabled=True,state='measured-provider-artifacts',
            producer=dict(workflowRun=11,job=22,integrationRevision='a'*40),
            productArtifact=dict(id=33,**scalar),evidenceArtifact=dict(id=44,**scalar),
            measurementEvidence=dict(path='runtime/evidence/synthetic-measurement.json',**scalar),
            providerDescriptor=scalar,productManifest=scalar)
        gate=dict(provider=scalar,providerReadback=dict(path='runtime/evidence/synthetic-readback.json',**scalar))
        provider_readback=dict(explicitSyntheticFixture=True)
        proof=dict(scope='independent-android-x64-provider-measurement-artifact-readback',
            workflow=dict(id=11,job=22,headSha='a'*40,status='completed',conclusion='success'),
            artifacts=dict(product=pin['productArtifact'],evidence=pin['evidenceArtifact']),providerDescriptor=scalar,productManifest=scalar,
            actualProviderReadback=provider_readback,allSmallArtifactZipBytesReadBack=True,everySmallArtifactMemberCrcAndSha256Verified=True,
            producerPackagingSourcesMatchExactGitBlobs=True,completeProductReadbackRequiredBeforeApk=True,
            **{name:False for name in artifacts.FALSE_FLAGS})
        lock=self.root/'lock.json'
        def load(value,report):
            lock.write_text(json.dumps(value))
            with patch.object(artifacts,'LOCK',lock),patch.object(artifacts.gate,'load_pin',return_value=gate), \
                    patch.object(artifacts.gate,'record',side_effect=lambda row:report if row['path'].endswith('measurement.json') else provider_readback):
                return artifacts.load_pin(require_enabled=True)
        self.assertEqual(load(pin,proof),pin)
        for field in ('allSmallArtifactZipBytesReadBack','everySmallArtifactMemberCrcAndSha256Verified',
                'producerPackagingSourcesMatchExactGitBlobs','completeProductReadbackRequiredBeforeApk'):
            with self.assertRaisesRegex(ValueError,'independent-measurement-required'):load(pin,dict(proof,**{field:False}))
        wrong=copy.deepcopy(proof);wrong['workflow']['conclusion']='failure'
        with self.assertRaisesRegex(ValueError,'independent-measurement-required'):load(pin,wrong)
        with self.assertRaisesRegex(ValueError,'android-selection-differs'):load(dict(pin,providerDescriptor=artifacts.provider.identity_bytes(b'foreign')),proof)

    def product(self):
        product=self.root/'product';(product/'provider/assets/installation-probe').mkdir(parents=True)
        (product/'corresponding-source').mkdir()
        (product/'provider/assets/installation-probe/provider.json').write_bytes(b'{"fixtureOnly":true}\n')
        (product/'corresponding-source/original.tar.gz').write_bytes(b'synthetic source bytes fixture')
        (product/'measurement.json').write_bytes(b'{"fixtureOnly":true}\n')
        (product/'measurement-recipe.tar').write_bytes(b'synthetic recipe fixture')
        pin=artifacts.files.identity(product/'provider/assets/installation-probe/provider.json')
        readback=dict(providerDescriptor=pin,sourceCompanionManifest=artifacts.files.identity(product/'corresponding-source/original.tar.gz'))
        manifest=artifacts.product_manifest(product,readback,artifacts.files.identity(product/'measurement-recipe.tar'))
        artifacts.provider.engine.put_metadata(product/artifacts.MANIFEST,manifest)
        return product,manifest

    def archive(self,product,name='product.zip',*,mutate=None):
        path=self.root/name
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for source in artifacts.files.installed_files(product):
                member=source.relative_to(product).as_posix();raw=source.read_bytes();info=zipfile.ZipInfo(member);info.external_attr=(stat.S_IFREG|0o444)<<16
                if mutate:member,raw,info=mutate(member,raw,info)
                z.writestr(info,raw)
        return path

    def test_closed_product_zip_is_fully_read_and_restored_without_adoption(self):
        product,manifest=self.product();archive=self.archive(product);wanted=artifacts.files.identity(product/artifacts.MANIFEST)
        observed=artifacts.restore_product(archive,self.root/'restored',wanted);self.assertEqual(observed,manifest)
        for name,pin in manifest['files'].items():self.assertEqual(artifacts.files.identity(self.root/'restored'/name),pin)
        with self.assertRaisesRegex(ValueError,'existing-output-preserved'):
            artifacts.restore_product(archive,self.root/'restored',wanted)

    def test_changed_source_bytes_or_foreign_manifest_refuse(self):
        product,_=self.product();wanted=artifacts.files.identity(product/artifacts.MANIFEST)
        def change(name,raw,info):return name,(b'foreign source' if name.endswith('original.tar.gz') else raw),info
        with self.assertRaisesRegex(ValueError,'kind-or-size|member-changed'):
            artifacts.restore_product(self.archive(product,mutate=change),self.root/'changed',wanted)
        wanted=dict(wanted,sha256='0'*64)
        with self.assertRaisesRegex(ValueError,'manifest-changed'):
            artifacts.restore_product(self.archive(product,'clean.zip'),self.root/'foreign',wanted)

    def test_symlink_and_undeclared_zip_member_refuse(self):
        product,_=self.product();wanted=artifacts.files.identity(product/artifacts.MANIFEST)
        def linked(name,raw,info):
            if name.endswith('original.tar.gz'):info.external_attr=(stat.S_IFLNK|0o777)<<16
            return name,raw,info
        with self.assertRaisesRegex(ValueError,'kind-or-size|unsupported-entry'):
            artifacts.restore_product(self.archive(product,mutate=linked),self.root/'linked',wanted)
        path=self.archive(product,'extra.zip')
        with zipfile.ZipFile(path,'a') as z:z.writestr('private-database.sql',b'not permitted')
        with self.assertRaisesRegex(ValueError,'product-closure'):
            artifacts.restore_product(path,self.root/'extra',wanted)

    def test_manifest_cannot_include_database_or_caller_namespace(self):
        product,_=self.product();(product/artifacts.MANIFEST).unlink();(product/'database-secret').write_bytes(b'fixture-only')
        with self.assertRaisesRegex(ValueError,'unexpected-product-file'):
            artifacts.product_manifest(product,dict(providerDescriptor={},sourceCompanionManifest={}),{})

    def small(self,*,large=False,linked=False):
        path=self.root/'evidence.zip'
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name in artifacts.SMALL:
                info=zipfile.ZipInfo(name);info.external_attr=(stat.S_IFLNK if linked else stat.S_IFREG)<<16
                z.writestr(info,b'x'*((4<<20)+1) if large and name=='provider.json' else b'{}\n')
        return path

    def test_small_evidence_checks_expansion_and_regular_members_before_read(self):
        self.assertEqual(set(artifacts.evidence_members(self.small())),artifacts.SMALL)
        (self.root/'evidence.zip').unlink()
        with self.assertRaisesRegex(ValueError,'expanded-bound'):artifacts.evidence_members(self.small(large=True))
        (self.root/'evidence.zip').unlink()
        with self.assertRaisesRegex(ValueError,'expanded-bound|unsupported-entry'):artifacts.evidence_members(self.small(linked=True))

    def test_original_producer_job_and_run_must_both_remain_successful(self):
        producer=dict(workflowRun=11,job=22,integrationRevision='a'*40)
        run=dict(id=11,head_sha='a'*40,status='completed',conclusion='success')
        job=dict(id=22,run_id=11,status='completed',conclusion='success')
        class Api:
            def json(self,path):return run if '/runs/' in path else job
        artifacts.remote_producer(Api(),producer)
        for target,field,value in ((run,'head_sha','b'*40),(run,'conclusion','failure'),(job,'run_id',99),(job,'conclusion','failure')):
            old=target[field];target[field]=value
            with self.assertRaisesRegex(ValueError,'no-longer-successful'):artifacts.remote_producer(Api(),producer)
            target[field]=old

    def test_pending_native_sql_refuses_measurement_before_output(self):
        with patch.object(artifacts.gate,'load_pin',side_effect=ValueError('native-sql-measurement-required')), \
                self.assertRaisesRegex(ValueError,'native-sql-measurement-required'):
            artifacts.seal(self.root/'missing-product',self.root/'must-not-exist')
        self.assertFalse((self.root/'must-not-exist').exists())

    def test_canonical_producer_recipe_ignores_git_replace_objects(self):
        repo=self.root/'git';repo.mkdir()
        def git(*words):return subprocess.check_output(['git','-C',str(repo),*words],stderr=subprocess.DEVNULL)
        git('init','-q');path=repo/'source.py';path.write_bytes(b'original producer source\n');original=artifacts.files.identity(path)
        git('add','.');git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','producer')
        p=git('rev-parse','HEAD').decode().strip();path.write_bytes(b'foreign replacement source\n');foreign=artifacts.files.identity(path)
        git('add','.');git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','replacement')
        q=git('rev-parse','HEAD').decode().strip();git('replace',p,q)
        self.assertEqual(git('show',p+':source.py'),path.read_bytes())
        with patch.object(artifacts,'ROOT',repo),patch.object(artifacts.provider,'recipe_names',return_value=['source.py']):
            artifacts.canonical_recipe(dict(commit=p,files={'source.py':original}))
            with self.assertRaisesRegex(ValueError,'canonical-git-recipe-differs'):
                artifacts.canonical_recipe(dict(commit=p,files={'source.py':foreign}))


if __name__=='__main__':unittest.main()
