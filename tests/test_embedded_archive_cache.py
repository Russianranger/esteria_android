from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


class EmbeddedCacheHost(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'Java17 required')
    def test_owned_asset_copy_resume_and_bounded_heap(self):
        with tempfile.TemporaryDirectory() as directory:
            base='io/github/russianranger/esteria/core/runtime/install/'
            sources=[ROOT/'core/src/main/java'/base/(name+'.java') for name in ('RuntimeFiles','RuntimeWork','RuntimeReadPolicy','PreparationSpeed','EmbeddedArchiveCache')]
            sources.append(ROOT/'core/src/main/java/io/github/russianranger/esteria/core/runtime/ExclusiveFileLease.java')
            sources.append(ROOT/'core/src/test/java'/base/'EmbeddedArchiveCacheTests.java')
            subprocess.run(['javac','-d',directory,*map(str,sources)],check=True,capture_output=True,text=True)
            result=subprocess.run(['java','-Xmx32m','-cp',directory,'io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCacheTests',directory+'/state'],check=True,capture_output=True,text=True,timeout=60)
            self.assertIn('PASS: embedded cache',result.stdout)


if __name__=='__main__':unittest.main()
