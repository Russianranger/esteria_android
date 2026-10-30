import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime import mysql_bootstrap as db
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm

RECEIPT = {'uuid': '12345678-1234-1234-1234-123456789012', 'version': '8.0.46-0ubuntu0.24.04.4'}


class Transaction:
    """Small row fixture tests transaction/ownership decisions, not a SQL engine."""
    def __init__(self, intent, *, existing=False, tracker=True):
        self.intent = intent
        self.present = existing
        self.tracker = tracker
        self.calls = []
        self.fail_tracker_insert = False

    def query(self, sql):
        self.calls.append(sql)
        if sql == 'START TRANSACTION':
            self.before = (self.present, self.tracker)
        elif sql == 'ROLLBACK':
            self.present, self.tracker = self.before
        elif sql.startswith(realm.ROW_SQL):
            return [realm.EXPECTED_ROW]
        elif sql.startswith('SELECT id,username,'):
            return ['7\t' + self.intent['username'] + '\t' + self.intent['saltHex'] + '\t' + self.intent['verifierHex']] if self.present else []
        elif sql.startswith('INSERT INTO acore_auth.account '):
            self.present = True
        elif sql.startswith('INSERT INTO acore_auth.realmcharacters '):
            if self.fail_tracker_insert:
                raise db.BootstrapError('simulated insert failure')
            self.tracker = True
        elif sql.startswith('SELECT numchars '):
            return ['4'] if self.tracker else []
        return []


class AccountGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        self.intent = account.new_intent(RECEIPT)
        self.path = self.state / account.JOURNAL

    def test_source_srp_vector_and_ascii_case(self):
        expected = '8d228fd2f89a39f80b6c27cf32bbcc9218e7026868bb5162fe6916785cb5450b'
        self.assertEqual(account.verifier('Admin', 'password', bytes(range(32))).hex(), expected)
        self.assertEqual(account.verifier('ADMIN', 'PASSWORD', bytes(range(32))).hex(), expected)
        self.assertNotEqual(account.verifier('Admin', 'pässword', bytes(range(32))),
                            account.verifier('Admin', 'pÄssword', bytes(range(32))))
        self.assertNotEqual(account.verifier('Admin', 'passw0rd', bytes(range(32))).hex(), expected)
        for username, password, salt in [('a' * 18, 'b', bytes(32)), ('a', 'b' * 17, bytes(32)), ('a', 'b', bytes(31))]:
            with self.assertRaises(db.BootstrapError):
                account.verifier(username, password, salt)

    def test_generated_credentials_are_private_and_bound_to_exact_instance(self):
        account.validate_intent(self.intent, RECEIPT)
        self.assertEqual(len(self.intent['username']), 17)
        self.assertEqual(len(self.intent['password']), 16)
        db.atomic_json(self.path, self.intent)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(account.read_intent(self.path, RECEIPT), self.intent)
        for key, value in [('mysqlUuid', 'other'), ('mysqlVersion', '8.99.99'), ('username', "'OR 1=1"),
                           ('password', 'A' * 16), ('phase', 'ready')]:
            altered = self.intent | {key: value}
            with self.subTest(key=key), self.assertRaises(db.BootstrapError):
                account.validate_intent(altered, RECEIPT)

    def test_corrupt_shared_and_symlink_credentials_are_preserved(self):
        db.atomic_json(self.path, self.intent)
        original = self.path.read_bytes()
        os.chmod(self.path, 0o644)
        with self.assertRaises(db.BootstrapError):
            account.read_intent(self.path, RECEIPT)
        self.assertEqual(self.path.read_bytes(), original)
        os.chmod(self.path, 0o600)
        other = self.state / 'other'
        os.link(self.path, other)
        with self.assertRaises(db.BootstrapError):
            account.read_intent(self.path, RECEIPT)
        other.unlink()
        self.path.unlink()
        self.path.symlink_to(other)
        with self.assertRaises(db.BootstrapError):
            account.read_intent(self.path, RECEIPT)

    def test_new_account_journals_before_insert_and_repeat_never_mutates_sql(self):
        connection = Transaction(self.intent)
        original = connection.query
        def query(sql):
            if sql.startswith('INSERT INTO acore_auth.account'):
                self.assertEqual(account.read_intent(self.path, RECEIPT), self.intent)
            return original(sql)
        connection.query = query
        with patch.object(account, 'new_intent', return_value=self.intent):
            self.assertEqual(account.configure_account(connection, self.state, RECEIPT), 'created-owned-account')
        completed = self.path.read_bytes()
        connection.calls.clear()
        self.assertEqual(account.configure_account(connection, self.state, RECEIPT), 'verified-owned-account')
        self.assertEqual(self.path.read_bytes(), completed)
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE')) for sql in connection.calls))

    def test_arbitrary_existing_name_never_adopted(self):
        connection = Transaction(self.intent, existing=True)
        with patch.object(account, 'new_intent', return_value=self.intent), self.assertRaisesRegex(db.BootstrapError, 'already exists'):
            account.configure_account(connection, self.state, RECEIPT)
        self.assertFalse(self.path.exists())
        self.assertEqual(connection.calls[-1], 'ROLLBACK')

    def test_unknown_commit_recovers_only_exact_intent(self):
        db.atomic_json(self.path, self.intent)
        connection = Transaction(self.intent, existing=True)
        self.assertEqual(account.configure_account(connection, self.state, RECEIPT), 'recovered-owned-commit')
        self.assertEqual(account.read_intent(self.path, RECEIPT)['accountId'], 7)
        self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE')) for sql in connection.calls))
        db.atomic_json(self.path, self.intent)
        connection.intent = self.intent | {'saltHex': '00' * 32}
        with self.assertRaisesRegex(db.BootstrapError, 'refusing adoption'):
            account.configure_account(connection, self.state, RECEIPT)
        self.assertEqual(account.read_intent(self.path, RECEIPT)['phase'], 'pending')

    def test_completed_missing_account_or_tracker_never_recreated(self):
        db.atomic_json(self.path, self.intent | {'phase': 'ready', 'accountId': 7})
        for existing, tracker in [(False, True), (True, False)]:
            connection = Transaction(self.intent, existing=existing, tracker=tracker)
            with self.subTest(existing=existing), self.assertRaises(db.BootstrapError):
                account.configure_account(connection, self.state, RECEIPT)
            self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE')) for sql in connection.calls))

    def test_tracker_failure_rolls_back_new_account_but_preserves_intent(self):
        connection = Transaction(self.intent)
        connection.fail_tracker_insert = True
        with patch.object(account, 'new_intent', return_value=self.intent), self.assertRaises(db.BootstrapError):
            account.configure_account(connection, self.state, RECEIPT)
        self.assertFalse(connection.present)
        self.assertEqual(account.read_intent(self.path, RECEIPT)['phase'], 'pending')

    def test_orphan_permissions_or_character_state_refuses_new_account(self):
        for failure in ('auth', 'characters'):
            calls = []
            class Connection:
                def query(self, sql):
                    calls.append(sql)
                    if 'information_schema.TABLES' in sql:
                        return ['characters', 'account_data', 'account_instance_times', 'account_tutorial']
                    if (failure == 'auth' and 'account_access' in sql) or (failure == 'characters' and 'acore_characters.' in sql):
                        return ['7']
                    return []
            with self.subTest(failure=failure), self.assertRaisesRegex(db.BootstrapError, 'refusing inheritance'):
                account.reject_orphan_state(Connection(), 7)
            self.assertTrue(all(sql.startswith('SELECT ') for sql in calls))

    def test_verify_missing_or_pending_does_not_create(self):
        connection = Transaction(self.intent)
        with self.assertRaises(db.BootstrapError):
            account.configure_account(connection, self.state, RECEIPT, verify_only=True)
        self.assertFalse(connection.calls)
        db.atomic_json(self.path, self.intent)
        for exists in (False, True):
            connection = Transaction(self.intent, existing=exists)
            with self.assertRaises(db.BootstrapError):
                account.configure_account(connection, self.state, RECEIPT, verify_only=True)
            self.assertFalse(any(sql.startswith(('INSERT', 'UPDATE', 'REPLACE', 'DELETE', 'COMMIT')) for sql in connection.calls))

    def test_schema_guards_are_read_only_and_reject_drift(self):
        responses = []
        for table, columns in account.COLUMNS.items():
            responses.extend([['InnoDB\tutf8mb4_unicode_ci'],
                              ['\t'.join(c) + '\t' + ('utf8mb4_unicode_ci' if c[1].startswith('varchar(') else '<NULL>') for c in columns],
                              [value + '\t<NULL>' for value in account.INDEXES[table]], ['0'], ['0']])
        class Connection:
            def __init__(self, values):
                self.values = iter(values)
                self.calls = []
            def query(self, sql):
                self.calls.append(sql)
                return next(self.values)
        account.check_schema(Connection(responses))
        for i in range(len(responses)):
            changed = copy.deepcopy(responses)
            changed[i] = ['unexpected']
            conn = Connection(changed)
            with self.subTest(i=i), self.assertRaises(db.BootstrapError):
                account.check_schema(conn)
            self.assertTrue(all(sql.startswith('SELECT ') for sql in conn.calls))
        collation = copy.deepcopy(responses)
        collation[1][1] = collation[1][1].replace('utf8mb4_unicode_ci', 'utf8mb4_bin')
        prefix = copy.deepcopy(responses)
        prefix[2][1] = prefix[2][1].replace('<NULL>', '16')
        for changed in (collation, prefix):
            with self.assertRaises(db.BootstrapError):
                account.check_schema(Connection(changed))

    def test_source_create_fragments_have_no_data_mutation(self):
        for name, digest, fragment in [
            ('account', account.ACCOUNT_SCHEMA_SHA256, '98fa6cbbc1dca7ab12e583b3c6d9d7e3c735a20f144bfd44c69d734ae6480a64'),
            ('realmcharacters', account.TRACKER_SCHEMA_SHA256, '15b3db391a9c3a572d475981427bb925590384ccccd94242132f1981fca0c49e')]:
            raw = (Path(__file__).parent / 'fixtures' / (name + '-f35f04d.sql')).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), fragment)
            text = raw.decode()
            self.assertIn(realm.SERVER_REVISION, text)
            self.assertIn(digest, text)
            statements = '\n'.join(line for line in text.splitlines() if not line.startswith('--'))
            self.assertTrue(statements.startswith('CREATE TABLE `' + name + '`'))
            self.assertNotIn('DROP TABLE', statements)
            self.assertNotIn('INSERT INTO', statements)


if __name__ == '__main__':
    unittest.main()
