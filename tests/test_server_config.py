import json
import os
from pathlib import Path
import tempfile
import unittest
from tools.render_server_config import overlay, quoted, render


AUTH = '''BindIP LogsDir SourceDirectory MySQLExecutable TempDir LoginDatabaseInfo
LoginDatabase.WorkerThreads LoginDatabase.SynchThreads RealmServerPort'''.split()
WORLD = '''BindIP LogsDir SourceDirectory MySQLExecutable TempDir LoginDatabaseInfo
LoginDatabase.WorkerThreads LoginDatabase.SynchThreads WorldServerPort DataDir
WorldDatabaseInfo CharacterDatabaseInfo WorldDatabase.WorkerThreads WorldDatabase.SynchThreads
CharacterDatabase.WorkerThreads CharacterDatabase.SynchThreads Console.Enable Ra.Enable SOAP.Enabled
Network.Threads MapUpdate.Threads Wintergrasp.DeferShutdownTimer'''.split()


def fixture(root):
    server = root / 'server'
    profile = json.loads((Path(__file__).parents[1] / 'config/local-server.json').read_text())
    bots = list(profile['playerbots']) + ['PlayerbotsDatabaseInfo']
    for path, keys in [('src/server/apps/authserver/authserver.conf.dist', AUTH),
                       ('src/server/apps/worldserver/worldserver.conf.dist', WORLD),
                       ('modules/mod-playerbots/conf/playerbots.conf.dist', bots)]:
        target = server / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('\n'.join(f'{key} = 0' for key in keys))
    return server


class ServerConfigTests(unittest.TestCase):
    def test_overlay_fails_on_unknown_or_duplicate_keys(self):
        for source in ('Other = 1', 'Port = 1\nPort = 2'):
            with self.assertRaises(ValueError):
                overlay(source, {'Port': 3})

    def test_paths_cannot_inject_configuration(self):
        for value in ('/data/"\nBindIP=0.0.0.0', '/data/a;b', '/data\\path', '/data\x00'):
            with self.assertRaises(ValueError):
                quoted(value)

    def test_secret_persistence_and_atomic_activation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            server = fixture(root)
            state = root / 'state'
            args = (server, state, root / 'data', root / 'sql', Path('/usr/bin/mysql'))
            first = render(*args)
            secret = (state / 'accounts/database-secret').read_bytes()
            self.assertEqual(os.stat(state / 'accounts/database-secret').st_mode & 0o777, 0o600)
            second = render(*args)
            self.assertEqual(first['generation'], second['generation'])
            self.assertEqual(secret, (state / 'accounts/database-secret').read_bytes())
            current = (state / 'config/current').resolve()
            world = (current / 'worldserver.conf').read_text()
            self.assertIn('BindIP = "127.0.0.1"', world)
            self.assertIn('Ra.Enable = 0', world)
            self.assertIn('Console.Enable = 1', world)
            self.assertIn('Wintergrasp.DeferShutdownTimer = 0', world)
            self.assertNotIn('500', (current / 'modules/playerbots.conf').read_text())
            self.assertFalse(first['database_initialized'])
            (server / 'src/server/apps/worldserver/worldserver.conf.dist').write_text('broken')
            with self.assertRaises(ValueError):
                render(*args)
            self.assertEqual(current, (state / 'config/current').resolve())
            self.assertEqual(secret, (state / 'accounts/database-secret').read_bytes())

    def test_console_shutdown_cannot_inherit_battle_deferral(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); server=fixture(root)
            source=server/'src/server/apps/worldserver/worldserver.conf.dist'
            source.write_text(source.read_text().replace('Wintergrasp.DeferShutdownTimer = 0','Wintergrasp.DeferShutdownTimer = 1'))
            render(server,root/'state',root/'data',root/'sql',Path('/usr/bin/mysql'))
            world=(root/'state/config/current/worldserver.conf').read_text()
            self.assertIn('Wintergrasp.DeferShutdownTimer = 0',world)
            self.assertNotIn('Wintergrasp.DeferShutdownTimer = 1',world)

    def test_does_not_replace_corrupt_existing_credentials(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            server = fixture(root)
            secret = root / 'state/accounts/database-secret'
            secret.parent.mkdir(parents=True)
            secret.write_text('invalid-but-existing')
            with self.assertRaisesRegex(ValueError, 'refusing replacement'):
                render(server, root / 'state', root / 'data', root / 'sql', Path('/usr/bin/mysql'))
            self.assertEqual(secret.read_text(), 'invalid-but-existing')
