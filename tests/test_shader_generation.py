"""Synthetic generation/storage guards; these do not qualify game shader translation."""
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from runtime import stock_shader_generation as shaders


def output(root):
    blocks = []
    for kind, model, digest, profile in [('vertex', 0, '1' * 32, 'vs_3_0'),
                                         ('pixel', 4, '2' * 32, 'ps_3_0')]:
        (root / kind).mkdir(exist_ok=True)
        # Deliberately structural-only SPIR-V, not a semantically valid shader.
        raw = struct.pack('<10I', 0x07230203, 0x10000, 0, 3, 0, (5 << 16) | 15,
                          model, 1, 0x6e69616d, 0)
        (root / kind / (digest + '.spv')).write_bytes(raw)
        blocks.append(f'record {digest} {kind} {profile} {kind}/{digest}.spv vconst=64 pconst=20\nname Fixture:0\n')
    (root / 'manifest.txt').write_text('\n'.join(blocks))
    (root / 'index.txt').write_text('# synthetic storage fixture\n')


class ShaderGenerationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.game, self.store, self.tools = [self.root / x for x in ('game', 'store', 'tools')]
        self.generation, self.revision = 'a' * 64, 'b' * 40
        at = self.game / 'generations' / self.generation
        (at / 'data').mkdir(parents=True)
        (at / 'complete').write_text('format=1\nclientBuild=12340\nrequest=' + self.generation + '\nsource=' + 'c' * 64 + '\n')
        (at / 'journal.tsv').write_text('bounded private importer journal\n')
        (self.game / 'current').write_text(self.generation + '\n')
        self.tools.mkdir()
        for name in shaders.TOOL_FILES:
            path = self.tools / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# synthetic tool; never run for positive generation\n')
        os.chmod(self.tools / 'bin/glslangValidator', 0o700)
        self.write_tools()

    def write_tools(self):
        (self.tools / 'shader-tools.json').write_bytes(shaders.encoded({
            'formatVersion': 1, 'clientRevision': self.revision,
            'files': {name: shaders.identity(self.tools / name, 64 << 20) for name in shaders.TOOL_FILES}}))

    def run_generation(self):
        return shaders.generate(self.store, self.game, self.generation, self.tools, self.revision, 'enUS')

    def fake_execute(self, command, log, timeout):
        self.assertIn('--strict', command)
        self.assertNotIn('--deploy', command)
        self.assertEqual(command[command.index('--client') + 1], str(self.game / 'generations' / self.generation / 'data'))
        output(Path(command[command.index('--out') + 1]))
        log.write_text('synthetic storage fixture, no compiler or game shaders\n')

    def test_generation_repeat_and_no_input_mutation(self):
        source = self.game / 'generations' / self.generation / 'data/common.MPQ'
        source.write_bytes(b'unopened-storage-fixture')
        before = source.read_bytes()
        with patch.object(shaders, 'execute', side_effect=self.fake_execute) as run:
            receipt = self.run_generation()
            self.assertEqual(self.run_generation(), receipt)
            self.assertEqual(run.call_count, 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(receipt['graphicsQualified'])
        self.assertFalse(receipt['gameplayQualified'])
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')

    def test_android_active_coordinator_uses_owned_child_adapter_and_cache_inputs(self):
        from runtime import shader_generation as frozen
        original = frozen.identity, frozen.execute
        source = self.game / 'generations' / self.generation / 'data/Data/common.MPQ'
        source.parent.mkdir()
        source.write_bytes(b'immutable synthetic cache input')
        fixture = self.root / 'compiled-fixture'
        fixture.mkdir()
        output(fixture)
        adapter = self.root / 'fixture-adapter.py'
        adapter.write_text('import pathlib,shutil,sys\n'
            'source=pathlib.Path(__file__).with_name("compiled-fixture")\n'
            'target=pathlib.Path(sys.argv[sys.argv.index("--out")+1])\n'
            'assert "--android-low-memory" in sys.argv\n'
            'shutil.copytree(source,target,dirs_exist_ok=True)\n'
            'print("synthetic guarded child fixture; no compiler or game shaders")\n')
        policy = shaders.world_io.android_policy
        with patch.object(shaders, 'TRANSLATION_ADAPTER', adapter), \
                patch.object(shaders, 'execute', wraps=shaders.world_io.shader_execute) as execute, \
                patch.object(shaders.world_io, 'android_policy',
                    side_effect=lambda: policy(memory_probe=lambda: 4 << 30)):
            receipt = shaders.generate(self.store, self.game, self.generation, self.tools, self.revision,
                'enUS', android_low_memory=True)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.kwargs['cache_inputs'], (source,))
        self.assertIn('--android-low-memory', execute.call_args.args[0])
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')
        self.assertEqual((frozen.identity, frozen.execute), original)
        self.assertFalse(shaders.world_io.enabled())

    def test_content_profile_separates_reuse_identity_and_rejects_unknown_profiles(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute) as run:
            stock = self.run_generation()
            custom = shaders.generate(self.store, self.game, self.generation, self.tools, self.revision, 'enUS', content_profile='esteria-custom')
            self.assertNotEqual(stock['generation'], custom['generation'])
            self.assertEqual(stock['inputs']['contentProfile'], 'stock-3.3.5a')
            self.assertEqual(custom['inputs']['contentProfile'], 'esteria-custom')
            self.assertEqual(self.run_generation(), stock)
            self.assertEqual(run.call_count, 2)
        with self.assertRaisesRegex(shaders.ShaderError, 'unsupported content profile'):
            shaders.generate(self.store, self.game, self.generation, self.tools, self.revision, 'enUS', content_profile='stock-unknown')

    def test_wrapper_source_changes_prevent_reusing_a_prior_shader_generation(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute) as run:
            first = self.run_generation()
            changed = self.root / 'changed-wrapper.py'; changed.write_text('# changed owned coordinator fixture\n')
            with patch.object(shaders, '__file__', str(changed)):
                second = self.run_generation()
            self.assertNotEqual(first['generation'], second['generation'])
            self.assertNotEqual(first['inputs']['preparationHelperSha256'], second['inputs']['preparationHelperSha256'])
            self.assertEqual(run.call_count, 2)

    def test_adapter_only_changes_invalidate_reuse_without_changing_provider_bytes(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute) as run:
            first = self.run_generation()
            changed = self.root / 'changed-adapter.py'; changed.write_text('# synthetic adapter change\n')
            with patch.object(shaders, 'TRANSLATION_ADAPTER', changed):
                second = self.run_generation()
            self.assertNotEqual(first['generation'], second['generation'])
            self.assertEqual(first['inputs']['preparationHelperSha256'], second['inputs']['preparationHelperSha256'])
            self.assertNotEqual(first['inputs']['preparationHelperFiles'], second['inputs']['preparationHelperFiles'])
            self.assertEqual(run.call_count, 2)

    def test_transient_pressure_preserves_previous_generation_and_retry_is_not_poisoned(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute):
            first = self.run_generation()
        (self.tools / 'bls/emitter.py').write_text('# synthetic new source identity\n')
        self.write_tools()
        with patch.object(shaders, 'execute', side_effect=shaders.world_io.PreparationPaused()):
            with self.assertRaises(shaders.world_io.PreparationPaused):
                self.run_generation()
        self.assertEqual((self.store / 'current').read_text(), first['generation'] + '\n')
        self.assertFalse(list((self.store / 'staging').rglob('receipt.json')))
        with patch.object(shaders, 'execute', side_effect=self.fake_execute):
            second = self.run_generation()
        self.assertNotEqual(first['generation'], second['generation'])
        self.assertEqual((self.store / 'current').read_text(), second['generation'] + '\n')

    def test_main_returns_distinct_pause_without_turning_it_into_failure(self):
        arguments = ['stock_shader_generation.py', '--store', str(self.store), '--game', str(self.game),
            '--tools', str(self.tools), '--generation', self.generation, '--client-revision', self.revision,
            '--locale', 'enUS', '--android-low-memory']
        with patch.object(sys, 'argv', arguments), patch.object(shaders, 'generate', side_effect=shaders.world_io.PreparationPaused()), \
                patch.object(shaders.world_io, 'print_pause') as marker:
            self.assertEqual(shaders.main(), shaders.world_io.PAUSED_EXIT_CODE)
            marker.assert_called_once()
        self.assertFalse(self.store.exists())

    def test_failed_or_changed_inputs_keep_previous_generation(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute):
            first = self.run_generation()
        source = self.tools / 'bls/emitter.py'
        source.write_text('# changed synthetic source\n')
        self.write_tools()
        def changed(command, log, timeout):
            self.fake_execute(command, log, timeout)
            (self.game / 'current').write_text('d' * 64 + '\n')
        with patch.object(shaders, 'execute', side_effect=changed), self.assertRaises(shaders.ShaderError):
            self.run_generation()
        self.assertEqual((self.store / 'current').read_text(), first['generation'] + '\n')
        self.assertTrue((self.store / 'generations' / first['generation'] / 'receipt.json').exists())
        self.assertEqual(len(list((self.store / 'staging').iterdir())), 1)

    def test_partial_output_never_activates(self):
        for corruption in ('refused', 'missing', 'truncated', 'wrong-stage', 'extra', 'companion'):
            with self.subTest(corruption=corruption):
                root = self.root / corruption
                root.mkdir()
                output(root)
                vertex = root / 'vertex' / ('1' * 32 + '.spv')
                if corruption == 'refused':
                    with (root / 'manifest.txt').open('a') as stream:
                        stream.write('# Refused (not translated):\n')
                elif corruption == 'missing':
                    vertex.unlink()
                elif corruption == 'truncated':
                    vertex.write_bytes(vertex.read_bytes()[:-1])
                elif corruption == 'wrong-stage':
                    raw = bytearray(vertex.read_bytes());struct.pack_into('<I', raw, 24, 4);vertex.write_bytes(raw)
                elif corruption == 'extra':
                    (root / 'unexpected.bin').write_bytes(b'no')
                else:
                    text = (root / 'manifest.txt').read_text().replace('name Fixture:0', 'companion ' + '3' * 32, 1)
                    (root / 'manifest.txt').write_text(text)
                with self.assertRaises(shaders.ShaderError):
                    shaders.validate_output(root)

    def test_private_tool_closure_and_receipt_rebinding(self):
        for relative in ('json.py', 'bls/__pycache__/archive.cpython-311.pyc'):
            path = self.tools / relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'unlisted')
            with self.assertRaises(shaders.ShaderError):
                shaders.tool_identity(self.tools, self.revision)
            path.unlink()
            if '__pycache__' in relative:
                path.parent.rmdir()
        with self.assertRaises(shaders.ShaderError):
            shaders.tool_identity(self.tools, 'd' * 40)
        target = self.tools / 'bls/archive.py'
        target.unlink();target.symlink_to(self.tools / 'bls/emitter.py')
        with self.assertRaises(shaders.ShaderError):
            shaders.tool_identity(self.tools, self.revision)

    def test_completed_import_ancestry_rejects_cycle_and_build_mismatch(self):
        at = self.game / 'generations' / self.generation
        (at / 'base-ready').write_text(self.generation + '\n')
        with self.assertRaises(shaders.ShaderError):
            shaders.imported(self.game, self.generation)
        (at / 'base-ready').unlink()
        receipt = at / 'complete'
        receipt.write_text(receipt.read_text().replace('12340', '12341'))
        with self.assertRaises(shaders.ShaderError):
            shaders.imported(self.game, self.generation)

    def test_cached_receipt_cannot_overclaim_or_hide_modified_module(self):
        with patch.object(shaders, 'execute', side_effect=self.fake_execute):
            original = self.run_generation()
        folder = self.store / 'generations' / original['generation']
        receipt = folder / 'receipt.json'
        value = json.loads(receipt.read_bytes());value['graphicsQualified'] = True
        receipt.write_bytes(shaders.encoded(value))
        with self.assertRaises(shaders.ShaderError):
            self.run_generation()
        receipt.write_bytes(shaders.encoded(original))
        vertex = folder / 'shaders/vertex' / ('1' * 32 + '.spv')
        vertex.write_bytes(vertex.read_bytes()[:-4])
        with self.assertRaises(shaders.ShaderError):
            self.run_generation()

    def test_real_subprocess_failure_timeout_and_capped_output(self):
        cases = [('failure', 'raise SystemExit(7)', 2),
                 ('timeout', 'import time; time.sleep(10)', .1),
                 ('overflow', "import os; data=b'x'*65536\nfor _ in range(160): os.write(1,data)", 4)]
        for name, program, timeout in cases:
            with self.subTest(name=name), self.assertRaises(shaders.ShaderError):
                shaders.execute([sys.executable, '-c', program], self.root / (name + '.log'), timeout)
            self.assertLessEqual((self.root / (name + '.log')).stat().st_size, 8 << 20)

    def test_actual_cleanup_keeps_leader_unreaped_until_group_stop(self):
        real_stop = os.killpg
        def retained(pid, signal):
            state = os.waitid(os.P_PID, pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            self.assertIsNotNone(state)
            self.assertEqual(state.si_pid, pid)
            self.assertEqual(state.si_status, 0)
            real_stop(pid, signal)
        with patch.object(shaders.os, 'killpg', side_effect=retained) as stop:
            shaders.execute([sys.executable, '-c', "print('finished')"], self.root / 'success.log', 2)
        self.assertEqual(stop.call_count, 1)
        self.assertEqual((self.root / 'success.log').read_text(), 'finished\n')


if __name__ == '__main__':
    unittest.main()
