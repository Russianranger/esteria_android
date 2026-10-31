import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from runtime import server_config as runtime
from tools import render_server_config as host
from tests import test_runtime_server_content as content_fixture
from tests import test_server_config as source_fixture


class RuntimeServerConfiguration(unittest.TestCase):
    def setUp(self):
        # Reuse a full, externally pinned archive-root fixture and obtain the
        # actual verification result; neither renderer fabricates one.
        fixture = content_fixture.RuntimeContent()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.root = fixture.base
        server = source_fixture.fixture(self.root)
        main = server / 'src/server/apps/worldserver/worldserver.conf.dist'
        main.write_text(main.read_text() + '\nRealmID = 1\n')
        inventory_path, _ = source_fixture.ServerConfigTests().module_fixture(self.root, server)
        inventory = json.loads(inventory_path.read_bytes())
        for name in runtime.MAIN_CONFIG_TEMPLATES:
            raw = (server / name).read_bytes()
            fixture.data[name] = raw
            fixture.payload['source/' + name] = raw
            fixture.manifest['files'][name] = content_fixture.source_identity(raw)
        for row in inventory['modules']:
            module = dict(row, notices=[], luaCandidates=[])
            fixture.manifest['modules'].append(module)
            for name in row['configTemplates']:
                raw = (server / name).read_bytes()
                fixture.payload['source/' + name] = raw
                fixture.manifest['files'][name] = content_fixture.source_identity(raw)
        path = 'modules/mod-playerbots/data/sql/playerbots/base/updates.sql'
        raw = b'CREATE TABLE updates(name TEXT);\n'
        fixture.payload['source/' + path] = raw
        fixture.manifest['files'][path] = content_fixture.source_identity(raw)
        fixture.manifest['databases']['playerbots'] = dict(base=[path], updateOrder=[], executionOrderQualified=True)
        # Exercise the production-sized complete selection without relying on
        # an external C++ checkout or claiming real module execution.
        existing = sum(len(row['configTemplates']) for row in fixture.manifest['modules'])
        for index in range(50 - existing):
            module = 'mod-parity-' + str(index).zfill(2)
            path = 'modules/' + module + '/conf/parity_' + str(index).zfill(2) + '.conf.dist'
            raw = ('[module]\nUntouched = ' + str(index) + '\n').encode()
            fixture.payload['source/' + path] = raw
            fixture.manifest['files'][path] = content_fixture.source_identity(raw)
            fixture.manifest['modules'].append(dict(name=module, configTemplates=[path], notices=[], luaCandidates=[]))
        fixture.manifest['modules'].sort(key=lambda row: row['name'])
        fixture.manifest['enabledModules'] = [row['name'] for row in fixture.manifest['modules']]
        fixture.compiled['enabledModules'] = list(fixture.manifest['enabledModules'])
        fixture.compiled['configFiles'] = sorted(Path(name).name[:-5]
            for row in fixture.manifest['modules'] for name in row['configTemplates'])
        fixture.write()
        self.content = fixture.verify()
        self.state = self.root / 'state'
        (self.state / 'accounts').mkdir(parents=True)
        self.secret = self.state / 'accounts/database-secret'
        self.secret.write_text('a' * 64 + '\n')
        self.data = self.root / 'data'
        self.mysql = Path('/usr/bin/mysql')
        self.profile = json.loads(host.PROFILE.read_bytes())

    def host_render(self, **kwargs):
        return host.render(self.content.source, self.state, self.data, self.content.source, self.mysql,
            module_inventory=kwargs.pop('module_inventory', self.content.root / 'metadata/content-manifest.json'),
            compiled_modules=kwargs.pop('compiled_modules', self.content.root / 'metadata/compiled-modules.json'), **kwargs)

    def runtime_render(self, **kwargs):
        return runtime.render_verified(self.content, self.state, self.data, self.mysql,
                                       profile=kwargs.pop('profile', self.profile), **kwargs)

    def files(self):
        current = (self.state / 'config/current').resolve()
        return {path.relative_to(current).as_posix(): path.read_bytes()
                for path in current.rglob('*') if path.is_file()}

    def test_host_and_runtime_have_identical_full_files_proof_and_generation(self):
        before_secret = self.secret.read_bytes()
        first = self.host_render(); expected = self.files()
        second = self.runtime_render()
        self.assertEqual(first, second)
        self.assertEqual(self.files(), expected)
        self.assertTrue(second['module_configurations_complete'])
        self.assertEqual({name for name in expected if name.startswith('modules/')},
                         {'modules/' + name for name in self.content.compiled['configFiles']})
        proof = json.loads(expected['module-configuration.json'])
        self.assertEqual(len(proof['configFiles']), 50)
        self.assertEqual(proof['contentProfile'], 'stock-3.3.5a')
        self.assertEqual(second['content_profile'], 'stock-3.3.5a')
        self.assertIn(b'Updates.EnableDatabases = 0', expected['worldserver.conf'])
        self.assertIn(b'ClasslessWildcard.Enable = 0', expected['modules/classless_wildcard.conf'])
        self.assertIn(b'WxlDbc.Enable = 0', expected['modules/mod_wxl_dbc.conf'])
        self.assertIn(b'Battlemon.Enable = 0', expected['modules/mod_battlemon.conf'])
        self.assertIn(b'Playerbots.Updates.EnableDatabases = 0', expected['modules/playerbots.conf'])
        self.assertEqual(proof['inventorySha256'], self.content.identities['files']['metadata/content-manifest.json']['sha256'])
        self.assertEqual(proof['compiledSelectionSha256'], self.content.identities['files']['metadata/compiled-modules.json']['sha256'])
        self.assertFalse(proof['moduleStartupQualified']); self.assertFalse(proof['gameplayQualified'])
        self.assertEqual(self.secret.read_bytes(), before_secret)

    def test_expected_private_generation_is_read_only_and_matches_renderer_exactly(self):
        self.runtime_render()
        expected = self.files()
        directory = (self.state / 'config/current').resolve()
        before = {path: path.stat().st_mtime_ns for path in [self.secret, directory, *directory.rglob('*')]}
        files = runtime.expected_private_files_verified(self.content, self.state, self.data, self.mysql,
            profile=self.profile, secret='a' * 64)
        self.assertEqual({name: value.encode() for name, value in files.items()}, expected)
        self.assertEqual({path: path.stat().st_mtime_ns for path in before}, before)

    def test_host_preserves_noncanonical_input_json_hash_semantics(self):
        inventory = self.root / 'noncanonical-inventory.json'
        compiled = self.root / 'noncanonical-compiled.json'
        inventory.write_text(json.dumps(self.content.manifest, indent=4))
        compiled.write_text(json.dumps(self.content.compiled, separators=(',', ':')))
        self.host_render(module_inventory=inventory, compiled_modules=compiled)
        proof = json.loads(self.files()['module-configuration.json'])
        self.assertEqual(proof['inventorySha256'], hashlib.sha256(inventory.read_bytes()).hexdigest())
        self.assertEqual(proof['compiledSelectionSha256'], hashlib.sha256(compiled.read_bytes()).hexdigest())
        self.assertNotEqual(proof['inventorySha256'], self.content.identities['files']['metadata/content-manifest.json']['sha256'])

    def test_host_source_module_validator_still_gates_activation(self):
        with patch('tools.package_server_content.validate_modules', side_effect=ValueError('host gate held')) as validate:
            with self.assertRaisesRegex(ValueError, 'host gate held'):
                self.host_render()
        validate.assert_called_once()
        self.assertFalse((self.state / 'config/current').exists())
        self.assertEqual(self.secret.read_text(), 'a' * 64 + '\n')

    def test_missing_or_changed_template_preserves_previous_activation_and_secret(self):
        self.runtime_render(); before = self.files()
        pointer = (self.state / 'config/current').readlink()
        for name in (runtime.MAIN_CONFIG_TEMPLATES[0], 'modules/mod-one/conf/one.conf.dist'):
            path = self.content.source / name
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(name=name, missing=True), self.assertRaises((ValueError, OSError)):
                self.runtime_render()
            path.write_bytes(raw + b'\nChanged = 1\n')
            with self.subTest(name=name, changed=True), self.assertRaisesRegex(ValueError, 'differs from verified'):
                self.runtime_render()
            path.write_bytes(raw)
            self.assertEqual((self.state / 'config/current').readlink(), pointer)
            self.assertEqual(self.files(), before)
            self.assertEqual(self.secret.read_text(), 'a' * 64 + '\n')

    def test_changed_archived_metadata_or_compiled_object_fails_before_state_creation(self):
        metadata = self.content.root / 'metadata/compiled-modules.json'
        raw = metadata.read_bytes(); metadata.write_bytes(raw + b' ')
        with self.assertRaisesRegex(ValueError, 'metadata changed'):
            self.runtime_render()
        metadata.write_bytes(raw)
        self.content.compiled['configFiles'].pop()
        with self.assertRaisesRegex(ValueError, 'metadata object differs'):
            self.runtime_render()
        self.assertFalse((self.state / 'config').exists())

    def test_runtime_requires_complete_verified_content_and_sealed_policy(self):
        with self.assertRaisesRegex(ValueError, 'Verified extracted'):
            runtime.render_verified(self.content.manifest, self.state, self.data, self.mysql, profile=self.profile)
        for change in ('port', 'bot-population', 'bot-ceiling', 'typed-port', 'custom-profile', 'missing-profile'):
            profile = copy.deepcopy(self.profile)
            if change == 'port': profile['database_port'] = 3306
            elif change == 'bot-population': profile['playerbots']['AiPlayerbot.RandomBotAutologin'] = 1
            elif change == 'bot-ceiling': profile['playerbots']['AiPlayerbot.MaxAddedBots'] = 5
            elif change == 'typed-port': profile['database_port'] = '13306'
            elif change == 'custom-profile': profile['content_profile'] = 'esteria-custom'
            else: del profile['content_profile']
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'sealed'):
                self.runtime_render(profile=profile)
        self.assertFalse((self.state / 'config').exists())

    def test_existing_invalid_secret_is_never_reset(self):
        self.secret.write_bytes(b'invalid-existing-private-value')
        with self.assertRaisesRegex(ValueError, 'refusing replacement'):
            self.runtime_render()
        self.assertEqual(self.secret.read_bytes(), b'invalid-existing-private-value')
        self.assertFalse((self.state / 'config/current').exists())

    def test_runtime_imports_only_stdlib_and_verified_content_helper(self):
        syntax = ast.parse(Path(runtime.__file__).read_text())
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name.split('.')[0] in sys.stdlib_module_names or
                                    alias.name == 'server_content' for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertTrue(node.level == 1 and node.module is None or
                                node.level == 0 and node.module.split('.')[0] in sys.stdlib_module_names)


if __name__ == '__main__':
    unittest.main()
