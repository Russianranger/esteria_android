import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'runtime/wine-probe/apply_adaptations.py'
SPEC = importlib.util.spec_from_file_location('wine_apply_adaptations', SOURCE)
ADAPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ADAPT)


def pin(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class WineAdaptations(unittest.TestCase):
    def fixture(self, root):
        directory = root / 'inputs'; directory.mkdir()
        source = root / 'upstream'; source.mkdir()
        (source / 'source.c').write_text('original\n')
        patch = b'--- a/source.c\n+++ b/source.c\n@@ -1 +1 @@\n-original\n+adapted\n'
        test = b'owned test source\n'
        (directory / 'change.patch').write_bytes(patch)
        (directory / 'test.c').write_bytes(test)
        lock = dict(wine=dict(androidPrivatePeCopy=dict(environment={'WINE_ANDROID_PRIVATE_PE_COPY': '1'},
                    patches=[dict(file='change.patch', **pin(patch))], testSources={'test.c': pin(test)})))
        return directory, source, lock

    def test_exact_patch_and_original_test_sources_are_retained_without_reapplication(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory, source, lock = self.fixture(root)
            output = root / 'retained'
            result = ADAPT.apply(lock, directory, source, output)
            self.assertEqual((source / 'source.c').read_text(), 'adapted\n')
            self.assertEqual({path.name for path in output.iterdir()}, {'change.patch', 'test.c'})
            self.assertFalse(result['androidRuntimeQualified'])
            for name in result['files']:
                self.assertEqual((directory / name).read_bytes(), (output / name).read_bytes())
            with self.assertRaisesRegex(ValueError, 'output-exists'):
                ADAPT.apply(lock, directory, source, output)

    def test_changed_or_linked_input_fails_before_source_mutation(self):
        for linked in (False, True):
            with self.subTest(linked=linked), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary); directory, source, lock = self.fixture(root)
                path = directory / 'test.c'
                if linked:
                    path.unlink(); path.symlink_to(source / 'source.c')
                else:
                    path.write_bytes(b'X' * path.stat().st_size)
                with self.assertRaisesRegex(ValueError, 'adaptation-source'):
                    ADAPT.apply(lock, directory, source, root / 'retained')
                self.assertEqual((source / 'source.c').read_text(), 'original\n')


if __name__ == '__main__':
    unittest.main()
