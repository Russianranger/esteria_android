import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_playerbots_reference as reference


class PlayerbotsReferenceGuards(unittest.TestCase):
    def test_compile_definition_requires_enabled_nonambiguous_module(self):
        for arguments in (['c++', '-DMOD_PLAYERBOTS'], ['c++', '-D', 'MOD_PLAYERBOTS=1']):
            reference.playerbots_definition({'arguments': arguments})
        for arguments in (['c++'], ['c++', '-DMOD_PLAYERBOTS=0'], ['c++', '-UMOD_PLAYERBOTS'],
                          ['c++', '-DMOD_PLAYERBOTS', '-UMOD_PLAYERBOTS'],
                          ['c++', '-DMOD_PLAYERBOTS', '-DMOD_PLAYERBOTS=1']):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(ValueError, 'enable MOD_PLAYERBOTS'):
                reference.playerbots_definition({'arguments': arguments})

    def test_commands_bind_exact_real_source_paths_and_all_required_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); server = root / 'server'; integration = root / 'integration'
            rows = [dict(file=str(server / name), arguments=['c++', '-DMOD_PLAYERBOTS'])
                    for name in reference.DATABASE_INPUTS]
            rows.append(dict(file=str(integration / reference.INPUTS[0]), arguments=['c++', '-DMOD_PLAYERBOTS']))
            path = root / 'compile_commands.json'; path.write_text(json.dumps(rows))
            self.assertEqual(reference.commands(path, server, integration), reference.files.identity(path))
            for wrong in (rows[:-1], rows + [rows[0]],
                          [dict(rows[0], file='/unrelated/' + reference.DATABASE_INPUTS[0]), *rows[1:]]):
                path.write_text(json.dumps(wrong))
                with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                    reference.commands(path, server, integration)

    def test_reference_source_is_bound_to_git_revision_and_disk_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in reference.INPUTS:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'actual source\n')
            with patch.object(reference.subprocess, 'check_output', return_value=b'actual source\n'):
                actual = reference.source_inputs(root, 'a' * 40)
                self.assertEqual(set(actual), set(reference.INPUTS))
                (root / reference.INPUTS[0]).write_bytes(b'changed source\n')
                with self.assertRaisesRegex(ValueError, 'differs from integration revision'):
                    reference.source_inputs(root, 'a' * 40)


if __name__ == '__main__':
    unittest.main()
