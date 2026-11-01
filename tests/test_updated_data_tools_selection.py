"""A native data update cannot silently reinterpret the frozen server cohort."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import select_updated_data_tools as update


class UpdatedDataToolsSelection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='data-update-selection-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.baseline_path = self.root / 'public.lock.json'
        self.baseline = {name: dict(bytes=10, sha256='a' * 64)
            for name in (*update.INPUTS, 'sources.lock.json', 'unaffected-programs.lock.json')}
        self.current = copy.deepcopy(self.baseline)
        for name in update.INPUTS: self.current[name] = dict(bytes=11, sha256='b' * 64)
        self.baseline_path.write_text(json.dumps(dict(selectedInputs=self.baseline)))
        native = self.root / update.NATIVE
        native.parent.mkdir(parents=True)
        native.write_bytes(b'test-only native input selection\n')
        self.source = {name: dict(bytes=12, sha256='c' * 64)
            for name in ('archive', 'receipt', 'nativeBuild', 'dependencyObservation')}
        self.qualify = mock.patch.object(update, 'current_qualification', return_value=self.source)
        self.qualification = self.qualify.start()
        self.addCleanup(self.qualify.stop)
        self.value = update.measure(self.baseline_path, self.current, self.root)

    def put(self, value=None):
        p = self.root / update.LOCK
        p.write_text(json.dumps(self.value if value is None else value))
        return p

    def test_equal_historical_selection_needs_no_update_or_native_claim(self):
        self.qualification.reset_mock()
        self.assertIsNone(update.selection(self.baseline_path, self.baseline, self.baseline, self.root))
        self.qualification.assert_not_called()
        self.assertFalse((self.root / update.LOCK).exists())

    def test_only_exact_measured_pair_is_selected(self):
        p = self.put()
        selected = update.selection(self.baseline_path, self.baseline, self.current, self.root)
        self.assertEqual(selected['selection'], update.files.identity(p))
        self.assertEqual(selected['baselineInputs'], {n: self.baseline[n] for n in update.INPUTS})
        self.assertEqual(selected['updatedInputs'], {n: self.current[n] for n in update.INPUTS})
        self.assertEqual(selected['orderedSourceQualification'], self.source)

    def test_missing_explicit_lock_and_partial_update_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'explicit-lock-required'):
            update.selection(self.baseline_path, self.baseline, self.current, self.root)
        partial = copy.deepcopy(self.current)
        partial[update.INPUTS[1]] = self.baseline[update.INPUTS[1]]
        self.put()
        with self.assertRaisesRegex(ValueError, 'only-two-measured-inputs'):
            update.selection(self.baseline_path, self.baseline, partial, self.root)

    def test_server_source_or_program_change_cannot_hide_in_data_update(self):
        self.put()
        for name in ('sources.lock.json', 'unaffected-programs.lock.json'):
            changed = copy.deepcopy(self.current)
            changed[name]['sha256'] = 'd' * 64
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'only-two-measured-inputs'):
                update.selection(self.baseline_path, self.baseline, changed, self.root)

    def test_baseline_native_qualification_and_extra_claim_mutations_are_refused(self):
        changes = [lambda v: v['baselineReleaseLock'].update(sha256='0' * 64),
            lambda v: v['updatedInputs'][update.INPUTS[0]].update(sha256='0' * 64),
            lambda v: v['nativeInputLock'].update(sha256='0' * 64),
            lambda v: v['orderedSourceQualification']['archive'].update(sha256='0' * 64),
            lambda v: v.update(extraProof=True),
            lambda v: v.update(androidRuntimeQualified=True),
            lambda v: v.update(oldPublicProviderReinterpreted=0),
            lambda v: v.update(formatVersion=True)]
        for change in changes:
            value = copy.deepcopy(self.value); change(value); self.put(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                update.selection(self.baseline_path, self.baseline, self.current, self.root)

    def test_current_native_qualification_is_required_each_time(self):
        self.put()
        self.qualification.side_effect = ValueError('unqualified-current-native-output')
        with self.assertRaisesRegex(ValueError, 'unqualified-current-native-output'):
            update.selection(self.baseline_path, self.baseline, self.current, self.root)

    def test_changed_native_input_and_symlink_lock_are_refused(self):
        p = self.put()
        native = self.root / update.NATIVE
        old = native.read_bytes(); native.write_bytes(b'changed\n')
        with self.assertRaises(ValueError):
            update.selection(self.baseline_path, self.baseline, self.current, self.root)
        native.write_bytes(old)
        stored = p.with_suffix('.retained'); p.rename(stored); p.symlink_to(stored)
        with self.assertRaises((ValueError, OSError)):
            update.selection(self.baseline_path, self.baseline, self.current, self.root)

    def test_ambiguous_and_nonfinite_selection_documents_are_refused(self):
        for raw in ('{"formatVersion":1,"formatVersion":1}', '{"claim":NaN}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError): update.document(raw)


if __name__ == '__main__': unittest.main()
