"""Tiny originals exercise the full public consumer; no Wine or network executes."""
import copy
import json
from pathlib import Path
import shutil
from unittest.mock import patch
import unittest

from tools import fetch_wine_arm64_release as public
from tests import test_wine_release as fixtures


class PublicWineInputs(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WineRelease('test_stage_and_verification_preserve_all_original_bytes_and_call_full_source_consumer')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.lock,self.selected = self.fixture.selected();self.selected.start();self.addCleanup(self.selected.stop)
        self.lock_path = self.fixture.root/'lock.json';self.lock_path.write_bytes(public.encoded(self.lock))
        self.package = patch.object(public.release.retained,'runtime_package',side_effect=self.fixture.check_package)
        self.sources = patch.object(public.release.retained.original_sources,'verify',side_effect=self.fixture.check_sources)
        self.package_mock=self.package.start();self.sources_mock=self.sources.start()
        self.addCleanup(self.package.stop);self.addCleanup(self.sources.stop)
        self.original = self.fixture.root/'release'
        public.release.stage(self.fixture.inputs,self.fixture.input_path,self.original,self.lock)
        self.package_mock.reset_mock();self.sources_mock.reset_mock()
        self.expected=public.expected_assets(self.lock)
        base='https://github.com/'+self.lock['repository']+'/releases/'
        self.receipt=dict(formatVersion=1,repository=self.lock['repository'],tag=self.lock['tag'],
            targetCommit=self.lock['targetCommit'],releaseId=123,url=base+'tag/'+self.lock['tag'],
            githubImmutable=False,publisherNeverOverwrites=True,
            assets={name:dict(pin,url=base+'download/'+self.lock['tag']+'/'+name) for name,pin in self.expected.items()})
        self.receipt_path=self.fixture.root/'published.json';self.receipt_path.write_bytes(public.encoded(self.receipt))
        self.row=dict(id=123,draft=False,prerelease=True,tag_name=self.lock['tag'],immutable=False,
            body=public.release.release_body(self.lock),assets=[dict(name=n,state='uploaded',size=p['bytes'],
                digest='sha256:'+p['sha256'],browser_download_url=self.receipt['assets'][n]['url']) for n,p in self.expected.items()])
        self.ref=dict(object=dict(type='commit',sha=self.lock['targetCommit']))
        self.downloads=[];owner=self
        class Api:
            def json(self,path):return owner.row if path.startswith('/releases/tags/') else owner.ref
            def download(self,url,target,expected):
                name=url.rsplit('/',1)[1];owner.downloads.append(name);shutil.copyfile(owner.original/name,target)
        self.api=Api()
        for p in (patch.object(public.release,'RECIPE_ROOTS',set(self.fixture.recipe)),
                  patch.object(public.release,'git_blob',return_value=b'recipe fixture')):
            p.start();self.addCleanup(p.stop)
        self.output=self.fixture.root/'public-inputs'

    def test_public_consumer_keeps_compatible_view_and_checks_all_sources_before_publish(self):
        proof=public.fetch(self.lock_path,self.receipt_path,self.output,self.api)
        self.assertEqual(set(self.downloads),public.release.RELEASE_FILES)
        self.assertEqual(self.sources_mock.call_count,1);self.assertEqual(self.package_mock.call_count,1)
        self.assertEqual((self.output/'sources.zip').read_bytes(),(self.fixture.inputs/'sources.zip').read_bytes())
        for name in public.release.retained.RUNTIME_FILES:
            self.assertEqual((self.output/'runtime-package'/name).read_bytes(),(self.fixture.package/name).read_bytes())
        self.assertTrue(proof['originalWholeSourceZipReadBack']);self.assertTrue(proof['historicalProducerRecipeGitBlobsVerified'])
        self.assertEqual(proof['inputTransport'],'public-write-once-prerelease')
        self.assertFalse(proof['runtimeRecompiled'] or proof['selectedClientExecuted'] or proof['androidQualified'])

    def test_changed_live_tag_release_scope_or_asset_digest_fail_before_download(self):
        cases=[('tag',None),('draft',True),('prerelease',False),('body','different'),('digest','sha256:'+'0'*64)]
        for kind,value in cases:
            with self.subTest(kind=kind):
                row,ref=copy.deepcopy(self.row),copy.deepcopy(self.ref)
                if kind=='tag':self.ref['object']['sha']='b'*40
                elif kind=='digest':self.row['assets'][0]['digest']=value
                else:self.row[kind]=value
                with self.assertRaises(ValueError):public.fetch(self.lock_path,self.receipt_path,self.output,self.api)
                self.assertEqual(self.downloads,[]);self.assertFalse(self.output.exists())
                self.row,self.ref=row,ref

    def test_entire_download_and_full_source_failure_are_required_before_visible_output(self):
        target=self.original/public.release.SOURCE_ZIP;target.write_bytes(target.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'download-readback'):
            public.fetch(self.lock_path,self.receipt_path,self.output,self.api)
        self.assertFalse(self.output.exists());self.sources_mock.assert_not_called()
        target.write_bytes((self.fixture.inputs/'sources.zip').read_bytes());self.sources_mock.side_effect=ValueError('original-source-failed')
        with self.assertRaisesRegex(ValueError,'original-source-failed'):
            public.fetch(self.lock_path,self.receipt_path,self.output,self.api)
        self.assertFalse(self.output.exists())

    def test_foreign_receipt_urls_and_changed_historical_git_inputs_are_refused(self):
        receipt=copy.deepcopy(self.receipt);receipt['assets'][public.release.SOURCE_ZIP]['url']='https://foreign.invalid/source.zip'
        self.receipt_path.write_bytes(public.encoded(receipt))
        with self.assertRaisesRegex(ValueError,'stored-asset-pin'):
            public.fetch(self.lock_path,self.receipt_path,self.output,self.api)
        self.assertEqual(self.downloads,[])
        with patch.object(public.release,'git_blob',return_value=b'changed'):
            with self.assertRaisesRegex(ValueError,'producer-git-blob-mismatch'):public.selection(self.lock_path)

    def test_existing_output_is_untouched_before_metadata_or_network_access(self):
        self.output.mkdir();(self.output/'save').write_bytes(b'keep')
        with patch.object(public,'selection') as selected,self.assertRaisesRegex(ValueError,'output-exists'):
            public.fetch(Path('/not-read'),Path('/not-read'),self.output,self.api)
        selected.assert_not_called();self.assertEqual((self.output/'save').read_bytes(),b'keep')


if __name__=='__main__':unittest.main()
