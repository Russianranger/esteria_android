"""Source-only composition guards; fixture receipts confer no native proof."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import seal_playerbots_helper_sources as source


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.chmod(0o600)
    path.write_bytes(data if type(data) is bytes else source.engine.canonical(data))
    return source.files.identity(path)


class SourceCompanion(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='playerbots-source-companion-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def test_pending_measurement_refuses_before_creating_output(self):
        pending = dict(formatVersion=1, scope='playerbots-helper-corresponding-source-inputs',
                       state='pending-native-helper-dependency-capture')
        with patch.object(source.modules, 'read_json', return_value=(pending, {})):
            with self.assertRaisesRegex(ValueError, 'measured-input-pin-required'):
                source.seal(*(self.root / n for n in ('payload', 'candidate', 'original', 'git', 'new/output')))
        self.assertFalse((self.root / 'new').exists())

    def test_measured_capture_pin_preserves_the_original_three_program_source_selection(self):
        pin, _, provider = source.load_pin()
        self.assertEqual(pin['originalSourceQualification'], provider['sourceQualification'])
        self.assertEqual(pin['serverBuildSourceLock'], provider['serverBuildSourceLock'])
        changed = copy.deepcopy(pin); changed['originalSourceQualification']['archive']['sha256'] = '0' * 64
        with patch.object(source.modules, 'read_json', return_value=(changed, {})):
            with self.assertRaisesRegex(ValueError, 'original-provider-binding-differs'): source.load_pin()

    def test_exact_inventory_refuses_extra_changed_and_linked_files(self):
        root = self.root / 'payload'; row = write(root / 'source.c', b'int source;\n')
        source.check_inventory(root, {'source.c': row})
        write(root / 'extra', b'unrecorded')
        with self.assertRaisesRegex(ValueError, 'file-set-or-bytes'): source.check_inventory(root, {'source.c': row})
        (root / 'extra').unlink(); write(root / 'source.c', b'changed')
        with self.assertRaisesRegex(ValueError, 'file-set-or-bytes'): source.check_inventory(root, {'source.c': row})
        (root / 'source.c').unlink(); (root / 'source.c').symlink_to('/etc/hostname')
        with self.assertRaises(ValueError): source.check_inventory(root, {'source.c': row})

    def test_only_declared_runtime_binaries_are_omitted_from_source_archive(self):
        root = self.root / 'payload'; write(root / 'bin/helper', b'\x7fELF' + bytes(80))
        write(root / 'source/ref.cpp', b'int source;\n')
        with self.assertRaisesRegex(ValueError, 'undeclared-native-program'): source.source_files(root)
        self.assertEqual(set(source.source_files(root, excluded=('bin/helper',))), {'source/ref.cpp'})
        write(root / 'source/hidden.o', b'object extension')
        with self.assertRaisesRegex(ValueError, 'binary-or-git'): source.source_files(root, excluded=('bin/helper',))

    def test_genuine_empty_regular_source_files_survive_inventory_and_archive_readback(self):
        root = self.root / 'sources'; empty = write(root / 'README.md', b'')
        selected = source.source_files(root)
        self.assertEqual(source.identity(empty)['bytes'], 0)
        archive = self.root / 'source.tar.gz'
        rows = source.isolated.write_source_archive(archive, selected)
        self.assertEqual(source.identity(rows['README.md']), empty)
        source.engine.verify_archive(archive, rows)

    def test_corresponding_sources_keep_both_binary_identities_and_require_exact_contract(self):
        old = {n: dict(bytes=1, sha256='1' * 64) for n in ('originalBuild', 'originalModules', 'sourceLock',
            'preparationReceipt', 'sourceInputArchive', 'sourceInputReceipt')}
        old.update(sourceSupplements={'header': 'exact'}, referenceInputs={'reference': 'exact'},
            cmakeOptions={'buildType': 'RelWithDebInfo'}, compilerExecutables={'gcc': 'exact'},
            serverSource={'commit': '1' * 40}, preparedStatementCountDeclared=52,
            executable=dict(bytes=10, sha256='2' * 64))
        new = copy.deepcopy(old); new['executable'] = dict(bytes=11, sha256='3' * 64)
        provider = {n: old[n] for n in ('originalBuild', 'originalModules')}
        provider['serverBuildSourceLock'] = old['sourceLock']
        result = source.correspondence(old, new, provider)
        self.assertEqual(result['originalRuntimeExecutable'], old['executable'])
        self.assertEqual(result['sourceObservationExecutable'], new['executable'])
        self.assertFalse(result['bitIdenticalExecutableClaimed']); self.assertFalse(result['originalNativeObjectsObserved'])
        new['executable'] = old['executable']; source.correspondence(old, new, provider)
        for key in ('sourceInputArchive', 'referenceInputs', 'cmakeOptions', 'compilerExecutables', 'preparationReceipt'):
            changed = copy.deepcopy(new); changed[key] = {'changed': True}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'source-contract-differs'):
                source.correspondence(old, changed, provider)

    def original(self):
        root = self.root / 'original'; root.mkdir()
        binding = dict(bytes=1, sha256='a' * 64)
        q = dict(scope='actual-native-arm64-isolated-server-source-rebuild', phase='complete', sourceLock=binding,
            originalBuild=binding, originalCompiledModules=binding, androidRuntimeQualified=False, gameplayQualified=False)
        for n in ('sourceCompanionComplete', 'isolatedSourceRebuildQualified', 'transitiveIncludeClosureProved',
                  'fullCompileObserved', 'noCompilerCacheUsed', 'fullBuildAndReferencesPassed', 'originalSelectionPreserved'): q[n] = True
        for n in ('configure', 'fullBuild', 'referenceBuild', 'install'): q[n] = dict(exitCode=0)
        qid = write(root / 'qualification.json', q)
        rows = source.isolated.write_source_archive(root / source.isolated.SOURCE_ARCHIVE,
            {'qualification/qualification.json': root / 'qualification.json'})
        archive = source.files.identity(root / source.isolated.SOURCE_ARCHIVE)
        seal = dict(scope='complete-isolated-server-source-rebuild-companion', archiveReadbackVerified=True,
            sourceCompanionComplete=True, isolatedSourceRebuildQualified=True, originalUnsealedReceiptsUnchanged=True,
            archive=dict(file=source.isolated.SOURCE_ARCHIVE, **archive), archiveFiles=rows, qualification=qid,
            sourceLock=binding, originalBuild=binding, originalCompiledModules=binding,
            androidRuntimeQualified=False, gameplayQualified=False)
        sid = write(root / 'sealed-source-receipt.json', seal)
        pin = dict(originalSourceQualification=dict(archive=archive, qualification=qid, receipt=sid),
                   serverBuildSourceLock=binding, originalBuild=binding, originalModules=binding)
        return root, pin, q, seal

    def test_original_three_program_source_triple_full_readback_does_not_rewrite_receipts(self):
        root, pin, q, sealed = self.original()
        before = source.inventory(root)
        self.assertEqual(source.verify_original(root, pin), sealed)
        self.assertEqual(source.inventory(root), before)
        path = root / source.isolated.SOURCE_ARCHIVE
        path.chmod(0o600); path.write_bytes(path.read_bytes()[:-4])
        with self.assertRaisesRegex(ValueError, 'seal-changed'): source.verify_original(root, pin)

    def test_positive_flags_cannot_replace_actual_zero_exit_build_records(self):
        root, pin, q, sealed = self.original()
        q['fullBuild']['exitCode'] = 1
        pin['originalSourceQualification']['qualification'] = write(root / 'qualification.json', q)
        sealed['qualification'] = pin['originalSourceQualification']['qualification']
        pin['originalSourceQualification']['receipt'] = write(root / 'sealed-source-receipt.json', sealed)
        with self.assertRaisesRegex(ValueError, 'original-full-build-required'): source.verify_original(root, pin)

    @unittest.skipUnless(shutil.which('git'), 'actual Git needed for committed recipe export')
    def test_recipe_export_reads_committed_blobs_and_refuses_supplied_worktree_mutation(self):
        git = self.root / 'git'; git.mkdir()
        rows = {'LICENSE': b'fixture license\n', 'sources.lock.json': b'{}\n', 'tools/build.py': b'import runtime.helper\n',
            'runtime/helper.py': b'VALUE=1\n', 'runtime/server/contract.json': b'{}\n', 'tests/reference.cpp': b'int source;\n',
            '.github/workflows/helper.yml': b'name: fixture\n', 'patches/server/patch.patch': b'retained patch\n'}
        for n, raw in rows.items(): write(git / n, raw)
        def command(*args): return subprocess.check_output(['git', *args], cwd=git, stderr=subprocess.PIPE)
        command('init', '-q'); command('add', '.')
        command('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        revision = command('rev-parse', 'HEAD').decode().strip()
        supplied = self.root / 'helper.yml'; write(supplied, rows['.github/workflows/helper.yml'])
        (git / 'tools/build.py').write_text('uncommitted')
        proof = source.export_recipes(git, revision, {'.github/workflows/helper.yml': supplied}, self.root / 'export')
        self.assertEqual(set(proof['files']), set(rows))
        self.assertEqual((self.root / 'export/tools/build.py').read_bytes(), rows['tools/build.py'])
        self.assertFalse((self.root / 'export/.git').exists())
        write(supplied, b'changed')
        with self.assertRaisesRegex(ValueError, 'not-exact-git-blob'):
            source.export_recipes(git, revision, {'.github/workflows/helper.yml': supplied}, self.root / 'bad')


if __name__ == '__main__': unittest.main()
