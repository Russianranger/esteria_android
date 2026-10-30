import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import manifest_server_modules as modules


def command(target, *, names='mod-one,mod-two,', configs='one.conf,two.conf,', arguments=False):
    row = {'file': '/checkout' + modules.TARGETS[target]}
    args = ['c++', '-DAC_MODULES_LIST="' + names + '"', '-DCONFIG_FILE_LIST="' + configs + '"', '-c', row['file']]
    if arguments:
        row['arguments'] = args
    else:
        import shlex
        row['command'] = shlex.join(args)
    return row


class CompiledModules(unittest.TestCase):
    def test_streamed_commands_accept_real_shell_quoting_and_argument_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'compile_commands.json'
            raw = json.dumps([command('worldserver'), command('dbimport', arguments=True)]).encode()
            path.write_bytes(raw)
            selection, identity = modules.extract_commands(path)
            self.assertEqual(selection['modules'], ['mod-one', 'mod-two'])
            self.assertEqual(selection['configFiles'], ['one.conf', 'two.conf'])
            self.assertEqual(identity, {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})

    def test_mismatched_missing_and_duplicate_target_definitions_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'commands.json'
            cases = [[command('worldserver')],
                     [command('worldserver'), command('dbimport', names='mod-other,')],
                     [command('worldserver'), command('worldserver'), command('dbimport')]]
            for rows in cases:
                path.write_text(json.dumps(rows))
                with self.subTest(rows=rows), self.assertRaises(ValueError):
                    modules.extract_commands(path)
            row = command('worldserver', arguments=True)
            row['arguments'].append('-DAC_MODULES_LIST="mod-injected,"')
            with self.assertRaises(ValueError):
                modules.macro_value(row, 'AC_MODULES_LIST')

    def test_malformed_oversized_and_trailing_json_rejected(self):
        for raw in (b'{}', b'[{},]', b'[] {}', b'[{"a":', b'[1]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                list(modules.json_array(io.BytesIO(raw), {}))
        with patch.object(modules, 'MAX_COMMANDS', 20), self.assertRaises(ValueError):
            list(modules.json_array(io.BytesIO(b'[{"data":"' + b'x' * 100 + b'"}]'), {}))

    def test_empty_invalid_and_duplicate_module_names_rejected(self):
        for value in ('', 'mod-one', 'mod-one,mod-one,', 'mod-one,$(bad),', '../escape,'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                modules.names(value)

    def test_literal_with_nonzero_predecessor_crossing_chunk_boundary_and_hash_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'worldserver'
            raw = b'x' * 131068 + b'mod-one,mod-two,\0' + b'tail'
            path.write_bytes(raw)
            expected = {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            self.assertTrue(modules.verify_literals(path, expected, ('mod-one,mod-two,',))['generatedLiteralsPresent'])
            with self.assertRaises(ValueError):
                modules.verify_literals(path, expected, ('mod-one,mod-two',))
            path.write_bytes(raw[:-1] + b'!')
            with self.assertRaises(ValueError):
                modules.verify_literals(path, expected, ('mod-one,mod-two,',))

    def test_receipt_binds_both_binaries_and_does_not_require_unused_dbimport_config_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'bin').mkdir()
            entries = []
            for target, raw in [('worldserver', b'header\0mod-one,mod-two,\0one.conf,two.conf,\0'),
                                ('dbimport', b'header\0mod-one,mod-two,\0')]:
                path = root / 'bin' / target
                path.write_bytes(raw)
                entries.append({'path': 'bin/' + target, 'bytes': len(raw),
                    'sha256': hashlib.sha256(raw).hexdigest(), 'elf': {'machine': 'AArch64'}})
            receipt = root / 'server-build.json'
            receipt.write_text(json.dumps({'schemaVersion': 1, 'architecture': 'Linux-ARM64',
                'sourceCheckoutAndPatchesVerified': True, 'files': entries,
                'serverSource': {'commit': 'a' * 40}, 'sourcesLock': {'sha256': 'b' * 64}}))
            commands = root / 'commands.json'
            commands.write_text(json.dumps([command('worldserver'), command('dbimport')]))
            evidence = modules.verify(commands, root, receipt)
            self.assertTrue(evidence['generatedListsMatchInstalledBinaries'])
            self.assertFalse(evidence['moduleStartupQualified'])
            self.assertFalse(evidence['sqlExecuted'])
            self.assertEqual(evidence['sourceLockSha256'], 'b' * 64)


if __name__ == '__main__':
    unittest.main()
