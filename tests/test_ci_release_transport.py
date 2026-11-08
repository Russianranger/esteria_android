import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import ci_release_transport as ci
from tools import release_server_dependencies as github


class ExactCiAsset(unittest.TestCase):
    def setUp(self):
        self.name='fixture.zip'
        self.pin=dict(bytes=2,sha256='a' * 64)
        self.url='https://github.com/'+github.REPOSITORY+'/releases/download/test/'+self.name
        self.pub=dict(tag='test',targetCommit='b'*40,releaseId=23,
                      assets={self.name:dict(self.pin,url=self.url,assetId=17)})
        self.asset=dict(name=self.name,id=17,state='uploaded',browser_download_url=self.url,
                        size=2,digest='sha256:'+self.pin['sha256'])
        self.release=dict(tag_name='test',id=23,draft=False,assets=[self.asset])
        self.ref=dict(object=dict(type='commit',sha=self.pub['targetCommit'],
                                  url=github.API+'/git/commits/'+self.pub['targetCommit']))

    def run_case(self, url=None):
        selected=ci.LockedRelease(self.pub)
        with patch.object(selected,'json',side_effect=[self.release,self.ref]), \
                patch.object(github.Github,'download',autospec=True) as transfer, \
                patch.dict(os.environ,{'GITHUB_RUN_ID':'81','GITHUB_RUN_ATTEMPT':'2'}):
            selected.download(url or self.url, Path(self.name),self.pin)
            transfer.assert_called_once_with(selected,github.API+'/releases/assets/17?run=81-2',
                                            Path(self.name),self.pin)

    def test_uses_measured_rest_asset_and_original_checked_transfer(self):
        self.run_case()

    def test_changed_source_name_digest_size_or_id_cannot_download(self):
        for obj,key,new in [(self.asset,'size',1),(self.asset,'digest','sha256:'+'c'*64),
                (self.asset,'id',19),(self.release,'draft',True),(self.pub,'targetCommit','e'*40),
                (self.asset,'browser_download_url',self.url+'x')]:
            with self.subTest(key=key),patch.dict(obj,{key:new}),self.assertRaises(ValueError):
                self.run_case()
        with self.assertRaises(ValueError): self.run_case('https://other.invalid/a')

    def test_original_transfer_drops_authorization_on_redirect_and_verifies_bytes(self):
        from urllib.error import HTTPError
        import hashlib
        selected=github.Github('ci-test-token')
        calls=[]
        def opened(request,timeout):
            calls.append(request)
            if len(calls)==1:
                raise HTTPError(request.full_url,302,'redirect',{'Location':'https://controlled.githubusercontent.com/a'},None)
            return io.BytesIO(b'ok')
        with TemporaryDirectory() as work,patch.object(selected.opener,'open',side_effect=opened):
            path=Path(work)/self.name
            selected.download(github.API+'/releases/assets/17',path,dict(bytes=2,sha256=hashlib.sha256(b'ok').hexdigest()))
            self.assertEqual(path.read_bytes(),b'ok')
        self.assertEqual(calls[0].get_header('Authorization'),'Bearer ci-test-token')
        self.assertIsNone(calls[1].get_header('Authorization'))

class UpstreamOriginals(unittest.TestCase):
    def test_pinned_id_and_redirect_bytes_only(self):
        from urllib.error import HTTPError
        from unittest.mock import Mock
        import hashlib
        class Payload(io.BytesIO):
            headers={'Content-Length':'2'}
            def geturl(self):
                return 'https://a.githubusercontent.com/object'
        name='artifact.zip'
        src='https://github.com/Russianranger/wowdecomp_esteria/releases/download/verified/'+name
        pin=dict(bytes=2,sha256=hashlib.sha256(b'ok').hexdigest())
        opener=Mock()
        opener.open.side_effect=[HTTPError('',302,'Redirect',{'Location':'https://a.githubusercontent.com/object'},None),Payload(b'ok')]
        with TemporaryDirectory() as work,patch.object(ci,'build_opener',return_value=opener),patch.dict(os.environ,{'CI_PUBLIC_RELEASE_TOKEN':'test'}):
            actual=ci.fetch_external('Russianranger/wowdecomp_esteria',42,src,pin,Path(work)/name)
            self.assertEqual(actual.read_bytes(),b'ok')
            first,second=[call.args[0] for call in opener.open.call_args_list]
            self.assertIn('api.github.com/repos/Russianranger/wowdecomp_esteria/releases/assets/42?',first.full_url)
            self.assertEqual(first.get_header('Authorization'),'Bearer test')
            self.assertIsNone(second.get_header('Authorization'))
            bad=HTTPError('',302,'Redirect',{'Location':'https://releases.not-github.invalid/wrong'},None)
            opener.open.side_effect=[bad]
            with self.assertRaisesRegex(ValueError,'redirect'):
                ci.fetch_external('Russianranger/wowdecomp_esteria',42,src,pin,Path(work)/'other.zip')
            self.assertFalse((Path(work)/'other.zip').exists())

    def test_client_original_and_both_source_files_are_release_bound(self):
        build=github.small_json(ci.ROOT/'runtime/client/stock-renderer-build.lock.json')
        with patch.object(ci,'fetch_external') as transfer:
            ci.client_inputs(Path('/tmp/verified-client'),build['sourceRevision'],build)
            self.assertEqual({call.args[1] for call in transfer.call_args_list},{723347201,723347284,723347318})
        with patch.dict(build,artifactId=build['artifactId']-1),self.assertRaisesRegex(ValueError,'source-mismatch'):
            ci.client_inputs(Path('/tmp/verified-client'),build['sourceRevision'],build)
