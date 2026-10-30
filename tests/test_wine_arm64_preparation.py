import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_wine_arm64_candidate as candidate


class CandidatePreparation(unittest.TestCase):
    def fixture(self, root):
        source = root / 'repo/runtime/bridges'; source.mkdir(parents=True)
        lock = dict(runtimeArchiveSha256='f' * 64, packages=[dict(package='unchanged-build-input')])
        raw = (json.dumps(lock) + '\n').encode(); (source / 'sources.lock.json').write_bytes(raw)
        (source / 'Dockerfile').write_text('source-owned builder\n')
        selected = root / 'candidate-sources.json'
        selected.write_text(json.dumps(dict(oldProviderArchiveSha256='f' * 64,
            qualificationReference=dict(bridgeInputLock=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())))))
        package = root / 'runtime'; package.mkdir()
        (package / 'candidate-runtime.lock.json').write_text(json.dumps(dict(scope='separate-native-arm64-wine-candidate',
            packages={'wine-arm64': dict(archive=dict(sha256='a' * 64))})))
        return source, selected, package, raw

    def test_candidate_bridge_is_separate_and_preserves_all_other_build_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source, lock, package, original = self.fixture(root)
            with patch.object(candidate, 'ROOT', root / 'repo'), patch.object(candidate, 'LOCK', lock):
                result = candidate.bridge_context(package, root / 'context')
            changed = json.loads((root / 'context/sources.lock.json').read_bytes())
            expected = json.loads(original); expected['runtimeArchiveSha256'] = 'a' * 64
            self.assertEqual(changed, expected)
            self.assertEqual((source / 'sources.lock.json').read_bytes(), original)
            self.assertEqual((root / 'context/Dockerfile').read_bytes(), (source / 'Dockerfile').read_bytes())
            self.assertFalse(result['productionFilesChanged'])
            self.assertEqual(result['runtimeArchiveSha256'], 'a' * 64)

    def test_stale_source_scope_or_existing_context_cannot_be_adopted(self):
        for mode in ('stale', 'scope', 'existing'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); source, lock, package, original = self.fixture(root)
                output = root / 'context'
                if mode == 'stale': (source / 'sources.lock.json').write_text('{}')
                if mode == 'scope': (package / 'candidate-runtime.lock.json').write_text('{"scope":"production"}')
                if mode == 'existing': output.mkdir(); (output / 'save').write_text('keep')
                with patch.object(candidate, 'ROOT', root / 'repo'), patch.object(candidate, 'LOCK', lock):
                    with self.assertRaises((ValueError, KeyError)):
                        candidate.bridge_context(package, output)
                if mode == 'existing': self.assertEqual((output / 'save').read_text(), 'keep')

    def test_changed_client_artifact_fails_before_extracting_any_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); artifact = root / 'client.zip'; artifact.write_bytes(b'not the measured original')
            with self.assertRaises(ValueError): candidate.fixtures(artifact, root / 'fixture')
            self.assertFalse((root / 'fixture').exists())


if __name__ == '__main__':
    unittest.main()
