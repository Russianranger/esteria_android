"""Real AArch64 ELF tooling tests; fixtures are compiled but never executed."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

from tools import server_engine_elf as engine


class ElfBounds(unittest.TestCase):
    def test_non_elf_and_links_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            item = root / 'input'; item.write_bytes(bytes(64))
            with self.assertRaisesRegex(ValueError, 'elf64'):
                engine.inspect(item)
            link = root / 'link'; link.symlink_to(item)
            with self.assertRaises(OSError):
                engine.inspect(link)

    def test_bounded_tool_output_and_failure(self):
        import sys
        self.assertEqual(engine.command([sys.executable, '-c', 'print("fixture")']), 'fixture\n')
        with self.assertRaisesRegex(ValueError, 'output-limit'):
            engine.command([sys.executable, '-c', 'import os;os.write(1,b"x"*100000)'])
        with self.assertRaisesRegex(ValueError, 'objcopy-failed'):
            engine.command([sys.executable, '-c', 'raise SystemExit(7)'])


@unittest.skipUnless(os.environ.get('ESTERIA_NDK_TOOLCHAIN'), 'exact NDK toolchain fixture not supplied')
class RealAarch64Derivatives(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory(prefix='server-elf-fixtures-')
        cls.root = Path(cls.base.name)
        cls.toolchain = Path(os.environ['ESTERIA_NDK_TOOLCHAIN']).resolve(strict=True)
        cls.objcopy = cls.toolchain / 'llvm-objcopy'
        cls.tool = dict(executable=engine.files.identity(cls.objcopy))
        source = cls.root / 'fixture.c'
        source.write_text('volatile int marker=17; void _start(void) { for(;;) marker++; }\n')
        cls.original = cls.root / 'original'
        subprocess.run([str(cls.toolchain / 'clang'), '--target=aarch64-linux-gnu',
            '-fuse-ld=lld', '-nostdlib', '-g', '-Wl,--build-id=sha1',
            '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(source),
            '-o', str(cls.original)], check=True, capture_output=True, timeout=30)
        cls.original_pin = engine.files.identity(cls.original)

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=self.root)
        self.directory = Path(self.temporary.name)
        self.output = self.directory / 'worldserver'
        self.debug = self.directory / 'worldserver.debug'

    def tearDown(self):
        self.assertEqual(engine.files.identity(self.original), self.original_pin)
        self.temporary.cleanup()

    def derive(self):
        return engine.derive(self.original, self.output, self.debug, self.objcopy, self.tool)

    def mutate(self, path, offset):
        path.chmod(0o600)
        with path.open('r+b') as stream:
            stream.seek(offset); old = stream.read(1); stream.seek(offset)
            stream.write(bytes([old[0] ^ 1]))

    def test_actual_strip_preserves_loaded_bytes_symbols_and_debuglink(self):
        result = self.derive()
        self.assertTrue(result['runtimeBytesPreserved'])
        self.assertTrue(result['debugLinkVerified'])
        self.assertFalse(result['serverExecuted'])
        self.assertLess(result['stripped']['bytes'], result['original']['bytes'])
        other = self.directory / 'second'; other.mkdir()
        second = engine.derive(self.original, other / 'worldserver', other / 'worldserver.debug',
                               self.objcopy, self.tool)
        self.assertEqual(result, second)

    def test_existing_output_is_preserved(self):
        self.output.write_bytes(b'existing')
        with self.assertRaisesRegex(ValueError, 'existing-derivative'):
            self.derive()
        self.assertEqual(self.output.read_bytes(), b'existing')
        self.assertFalse(self.debug.exists())

    def test_changed_tool_is_refused_before_writes(self):
        with self.assertRaisesRegex(ValueError, 'tool-changed'):
            engine.derive(self.original, self.output, self.debug, self.objcopy,
                          dict(executable=dict(bytes=1, sha256='0'*64)))
        self.assertFalse(self.output.exists())
        self.assertFalse(self.debug.exists())

    def test_changed_loaded_instruction_is_refused(self):
        self.derive(); row = engine.inspect(self.output)['sections']['.text']
        self.mutate(self.output, row['offset'])
        with self.assertRaisesRegex(ValueError, 'loaded-bytes-changed'):
            engine.verify_pair(self.original, self.output, self.debug)

    def test_changed_debug_data_is_refused(self):
        self.derive(); row = engine.inspect(self.debug, debug=True)['sections']['.debug_info']
        self.mutate(self.debug, row['offset'])
        with self.assertRaisesRegex(ValueError, 'debug-section-changed'):
            engine.verify_pair(self.original, self.output, self.debug)

    def test_changed_symbol_value_is_refused(self):
        self.derive(); row = engine.inspect(self.debug, debug=True)['sections']['.symtab']
        self.mutate(self.debug, row['offset'] + 24 + 8)
        with self.assertRaisesRegex(ValueError, 'debug-symbols-changed'):
            engine.verify_pair(self.original, self.output, self.debug)

    def test_debug_build_id_is_preserved_and_changed_bytes_are_refused(self):
        self.derive(); row = engine.inspect(self.debug, debug=True)['sections']['.note.gnu.build-id']
        self.mutate(self.debug, row['offset'] + row['bytes'] - 1)
        with self.assertRaisesRegex(ValueError, 'debug-section-changed'):
            engine.verify_pair(self.original, self.output, self.debug)

    def test_valid_long_symbol_names_are_preserved(self):
        symbol = 'long_symbol_' + 'x' * 5000
        source = self.directory / 'long.c'
        source.write_text('volatile int ' + symbol + '=17; void _start(void) { for(;;) ' + symbol + '++; }\n')
        original = self.directory / 'long-original'
        subprocess.run([str(self.toolchain / 'clang'), '--target=aarch64-linux-gnu',
            '-fuse-ld=lld', '-nostdlib', '-g', '-Wl,--build-id=sha1',
            '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(source), '-o', str(original)],
            check=True, capture_output=True, timeout=30)
        result = engine.derive(original, self.output, self.debug, self.objcopy, self.tool)
        self.assertTrue(result['runtimeBytesPreserved'])

    def test_wrong_debuglink_is_refused(self):
        self.derive(); row = engine.inspect(self.output)['sections']['.gnu_debuglink']
        self.mutate(self.output, row['offset'])
        with self.assertRaisesRegex(ValueError, 'debuglink-identity'):
            engine.verify_pair(self.original, self.output, self.debug)

    def test_out_of_bounds_section_table_is_refused(self):
        self.derive(); self.output.chmod(0o600)
        with self.output.open('r+b') as stream:
            stream.seek(40); stream.write(struct.pack('<Q', 2**63))
        with self.assertRaisesRegex(ValueError, 'section-table-invalid'):
            engine.inspect(self.output)


if __name__ == '__main__':
    unittest.main()
