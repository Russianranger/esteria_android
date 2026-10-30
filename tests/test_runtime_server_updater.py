import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import owned_process_group as runtime_owner
from runtime import server_updater as runtime
from tools import owned_process_group as host_owner
from tools import qualify_dbimport as host


class RuntimeUpdaterPrimitives(unittest.TestCase):
    def test_standalone_tool_owner_bytes_match_and_native_updater_uses_runtime_owner(self):
        self.assertEqual(Path(host_owner.__file__).read_bytes(), Path(runtime_owner.__file__).read_bytes())
        self.assertIs(host.OwnedGroup, runtime.OwnedGroup)
        for name in ('os', 'signal', 'subprocess', 'time'):
            self.assertIs(getattr(host_owner, name), getattr(runtime_owner, name))
        for name in ('render_importer', 'run_importer', 'expected_updates', 'schema_snapshot'):
            self.assertIs(getattr(host, name), getattr(runtime, name))

    def test_update_expectations_hash_actual_binary_bytes_and_reject_duplicate_basenames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = b'-- unchanged source SQL\n\x00\xff\n'
            path = root / 'updates/revision.sql'; path.parent.mkdir(); path.write_bytes(raw)
            selection = [dict(path='updates/revision.sql', state='MODULE')]
            manifest = {'databases': {'world': {'updateOrder': selection}}}
            self.assertEqual(runtime.expected_updates(root, manifest, 'world'),
                             {'revision.sql': (hashlib.sha1(raw).hexdigest(), 'MODULE')})
            second = root / 'other/revision.sql'; second.parent.mkdir(); second.write_bytes(raw)
            selection.append(dict(path='other/revision.sql', state='MODULE'))
            with self.assertRaisesRegex(ValueError, 'duplicate SQL basename'):
                runtime.expected_updates(root, manifest, 'world')

    def test_update_input_links_and_special_files_are_refused_before_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = {'databases': {'world': {'updateOrder': [dict(path='source.sql', state='PENDING')]}}}
            target = root / 'target'; target.write_bytes(b'SELECT 1;\n')
            source = root / 'source.sql'; source.symlink_to(target)
            with self.assertRaises((ValueError, OSError)):
                runtime.expected_updates(root, manifest, 'world')
            source.unlink(); os.mkfifo(source)
            with self.assertRaisesRegex(ValueError, 'not-a-regular-file'):
                runtime.expected_updates(root, manifest, 'world')

    def test_existing_private_log_cannot_be_reused_or_launch_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); log = root / 'existing.log'; log.write_bytes(b'private previous evidence')
            with patch.object(runtime.subprocess, 'Popen') as start, self.assertRaises(FileExistsError):
                runtime.run_importer(root / 'dbimport', root / 'dbimport.conf', log)
            start.assert_not_called()
            self.assertEqual(log.read_bytes(), b'private previous evidence')

    def test_ledger_snapshot_preserves_canonical_hash_semantics_and_archived_policy(self):
        expected = {name: {'new.sql': ('a' * 40, 'MODULE'), 'old.sql': ('b' * 40, 'ARCHIVED')}
                    for name in runtime.DATABASES}
        tables = ['updates', 'updates_include']
        rows = ['new.sql\t' + 'a' * 40 + '\tMODULE', 'old.sql\t\tARCHIVED']
        class Connection:
            def __init__(self): self.queries = []
            def query(self, query):
                self.queries.append(query)
                if 'acore_playerbots' in query: return []
                return tables if query.startswith('SHOW TABLES') else rows
        connection = Connection()
        snapshot = runtime.schema_snapshot(connection, expected)
        canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        for name in runtime.DATABASES:
            self.assertEqual(snapshot[name], dict(tableCount=2, tablesSha256=hashlib.sha256(canonical(tables)).hexdigest(),
                ledgerRows=2, ledgerSha256=hashlib.sha256(canonical(rows)).hexdigest(), sourceUpdateNamesVerified=2))
        self.assertTrue(all(query.startswith(('SELECT ', 'SHOW TABLES ')) for query in connection.queries))

    def test_runtime_modules_import_only_stdlib_and_runtime_primitives(self):
        for module in (runtime, runtime_owner):
            syntax = ast.parse(Path(module.__file__).read_text())
            for node in ast.walk(syntax):
                if isinstance(node, ast.Import):
                    self.assertTrue(all(alias.name.split('.')[0] in sys.stdlib_module_names or
                        alias.name in ('server_config', 'server_schema_baseline') for alias in node.names))
                elif isinstance(node, ast.ImportFrom):
                    self.assertTrue(node.level == 1 and node.module in (None, 'owned_process_group') or
                        node.level == 0 and node.module.split('.')[0] in sys.stdlib_module_names | {'owned_process_group'})


if __name__ == '__main__':
    unittest.main()
