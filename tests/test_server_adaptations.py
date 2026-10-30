import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import manifest_server_content as content


class ReviewedAdaptations(unittest.TestCase):
    def setUp(self):
        self.source = json.loads((content.ROOT / 'sources.lock.json').read_text())['sources']['server']

    def test_current_exact_patch_bytes_and_distinct_scopes_are_reviewed(self):
        content.validate_patch_contract(self.source, content.ROOT)
        records = content.adaptation_records(self.source)
        root = [row for row in records if row['submodule'] is None]
        self.assertEqual([Path(row['path']).name for row in root], ['0004-attunement-stat-api.patch'])
        self.assertIn('display-only', root[0]['effect'])
        self.assertTrue(all(not row[key] for row in records for key in
                            ('sqlOrLuaInputsChanged', 'moduleSelectionChanged', 'updaterOrderingChanged')))

    def test_known_patch_cannot_move_between_root_and_eluna_scope(self):
        for index in (0, len(self.source['patches']) - 1):
            source = copy.deepcopy(self.source)
            patch = source['patches'][index]
            if 'submodule' in patch:
                del patch['submodule']
            else:
                patch['submodule'] = content.ELUNA
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, 'scope requires'):
                content.validate_patch_contract(source, content.ROOT)

    def test_checksum_valid_but_unreviewed_sql_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / 'new-sql.patch'
            path.write_text('--- a/data/sql/base/db_auth/account.sql\n+++ b/data/sql/base/db_auth/account.sql\n')
            source = copy.deepcopy(self.source)
            source['patches'] = [dict(path=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())]
            with self.assertRaisesRegex(ValueError, 'contract review'):
                content.validate_patch_contract(source, root)
            with self.assertRaisesRegex(ValueError, 'was not reviewed'):
                content.adaptation_records(source)

    def test_named_reviewed_patch_with_changed_bytes_is_rejected(self):
        source = copy.deepcopy(self.source)
        source['patches'][-1]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            content.validate_patch_contract(source, content.ROOT)
        with self.assertRaisesRegex(ValueError, 'was not reviewed'):
            content.adaptation_records(source)


if __name__ == '__main__':
    unittest.main()
