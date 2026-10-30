"""Actual source-backed ConfigMgr path/reload qualification (no parser model)."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

REFERENCE = os.environ.get('ESTERIA_CONFIG_PATH_REFERENCE')


@unittest.skipUnless(REFERENCE, 'requires actual source-built ConfigMgr reference executable')
class ConfigPathReference(unittest.TestCase):
    def test_real_parser_uses_selected_main_sibling_and_reloads(self):
        environment = {key: value for key, value in os.environ.items() if not key.startswith('AC_')}
        with tempfile.TemporaryDirectory(prefix='esteria-config-path-') as directory:
            target = Path(directory) / 'new-fixture'
            result = subprocess.run([str(Path(REFERENCE).resolve()), str(target)], env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout.decode(errors='replace')[-4096:])
            self.assertIn(b'ESTERIA_CONFIG_PATH_REFERENCE_PASS absolute relative bare reload default missing',
                          result.stdout)
            # The reference refuses an existing fixture. Re-entry may not rewrite
            # configurations, even though this tree is deliberately disposable.
            main = target / 'worldserver.conf'
            before = main.read_bytes()
            again = subprocess.run([str(Path(REFERENCE).resolve()), str(target)], env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            self.assertNotEqual(again.returncode, 0)
            self.assertEqual(before, main.read_bytes())


if __name__ == '__main__':
    unittest.main()
