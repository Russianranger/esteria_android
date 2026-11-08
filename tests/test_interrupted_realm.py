import tempfile
import unittest
from pathlib import Path

from runtime import server_session as session


class RealmConnection:
    """Model the transaction and the fixed queries. Real native lifecycle is qualified separately."""
    def __init__(self, flag):
        self.flag = str(flag)
        self.ids = ['1']
        self.endpoint = [session.realm.EXPECTED_ROW]
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        self.pending = None
        self.updates = 0
        self.fail_after_update = False
        self.locked = False
        self.before_row_lock = None
        self.snapshot = None

    def query(self, sql):
        if sql.startswith('SELECT GET_LOCK'):
            assert not self.locked
            self.locked = True
            return ['1']
        if sql.startswith('SELECT RELEASE_LOCK'):
            assert self.locked
            self.locked = False
            return ['1']
        if sql == 'SELECT @@server_uuid':
            return [self.uuid]
        if 'ORDER BY `id` FOR UPDATE' in sql:
            assert self.locked and self.pending is not None
            if self.before_row_lock:
                self.before_row_lock(self)
                self.pending = self.flag
            return self.ids
        if sql == session.realm.ROW_SQL + ' FOR UPDATE':
            assert self.locked and self.pending is not None
            return self.endpoint
        if sql == session.realm.ROW_SQL:
            return self.snapshot[0] if self.pending is not None else self.endpoint
        if sql.startswith('SELECT `flag` FROM'):
            if self.pending is None:
                return [self.flag]
            if sql.endswith(' FOR UPDATE') or self.pending == '2':
                return [self.pending]
            return [self.snapshot[1]]
        if sql == 'START TRANSACTION':
            assert self.locked and self.pending is None
            self.pending = self.flag
            self.snapshot = self.endpoint[:], self.flag
        elif sql.startswith('UPDATE '):
            assert self.locked and self.pending in ('1','3')
            assert sql == 'UPDATE `acore_auth`.`realmlist` SET `flag`=2 WHERE `id`=1 AND `flag` IN (1,3)'
            self.pending = '2'
            self.updates += 1
            if self.fail_after_update:
                raise InterruptedError('test interruption before commit')
        elif sql == 'COMMIT':
            self.flag,self.pending = self.pending,None
        elif sql == 'ROLLBACK':
            self.pending = None
        else:
            raise AssertionError(sql)
        return []


class InterruptedRealmTests(unittest.TestCase):
    def recover(self, state, connection, lease, **changes):
        args = dict(expected_uuid=connection.uuid,verify_service=lambda: True,state_lease=lease)
        args.update(changes)
        return session.recover_interrupted_realm(connection,state,**args)

    def test_interrupted_world_and_failed_auth_reenter_offline_without_repeating_mutation(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)
            for original in (1,3):
                with self.subTest(original=original), session.db.state_lock(state) as lease:
                    connection=RealmConnection(original)
                    connection.fail_after_update=True
                    with self.assertRaises(InterruptedError):
                        self.recover(state,connection,lease)
                    self.assertEqual((connection.flag,connection.pending,connection.locked),(str(original),None,False))
                    connection.fail_after_update=False
                    phases=[]
                    self.assertTrue(self.recover(state,connection,lease,progress=phases.append))
                    self.assertEqual(phases,['realm-offline-recovery'])
                    self.assertEqual(connection.flag,'2')
                with session.db.state_lock(state) as next_lease:
                    self.assertFalse(self.recover(state,connection,next_lease))
                    self.assertEqual(connection.updates,2)

    def test_stop_before_recovery_before_mutation_and_before_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with session.db.state_lock(state) as lease:
                for stop_at in ('entry', 'locked', 'updated'):
                    with self.subTest(stop_at=stop_at):
                        connection = RealmConnection(3)
                        def cancelled():
                            return (stop_at == 'entry' or
                                    (stop_at == 'locked' and connection.locked) or
                                    (stop_at == 'updated' and connection.updates > 0))
                        with self.assertRaisesRegex(ValueError, 'startup cancelled'):
                            self.recover(state, connection, lease, cancelled=cancelled)
                        self.assertEqual((connection.flag, connection.pending, connection.locked), ('3', None, False))
                        self.assertEqual(connection.updates, int(stop_at == 'updated'))
                        self.assertTrue(self.recover(state, connection, lease))
                        self.assertFalse(self.recover(state, connection, lease))

    def test_recovery_rejects_a_change_committed_before_its_row_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with session.db.state_lock(state) as lease:
                for field, value in [('endpoint', ['foreign']), ('flag', '1')]:
                    with self.subTest(changed=field):
                        connection = RealmConnection(3)
                        connection.before_row_lock = lambda current: setattr(current, field, value)
                        with self.assertRaisesRegex(ValueError, 'singleton stock realm selection differs'):
                            self.recover(state, connection, lease)
                        self.assertEqual(getattr(connection, field), value)
                        self.assertEqual((connection.updates, connection.pending, connection.locked), (0, None, False))

    def test_foreign_or_unowned_state_cannot_mutate_the_realm(self):
        with tempfile.TemporaryDirectory() as root:
            state=Path(root)
            with session.db.state_lock(state) as lease:
                for field,value in [('ids',['1','2']),('endpoint',['foreign']),('flag','7')]:
                    c=RealmConnection(1)
                    setattr(c,field,value)
                    with self.subTest(field=field),self.assertRaises(ValueError):
                        self.recover(state,c,lease)
                    self.assertEqual((c.updates,c.pending,c.locked),(0,None,False))
                for changes in [dict(expected_uuid='different'),dict(verify_service=lambda:False)]:
                    c=RealmConnection(3)
                    with self.assertRaises(ValueError):
                        self.recover(state,c,lease,**changes)
                    self.assertEqual(c.updates,0)
                for flag in (0,2,4,32,64,128):
                    c=RealmConnection(flag)
                    self.assertFalse(self.recover(state,c,lease))
                    self.assertEqual((c.flag,c.updates),(str(flag),0))
            c=RealmConnection(3)
            with self.assertRaises(session.db.BootstrapError):
                self.recover(state,c,lease)
            self.assertEqual(c.updates,0)
