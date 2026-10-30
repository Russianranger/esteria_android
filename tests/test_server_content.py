import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools import manifest_server_content as content


def include_sql(*rows):
    return ('INSERT INTO `updates_include` (`path`, `state`) VALUES\n' +
            ',\n'.join("('%s', '%s')" % row for row in rows) + ';\n').encode()


def plan_fixture():
    files = {'data/sql/base/db_world/a.sql': b'base first',
             'data/sql/base/db_world/updates_include.sql': include_sql(
                 ('$/updates/released', 'RELEASED'), ('$/updates/pending', 'PENDING'),
                 ('$/updates/archive', 'ARCHIVED')),
             'updates/released/z.sql': b'new core', 'updates/archive/b.sql': b'old core',
             'updates/pending/a.sql': b'pending',
             'modules/mod-one/data/sql/db-world/m.sql': b'module',
             'modules/mod-one/data/sql/db-world/base/n.sql': b'module base',
             'modules/mod-one/data/sql/manual/remove.sql': b'never apply',
             'modules/mod-one/data/sql/updates/pending_db_world/u.sql': b'not auto scanned',
             'modules/mod-one/data/sql/other-world-name/c.sql': b'substring match',
             'modules/mod-one/data/sql/db-auth/q.sql': b'auth only'}
    return files


class Plans(unittest.TestCase):
    def test_literal_include_rows_only_and_safe_relative_sources(self):
        rows = content.parse_includes(include_sql(('$/first', 'RELEASED'), ('$/second', 'CUSTOM')))
        self.assertEqual(rows, [{'path': 'first', 'state': 'RELEASED'}, {'path': 'second', 'state': 'CUSTOM'}])
        for value in [include_sql(('/etc', 'RELEASED')), include_sql(('$/../escape', 'RELEASED')),
                      include_sql(('$/same', 'RELEASED'), ('$/same', 'CUSTOM')),
                      b"INSERT INTO `updates_include` VALUES (CONCAT('$','/sql'),'RELEASED');",
                      b"UPDATE updates_include SET state='ARCHIVED';"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                content.parse_includes(value)

    def test_base_sort_and_two_phase_global_basename_update_order(self):
        files = plan_fixture()
        plan = content.database_plan(files, 'world', ['mod-one'], files.__getitem__)
        self.assertEqual([Path(row['path']).name for row in plan['updateOrder']],
                         ['b.sql', 'z.sql', 'a.sql', 'c.sql', 'm.sql', 'n.sql'])
        self.assertEqual(plan['base'], ['data/sql/base/db_world/a.sql',
                                       'data/sql/base/db_world/updates_include.sql'])
        picked = {row['path'] for row in plan['updateOrder']}
        self.assertNotIn('modules/mod-one/data/sql/manual/remove.sql', picked)
        self.assertNotIn('modules/mod-one/data/sql/updates/pending_db_world/u.sql', picked)
        self.assertNotIn('modules/mod-one/data/sql/db-auth/q.sql', picked)
        self.assertFalse(plan['existingDatabasePlan'])

    def test_duplicate_basename_blocks_even_across_core_and_module(self):
        files = plan_fixture()
        files['modules/mod-one/data/sql/db-world/z.sql'] = b'conflicting update'
        plan = content.database_plan(files, 'world', ['mod-one'], files.__getitem__)
        self.assertEqual(len(plan['duplicateBasenames']['z.sql']), 2)
        self.assertIsNone(plan['updateOrder'])
        self.assertFalse(plan['executionOrderQualified'])

    def test_depth_ten_boundary_and_missing_custom_root_reported(self):
        files = plan_fixture()
        deep = 'updates/released/' + '/'.join(['d'] * 9) + '/depth10.sql'
        deeper = 'updates/released/' + '/'.join(['d'] * 10) + '/depth11.sql'
        files[deep] = files[deeper] = b'select 1;'
        files['data/sql/base/db_world/updates_include.sql'] = include_sql(
            ('$/updates/released', 'RELEASED'), ('$/custom/private', 'CUSTOM'))
        plan = content.database_plan(files, 'world', [], files.__getitem__)
        self.assertEqual(plan['ignoredBeyondDepth10'], [deeper])
        self.assertIn(deep, [row['path'] for row in plan['discoveredUpdates']])
        self.assertEqual(plan['missingSourceDirectories'][0]['path'], 'custom/private')
        self.assertFalse(plan['executionOrderQualified'])

    def test_playerbots_paths_are_relative_to_its_own_source_and_no_module_list(self):
        root = 'modules/mod-playerbots'
        files = {root + '/data/sql/playerbots/base/updates_include.sql':
                 include_sql(('$/data/sql/playerbots/updates', 'RELEASED')),
                 root + '/data/sql/playerbots/updates/first.sql': b'bot update',
                 root + '/modules/mod-one/data/sql/db_playerbot/wrong.sql': b'not loaded'}
        plan = content.database_plan(files, 'playerbots', ['mod-one'], files.__getitem__)
        self.assertEqual([row['path'] for row in plan['updateOrder']],
                         [root + '/data/sql/playerbots/updates/first.sql'])

    def test_source_profile_requires_src_and_not_merely_cmake_or_lua(self):
        self.assertEqual(content.source_modules([
            'modules/mod-live/src/main.cpp', 'modules/mod-live/src/nested/a.cpp',
            'modules/mod-old/CMakeLists.txt', 'modules/mod-lua/lua_scripts/a.lua']), ['mod-live'])

    def test_manifest_keeps_execution_and_runtime_unqualified_and_requires_post_update_realm_gate(self):
        class MemorySource:
            tree = '1' * 40

            def __init__(self, contents):
                self.contents = contents
                self.files = {name: {'kind': 'blob', 'mode': '100644', 'gitBlob': '2' * 40}
                              for name in contents}

            def read(self, name):
                return self.contents[name]

            def identities(self, names, hashes):
                return {name: {'gitBlob': self.files[name]['gitBlob']} for name in names}

        files = {name: b'evidence' for name in content.EVIDENCE}
        for db in ('auth', 'characters', 'world'):
            root = content.DATABASES[db][1]
            files[root + '/updates_include.sql'] = include_sql(('$/updates/' + db, 'RELEASED'))
            files['updates/' + db + '/update.sql'] = b'update'
        files['modules/mod-one/src/source.cpp'] = b'compiled module'
        files['modules/mod-one/data/sql/manual/remove.sql'] = b'must stay excluded'
        server = MemorySource(files)
        server.files[content.ELUNA] = {'kind': 'commit', 'gitBlob': content.SUPPORTED_ELUNA}
        eluna = MemorySource({'extensions/first.ext': b'extension'})
        source = {'submodules': {content.ELUNA: content.SUPPORTED_ELUNA}}
        manifest = content.make_manifest(server, eluna, source, 'a' * 64,
                                         ['mod-one'], 'all-source-static', False)
        self.assertFalse(manifest['sqlExecuted'])
        self.assertFalse(manifest['databaseQualified'])
        self.assertFalse(manifest['androidRuntimeQualified'])
        self.assertFalse(manifest['packagingSelectionComplete'])
        self.assertFalse(manifest['contentSha256Complete'])
        self.assertTrue(manifest['loaderContract']['localRealmGate']['afterAllCoreAndModuleUpdates'])
        self.assertTrue(manifest['loaderContract']['localRealmGate']['requireAuthenticatedLoopbackVerification'])
        self.assertEqual(manifest['modules'][0]['sqlNotDiscoveredByUpdater'],
                         ['modules/mod-one/data/sql/manual/remove.sql'])


class GitContent(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / 'source'
        self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.name', 'Content Test')
        self.git('config', 'user.email', 'content@example.invalid')

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.PIPE).decode().strip()

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')
        return self.git('rev-parse', 'HEAD')

    def test_hashes_exact_committed_bytes_ignores_modified_and_untracked_inputs(self):
        data = b'committed\x00data\r\n' * 100000
        (self.repo / 'data.sql').write_bytes(data)
        revision = self.commit()
        (self.repo / 'data.sql').write_bytes(b'local work must remain untouched')
        (self.repo / 'private.sql').write_text('do not package')
        source = content.GitObjects(self.repo, revision)
        record = source.identities(['data.sql'], True)['data.sql']
        self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(record['bytes'], len(data))
        self.assertEqual((self.repo / 'data.sql').read_bytes(), b'local work must remain untouched')
        self.assertNotIn('private.sql', source.files)
        self.assertEqual(source.env['GIT_NO_LAZY_FETCH'], '1')

    def test_metadata_only_has_exact_blob_identity_but_no_content_hash_claim(self):
        (self.repo / 'sample.sql').write_text('SELECT 1;\n')
        revision = self.commit()
        source = content.GitObjects(self.repo, revision)
        record = source.identities(['sample.sql'], False)['sample.sql']
        self.assertEqual(record['gitBlob'], self.git('rev-parse', revision + ':sample.sql'))
        self.assertNotIn('sha256', record)
        self.assertNotIn('bytes', record)

    def test_symlinks_cannot_become_runtime_files(self):
        (self.repo / 'unsafe.sql').symlink_to('/etc/passwd')
        revision = self.commit()
        source = content.GitObjects(self.repo, revision)
        with self.assertRaises(ValueError):
            source.identities(['unsafe.sql'], True)
        with self.assertRaises(ValueError):
            source.read('unsafe.sql')

    def test_output_never_replaces_existing_file_or_symlink(self):
        output = self.root / 'manifest.json'
        content.atomic_output(output, {'sqlExecuted': False})
        self.assertEqual(json.loads(output.read_text()), {'sqlExecuted': False})
        with self.assertRaises(ValueError):
            content.atomic_output(output, {'overwrite': True})
        link = self.root / 'link.json'
        link.symlink_to(self.root / 'absent')
        with self.assertRaises(ValueError):
            content.atomic_output(link, {})
        self.assertFalse((self.root / 'absent').exists())
        self.assertFalse(list(self.root.glob('.server-content-*')))


if __name__ == '__main__':
    unittest.main()
