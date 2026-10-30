import json
import hashlib
import copy
import os
from pathlib import Path
import tempfile
import unittest
from tools.render_server_config import overlay, quoted, render, MODULE_OVERRIDES


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
            self.assertIn('Eluna.Enabled = 0', world)
            self.assertNotIn('500', (current / 'modules/playerbots.conf').read_text())
            self.assertIn('AiPlayerbot.CommandServerPort = 0', (current / 'modules/playerbots.conf').read_text())
            self.assertFalse(first['database_initialized'])
            self.assertFalse(first['module_configurations_complete'])
            self.assertFalse(first['lua_scripts_enabled'])
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

    def module_fixture(self, root, server):
        rows = []
        files = {}
        for i, (name, settings) in enumerate(MODULE_OVERRIDES.items()):
            path = server / 'modules' / ('mod-fixture-' + str(i)) / 'conf' / (name + '.dist')
            path.parent.mkdir(parents=True)
            path.write_text('\n'.join(f'{key} = 1' for key in settings) + '\nUntouched = 17\n')
        for path in sorted(server.glob('modules/*/conf/*.conf.dist')):
            name = path.relative_to(server).as_posix(); raw = path.read_bytes()
            rows.append(dict(name=path.parts[-3], configTemplates=[name]))
            files[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        inventory = dict(formatVersion=1, scope='source-content-inventory', contentSha256Complete=True,
                         source={'commit': 'a'*40}, sourceLockSha256='b'*64, modules=rows,
                         enabledModules=sorted(row['name'] for row in rows), files=files)
        compiled = dict(formatVersion=1, scope='compiled-server-module-selection', source=inventory['source'],
                        sourceLockSha256=inventory['sourceLockSha256'], generatedListsMatchInstalledBinaries=True,
                        enabledModules=inventory['enabledModules'], binaries={'worldserver': {}, 'dbimport': {}},
                        configFiles=[Path(name).name[:-5] for name in files])
        for name in ('src/server/apps/authserver/authserver.conf.dist', 'src/server/apps/worldserver/worldserver.conf.dist'):
            raw=(server/name).read_bytes()
            files[name]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        # Synthetic selection records test composition; they are not executable build receipts.
        a, b = root/'content.json', root/'modules.json'
        a.write_text(json.dumps(inventory));b.write_text(json.dumps(compiled))
        return a, b

    def test_complete_selected_templates_are_hash_checked_and_locally_configured(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);server=fixture(root);inventory,compiled=self.module_fixture(root,server)
            args=(server,root/'state',root/'data',root/'sql',Path('/usr/bin/mysql'))
            proof=render(*args,module_inventory=inventory,compiled_modules=compiled)
            self.assertTrue(proof['module_configurations_complete']);self.assertFalse(proof['module_startup_qualified'])
            current=(root/'state/config/current').resolve()
            for filename, settings in MODULE_OVERRIDES.items():
                actual=(current/'modules'/filename).read_text()
                for key,value in settings.items():self.assertIn(f'{key} = {value}',actual)
                self.assertIn('Untouched = 17',actual)
            saved=(root/'state/accounts/database-secret').read_bytes()
            template=next(server.glob('modules/mod-fixture-*/conf/*.conf.dist'))
            template.write_text(template.read_text()+'Changed = 1\n')
            with self.assertRaisesRegex(ValueError,'differs from verified'):
                render(*args,module_inventory=inventory,compiled_modules=compiled)
            self.assertEqual(current,(root/'state/config/current').resolve())
            self.assertEqual(saved,(root/'state/accounts/database-secret').read_bytes())

    def test_missing_or_ambiguous_selection_and_changed_generation_fail_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);server=fixture(root);inventory,compiled=self.module_fixture(root,server)
            args=(server,root/'state',root/'data',root/'sql',Path('/usr/bin/mysql'))
            original=json.loads(compiled.read_text())
            for mutation in ('missing', 'wrong-source', 'case-duplicate'):
                changed=copy.deepcopy(original)
                if mutation=='missing':changed['configFiles'].pop()
                elif mutation=='wrong-source':changed['sourceLockSha256']='c'*64
                else:changed['configFiles'].append(changed['configFiles'][0].upper())
                compiled.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):render(*args,module_inventory=inventory,compiled_modules=compiled)
                self.assertFalse((root/'state/config/current').exists())
            compiled.write_text(json.dumps(original))
            render(*args,module_inventory=inventory,compiled_modules=compiled)
            (root/'state/config/current/modules/extra.conf').write_text('Unexpected = 1\n')
            with self.assertRaisesRegex(ValueError,'file set changed'):
                render(*args,module_inventory=inventory,compiled_modules=compiled)

    def test_reuse_rejects_fifo_oversize_and_redirected_generation(self):
        for mutation in ('fifo','oversize','directory-link'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as name:
                root=Path(name);server=fixture(root)
                args=(server,root/'state',root/'data',root/'sql',Path('/usr/bin/mysql'))
                render(*args)
                current=(root/'state/config/current').resolve()
                if mutation=='directory-link':
                    retained=current.with_name(current.name+'-retained')
                    current.rename(retained);current.symlink_to(retained,target_is_directory=True)
                else:
                    target=current/'worldserver.conf';target.unlink()
                    if mutation=='fifo':os.mkfifo(target)
                    else:target.write_bytes(b'x'*(4<<20))
                with self.assertRaises(ValueError):render(*args)
