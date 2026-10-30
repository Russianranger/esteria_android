import copy
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import wine_arm64_requalification as reuse
from tools import package_wine_arm64_candidate as package
import tests.test_wine_arm64_candidate as package_fixture


class RetainedWineInputs(unittest.TestCase):
    def test_selected_client_and_original_host_cohort_remain_distinct(self):
        runtime, selected = reuse.pins()
        self.assertEqual(runtime['originalNativeClientRevision'], '0f931bbade36a4b197725d691b8eff7caea7b3be')
        self.assertEqual(selected['sourceRevision'], '471ee42faadf4a97a1d0a86989cf1452621f2dc5')
        self.assertNotEqual(runtime['originalNativeClientRevision'], selected['sourceRevision'])
        self.assertFalse(runtime['androidQualified']); self.assertFalse(runtime['gameplayQualified'])

    def test_incomplete_source_build_or_relabelled_input_is_refused(self):
        original, selected = reuse.pins()
        for change in ({'sourceBuildPassed': False}, {'originalNativeClientComponentGatesPassed': False},
                       {'sourcesPrefix': '../outside/'}, {'androidQualified': True}):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'runtime.json'; value = copy.deepcopy(original); value.update(change)
                path.write_text(json.dumps(value))
                with patch.object(reuse, 'RUNTIME_PIN', path), self.assertRaises(ValueError): reuse.pins()

    def test_existing_input_directory_fails_before_any_network_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'save').write_text('keep')
            with patch.object(reuse, 'Github') as api, self.assertRaises(ValueError): reuse.fetch(root)
            api.assert_not_called(); self.assertEqual((root / 'save').read_text(), 'keep')

    def source_archive(self, root, rows):
        path = root / 'sources.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name, data, mode in rows:
                item = zipfile.ZipInfo(name); item.compress_type = zipfile.ZIP_DEFLATED
                item.external_attr = mode << 16; z.writestr(item, data)
        return path, {'sourcesArtifact': {'bytes': path.stat().st_size}, 'sourcesPrefix': 'wine-arm64-sources/'}

    def test_original_export_scope_preserves_regular_and_empty_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); archive, pin = self.source_archive(root, [
                ('wine-arm64-sources/source.c', b'original bytes', stat.S_IFREG | 0o600),
                ('wine-arm64-sources/empty', b'', stat.S_IFREG | 0o600),
                ('wine-arm64-bridge/notices/LICENSE', b'original license', stat.S_IFREG | 0o600)])
            selected = reuse.extract_sources(archive, root / 'out', pin)
            self.assertEqual((selected / 'source.c').read_bytes(), b'original bytes')
            self.assertEqual((selected / 'empty').read_bytes(), b'')
            self.assertEqual((root / 'out/wine-arm64-bridge/notices/LICENSE').read_bytes(), b'original license')

    def test_source_links_escape_unexpected_scope_and_expansion_are_refused(self):
        cases = [('wine-arm64-sources/link', b'/etc/passwd', stat.S_IFLNK | 0o777),
                 ('wine-arm64-sources/../../escape', b'no', stat.S_IFREG | 0o600),
                 ('private/key', b'no', stat.S_IFREG | 0o600),
                 ('wine-arm64-sources/fifo', b'', stat.S_IFIFO | 0o600),
                 ('wine-arm64-sources/large', b'\0' * 65536, stat.S_IFREG | 0o600)]
        for row in cases:
            with self.subTest(path=row[0]), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); archive, pin = self.source_archive(root, [row])
                with self.assertRaises(ValueError): reuse.extract_sources(archive, root / 'out', pin)
                self.assertFalse((root / 'escape').exists())

    def package(self):
        fixture = package_fixture.Arm64Candidate('test_existing_outputs_are_never_overwritten')
        fixture.setUp(); self.addCleanup(fixture.doCleanups); fixture.prepare()
        package.build(fixture.export, fixture.measured, fixture.output)
        pin = {'files': {p.name: reuse.client.identity(p) for p in fixture.output.iterdir()}}
        return fixture, pin

    def test_retained_measured_package_keeps_its_original_source_and_archive_binding(self):
        fixture, pin = self.package()
        proof, selected = reuse.runtime_package(fixture.output, pin)
        self.assertEqual(proof['archive'], selected['packages']['wine-arm64']['archive'])
        self.assertTrue(proof['archiveReadBack']); self.assertFalse(proof['arm64Qualified'])
        path = fixture.output / 'wine-arm64.tar.gz'; changed = bytearray(path.read_bytes()); changed[-1] ^= 1
        path.write_bytes(changed)
        with self.assertRaises(ValueError): reuse.runtime_package(fixture.output, pin)

    def test_truthfully_rehashed_overclaim_cannot_adopt_a_build_as_execution(self):
        fixture, pin = self.package()
        path = fixture.output / 'package-build-receipt.json'; value = json.loads(path.read_bytes())
        value['gameplayQualified'] = True; path.write_text(json.dumps(value))
        pin['files'][path.name] = reuse.client.identity(path)
        with self.assertRaisesRegex(ValueError, 'overclaim'): reuse.runtime_package(fixture.output, pin)


if __name__ == '__main__': unittest.main()
