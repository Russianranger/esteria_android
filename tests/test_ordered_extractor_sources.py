"""Source closure/refusal tests; host compiler observations make no ARM claim."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import seal_ordered_extractor_sources as sources
from tests import test_ordered_extractor_dependencies as host_fixture


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists(): path.chmod(0o600)
    path.write_bytes(raw)
    return identity(raw)


class SourceGuards(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='ordered-source-guards-')
        self.addCleanup(directory.cleanup); self.root = Path(directory.name)

    def test_pending_input_pin_refuses_before_creating_output(self):
        pending = dict(formatVersion=1, scope='exact-ordered-server-data-tools-packaging-inputs',
                       state='pending-native-dependency-capture')
        with patch.object(sources, 'read_json', return_value=(pending, {})):
            with self.assertRaisesRegex(ValueError, 'measured-input-pin-required'):
                sources.seal(self.root/'absent', self.root/'absent2', self.root/'absent3',
                             self.root/'absent.md', self.root/'new'/'output')
        self.assertFalse((self.root/'new').exists())

    def test_inventory_requires_every_member_and_refuses_links_and_changes(self):
        directory = self.root/'inputs'; row = write(directory/'source.txt', b'exact source\n')
        sources.check_inventory(directory, {'source.txt': row})
        write(directory/'untracked', b'not selected')
        with self.assertRaisesRegex(ValueError, 'file-set'):
            sources.check_inventory(directory, {'source.txt': row})
        (directory/'untracked').unlink(); (directory/'source.txt').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'file-changed'):
            sources.check_inventory(directory, {'source.txt': row})
        (directory/'source.txt').unlink(); (directory/'source.txt').symlink_to('/etc/hostname')
        with self.assertRaises(ValueError): sources.check_inventory(directory, {'source.txt': row})

    def test_original_archive_full_readback_and_metadata_are_required(self):
        plain = self.root/'source.c'; plain.write_bytes(b'int retained_source;\n')
        archive = self.root/'source.tar.gz'
        rows = sources.isolated.write_source_archive(archive, {'source/source.c': plain})
        sources.extract_original(archive, rows, self.root/'extracted')
        self.assertEqual((self.root/'extracted/source/source.c').read_bytes(), plain.read_bytes())
        wrong = copy.deepcopy(rows); wrong['source/source.c']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'SHA-256|sha256|hash'):
            sources.extract_original(archive, wrong, self.root/'refused')
        self.assertFalse((self.root/'refused').exists())
        changed = self.root/'truncated.tar.gz'; changed.write_bytes(archive.read_bytes()[:-4])
        with self.assertRaises((ValueError, EOFError, OSError)):
            sources.extract_original(changed, rows, self.root/'truncated')

    def test_duplicate_json_keys_and_typed_identities_refuse(self):
        path = self.root/'bad.json'; path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, 'duplicate-json-key'): sources.read_json(path)
        with self.assertRaisesRegex(ValueError, 'invalid-file-identity'):
            sources.identity(dict(bytes=True, sha256='0'*64))

    def test_native_receipt_needs_false_source_scope_and_successful_second_build(self):
        payload = self.root/'payload'; payload.mkdir()
        q = dict(formatVersion=1, scope='native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups',
            phase='complete', integrationRevision='1'*40, targets=list(sources.TARGETS),
            network=dict(interfaces=['lo'], externalNetworkingAvailable=False))
        for flag in ('actualTargetCompileSucceeded', 'nativeOrderedLookupQualified', 'onlyRequestedToolsBuilt',
                     'compilerCacheDisabled', 'originalInputsUnchanged'): q[flag] = True
        for flag in sources.FALSE_FLAGS + ('globalServerPatchListChanged', 'serverProgramsReplaced',
                                          'isolatedFullServerRebuildQualified', 'proprietaryClientDataSupplied'): q[flag] = False
        for phase in ('configure', 'compile', 'syntheticLookupTests', *(t+'Capability' for t in sources.TARGETS)):
            q[phase] = dict(exitCode=0)
        for phase in ('environmentBefore', 'environmentAfter'): q[phase] = dict(relevantBuildEnvironmentMatched=True)
        def pin():
            row = write(payload/'ordered-build.json', json.dumps(q).encode())
            return dict(nativeBuild=dict(receipt=row, integrationRevision='1'*40))
        with self.assertRaisesRegex(ValueError, 'successful-target-build-required'):
            sources.verify_native(payload, pin())
        q['generatedMetadataStabilizationBuild'] = dict(exitCode=0); q['sourceCompanionComplete'] = True
        with self.assertRaisesRegex(ValueError, 'native-scope-or-gates'):
            sources.verify_native(payload, pin())

    def test_source_archive_writer_refuses_objects_and_disguised_elf(self):
        binary = self.root/'not-source.txt'; binary.write_bytes(b'\x7fELF' + b'\0'*64)
        with self.assertRaisesRegex(ValueError, 'elf-binary-in-complete-source'):
            sources.isolated.write_source_archive(self.root/'refused.tar.gz', {'prepared/source/header.h': binary})
        plain = self.root/'source.c'; plain.write_bytes(b'int source;\n')
        with self.assertRaisesRegex(ValueError, 'binary-or-asset-in-complete-source'):
            sources.isolated.write_source_archive(self.root/'object.tar.gz', {'prepared/source/compiled.o': plain})

    def test_current_sealing_recipe_mutation_refuses_after_archive_creation(self):
        current = self.root/'current-sealer'
        for name in sources.SEALING_RECIPES: write(current/name, ('synthetic creation '+name).encode())
        selected, recorded = sources.sealing_recipes(current, 'a'*40)
        self.assertEqual(set(selected), {'sealing-recipes/'+name for name in sources.SEALING_RECIPES})
        self.assertFalse(recorded['claimedToBeNativeBuildGitRecipes'])
        self.assertFalse(recorded['creationGitBlobClosureClaimed'])
        self.assertEqual(recorded['creationIntegrationRevision'], 'a'*40)
        sources.isolated.write_source_archive(self.root/'created.tar.gz', selected)
        sources.verify_sealing_recipes(selected, recorded)
        write(current/'tools/seal_ordered_extractor_sources.py', b'changed after archive write\n')
        with self.assertRaisesRegex(ValueError, 'sealing-recipe-changed-before-publication'):
            sources.verify_sealing_recipes(selected, recorded)
        self.assertFalse((self.root/'ordered-source-receipt.json').exists())
        with self.assertRaisesRegex(ValueError, 'creation-integration-revision'):
            sources.sealing_recipes(current, 'not-a-commit')

    def test_client_reference_readme_has_no_inferred_license_grant(self):
        raw = b'# Synthetic reference attribution\n'; path = self.root/'README.md'; path.write_bytes(raw)
        row = dict(identity(raw), file='README.md', gitMode='100644', clientRevision='1'*40,
                   gitBlob=hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest())
        pin = dict(clientPolicyReadme=row)
        audit = sources.verify_readme(path, pin)
        self.assertFalse(audit['rootLicenseFound']); self.assertFalse(audit['licenseGrantVerified'])
        self.assertFalse(audit['clientPolicyLicenseInferredFromServerLicense'])
        self.assertEqual(audit['applicablePolicyNoticeFiles'], [])
        row['gitBlob'] = '2'*40
        with self.assertRaisesRegex(ValueError, 'readme-blob-changed'): sources.verify_readme(path, pin)

    def test_recipe_closure_reads_committed_blobs_and_rejects_untracked_payload(self):
        git = self.root/'repository'; git.mkdir()
        selected = {'LICENSE': b'synthetic server license\n', 'sources.lock.json': b'{}\n',
            '.github/workflows/server-extractor-order.yml': b'name: synthetic\n',
            'runtime/server/extractor-order/EsteriaArchiveOrder.h': b'// header\n',
            'runtime/server/extractor-order/0001-explicit-ordered-providers.patch': b'patch text\n',
            'tools/build.py': b'from runtime import resource\n',
            'runtime/resource.py': b'VALUE = 1\n', 'runtime/server/build.lock.json': b'{}\n',
            'runtime/server/EXTRACTOR-ORDER.md': b'synthetic recipe documentation\n',
            'config/example.json': b'{}\n', 'tests/reference.cpp': b'int reference;\n',
            'tests/reference.cmake': b'# reference\n'}
        for name, raw in selected.items(): write(git/name, raw)
        # A historical public proof and unrelated content are deliberately not
        # imported as source recipes by the explicit selection rule.
        write(git/'runtime/evidence/proof.json', b'{}\n'); write(git/'unrelated.txt', b'outside rule\n')
        def command(*args):
            return subprocess.check_output(['git', *args], cwd=git, stderr=subprocess.PIPE)
        command('init', '-q'); command('add', '.')
        command('-c', 'user.name=Synthetic Fixture', '-c', 'user.email=fixture@example.invalid',
                'commit', '-qm', 'synthetic recipe closure')
        revision = command('rev-parse', 'HEAD').decode().strip()
        payload = self.root/'payload'; write(payload/'recipes/tools/build.py', selected['tools/build.py'])
        (git/'tools/build.py').write_bytes(b'working tree mutation must not be used\n')
        write(git/'tools/private-untracked.py', b'not committed\n')
        proof = sources.export_recipes(git, revision, payload, self.root/'export')
        self.assertEqual(set(proof['files']), set(selected))
        self.assertEqual((self.root/'export/tools/build.py').read_bytes(), selected['tools/build.py'])
        self.assertFalse((self.root/'export/.git').exists())
        write(payload/'recipes/tools/private-untracked.py', b'not committed\n')
        with self.assertRaisesRegex(ValueError, 'untracked-native-recipe'):
            sources.export_recipes(git, revision, payload, self.root/'bad-export')
        (payload/'recipes/tools/private-untracked.py').unlink()
        (payload/'recipes/tools/build.py').write_bytes(b'changed recipe\n')
        with self.assertRaisesRegex(ValueError, 'not-git-blob'):
            sources.export_recipes(git, revision, payload, self.root/'changed-export')


class OfflineReplayStaging(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='ordered-source-replay-')
        self.addCleanup(directory.cleanup); self.root = Path(directory.name); self.bundle = self.root/'bundle'
        original_files = {}
        for name, raw in {
            'inputs/source-inputs/server-engine-source-inputs.tar.gz': b'synthetic inner source archive',
            'inputs/source-inputs/source-inputs-receipt.json': b'{"synthetic":true}\n',
            'inputs/environment/package-list.json': b'{}\n',
            'inputs/supplements/modules/ModulesScriptLoader.h': b'// source supplement\n',
            'inputs/acquisition.json': b'{"synthetic":true}\n',
            'recipes/unneeded-reference.py': b'# retained original source\n'}.items():
            path = self.root/'original-files'/name; write(path, raw); original_files[name] = path
        archive = self.bundle/'original'/sources.ORIGINAL_ARCHIVE; archive.parent.mkdir(parents=True)
        inventory = sources.isolated.write_source_archive(archive, original_files)
        sealed = dict(archive=dict(file=sources.ORIGINAL_ARCHIVE, **sources.files.identity(archive)), archiveFiles=inventory)
        seal_id = write(self.bundle/'original/sealed-source-receipt.json', json.dumps(sealed).encode())
        native = {}
        for name, raw in {
            'original-inputs/sources.lock.json': b'{"synthetic-original-lock":true}\n',
            'build/environment-before.json': b'{"synthetic-original-env":true}\n',
            'client-policy/policy-source-receipt.json': b'{"synthetic-policy":true}\n',
            'client-policy/WoW/Source/Client.cpp': b'// synthetic client policy\n'}.items():
            native[name] = write(self.bundle/'ordered'/name, raw)
        recipes = {}
        for name in ('tools/build_ordered_extractors.py', 'tools/prepare_server_isolated_sources.py'):
            row = write(self.bundle/'integration'/name, b'raise RuntimeError("staging must never execute this source")\n')
            recipes[name] = dict(row, gitMode='100755')
        self.plan = sources.replay_plan(dict(integrationRevision='a'*40), sealed, seal_id, native, recipes)
        write(self.bundle/'replay-plan.json', json.dumps(self.plan).encode())
        self.namespace = {'__name__': 'offline_replay_fixture'}
        exec(compile(sources.replay_script(), 'prepare-replay.py', 'exec'), self.namespace)

    def test_standalone_stdlib_helper_stages_exact_acquired_policy_recipes_and_modes(self):
        output = self.root/'replay'
        with patch.object(subprocess, 'Popen', side_effect=AssertionError('staging must not execute a process')):
            receipt = self.namespace['prepare'](self.bundle, output)
        self.assertFalse(receipt['commandsExecuted']); self.assertFalse(receipt['nativeCompilationPerformed'])
        self.assertFalse(receipt['sourceCompanionComplete'])
        self.assertEqual(receipt['cwd'], str(output))
        self.assertEqual(set(sources.inventory(output/'acquired')), {
            'source-inputs/server-engine-source-inputs.tar.gz', 'source-inputs/source-inputs-receipt.json',
            'environment/package-list.json', 'supplements/modules/ModulesScriptLoader.h', 'acquisition.json'})
        self.assertEqual((output/'original-lock/sources.lock.json').read_bytes(),
                         (self.bundle/'ordered/original-inputs/sources.lock.json').read_bytes())
        self.assertEqual(set(sources.inventory(output/'policy_sources')), {
            'policy-source-receipt.json', 'WoW/Source/Client.cpp'})
        for row in self.plan['copies']:
            self.assertEqual(sources.files.identity(output/row['destination']), row['identity'])
            self.assertEqual((output/row['destination']).stat().st_mode & 0o777, row['mode'])
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertFalse((output/'base').exists()); self.assertFalse((output/'native').exists())
        prepare, native = receipt['commands']
        self.assertEqual(prepare['argv'], ['python3', 'integration/tools/prepare_server_isolated_sources.py',
            '--source-inputs', 'acquired/source-inputs', '--supplements', 'acquired/supplements',
            '--original-lock', 'original-lock/sources.lock.json', '--output', 'base'])
        self.assertEqual(native['argv'], ['python3', 'integration/tools/build_ordered_extractors.py', 'build',
            '--prepared', 'base', '--inputs', 'acquired', '--original-lock', 'original-lock/sources.lock.json',
            '--environment', 'environment/input.json', '--client-policy', 'policy_sources', '--output', 'native',
            '--integration-revision', 'a'*40])
        with self.assertRaisesRegex(ValueError, 'existing or overlapping'):
            self.namespace['prepare'](self.bundle, output)

    def test_changed_staging_input_and_path_escape_leave_no_published_replay(self):
        lock = self.bundle/'ordered/original-inputs/sources.lock.json'; old = lock.read_bytes()
        lock.write_bytes(b'changed exact old lock')
        with self.assertRaisesRegex(ValueError, 'changed replay staging input'):
            self.namespace['prepare'](self.bundle, self.root/'changed')
        self.assertFalse((self.root/'changed').exists()); lock.write_bytes(old)
        self.plan['copies'][0]['destination'] = '../escape.py'
        (self.bundle/'replay-plan.json').write_text(json.dumps(self.plan))
        with self.assertRaisesRegex(ValueError, 'unsafe replay path'):
            self.namespace['prepare'](self.bundle, self.root/'escaped')
        self.assertFalse((self.root/'escaped').exists()); self.assertFalse((self.root/'escape.py').exists())


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ninja'), 'actual host GCC and Ninja required')
class ActualHostObservationComposition(unittest.TestCase):
    def setUp(self):
        fixture = host_fixture.ActualHostDependencies(methodName='test_actual_built_units_project_system_and_generated_headers_are_closed')
        fixture.link_depfiles = True
        fixture.setUp(); self.addCleanup(fixture.doCleanups); self.fixture = fixture
        self.payload = fixture.root/'payload'
        self.observed_root = self.payload/'build/dependency-observation'
        self.observed_root.parent.mkdir(parents=True)
        self.receipt = fixture.observe(output=self.observed_root)
        self.observed, _ = sources.read_json(self.observed_root/'observation.json')
        write(self.payload/'build/compile_commands.json', fixture.commands.read_bytes())
        write(self.payload/'build/commands.json', json.dumps([dict(phase='configure', argv=[
            '/usr/bin/cmake', '-S', str(fixture.prepared/'source'), '-B', str(fixture.build)])]).encode())
        self.q = dict(targetSourceDependencies=self.receipt, compileCommands=sources.files.identity(fixture.commands),
            programs={name:sources.files.identity(fixture.build/name) for name in sources.TARGETS})
        self.pin = dict(nativeBuild=dict(dependencyObservation=self.receipt['outputFiles']['observation.json']))
        self.apin = dict(adaptedFiles={path.relative_to(fixture.prepared/'source').as_posix(): sources.files.identity(path)
            for path in fixture.prepared.glob('source/*.c')})
        self.after = sources.inventory(fixture.prepared)
        self.count = patch.object(sources, 'EXPECTED_OBJECTS', 3); self.count.start(); self.addCleanup(self.count.stop)
        self.machines = patch.object(sources, 'EXPECTED_MACHINES', [fixture.machine]); self.machines.start(); self.addCleanup(self.machines.stop)

    def verify(self):
        return sources.verify_observation(self.payload, self.q, self.pin, self.after, self.apin)

    def rebind_synthetic_observation(self):
        # Only test fixtures rebind their in-memory pins. Production load_pin
        # requires the measured native receipt and observation from its lock.
        raw = sources.dependencies.encoded(self.observed)
        self.pin['nativeBuild']['dependencyObservation'] = write(self.observed_root/'observation.json', raw)
        self.receipt['objectMetadataSha256'] = hashlib.sha256(
            sources.dependencies.encoded(self.observed['objects'])).hexdigest()
        self.receipt['linkMetadataSha256'] = hashlib.sha256(
            sources.dependencies.encoded(self.observed['links'])).hexdigest()
        self.receipt['outputFiles'] = sources.inventory(self.observed_root)

    def test_actual_host_observation_closes_project_generated_and_system_maps(self):
        proof = self.verify()
        self.assertEqual(proof['observation'], self.pin['nativeBuild']['dependencyObservation'])
        self.assertTrue(proof['observedObjectMetadataReadback'])
        self.assertFalse(proof['originalObjectBytesIndependentlyReadback'])
        self.assertFalse(proof['systemHeaderSourcesCopied'])
        self.assertEqual(proof['projectFiles'], self.observed['projectFiles'])
        self.assertEqual(self.receipt['objectElfMachines'], [self.fixture.machine])  # actual host fixture only
        self.assertFalse(self.receipt['sourceCompanionComplete'])
        self.assertTrue(proof['observedLinkMetadataReadback'])
        self.assertEqual(len(proof['links']), 2)
        self.assertFalse(proof['originalLinkInputBytesIndependentlyReadback'])

    def test_changed_header_or_missing_prepared_source_cannot_be_sealed(self):
        original = self.after['source/shared.h']; self.after['source/shared.h'] = identity(b'wrong header')
        with self.assertRaisesRegex(ValueError, 'project-source-changed'): self.verify()
        self.after['source/shared.h'] = original
        write(self.observed_root/'generated/generated.h', b'changed generated header')
        with self.assertRaisesRegex(ValueError, 'output-files-changed'): self.verify()

    def test_raw_graph_command_and_observation_must_agree(self):
        name = next(iter(self.observed['objects']))
        self.observed['objects'][name]['compileCommandSha256'] = '0'*64
        self.rebind_synthetic_observation()
        with self.assertRaisesRegex(ValueError, 'object-command-binding'): self.verify()

    def test_repeated_dependency_edges_retain_exact_raw_count(self):
        name, row = next(iter(self.observed['objects'].items()))
        path = self.observed_root/'ninja-deps.txt'; raw = path.read_text()
        records = sources.dependencies.parse_dependencies(raw)
        record = records[name]; lines = raw.splitlines(); start = next(i for i, line in enumerate(lines) if line.startswith(name+':'))
        lines[start] = lines[start].replace('#deps '+str(record['count'])+',', '#deps '+str(record['count']+1)+',')
        lines.insert(start+1+record['count'], '    '+record['dependencies'][0])
        write(path, ('\n'.join(lines)+'\n').encode())
        row['dependencies'].append(row['dependencies'][0]); row['dependencyCount'] += 1
        self.rebind_synthetic_observation()
        self.verify()

    def test_unknown_system_roots_and_uncompiled_adaptations_refuse(self):
        self.apin['adaptedFiles']['not-compiled.c'] = identity(b'selected but not compiled')
        with self.assertRaisesRegex(ValueError, 'not-compiled'): self.verify()
        del self.apin['adaptedFiles']['not-compiled.c']
        old = next(iter(self.observed['systemHeaders']))
        self.observed['systemHeaders']['/opt/unknown.h'] = self.observed['systemHeaders'].pop(old)
        for row in self.observed['objects'].values():
            row['dependencies'] = [v.replace('system:'+old, 'system:/opt/unknown.h') for v in row['dependencies']]
        self.rebind_synthetic_observation()
        with self.assertRaisesRegex(ValueError, 'system-header-root-differs'): self.verify()

    def test_original_false_scope_and_no_newer_dependency_gate_are_required(self):
        self.receipt['dependenciesNotNewerThanObject'] = False
        with self.assertRaisesRegex(ValueError, 'native-scope-or-gates'): self.verify()
        self.receipt['dependenciesNotNewerThanObject'] = True
        self.observed['sourceCompanionComplete'] = True; self.rebind_synthetic_observation()
        with self.assertRaisesRegex(ValueError, 'document-scope-differs'): self.verify()

    def test_ordered_wrapper_requires_both_selected_link_program_identities(self):
        self.receipt['observedLinks'] = 1
        with self.assertRaisesRegex(ValueError, 'link-count-differs'): self.verify()
        self.receipt['observedLinks'] = 2
        self.q['programs']['map_extractor'] = identity(b'changed selected executable')
        with self.assertRaisesRegex(ValueError, 'selected-link-programs-differ'): self.verify()


if __name__ == '__main__': unittest.main()
