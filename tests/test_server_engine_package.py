"""Engine selection/transaction tests; synthetic installs establish no server gate."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_server_engine as engine


class InputSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.install = self.root / 'install'; self.install.mkdir()
        self.server = self.root / 'server'; self.server.mkdir()
        self.lock = engine.ROOT / 'sources.lock.json'
        self.modules = self.root / 'server-modules.json'
        self.commands = self.root / 'compile_commands.json'; self.commands.write_text('[]\n')
        raw = bytearray(256)
        raw[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', raw, 16, 3, 183, 1)
        struct.pack_into('<Q', raw, 32, 64)
        struct.pack_into('<HHH', raw, 52, 64, 56, 2)
        interpreter = b'/lib/ld-linux-aarch64.so.1\0'
        struct.pack_into('<IIQQQQQQ', raw, 64, 1, 5, 0, 0, 0, len(raw), len(raw), 4096)
        struct.pack_into('<IIQQQQQQ', raw, 120, 3, 4, 176, 176, 176, len(interpreter), len(interpreter), 1)
        raw[176:176+len(interpreter)] = interpreter
        for name in engine.PROGRAMS:
            path = self.install / 'bin' / name
            path.parent.mkdir(exist_ok=True); path.write_bytes(raw); path.chmod(0o555)
        self.configs = engine.MAIN_CONFIGS | {'etc/modules/playerbots.conf.dist'}
        for name in self.configs:
            path = self.install / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic immutable configuration fixture\n')
        shutil.copyfile(self.lock, self.install / 'sources.lock.json')
        self.build = dict(schemaVersion=1, architecture='Linux-ARM64', sourceCheckoutAndPatchesVerified=True,
            serverSource=engine.fetch_sources.load_lock(self.lock)['sources']['server'],
            sourcesLock=engine.files.identity(self.lock), integrationRevision='a'*40, buildId='synthetic.1',
            cmakeOptions={'CMAKE_BUILD_TYPE':'RelWithDebInfo'}, hostLoaderSmoke={'qualified':True}, files=[])
        for source in engine.files.installed_files(self.install):
            name = source.relative_to(self.install).as_posix()
            row = dict(path=name, **engine.files.identity(source))
            if name.startswith('bin/'): row['elf'] = {'machine':'AArch64'}
            self.build['files'].append(row)
        self.compiled = dict(formatVersion=1, scope='compiled-server-module-selection',
            source=self.build['serverSource'], sourceLockSha256=self.build['sourcesLock']['sha256'],
            generatedListsMatchInstalledBinaries=True, configFiles=['playerbots.conf'],
            enabledModules=['mod-playerbots'], compileCommands=engine.files.identity(self.commands))
        self.write_metadata()
        self.checkout = patch.object(engine.fetch_sources, 'verify_checkout')
        self.checkout.start(); self.addCleanup(self.checkout.stop)

    def write_metadata(self):
        (self.install / 'server-build.json').write_bytes(engine.canonical(self.build))
        self.compiled['serverBuild'] = engine.files.identity(self.install / 'server-build.json')
        self.modules.write_bytes(engine.canonical(self.compiled))

    def validate(self):
        with patch.object(engine.modules, 'verify', return_value=copy.deepcopy(self.compiled)):
            return engine.validate_inputs(self.install, self.modules, self.commands, self.lock, self.server)

    def test_exact_current_source_and_configuration_selection(self):
        proof = self.validate()
        self.assertEqual(set(proof['configs']), self.configs)
        self.assertEqual(set(proof['selected']), self.configs | {'bin/'+name for name in engine.PROGRAMS})
        self.assertEqual(proof['sourceLock'], engine.files.identity(self.lock))

    def test_changed_template_and_installed_lock_are_refused(self):
        path = self.install / sorted(self.configs)[0]; original = path.read_bytes()
        path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'installed-file-changed'): self.validate()
        path.write_bytes(original)
        (self.install / 'sources.lock.json').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'installed-source-lock'): self.validate()

    def test_old_patch_build_cannot_be_relabelled_current(self):
        self.build['serverSource'] = copy.deepcopy(self.build['serverSource'])
        self.build['serverSource']['patches'] = self.build['serverSource']['patches'][:-1]
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'source-selection-mismatch'): self.validate()

    def test_compiled_receipt_is_recomputed_and_must_match_original_bytes(self):
        self.compiled['enabledModules'] = ['different-module']; self.write_metadata()
        with patch.object(engine.modules, 'verify', return_value={}):
            with self.assertRaisesRegex(ValueError, 'compiled-module-receipt-changed'):
                engine.validate_inputs(self.install, self.modules, self.commands, self.lock, self.server)

    def test_additional_config_or_private_shared_library_requires_review(self):
        extra = dict(path='etc/private.conf', bytes=0, sha256=hashlib.sha256(b'').hexdigest())
        self.build['files'].append(extra); self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'configuration-selection'): self.validate()
        self.build['files'].pop()
        for name in ('lib/private.so', 'bin/private.so'):
            row = dict(path=name, bytes=0, sha256=hashlib.sha256(b'').hexdigest(), elf={'machine':'AArch64'})
            self.build['files'].append(row); self.write_metadata()
            with self.subTest(path=name), self.assertRaisesRegex(ValueError, 'private-shared-library'): self.validate()
            self.build['files'].pop()

    def test_existing_output_preserved_before_input_or_tool_verification(self):
        output = self.root / 'existing'; output.mkdir(); (output/'marker').write_text('preserved')
        with patch.object(engine, 'validate_inputs') as checked, self.assertRaisesRegex(ValueError, 'output-exists'):
            engine.build(output, self.install, self.modules, self.commands, self.lock, self.server,
                         self.root/'not-read', self.root/'not-executed')
        checked.assert_not_called(); self.assertEqual((output/'marker').read_text(), 'preserved')

    def test_output_cannot_modify_verified_server_checkout(self):
        with patch.object(engine, 'validate_inputs') as checked, self.assertRaisesRegex(ValueError, 'overlaps-input'):
            engine.build(self.server/'new-package', self.install, self.modules, self.commands, self.lock,
                         self.server, self.root/'not-read', self.root/'not-executed')
        checked.assert_not_called(); self.assertEqual(list(self.server.iterdir()), [])

    def test_derivative_failure_retains_only_unpublished_private_stage(self):
        proof = self.validate(); output = self.root/'failed-package'
        with patch.object(engine, 'validate_inputs', return_value=proof), \
             patch.object(engine.elf, 'verify_tool', return_value={}), \
             patch.object(engine.elf, 'derive', side_effect=ValueError('fixture-derivative-failure')), \
             patch('sys.stderr', new_callable=io.StringIO), self.assertRaisesRegex(ValueError, 'fixture-derivative-failure'):
            engine.build(output, self.install, self.modules, self.commands, self.lock,
                         self.server, self.root/'not-read', self.root/'not-executed')
        self.assertFalse(output.exists())
        stages = list(self.root.glob('.failed-package.stage-*'))
        self.assertEqual(len(stages), 1)
        self.assertFalse(list(stages[0].glob('*.tar.gz')))
        self.assertEqual(stages[0].stat().st_mode & 0o777, 0o700)


class ArchiveReadback(unittest.TestCase):
    def test_deterministic_modes_member_set_and_changed_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); payload = root/'payload'; (payload/'bin').mkdir(parents=True)
            (payload/'bin/authserver').write_bytes(b'synthetic program; not executable ELF')
            (payload/'provenance').mkdir(); (payload/'provenance/original.json').write_text('{"fixture":true}\n')
            one, two = root/'one.tar.gz', root/'two.tar.gz'
            inventory = engine.write_archive(payload, one)
            self.assertEqual(inventory, engine.write_archive(payload, two))
            self.assertEqual(one.read_bytes(), two.read_bytes())
            self.assertEqual(inventory['bin/authserver']['mode'], 0o555)
            self.assertEqual(inventory['provenance/original.json']['mode'], 0o444)
            wrong = copy.deepcopy(inventory); wrong['bin/authserver']['sha256'] = '0'*64
            with self.assertRaisesRegex(ValueError, 'SHA-256 mismatch'): engine.verify_archive(one, wrong)
            one.write_bytes(one.read_bytes()[:-8])
            with self.assertRaises((EOFError, OSError)): engine.verify_archive(one, inventory)

    def test_pax_and_oversized_gnu_name_headers_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind in ('pax', 'gnu-long-name'):
                path = root/(kind+'.tar.gz')
                name = 'fixture' if kind == 'pax' else 'x'*5000
                with tarfile.open(path, 'w:gz', format=tarfile.PAX_FORMAT if kind == 'pax' else tarfile.GNU_FORMAT) as archive:
                    info = tarfile.TarInfo(name); info.size = 1; info.mode = 0o444
                    if kind == 'pax': info.pax_headers = {'comment':'fixture extended header'}
                    archive.addfile(info, io.BytesIO(b'x'))
                row = dict(bytes=1, sha256=hashlib.sha256(b'x').hexdigest(), mode=0o444)
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'pax-header|name-header-bound'):
                    engine.verify_archive(path, {name:row})


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact NDK toolchain fixture not supplied')
class RealAarch64Packaging(unittest.TestCase):
    """Use real LLVM derivatives, synthetic provenance, and never execute the ELFs."""
    setUp = InputSelection.setUp
    write_metadata = InputSelection.write_metadata
    validate = InputSelection.validate

    def test_paired_archives_preserve_original_receipts_and_omit_private_inputs(self):
        toolchain = Path(os.environ['ESTERIA_NDK_TOOLCHAIN']).resolve(strict=True)
        source = self.root/'fixture.c'
        source.write_text('volatile int marker=17; void _start(void) { for(;;) marker++; }\n')
        executable = self.root/'original'
        subprocess.run([str(toolchain/'clang'), '--target=aarch64-linux-gnu', '-fuse-ld=lld',
            '-nostdlib', '-g', '-Wl,--build-id=sha1', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
            str(source), '-o', str(executable)], check=True, capture_output=True, timeout=30)
        for name in engine.PROGRAMS:
            target = self.install/'bin'/name; target.chmod(0o755)
            shutil.copyfile(executable, target)
        for row in self.build['files']:
            row.update(engine.files.identity(self.install/row['path']))
        self.write_metadata(); proof = self.validate()
        original_modules = self.modules.read_bytes()
        objcopy = toolchain/'llvm-objcopy'; tool = {'executable':engine.files.identity(objcopy)}
        output = self.root/'package'
        with patch.object(engine, 'validate_inputs', return_value=proof), \
             patch.object(engine.elf, 'verify_tool', return_value=tool):
            receipt = engine.build(output, self.install, self.modules, self.commands, self.lock,
                self.server, self.root/'verified-upstream-archive-fixture', objcopy)
        self.assertTrue(receipt['archiveReadbackVerified'])
        self.assertFalse(receipt['sourceCompanionComplete']); self.assertFalse(receipt['androidProviderCreated'])
        self.assertEqual(self.modules.read_bytes(), original_modules)
        self.assertEqual({p.name for p in output.iterdir()},
            {'server-engine-runtime-arm64.tar.gz', 'server-engine-debug-arm64.tar.gz', 'package-receipt.json'})
        for group in ('runtime','debug'):
            row = receipt['packages'][group]
            archive = output/row['archiveFile']; engine.verify_archive(archive, row['inventory'])
            with tarfile.open(archive, 'r:gz') as package:
                self.assertEqual(package.extractfile('provenance/server-modules.json').read(), original_modules)
                self.assertNotIn('sources/server', package.getnames())
                self.assertFalse(any('private' in name or name.startswith(('lib/','include/','var/'))
                    for name in package.getnames()))
        runtime = receipt['packages']['runtime']['inventory']
        self.assertEqual({name for name in runtime if name.startswith('bin/')}, {'bin/'+name for name in engine.PROGRAMS})
        debug = receipt['packages']['debug']['inventory']
        self.assertEqual({name for name in debug if name.startswith('symbols/')}, {'symbols/'+name+'.debug' for name in engine.PROGRAMS})


if __name__ == '__main__': unittest.main()
