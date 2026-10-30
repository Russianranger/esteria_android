"""Host guards and receipt separation; fixtures never qualify a native build."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import build_playerbots_component as component
from tools import prepare_server_isolated_build as inputs


class PlayerbotsComponentBuild(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.provider = json.loads(component.PROVIDER.read_text())
        self.original_lock = self.root / 'original-sources.lock.json'
        self.original_lock.write_text(self.provider['serverBuildSourceLockText'])

    def test_explicit_original_lock_keeps_archived_hash_and_current_server_profile(self):
        pin = inputs.load_pin(self.original_lock)
        self.assertEqual(pin['sourceLockSha256'], self.provider['serverBuildSourceLock']['sha256'])
        self.assertEqual(inputs.files.identity(self.original_lock), self.provider['serverBuildSourceLock'])
        self.assertEqual(inputs.selected_source_lock(self.original_lock), self.original_lock)
        expected = inputs.ROOT / 'sources.lock.json' if inputs.files.identity(inputs.ROOT / 'sources.lock.json') == \
            self.provider['serverBuildSourceLock'] else inputs.ARCHIVED_LOCK
        self.assertEqual(inputs.selected_source_lock(), expected)
        self.assertEqual(inputs.load_pin(), pin)

    def test_default_current_identity_or_pinned_snapshot_survives_only_client_advance(self):
        current = self.root / 'sources.lock.json'
        current.write_bytes(self.original_lock.read_bytes())
        with patch.object(inputs, 'ROOT', self.root), patch.object(inputs, 'ARCHIVED_LOCK', self.original_lock):
            self.assertEqual(inputs.selected_source_lock(), current)
            advanced = json.loads(current.read_text()); advanced['sources']['client']['commit'] = '4' * 40
            current.write_text(json.dumps(advanced))
            self.assertEqual(inputs.selected_source_lock(), self.original_lock)
            self.original_lock.write_bytes(self.original_lock.read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'original-source-lock-pin'):
                inputs.selected_source_lock()
            self.original_lock.write_text(self.provider['serverBuildSourceLockText'])
            for field in ('server', 'compatibility'):
                changed = copy.deepcopy(advanced)
                if field == 'server': changed['sources']['server']['patches'][-1]['sha256'] = '0' * 64
                else: changed['compatibility']['base_client_build'] = 12340.0
                current.write_text(json.dumps(changed))
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'current-server-or-compatibility'):
                    inputs.selected_source_lock()

    def test_original_lock_pin_and_typed_current_source_or_compatibility_drift_are_refused(self):
        self.original_lock.write_bytes(self.original_lock.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'original-source-lock-pin'):
            inputs.load_pin(self.original_lock)
        self.original_lock.write_text(self.provider['serverBuildSourceLockText'])
        original = json.loads(self.original_lock.read_text())
        current = json.loads((inputs.ROOT / 'sources.lock.json').read_text())
        for field in ('server', 'compatibility', 'schema'):
            changed = copy.deepcopy(current)
            if field == 'server': changed['sources']['server']['commit'] = '0' * 40
            elif field == 'compatibility': changed['compatibility']['base_client_build'] = 12340.0
            else: changed['schema'] = True
            with self.subTest(field=field), patch.object(inputs.fetch_sources, 'load_lock', side_effect=[original, changed]), \
                    self.assertRaisesRegex(ValueError, 'current-server-or-compatibility'):
                inputs.selected_source_lock(self.original_lock)

    def test_wrong_native_architecture_stops_before_input_reads_commands_or_output(self):
        output = self.root / 'not-created'
        with patch.object(component.platform, 'machine', return_value='x86_64'), \
                patch.object(component.isolated, 'verify_prepared') as verify, \
                patch.object(component.isolated, 'run_owned') as run, \
                self.assertRaisesRegex(ValueError, 'native-arm64-playerbots'):
            component.build(output, output, output, output, output, integration_revision='a' * 40)
        verify.assert_not_called(); run.assert_not_called(); self.assertFalse(output.exists())

    def test_existing_and_overlapping_outputs_stop_before_network_or_source_work(self):
        prepared = self.root / 'prepared'; prepared.mkdir()
        acquired = self.root / 'acquired'; acquired.mkdir()
        existing = self.root / 'existing'; existing.mkdir(); (existing / 'saved').write_bytes(b'preserved')
        for output in (existing, prepared / 'nested', acquired / 'nested'):
            with self.subTest(output=output), patch.object(component.platform, 'machine', return_value='aarch64'), \
                    patch.object(component.isolated, 'require_offline') as network, \
                    self.assertRaisesRegex(ValueError, 'output-preserved'):
                component.build(prepared, acquired, self.original_lock, self.root / 'env', output, integration_revision='a' * 40)
            network.assert_not_called()
        self.assertEqual((existing / 'saved').read_bytes(), b'preserved')

    def test_original_reference_bytes_are_used_instead_of_current_integration_replacements(self):
        prepared = self.root / 'prepared'
        rows = {}
        for name in component.reference.INPUTS:
            raw = (component.ROOT / name).read_bytes()
            target = prepared / 'integration' / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            rows[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), gitMode='100644')
        manifest = dict(pristineGitFiles=dict(integration=rows))
        result = component.verify_reference_inputs(prepared, manifest)
        self.assertEqual({name: result[name] for name in component.REFERENCE_INPUTS}, component.REFERENCE_INPUTS)
        target = prepared / 'integration/tests/playerbots_database_reference.cpp'; target.write_bytes(b'changed reference')
        with self.assertRaisesRegex(ValueError, 'prepared-input-changed'):
            component.verify_reference_inputs(prepared, manifest)
        rows['tests/playerbots_database_reference.cpp'].update(component.files.identity(target))
        with self.assertRaisesRegex(ValueError, 'original-input-pin-differs'):
            component.verify_reference_inputs(prepared, manifest)

    def test_declared_count_refuses_reordered_sentinel_explicit_values_or_changed_count(self):
        header = self.root / 'PlayerbotsDatabase.h'
        values = ['PLAYERBOTS_TEST_' + str(index) for index in range(52)]
        def write(rows): header.write_text('enum PlayerbotsDatabaseStatements : uint32 {\n' + ',\n'.join(rows) + '\n};\n')
        write(values + ['MAX_PLAYERBOTS_STATEMENTS'])
        self.assertEqual(component.declared_statement_count(header), 52)
        for rows in (values[:-1] + ['MAX_PLAYERBOTS_STATEMENTS'],
                     ['MAX_PLAYERBOTS_STATEMENTS'] + values,
                     ['PLAYERBOTS_TEST_0 = 0'] + values[1:] + ['MAX_PLAYERBOTS_STATEMENTS']):
            write(rows)
            with self.assertRaisesRegex(ValueError, '52-statement-enum-differs'):
                component.declared_statement_count(header)

    def test_failed_source_binding_keeps_false_typed_receipt_and_never_configures(self):
        prepared = self.root / 'prepared'; prepared.mkdir(); acquired = self.root / 'acquired'; acquired.mkdir()
        output = self.root / 'result'
        wrong = dict(originalBuild=dict(bytes=1, sha256='0' * 64), originalCompiledModules=component.ORIGINAL_MODULES,
                     sourceLock=self.provider['serverBuildSourceLock'])
        with patch.object(component.platform, 'machine', return_value='aarch64'), \
                patch.object(component.isolated, 'require_offline', return_value=dict(interfaces=['lo'])), \
                patch.object(component.isolated, 'verify_prepared', return_value=(wrong, {}, {'source': self.provider['serverSource']})), \
                patch.object(component.isolated, 'run_owned') as run, \
                self.assertRaisesRegex(ValueError, 'original-server-binding-differs'):
            component.build(prepared, acquired, self.original_lock, self.root / 'env', output, integration_revision='a' * 40)
        run.assert_not_called()
        receipt = json.loads((output / 'qualification.json').read_text())
        self.assertEqual(receipt['scope'], 'source-built-playerbots-schema-helper')
        for flag in ('actualCompileSucceeded', 'actualDatabaseSourcesAndDefinitionVerified', 'databaseExecuted',
                     'sourceCompanionComplete', 'fullServerCompileSucceeded', 'originalServerProgramsReplaced',
                     'playerbotsAiQualified', 'worldserverQualified', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(receipt[flag], False)
        self.assertFalse((output / 'payload').exists())

    def test_copy_rejects_changed_identity_and_link_without_mutating_original(self):
        source = self.root / 'source'; source.write_bytes(b'original immutable bytes')
        expected = component.files.identity(source)
        target = self.root / 'copy'
        self.assertEqual(component.copy_exact(source, target, expected), expected)
        self.assertEqual(source.read_bytes(), target.read_bytes())
        self.assertEqual(target.stat().st_mode & 0o777, 0o444)
        with self.assertRaisesRegex(ValueError, 'payload-input-changed'):
            component.copy_exact(source, self.root / 'changed', dict(bytes=1, sha256='0' * 64))
        link = self.root / 'link'; link.symlink_to(source)
        with self.assertRaises((ValueError, OSError)): component.copy_exact(link, self.root / 'bad')

    def test_mocked_orchestration_builds_only_reference_and_preserves_new_vs_original_commands(self):
        prepared = self.root / 'prepared'; prepared.mkdir(); acquired = self.root / 'acquired'; acquired.mkdir()
        output = self.root / 'result'; environment = self.root / 'environment.json'
        environment.write_text(json.dumps(dict(scope='measured-original-relevant-native-build-environment-comparison',
                                               relevantBuildEnvironmentMatched=True)))
        integration = {}
        for name in component.reference.INPUTS:
            target = prepared / 'integration' / name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((component.ROOT / name).read_bytes()); integration[name] = component.files.identity(target)
        header = prepared / 'source/src/server/database/Database/Implementation/PlayerbotsDatabase.h'
        header.parent.mkdir(parents=True)
        header.write_text('enum PlayerbotsDatabaseStatements : uint32 {' + ','.join(
            ['PLAYERBOTS_TEST_' + str(index) for index in range(52)] + ['MAX_PLAYERBOTS_STATEMENTS']) + '};')
        old_commands = dict(bytes=111, sha256='1' * 64); new_commands = dict(bytes=222, sha256='2' * 64)
        pin = inputs.load_pin(self.original_lock)
        prep = dict(originalBuild=component.ORIGINAL_BUILD, originalCompiledModules=component.ORIGINAL_MODULES,
            sourceLock=self.provider['serverBuildSourceLock'], sourceInputArchive=pin['sourceInputs']['archive'],
            sourceInputReceipt=pin['sourceInputs']['receipt'], sourceSupplements=pin['sourceSupplements'])
        manifest = dict(source=self.provider['serverSource'], compileCommands=old_commands,
                        pristineGitFiles=dict(integration=integration))
        original = dict(enabledModules=['mod-playerbots'], configFiles=['playerbots.conf'])
        read_json = component.modules.read_json
        def read(path, **kwargs):
            if path == prepared / 'provenance/metadata/server-modules.json': return original, component.ORIGINAL_MODULES
            return read_json(path, **kwargs)
        executed = []
        def run(arguments, log, build_environment, **kwargs):
            executed.append([str(row) for row in arguments]); log.write_bytes(b'fixture compiler output\n')
            if '--build' not in arguments:
                (output / 'build').mkdir()
            else:
                (output / 'build' / component.TARGET).write_bytes(
                    b'fixture binary\x00ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements=\x00')
            return dict(exitCode=0, output=component.files.identity(log))
        def compare(acquired, path, **kwargs):
            path.write_text('{"fixture":true}\n')
            return dict(relevantBuildEnvironmentMatched=True)
        def retain(path, *args): path.mkdir(); return {'fixture-only': dict(bytes=0, sha256='0' * 64)}
        with patch.object(component.platform, 'machine', return_value='aarch64'), \
                patch.object(component.isolated, 'require_offline', return_value=dict(interfaces=['lo'])), \
                patch.object(component.isolated, 'verify_prepared', return_value=(prep, {'fixture': True}, manifest)), \
                patch.object(component.modules, 'read_json', side_effect=read), \
                patch.object(component.inputs, 'verify_environment', side_effect=compare), \
                patch.object(component.shutil, 'which', return_value=sys.executable), \
                patch.object(component.isolated, 'run_owned', side_effect=run), \
                patch.object(component.files, 'cmake_options', return_value=dict(CMAKE_C_COMPILER_LAUNCHER='', CMAKE_CXX_COMPILER_LAUNCHER='')), \
                patch.object(component.reference, 'commands', return_value=new_commands), \
                patch.object(component.files, 'elf_header', return_value=dict(machine='AArch64')), \
                patch.object(component.files, 'bounded_command', return_value=''), \
                patch.object(component, 'retain_payload', side_effect=retain):
            proof = component.build(prepared, acquired, self.original_lock, environment, output, integration_revision='a' * 40)
        self.assertEqual(len(executed), 2)
        self.assertEqual(executed[1][1:], ['--build', str(output / 'build'), '--parallel', '2', '--target', component.TARGET])
        self.assertIn('-DFETCHCONTENT_FULLY_DISCONNECTED=ON', executed[0])
        self.assertEqual(proof['originalCompileCommands'], old_commands)
        self.assertEqual(proof['newCompileCommands'], new_commands)
        self.assertEqual(proof['originalBuild'], component.ORIGINAL_BUILD)
        self.assertEqual(proof['originalModules'], component.ORIGINAL_MODULES)
        self.assertEqual(proof['preparedStatementCountDeclared'], 52)
        self.assertTrue(proof['actualCompileSucceeded']); self.assertTrue(proof['actualDatabaseSourcesAndDefinitionVerified'])
        for flag in ('databaseExecuted', 'sqlExecuted', 'fullServerCompileSucceeded', 'sourceCompanionComplete',
                     'originalServerProgramsReplaced', 'playerbotsAiQualified', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(proof[flag], False)
        self.assertEqual(json.loads((output / 'payload/helper-build.json').read_text()), proof)

    def test_payload_retains_original_source_archive_receipts_supplement_and_new_build_inputs(self):
        prepared, acquired, output = (self.root / name for name in ('prepared', 'acquired', 'output'))
        environment = self.root / 'environment.json'; environment.write_bytes(b'fixture environment\n')
        paths = [output / 'build' / component.TARGET,
            acquired / 'source-inputs/server-engine-source-inputs.tar.gz',
            acquired / 'source-inputs/source-inputs-receipt.json',
            prepared / 'preparation-receipt.json', prepared / 'provenance/archival-revision.txt',
            prepared / 'provenance/metadata/server-build.json', prepared / 'provenance/metadata/server-modules.json',
            prepared / 'provenance/metadata/compile_commands.json', output / 'build/compile_commands.json',
            output / 'build/CMakeCache.txt', output / 'diagnostics/commands.json',
            output / 'diagnostics/environment-before.json', output / 'diagnostics/environment-after.json',
            acquired / 'supplements/modules/ModulesScriptLoader.h']
        paths += [acquired / 'environment' / name for name in ('cache-environment.json', 'build-packages.txt',
                                                             'build-host.txt', 'CMakeCache.txt')]
        paths += [prepared / 'integration' / name for name in component.reference.INPUTS]
        for name in ('src/cmake/genrev.cmake', 'src/genrev/CMakeLists.txt'):
            paths += [prepared / 'provenance/source-export-adaptations' / name, prepared / 'source' / name]
        for index, path in enumerate(paths):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(('fixture input ' + str(index)).encode())
        originals = {path: component.files.identity(path) for path in paths}
        proof = dict(sourceSupplements={'modules/ModulesScriptLoader.h': {}},
            executable=originals[output / 'build' / component.TARGET],
            originalBuild=originals[prepared / 'provenance/metadata/server-build.json'],
            originalModules=originals[prepared / 'provenance/metadata/server-modules.json'],
            sourceLock=component.files.identity(self.original_lock))
        payload = self.root / 'payload'
        inventory = component.retain_payload(payload, prepared, acquired, output, self.original_lock, environment, proof)
        self.assertEqual(inventory['source-inputs/server-engine-source-inputs.tar.gz'],
                         originals[acquired / 'source-inputs/server-engine-source-inputs.tar.gz'])
        self.assertEqual(inventory['provenance/original-modules.json'], proof['originalModules'])
        self.assertEqual(inventory['bin/playerbots-schema'], proof['executable'])
        self.assertEqual((payload / 'bin/playerbots-schema').stat().st_mode & 0o777, 0o755)
        self.assertEqual([name for name in inventory if name.startswith('bin/')], ['bin/playerbots-schema'])
        for name in component.RECIPES:
            self.assertEqual(inventory['recipes/' + name], component.files.identity(component.ROOT / name))
        for path, identity in originals.items(): self.assertEqual(component.files.identity(path), identity)
        self.assertFalse((payload / 'helper-build.json').exists())  # Written only after this readback succeeds.


if __name__ == '__main__': unittest.main()
