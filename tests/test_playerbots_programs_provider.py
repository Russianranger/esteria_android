"""Optional profile refusals and source authority; no Android execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import provider_playerbots_programs as provider


class OptionalProvider(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='optional-helper-provider-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.pin, self.pid, self.anchor, self.base = provider.load_pin()

    def test_actual_descriptor_keeps_original_three_and_only_fixed_helper_roles(self):
        original = copy.deepcopy(self.base); old = provider.stock.descriptor(self.base)
        result = provider.descriptor(self.pin, self.pid, self.base)
        self.assertEqual(self.base, original)
        self.assertEqual(provider.stock.descriptor(self.base), old)
        self.assertEqual(result['programNames'], list(provider.stock.PROGRAMS))
        self.assertEqual(result['programPairs'], old['programPairs'])
        self.assertEqual(result['sourceQualification'], old['sourceQualification'])
        self.assertEqual(result['debugArchive'], old['debugArchive'])
        self.assertEqual(result['archiveEntries'], 131)
        self.assertEqual(result['originalNoticeFiles'], 66)
        self.assertEqual(set(result['helperNoticeFiles']), {provider.measure.HELPER_NOTICE})
        for name, row in self.base['files'].items():
            self.assertEqual(provider.stock.identity(result['requiredFiles'][name]), provider.stock.identity(row))
        self.assertEqual({n for n, r in result['requiredFiles'].items() if r.get('elfMachine') == 183},
            {'bin/' + n for n in provider.stock.PROGRAMS} | {provider.measure.helper.HELPER})
        helper = result['playerbotsHelper']
        self.assertEqual(helper['sourceReceipt'], provider.stock.identity(helper['sourceQualification']['receipt']))
        self.assertFalse(helper['androidRuntimeQualified']); self.assertFalse(helper['playerbotsAiQualified'])
        self.assertEqual(result['inputLockSha256'], self.pid['sha256'])

    def check_modified(self, pin, reason):
        with patch.object(provider.modules, 'read_json', return_value=(pin, {})), \
                patch.object(provider.measure, 'load_anchor', return_value=(self.anchor, self.pin['helperSourceAnchor'], self.base)):
            with self.assertRaisesRegex(ValueError, reason): provider.load_pin()

    def test_stock_or_helper_source_anchor_changes_cannot_be_adopted(self):
        for name in ('originalStockInputLock', 'helperSourceAnchor'):
            changed = copy.deepcopy(self.pin); changed[name]['sha256'] = '0' * 64
            self.check_modified(changed, 'original-inputs-differ')
        changed = copy.deepcopy(self.pin); changed['helper']['executable']['sha256'] = '0' * 64
        self.check_modified(changed, 'original-inputs-differ')

    def test_original_member_mutation_or_extra_helper_role_is_rejected(self):
        changed = copy.deepcopy(self.pin); changed['files']['bin/worldserver']['sha256'] = '0' * 64
        self.check_modified(changed, 'original-126-or-helper-delta-changed')
        changed = copy.deepcopy(self.pin); changed['helperNames'].append('world-helper')
        self.check_modified(changed, 'closed-role-selection')
        changed = copy.deepcopy(self.pin); changed['programPairs']['playerbots-schema'] = {}
        self.check_modified(changed, 'stock-provenance-changed')

    def test_source_flags_cannot_enable_android_or_fake_unsealed_source(self):
        for key, value in (('sourceCompanionComplete', False), ('helperSourceCompanionComplete', False),
                           ('androidRuntimeQualified', True), ('productionActivated', True)):
            changed = copy.deepcopy(self.pin); changed[key] = value
            self.check_modified(changed, 'source-and-native-pin-required')

    def test_full_original_source_and_paired_debug_verification_cannot_be_skipped(self):
        root = self.root / 'sources'; root.mkdir()
        for name in ('stock-provider', 'playerbots-candidate', 'playerbots-source'): (root / name).mkdir()
        for name in ('playerbots-source-anchor.json', 'runtime-measurement.json'): (root / name).write_bytes(b'{}')
        with patch.object(provider.stock, 'verify', side_effect=ValueError('full-paired-debug-proof-required')) as stock, \
                patch.object(provider.measure.helper, 'verify') as helper:
            with self.assertRaisesRegex(ValueError, 'full-paired-debug-proof-required'):
                provider.verify_sources(root, self.pin, self.anchor)
        stock.assert_called_once_with(root / 'stock-provider'); helper.assert_not_called()

    def test_copy_rejects_changed_identity_and_symlink_without_touching_original(self):
        source = self.root / 'source'; source.write_bytes(b'exact')
        expected = provider.files.identity(source)
        provider.copy_file(source, self.root / 'copied', expected)
        self.assertEqual(source.read_bytes(), b'exact')
        changed = dict(expected, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'copy-input-changed'):
            provider.copy_file(source, self.root / 'refused', changed)
        link = self.root / 'link'; link.symlink_to(source)
        with self.assertRaises((ValueError, OSError)): provider.copy_file(link, self.root / 'refused-link')

    def test_existing_provider_output_is_retained_before_verifying_sources(self):
        roots = []
        for name in ('stock', 'helper', 'source', 'runtime'):
            root = self.root / name; root.mkdir(); roots.append(root)
        output = self.root / 'existing'; output.mkdir(); (output / 'retain').write_text('retain')
        with patch.object(provider.stock, 'verify') as stock:
            with self.assertRaisesRegex(ValueError, 'existing-or-overlapping-provider-output'):
                provider.build(*roots, output)
        stock.assert_not_called(); self.assertEqual((output / 'retain').read_text(), 'retain')

    def test_retained_measurement_rechecks_all_execution_flags_and_helper_source_tree_closure(self):
        q=dict(scope='measured-optional-playerbots-programs-profile-candidate', archive=self.pin['archive'],
            files=self.pin['files'], helperSourceAnchor=self.pin['helperSourceAnchor'],
            originalStockInputLock=self.pin['originalStockInputLock'],archiveReadbackVerified=True,
            originalThreeProgramBytesAndReceiptsUnchanged=True,originalHelperBuildAndSqlReceiptsUnchanged=True,
            helperSourceCompanionVerified=True)
        for name in ('androidProviderCreated','productionActivated','slotPromoted','newlyObservedExecutableInstalled',
                     'compilerExecuted','helperExecuted','sqlExecuted','androidRuntimeQualified',
                     'playerbotsAiQualified','worldserverQualified','gameplayQualified'):q[name]=False
        provider.validate_measurement(q,self.pin)
        root=self.root/'retained';root.mkdir()
        for name in ('stock-provider','playerbots-candidate','playerbots-source'):(root/name).mkdir()
        provider.copy_file(provider.measure.ANCHOR,root/'playerbots-source-anchor.json',self.pin['helperSourceAnchor'])
        for name in (provider.measure.source.SOURCE_ARCHIVE,provider.measure.source.RECEIPT):(root/'playerbots-source'/name).write_bytes(b'fixture')
        def write(value):(root/'runtime-measurement.json').write_text(json.dumps(value))
        notice=provider.stock.identity(self.pin['helperNoticeFiles'][provider.measure.HELPER_NOTICE])
        with patch.object(provider.stock,'verify',return_value={'TEST_ONLY_NO_QUALIFICATION':True}), \
                patch.object(provider.measure.helper,'verify',return_value={'helper':self.pin['helper']}), \
                patch.object(provider.measure,'verify_helper_sources',return_value=({},b'fixture',notice)):
            write(q);provider.verify_sources(root,self.pin,self.anchor)
            for key in ('sqlExecuted','productionActivated','newlyObservedExecutableInstalled'):
                changed=copy.deepcopy(q);changed[key]=True;write(changed)
                with self.subTest(key=key),self.assertRaisesRegex(ValueError,'exact-measured-candidate-required'):
                    provider.verify_sources(root,self.pin,self.anchor)
            write(q);(root/'playerbots-source/unrecorded').write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError,'helper-source-file-closure'):
                provider.verify_sources(root,self.pin,self.anchor)


if __name__ == '__main__': unittest.main()
