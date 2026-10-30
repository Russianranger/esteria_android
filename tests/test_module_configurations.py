import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import qualify_module_configurations as qualify

REFERENCE = os.environ.get('ESTERIA_MODULE_CONFIG_REFERENCE')


class ModuleConfigurationGuards(unittest.TestCase):
    def test_existing_state_is_preserved_before_source_or_binary_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); saved = output / 'save'; saved.write_bytes(b'unchanged')
            with patch.object(qualify, 'source_binding') as binding, self.assertRaisesRegex(ValueError, 'preserved'):
                qualify.qualify(*[Path('/unused')] * 7, output)
            binding.assert_not_called(); self.assertEqual(saved.read_bytes(), b'unchanged')

    def test_unsafe_or_case_duplicate_selection_never_creates_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for names in (['../outside.conf'], ['x.conf', 'X.conf'], []):
                with self.subTest(names=names), self.assertRaisesRegex(ValueError, 'module selection'):
                    qualify.execute(Path('/unused'), root, names, root / 'run')
            self.assertFalse((root / 'run').exists())


@unittest.skipUnless(REFERENCE, 'requires actual source-built ConfigMgr module reference')
class ActualModuleConfiguration(unittest.TestCase):
    def test_real_parser_reads_every_selected_file_reloads_and_preserves_input(self):
        with tempfile.TemporaryDirectory(prefix='esteria-modules-') as temporary:
            root = Path(temporary); source = root / 'source'; (source / 'modules').mkdir(parents=True)
            (source / 'worldserver.conf').write_text('[worldserver]\nEluna.Enabled = 0\n')
            (source / 'modules/playerbots.conf').write_text('[worldserver]\nAiPlayerbot.CommandServerPort = 0\n'
                'AiPlayerbot.RandomBotAutologin = 0\nAiPlayerbot.MaxAddedBots = 4\n')
            (source / 'modules/second.conf').write_text('[module]\nSecond.Existing = 77\n')
            qualify.execute(Path(REFERENCE).resolve(), source, ['playerbots.conf', 'second.conf'], root / 'run')
            with self.assertRaisesRegex(ValueError, 'fixture preserved'):
                qualify.execute(Path(REFERENCE).resolve(), source, ['playerbots.conf', 'second.conf'], root / 'run')
            # Actual reference independently refuses its already-created tree.
            with self.assertRaisesRegex(ValueError, 'exit 1'):
                qualify.importer.run_importer(Path(REFERENCE).resolve(), root/'run/reference.conf', root/'run/reentry.log', timeout=30)

    def test_actual_parser_rejects_missing_selected_file_and_wrong_runtime_policy(self):
        for missing in (False, True):
            with tempfile.TemporaryDirectory(prefix='esteria-modules-') as temporary:
                root = Path(temporary); source = root / 'source'; (source / 'modules').mkdir(parents=True)
                (source / 'worldserver.conf').write_text('[worldserver]\nEluna.Enabled = 1\n')
                if not missing: (source / 'modules/playerbots.conf').write_text('[worldserver]\nAiPlayerbot.MaxAddedBots = 4\n')
                with self.subTest(missing=missing), self.assertRaises((ValueError, OSError)):
                    qualify.execute(Path(REFERENCE).resolve(), source, ['playerbots.conf'], root / 'run')


if __name__ == '__main__': unittest.main()
