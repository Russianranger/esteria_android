"""Host guard tests never qualify an ARM64 server build or source closure."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import qualify_server_isolated_build as isolated


class IsolatedBuildGuards(unittest.TestCase):
    def test_non_native_host_cannot_read_inputs_execute_or_create_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'not-created'
            with patch.object(isolated.platform, 'machine', return_value='x86_64'), \
                    patch.object(isolated, 'verify_prepared') as verify, \
                    patch.object(isolated, 'run_owned') as execute, \
                    self.assertRaisesRegex(ValueError, 'native-arm64-isolated'):
                isolated.qualify(output, output, output, output)
            verify.assert_not_called(); execute.assert_not_called(); self.assertFalse(output.exists())

    def test_network_guard_accepts_only_loopback_and_never_promises_remote_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'netdev'
            path.write_text('Inter-| Receive | Transmit\n lo: 0 0 0\n')
            self.assertIs(isolated.require_offline(path)['externalNetworkingAvailable'], False)
            path.write_text('lo: 0\n eth0: 0\n')
            with self.assertRaisesRegex(ValueError, 'loopback-only'): isolated.require_offline(path)

    def test_existing_and_overlapping_outputs_preserved_before_command_or_environment_work(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prepared = root / 'prepared'; prepared.mkdir()
            acquired = root / 'inputs'; acquired.mkdir(); output = root / 'existing'; output.mkdir()
            (output / 'save').write_bytes(b'keep')
            with patch.object(isolated.platform, 'machine', return_value='aarch64'), \
                    patch.object(isolated, 'require_offline') as network:
                for target in (output, prepared / 'new', acquired / 'new'):
                    with self.subTest(target=target), self.assertRaisesRegex(ValueError, 'output-preserved'):
                        isolated.qualify(prepared, acquired, root / 'limits', target)
                network.assert_not_called()
            self.assertEqual((output / 'save').read_bytes(), b'keep')

    def test_configuration_uses_private_fresh_tree_original_flags_and_disconnected_original_lua(self):
        prepared, output = Path('/prepared'), Path('/new-output')
        args = isolated.configure_arguments(Path('/usr/local/bin/cmake'), prepared, output)
        self.assertEqual(args[0], '/usr/local/bin/cmake')
        for flag in ('-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DSCRIPTS=static', '-DMODULES=static',
                     '-DAPPS_BUILD=all', '-DTOOLS_BUILD=all', '-DELUNA=ON', '-DLUA_VERSION=lua52',
                     '-DLUA_STATIC=ON', '-DNOPCH=1', '-DWITHOUT_GIT=ON', '-DFETCHCONTENT_FULLY_DISCONNECTED=ON',
                     '-DCMAKE_C_COMPILER_LAUNCHER=', '-DCMAKE_CXX_COMPILER_LAUNCHER='):
            self.assertIn(flag, args)
        self.assertIn('-DFETCHCONTENT_SOURCE_DIR_LUA52=/prepared/external/lua-5.2.4', args)
        self.assertIn('-DESTERIA_ARCHIVAL_REVISION_FILE=/prepared/provenance/archival-revision.txt', args)
        self.assertNotIn('ccache', ' '.join(args))
        with patch.dict(os.environ, {'GITHUB_TOKEN': 'private', 'CXXFLAGS': '-DUNREVIEWED', 'CCACHE_DIR': '/cache'}):
            environment = isolated.build_environment(output)
        self.assertEqual(environment['CCACHE_DISABLE'], '1')
        self.assertNotIn('GITHUB_TOKEN', environment); self.assertNotIn('CXXFLAGS', environment)
        self.assertNotIn('CCACHE_DIR', environment)

    def test_actual_owned_command_success_nonzero_bounded_output_and_timeout(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); environment = {'PATH': '/usr/bin:/bin'}
            receipt = isolated.run_owned([sys.executable, '-c', 'print("actual subprocess fixture")'],
                                        root / 'success.log', environment, timeout=5)
            self.assertEqual(receipt['exitCode'], 0)
            self.assertIn('actual subprocess fixture', (root / 'success.log').read_text())
            with self.assertRaisesRegex(ValueError, 'nonzero-exit:7'):
                isolated.run_owned([sys.executable, '-c', 'raise SystemExit(7)'], root / 'failed.log', environment, timeout=5)
            with self.assertRaisesRegex(ValueError, 'log-bound'):
                isolated.run_owned([sys.executable, '-c', 'import os;os.write(1,b"x"*100000)'],
                                   root / 'bounded.log', environment, timeout=5, maximum=1024)
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, 'command-timeout'):
                isolated.run_owned([sys.executable, '-c', 'import os,time; os.fork(); time.sleep(60)'],
                                   root / 'timeout.log', environment, timeout=.1)
            self.assertLess(time.monotonic() - started, 3)

    def test_failed_environment_check_leaves_typed_false_receipt_without_configure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prepared = root / 'prepared'; prepared.mkdir()
            acquired = root / 'inputs'; acquired.mkdir(); output = root / 'result'
            prep = dict(originalBuild={'fixture': True}, originalCompiledModules={'fixture': True}, sourceLock={'fixture': True})
            with patch.object(isolated.platform, 'machine', return_value='aarch64'), \
                 patch.object(isolated, 'require_offline', return_value={'interfaces': ['lo']}), \
                 patch.object(isolated, 'verify_prepared', return_value=(prep, {'fixture': True}, {})), \
                 patch.object(isolated.inputs, 'verify_environment', side_effect=ValueError('fixture-environment-drift')), \
                 patch.object(isolated, 'run_owned') as execute, self.assertRaisesRegex(ValueError, 'environment-drift'):
                isolated.qualify(prepared, acquired, root / 'limits.json', output)
            execute.assert_not_called()
            receipt = json.loads((output / 'qualification.json').read_bytes())
            self.assertFalse(receipt['sourceCompanionComplete']); self.assertFalse(receipt['isolatedSourceRebuildQualified'])
            self.assertFalse(receipt['fullCompileObserved']); self.assertFalse((output / 'sealed').exists())

    def test_separate_source_archive_is_deterministic_read_back_and_excludes_elf_git_and_assets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'source.py'; source.write_text('# exact recipe fixture\n')
            one, two = root / 'one.tar.gz', root / 'two.tar.gz'
            selected = {'recipes/tools/fixture.py': source}
            first = isolated.write_source_archive(one, selected)
            self.assertEqual(first, isolated.write_source_archive(two, selected)); self.assertEqual(one.read_bytes(), two.read_bytes())
            isolated.engine.verify_archive(one, first)
            for index, name in enumerate(('source/.git/config', 'source/Data/game.MPQ', 'new-build/worldserver.o')):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'binary-or-asset'):
                    isolated.write_source_archive(root / ('bad-' + str(index)), {name: source})
            source.write_bytes(b'\x7fELF' + b'private executable fixture')
            with self.assertRaisesRegex(ValueError, 'elf-binary'):
                isolated.write_source_archive(root / 'elf-rejected', {'source/hidden': source})

    def test_rebound_protocol_metadata_cannot_replace_exact_actual_client_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); manifest = root / 'limits.json'; manifest.write_text('{}')
            (root / 'client-build.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'actual-pinned-client-layout'):
                isolated.protocol_check(root, manifest)


@unittest.skipUnless(os.environ.get('ESTERIA_ISOLATED_RETAINED_INPUTS') and os.environ.get('ESTERIA_ISOLATED_PREPARED'),
                     'exact retained isolated preparation not supplied')
class ExactSourcePreparation(unittest.TestCase):
    def test_actual_prepared_source_and_archival_recipes_reverify_without_build_or_source_fetch(self):
        retained = Path(os.environ['ESTERIA_ISOLATED_RETAINED_INPUTS']).resolve(strict=True)
        prepared = Path(os.environ['ESTERIA_ISOLATED_PREPARED']).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix='isolated-input-contract-') as temporary:
            root = Path(temporary); (root / 'source-inputs').mkdir()
            pin = isolated.inputs.load_pin()
            for field in ('archive', 'receipt'):
                name = pin['sourceInputs'][field]['file']
                shutil.copyfile(retained / 'source-inputs' / name, root / 'source-inputs' / name)
            shutil.copytree(retained / 'original-build-environment', root / 'environment')
            (root / 'acquisition.json').write_bytes(isolated.engine.canonical(dict(formatVersion=1,
                scope='isolated-source-build-inputs-acquired', inputLock=isolated.files.identity(isolated.inputs.LOCK))))
            receipt, _, manifest = isolated.verify_prepared(prepared, root)
            self.assertEqual(receipt['selectedSourceFiles'], 4942)
            self.assertEqual(len(manifest['compilerCoverage']['observedServerSources']), 2199)
            self.assertEqual(len(manifest['compilerCoverage']['observedServerIncludeDirectories']), 340)
            self.assertFalse(receipt['sourceCompanionComplete'])


if __name__ == '__main__': unittest.main()
