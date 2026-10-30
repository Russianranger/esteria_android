"""Authenticated helper-source transfer and original-debug admission boundaries."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import qualify_playerbots_programs as qualification


class HelperProgramsQualification(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='helper-programs-qualification-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def fixture(self, *, extra=False, changed=False, symlink=False):
        anchor = copy.deepcopy(qualification.provider.load_pin()[2])
        members = {qualification.provider.measure.source.SOURCE_ARCHIVE: b'fixture-source-no-execution',
            qualification.provider.measure.source.RECEIPT: b'fixture-receipt-no-qualification'}
        for role, name in (('archive', qualification.provider.measure.source.SOURCE_ARCHIVE),
                            ('receipt', qualification.provider.measure.source.RECEIPT)):
            anchor[role] = dict(file=name, bytes=len(members[name]), sha256=hashlib.sha256(members[name]).hexdigest())
        archive = self.root / 'source.zip'
        with zipfile.ZipFile(archive, 'w') as out:
            for name, body in members.items():
                if changed and name.endswith('.json'): body = body[:-1] + b'X'
                info = zipfile.ZipInfo(name); info.external_attr = (0o120777 if symlink else 0o100444) << 16
                out.writestr(info, body)
            if extra: out.writestr('unrecorded.txt', b'foreign')
        anchor['artifact'] = dict(anchor['artifact'], **qualification.files.identity(archive))
        return anchor, archive, members

    def test_exact_transport_preserves_bytes_and_refuses_existing_destination(self):
        anchor, archive, members = self.fixture(); target = self.root / 'sources'
        qualification.extract_sources(archive, target, anchor)
        self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, members)
        with self.assertRaisesRegex(ValueError, 'existing-optional-programs-helper-sources-preserved'):
            qualification.extract_sources(archive, target, anchor)

    def test_unrecorded_member_or_symlink_refuses_before_destination(self):
        for key in ('extra', 'symlink'):
            with self.subTest(key=key):
                anchor, archive, _ = self.fixture(**{key: True}); target = self.root / key
                with self.assertRaises(ValueError): qualification.extract_sources(archive, target, anchor)
                self.assertFalse(target.exists()); archive.unlink()

    def test_changed_outer_or_selected_member_is_rejected(self):
        anchor, archive, _ = self.fixture(changed=True)
        with self.assertRaisesRegex(ValueError, 'member-hash-differs'):
            qualification.extract_sources(archive, self.root / 'changed-member', anchor)
        archive.unlink(); anchor, archive, _ = self.fixture(); anchor['artifact']['sha256'] = '0' * 64
        target = self.root / 'changed-outer'
        with self.assertRaisesRegex(ValueError, 'outer-identity-differs'):
            qualification.extract_sources(archive, target, anchor)
        self.assertFalse(target.exists())

    def test_full_original_source_and_debug_failure_precedes_output_or_new_provider(self):
        stock, inputs, target = self.root / 'stock', self.root / 'inputs', self.root / 'provider'
        stock.mkdir(); inputs.mkdir()
        pid = qualification.provider.load_pin()[1]
        (inputs / 'acquisition.json').write_text(json.dumps(dict(scope='exact-optional-playerbots-programs-helper-inputs',
            inputLock=pid, allSelectedBytesAndModesVerified=True)))
        with patch.object(qualification.provider.stock, 'verify', side_effect=ValueError('actual-full-source-debug-required')) as verify, \
                patch.object(qualification.provider, 'build') as build:
            with self.assertRaisesRegex(ValueError, 'actual-full-source-debug-required'):
                qualification.build(stock, inputs, target)
        verify.assert_called_once_with(stock / 'programs'); build.assert_not_called(); self.assertFalse(target.exists())

    def test_wrong_acquisition_selection_cannot_reach_original_provider(self):
        stock, inputs = self.root / 'stock', self.root / 'inputs'; stock.mkdir(); inputs.mkdir()
        (inputs / 'acquisition.json').write_text('{}')
        with patch.object(qualification.provider.stock, 'verify') as verify:
            with self.assertRaisesRegex(ValueError, 'acquisition-selection-differs'):
                qualification.build(stock, inputs, self.root / 'refused')
        verify.assert_not_called(); self.assertFalse((self.root / 'refused').exists())


if __name__ == '__main__': unittest.main()
