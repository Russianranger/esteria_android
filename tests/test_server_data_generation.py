"""Storage/real-child guards only; synthetic files do not qualify extraction."""
import errno
import fcntl
import hashlib
import io
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
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
        expected_cache = (self.import_root / 'data/Data/common.MPQ',) if name in data.PROGRAMS[:2] and \
            command[1:] != ['--esteria-order-capabilities'] else ()
        self.assertEqual(kwargs.get('cache_inputs'), expected_cache)
        if command[1:] == ['--esteria-order-capabilities']:
            log.write_bytes(data.CAPABILITY + b'\n')
            return
        log.write_text('synthetic storage fixture\n')
        if name == 'map_extractor':
            self.assertEqual(command[command.index('-e') + 1], '7')
            self.assertEqual(command[command.index('-o') + 1], '.')
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
            (cwd / 'mmaps').mkdir(exist_ok=True)
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

    def test_profiles_separate_data_reuse_and_stock_rejects_custom_overlay(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            stock = self.generate()
            custom = self.generate(content_profile='esteria-custom')
            self.assertNotEqual(stock['generation'], custom['generation'])
            self.assertEqual(stock['inputs']['contentProfile'], 'stock-3.3.5a')
            self.assertEqual(custom['inputs']['contentProfile'], 'esteria-custom')
        prior = (self.store / 'current').read_text()
        namespace = self.import_root / 'data/EsteriaServerData'; namespace.mkdir()
        (namespace / 'data').mkdir()
        (namespace / 'manifest.properties').write_text('format=1\nscope=esteria-user-supplied-server-data\nserverRevision=' +
            data.formats.SERVER_REVISION + '\nclientBuild=12340\nmode=overlay\nprovenance=user-supplied-format-checked\nclientProviderOrderSha256=none\n')
        with self.assertRaisesRegex(ValueError, 'custom server-data overlays require the Esteria profile'):
            self.generate()
        self.assertEqual((self.store / 'current').read_text(), prior)

    def test_helper_generation_changes_separate_stock_data_reuse(self):
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            first = self.generate()
            with patch.object(data, 'preparation_helper_generation', return_value='9' * 64):
                second = self.generate()
            self.assertNotEqual(first['generation'], second['generation'])
            self.assertEqual(second['inputs']['preparationHelperGeneration'], '9' * 64)

    @staticmethod
    def tile(payload=b'fixture-navmesh'):
        # Structural write-completion fixture, not a generated Detour mesh.
        return struct.pack('<4I', 0x4D4D4150, 7, 20, len(payload)) + b'\0' * 40 + payload

    def pause_navigation(self, command, cwd, log, timeout, **kwargs):
        self.fake_execute(command, cwd, log, timeout, **kwargs)
        if Path(command[0]).name == 'mmaps_generator':
            (cwd / 'mmaps/0000000.mmtile').write_bytes(self.tile())
            # Native shouldSkipTile accepts this header; our retry must remove
            # the truncated payload before giving that process the directory.
            (cwd / 'mmaps/0000001.mmtile').write_bytes(self.tile()[:57])
            raise data.world_io.PreparationPaused('controlled memory pause')

    def test_navigation_retry_keeps_finished_tiles_and_rebuilds_only_partial_output(self):
        events = []
        with patch.object(data, 'execute', side_effect=self.pause_navigation):
            for _ in range(3):
                with self.assertRaisesRegex(data.world_io.PreparationPaused, 'controlled memory pause'):
                    self.generate(progress=events.append)
                attempts = list((self.store / 'staging').glob('*/navigation-in-progress'))
                self.assertEqual(len(attempts), 1)
                self.assertFalse((self.store / 'current').exists())
        retained = attempts[0] / 'data/mmaps/0000000.mmtile'
        self.assertEqual(retained.read_bytes(), self.tile())
        def resume(command, cwd, log, timeout, **kwargs):
            if Path(command[0]).name == 'mmaps_generator':
                self.assertEqual((cwd / 'mmaps/0000000.mmtile').read_bytes(), self.tile())
                self.assertFalse((cwd / 'mmaps/0000001.mmtile').exists())
            self.fake_execute(command, cwd, log, timeout, **kwargs)
        with patch.object(data, 'execute', side_effect=resume):
            receipt = self.generate(progress=events.append)
        self.assertIn('extraction-navigation-resume-1-tiles', events)
        self.assertIn('extraction-reused-maps-dbc-cameras', events)
        self.assertEqual(sum(n == 'map_extractor' and '-e' in a for n, a in self.calls), 1)
        self.assertEqual(sum(n == 'vmap4_extractor' and '--esteria-order' in a for n, a in self.calls), 1)
        self.assertEqual(sum(n == 'vmap4_assembler' for n, _ in self.calls), 1)
        self.assertEqual(list((self.store / 'staging').iterdir()), [])
        self.assertFalse(receipt['worldQualified'])

    def test_reviewed_v8_staging_migrates_without_reextracting_completed_phases(self):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        old = next((self.store / 'staging').iterdir())
        # v8 used a new UUID attempt rather than the v9 deterministic slot.
        old_attempt = old / ('navigation-' + '1' * 32)
        (old / 'navigation-in-progress').rename(old_attempt)
        events = []
        def resume(command, cwd, log, timeout, **kwargs):
            if Path(command[0]).name == 'mmaps_generator':
                self.assertEqual((cwd / 'mmaps/0000000.mmtile').read_bytes(), self.tile())
            self.fake_execute(command, cwd, log, timeout, **kwargs)
        with patch.object(data, 'execute', side_effect=resume): receipt = self.generate(progress=events.append)
        self.assertIn('extraction-resumed-reviewed-v8-work', events)
        self.assertFalse(old.exists())
        self.assertEqual(sum(n == 'map_extractor' and '-e' in a for n, a in self.calls), 1)
        self.assertNotEqual(receipt['inputs']['preparationHelperGeneration'], data.V8_HELPER_GENERATION)

    def test_navigation_recovers_crash_before_data_directory_creation(self):
        with patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        attempt = next((self.store / 'staging').glob('*/navigation-in-progress'))
        shutil.rmtree(attempt / 'data')
        with patch.object(data, 'execute', side_effect=self.fake_execute): receipt = self.generate()
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')
        self.assertEqual(sum(n == 'map_extractor' and '-e' in a for n, a in self.calls), 1)

    def test_navigation_keeps_most_finished_legacy_attempt_and_discards_duplicates(self):
        with patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        work = next((self.store / 'staging').iterdir())
        selected = work / 'navigation-in-progress'
        older = work / ('navigation-' + '1' * 32)
        shutil.copytree(selected, older)
        (older / 'data/mmaps/0000002.mmtile').write_bytes(self.tile(b'second completed tile'))
        events = []
        def resume(command, cwd, log, timeout, **kwargs):
            if Path(command[0]).name == 'mmaps_generator':
                self.assertEqual((cwd / 'mmaps/0000002.mmtile').read_bytes(), self.tile(b'second completed tile'))
                self.assertFalse(older.exists())
                self.assertFalse((cwd / 'mmaps/0000001.mmtile').exists())
            self.fake_execute(command, cwd, log, timeout, **kwargs)
        with patch.object(data, 'execute', side_effect=resume): self.generate(progress=events.append)
        self.assertIn('extraction-navigation-resume-2-tiles', events)

    def test_navigation_symlink_checkpoint_never_touches_external_target(self):
        with patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        attempt = next((self.store / 'staging').glob('*/navigation-in-progress'))
        outside = self.root / 'keep'; outside.write_bytes(b'preserve me')
        (attempt / 'data/mmaps/0000003.mmtile').symlink_to(outside)
        with patch.object(data, 'execute', side_effect=self.fake_execute):
            with self.assertRaisesRegex(ValueError, 'symlink'): self.generate()
        self.assertEqual(outside.read_bytes(), b'preserve me')

    def test_successful_trim_preserves_unrecognized_staging_entries(self):
        marker = []
        def capture(command, cwd, log, timeout, **kwargs):
            self.fake_execute(command, cwd, log, timeout, **kwargs)
            if Path(command[0]).name == 'mmaps_generator':
                path = cwd.parent.parent / 'owner-note.txt'; path.write_bytes(b'keep unknown content'); marker.append(path)
        with patch.object(data, 'execute', side_effect=capture): receipt = self.generate()
        self.assertEqual(marker[0].read_bytes(), b'keep unknown content')
        self.assertEqual({p.name for p in marker[0].parent.iterdir()}, {'owner-note.txt'})
        self.assertTrue((self.store / 'generations' / receipt['generation'] / 'data/dbc/Map.dbc').exists())

    def test_reviewed_v8_completed_generation_migrates_without_children_or_replan(self):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.fake_execute): previous = self.generate()
        count = len(self.calls); events = []
        with patch.object(data, 'execute', side_effect=AssertionError('old complete output must be reused')), \
             patch.object(data.order, 'plan', side_effect=AssertionError('old provider order must be reused')):
            receipt = self.generate(progress=events.append)
        self.assertEqual(receipt['files'], previous['files'])
        self.assertNotEqual(receipt['generation'], previous['generation'])
        self.assertEqual(count, len(self.calls))
        self.assertIn('extraction-migrated-reviewed-v8-generation', events)
        self.assertFalse((self.store / 'generations' / previous['generation']).exists())
        self.assertFalse(receipt['worldQualified'])

    def test_reviewed_v8_migration_cleanup_can_retry_after_old_metadata_is_removed(self):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        old = next((self.store / 'staging').iterdir())
        (old / 'navigation-in-progress').rename(old / ('navigation-' + '2' * 32))
        (old / 'owner-note.txt').write_bytes(b'preserved unknown content')
        with patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        self.assertTrue(old.is_dir())
        self.assertFalse((old / 'order.json').exists())
        with patch.object(data, 'execute', side_effect=self.fake_execute): self.generate()
        self.assertEqual((old / 'owner-note.txt').read_bytes(), b'preserved unknown content')

    def test_completed_migration_retires_old_generation_after_interrupted_cleanup(self):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.fake_execute): previous = self.generate()
        old = self.store / 'generations' / previous['generation']
        real_retire = data._retire_v8_generation
        def interrupted(path, receipt):
            if path == old:
                (old / 'receipt.json').unlink()
                raise OSError('controlled interrupted old cleanup')
            return real_retire(path, receipt)
        with patch.object(data, '_retire_v8_generation', side_effect=interrupted):
            with self.assertRaisesRegex(OSError, 'controlled interrupted old cleanup'): self.generate()
        self.assertNotEqual((self.store / 'current').read_text(), previous['generation'] + '\n')
        with patch.object(data, 'execute', side_effect=AssertionError('verified v9 output must remain usable')):
            receipt = self.generate()
        self.assertFalse(old.exists())
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')

    def test_completed_v8_retirement_preserves_unknown_root_and_nested_entries(self):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.fake_execute): previous = self.generate()
        old = self.store / 'generations' / previous['generation']
        (old / 'owner-note.txt').write_bytes(b'preserve root note')
        real_retire = data._retire_v8_generation
        def add_unknown(path, receipt):
            (path / 'data/owner-note.txt').write_bytes(b'preserve nested note')
            return real_retire(path, receipt)
        with patch.object(data, '_retire_v8_generation', side_effect=add_unknown): receipt = self.generate()
        self.assertEqual((old / 'owner-note.txt').read_bytes(), b'preserve root note')
        self.assertEqual((old / 'data/owner-note.txt').read_bytes(), b'preserve nested note')
        self.assertFalse((old / 'receipt.json').exists())
        self.assertEqual({path.name for path in old.iterdir()}, {'data', 'owner-note.txt'})
        self.assertEqual({path.name for path in (old / 'data').iterdir()}, {'owner-note.txt'})
        with patch.object(data, 'execute', side_effect=AssertionError('verified v9 data remains usable')):
            self.assertEqual(self.generate(), receipt)

    def interrupt_migrated_order(self, *, completed):
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.fake_execute if completed else self.pause_navigation):
            if completed: previous = self.generate()['generation']
            else:
                with self.assertRaises(data.world_io.PreparationPaused): self.generate()
                old = next((self.store / 'staging').iterdir()); previous = old.name
                (old / 'navigation-in-progress').rename(old / ('navigation-' + '3' * 32))
        real_atomic = data.storage.atomic; interrupted = []
        def publish(path, raw):
            if path.name == 'order.json' and path.parent.parent == self.store / 'staging' and path.parent.name != previous:
                interrupted.append(path.parent)
                raise OSError('controlled interruption before migration JSON commit')
            return real_atomic(path, raw)
        with patch.object(data.storage, 'atomic', side_effect=publish):
            with self.assertRaisesRegex(OSError, 'controlled interruption before migration JSON commit'): self.generate()
        self.assertEqual(len(interrupted), 1)
        self.assertTrue((interrupted[0] / 'order.tsv').is_file())
        self.assertFalse((interrupted[0] / 'order.json').exists())
        with patch.object(data, 'execute', side_effect=self.fake_execute): receipt = self.generate()
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')

    def test_staging_migration_commits_wire_before_json_and_recovers_interruption(self):
        self.interrupt_migrated_order(completed=False)

    def test_completed_migration_commits_wire_before_json_and_recovers_interruption(self):
        self.interrupt_migrated_order(completed=True)

    def test_reviewed_v8_mutated_phase_is_refused_and_prior_pointer_preserved(self):
        self.store.mkdir(); (self.store / 'current').write_text('f' * 64 + '\n')
        with patch.object(data, 'preparation_helper_generation', return_value=data.V8_HELPER_GENERATION), \
             patch.object(data, 'execute', side_effect=self.pause_navigation):
            with self.assertRaises(data.world_io.PreparationPaused): self.generate()
        old = next((self.store / 'staging').iterdir())
        (old / 'maps-dbc-cameras-complete/data/dbc/Map.dbc').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'completed extraction phase changed'): self.generate()
        self.assertEqual((self.store / 'current').read_text(), 'f' * 64 + '\n')

    def test_navigation_progress_is_numeric_bounded_throttled_and_split_safe(self):
        rows = []; clock = [0]
        progress = data.NavigationProgress(emit=rows.append, clock=lambda: clock[0])
        progress.feed(b'10% [Map 0000] Building ti')
        progress.feed(b'le [12,34]\n')
        progress.feed(b'11% [Map 0000] Building tile [13,34]\n')
        self.assertEqual(rows, [dict(percent=10, map=0, tileX=12, tileY=34)])
        clock[0] = 3
        progress.feed(b'/private/path 80% [Map 0001] Building tile [12,34]\n')
        progress.feed(b'x' * 10000 + b'\n101% [Map 0000] Building tile [12,34]\n')
        progress.feed(b'20% [Map 0000] Building tile [99,34]\n')
        progress.feed(b'20% [Map 0001] Building tile [12,34]\n')
        self.assertEqual(rows[-1], dict(percent=20, map=1, tileX=12, tileY=34))
        self.assertEqual(len(rows), 2)
        self.assertLessEqual(len(progress.pending), 256)

    def test_real_host_fixture_progress_relay_drops_raw_paths(self):
        executable = self.root / 'mmaps_generator'
        executable.write_text('#!' + sys.executable + '\n' +
            'print("/private/owner/path 19% [Map 0000] Building tile [12,34]")\n' +
            'print("20% [Map 0000] Building tile [12,34]")\n')
        executable.chmod(0o700); observed = io.StringIO()
        with redirect_stdout(observed):
            result = data.execute([str(executable)], self.root, self.root / 'native-fixture.log', 10)
        self.assertEqual(result['exitStatus'], 0)
        self.assertEqual(observed.getvalue(), 'NAVIGATION_PROGRESS {"percent":20,"map":0,"tileX":12,"tileY":34}\n')
        # Real owned host process only. This executes no shipped ARM64 code.

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
        partial = list((self.store / 'staging').glob('*/raw-vmaps-*/data/Buildings/dir_bin'))
        self.assertTrue(any(path.read_bytes() == b'partial' for path in partial))
        self.assertEqual((self.store / 'current').read_text(), prior)
        initial_maps = sum(name == 'map_extractor' and '-e' in args for name, args in self.calls)
        with patch.object(data, 'execute', side_effect=self.fake_execute), \
             patch.object(data.order, 'plan', side_effect=AssertionError('cached provider order must be reused')):
            with patch.object(data, 'tools_verified', return_value='d' * 64):
                self.assertFalse(data.generate(self.store, self.game, self.generation, self.tools, {}, 'enUS')['worldQualified'])
        self.assertEqual(sum(name == 'map_extractor' and '-e' in args for name, args in self.calls), initial_maps)
        self.assertEqual(list((self.store / 'staging').iterdir()), [])

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

    def test_long_private_phase_uses_short_output_in_existing_data_cwd(self):
        self.store = self.root / 'private-runtime-state' / ('s' * 64) / 'server-data'
        observed = []
        def capture(command, cwd, log, timeout, **kwargs):
            if Path(command[0]).name == 'map_extractor' and '-e' in command:
                # Exercise the actual generation/phase path, including the
                # 64-byte generation and fresh UUID, rather than a short fixture.
                self.assertGreater(len(os.fsencode(cwd)), 127)
                self.assertEqual(cwd.name, 'data')
                self.assertTrue(cwd.is_dir())
                self.assertFalse(cwd.is_symlink())
                self.assertEqual(cwd.parent.parent.parent, self.store / 'staging')
                output = command[command.index('-o') + 1]
                self.assertEqual(output, '.')
                self.assertFalse(Path(output).is_absolute())
                self.assertEqual((cwd / output).resolve(), cwd.resolve())
                observed.append(cwd)
            self.fake_execute(command, cwd, log, timeout, **kwargs)
        with patch.object(data, 'execute', side_effect=capture):
            receipt = self.generate()
        self.assertEqual(len(observed), 1)
        self.assertEqual(list((self.store / 'staging').iterdir()), [])
        completed = self.store / 'generations' / receipt['generation'] / 'data'
        self.assertTrue((completed / 'dbc/Map.dbc').is_file())
        self.assertEqual((self.store / 'current').read_text(), receipt['generation'] + '\n')
        # Format-only synthetic storage coverage; no native conversion claim.
        self.assertFalse(receipt['worldQualified'])
        self.assertFalse(receipt['gameplayQualified'])

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
