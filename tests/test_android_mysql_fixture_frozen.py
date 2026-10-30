"""Actual Git/blob/EOL guards; no fixture archive download or SQL execution."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from tools import fetch_android_mysql_fixture_frozen as frozen


class AndroidMysqlFrozenConsumer(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.checkout=self.root/'recipe';self.checkout.mkdir()
        self.git('init','-q');self.git('config','user.name','Fixture');self.git('config','user.email','fixture@example.invalid')
        self.git('config','core.autocrlf','false');self.git('config','core.filemode','true')
        (self.checkout/'.gitattributes').write_text('* text=auto eol=lf\n*.bat text eol=crlf\n')
        (self.checkout/'.gitignore').write_text('ignored/\n')
        (self.checkout/'fixture.py').write_text('print("source fixture only")\n')
        (self.checkout/'fixture.sh').write_text('#!/bin/sh\nexit 0\n');(self.checkout/'fixture.sh').chmod(0o755)
        (self.checkout/'gradlew.bat').write_bytes(b'@echo off\nexit /b 0\n')
        (self.checkout/'binary.bin').write_bytes(bytes(range(256)))
        self.git('add','.');self.git('commit','-qm','Synthetic checkout only; never executed')
        self.revision=self.git('rev-parse','HEAD').strip()

    def git(self,*arguments):
        return subprocess.check_output(['git','-C',str(self.checkout),*arguments],stderr=subprocess.DEVNULL,text=True)

    def test_actual_tiny_git_tree_verifies_every_blob_binary_file_and_mode(self):
        value=frozen._verify_checkout(self.checkout,self.revision)
        self.assertEqual(value['fileCount'],6);self.assertTrue(value['allTrackedGitAndCheckoutBytesVerified'])
        self.assertEqual(value['files']['binary.bin']['sha256'],frozen.identity(bytes(range(256)))['sha256'])
        self.assertEqual(value['files']['fixture.sh']['mode'],0o100755)
        self.assertEqual(value['validatedCheckoutConversions'],[])

    def test_only_explicit_bat_checkout_conversion_is_accepted(self):
        path=self.checkout/'gradlew.bat';path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
        value=frozen._verify_checkout(self.checkout,self.revision)
        self.assertEqual([row['path'] for row in value['validatedCheckoutConversions']],['gradlew.bat'])
        # Git's clean filter permits CRLF Python text, but executable consumer
        # source must still match canonical Git bytes exactly.
        path=self.checkout/'fixture.py';path.write_bytes(path.read_bytes().replace(b'\n',b'\r\n'))
        with self.assertRaisesRegex(ValueError,'working-file-bytes'):frozen._verify_checkout(self.checkout,self.revision)

    def test_changed_commit_or_tracked_file_or_staged_change_is_refused(self):
        with self.assertRaisesRegex(ValueError,'checkout-revision'):frozen._verify_checkout(self.checkout,'a'*40)
        path=self.checkout/'fixture.py';original=path.read_bytes();path.write_bytes(original+b'# changed\n')
        with self.assertRaises(ValueError):frozen._verify_checkout(self.checkout,self.revision)
        self.git('add','fixture.py')
        with self.assertRaises(ValueError):frozen._verify_checkout(self.checkout,self.revision)

    def test_ignored_python_shadow_file_is_untracked_and_refused(self):
        folder=self.checkout/'ignored';folder.mkdir();(folder/'shadow.py').write_text('raise RuntimeError("never execute")\n')
        self.assertEqual(self.git('status','--porcelain'),'')
        with self.assertRaisesRegex(ValueError,'untracked-files'):frozen._verify_checkout(self.checkout,self.revision)

    def test_hidden_assume_unchanged_or_skip_worktree_flags_are_refused(self):
        for flag in ('--assume-unchanged','--skip-worktree'):
            self.git('update-index',flag,'fixture.py')
            with self.subTest(flag=flag),self.assertRaisesRegex(ValueError,'hidden-index-flags'):
                frozen._verify_checkout(self.checkout,self.revision)
            self.git('update-index','--no-assume-unchanged','--no-skip-worktree','fixture.py')

    def test_executable_mode_is_checked_even_when_git_ignores_mode_drift(self):
        self.git('config','core.filemode','false');(self.checkout/'fixture.sh').chmod(0o644)
        self.assertEqual(self.git('status','--porcelain'),'')
        with self.assertRaisesRegex(ValueError,'working-file-mode-or-identity'):frozen._verify_checkout(self.checkout,self.revision)

    def test_metadata_selection_preserves_original_producer_without_old_code_or_git(self):
        with patch.object(frozen,'_verify_checkout') as checkout,patch.object(frozen.subprocess,'run') as run:
            value=frozen.input_selection()
        self.assertEqual(value['producer']['workflowRun'],41109642918)
        self.assertEqual(value['producer']['integrationRevision'],'4fd32df287961b9cc5175213a6fe85eac1c6d868')
        self.assertFalse(value['productionAdapterQualified']);self.assertFalse(value['serverSchemasQualified'])
        checkout.assert_not_called();run.assert_not_called()

    def test_nonfrozen_checkout_cannot_run_script_or_create_acquisition_output(self):
        output=self.root/'absent'
        with patch.object(frozen.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'checkout-revision'):
            frozen.acquire(self.checkout,output)
        run.assert_not_called();self.assertFalse(output.exists())

    def test_python_injection_removed_while_authorized_auth_and_proxy_settings_survive(self):
        with patch.dict(os.environ,{'PYTHONPATH':'unverified','PYTHONHOME':'unverified',
                'GITHUB_TOKEN':'fixture-not-a-real-token','HTTPS_PROXY':'http://fixture.invalid:8080','SSL_CERT_FILE':'/fixture/ca.pem'}):
            value=frozen._environment()
        self.assertNotIn('PYTHONPATH',value);self.assertNotIn('PYTHONHOME',value)
        self.assertEqual(value['PYTHONDONTWRITEBYTECODE'],'1')
        self.assertEqual(value['GITHUB_TOKEN'],'fixture-not-a-real-token')
        self.assertEqual(value['HTTPS_PROXY'],'http://fixture.invalid:8080');self.assertEqual(value['SSL_CERT_FILE'],'/fixture/ca.pem')


if __name__=='__main__':unittest.main()
