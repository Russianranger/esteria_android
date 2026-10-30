"""Synthetic receipt/ELF fixtures only; no helper, SQL or provider is executed."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tests.test_server_build import elf
from tools import package_playerbots_helper as candidate


class HelperCandidate(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name); self.payload = self.root / 'payload'; self.payload.mkdir()
        self.pin = copy.deepcopy(candidate.programs.load_pin())
        self.content = json.loads(candidate.CONTENT_PIN.read_bytes())
        self.original = {}
        inputs = {
            'bin/playerbots-schema': elf(),
            'source-inputs/server-engine-source-inputs.tar.gz': b'not a source archive: host hash fixture only',
            'source-inputs/source-inputs-receipt.json': b'{"hostFixture":true}\n',
            'source-inputs/original-sources.lock.json': self.pin['serverBuildSourceLockText'].encode(),
            'provenance/original-build.json': b'{"hostFixture":"original-build"}\n',
            'provenance/original-modules.json': b'{"hostFixture":"original-modules"}\n',
            'build/compile_commands.json': b'[{"hostFixture":"not compiled"}]\n',
            'build/CMakeCache.txt': b'CMAKE_C_COMPILER_LAUNCHER:STRING=\nCMAKE_CXX_COMPILER_LAUNCHER:STRING=\n',
            'build/commands.json': b'[{"hostFixture":"not executed"}]\n',
        }
        for name, raw in inputs.items():
            path = self.payload / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            path.chmod(0o555 if name.startswith('bin/') else 0o444)
            self.original[name] = candidate.files.identity(path)
        # Only the unit-test selection is replaced with synthetic original input
        # identities. Production selection always validates the checked-in pins.
        self.pin['originalBuild'] = self.original['provenance/original-build.json']
        self.pin['originalModules'] = self.original['provenance/original-modules.json']
        self.pin['originalSourceInputs']['archive'] = self.original['source-inputs/server-engine-source-inputs.tar.gz']
        self.pin['originalSourceInputs']['receipt'] = self.original['source-inputs/source-inputs-receipt.json']
        self.content['originalBuild'] = self.pin['originalBuild']; self.content['compiledModules'] = self.pin['originalModules']
        self.compiled = dict(formatVersion=1, scope='source-built-playerbots-schema-helper', phase='built-component',
            buildTarget='esteria_playerbots_database_reference', actualCompileSucceeded=True,
            actualDatabaseSourcesAndDefinitionVerified=True, compilerCacheDisabled=True, databaseExecuted=False,
            sqlExecuted=False, fullServerCompileSucceeded=False, originalServerProgramsReplaced=False,
            sourceCompanionComplete=False, playerbotsAiQualified=False, worldserverQualified=False,
            androidRuntimeQualified=False, gameplayQualified=False, preparedStatementCountDeclared=52,
            compilerLaunchers=dict(CMAKE_C_COMPILER_LAUNCHER='', CMAKE_CXX_COMPILER_LAUNCHER=''),
            originalBuild=self.pin['originalBuild'], originalModules=self.pin['originalModules'],
            sourceLock=self.pin['serverBuildSourceLock'], serverSource=self.pin['serverSource'],
            executable=self.original['bin/playerbots-schema'],
            sourceInputArchive=self.pin['originalSourceInputs']['archive'], sourceInputReceipt=self.pin['originalSourceInputs']['receipt'],
            elf=candidate.files.elf_header(self.payload / 'bin/playerbots-schema', executable=True),
            payloadFiles=copy.deepcopy(self.original))
        self.write_build()
        self.native_path = self.root / 'native.json'
        self.uuid = '01234567-89ab-4cde-8fab-0123456789ab'
        row = dict(scope='owned-packaged-content-playerbots-schema-only', mysqlUuid=self.uuid, mysqlVersion='8.0.46',
            originalBuild=self.pin['originalBuild'], compiledModules=self.pin['originalModules'], contentReceipt=self.content['receipt'],
            sourceLockSha256=self.pin['serverBuildSourceLock']['sha256'], preparedStatementCount=52,
            playerbotsPlanSha256='1' * 64, helperBuildReceipt=self.build_identity, helperExecutable=self.compiled['executable'],
            playerbotsSchemaInitialized=True, exactSourceLedgerVerified=True,
            coreSchemasLedgersCredentialsAccountPreserved=True, compiledPlayerbotsLoaderExecuted=False,
            databaseSnapshot=dict(tableCount=32, updateCount=31), playerbotsAiQualified=False, botCharactersCreated=False,
            worldserverExecuted=False, schemaUpgradeQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
        self.native = dict(formatVersion=1, scope='disposable-native-arm64-product-playerbots-schema', phase='complete',
            qualificationSucceeded=True, originalBuild=self.pin['originalBuild'], compiledModules=self.pin['originalModules'],
            sourceLockSha256=self.pin['serverBuildSourceLock']['sha256'], source=self.pin['serverSource'],
            contentReceipt=self.content['receipt'], helperBuildReceipt=self.build_identity, helperExecutable=self.compiled['executable'],
            preparedStatementCount=52, selectedSourceBaseFiles=29, selectedSourceUpdates=31,
            mysqlUuid=self.uuid, mysqlVersion='8.0.46', databaseSnapshot=copy.deepcopy(row['databaseSnapshot']),
            engineDerivative=dict(scope='verified-engine-derivative-program-selection', originalReceiptsUnchanged=True,
                originalBuild=self.pin['originalBuild'], originalModules=self.pin['originalModules'],
                packageReceipt=candidate.identity(self.pin['originalPackageReceipt']), runtimeArchive=self.pin['originalRuntimeArchive'],
                programs={name: value['stripped'] for name, value in self.pin['programPairs'].items()}),
            playerbotsFirst=dict(row, compiledPlayerbotsLoaderExecuted=True), playerbotsCompletedReentry=copy.deepcopy(row),
            actualLoaderReentry=dict(exitCode=0, preparedStatementCount=52))
        self.native.update({name: True for name in candidate.SQL_TRUE}); self.native.update({name: False for name in candidate.FALSE})
        for phase in ('productBeforeNativeProbe', 'productAfterRestart'):
            self.native[phase] = dict(playerbots=copy.deepcopy(row),
                updater=dict(compiledUpdaterCompleted=True, compiledUpdaterExecuted=False, sourceLedgersVerified=True,
                             playerbots=copy.deepcopy(row)),
                realm=dict(completedUpdaterVerified=True, mysqlUuid=self.uuid),
                account=dict(completedUpdaterVerified=True, mysqlUuid=self.uuid))
        self.write_native()
        self.selected = patch.object(candidate, 'selection', side_effect=lambda: (copy.deepcopy(self.pin), copy.deepcopy(self.content)))
        self.selected.start(); self.addCleanup(self.selected.stop)

    def write_build(self):
        path = self.payload / 'helper-build.json'; path.write_bytes(candidate.programs.encoded(self.compiled))
        self.build_identity = candidate.files.identity(path)

    def write_native(self):
        self.native_path.write_bytes(candidate.programs.encoded(self.native))
        self.native_identity = candidate.files.identity(self.native_path)

    def build(self, output=None, **kwargs):
        return candidate.build(self.payload, kwargs.pop('build_sha', self.build_identity['sha256']), self.native_path,
            kwargs.pop('native_sha', self.native_identity['sha256']), output or self.root / 'candidate', **kwargs)

    def test_candidate_and_reverification_preserve_three_programs_without_activation(self):
        original_pin = copy.deepcopy(self.pin)
        proof = self.build(); output = self.root / 'candidate'
        pin_sha = candidate.files.identity(output / 'candidate-pin.json')['sha256']
        self.assertEqual(candidate.verify(output, pin_sha), proof)
        self.assertEqual(proof['originalProgramPairs'], original_pin['programPairs'])
        self.assertEqual(proof['originalProgramsArchive'], original_pin['archive'])
        self.assertEqual(set(proof['runtimeFiles']), {candidate.HELPER, candidate.BUILD, candidate.NATIVE})
        self.assertTrue(proof['helperBuildAndNativeSchemaProofVerified'])
        for flag in ('sourceCompanionComplete', 'androidProviderCreated', 'productionActivated',
                     'completeSetupQualified', 'slotPromoted', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(proof[flag], False)
        self.assertEqual(self.pin, original_pin)
        for name, identity in self.original.items(): self.assertEqual(candidate.files.identity(self.payload / name), identity)
        self.assertEqual((output / 'runtime' / candidate.HELPER).stat().st_mode & 0o777, 0o555)

    def test_unpinned_build_or_native_receipts_never_create_output(self):
        for kwargs in ({'build_sha': '0' * 64}, {'native_sha': '0' * 64}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, 'receipt-digest-differs'):
                self.build(**kwargs)
            self.assertFalse((self.root / 'candidate').exists())

    def test_missing_or_changed_source_member_refuses_before_publication(self):
        path = self.payload / 'build/compile_commands.json'; original = path.read_bytes()
        path.chmod(0o600); path.write_bytes(b'changed retained source/build input')
        with self.assertRaisesRegex(ValueError, 'payload-changed'): self.build()
        path.write_bytes(original); extra = self.payload / 'extra'; extra.write_bytes(b'extra')
        with self.assertRaisesRegex(ValueError, 'exact-source-payload'): self.build()
        self.assertFalse((self.root / 'candidate').exists())

    def test_failure_partial_scope_overclaim_and_no_restart_proofs_refuse(self):
        original = copy.deepcopy(self.native)
        for field, value in [('qualificationSucceeded', False), ('phase', 'failed'), ('restartPersistenceVerified', False),
                             ('fixtureProbeRemoved', False), ('androidRuntimeQualified', True), ('failureClass', 'ValueError')]:
            self.native = dict(copy.deepcopy(original), **{field: value}); self.write_native()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'actual-native-schema-proof'):
                self.build()
            self.assertFalse((self.root / 'candidate').exists())

    def test_native_original_program_swap_or_different_instance_replay_refuses(self):
        original = copy.deepcopy(self.native)
        self.native['engineDerivative']['programs']['dbimport'] = dict(bytes=1, sha256='0' * 64); self.write_native()
        with self.assertRaisesRegex(ValueError, 'original-three-programs-changed'): self.build()
        self.native = original; self.native['productAfterRestart']['playerbots']['mysqlUuid'] = '11111111-1111-4111-8111-111111111111'
        self.write_native()
        with self.assertRaisesRegex(ValueError, 'final-product-proof|same-instance-completed-proof'): self.build()

    def test_verify_rejects_changed_helper_companion_mode_and_candidate_activation(self):
        self.build(); root = self.root / 'candidate'; receipt = root / 'candidate-pin.json'
        pin_sha = candidate.files.identity(receipt)['sha256']; helper = root / 'runtime' / candidate.HELPER
        helper.chmod(0o444)
        with self.assertRaisesRegex(ValueError, 'runtime-or-companion-changed'): candidate.verify(root, pin_sha)
        helper.chmod(0o555)
        source = root / 'companion/build-payload/build/commands.json'; source.chmod(0o600); source.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'payload-changed'): candidate.verify(root, pin_sha)
        proof = json.loads(receipt.read_bytes()); proof['productionActivated'] = True
        receipt.write_bytes(candidate.programs.encoded(proof)); new_sha = candidate.files.identity(receipt)['sha256']
        with self.assertRaisesRegex(ValueError, 'scope-or-activation'): candidate.verify(root, new_sha)

    def test_existing_output_and_overlapping_payload_are_preserved(self):
        output = self.root / 'candidate'; output.mkdir(); (output / 'marker').write_bytes(b'preserved')
        with self.assertRaisesRegex(ValueError, 'existing-or-overlapping'): self.build(output)
        self.assertEqual((output / 'marker').read_bytes(), b'preserved')
        with self.assertRaisesRegex(ValueError, 'existing-or-overlapping'): self.build(self.payload / 'nested')


if __name__ == '__main__': unittest.main()
