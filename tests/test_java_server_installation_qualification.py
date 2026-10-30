"""Bounded host input/receipt contracts; these tests execute no SQL or guest."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import qualify_java_server_installation as qualification


class NativeJavaInstallationQualificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='esteria-java-installation-contract-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def test_actual_gradle_helper_closure_preserves_nested_sources_and_hashes(self):
        target = self.root / 'assets'; target.mkdir()
        records = qualification.helper_assets(target, 'app/server-installation.gradle',
            'installationHelpers', 'server-installation', ('local-server.json', 'config/local-server.json'))
        self.assertEqual(len(records), 18)
        self.assertIn('server/appearance-schema-v1.sql', records)
        manifest = json.loads((target / 'server-installation/manifest.json').read_bytes())
        self.assertEqual(manifest, dict(formatVersion=1, files=records))
        for name, pin in records.items():
            raw = (target / 'server-installation' / name).read_bytes()
            self.assertEqual(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()), pin)

    def test_existing_output_and_linked_input_preserve_original_files(self):
        existing = self.root / 'existing'; existing.mkdir(); sentinel = existing / 'sentinel'; sentinel.write_bytes(b'KEEP')
        with self.assertRaises(ValueError):
            qualification.new_directory(existing)
        self.assertEqual(sentinel.read_bytes(), b'KEEP')
        linked = self.root / 'linked'; linked.symlink_to(sentinel)
        with self.assertRaises((ValueError, OSError)):
            qualification.copy(linked, self.root / 'copied')
        self.assertFalse((self.root / 'copied').exists())

    @staticmethod
    def complete_receipt():
        # Metadata-only fixture, deliberately never used as runtime evidence.
        value = dict(formatVersion=1, scope='native-arm64-java-owned-installation-promotion-and-restart',
            integrationRevision='a' * 40, phase='complete')
        for name in ('qualificationSucceeded', 'javaCoordinatorExecuted', 'actualSqlExecuted', 'slotPromoted',
                'productionProotProcessExecuted', 'completedSelectionReadBack', 'activeFreshInitializationRefused',
                'restartedSameLiveSqlUuid', 'actualCoreAccountRealmAndBotSqlPreserved',
                'privateJournalsAndCredentialsPreserved', 'twoCleanDatabaseStopsVerified'):
            value[name] = True
        for name in ('androidRuntimeQualified', 'androidApiExecuted', 'androidBionicProotLocatorExecuted',
                'worldserverExecuted', 'authserverExecuted', 'serverDataQualified', 'characterPersistenceQualified',
                'playerbotsAiQualified', 'gameplayQualified'):
            value[name] = False
        return value

    def test_partial_or_scope_widened_receipt_is_refused(self):
        original = self.complete_receipt(); qualification.validate_result(original, 'a' * 40)
        for field in original:
            changed = copy.deepcopy(original)
            if type(changed[field]) is bool:
                changed[field] = not changed[field]
            else:
                changed[field] = 'different'
            with self.subTest(field=field), self.assertRaises(ValueError):
                qualification.validate_result(changed, 'a' * 40)
        changed = copy.deepcopy(original); changed['actualSqlExecuted'] = 1
        with self.assertRaises(ValueError):
            qualification.validate_result(changed, 'a' * 40)


if __name__ == '__main__':
    unittest.main()
