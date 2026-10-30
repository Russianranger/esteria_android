"""Actual host GCC/Ninja readback and refusal tests; no native ARM claim."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tests import test_ordered_extractor_dependencies as fixture
from tools import verify_target_dependency_observation as verify


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ninja'), 'actual host GCC and Ninja required')
class TargetObservation(unittest.TestCase):
    def setUp(self):
        self.host = fixture.ActualHostDependencies(methodName='test_actual_built_units_project_system_and_generated_headers_are_closed')
        self.host.setUp(); self.addCleanup(self.host.doCleanups)
        self.payload = self.host.root / 'payload'; root = self.payload / 'build'
        root.mkdir(parents=True)
        self.receipt = self.host.observe(output=root / 'dependency-observation')
        shutil.copyfile(self.host.commands, root / 'compile_commands.json')
        (root / 'commands.json').write_text(json.dumps([dict(phase='configure', argv=[
            '/usr/bin/cmake', '-S', str(self.host.prepared / 'source'), '-B', str(self.host.build)])]))
        self.prepared = {p.relative_to(self.host.prepared).as_posix(): verify.files.identity(p)
                         for p in self.host.prepared.rglob('*') if p.is_file()}
        self.observation_root = root / 'dependency-observation'
        self.observed = json.loads((self.observation_root / 'observation.json').read_text())
        self.kwargs = dict(targets=verify.dependencies.TARGETS, machines=(62,), expected_objects=2,
            observation_identity=self.receipt['outputFiles']['observation.json'],
            required_sources=('source/map_extractor.c', 'source/vmap4_extractor.c'))

    def check(self):
        return verify.verify(self.payload, self.receipt, self.prepared,
                             verify.files.identity(self.host.commands), **self.kwargs)

    def rebind(self):
        # Only synthetic fixture pins change. Production callers retain external
        # exact native receipt hashes and do not authenticate a rewritten input.
        path = self.observation_root / 'observation.json'; path.chmod(0o600)
        path.write_bytes(verify.dependencies.encoded(self.observed))
        self.receipt['outputFiles'] = {p.relative_to(self.observation_root).as_posix(): verify.files.identity(p)
                                     for p in self.observation_root.rglob('*') if p.is_file()}
        self.kwargs['observation_identity'] = self.receipt['outputFiles']['observation.json']
        self.receipt['objectMetadataSha256'] = hashlib.sha256(verify.dependencies.encoded(self.observed['objects'])).hexdigest()

    def test_actual_host_graph_is_rechecked_without_reading_original_objects(self):
        for path in self.host.build.glob('*.o'): path.unlink()
        result = self.check()
        self.assertTrue(result['observedObjectMetadataReadback'])
        self.assertFalse(result['originalObjectBytesIndependentlyReadback'])
        self.assertFalse(result['systemHeaderSourcesCopied'])
        self.assertEqual(result['projectFiles'], self.observed['projectFiles'])
        self.assertFalse(result['receipt']['sourceCompanionComplete'])

    def test_immutable_source_graph_and_required_units_are_enforced(self):
        self.prepared['source/shared.h'] = dict(bytes=0, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'project-source-changed'): self.check()
        self.prepared['source/shared.h'] = self.observed['projectFiles']['source/shared.h']
        self.kwargs['required_sources'] += ('source/not-built.c',)
        with self.assertRaisesRegex(ValueError, 'required-unit-not-compiled'): self.check()

    def test_repeated_raw_dependency_edges_preserve_actual_count(self):
        name, obj = next(iter(self.observed['objects'].items()))
        path = self.observation_root / 'ninja-deps.txt'; lines = path.read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(name + ':'))
        count = obj['dependencyCount']
        lines[start] = lines[start].replace('#deps ' + str(count) + ',', '#deps ' + str(count + 1) + ',')
        lines.insert(start + 1 + count, lines[start + 1])
        path.chmod(0o600); path.write_text('\n'.join(lines) + '\n')
        obj['dependencies'].append(obj['dependencies'][0]); obj['dependencyCount'] += 1
        self.rebind(); self.check()
        obj['dependencyCount'] -= 1; self.rebind()
        with self.assertRaisesRegex(ValueError, 'object-command-binding'): self.check()

    def test_command_object_machine_scope_and_exact_observation_are_not_inferred(self):
        original = copy.deepcopy(self.kwargs)
        self.kwargs['machines'] = (183,)
        with self.assertRaisesRegex(ValueError, 'native-scope-or-gates'): self.check()
        self.kwargs = original
        self.kwargs['observation_identity'] = dict(bytes=0, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'exact-identity-required'): self.check()
        self.kwargs = original
        name = next(iter(self.observed['objects']))
        self.observed['objects'][name]['compileCommandSha256'] = '0' * 64; self.rebind()
        with self.assertRaisesRegex(ValueError, 'object-command-binding'): self.check()

    def test_unknown_system_roots_and_extra_or_changed_output_refuse(self):
        (self.observation_root / 'extra').write_text('unaccounted')
        with self.assertRaisesRegex(ValueError, 'output-files-changed'): self.check()
        (self.observation_root / 'extra').unlink()
        old = next(iter(self.observed['systemHeaders']))
        self.observed['systemHeaders']['/opt/private/unknown.h'] = self.observed['systemHeaders'].pop(old)
        self.rebind()
        with self.assertRaisesRegex(ValueError, 'system-header-root-differs'): self.check()

    def test_copied_generated_file_and_false_scope_flags_are_required(self):
        self.receipt['dependenciesNotNewerThanObject'] = False
        with self.assertRaisesRegex(ValueError, 'native-scope-or-gates'): self.check()
        self.receipt['dependenciesNotNewerThanObject'] = True
        generated = self.observation_root / 'generated/generated.h'
        generated.chmod(0o600); generated.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'output-files-changed'): self.check()


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ninja'), 'actual host GCC and Ninja required')
class LinkedTargetObservation(unittest.TestCase):
    def setUp(self):
        self.base = TargetObservation(methodName='test_actual_host_graph_is_rechecked_without_reading_original_objects')
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        host = self.base.host
        path = host.build / 'build.ninja'
        text = path.read_text().replace('  command = ' + str(host.gcc) + ' $in -o $out',
            '  command = : && ' + str(host.gcc) + ' $in -Wl,--dependency-file=$out.d -o $out && :\n'
            '  depfile = $out.d\n  deps = gcc')
        path.write_text(text)
        for name in verify.dependencies.TARGETS: (host.build / name).unlink()
        subprocess.run([str(host.ninja), '-C', str(host.build), *verify.dependencies.TARGETS],
                       check=True, capture_output=True, timeout=30)
        self.base.payload = host.root / 'payload-linked'; root = self.base.payload / 'build'; root.mkdir(parents=True)
        self.base.receipt = host.observe(output=root / 'dependency-observation')
        shutil.copyfile(host.commands, root / 'compile_commands.json')
        (root / 'commands.json').write_text(json.dumps([dict(phase='configure', argv=[
            '/usr/bin/cmake', '-S', str(host.prepared / 'source'), '-B', str(host.build)])]))
        self.base.observation_root = root / 'dependency-observation'
        self.base.observed = json.loads((self.base.observation_root / 'observation.json').read_text())
        self.base.kwargs.update(observation_identity=self.base.receipt['outputFiles']['observation.json'],
            expected_links=2, required_link_programs={n: verify.files.identity(host.build / n)
                                                     for n in verify.dependencies.TARGETS})

    def test_actual_link_records_are_separate_and_selected_program_bytes_are_bound(self):
        proof = self.base.check()
        self.assertEqual(len(proof['links']), 2)
        self.assertTrue(proof['observedLinkMetadataReadback'])
        self.assertFalse(proof['originalLinkInputBytesIndependentlyReadback'])
        self.assertGreater(len(proof['systemLinkInputIdentities']), 0)
        self.assertEqual(len(proof['linkInputIdentities']), 2)
        name = next(iter(self.base.kwargs['required_link_programs']))
        self.base.kwargs['required_link_programs'][name] = dict(bytes=0, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'selected-link-programs-differ'): self.base.check()

    def rebind_links(self):
        self.base.receipt['linkMetadataSha256'] = hashlib.sha256(
            verify.dependencies.encoded(self.base.observed['links'])).hexdigest()
        self.base.rebind()

    def test_changed_link_command_and_local_object_or_system_root_refuse(self):
        name = next(iter(self.base.observed['links'])); row = self.base.observed['links'][name]
        before = row['linkCommandSha256']; row['linkCommandSha256'] = '0' * 64; self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'native-link-command-binding'): self.base.check()
        row['linkCommandSha256'] = before; self.rebind_links()
        local = next(iter(self.base.observed['linkInputs']))
        old_local = copy.deepcopy(self.base.observed['linkInputs'][local])
        self.base.observed['linkInputs'][local]['identity'] = dict(bytes=0, sha256='0' * 64); self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'local-link-object-differs'): self.base.check()
        self.base.observed['linkInputs'][local] = old_local
        old_system = next(iter(self.base.observed['systemLinkInputs']))
        self.base.observed['systemLinkInputs']['/opt/private/unapproved.so'] = self.base.observed['systemLinkInputs'].pop(old_system)
        self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'system-link-input-root-differs'): self.base.check()

    def test_repeated_raw_link_edges_preserve_the_recorded_count(self):
        name, row = next(iter(self.base.observed['links'].items()))
        path = self.base.observation_root / 'ninja-deps.txt'; lines = path.read_text().splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith(name + ':'))
        count = row['dependencyCount']
        lines[start] = lines[start].replace('#deps ' + str(count) + ',', '#deps ' + str(count + 1) + ',')
        lines.insert(start + 1 + count, lines[start + 1])
        path.chmod(0o600); path.write_text('\n'.join(lines) + '\n')
        row['dependencies'].append(row['dependencies'][0]); row['dependencyCount'] += 1
        self.rebind_links(); self.base.check()
        row['dependencyCount'] -= 1; self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'native-link-command-binding'): self.base.check()

    def test_missing_link_record_cannot_be_silently_discarded(self):
        self.base.receipt['observedLinks'] = 0
        with self.assertRaisesRegex(ValueError, 'link-count-differs'): self.base.check()
        self.base.receipt['observedLinks'] = 2
        self.base.observed['links'].pop(next(iter(self.base.observed['links'])))
        self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'link-count-or-metadata-differs'): self.base.check()

    def test_explicit_local_link_command_input_must_be_in_raw_record(self):
        path = self.base.observation_root / 'ninja-target-commands.txt'
        text = path.read_text(); target = verify.dependencies.TARGETS[0]
        # Change only the link command; keep the compiler command and native
        # raw dependency graph. The synthetic fixture then rebinds its own pin.
        lines = [line.replace(target + '.o', 'unobserved.o') if '-Wl,--dependency-file=' in line and
                 target + '.o' in line else line for line in text.splitlines()]
        path.chmod(0o600); path.write_text('\n'.join(lines) + '\n')
        commands = verify.dependencies.link_commands(path.read_text(), self.base.host.build)
        output = next(p for p in commands if p.name == target)
        self.base.observed['links'][output.relative_to(self.base.host.build).as_posix()]['linkCommandSha256'] = hashlib.sha256(
            verify.dependencies.encoded(commands[output]['argv'])).hexdigest()
        self.rebind_links()
        with self.assertRaisesRegex(ValueError, 'explicit-local-link-input-missing'): self.base.check()


if __name__ == '__main__': unittest.main()
