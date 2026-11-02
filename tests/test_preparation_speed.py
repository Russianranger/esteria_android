"""Real JVM propagation checks for the preparation-only speed selection."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PreparationSpeedHost(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'Java17 required')
    def test_bounded_rates_and_worker_local_guest_environment(self):
        with tempfile.TemporaryDirectory() as output:
            base = Path('io/github/russianranger/esteria/core/runtime/install')
            sources = [ROOT / 'core/src/main/java' / base / (name + '.java')
                       for name in ('PreparationSpeed', 'RuntimeReadPolicy')]
            sources.append(ROOT / 'core/src/test/java' / base / 'PreparationSpeedTests.java')
            subprocess.run(['javac', '-d', output, *map(str, sources)], check=True,
                           capture_output=True, text=True, timeout=30)
            result = subprocess.run(['java', '-Xmx32m', '-cp', output,
                'io.github.russianranger.esteria.core.runtime.install.PreparationSpeedTests'],
                check=True, capture_output=True, text=True, timeout=30)
            self.assertIn('PASS: preparation speed', result.stdout)


if __name__ == '__main__':
    unittest.main()
