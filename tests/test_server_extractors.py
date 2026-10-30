"""Exact extractor selection and bounded CLI tests; no game data or ELF execution."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_server_extractors as extractors
from tests import test_server_engine_package as engine_tests


class ExtractorFixture(unittest.TestCase):
    write_metadata = engine_tests.InputSelection.write_metadata
    validate = engine_tests.InputSelection.validate

    def setUp(self):
        engine_tests.InputSelection.setUp(self)
        template = self.install / 'bin/authserver'
        for name in extractors.PROGRAMS:
            shutil.copyfile(template, self.install / 'bin' / name)
            (self.install / 'bin' / name).chmod(0o755)
        (self.install / 'bin/mmaps-config.yaml').write_text('mmapsConfig:\n  dataDir: "./"\n')
        self.build['files'] = [row for row in self.build['files'] if row['path'] not in
                               {'bin/' + name for name in extractors.PROGRAMS} | {'bin/mmaps-config.yaml'}]
        for name in (*extractors.PROGRAMS, 'mmaps-config.yaml'):
            row = dict(path='bin/' + name, **extractors.files.identity(self.install / 'bin' / name))
            if name in extractors.PROGRAMS: row['elf'] = dict(machine='AArch64')
            self.build['files'].append(row)
        self.write_metadata(); proof = engine_tests.InputSelection.validate(self)
        self.pin = dict(formatVersion=1, sourceLockSha256=proof['sourceLock']['sha256'],
            originalBuild=proof['buildIdentity'], originalModules=proof['moduleIdentity'],
            buildId=self.build['buildId'], integrationRevision=self.build['integrationRevision'],
            runtimeMount='/esteria-server-extractors', sourceFiles={},
            originalFiles={row['path']: extractors.engine.identity(row) for row in self.build['files']
                           if row['path'] in {'bin/' + name for name in extractors.PROGRAMS} | {'bin/mmaps-config.yaml'}})
        path = self.server / 'src/tools/mmaps_generator/mmaps-config.yaml'
        path.parent.mkdir(parents=True); shutil.copyfile(self.install / 'bin/mmaps-config.yaml', path)
        self.proof = proof
        self.pin_identity = dict(bytes=1, sha256='f'*64)

    def select_extractors(self):
        with patch.object(extractors.engine, 'validate_inputs', return_value=self.proof), \
             patch.object(extractors, 'load_pin', return_value=(self.pin, self.pin_identity)):
            return extractors.validate_inputs(self.install, self.modules, self.commands, self.lock, self.server)


class ExtractorInputs(ExtractorFixture):
    def test_exact_four_original_programs_and_configuration(self):
        _, pin, _ = self.select_extractors()
        self.assertEqual(len(pin['originalFiles']), 5)
        self.assertEqual(set(pin['originalFiles']), {'bin/' + name for name in extractors.PROGRAMS} | {'bin/mmaps-config.yaml'})

    def test_changed_program_configuration_and_cli_source_refused(self):
        for name in ('bin/map_extractor', 'bin/mmaps-config.yaml'):
            path = self.install / name; original = path.read_bytes(); path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'original-file-changed'): self.select_extractors()
            path.write_bytes(original)
        self.pin['sourceFiles'] = {'reviewed.cpp': dict(bytes=1, sha256='0'*64)}
        (self.server / 'reviewed.cpp').write_text('different')
        with self.assertRaisesRegex(ValueError, 'reviewed-cli-source-changed'): self.select_extractors()

    def test_different_build_or_modules_cannot_be_relabelled(self):
        for field in ('originalBuild', 'originalModules'):
            original = self.pin[field]; self.pin[field] = dict(bytes=1, sha256='0'*64)
            with self.assertRaisesRegex(ValueError, 'exact-original-build'): self.select_extractors()
            self.pin[field] = original

    def test_existing_output_is_preserved_before_selection(self):
        output = self.root / 'existing'; output.mkdir(); (output / 'marker').write_text('preserved')
        with patch.object(extractors, 'validate_inputs') as checked, \
             self.assertRaisesRegex(ValueError, 'output-exists'):
            extractors.build(output, self.install, self.modules, self.commands, self.lock, self.server,
                             self.server, self.root / 'unused', self.root / 'unused')
        checked.assert_not_called(); self.assertEqual((output / 'marker').read_text(), 'preserved')


class BoundedCases(unittest.TestCase):
    def test_expected_nonzero_status_and_tokens(self):
        with tempfile.TemporaryDirectory() as empty:
            result = extractors.bounded_case([sys.executable, '-c', 'print("fixture usage"); raise SystemExit(7)'],
                empty, dict(name='fixture', exitCode=7, contains=['fixture usage']))
        self.assertEqual(result['exitCode'], 7)

    def test_unexpected_status_output_and_output_flood_are_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            for code, status, tokens, error in [('print("usage")', 1, ['usage'], 'result-mismatch'),
                    ('raise SystemExit(1)', 1, ['usage'], 'result-mismatch'),
                    ('print("x"*70000)', 0, [], 'output-bound')]:
                with self.subTest(code=code), self.assertRaisesRegex(ValueError, error):
                    extractors.bounded_case([sys.executable, '-c', code], empty,
                        dict(name='fixture', exitCode=status, contains=tokens))

    def test_host_cannot_establish_native_arm64_qualification(self):
        with patch.object(extractors.platform, 'machine', return_value='x86_64'):
            with self.assertRaisesRegex(ValueError, 'native-arm64'):
                extractors.smoke(Path('/not-read'), Path('/not-read'))

    def test_real_pin_has_exact_source_derived_cli_contracts_and_false_conversion_flags(self):
        pin, _ = extractors.load_pin()
        self.assertEqual(len(pin['cliCases']), 5)
        self.assertEqual({case['program'] for case in pin['cliCases']}, set(extractors.PROGRAMS))
        self.assertTrue(all(case['exitCode'] != 0 for case in pin['cliCases']))
        self.assertFalse(pin['clientMpqConversionQualified']); self.assertFalse(pin['customEsteriaDataLoadOrderQualified'])


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact NDK fixture not supplied')
class RealExtractorPairs(ExtractorFixture):
    def test_real_aarch64_derivatives_and_debug_stay_separate_without_execution(self):
        toolchain = Path(os.environ['ESTERIA_NDK_TOOLCHAIN']).resolve(strict=True)
        source = self.root / 'fixture.c'; source.write_text('volatile int marker=3; void _start(void){for(;;)marker++;}\n')
        executable = self.root / 'original'
        subprocess.run([str(toolchain / 'clang'), '--target=aarch64-linux-gnu', '-fuse-ld=lld', '-nostdlib', '-g',
            '-Wl,--build-id=sha1', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(source), '-o', str(executable)],
            check=True, capture_output=True, timeout=30)
        for name in extractors.PROGRAMS:
            shutil.copyfile(executable, self.install / 'bin' / name)
            self.pin['originalFiles']['bin/' + name] = extractors.files.identity(executable)
        source_inputs = self.root / 'source-inputs'; source_inputs.mkdir()
        (source_inputs / extractors.notices.SOURCE_RECEIPT).write_bytes(b'fixture receipt\n')
        (source_inputs / extractors.notices.SOURCE_ARCHIVE).write_bytes(b'fixture source archive\n')
        source_proof = dict(receipt=extractors.files.identity(source_inputs / extractors.notices.SOURCE_RECEIPT),
                            archive=extractors.files.identity(source_inputs / extractors.notices.SOURCE_ARCHIVE))
        pin = self.root / 'fixture-pin.json'; pin.write_bytes(extractors.engine.canonical(self.pin))
        notice_bytes = {'notices/source/fixture-license-' + str(i) + '.txt': b'original fixture notice\n'
                        for i in range(66)}
        output = self.root / 'extractors'
        with patch.object(extractors, 'validate_inputs', return_value=(self.proof, self.pin, extractors.files.identity(pin))), \
             patch.object(extractors, 'LOCK', pin), \
             patch.object(extractors, 'source_notices', return_value=(source_proof, notice_bytes)), \
             patch.object(extractors.engine.elf, 'verify_tool',
                          return_value={'executable': extractors.files.identity(toolchain / 'llvm-objcopy')}):
            receipt = extractors.build(output, self.install, self.modules, self.commands, self.lock, self.server,
                source_inputs, self.root / 'unused', toolchain / 'llvm-objcopy')
        self.assertTrue(receipt['archiveReadbackVerified']); self.assertFalse(receipt['sourceCompanionComplete'])
        runtime, debug = (receipt['packages'][name] for name in ('runtime', 'debug'))
        self.assertEqual({name for name in runtime['inventory'] if name.startswith('bin/')},
                         {'bin/' + name for name in extractors.PROGRAMS})
        self.assertEqual({name for name in debug['inventory'] if name.startswith('symbols/')},
                         {'symbols/' + name + '.debug' for name in extractors.PROGRAMS})
        self.assertIn(extractors.CONFIG, runtime['inventory'])
        with tarfile.open(output / runtime['archiveFile']) as archive:
            self.assertEqual(archive.extractfile('notices/source/fixture-license-0.txt').read(), notice_bytes['notices/source/fixture-license-0.txt'])
        for group in (runtime, debug): extractors.engine.verify_archive(output / group['archiveFile'], group['inventory'])
        with patch.object(extractors, 'load_pin', return_value=(self.pin, extractors.files.identity(pin))):
            extractors.load_runtime(output / 'package-receipt.json')
            for name in ('server-build.json', 'server-modules.json', 'sources.lock.json', 'extractors-packaging.lock.json'):
                altered = copy.deepcopy(receipt)
                altered['packages']['runtime']['inventory']['provenance/' + name]['sha256'] = '0'*64
                path = output / ('changed-' + name)
                path.write_bytes(extractors.engine.canonical(altered))
                with self.subTest(provenance=name), self.assertRaisesRegex(ValueError, 'original-provenance-binding'):
                    extractors.load_runtime(path)
            installed = self.root / 'extracted'
            proof = extractors.extract(output / 'package-receipt.json', installed)
            self.assertEqual(proof['extractedFiles'], len(runtime['inventory']))
            for name, row in runtime['inventory'].items():
                self.assertEqual(extractors.files.identity(installed / name), extractors.engine.identity(row))


if __name__ == '__main__': unittest.main()
