import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import measure_wine_x11_closure as closure
from tests.test_wine_arm64_candidate import image


class StaticX11Closure(unittest.TestCase):
    def test_guest_aliases_resolve_with_parent_only_inventory_and_full_loader_targets(self):
        links = {'lib': 'usr/lib', 'usr/lib/ld-linux-aarch64.so.1': 'aarch64-linux-gnu/ld-linux-aarch64.so.1',
                 'usr/lib/aarch64-linux-gnu/libX11.so.6': 'libX11.so.6.4.0'}
        self.assertEqual(closure.resolve('lib/ld-linux-aarch64.so.1', links, parent_only=True),
                         'usr/lib/ld-linux-aarch64.so.1')
        self.assertEqual(closure.resolve('lib/ld-linux-aarch64.so.1', links),
                         'usr/lib/aarch64-linux-gnu/ld-linux-aarch64.so.1')
        self.assertEqual(closure.resolve('usr/lib/aarch64-linux-gnu/libX11.so.6', links),
                         'usr/lib/aarch64-linux-gnu/libX11.so.6.4.0')
        for name, bad in (('../escape', {}), ('a', {'a': 'b', 'b': 'a'}), ('a', {'a': '../../escape'})):
            with self.subTest(name=name), self.assertRaises(ValueError): closure.resolve(name, bad)

    def test_transitive_needed_and_exact_interpreter_must_reach_pinned_regular_images(self):
        images = {'usr/bin/X': dict(needed=['libX.so.1'], interpreter=['/lib/ld.so']),
                  'usr/lib/aarch64-linux-gnu/libX.so.1.0': dict(needed=[], interpreter=[]),
                  'usr/lib/ld.so': dict(needed=[], interpreter=[])}
        links = {'lib': 'usr/lib', 'usr/lib/aarch64-linux-gnu/libX.so.1': 'libX.so.1.0'}
        result = closure.dependency_closure(images, links, ['usr/bin/X'])
        self.assertEqual(set(result), set(images))
        self.assertEqual(result['usr/bin/X'], {'libX.so.1': 'usr/lib/aarch64-linux-gnu/libX.so.1.0'})
        images['usr/bin/X']['needed'] = ['not-pinned.so']
        with self.assertRaisesRegex(ValueError, 'unreviewed-dependency'):
            closure.dependency_closure(images, links, ['usr/bin/X'])

    def test_unused_roster_cannot_be_called_an_exact_dependency_closure(self):
        images = {'usr/bin/X': dict(needed=[], interpreter=[]),
                  'usr/lib/aarch64-linux-gnu/unrelated.so': dict(needed=[], interpreter=[])}
        with self.assertRaisesRegex(ValueError, 'not-exactly-transitive'):
            closure.dependency_closure(images, {}, ['usr/bin/X'])

    def test_actual_header_checked_before_bounded_readelf_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'elf'; path.write_bytes(image())
            output = b' 0x00001 (NEEDED) Shared library: [libc.so.6]\n[Requesting program interpreter: /lib/ld-linux-aarch64.so.1]\n'
            with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, b'')):
                value = closure.elf_dependencies(path)
            self.assertEqual(value, dict(needed=['libc.so.6'], interpreter=['/lib/ld-linux-aarch64.so.1']))
            for changed in (output+b' (RPATH) Library rpath: [/injected]\n',
                            output+output, b'[Requesting program interpreter: /system/bin/linker64]\n'):
                with self.subTest(changed=changed), patch.object(subprocess, 'run',
                        return_value=subprocess.CompletedProcess([], 0, changed, b'')), self.assertRaises(ValueError):
                    closure.elf_dependencies(path)
            path.write_bytes(b'not-an-ELF')
            with patch.object(subprocess, 'run') as command, self.assertRaises(ValueError):
                closure.elf_dependencies(path)
            command.assert_not_called()

    def test_existing_output_does_not_expand_or_read_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary); (path/'save').write_bytes(b'keep')
            with patch.object(closure.retained, 'pins') as pins, self.assertRaisesRegex(ValueError, 'output-exists'):
                closure.measure(Path('/not-selected'), path)
            pins.assert_not_called(); self.assertEqual((path/'save').read_bytes(), b'keep')


if __name__ == '__main__': unittest.main()
