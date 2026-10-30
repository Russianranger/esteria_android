import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_local_account as qualification
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm


class AccountFixtureGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.fixture = self.root / 'fixture'
        self.fixture.mkdir()
        self.pin = {'commit': realm.SERVER_REVISION, 'patches': []}
        self.lock_hash = 'f' * 64
        self.rows = {}
        for name in qualification.INPUTS:
            raw = ('exact source ' + name).encode()
            path = self.fixture / 'source' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.rows[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(),
                gitBlob=hashlib.sha1(('blob ' + str(len(raw)) + '\0').encode() + raw).hexdigest())
        self.manifest = dict(formatVersion=1, scope='pinned-local-account-fixture', source=self.pin,
                             sourceLockSha256=self.lock_hash, files=self.rows)
        self.patches = [patch.object(qualification.base, 'locked_source', return_value=(self.pin, self.lock_hash)),
                        patch.object(account, 'ACCOUNT_SCHEMA_SHA256', self.rows['data/sql/base/db_auth/account.sql']['sha256']),
                        patch.object(account, 'TRACKER_SCHEMA_SHA256', self.rows['data/sql/base/db_auth/realmcharacters.sql']['sha256']),
                        patch.object(realm, 'SCHEMA_SHA256', self.rows['data/sql/base/db_auth/realmlist.sql']['sha256'])]
        for mocked in self.patches:
            mocked.start(); self.addCleanup(mocked.stop)

    def save(self):
        raw = json.dumps(self.manifest).encode()
        (self.fixture / 'account-fixture.json').write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    def copy(self, digest):
        return qualification.copy_fixture(self.fixture, digest, self.root / 'source.lock', self.root / 'copied')

    def test_verified_exact_auth_and_real_config_inputs_are_copied(self):
        self.assertEqual(self.copy(self.save()), self.manifest)
        self.assertEqual(len(list((self.root / 'copied').rglob('*.sql'))), 22)
        self.assertEqual(len(list((self.root / 'copied').rglob('*.conf.dist'))), 3)
        for name in qualification.INPUTS:
            self.assertEqual((self.fixture / 'source' / name).read_bytes(), (self.root / 'copied' / name).read_bytes())

    def test_external_digest_and_exact_input_set_fail_before_source_copy(self):
        self.save()
        with self.assertRaisesRegex(ValueError, 'manifest digest'):
            self.copy('0' * 64)
        self.assertFalse((self.root / 'copied').exists())
        self.manifest['files']['../../escape.sql'] = self.manifest['files'].pop(qualification.INPUTS[0])
        with self.assertRaisesRegex(ValueError, 'provenance mismatch'):
            self.copy(self.save())
        self.assertFalse((self.root / 'copied').exists())

    def test_tampered_source_and_git_blob_identity_are_rejected(self):
        first = qualification.INPUTS[0]
        (self.fixture / 'source' / first).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source type/size'):
            self.copy(self.save())

    def test_changed_git_identity_fails_even_with_correct_sha256(self):
        self.manifest['files'][qualification.INPUTS[0]]['gitBlob'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'source hash mismatch'):
            self.copy(self.save())

    def test_existing_output_never_starts_mysql_or_reads_fixture(self):
        destination = self.root / 'existing'
        destination.mkdir()
        (destination / 'keep').write_bytes(b'unchanged')
        with patch.object(qualification, 'copy_fixture', side_effect=AssertionError('must not load')):
            with self.assertRaisesRegex(ValueError, 'existing qualification preserved'):
                qualification.run(Path('/bin/mysql'), Path('/bin/mysqld'), self.fixture, 'a'*64,
                                  self.root / 'lock', destination, '8.0.46')
        self.assertEqual((destination / 'keep').read_bytes(), b'unchanged')


if __name__ == '__main__':
    unittest.main()
