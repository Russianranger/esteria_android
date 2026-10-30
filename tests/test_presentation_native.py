"""Production C decoder against host-only window stubs; never an Android pass."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PresentationNative(unittest.TestCase):
    def test_actual_surface_decoder_colour_stride_resize_and_failures(self):
        compiler = shutil.which('cc')
        java = Path(os.environ['JAVA_HOME']) if os.environ.get('JAVA_HOME') else None
        if java is None:
            javac = shutil.which('javac')
            if javac:
                java = Path(javac).resolve().parents[1]
        if not compiler or java is None or not (java / 'include/jni.h').is_file():
            self.skipTest('requires host C compiler and JDK JNI headers')
        with tempfile.TemporaryDirectory(prefix='esteria-surface-') as directory:
            binary = Path(directory) / 'surface-probe'
            subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                            '-I' + str(ROOT / 'tests/bridge-stubs'), '-I' + str(java / 'include'),
                            '-I' + str(java / 'include/linux'), str(ROOT / 'tests/presentation_surface_probe.c'),
                            '-o', str(binary)], check=True, timeout=60, capture_output=True)
            result = subprocess.run([str(binary)], check=True, timeout=15, capture_output=True, text=True)
            self.assertIn('SURFACE_PROTOCOL_COPY_OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
