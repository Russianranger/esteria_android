"""Storage/real-child guards only; synthetic files do not qualify extraction."""
import errno
import fcntl
import hashlib
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from runtime import server_data_generation as data


class ServerDataGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store, self.game, self.tools = [self.root / name for name in ('store', 'game', 'tools')]
        self.generation = 'a' * 64
        self.import_root = self.game / 'generations' / self.generation
        (self.import_root / 'data').mkdir(parents=True)
        (self.import_root / 'complete').write_text('format=1\nclientBuild=12340\nrequest=' + self.generation + '\nsource=' + 'b' * 64 + '\n')
        (self.import_root / 'journal.tsv').write_text('private synthetic importer record\n')
        (self.game / 'current').write_text(self.generation + '\n')
        self.tools.mkdir()
        self.plan = {'scope': data.order.SCHEMA, 'priorityOrder': 'highest-first', 'effectiveLocale': 'enUS',
                     'configuredLocale': 'enUS', 'profile': data.PROFILE,
                     'providers': [{'rank': 0, 'kind': 'mpq', 'path': 'Data/common.MPQ', 'prefix': '',
                                    'bytes': 1, 'sha256': 'c' * 64}]}
        self.calls = []

    def generate(self, **kwargs):
        with patch.object(data, 'tools_verified', return_value='d' * 64), \
             patch.object(data.order, 'plan', return_value=self.plan):
            return data.generate(self.store, self.game, self.generation, self.tools, {}, 'enUS', **kwargs)

    def fake_execute(self, command, cwd, log, timeout, **kwargs):
        """Deliberately no extractor, MPQ, ARM64 or usable game data is executed."""
        name = Path(command[0]).name
        self.calls.append((name, list(command[1:])))
        if command[1:] == ['--esteria-order-capabilities']:
            log.write_bytes(data.CAPABILITY + b'\n')
            return
        log.write_text('synthetic storage fixture\n')
        if name == 'map_extractor':
            self.assertEqual(command[command.index('-e') + 1], '7')
            self.assertIn('--esteria-order', command)
            self.assertNotIn('-i', command)
            for name in ('maps', 'dbc', 'Cameras'):
                (cwd / name).mkdir()
            (cwd / 'maps/0000000.map').write_bytes(struct.pack('<4s10I', b'MAPS', 9, 12340, *([0] * 8)))
            (cwd / 'dbc/Map.dbc').write_bytes(struct.pack('<4s4I', b'WDBC', 0, 66, 264, 1) + b'\0')
            (cwd / 'Cameras/test.m2').write_bytes(b'MD20' + struct.pack('<I', 264))
        elif name == 'vmap4_extractor':
            self.assertIn('--esteria-order', command)
            self.assertNotIn('-d', command)
            (cwd / 'Buildings').mkdir()
            (cwd / 'Buildings/dir_bin').write_bytes(b'not real raw vector data')
        elif name == 'vmap4_assembler':
            self.assertTrue(Path(command[1], 'dir_bin').is_file())
            (cwd / 'vmaps/000.vmtree').write_bytes(b'VMAP_4.8')
        elif name == 'mmaps_generator':
            self.assertEqual(command[command.index('--threads') + 1], '1')
            self.assertIn('--silent', command)
            self.assertTrue((cwd / 'maps/0000000.map').is_file())
            self.assertTrue((cwd / 'vmaps/000.vmtree').is_file())
            (cwd / 'mmaps').mkdir()
            (cwd / 'mmaps/000.mmap').write_bytes(b'\0' * 28)
        else:
            self.fail(name)

    def test_completed_generation_repeat_does_not_execute_or_replan(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
            self.assertEqual(len(self.calls), 6)
            with patch.object(data.order, 'plan', side_effect=AssertionError('unnecessary provider rehash')):
                # The generation cache resolves before provider planning.
                with patch.object(data, 'tools_verified', return_value='d' * 64):
                    second = data.generate(self.store, self.game, self.generation, self.tools, {}, 'enUS')
        self.assertEqual(first, second)
        self.assertFalse(first['worldQualified'])
        self.assertFalse(first['gameplayQualified'])
        self.assertEqual(len(first['files']), 5)
        self.assertEqual((self.store / 'current').read_text(), first['generation'] + '\n')

    def test_interrupted_vmap_phase_reuses_only_completed_map_phase(self):
        prior = 'f' * 64 + '\n'
        self.store.mkdir(); (self.store / 'current').write_text(prior)
        def fail(command, cwd, log, timeout, **kwargs):
            if Path(command[0]).name == 'vmap4_extractor' and command[1:] != ['--esteria-order-capabilities']:
                (cwd / 'Buildings').mkdir(); (cwd / 'Buildings/dir_bin').write_text('partial')
                raise ValueError('interrupted raw vectors')
            self.fake_execute(command, cwd, log, timeout, **kwargs)
        with patch.object(data, 'execute', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'interrupted raw'):
                self.generate()
        self.assertEqual((self.store / 'current').read_text(), prior)
        initial_maps = sum(name == 'map_extractor' and '-e' in args for name, args in self.calls)
        with patch.object(data, 'execute', side_effect=self.fake_execute), \
             patch.object(data.order, 'plan', side_effect=AssertionError('cached provider order must be reused')):
            with patch.object(data, 'tools_verified', return_value='d' * 64):
                self.assertFalse(data.generate(self.store, self.game, self.generation, self.tools, {}, 'enUS')['worldQualified'])
        self.assertEqual(sum(name == 'map_extractor' and '-e' in args for name, args in self.calls), initial_maps)
        partial = list((self.store / 'staging').glob('*/raw-vmaps-*/data/Buildings/dir_bin'))
        self.assertTrue(any(path.read_bytes() == b'partial' for path in partial))

    def test_input_change_before_activation_preserves_current(self):
        self.store.mkdir(); (self.store / 'current').write_text('f' * 64 + '\n')
        def change(command, cwd, log, timeout, **kwargs):
            self.fake_execute(command, cwd, log, timeout, **kwargs)
            if Path(command[0]).name == 'mmaps_generator':
                (self.game / 'current').write_text('e' * 64 + '\n')
        with patch.object(data, 'execute', side_effect=change):
            with self.assertRaisesRegex(ValueError, 'no longer current'):
                self.generate()
        self.assertEqual((self.store / 'current').read_text(), 'f' * 64 + '\n')

    def test_completed_output_mutation_refused_before_reuse(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
            target = self.store / 'generations' / first['generation'] / 'data/dbc/Map.dbc'
            target.write_bytes(target.read_bytes()[:-1] + b'x')
            with self.assertRaisesRegex(ValueError, 'prepared server data changed'):
                self.generate()
        self.assertEqual(len(self.calls), 6)

    def test_changed_cached_preflight_is_refused(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
            path = self.store / 'generations' / first['generation'] / 'receipt.json'
            proof = data.document(path); proof['preflight'] = {'checks_passed': False}
            path.write_bytes(data.storage.encoded(proof))
            with self.assertRaisesRegex(ValueError, 'preflight changed'):
                self.generate()

    def test_completed_readonly_binding_requires_exact_input_selection(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
        generation = self.store / 'generations' / first['generation']
        self.assertEqual(data.verify_completed(generation, first['inputs']), first)
        selected = dict(first['inputs']); selected['toolSelectionSha256'] = 'e' * 64
        with self.assertRaisesRegex(ValueError, 'generation/source selection'):
            data.verify_completed(generation, selected)

    def test_retained_provider_projection_mutation_is_refused(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
        generation = self.store / 'generations' / first['generation']
        projection = generation / 'order.tsv'
        projection.write_bytes(projection.read_bytes()[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'provider order bytes'):
            data.verify_completed(generation)

    def test_fixed_guest_alias_requires_explicit_external_generation_binding(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
        alias = self.root / 'esteria-data'
        shutil.copytree(self.store / 'generations' / first['generation'], alias)
        with self.assertRaisesRegex(ValueError, 'generation identity'):
            data.verify_completed(alias)
        self.assertEqual(data.verify_completed(alias, first['inputs'], expected_generation=first['generation']), first)
        with self.assertRaisesRegex(ValueError, 'generation/source selection'):
            data.verify_completed(alias, first['inputs'], expected_generation='e' * 64)

    def test_cached_preflight_numeric_boolean_is_not_a_typed_pass(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
        generation = self.store / 'generations' / first['generation']
        path = generation / 'receipt.json'
        proof = data.document(path); proof['preflight']['checks_passed'] = 1
        path.write_bytes(data.storage.encoded(proof))
        with self.assertRaisesRegex(ValueError, 'preflight changed'):
            data.verify_completed(generation)

    def test_directory_count_and_unreadable_subtree_fail_closed(self):
        source = self.root / 'many'; source.mkdir()
        for number in range(3):
            (source / str(number)).mkdir()
        with patch.object(data, 'MAX_FILES', 2):
            with self.assertRaisesRegex(ValueError, 'entry bound'):
                data.inventory(source)
        real_scandir = os.scandir
        def denied(path):
            if Path(path) == source / '0':
                raise PermissionError('controlled unreadable subtree')
            return real_scandir(path)
        with patch.object(os, 'scandir', side_effect=denied):
            with self.assertRaises(PermissionError):
                data.inventory(source)
            with self.assertRaises(PermissionError):
                list(data.formats.files_bounded(source))

    def test_cancellation_and_lock_exclusion_leave_pointer_untouched(self):
        self.store.mkdir(); (self.store / 'current').write_text('f' * 64 + '\n')
        with (self.store / '.setup.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.generate()
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            with self.assertRaisesRegex(ValueError, 'import changed before server data activation|extraction inputs changed'):
                self.generate(cancelled=lambda: True)
        self.assertEqual((self.store / 'current').read_text(), 'f' * 64 + '\n')

    def test_stock_capability_cannot_start_conversion(self):
        def stock(command, cwd, log, timeout, **kwargs):
            log.write_text('stock extractor\n')
        with patch.object(data, 'execute', side_effect=stock):
            with self.assertRaisesRegex(ValueError, 'no stock fallback'):
                self.generate()
        self.assertFalse((self.store / 'current').exists())

    def test_unsafe_root_thread_and_selection_types_rejected(self):
        for threads in (0, 3, True, '1'):
            with self.assertRaisesRegex(ValueError, 'workers'):
                self.generate(threads=threads)
        with self.assertRaisesRegex(ValueError, 'tool selection'):
            data.tools_verified(self.tools, {'formatVersion': True})
        linked = self.root / 'linked'; linked.symlink_to(self.game, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            data.generate(self.store, linked, self.generation, self.tools, {}, 'enUS')

    def test_copy_fallback_preserves_bytes_and_symlink_inventory_rejected(self):
        source = self.root / 'source'; source.mkdir(); (source / 'file').write_bytes(b'private phase file')
        destination = self.root / 'copy'
        with patch.object(os, 'link', side_effect=OSError(errno.EPERM, 'Android hard link policy')):
            data.clone(source, destination)
        self.assertEqual(data.inventory(source), data.inventory(destination))
        (destination / 'link').symlink_to(source / 'file')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            data.inventory(destination)

    def test_real_host_child_bounded_logs_and_nonzero_failure(self):
        log = self.root / 'child.log'
        result = data.execute([sys.executable, '-c', 'import sys;sys.stdout.write("x"*(5<<20))'], self.root, log, 10)
        self.assertEqual(result['logBytesObserved'], 5 << 20)
        self.assertLess(log.stat().st_size, (4 << 20) + (257 << 10))
        with self.assertRaisesRegex(ValueError, 'extractor failed'):
            data.execute([sys.executable, '-c', 'raise SystemExit(7)'], self.root, self.root / 'failed.log', 10)

    def test_real_host_cancellation_reaps_process_group(self):
        marker = self.root / 'child.pid'
        script = 'import os,time;open(' + repr(str(marker)) + ',"w").write(str(os.getpid()));time.sleep(30)'
        began = time.monotonic()
        with self.assertRaisesRegex(ValueError, 'cancelled|interrupted'):
            data.execute([sys.executable, '-c', script], self.root, self.root / 'cancel.log', 10,
                         cancelled=lambda: marker.exists())
        self.assertLess(time.monotonic() - began, 5)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(marker.read_text()), 0)

    @unittest.skipUnless(hasattr(os, 'fork'), 'Linux process-group regression')
    def test_exited_leader_with_writing_descendant_cannot_bypass_deadline(self):
        script = ('import os\n'
                  'if os.fork(): os._exit(0)\n'
                  'while True: os.write(1,b"x"*65536)\n')
        began = time.monotonic()
        try:
            data.execute([sys.executable, '-c', script], self.root, self.root / 'descendant.log', 1)
        except ValueError as error:
            self.assertRegex(str(error), 'deadline|interrupted')
        # A drained pipe permits earlier successful group cleanup; either path
        # must be bounded and must retain only the bounded log, never the writer.
        self.assertLess(time.monotonic() - began, 5)
        self.assertLess((self.root / 'descendant.log').stat().st_size, (4 << 20) + (257 << 10))


if __name__ == '__main__':
    unittest.main()
