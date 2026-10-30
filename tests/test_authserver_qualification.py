import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db
from tools import qualify_authserver as auth


class AuthserverGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def proc(self, endpoint='0100007F:0E8C', inode='123', ipv6=False):
        root = self.root / 'proc'; process = root / '52'
        (process/'fd').mkdir(parents=True, exist_ok=True)
        (process/'net').mkdir(exist_ok=True)
        link = process/'fd/7'; link.unlink(missing_ok=True); link.symlink_to('socket:[123]')
        line = '0: '+endpoint+' 00000000:0000 0A 0:0 00:0 0 0 0 '+inode+'\n'
        (process/'net/tcp').write_text('header\n' + ('' if ipv6 else line))
        (process/'net/tcp6').write_text('header\n' + (line if ipv6 else ''))
        return root

    def test_listener_must_belong_to_child_and_be_loopback_ipv4_only(self):
        self.assertTrue(auth.owns_listener(52, proc=self.proc()))
        self.assertFalse(auth.owns_listener(52, proc=self.proc(inode='999')))
        for endpoint, ipv6 in [('00000000:0E8C',False),('0100007F:FFFF',False),('00000000:0E8C',True)]:
            with self.subTest(endpoint=endpoint,ipv6=ipv6), self.assertRaises(ValueError):
                auth.owns_listener(52,proc=self.proc(endpoint=endpoint,ipv6=ipv6))

    def test_redacted_export_never_contains_account_or_session_material(self):
        state = self.root/'private'; output = self.root/'evidence'; output.mkdir()
        (state/'logs').mkdir(parents=True); (state/'accounts').mkdir()
        credentials = dict(username='EST1234567890ABCD',password='ABCDEFGHIJKLMNOP',saltHex='a'*64,verifierHex='b'*64)
        db.atomic_json(state/auth.account.JOURNAL, credentials)
        (state/'accounts/database-secret').write_text('c'*64+'\n')
        session = 'd'*80
        (state/'logs/authserver-private.log').write_text(' '.join([*credentials.values(),'c'*64,session,'safe failure']))
        auth.export_auth_log(state,output,(session,))
        redacted = (output/'authserver-redacted.log').read_text()
        self.assertIn('safe failure',redacted)
        for value in [*credentials.values(),'c'*64,session]: self.assertNotIn(value,redacted)

    @unittest.skipUnless(os.name=='posix','process-group ownership requires POSIX')
    def test_owned_capture_is_bounded_private_and_cleanly_stopped(self):
        executable=self.root/'authserver'; configuration=self.root/'authserver.conf'; log=self.root/'private.log'
        configuration.write_text('private-data-never-in-argv')
        executable.write_text('#!/usr/bin/python3\nimport signal,sys,time\n'
            'signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))\n'
            'print("x"*400000+"END",flush=True)\nwhile True:time.sleep(.1)\n')
        executable.chmod(0o700)
        capture=auth.OwnedAuthserver(executable,configuration,log)
        try:
            deadline=time.monotonic()+5
            while not log.exists() or b'END' not in log.read_bytes():
                self.assertLess(time.monotonic(),deadline);time.sleep(.02)
            self.assertLessEqual(log.stat().st_size,auth.LOG_LIMIT)
            self.assertEqual(log.stat().st_mode&0o777,0o600)
            self.assertNotIn('private-data-never-in-argv',' '.join(capture.process.args))
        finally: capture.stop()
        self.assertEqual(capture.process.returncode,0)

    def test_failed_fresh_updater_never_starts_authserver(self):
        with (patch.object(auth.importer,'run',side_effect=ValueError('new fixture required')),
              patch.object(auth,'OwnedAuthserver',side_effect=AssertionError('must not start'))):
            with self.assertRaises(ValueError):
                auth.run(Path('/install'),Path('/content'),'a'*64,Path('/lock'),Path('/mysql'),Path('/mysqld'),'8.0.46',self.root/'new')

    def test_natural_readiness_failure_retains_leader_until_owned_cleanup(self):
        executable=self.root/'authserver'; configuration=self.root/'authserver.conf'
        configuration.write_text('fixture')
        executable.write_text('#!/usr/bin/python3\nprint("failed",flush=True)\nraise SystemExit(9)\n')
        executable.chmod(0o700)
        capture=auth.OwnedAuthserver(executable,configuration,self.root/'private.log')
        try:
            self.assertEqual(capture.group.wait(5),9)
            with self.assertRaisesRegex(ValueError,'exited before readiness'):
                auth.wait_authserver(capture)
            self.assertIsNone(capture.process.returncode)
        finally:
            with self.assertRaisesRegex(ValueError,'failed startup/shutdown'):capture.stop()
        self.assertEqual(capture.process.returncode,9)
        with patch('tools.owned_process_group.os.killpg') as kill:
            with self.assertRaisesRegex(ValueError,'failed startup/shutdown'):capture.stop()
            kill.assert_not_called()


if __name__=='__main__':unittest.main()
