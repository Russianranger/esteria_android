import copy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import manifest_server_content as content
from tools import package_server_content as package
from tools import qualify_dbimport as consumer


class Packaging(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = {
            'src/server/apps/authserver/authserver.conf.dist': b'# source auth template\n',
            'src/server/apps/worldserver/worldserver.conf.dist': b'# source world template\n',
            'LICENSE': b'server license',
            'data/sql/base/db_auth/base.sql': b'CREATE TABLE fixture(id INT);\n',
            'modules/mod-one/data/sql/db-auth/update.sql': b'UPDATE fixture SET id=1;\n',
            'modules/mod-one/data/sql/manual/uninstall.sql': b'DROP TABLE fixture;\n',
            'modules/mod-one/conf/one.conf.dist': b'Enabled = 1\n',
            'modules/mod-one/LICENSE': b'module notice',
            'modules/mod-one/lua_scripts/main.lua': b'-- source script, not automatically active\n',
            'src/evidence.cpp': b'not runtime data',
        }
        self.server = self.repository('server', self.data)
        self.eluna = self.repository('eluna', {'extensions/first.ext': b'-- extension', 'docs/LICENSE.md': b'eluna notice'})
        self.manifest = dict(source={'commit': 'a' * 40, 'submodules': {content.ELUNA: 'b' * 40}},
            sourceLockSha256='c' * 64, enabledModules=['mod-one'],
            files=self.server.identities(self.data, True), elunaFiles=self.eluna.identities(self.eluna.files, True),
            databases={'auth': {'base': ['data/sql/base/db_auth/base.sql'],
                'updateOrder': [{'path': 'modules/mod-one/data/sql/db-auth/update.sql', 'state': 'MODULE'}]}},
            modules=[{'name': 'mod-one', 'configTemplates': ['modules/mod-one/conf/one.conf.dist'],
                'notices': ['modules/mod-one/LICENSE'], 'luaCandidates': ['modules/mod-one/lua_scripts/main.lua'],
                'sqlNotDiscoveredByUpdater': ['modules/mod-one/data/sql/manual/uninstall.sql']}],
            loaderContract={'localRealmGate': {'required': True, 'afterAllCoreAndModuleUpdates': True}})
        self.lua = dict(formatVersion=1, mode='disabled', serverRevision='a' * 40, elunaRevision='b' * 40,
            files=[dict(origin=origin, source=name, sha256=identity['sha256'], destination=None,
                        reason='Explicitly held for dependency qualification.', requirements=[])
                   for (origin, name), identity in package.lua_candidates(self.manifest).items()])

    def repository(self, name, payload):
        root = self.root / name
        root.mkdir()
        for name, raw in payload.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        def git(*args):
            return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.PIPE).decode().strip()
        git('init', '-q')
        git('config', 'user.name', 'Content Test')
        git('config', 'user.email', 'content@example.invalid')
        git('add', '.')
        git('commit', '-qm', 'fixture')
        return content.GitObjects(root, git('rev-parse', 'HEAD'))

    def build(self, name, manifest=None, lua=None):
        return package.build_package(self.root / name, manifest or self.manifest,
            {'sha256': 'd' * 64, 'bytes': 123}, None, None, lua or self.lua,
            {'sha256': 'e' * 64, 'bytes': 123}, self.server, self.eluna)

    def test_repeated_package_is_identical_and_manual_sql_lua_evidence_are_not_active_payloads(self):
        first, second = self.build('one'), self.build('two')
        self.assertEqual(first['archive'], second['archive'])
        self.assertTrue(first['archiveReadBackVerified'])
        self.assertFalse(first['moduleSelectionVerified'])
        self.assertFalse(first['configurationRequirements']['Eluna.Enabled'])
        self.assertFalse(first['gameSchemasLoaded'])
        with tarfile.open(self.root / 'one/server-content.tar.gz', 'r:gz') as archive:
            names = set(archive.getnames())
            self.assertIn('source/data/sql/base/db_auth/base.sql', names)
            self.assertIn('source/modules/mod-one/data/sql/db-auth/update.sql', names)
            self.assertIn('source/modules/mod-one/LICENSE', names)
            for name in content.MAIN_CONFIG_TEMPLATES:
                self.assertEqual(archive.extractfile('source/' + name).read(), self.data[name])
            self.assertIn('source/src/server/game/LuaEngine/docs/LICENSE.md', names)
            self.assertNotIn('source/modules/mod-one/data/sql/manual/uninstall.sql', names)
            self.assertNotIn('source/src/evidence.cpp', names)
            self.assertFalse(any(name.startswith('lua_scripts/') for name in names))
            review = json.load(archive.extractfile('metadata/content-manifest.json'))
            self.assertIn('modules/mod-one/data/sql/manual/uninstall.sql', review['files'])

    def test_actual_git_packager_round_trips_through_runtime_consumer_with_full_provenance(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['contentSha256Complete'] = True
        manifest['databases']['auth']['executionOrderQualified'] = True
        for name in ('characters', 'world'):
            manifest['databases'][name] = dict(base=[], updateOrder=[], executionOrderQualified=True)
        compiled = dict(formatVersion=1, scope='compiled-server-module-selection',
            generatedListsMatchInstalledBinaries=True, source=manifest['source'],
            sourceLockSha256=manifest['sourceLockSha256'], enabledModules=['mod-one'],
            configFiles=['one.conf'], binaries={'worldserver': {}, 'dbimport': {}})
        output = self.root / 'producer'
        receipt = package.build_package(output, manifest, {'sha256': 'd' * 64, 'bytes': 123},
            compiled, {'sha256': 'f' * 64, 'bytes': 123}, self.lua,
            {'sha256': 'e' * 64, 'bytes': 123}, self.server, self.eluna)
        digest = hashlib.sha256((output / 'package-receipt.json').read_bytes()).hexdigest()
        with patch.object(consumer.base, 'locked_source', return_value=(manifest['source'], manifest['sourceLockSha256'])):
            observed, inventory, selected = consumer.unpack_content(output, digest, self.root / 'lock', self.root / 'consumer')
        self.assertEqual((observed, inventory, selected), (receipt, manifest, compiled))
        self.assertEqual((self.root / 'consumer/source/data/sql/base/db_auth/base.sql').read_bytes(),
                         self.data['data/sql/base/db_auth/base.sql'])
        notice = 'source/' + content.ELUNA + '/docs/LICENSE.md'
        self.assertEqual(receipt['archiveFiles'][notice]['origin'], 'eluna')
        self.assertEqual((self.root / 'consumer' / notice).read_bytes(), b'eluna notice')

    def test_hash_failure_preserves_old_packages_and_publishes_nothing(self):
        self.build('existing')
        before = (self.root / 'existing/server-content.tar.gz').read_bytes()
        changed = copy.deepcopy(self.manifest)
        changed['files']['data/sql/base/db_auth/base.sql']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            self.build('bad', manifest=changed)
        self.assertFalse((self.root / 'bad').exists())
        self.assertFalse(list(self.root.glob('.server-content-*')))
        self.assertEqual((self.root / 'existing/server-content.tar.gz').read_bytes(), before)
        with self.assertRaises(ValueError):
            self.build('existing')

    def test_long_source_paths_use_gnu_metadata_and_round_trip_without_pax(self):
        source_path = 'modules/mod-one/data/sql/db-auth/' + 'long_' * 25 + 'update.sql'
        self.server = self.repository('server-long', dict(self.data, **{source_path: b'SELECT 1;\n'}))
        manifest = copy.deepcopy(self.manifest)
        manifest['files'][source_path] = self.server.identities([source_path], True)[source_path]
        manifest['databases']['auth']['updateOrder'].append({'path': source_path, 'state': 'MODULE'})
        receipt = self.build('long-names', manifest=manifest)
        archive_path = self.root / 'long-names/server-content.tar.gz'
        raw = gzip.decompress(archive_path.read_bytes())
        self.assertIn(b'././@LongLink\0', raw)
        self.assertNotIn(b'././@PaxHeader', raw)
        self.assertIn('source/' + source_path, receipt['archiveFiles'])
        with tarfile.open(archive_path, 'r:gz') as archive:
            self.assertEqual(archive.extractfile('source/' + source_path).read(), b'SELECT 1;\n')

    def test_explicit_complete_lua_map_rejects_unknown_paths_collisions_and_dependencies(self):
        for mutation in ('missing', 'hash', 'traversal', 'collision', 'dependency'):
            mapped = copy.deepcopy(self.lua)
            mapped['mode'] = 'mapped'
            for i, row in enumerate(mapped['files']):
                row['destination'] = f'script{i}.lua'
            if mutation == 'missing': mapped['files'].pop()
            elif mutation == 'hash': mapped['files'][0]['sha256'] = '0' * 64
            elif mutation == 'traversal': mapped['files'][0]['destination'] = '../escape.lua'
            elif mutation == 'collision': mapped['files'][1]['destination'] = 'SCRIPT0.lua'
            else: mapped['files'][0]['requirements'] = ['missing-client-AIO']
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                package.validate_lua(mapped, self.manifest)
        self.assertFalse((self.root / 'escape.lua').exists())

    def test_explicit_mapped_extension_is_copied_only_to_selected_destination(self):
        mapped = copy.deepcopy(self.lua)
        mapped['mode'] = 'mapped'
        extension = next(row for row in mapped['files'] if row['origin'] == 'eluna')
        extension['destination'] = 'extensions/first.ext'
        receipt = self.build('mapped', lua=mapped)
        self.assertEqual(receipt['luaFiles'], 1)
        self.assertTrue(receipt['configurationRequirements']['Eluna.Enabled'])
        self.assertFalse(receipt['luaRuntimeQualified'])
        self.assertIn('lua_scripts/extensions/first.ext', receipt['archiveFiles'])

    def test_compiled_module_mismatch_stops_before_packaging(self):
        receipt = dict(formatVersion=1, scope='compiled-server-module-selection',
            generatedListsMatchInstalledBinaries=True, source=self.manifest['source'],
            sourceLockSha256=self.manifest['sourceLockSha256'], enabledModules=['mod-one'],
            configFiles=['one.conf'], binaries={'worldserver': {}, 'dbimport': {}})
        self.assertTrue(package.validate_modules(receipt, self.manifest))
        for key, value in [('enabledModules', ['mod-other']), ('configFiles', ['wrong.conf']),
                           ('sourceLockSha256', '0' * 64), ('generatedListsMatchInstalledBinaries', False)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                package.validate_modules(dict(receipt, **{key: value}), self.manifest)

    def test_atomic_publish_does_not_replace_even_empty_destination_directory(self):
        stage, output = self.root / 'stage', self.root / 'published'
        stage.mkdir(); output.mkdir()
        (stage / 'data').write_text('keep staged')
        with self.assertRaises(FileExistsError):
            package.publish_directory(stage, output)
        self.assertEqual(list(output.iterdir()), [])
        self.assertEqual((stage / 'data').read_text(), 'keep staged')


if __name__ == '__main__':
    unittest.main()
