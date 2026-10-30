import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from runtime import server_content as content


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def source_identity(raw):
    return dict(identity(raw), gitMode='100644',
                gitBlob=hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest())


class RuntimeContent(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'extracted'
        self.receipt_path = self.base / 'package-receipt.json'
        self.source = dict(repository='https://example.invalid/server', commit='a' * 40,
                           submodules={content.ELUNA: 'b' * 40}, patches=[])
        self.lock = 'c' * 64
        self.data = {
            content.MAIN_CONFIGS[0]: b'[authserver]\n',
            content.MAIN_CONFIGS[1]: b'[worldserver]\n',
            'LICENSE': b'original notice\n',
            'modules/mod-one/conf/one.conf.dist': b'[module]\nOne.Enabled = 0\n',
            'modules/mod-one/LICENSE': b'module notice\n',
            'modules/mod-one/data/sql/db-auth/update.sql': b'SELECT 1;\n',
        }
        plans = {}
        for database in ('auth', 'characters', 'world'):
            path = content.DATABASES[database] + '/updates.sql'
            self.data[path] = (b'-- large streamed world fixture\n' + b'x' * (content.BLOCK * 3)
                               if database == 'world' else b'CREATE TABLE updates(name TEXT);\n')
            plans[database] = dict(base=[path], updateOrder=[], executionOrderQualified=True)
        plans['auth']['updateOrder'] = [dict(path='modules/mod-one/data/sql/db-auth/update.sql',
                                           state='MODULE', origin='mod-one')]
        self.manifest = dict(formatVersion=1, scope='source-content-inventory',
            source=copy.deepcopy(self.source), sourceLockSha256=self.lock, contentSha256Complete=True,
            profile='explicit-module-list', enabledModules=['mod-one'], databases=plans,
            modules=[dict(name='mod-one', configTemplates=['modules/mod-one/conf/one.conf.dist'],
                          notices=['modules/mod-one/LICENSE'], luaCandidates=['modules/mod-one/lua_scripts/held.lua'])],
            files={path: source_identity(raw) for path, raw in self.data.items()},
            elunaFiles={'docs/LICENSE.md': source_identity(b'Eluna notice\n'),
                        'extensions/held.ext': source_identity(b'-- held Eluna\n')})
        for path, raw in [('modules/mod-one/lua_scripts/held.lua', b'-- held module\n'),
                          ('modules/mod-one/data/sql/manual/uninstall.sql', b'DROP TABLE updates;\n')]:
            self.manifest['files'][path] = source_identity(raw)
        self.compiled = dict(formatVersion=1, scope='compiled-server-module-selection',
            source=copy.deepcopy(self.source), sourceLockSha256=self.lock, enabledModules=['mod-one'],
            configFiles=['one.conf'], generatedListsMatchInstalledBinaries=True,
            serverBuild=dict(bytes=777, sha256='d' * 64), compileCommands=dict(bytes=888, sha256='e' * 64),
            binaries={name: dict(bytes=999, sha256='f' * 64, generatedLiteralsPresent=True)
                      for name in ('worldserver', 'dbimport')})
        self.lua = dict(formatVersion=1, mode='disabled', serverRevision=self.source['commit'],
            elunaRevision=self.source['submodules'][content.ELUNA], files=[
                dict(origin='server', source='modules/mod-one/lua_scripts/held.lua', destination=None,
                     reason='Held for qualified dependencies', requirements=['matching-client'],
                     sha256=self.manifest['files']['modules/mod-one/lua_scripts/held.lua']['sha256']),
                dict(origin='eluna', source='extensions/held.ext', destination=None,
                     reason='Held while Lua is disabled', requirements=[],
                     sha256=self.manifest['elunaFiles']['extensions/held.ext']['sha256'])])
        self.payload = {'source/' + path: raw for path, raw in self.data.items()}
        self.payload['source/' + content.ELUNA + '/docs/LICENSE.md'] = b'Eluna notice\n'
        self.receipt = dict(formatVersion=1, scope='immutable-server-source-content-package',
            source=copy.deepcopy(self.source), sourceLockSha256=self.lock, moduleSelectionVerified=True,
            archiveReadBackVerified=True, deterministicArchive=True, sourceDirectory='source',
            luaMode='disabled', luaFiles=0,
            configurationRequirements={'Eluna.Enabled': False, 'Eluna.ScriptPath': 'lua_scripts'},
            archive=dict(bytes=12345, sha256='1' * 64), sqlExecuted=False, gameplayQualified=False)
        self.write()

    def write(self):
        metadata = {'metadata/content-manifest.json': encoded(self.manifest),
                    'metadata/compiled-modules.json': encoded(self.compiled),
                    'metadata/lua-map.json': encoded(self.lua)}
        # Producer input JSON identities may differ from its canonical archive
        # metadata. The trusted archiveFiles inventory binds the bytes installed.
        for field in ('contentManifest', 'compiledModules', 'luaMap'):
            self.receipt[field] = dict(bytes=42, sha256='2' * 64)
        plan = {key: value for key, value in self.receipt.items()
                if key not in ('archive', 'archiveFiles', 'archiveReadBackVerified', 'deterministicArchive')}
        metadata['metadata/package-plan.json'] = encoded(plan)
        rows = {}
        for name, raw in self.payload.items():
            if name.startswith('source/' + content.ELUNA + '/'):
                path, origin = name[len('source/' + content.ELUNA + '/'):], 'eluna'
                row = self.manifest['elunaFiles'][path]
            else:
                path, origin = name[len('source/'):], 'server'
                row = self.manifest['files'][path]
            rows[name] = dict(identity(raw), origin=origin, source=path, gitBlob=row['gitBlob'])
        for name, raw in (self.payload | metadata).items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        rows.update({name: identity(raw) for name, raw in metadata.items()})
        self.receipt['archiveFiles'] = rows
        self.pin_receipt()

    def pin_receipt(self):
        raw = encoded(self.receipt)
        self.receipt_path.write_bytes(raw)
        self.pin = identity(raw)['sha256']

    def verify(self, **kwargs):
        return content.verify(self.root, self.receipt_path, self.pin,
                              self.source, self.lock, self.compiled, **kwargs)

    def snapshot(self):
        return {path.relative_to(self.base).as_posix(): path.read_bytes()
                for path in self.base.rglob('*') if path.is_file() and not path.is_symlink()}

    def test_verified_content_is_bound_to_full_original_engine_and_selected_payload(self):
        before = self.snapshot()
        events = []
        result = self.verify(progress=events.append)
        self.assertEqual(result.root, self.root)
        self.assertEqual(result.source, self.root / 'source')
        self.assertEqual((result.manifest, result.compiled, result.receipt),
                         (self.manifest, self.compiled, self.receipt))
        self.assertEqual(result.identities['receipt']['sha256'], self.pin)
        self.assertEqual(set(result.identities['files']), set(self.receipt['archiveFiles']))
        self.assertTrue(any(event['fileBytes'] == content.BLOCK for event in events))
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((result.source / 'modules/mod-one/data/sql/manual/uninstall.sql').exists())

    def test_outer_pin_is_checked_before_any_content_tree_is_opened(self):
        before = self.snapshot()
        with self.assertRaisesRegex(content.ContentError, 'outer pin'):
            content.verify(self.base / 'does-not-exist', self.receipt_path, '0' * 64,
                           self.source, self.lock, self.compiled)
        self.assertEqual(self.snapshot(), before)

    def test_full_source_and_lock_selection_must_match_external_inputs(self):
        for field in ('source', 'lock'):
            with self.subTest(field=field), self.assertRaises(content.ContentError):
                content.verify(self.root, self.receipt_path, self.pin,
                    dict(self.source, repository='https://example.invalid/other') if field == 'source' else self.source,
                    '0' * 64 if field == 'lock' else self.lock, self.compiled)

    def test_complete_compiled_object_is_compared_not_only_module_names(self):
        changed = copy.deepcopy(self.compiled)
        changed['compileCommands']['sha256'] = '0' * 64
        with self.assertRaisesRegex(content.ContentError, 'original engine provenance'):
            content.verify(self.root, self.receipt_path, self.pin, self.source, self.lock, changed)

    def test_metadata_hashes_and_exact_plan_are_bound_to_pinned_receipt(self):
        path = self.root / 'metadata/content-manifest.json'
        original = path.read_bytes()
        path.write_bytes(original.replace(b'mod-one', b'mod-two'))
        with self.assertRaisesRegex(content.ContentError, 'digest mismatch'):
            self.verify()
        path.write_bytes(original)
        plan = self.root / 'metadata/package-plan.json'
        plan.write_bytes(encoded(dict(json.loads(plan.read_bytes()), luaFiles=7)))
        self.receipt['archiveFiles']['metadata/package-plan.json'] = identity(plan.read_bytes())
        self.pin_receipt()
        with self.assertRaisesRegex(content.ContentError, 'plan differs'):
            self.verify()

    def test_self_consistent_metadata_cannot_change_module_template_selection(self):
        self.manifest['modules'][0]['configTemplates'] = []
        self.write()
        with self.assertRaisesRegex(content.ContentError, 'configuration templates differ'):
            self.verify()

    def test_payload_must_match_manifest_identity_even_if_receipt_is_self_consistent(self):
        self.manifest['files']['LICENSE']['sha256'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(content.ContentError, 'source manifest'):
            self.verify()

    def test_active_or_incomplete_lua_mapping_is_explicitly_rejected(self):
        original = copy.deepcopy(self.lua)
        for kind in ('mode', 'destination', 'missing'):
            self.lua = copy.deepcopy(original)
            if kind == 'mode':
                self.lua['mode'] = 'mapped'
            elif kind == 'destination':
                self.lua['files'][0]['destination'] = 'active.lua'
            else:
                self.lua['files'].pop()
            self.write()
            with self.subTest(kind=kind), self.assertRaises(content.ContentError):
                self.verify()

    def test_unsafe_case_colliding_and_file_directory_inventory_paths_are_rejected(self):
        original = copy.deepcopy(self.receipt)
        for name in ('../escaped', '/absolute', 'source\\bad', 'source/LICENSE/child', 'source/license'):
            self.receipt = copy.deepcopy(original)
            self.receipt['archiveFiles'][name] = identity(b'')
            self.pin_receipt()
            with self.subTest(name=name), self.assertRaises(content.ContentError):
                self.verify()
        self.assertFalse((self.base / 'escaped').exists())

    def test_extra_missing_and_changed_files_are_rejected_without_mutation(self):
        extra = self.root / 'unexpected'
        extra.write_bytes(b'not selected')
        before = self.snapshot()
        with self.assertRaisesRegex(content.ContentError, 'unexpected content file'):
            self.verify()
        self.assertEqual(self.snapshot(), before)
        extra.unlink()
        path = self.root / 'source/LICENSE'
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(content.ContentError, 'file set incomplete'):
            self.verify()
        path.write_bytes(raw.upper())
        with self.assertRaisesRegex(content.ContentError, 'digest mismatch'):
            self.verify()

    def test_parent_symlink_file_symlink_fifo_and_hardlink_are_rejected(self):
        path = self.root / 'source/LICENSE'
        raw = path.read_bytes()
        path.unlink()
        path.symlink_to(self.receipt_path)
        with self.assertRaises(content.ContentError):
            self.verify()
        path.unlink()
        os.mkfifo(path)
        with self.assertRaises(content.ContentError):
            self.verify()
        path.unlink()
        target = self.base / 'hardlink-target'
        target.write_bytes(raw)
        os.link(target, path)
        with self.assertRaises(content.ContentError):
            self.verify()
        path.unlink()
        path.write_bytes(raw)
        actual = self.base / 'actual'
        self.root.rename(actual)
        self.root.symlink_to(actual, target_is_directory=True)
        with self.assertRaises(content.ContentError):
            self.verify()

    def test_cancellation_before_and_between_hash_blocks_never_mutates_inputs(self):
        before = self.snapshot()
        with self.assertRaises(content.ContentCancelled):
            self.verify(cancelled=lambda: True)
        stopped, large_events = False, []
        def progress(event):
            nonlocal stopped
            if event['fileTotalBytes'] > content.BLOCK:
                large_events.append(event)
                stopped = True
        with self.assertRaises(content.ContentCancelled):
            self.verify(progress=progress, cancelled=lambda: stopped)
        self.assertEqual(len(large_events), 1)
        self.assertEqual(large_events[0]['fileBytes'], content.BLOCK)
        self.assertEqual(self.snapshot(), before)

    def test_runtime_module_imports_only_standard_library_dependencies(self):
        syntax = ast.parse(Path(content.__file__).read_text())
        imports = []
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                imports.extend(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual(node.level, 0)
                imports.append(node.module.split('.')[0])
        self.assertTrue(set(imports) <= sys.stdlib_module_names | {'__future__'}, imports)


if __name__ == '__main__':
    unittest.main()
