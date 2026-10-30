import copy
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock
from tools import fetch_wine_cohort as consumer


class PublicCohort(unittest.TestCase):
    def fixture(self):
        release=consumer.release
        lock=dict(formatVersion=1,scope=release.SCOPE,repository=release.wine.shared.REPOSITORY,tag=release.TAG,
            targetCommit='a'*40,selectedInputs=release.selected_inputs(),recipeInputs={},
            files={name:dict(bytes=1,sha256='b'*64) for name in release.PAYLOAD})
        expected=consumer.expected_assets(lock);base='https://github.com/'+lock['repository']+'/releases/'
        receipt=dict(formatVersion=1,repository=lock['repository'],tag=lock['tag'],targetCommit=lock['targetCommit'],
            publisherNeverOverwrites=True,releaseId=123,url=base+'tag/'+lock['tag'],githubImmutable=False,
            assets={name:dict(pin,url=base+'download/'+lock['tag']+'/'+name) for name,pin in expected.items()})
        row=dict(id=123,draft=False,prerelease=True,tag_name=lock['tag'],body=release.body(lock),immutable=False,
            assets=[dict(name=name,state='uploaded',size=pin['bytes'],digest='sha256:'+pin['sha256'],browser_download_url=receipt['assets'][name]['url'])
                    for name,pin in expected.items()])
        ref=dict(object=dict(type='commit',sha=lock['targetCommit']))
        return lock,expected,receipt,row,ref

    def test_live_tag_asset_digest_and_original_public_urls_must_all_match(self):
        lock,pins,receipt,row,ref=self.fixture();api=mock.Mock()
        for failure in (None,'tag','target','digest','url','draft','extra'):
            changed=copy.deepcopy(row);target=copy.deepcopy(ref)
            if failure=='tag':changed['tag_name']='old-tag'
            if failure=='target':target['object']['sha']='c'*40
            if failure=='digest':changed['assets'][0]['digest']='sha256:'+'0'*64
            if failure=='url':changed['assets'][0]['browser_download_url']='https://other.invalid/file'
            if failure=='draft':changed['draft']=True
            if failure=='extra':changed['assets'].append(dict(changed['assets'][0]))
            api.json.side_effect=lambda path:target if path.startswith('/git/ref/') else changed
            if failure is None:consumer.public_identity(api,lock,receipt,pins)
            else:
                with self.subTest(failure=failure),self.assertRaises(ValueError):consumer.public_identity(api,lock,receipt,pins)

    def test_receipt_cannot_claim_a_different_asset_roster_or_overwrite_policy(self):
        lock,pins,receipt,row,ref=self.fixture();api=mock.Mock()
        for field,value in [('publisherNeverOverwrites',False),('formatVersion',True),('assets',{})]:
            bad=dict(receipt,**{field:value})
            with self.assertRaises(ValueError):consumer.public_identity(api,lock,bad,pins)
        api.json.assert_not_called()

    def test_existing_output_or_provider_is_preserved_before_any_network_or_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);existing=root/'existing';existing.mkdir();(existing/'sentinel').write_bytes(b'keep')
            api=mock.Mock()
            with mock.patch.object(consumer,'selection',side_effect=AssertionError('existing output consumed')):
                for output,providers in [(existing,None),(root/'new',existing)]:
                    with self.assertRaises(ValueError):consumer.fetch(root/'lock',root/'receipt',root,output,providers,api)
            api.json.assert_not_called();self.assertEqual((existing/'sentinel').read_bytes(),b'keep')

    def test_recipe_subprocess_receives_no_application_token_or_source_bytecode_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/'lock';lock.write_text('{}')
            result=mock.Mock(returncode=0,stdout=b'{}',stderr=b'')
            with mock.patch.dict(consumer.os.environ,{'GITHUB_TOKEN':'private','PYTHONPATH':'untrusted'}), \
                    mock.patch.object(consumer.subprocess,'run',return_value=result) as run:
                self.assertEqual(consumer.recipe_verify(root,lock,root),{})
            args=run.call_args
            self.assertNotIn('GITHUB_TOKEN',args.kwargs['env']);self.assertNotIn('PYTHONPATH',args.kwargs['env'])
            self.assertEqual(args.kwargs['env']['GIT_NO_LAZY_FETCH'],'1')
            self.assertIn('-B',args.args[0]);self.assertTrue(any(x.startswith('pycache_prefix=') for x in args.args[0]))

    def test_original_producer_history_is_required_in_its_own_recipe_checkout_before_network(self):
        lock,_,_,_,_=self.fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'lock.json';path.write_bytes(consumer.encoded(lock))
            for producer in (subprocess.CalledProcessError(128,['git','cat-file'],stderr=b'private detail'),b'blob\n'):
                def query(command,**kwargs):
                    if 'rev-parse' in command:return (lock['targetCommit']+'\n').encode()
                    if isinstance(producer,Exception):raise producer
                    return producer
                with mock.patch.object(consumer.subprocess,'check_output',side_effect=query),self.assertRaisesRegex(ValueError,'producer') as caught:
                    consumer.selection(path,root)
                self.assertNotIn('private detail',str(caught.exception))


if __name__=='__main__':unittest.main()
