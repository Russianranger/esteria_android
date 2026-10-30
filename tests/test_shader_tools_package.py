"""Packaging/identity tests; synthetic compiler bytes are never executed."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_shader_tools as package


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class ShaderToolsPackage(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.client = self.root / 'client'; self.integration = self.root / 'integration'
        self.payload = self.root / 'payload'; self.output = self.root / 'output'
        for source in (self.client, self.integration):
            source.mkdir(); self.git(source, 'init', '-q')
            self.git(source, 'config', 'user.name', 'Synthetic fixture')
            self.git(source, 'config', 'user.email', 'fixture@example.invalid')
        for name in (*package.PYTHON, 'README.md'):
            self.write(self.client / 'Tools/VulkanShaders' / name, ('# committed fixture ' + name + '\n').encode())
        self.git(self.client, 'add', '.'); self.git(self.client, 'commit', '-qm', 'synthetic translators')
        self.client_revision = self.git(self.client, 'rev-parse', 'HEAD').strip()
        upstream = {}
        for name, (license_name, notice_name) in package.SOURCES.items():
            raw = ('Original synthetic license for ' + name + '\n').encode()
            path = self.payload / 'corresponding-source/original-archives' / (name + '.tar.gz')
            path.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path, 'w:gz') as tar:
                member = tarfile.TarInfo(name + '-fixture/' + license_name); member.size = len(raw)
                tar.addfile(member, io.BytesIO(raw))
            upstream[name] = dict(file=path.name, prefix=name + '-fixture', revision='a'*40,
                                  url='https://example.invalid/synthetic-source', **package.identity(path))
            self.write(self.payload / 'notices' / notice_name, raw)
        lock = dict(upstream=upstream, runtimeArchiveSha256='f'*64, packages=[{'package':'libc6'}])
        lock_raw = package.encoded(lock)
        self.write(self.integration / 'runtime/turnip/sources.lock.json', lock_raw)
        self.write(self.integration / 'runtime/turnip/build.sh', b'#!/bin/sh\n# synthetic build recipe\n')
        self.write(self.integration / 'LICENSE', b'Synthetic fixture notice, not a real license\n')
        self.git(self.integration, 'add', '.'); self.git(self.integration, 'commit', '-qm', 'synthetic build')
        self.integration_revision = self.git(self.integration, 'rev-parse', 'HEAD').strip()
        recipe = {}
        for source in (self.integration / 'runtime/turnip').iterdir():
            raw = source.read_bytes(); recipe[source.name] = identity(raw)
            self.write(self.payload / 'corresponding-source/build-recipe' / source.name, raw)
        self.write(self.payload / 'notices/libc6-copyright', b'Synthetic package copyright\n')
        self.compiler_raw = b'Synthetic, deliberately nonexecutable compiler fixture\n'
        self.write(self.payload / 'bin/glslangValidator', self.compiler_raw)
        self.measured = dict(**identity(self.compiler_raw), architecture='arm64', needed=['libc.so.6'],
            interpreter=['/lib/ld-linux-aarch64.so.1'], maxGlibc='2.36', maxGlibcxx=None)
        self.qualification = dict(formatVersion=1, scope='native-linux-arm64-shader-tools-only', qualified=True,
            validGlslCompiled=True, spirvValidated=True, spirvDisassembled=True, invalidGlslRejected=True,
            invalidSpirvRejected=True, androidQualified=False, gameAssetShadersQualified=False,
            gameplayQualified=False, validSpirvSha256='b'*64)
        evidence = package.encoded(self.qualification)
        self.write(self.payload / 'shader-tool-check/qualification.json', evidence)
        self.receipt = dict(formatVersion=1, scope='linux-arm64-turnip-kgsl-build-only',
            integrationRevision=self.integration_revision, compiled=True, hardwareQualified=False,
            androidQualified=False, x11PresentationQualified=False, gameplayQualified=False,
            inputLockSha256=hashlib.sha256(lock_raw).hexdigest(), runtimeArchiveSha256='f'*64, upstream=upstream,
            binaries={'bin/glslangValidator':self.measured}, shaderToolEvidence=dict(**identity(evidence), result=self.qualification),
            recipeSources=recipe, notices={'notices/' + p.name:identity(p.read_bytes()) for p in (self.payload / 'notices').iterdir()},
            noticeInventoryScope='source-build-notices-before-integration-license')
        self.update_receipt()

    def write(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def git(self, source, *args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True, stderr=subprocess.DEVNULL)

    def update_receipt(self):
        raw = package.encoded(self.receipt); self.write(self.payload / 'turnip-build.json', raw)
        self.build_sha = hashlib.sha256(raw).hexdigest()

    def build(self):
        # The package/identity tests deliberately inject only the ELF measurement.
        # Production always invokes readelf on real ARM64 bytes; test below covers rejection.
        with patch.object(package, 'measure_elf', return_value=self.measured):
            return package.build(self.output, self.client, self.client_revision, self.payload,
                                 self.build_sha, self.integration, self.integration_revision)

    def test_git_blobs_readback_exact_closure_and_fresh_publication(self):
        report = self.build()
        actual = {str(p.relative_to(self.output / 'tools')) for p in (self.output / 'tools').rglob('*') if p.is_file()}
        self.assertEqual(actual, set(package.PYTHON) | {'bin/glslangValidator', 'shader-tools.json'})
        manifest = json.loads((self.output / 'tools/shader-tools.json').read_text())
        self.assertEqual(manifest['clientRevision'], self.client_revision)
        for name, pin in manifest['files'].items(): self.assertEqual(package.identity(self.output / 'tools' / name), pin)
        self.assertFalse(report['androidQualified']); self.assertFalse(report['gameAssetShadersQualified'])
        self.assertFalse(report['completeGuestRootfsSourceClosure'])
        self.assertEqual(len(list((self.output / 'corresponding-source').glob('*.tar.gz'))), 3)
        from runtime.shader_generation import tool_identity
        self.assertEqual(tool_identity(self.output / 'tools', self.client_revision), report['toolManifestSha256'])
        with self.assertRaisesRegex(ValueError, 'fresh-canonical'): self.build()

    def test_changed_checkout_and_changed_revision_rejected(self):
        source = self.client / 'Tools/VulkanShaders/bls/archive.py'; source.write_text('# uncommitted changed bytes\n')
        with self.assertRaisesRegex(ValueError, 'checkout-content'): self.build()
        self.assertFalse(self.output.exists())
        self.client_revision = 'a'*40
        with self.assertRaisesRegex(ValueError, 'checkout-revision'): self.build()

    def test_compiler_license_and_original_source_mutations_rejected(self):
        for name in ('bin/glslangValidator', 'notices/GLSLANG-LICENSE.txt',
                     'notices/libc6-copyright', 'corresponding-source/original-archives/glslang.tar.gz'):
            with self.subTest(name=name):
                path = self.payload / name; original = path.read_bytes(); path.write_bytes(original + b'changed')
                with self.assertRaises(ValueError): self.build()
                self.assertFalse(self.output.exists()); path.write_bytes(original)

    def test_symlink_ancestor_and_receipt_pin_rejected(self):
        parent = self.payload / 'notices'; moved = self.root / 'moved'; parent.rename(moved); parent.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'symlink'): self.build()
        parent.unlink(); moved.rename(parent)
        self.build_sha = '0'*64
        with self.assertRaisesRegex(ValueError, 'receipt-pin'): self.build()

    def test_false_or_overclaimed_qualification_rejected(self):
        for key in self.qualification:
            if type(self.qualification[key]) is bool:
                altered = copy.deepcopy(self.qualification); altered[key] = not altered[key]
                with self.subTest(key=key), self.assertRaises(ValueError): package.qualification(altered)
        altered = dict(self.qualification, formatVersion=True)
        with self.assertRaises(ValueError): package.qualification(altered)

    def test_real_elf_parser_rejects_synthetic_compiler(self):
        with self.assertRaisesRegex(ValueError, 'not-arm64-elf'):
            package.measure_elf(self.payload / 'bin/glslangValidator')

    def test_explicit_runtime_binding_retains_actual_build_input_and_committed_reference(self):
        original = (self.integration/'runtime/turnip/sources.lock.json').read_bytes()
        value = json.loads(original); value['runtimeArchiveSha256'] = 'c'*64
        chosen = self.root/'selected.json'; chosen.write_bytes(package.encoded(value))
        retained = self.payload/'corresponding-source/build-recipe/sources.lock.json'
        retained.write_bytes(chosen.read_bytes())
        self.receipt.update(inputLockSha256=identity(chosen.read_bytes())['sha256'], runtimeArchiveSha256='c'*64)
        self.receipt['recipeSources']['sources.lock.json'] = identity(chosen.read_bytes()); self.update_receipt()
        with patch.object(package,'measure_elf',return_value=self.measured):
            report = package.build(self.output,self.client,self.client_revision,self.payload,self.build_sha,
                                   self.integration,self.integration_revision,chosen)
        self.assertEqual((self.output/'provenance/build-recipe/sources.lock.json').read_bytes(),chosen.read_bytes())
        self.assertEqual((self.output/'provenance/build-recipe-reference/sources.lock.json').read_bytes(),original)
        self.assertEqual(report['wineRuntimeArchiveSha256'],'c'*64)
        self.assertTrue(report['selectedBuildInput']['onlyRuntimeArchiveBindingChanged'])
        self.assertEqual(report['selectedBuildInput']['selectedSource'],identity(chosen.read_bytes()))
        self.assertFalse(report['androidQualified'] or report['gameAssetShadersQualified'])

    def test_explicit_build_selection_cannot_change_other_sources_or_ignore_actual_retained_bytes(self):
        value = json.loads((self.integration/'runtime/turnip/sources.lock.json').read_bytes())
        chosen = self.root/'selected.json'; value['runtimeArchiveSha256']='c'*64
        changed = copy.deepcopy(value); changed['packages'] = []
        chosen.write_bytes(package.encoded(changed))
        with self.assertRaisesRegex(ValueError,'changes-other-inputs'):
            package.build_input(self.integration,self.integration_revision,chosen)
        chosen.write_bytes(package.encoded(value))
        self.receipt.update(inputLockSha256=identity(chosen.read_bytes())['sha256'],runtimeArchiveSha256='c'*64)
        self.receipt['recipeSources']['sources.lock.json'] = identity(chosen.read_bytes()); self.update_receipt()
        with patch.object(package,'measure_elf',return_value=self.measured),self.assertRaisesRegex(ValueError,'recipe-source-mismatch'):
            package.build(self.output,self.client,self.client_revision,self.payload,self.build_sha,
                          self.integration,self.integration_revision,chosen)


if __name__ == '__main__': unittest.main()
