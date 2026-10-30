import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest import mock
from tools import client_auth_contract as contract
from tools import qualify_client_auth as qualifier


class ClientAuthQualification(unittest.TestCase):
    def test_worker_failure_locations_never_export_error_text_or_unowned_frames(self):
        try:
            qualifier.prepare_client(Path('/unused'),Path('/unused'),'invalid','private-secret',1,Path('/unused'))
        except Exception as error:
            locations=qualifier.failure_locations(error)
        self.assertTrue(locations)
        self.assertTrue(all(location.startswith('client-auth/') for location in locations))
        self.assertNotIn('private-secret',json.dumps(locations));self.assertNotIn('test_',json.dumps(locations))

    def test_readonly_source_verification_uses_exact_trust_and_no_index_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); revision='a'*40
            outputs=[(revision+'\n').encode(),b'H clean.cpp\0',b'',b'',b'']
            with mock.patch.object(qualifier.subprocess,'run',side_effect=[
                    subprocess.CompletedProcess([],0,stdout=raw,stderr=b'') for raw in outputs]) as run:
                qualifier.verify_readonly_client_source(root,revision)
            commands=[call.args[0] for call in run.call_args_list]
            self.assertEqual(len(commands),5)
            for call in run.call_args_list:
                self.assertIn('safe.directory='+str(root),call.args[0])
                self.assertEqual(call.kwargs['env']['GIT_OPTIONAL_LOCKS'],'0')
                self.assertEqual(call.kwargs['env']['GIT_NO_LAZY_FETCH'],'1')
                self.assertNotIn('write-tree',call.args[0]);self.assertNotIn('read-tree',call.args[0])
            self.assertIn('diff-index',commands[2]);self.assertIn('--cached',commands[2])
            self.assertIn('diff-files',commands[3])

    def test_readonly_source_rejects_hidden_changes_before_binary_or_namespace_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);revision='b'*40
            for hidden in (b'S hidden.cpp\0',b'h hidden.cpp\0'):
                with mock.patch.object(qualifier.subprocess,'run',side_effect=[
                        subprocess.CompletedProcess([],0,stdout=(revision+'\n').encode(),stderr=b''),
                        subprocess.CompletedProcess([],0,stdout=hidden,stderr=b'')]), \
                        self.assertRaisesRegex(ValueError,'hidden-index-flags'):
                    qualifier.verify_readonly_client_source(root,revision)

    def test_readonly_source_rejects_changed_index_worktree_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);revision='c'*40
            for failure in (2,3,4):
                results=[subprocess.CompletedProcess([],0,stdout=(revision+'\n').encode(),stderr=b''),
                    subprocess.CompletedProcess([],0,stdout=b'H source.cpp\0',stderr=b''),
                    subprocess.CompletedProcess([],0,stdout=b'',stderr=b''),
                    subprocess.CompletedProcess([],0,stdout=b'',stderr=b''),
                    subprocess.CompletedProcess([],0,stdout=b'',stderr=b'')]
                results[failure]=subprocess.CompletedProcess([],1 if failure<4 else 0,
                    stdout=b'extra.cpp\0' if failure==4 else b'',stderr=b'private error withheld')
                with self.subTest(failure=failure),mock.patch.object(qualifier.subprocess,'run',side_effect=results), \
                        self.assertRaises(ValueError) as caught:
                    qualifier.verify_readonly_client_source(root,revision)
                self.assertNotIn('private',str(caught.exception))

    def test_private_credentials_are_exact_bounded_exclusive_and_not_link_following(self):
        intent=dict(username='EST0123456789ABCD',password='ABCDEFGHJKLMNPQR')
        nonce=bytes(range(16))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);target=root/'input'
            contract.write_input(target,intent,nonce)
            raw=target.read_bytes();self.assertEqual(raw,b'ESTAUTH1'+nonce+intent['username'].encode()+intent['password'].encode())
            self.assertEqual(len(raw),57);self.assertEqual(target.stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):contract.write_input(target,intent,nonce)
            linked=root/'linked';linked.symlink_to(target)
            with self.assertRaises(OSError):contract.write_input(linked,intent,nonce)
            for field,bad in (('username','ADMIN'),('password','bad'),('username','EST0123456789abcd')):
                with self.assertRaises(ValueError):contract.write_input(root/'new',dict(intent,**{field:bad}),nonce)
            with self.assertRaises(ValueError):contract.write_input(root/'new',intent,bytes(15))

    def receipt(self,nonce):
        return dict(schemaVersion=1,scope='executable-grunt-authentication-only',architecture='ARM64',protocolBuild=12340,
            fixtureId=nonce.hex(),checks={name:True for name in contract.CHECKS},authentications=1,realms=1,realmId=1,
            worldEndpoint='127.0.0.1:8085',realmFlags=2,realmBuildPresent=False,privateSessionKeyBytes=40,
            versionChecksumQualified=False,commonMainStarted=False,assetsLoaded=False,compiledServerQualified=False,
            worldEntryQualified=False,gameplayQualified=False)

    def test_nonce_checks_types_and_scope_are_required_and_key_never_part_of_public_receipt(self):
        nonce=bytes(range(16));good=self.receipt(nonce)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);receipt=root/'receipt';receipt.write_text(json.dumps(good))
            result,digest=contract.read_receipt(receipt,nonce);self.assertEqual(result,good);self.assertEqual(len(digest),64)
            bad_cases=[('schemaVersion',True),('architecture','x64'),('fixtureId','ff'*16),('realmFlags',True),
                       ('realmBuildPresent',True),('commonMainStarted',True),('compiledServerQualified',True),
                       ('worldEndpoint','203.0.113.1:8085'),('privateSessionKeyBytes',0)]
            for name,value in bad_cases:
                receipt.write_text(json.dumps(dict(good,**{name:value})))
                with self.subTest(name=name),self.assertRaises(ValueError):contract.read_receipt(receipt,nonce)
            for name in contract.CHECKS:
                bad=copy.deepcopy(good);bad['checks'][name]=1;receipt.write_text(json.dumps(bad))
                with self.subTest(name=name),self.assertRaises(ValueError):contract.read_receipt(receipt,nonce)
            key=root/'key';key.write_bytes(bytes(range(40)));self.assertEqual(contract.read_key(key),bytes(range(40)))
            os.link(key,root/'key-link')
            with self.assertRaises(ValueError):contract.read_key(key)
            (root/'key-link').unlink();key.write_bytes(bytes(41))
            with self.assertRaises(ValueError):contract.read_key(key)
            self.assertNotIn('sessionKey',json.dumps(good))

    def test_arbitrary_private_log_and_crash_memory_are_withheld(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);private=root/'private';public=root/'public'
            private.write_bytes(b'password=private\nRegisters: private-session-key\n'
                b'FAIL: Esteria Grunt authentication check: private-account-key\n'+b'x'*4096+b'\n')
            contract.export_status(private,public)
            self.assertEqual(public.read_bytes(),b'FAIL: Esteria Grunt authentication check (private detail withheld)\n')

    def test_abnormal_exit_or_incomplete_cleanup_cannot_qualify_authentication(self):
        good=dict(formatVersion=1,scope=qualifier.SCOPE,phase='complete',cleanupFailures=[],expectedExit=0,workerCompleted=True,
            **{name:True for name in ('networkIsolated','ownedLoopbackListenerVerified','reconstructedClientAuthenticated',
                'persistedSessionKeyVerified','credentialsAndTrackersPreserved','schemaLedgerPreserved','cleanShutdownVerified',
                'privateKeyRemoved','logsComplete')},androidRuntimeQualified=False,worldEntryQualified=False,gameplayQualified=False)
        self.assertTrue(qualifier.typed_success(good,0))
        for status in (1,-9,137,False):self.assertFalse(qualifier.typed_success(good,status))
        for key,value in list(good.items()):
            if type(value) is bool:
                with self.subTest(key=key):self.assertFalse(qualifier.typed_success(dict(good,**{key:not value}),0))
        self.assertFalse(qualifier.typed_success(dict(good,cleanupFailures=['mysql']),0))
        self.assertFalse(qualifier.typed_success(dict(good,expectedExit=False),0))

    def test_worker_refuses_caller_namespace_before_reading_plan_or_starting_process(self):
        with mock.patch.object(qualifier.os,'getpid',return_value=42),mock.patch.object(qualifier.wine,'read_json') as read:
            with self.assertRaises(ValueError):qualifier.worker(Path('/no-plan'))
            read.assert_not_called()


if __name__=='__main__':unittest.main()
