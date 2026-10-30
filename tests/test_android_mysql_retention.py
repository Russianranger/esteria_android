"""Real source-file closure/readback guards for future x64 fixture retention."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import preserve_android_mysql_probe as retention


def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class MysqlFixtureRetention(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        self.sources=self.root/'sources';self.sources.mkdir()
        self.runtime=retention.builder.encoded(dict(sourcePackages=[dict(package='fixture',version='1.0')]))
        self.body=b'synthetic corresponding source archive, no runtime claim'
        row=dict(file='fixture_1.0.orig.tar.gz',**identity(self.body))
        self.lock=retention.builder.encoded(dict(mysql=dict(sourceArchives=[row])))
        self.manifest=dict(formatVersion=1,scope='installed-ubuntu-package-corresponding-sources',
            runtimeManifestSha256=identity(self.runtime)['sha256'],sourceLockSha256=identity(self.lock)['sha256'],
            sourcePackages=json.loads(self.runtime)['sourcePackages'],files=[row],fileBytes=len(self.body))
        (self.sources/row['file']).write_bytes(self.body)
        (self.sources/'server-runtime.json').write_bytes(self.runtime);(self.sources/'sources.lock.json').write_bytes(self.lock)
        self.save()

    def save(self):(self.sources/'SOURCE-MANIFEST.json').write_bytes(retention.builder.encoded(self.manifest))

    def test_actual_complete_source_files_and_both_runtime_bindings_are_read_back(self):
        result,row=retention.verify_sources(self.sources,self.runtime,self.lock)
        self.assertEqual(result,self.manifest)
        self.assertEqual(row,retention.builder.identity(self.sources/'SOURCE-MANIFEST.json'))

    def test_tampered_missing_linked_and_extra_source_entries_refuse(self):
        path=self.sources/'fixture_1.0.orig.tar.gz'
        for change in ('changed','missing','linked','extra'):
            with self.subTest(change=change):
                if path.exists() or path.is_symlink():path.unlink()
                path.write_bytes(self.body)
                if change=='changed':path.write_bytes(b'different source')
                elif change=='missing':path.unlink()
                elif change=='linked':
                    path.unlink();target=self.root/'foreign';target.write_bytes(self.body);path.symlink_to(target)
                else:(self.sources/'unlisted').write_bytes(b'foreign')
                with self.assertRaises((ValueError,OSError)):retention.verify_sources(self.sources,self.runtime,self.lock)
        self.assertTrue((self.sources/'unlisted').exists())

    def test_foreign_source_manifest_and_mysql_archive_pins_refuse(self):
        for key,value in [('runtimeManifestSha256','0'*64),('sourceLockSha256','0'*64),('sourcePackages',[]),('fileBytes',1),('formatVersion',True)]:
            original=copy.deepcopy(self.manifest);self.manifest[key]=value;self.save()
            with self.subTest(key=key),self.assertRaises(ValueError):retention.verify_sources(self.sources,self.runtime,self.lock)
            self.manifest=original
        self.save();bad=json.loads(self.lock);bad['mysql']['sourceArchives'][0]['sha256']='0'*64
        changed=retention.builder.encoded(bad);self.manifest['sourceLockSha256']=identity(changed)['sha256'];self.save()
        (self.sources/'sources.lock.json').write_bytes(changed)
        with self.assertRaisesRegex(ValueError,'original-mysql-source-pins'):retention.verify_sources(self.sources,self.runtime,changed)

    def test_source_manifest_rejects_duplicate_traversal_boolean_sizes_and_oversize(self):
        for change in ('duplicate','traversal','boolean','large'):
            original=copy.deepcopy(self.manifest)
            if change=='duplicate':self.manifest['files']*=2
            elif change=='traversal':self.manifest['files'][0]['file']='../foreign'
            elif change=='boolean':self.manifest['files'][0]['bytes']=True
            else:self.manifest['files'][0]['bytes']=(2<<30)+1
            self.save()
            with self.subTest(change=change),self.assertRaises(ValueError):retention.verify_sources(self.sources,self.runtime,self.lock)
            self.manifest=original

    def test_closed_retention_transaction_copies_exact_inputs_and_never_private_sibling(self):
        provider=self.root/'provider';assets=provider/'assets/mysql-probe';assets.mkdir(parents=True)
        for name in retention.builder.NAMES:(assets/name).write_bytes(b'synthetic fixture '+name.encode())
        (assets/'runtime.json').write_bytes(self.runtime);(assets/'sources.lock.json').write_bytes(self.lock)
        (self.root/'database-secret').write_bytes(b'private sibling must not be retained')
        apk=self.root/'probe.apk';apk.write_bytes(b'synthetic fixture apk; verifier mocked for transaction only')
        test_apk=self.root/'tests.apk';test_apk.write_bytes(b'synthetic test apk')
        output=self.root/'retained'
        with patch.object(retention.verify,'verify',return_value=dict(scope='synthetic-transaction-test-only')):
            proof=retention.retain(provider,self.root,apk,test_apk,self.sources,'a'*40,123,'b'*64,output)
        self.assertEqual(proof['sourceCompanionArtifact']['id'],123)
        self.assertEqual(proof['sourceCompanionArtifact']['sha256'],'b'*64)
        self.assertFalse(proof['androidExecutionSucceeded']);self.assertFalse(proof['databaseStateCopied'])
        self.assertFalse(proof['offlineConsumerPinCreated'])
        self.assertEqual({p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()},
            set(proof['files'])|{'retention.json'})
        for name,row in proof['files'].items():self.assertEqual(retention.builder.identity(output/name),row)
        before=(output/'retention.json').read_bytes()
        with patch.object(retention.verify,'verify',return_value={}),self.assertRaisesRegex(ValueError,'existing-or-overlapping'):
            retention.retain(provider,self.root,apk,test_apk,self.sources,'a'*40,123,'b'*64,output)
        self.assertEqual((output/'retention.json').read_bytes(),before)
        self.assertFalse((output/'database-secret').exists())

    def test_missing_source_artifact_identity_never_creates_retention_or_touches_existing_saves(self):
        output=self.root/'saves';output.mkdir();(output/'keep').write_bytes(b'private persistent bytes')
        for artifact,digest,revision in [(0,'a'*64,'b'*40),(1,'','b'*40),(1,'a'*64,'floating')]:
            with self.subTest(artifact=artifact,digest=digest),self.assertRaisesRegex(ValueError,'exact-source-artifact'):
                retention.retain(self.root,self.root,self.root/'probe.apk',self.root/'tests.apk',self.sources,
                    revision,artifact,digest,output)
        self.assertEqual((output/'keep').read_bytes(),b'private persistent bytes')
        self.assertEqual({p.name for p in output.iterdir()},{'keep'})

if __name__=='__main__':unittest.main()
