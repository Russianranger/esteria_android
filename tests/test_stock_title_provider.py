import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_client_runtime, qualify_stock_client_title as title


class StockTitleProvider(unittest.TestCase):
    def test_stage_preserves_selected_localized_agreement_body_and_owns_realm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client, view = root/'import', root/'view'
            locale = client/'Data'/'frFR'
            locale.mkdir(parents=True)
            for name in ('eula.html', 'tos.html', 'locale-frFR.MPQ', 'realmlist.wtf'):
                (locale/name).write_bytes(b'original')
            title.stage_client_data(client, view, 'frFR')
            for name in ('eula.html', 'tos.html', 'locale-frFR.MPQ'):
                self.assertEqual((view/'Data/frFR'/name).readlink(), Path('/esteria-data/Data/frFR')/name)
            self.assertEqual((view/'Data/frFR/realmlist.wtf').read_text(), 'set realmlist 127.0.0.1\n')
            self.assertEqual((locale/'realmlist.wtf').read_bytes(), b'original')
            self.assertFalse((view/'Data/frFR/termination.html').exists())

    def test_measured_candidate_is_bound_to_zip_and_final_pe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            view = root/'view'
            view.mkdir()
            original = root/'original.zip'
            with zipfile.ZipFile(original, 'w') as archive:
                for name in provider_client_runtime.SELECTED:
                    archive.writestr(name, name.encode())
            image = b'bin/Win/ARM64/WowClient64.exe'
            build = {'artifact': {'bytes': original.stat().st_size,
                                  'sha256': hashlib.sha256(original.read_bytes()).hexdigest()}}
            pair = {'executableRevision': 'a'*40, 'executableSha256': hashlib.sha256(image).hexdigest()}
            digest = title.stage_renderer(view, root, pair, build, original)
            self.assertEqual(digest, build['artifact']['sha256'])
            self.assertEqual((view/'WowClient64.exe').read_bytes(), image)
            with self.assertRaisesRegex(ValueError, 'candidate-executable'):
                title.stage_renderer(view, root, dict(pair, executableSha256='0'*64), build, original)
            original.write_bytes(b'x'*build['artifact']['bytes'])
            with self.assertRaisesRegex(ValueError, 'package-hash-mismatch'):
                title.stage_renderer(view, root, pair, build, original)

    def test_prepared_recipe_cannot_select_an_unpaired_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client = root/'runtime/client'
            shader = root/'runtime/shaders'
            client.mkdir(parents=True)
            shader.mkdir(parents=True)
            source = client/'stock-renderer-sources.lock.json'
            source.write_text(json.dumps({'sources': {'client': {'commit': 'b'*40}}}))
            donor = root/'sources.lock.json'
            donor.write_text('{}')
            (shader/'android-provider.lock.json').write_text(json.dumps({'clientRevision': 'a'*40,
                                                                        'toolManifestSha256': '1'*64}))
            pair = {'formatVersion': 1, 'scope': 'stock-renderer-and-archive-read', 'preparedClientRevision': 'a'*40,
                    'executableRevision': 'b'*40, 'preparedSourceLockSha256': hashlib.sha256(donor.read_bytes()).hexdigest(),
                    'executableSourceLockSha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                    'requiredWineArchiveSha256': '2'*64, 'shaderToolManifestSha256': '1'*64}
            (client/'renderer-compatibility.json').write_text(json.dumps(pair))
            (client/'stock-renderer-build.lock.json').write_text(json.dumps({'sourceRevision': 'b'*40}))
            with patch.object(title, 'ROOT', root):
                self.assertEqual(title.renderer_pair('a'*40, '2'*64)[0], pair)
                for revision, wine in [('b'*40, '2'*64), ('a'*40, '3'*64)]:
                    with self.assertRaisesRegex(ValueError, 'renderer-preparation-pair'):
                        title.renderer_pair(revision, wine)
                source.write_text(json.dumps({'sources': {'client': {'commit': 'c'*40}}}))
                with self.assertRaisesRegex(ValueError, 'renderer-preparation-pair'):
                    title.renderer_pair('a'*40, '2'*64)


if __name__ == '__main__':
    unittest.main()
