from contextlib import nullcontext
import copy
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from tools import wine_auth as auth, qualify_wine_arm64 as wine


class WineAuth(unittest.TestCase):
    def good(self):
        return dict(scope='linux-arm64-wine-grunt-synthetic-peer-only',qualified=True,privateOutputsRemoved=True,
            existingOutputsPreserved=True,privateSessionKeyMatched=True,receiptValidated=True,compiledServerQualified=False,
            gameInitializationStarted=False,worldEntryQualified=False,gameplayQualified=False,
            cases=[dict(mode=mode,exitCode=0 if mode=='valid' else 65,peerVerifiedClientProof=True,peerObservedClose=True)
                   for mode in auth.MODES])

    def test_all_synthetic_cases_private_key_cleanup_and_narrow_scope_required(self):
        good=self.good();self.assertTrue(auth.passed(good))
        for key,value in good.items():
            if type(value) is bool:
                with self.subTest(key=key):self.assertFalse(auth.passed(dict(good,**{key:not value})))
        for field,bad in (('exitCode',True),('peerVerifiedClientProof',False),('peerObservedClose',False),('mode','other')):
            changed=copy.deepcopy(good);changed['cases'][0][field]=bad
            with self.subTest(field=field):self.assertFalse(auth.passed(changed))
        self.assertFalse(auth.passed(dict(good,cases=good['cases'][:-1])))
        self.assertFalse(auth.passed(dict(good,cases=[None,*good['cases'][1:]])))

    def test_namespace_and_all_existing_cleanup_gates_still_apply(self):
        result=dict(displayReady=True,networkIsolated=True,prefixExit=0,wineStopExit=0,wineWaitExit=0,
            logStreamsDrained=True,logsWithinLimit=True,logWritesSucceeded=True,workerCompleted=True,expectedExit=0,clientAuth=self.good())
        key='linuxArm64ClientGruntSyntheticPeerQualified'
        self.assertTrue(wine.qualification_flags(result,[],client_auth=True)[key])
        self.assertFalse(wine.qualification_flags(result,[])[key])
        for name in ('networkIsolated','logStreamsDrained','logsWithinLimit','logWritesSucceeded','workerCompleted'):
            self.assertFalse(wine.qualification_flags(dict(result,**{name:False}),[],client_auth=True)[key])
        self.assertFalse(wine.qualification_flags(result,[],namespace_exit=-9,client_auth=True)[key])
        self.assertFalse(wine.qualification_flags(dict(result,wineWaitExit=1),[],client_auth=True)[key])
        with self.assertRaisesRegex(ValueError,'auth-check-requires-entry-offline-and-loopback'):
            wine.qualify(Path('/missing'),None,None,None,client_auth_source=Path('/missing'))

    def test_only_committed_matching_clean_source_can_be_staged_and_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'source';source.mkdir();fixture=root/'fixture';fixture.mkdir()
            def git(*args):return subprocess.check_output(['git',*args],cwd=source,text=True,stderr=subprocess.DEVNULL).strip()
            git('init');path=source/'Tools/PlatformTests/auth_peer.py';path.parent.mkdir(parents=True);path.write_text('FIXTURE_VALUE = 12340\n')
            git('add','.');git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
            revision=git('rev-parse','HEAD');identity=auth.prepare(source,revision,fixture)
            self.assertEqual(auth.load_peer(fixture,identity).FIXTURE_VALUE,12340)
            (fixture/auth.PEER).write_text('raise RuntimeError("must not execute changed source")\n')
            with self.assertRaisesRegex(ValueError,'source-changed'):auth.load_peer(fixture,identity)
            path.write_text('FIXTURE_VALUE = 1\n')
            with self.assertRaises(ValueError):auth.prepare(source,revision,root/'unused')

    def test_failure_removes_private_input_and_key_and_withholds_exception_text(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=Path(temporary);value=dict(username='EST0123456789ABCD',password='ABCDEFGHJKLMNPQR',fixtureId='01'*16)
            module=SimpleNamespace(credentials=lambda:value,Peer=lambda *_:nullcontext(object()))
            def fail(*args):
                self.assertEqual((fixture/auth.contract.INPUT).stat().st_size,57)
                (fixture/auth.contract.KEY).write_bytes(bytes(40))
                raise ValueError('private-password-or-session-key')
            observed={}
            with patch.object(auth,'load_peer',return_value=module),self.assertRaisesRegex(ValueError,'^actual-wine-grunt-synthetic-exchange-failed$'):
                auth.execute(fixture,fixture,'/fixture',{},observed,fail,lambda *_:['owned'],[])
            self.assertFalse((fixture/auth.contract.INPUT).exists());self.assertFalse((fixture/auth.contract.KEY).exists())
            self.assertTrue(observed['privateOutputsRemoved']);self.assertFalse(auth.passed(observed))


if __name__=='__main__':unittest.main()
