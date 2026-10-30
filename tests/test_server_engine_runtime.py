"""Real derivative archive readback with synthetic provenance, never server execution."""
import copy
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

from tools import qualify_authserver as auth, qualify_dbimport as importer
from tools import package_server_engine as package, verify_server_engine_runtime as runtime
from tests import test_server_engine_package as fixtures


class ExplicitSelection(unittest.TestCase):
    def test_default_original_selection_and_explicit_derivative_are_separate(self):
        build = {'files':[dict(path='bin/'+name, bytes=1, sha256='a'*64) for name in package.PROGRAMS]}
        with patch.object(importer, 'verify_install', return_value=(build, Path('/template'))) as original:
            selected = importer.select_install(Path('/install'), {}, Path('/lock'))
        self.assertIs(selected[0], build); self.assertIsNone(selected[3]); original.assert_called_once()
        proof = (build, Path('/template'), {'authserver':{'bytes':2,'sha256':'b'*64}}, {'fixture':True})
        with patch.object(runtime, 'verify_install', return_value=proof) as derivative, \
             patch.object(importer, 'verify_install') as original:
            self.assertEqual(importer.select_install(Path('/install'), {}, Path('/lock'), Path('/receipt')), proof)
        derivative.assert_called_once_with(Path('/install'), {}, Path('/lock'), Path('/receipt'))
        original.assert_not_called()

    def test_auth_forwards_explicit_derivative_to_sole_fresh_state_creator(self):
        with patch.object(auth.importer, 'run', side_effect=ValueError('fixture-stop-before-SQL')) as run:
            with self.assertRaisesRegex(ValueError, 'fixture-stop-before-SQL'):
                auth.run(Path('/install'), Path('/content'), 'a'*64, Path('/lock'), Path('/mysql'),
                    Path('/mysqld'), '8.0.46', Path('/new'), engine_derivative_receipt=Path('/receipt'))
        self.assertEqual(run.call_args.kwargs, {'engine_derivative_receipt':Path('/receipt')})


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact NDK toolchain fixture not supplied')
class DerivativeRuntime(unittest.TestCase):
    write_metadata = fixtures.InputSelection.write_metadata
    validate = fixtures.InputSelection.validate

    def setUp(self):
        fixtures.InputSelection.setUp(self)
        toolchain = Path(os.environ['ESTERIA_NDK_TOOLCHAIN']).resolve(strict=True)
        source = self.root/'fixture.c'
        source.write_text('volatile int marker=17; void _start(void) { for(;;) marker++; }\n')
        executable = self.root/'original'
        subprocess.run([str(toolchain/'clang'), '--target=aarch64-linux-gnu', '-fuse-ld=lld',
            '-nostdlib', '-g', '-Wl,--build-id=sha1', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
            str(source), '-o', str(executable)], check=True, capture_output=True, timeout=30)
        for name in package.PROGRAMS:
            target = self.install/'bin'/name; target.chmod(0o755); shutil.copyfile(executable, target)
        for row in self.build['files']: row.update(package.files.identity(self.install/row['path']))
        self.compiled['binaries'] = {name: package.files.identity(self.install/'bin'/name)
                                    for name in ('worldserver','dbimport')}
        self.write_metadata(); proof = self.validate()
        self.output = self.root/'package'
        objcopy = toolchain/'llvm-objcopy'
        with patch.object(package, 'validate_inputs', return_value=proof), \
             patch.object(package.elf, 'verify_tool', return_value={'executable':package.files.identity(objcopy)}):
            package.build(self.output, self.install, self.modules, self.commands, self.lock,
                self.server, self.root/'verified-upstream-archive-fixture', objcopy)
        self.receipt = self.output/'package-receipt.json'
        self.runtime = self.root/'expanded'
        runtime.extract(self.receipt, self.runtime)

    def test_exact_runtime_preserves_original_manifests_and_selects_new_programs(self):
        before = (self.install/'server-build.json').read_bytes()
        build, template, programs, proof = runtime.verify_install(self.runtime, self.compiled, self.lock, self.receipt)
        self.assertEqual(build, self.build); self.assertEqual(template, self.runtime/'etc/dbimport.conf.dist')
        self.assertEqual((self.runtime/'provenance/server-build.json').read_bytes(), before)
        self.assertEqual(set(programs), set(package.PROGRAMS))
        self.assertNotEqual(programs['authserver'], package.files.identity(self.install/'bin/authserver'))
        self.assertFalse(proof['sourceCompanionComplete']); self.assertFalse(proof['debugArchiveReadBackHere'])

    def test_runtime_file_mutation_and_other_compiled_module_receipt_refused(self):
        wrong = copy.deepcopy(self.compiled); wrong['enabledModules'] = ['other']
        with self.assertRaisesRegex(ValueError, 'original-provenance-mismatch'):
            runtime.verify_install(self.runtime, wrong, self.lock, self.receipt)
        target = self.runtime/'bin/authserver'; target.chmod(0o755); target.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'runtime-file-changed'):
            runtime.verify_install(self.runtime, self.compiled, self.lock, self.receipt)

    def test_changed_archive_and_existing_destination_preserve_prior_files(self):
        with self.assertRaisesRegex(ValueError, 'existing-engine-runtime-preserved'):
            runtime.extract(self.receipt, self.runtime)
        archive = self.output/'server-engine-runtime-arm64.tar.gz'; archive.chmod(0o644)
        archive.write_bytes(archive.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError, 'archive-changed'): runtime.extract(self.receipt, self.root/'refused')
        self.assertFalse((self.root/'refused').exists())

    def test_wrong_native_host_refuses_before_executing_any_elf(self):
        with patch.object(runtime.platform, 'machine', return_value='x86_64'), \
             patch.object(runtime.files, 'bounded_command') as execute, \
             self.assertRaisesRegex(ValueError, 'native-arm64-engine-smoke-required'):
            runtime.smoke(self.runtime, self.lock, self.receipt)
        execute.assert_not_called()


if __name__ == '__main__': unittest.main()
