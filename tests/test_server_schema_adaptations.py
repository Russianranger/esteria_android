import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from runtime import server_schema_adaptations as adaptation


class Connection:
    def __init__(self):
        self.tables = {name: [] for name in adaptation.baseline.DB_ORDER}
        self.rows = {name: 0 for name in adaptation.TABLES}
        self.applied = []

    def query(self, sql):
        if sql.startswith('SHOW TABLES FROM `acore_'):
            return list(self.tables[sql[len('SHOW TABLES FROM `acore_'):-1]])
        match = re.fullmatch(r'SELECT COUNT\(\*\) FROM `acore_characters`.`([^`]+)`', sql)
        if match and match[1] in self.rows:
            return [str(self.rows[match[1]])]
        raise AssertionError('Unexpected SQL: no content, credential or ledger writes are allowed')

    def apply(self, database, path):
        self.applied.append((database, path))
        self.tables[database].extend(adaptation.TABLES)


class AppearanceAdaptations(unittest.TestCase):
    def setUp(self):
        self.metadata = json.loads(adaptation.LOCK_PATH.read_bytes())
        self.lock = '5f72e02c89a265acb64c64a8743953926faa5b76b50c9b146846f17063be80c1'
        self.manifest = dict(formatVersion=1, scope='source-content-inventory', contentSha256Complete=True,
            sourceLockSha256=self.lock, source=copy.deepcopy(self.metadata['supportedSourceSelections'][self.lock]))
        self.connection = Connection()
        self.original = dict(baselineImportCompleted=True, sourceFiles={'canonical.sql': {'sha256': 'a' * 64}},
            appliedFiles=['canonical.sql'], coreBaseOrder={'characters': ['canonical.sql']},
            syntheticUpdaterLedgerRowsWritten=False, compiledAutoPopulationQualified=False)
        self.baseline_calls = []

    def baseline(self, connection, source, manifest, apply):
        self.baseline_calls.append((connection, source, manifest, apply))
        connection.tables['characters'].append('canonical_core_table')
        return self.original

    def initialize(self, **kwargs):
        return adaptation.initialize(self.connection, Path('/verified/source'), self.manifest,
            self.connection.apply, baseline_initializer=kwargs.pop('baseline_initializer', self.baseline), **kwargs)

    def test_exact_source_and_separate_proof_preserve_original_baseline_receipt(self):
        before = copy.deepcopy(self.original)
        prepared = adaptation.prepare(self.manifest)
        self.assertEqual(prepared.sql_path, adaptation.SQL_PATH)
        self.assertEqual(prepared.tables, adaptation.TABLES)
        self.assertFalse(prepared.proof['sqlExecuted'])
        result = self.initialize()
        self.assertEqual(self.original, before)
        self.assertEqual({key: result[key] for key in before}, before)
        self.assertEqual(self.connection.applied, [('characters', adaptation.SQL_PATH)])
        proof, = result['sourceDerivedAdaptations']
        self.assertTrue(proof['sourceDerived']); self.assertFalse(proof['canonicalOriginal'])
        self.assertTrue(proof['exactEmptyTableAdditionVerified']); self.assertTrue(proof['sqlExecuted'])
        for field in ('rowsSeeded', 'updaterLedgerRowsWritten', 'worldserverExecuted', 'gameplayQualified'):
            self.assertFalse(proof[field])
        with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
            self.initialize()
        self.assertEqual(len(self.connection.applied), 1)

    def test_both_exact_historical_and_current_source_selections_are_supported(self):
        for digest, source in self.metadata['supportedSourceSelections'].items():
            manifest = dict(self.manifest, sourceLockSha256=digest, source=source)
            with self.subTest(digest=digest):
                self.assertEqual(adaptation.prepare(manifest).proof['sourceLockSha256'], digest)
        self.assertEqual(len(self.metadata['supportedSourceSelections']), 2)

    def test_unknown_lock_changed_full_source_or_incomplete_inventory_stops_before_sql(self):
        for change in ('lock', 'source', 'submodule', 'hashes'):
            manifest = copy.deepcopy(self.manifest)
            if change == 'lock': manifest['sourceLockSha256'] = '0' * 64
            elif change == 'source': manifest['source']['commit'] = '0' * 40
            elif change == 'submodule': manifest['source']['submodules']['src/server/game/LuaEngine'] = '0' * 40
            else: manifest['contentSha256Complete'] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                adaptation.initialize(self.connection, Path('/source'), manifest, self.connection.apply,
                                      baseline_initializer=self.baseline)
            self.assertFalse(self.baseline_calls); self.assertFalse(self.connection.applied)

    def test_all_four_existing_databases_are_preserved_before_baseline_or_ddl(self):
        for database in adaptation.baseline.DB_ORDER:
            self.connection = Connection(); self.connection.tables[database] = ['existing_saved_state']
            with self.subTest(database=database), self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
                self.initialize()
            self.assertFalse(self.baseline_calls); self.assertFalse(self.connection.applied)

    def test_changed_sql_and_changed_cpp_audit_bindings_fail_before_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sql = root / 'appearance.sql'; sql.write_bytes(adaptation.SQL_PATH.read_bytes() + b'-- changed\n')
            with patch.object(adaptation, 'SQL_PATH', sql), self.assertRaisesRegex(ValueError, 'SQL changed'):
                self.initialize()
            changed = copy.deepcopy(self.metadata)
            changed['sourceBindings']['src/server/shared/BodyShapeWire.h']['sha256'] = '0' * 64
            lock = root / 'appearance.lock.json'; lock.write_text(json.dumps(changed))
            with patch.object(adaptation, 'LOCK_PATH', lock), self.assertRaisesRegex(ValueError, 'audit metadata changed'):
                self.initialize()
        self.assertFalse(self.baseline_calls); self.assertFalse(self.connection.applied)

    def test_changed_sql_during_original_baseline_is_not_applied(self):
        with tempfile.TemporaryDirectory() as temporary:
            sql = Path(temporary) / 'appearance.sql'; sql.write_bytes(adaptation.SQL_PATH.read_bytes())
            def changing(*args):
                value = self.baseline(*args)
                sql.write_bytes(b'changed after original baseline')
                return value
            with patch.object(adaptation, 'SQL_PATH', sql), self.assertRaisesRegex(ValueError, 'SQL changed'):
                self.initialize(baseline_initializer=changing)
        self.assertFalse(self.connection.applied)

    def test_existing_appearance_table_after_baseline_is_never_adopted(self):
        def existing(*args):
            value = self.baseline(*args)
            self.connection.tables['characters'].append(adaptation.TABLES[0])
            return value
        with self.assertRaisesRegex(ValueError, 'Existing appearance tables preserved'):
            self.initialize(baseline_initializer=existing)
        self.assertFalse(self.connection.applied)

    def test_extra_table_or_seeded_row_cannot_be_qualified(self):
        for kind in ('extra', 'row'):
            self.connection = Connection()
            def changed(database, path):
                self.connection.apply(database, path)
                if kind == 'extra': self.connection.tables[database].append('unexpected_table')
                else: self.connection.rows[adaptation.TABLES[0]] = 1
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                adaptation.initialize(self.connection, Path('/source'), self.manifest, changed,
                                      baseline_initializer=self.baseline)
            self.assertNotIn('sourceDerivedAdaptations', self.original)

    def test_failure_preserves_partial_tables_and_cannot_resume(self):
        def failing(database, path):
            self.connection.tables[database].append(adaptation.TABLES[0])
            raise RuntimeError('private engine failure')
        with self.assertRaises(RuntimeError):
            adaptation.initialize(self.connection, Path('/source'), self.manifest, failing,
                                  baseline_initializer=self.baseline)
        with self.assertRaisesRegex(ValueError, 'nonempty database preserved'):
            self.initialize()
        self.assertEqual(self.connection.tables['characters'], ['canonical_core_table', adaptation.TABLES[0]])

    def test_sql_is_only_two_empty_creators_and_module_needs_no_git_or_tools(self):
        raw = adaptation.SQL_PATH.read_bytes()
        self.assertEqual(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()), adaptation.SQL_IDENTITY)
        statements = re.sub(rb'--[^\n]*', b'', raw).strip().split(b';')
        statements = [statement.strip() for statement in statements if statement.strip()]
        self.assertEqual(len(statements), 2)
        self.assertEqual(re.findall(rb'CREATE TABLE `([^`]+)`', raw), [name.encode() for name in adaptation.TABLES])
        self.assertNotIn(b'IF NOT EXISTS', raw)
        self.assertIsNone(re.search(rb'\b(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|TRUNCATE|REFERENCES|DEFAULT\s+[\'"0-9])\b',
                                    b'\n'.join(statements), re.I))
        syntax = ast.parse(Path(adaptation.__file__).read_text())
        for node in ast.walk(syntax):
            if isinstance(node, ast.Import):
                self.assertTrue(all(alias.name in ('hashlib', 'json', 'os', 'stat', 'server_schema_baseline')
                                    for alias in node.names))
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, ('__future__', 'dataclasses', 'pathlib', None))
                self.assertTrue(node.level == 1 or node.module in ('__future__', 'dataclasses', 'pathlib'))


if __name__ == '__main__':
    unittest.main()
