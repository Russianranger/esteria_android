"""Host execution of the actual Android adapter's persistence/review flow with narrow Android stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ClientLaunchSetupTests(unittest.TestCase):
    def test_real_adapter_persistence_review_and_stale_decisions(self):
        java_home = Path(os.environ.get('JAVA_HOME', '/nonexistent')) / 'bin'
        javac = shutil.which('javac') or (str(java_home / 'javac') if (java_home / 'javac').is_file() else None)
        java = shutil.which('java') or (str(java_home / 'java') if (java_home / 'java').is_file() else None)
        if not javac or not java:
            self.skipTest('Java 17+ host toolchain unavailable')
        with tempfile.TemporaryDirectory(prefix='esteria-app-ui-host-') as scratch:
            at = Path(scratch)
            context = at / 'android/content/Context.java'
            context.parent.mkdir(parents=True)
            context.write_text('package android.content; public abstract class Context { public abstract java.io.File getFilesDir(); }\n')
            runtime = at / 'io/github/russianranger/esteria/runtime/ClientRuntimeSetup.java'
            runtime.parent.mkdir(parents=True)
            runtime.write_text('package io.github.russianranger.esteria.runtime; public abstract class ClientRuntimeSetup { '
                               'public abstract java.nio.file.Path current() throws java.io.IOException; '
                               'public abstract io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan packagePlan(); }\n')
            sources = sorted((ROOT / 'core/src/main/java').rglob('*.java')) + [context, runtime,
                ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime/ClientLaunchSetup.java',
                ROOT / 'tests/java/io/github/russianranger/esteria/runtime/ClientLaunchSetupTest.java']
            classes = at / 'classes'
            subprocess.run([javac, '--release', '17', '-d', str(classes), *map(str, sources)], check=True, timeout=60)
            result = subprocess.run([java, '-Xmx32m', '-cp', str(classes),
                                     'io.github.russianranger.esteria.runtime.ClientLaunchSetupTest'],
                                    check=True, capture_output=True, text=True, timeout=60)
            self.assertIn('PASS: actual app adapter', result.stdout)


if __name__ == '__main__':
    unittest.main()
