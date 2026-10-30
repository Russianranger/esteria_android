import copy
import unittest
from tools.verify_protocol import APPROVED, parse_fields, verify


def fixture():
    rows = ['ITEM_END = 64,', 'CONTAINER_FIELD_SLOT_1 = ITEM_END + 2, // Size: 508',
            'CONTAINER_END = ITEM_END + 510,', 'UNIT_END = 148,']
    descriptors = []
    for slot in range(25):
        name = f'PLAYER_QUEST_LOG_{slot + 1}_1'
        offset = 148 + slot * 5
        rows.append(f'{name} = UNIT_END + {slot * 5}, // Size: 5')
        descriptors.append(dict(name=name, offset=offset, count=5))
    rows.append('PLAYER_END = UNIT_END + 125,')
    manifest = APPROVED | {'active_player_dwords': 273, 'container_dwords': 574,
                           'player_field_base_dword': 148, 'required_mask_dwords': 9,
                           'player_fields': descriptors}
    return manifest, '\n'.join(rows)


class ProtocolTests(unittest.TestCase):
    def test_matches_all_numeric_offsets_and_sizes(self):
        manifest, source = fixture()
        self.assertEqual(verify(manifest, source)['player_fields_checked'], 25)

    def test_rejects_layout_drift_after_first_field(self):
        manifest, source = fixture()
        manifest['player_fields'][20]['offset'] += 1
        with self.assertRaisesRegex(ValueError, 'PLAYER_QUEST_LOG_21_1'):
            verify(manifest, source)

    def test_rejects_optional_quest_and_class_wire_formats(self):
        for key, value in [('quest_slots', 1000), ('max_class_id', 254), ('class_mask_words', 8),
                           ('quest_remove_slot_bytes', 2), ('container_slots', 36)]:
            manifest, source = fixture()
            manifest[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, key):
                verify(manifest, source)

    def test_missing_and_duplicate_descriptors_fail(self):
        for operation in ('remove', 'duplicate'):
            manifest, source = fixture()
            if operation == 'remove':
                manifest['player_fields'].pop()
            else:
                manifest['player_fields'].append(copy.deepcopy(manifest['player_fields'][0]))
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                verify(manifest, source)

    def test_size_comment_is_checked_against_next_real_offset(self):
        manifest, source = fixture()
        source = source.replace('UNIT_END + 5, // Size: 5', 'UNIT_END + 6, // Size: 5')
        with self.assertRaisesRegex(ValueError, 'interval to next field'):
            verify(manifest, source)

    def test_rejects_unsupported_cpp_expression_without_execution(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported server expression'):
            parse_fields('OBJECT_END = system("bad"),')

    def test_rejects_duplicate_server_symbols(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate server field'):
            parse_fields('OBJECT_END = 6,\nOBJECT_END = 7,')
