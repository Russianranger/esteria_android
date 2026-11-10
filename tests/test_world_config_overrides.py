import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime'))

import server_config  # noqa: E402
import server_session_process as process  # noqa: E402
import world_config_overrides as overrides  # noqa: E402
from tests.test_server_session_process import pinned_env_name  # noqa: E402

POLICY = ROOT / 'config/world-config-policy.json'


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = overrides.Policy.load(POLICY)

    def test_environment_names_follow_the_pinned_server(self):
        for key in ('MinWorldUpdateTime', 'MapUpdateInterval', 'Rate.XP.Kill', 'AiPlayerbot.MaxRandomBots',
                    'Visibility.Distance.Continents', 'Rate.Drop.Item.Poor', 'PlayerSave.Stats.MinLevel',
                    'Quests.IgnoreRaid', 'Logger.playerbots', 'Arena.ArenaSeason.ID', 'StartPlayerLevel'):
            self.assertEqual(overrides.env_name(key), pinned_env_name(key), key)
        self.assertEqual(overrides.env_name('AiPlayerbot.MaxRandomBots'), 'AC_AI_PLAYERBOT_MAX_RANDOM_BOTS')
        self.assertEqual(overrides.env_name('Rate.XP.Kill'), 'AC_RATE_XP_KILL')

    def test_launch_defaults_are_the_session_tick(self):
        self.assertEqual({overrides.env_name(key): value for key, value in self.policy.launch_defaults.items()},
                         process.WORLDSERVER_TICK_ENVIRONMENT)

    def test_every_key_the_renderer_sets_is_managed_by_esteria(self):
        source = inspect.getsource(server_config._configuration_files)
        rendered = set(re.findall(r"'([A-Z][A-Za-z0-9.]+)':", source))
        self.assertTrue({'BindIP', 'DataDir', 'WorldDatabaseInfo', 'PlayerbotsDatabaseInfo', 'Console.Enable',
                         'MapUpdate.Threads'} <= rendered)
        # MapUpdate.Threads stays an owner choice: it changes load, not ownership or safety.
        for key in rendered - {'MapUpdate.Threads'}:
            self.assertTrue(self.policy.protected(key), key)
        for settings in server_config.MODULE_OVERRIDES.values():
            for key in settings:
                self.assertTrue(self.policy.protected(key), key)
        self.assertTrue(self.policy.protected('Eluna.Enabled'))

    def test_owner_choices_stay_open(self):
        profile = json.loads((ROOT / 'config/local-server.json').read_text())['playerbots']
        for key in profile:
            self.assertEqual(self.policy.protected(key), key == 'AiPlayerbot.CommandServerPort', key)
        for key in ('Rate.XP.Kill', 'Rate.Drop.Money', 'MinWorldUpdateTime', 'MaxPlayerLevel', 'Motd', 'MapUpdate.Threads',
                    'Visibility.Distance.Continents', 'PlayerSave.Stats.MinLevel', 'StartPlayerMoney'):
            self.assertFalse(self.policy.protected(key), key)
        for key in ('LogsDir', 'LogDB.Opt.ClearTime', 'Appender.Console', 'Logger.root', 'PidFile', 'IPLocationFile',
                    'Network.OutKBuff', 'Ra.Port', 'SOAP.IP', 'Metric.ConnectionInfo', 'RealmID', 'Expansion'):
            self.assertTrue(self.policy.protected(key), key)

    def test_policy_is_found_packaged_and_in_the_repository(self):
        self.assertEqual(overrides.policy_path(ROOT / 'runtime'), POLICY)
        with tempfile.TemporaryDirectory() as temp:
            packaged = Path(temp) / 'world-config-policy.json'; packaged.write_text(POLICY.read_text())
            self.assertEqual(overrides.policy_path(Path(temp)), packaged)

    def test_values(self):
        allowed = self.policy.value_allowed
        self.assertTrue(allowed('3') and allowed('0.5') and allowed('Welcome to the realm'))
        self.assertTrue(allowed(''))
        for value in (' 1', '1 ', 'a\nb', '\u00a0', 'say "x"', 'C:\\x', 'x' * 256, 3, None, '\x00'):
            self.assertFalse(allowed(value), repr(value))


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generation = self.root / 'generation'; (self.generation / 'modules').mkdir(parents=True)
        (self.generation / 'worldserver.conf').write_text(
            '# Content profile: stock-3.3.5a\n#    Rate.XP.Kill\n#        Default: 1\n\nRate.XP.Kill = 1\n'
            'Rate.XP.Quest  =  1\nDataDir = "/esteria-data"\nWorldDatabaseInfo = "127.0.0.1;13306;esteria;secret;acore_world"\n'
            'MinWorldUpdateTime = 1\nMotd = "Welcome"\n')
        (self.generation / 'modules/playerbots.conf').write_text('AiPlayerbot.MaxRandomBots = 0\nAiPlayerbot.CommandServerPort = 0\n')
        self.policy = overrides.Policy.load(POLICY)
        self.document = self.root / overrides.OVERRIDES_NAME

    def write(self, settings, **fields):
        self.document.write_text(json.dumps(dict(dict(formatVersion=1, scope=overrides.SCOPE, settings=settings), **fields)))

    def apply(self):
        return overrides.environment(self.document, self.generation, self.policy)

    def test_missing_document_applies_nothing(self):
        self.assertEqual(self.apply(), ({}, [], []))

    def test_accepted_and_refused_settings(self):
        self.write([
            dict(file='worldserver.conf', key='Rate.XP.Kill', value='3'),
            dict(file='worldserver.conf', key='MinWorldUpdateTime', value='10'),
            dict(file='modules/playerbots.conf', key='AiPlayerbot.MaxRandomBots', value='20'),
            dict(file='worldserver.conf', key='Motd', value='Hello from the Thor'),
            dict(file='worldserver.conf', key='DataDir', value='/elsewhere'),
            dict(file='worldserver.conf', key='WorldDatabaseInfo', value='x'),
            dict(file='modules/playerbots.conf', key='AiPlayerbot.CommandServerPort', value='8888'),
            dict(file='worldserver.conf', key='Rate.Honor', value='2'),
            dict(file='modules/playerbots.conf', key='Rate.XP.Kill', value='2'),
            dict(file='../worldserver.conf', key='Rate.XP.Quest', value='2'),
            dict(file='worldserver.conf', key='Rate.XP.Quest', value='2\nRate.XP.Kill = 9'),
            dict(file='worldserver.conf', key='Rate.XP.Quest', value='say "x"'),
            dict(file='worldserver.conf', key='Rate.XP.Kill', value='4'),
            dict(file='worldserver.conf', key='Rate XP', value='2'),
            dict(file='worldserver.conf', key='Rate.XP.Quest', value='2', extra=True),
            'not an entry',
        ])
        env, applied, refused = self.apply()
        self.assertEqual(env, {'AC_RATE_XP_KILL': '3', 'AC_MIN_WORLD_UPDATE_TIME': '10',
                               'AC_AI_PLAYERBOT_MAX_RANDOM_BOTS': '20', 'AC_MOTD': 'Hello from the Thor'})
        self.assertEqual(applied, ['Rate.XP.Kill', 'MinWorldUpdateTime', 'AiPlayerbot.MaxRandomBots', 'Motd'])
        self.assertEqual(refused, ['DataDir', 'WorldDatabaseInfo', 'AiPlayerbot.CommandServerPort', 'Rate.Honor', 'Rate.XP.Kill',
                                   'Rate.XP.Quest', 'Rate.XP.Quest', 'Rate.XP.Quest', 'Rate.XP.Kill', '#13', 'Rate.XP.Quest', '#15'])
        line = overrides.report(applied, refused)
        self.assertIn('applied=4 refused=12', line)
        self.assertNotIn('Thor', line); self.assertNotIn('secret', line)

    def test_limits_and_documents(self):
        self.write([dict(file='worldserver.conf', key='Rate.XP.Kill', value='2')] * 300)
        env, applied, refused = self.apply()
        self.assertEqual((len(applied), len(refused)), (256, 44))
        self.assertEqual(env, {'AC_RATE_XP_KILL': '2'})
        for document in ('[]', '{"formatVersion":2,"scope":"esteria-world-config-overrides","settings":[]}', 'not json'):
            self.document.write_text(document)
            with self.assertRaises((overrides.Rejected, ValueError)):
                self.apply()

    def test_symlinked_files_are_refused(self):
        outside = self.root / 'outside.conf'; outside.write_text('Rate.XP.Kill = 1\n')
        (self.generation / 'modules/evil.conf').symlink_to(outside)
        self.write([dict(file='modules/evil.conf', key='Rate.XP.Kill', value='2')])
        self.assertEqual(self.apply(), ({}, [], ['Rate.XP.Kill']))
        self.document.unlink(); self.document.symlink_to(outside)
        with self.assertRaises(overrides.Rejected):
            self.apply()


class ChildEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def child(self, program, **options):
        script = self.root / 'fixture'; script.write_text('#!/usr/bin/env python3\n')
        return process.ServerChild(program, script, self.root / 'config', self.root, self.root / 'log', **options)

    def test_overrides_are_worldserver_only_and_well_formed(self):
        self.assertEqual(self.child('worldserver', overrides={'AC_RATE_XP_KILL': '3'}).overrides, {'AC_RATE_XP_KILL': '3'})
        for program, values in (('authserver', {'AC_RATE_XP_KILL': '3'}), ('worldserver', {'PATH': '/tmp'}),
                                ('worldserver', {'AC_RATE': 'a\x00b'}), ('worldserver', {'AC_APPENDER_CONSOLE': '1'}),
                                ('worldserver', {'AC_LOGGER_PLAYERBOTS': '1'})):
            with self.assertRaises(ValueError):
                self.child(program, overrides=values)

    def test_owner_choice_wins_over_the_session_tick(self):
        marker = self.root / 'env.json'
        script = self.root / 'world'; script.write_text('#!/usr/bin/env python3\nimport json,os\n'
            'json.dump({k:v for k,v in os.environ.items() if k.startswith("AC_")},open(%r,"w"))\n' % str(marker))
        script.chmod(0o700)
        child = process.ServerChild('worldserver', script, self.root / 'config', self.root, self.root / 'log',
                                    overrides={'AC_MIN_WORLD_UPDATE_TIME': '10', 'AC_RATE_XP_KILL': '3'})
        child.start()
        deadline = time.monotonic() + 5
        while not marker.exists() or not marker.read_text():
            self.assertLess(time.monotonic(), deadline); time.sleep(.02)
        time.sleep(.1)
        try:
            child.stop(world_timeout=.5, auth_timeout=.5)
        except (OSError, ValueError):
            pass
        env = json.loads(marker.read_text())
        self.assertEqual(env['AC_MIN_WORLD_UPDATE_TIME'], '10')
        self.assertEqual(env['AC_MAP_UPDATE_INTERVAL'], '50')
        self.assertEqual(env['AC_RATE_XP_KILL'], '3')
        self.assertEqual(env['AC_APPENDER_CONSOLE'], '1,4,1')


if __name__ == '__main__':
    unittest.main()
