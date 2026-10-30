import hashlib
import json
from pathlib import Path
import struct
import tempfile
import types
import unittest
from unittest.mock import patch

from tools import wine_audio


class WineAudioInputs(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_checked_in_runtime_pins_match_immutable_wine_archive(self):
        lock = json.loads(wine_audio.packages.DEFAULT_LOCK.read_text())
        audio = lock['softwareAudio']
        self.assertEqual(audio['runtimeArchiveSha256'], lock['packages']['wine-arm64']['archive']['sha256'])
        self.assertEqual(len(audio['components']), 4)
        for name, identity in audio['components'].items():
            wine_audio.packages.pin_identity(dict(file=Path(name).name, **identity))
            if name.endswith('.drv'):
                self.assertEqual(identity['peMachine'], '0xaa64')

    def test_source_recipe_runtime_and_actual_plugin_identity_must_all_match(self):
        source = self.root / 'source'
        for directory in ('native/guest-bridges', 'native/presentation', 'runtime/bridges'):
            (source / directory).mkdir(parents=True)
        for name in ('guest-bridges/pcm_esteria.c', 'presentation/frame_protocol.h', 'presentation/frame_transport.h'):
            (source / 'native' / name).write_text('synthetic source fixture\n')
        (source / 'runtime/bridges/sources.lock.json').write_text('{}')
        expected_sources = {str(path.relative_to(source / 'native')):
                            dict(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                            for path in (source / 'native').rglob('*') if path.is_file()}
        runtime = self.root / 'runtime'; runtime.mkdir()
        image = bytearray(64); image[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', image, 18, 183)
        (runtime / 'alsa.so').write_bytes(image)
        component = dict(bytes=len(image), sha256=hashlib.sha256(image).hexdigest(), elfMachine=183, elfClass=2)
        lock = dict(packages={'wine-arm64': {'archive': {'sha256': 'b' * 64}}},
                    softwareAudio={'runtimeArchiveSha256': 'b' * 64, 'components': {'alsa.so': component}})
        payload = self.root / 'payload'; (payload / 'bin').mkdir(parents=True)
        (payload / 'bin' / wine_audio.PLUGIN).write_bytes(image)
        actual = dict(bytes=len(image), sha256=hashlib.sha256(image).hexdigest(), architecture='arm64',
                      needed=['libasound.so.2', 'libc.so.6'], maxGlibc='2.34', interpreter=None)
        receipt = dict(formatVersion=1, compiled=True, scope='linux-arm64-guest-bridge-build-only',
                       integrationRevision='a' * 40, sources=expected_sources,
                       inputLockSha256=hashlib.sha256(b'{}').hexdigest(), runtimeArchiveSha256='b' * 64,
                       binaries={wine_audio.PLUGIN: actual})
        spec = types.SimpleNamespace(loader=types.SimpleNamespace(exec_module=lambda _: None))
        with patch.object(wine_audio, 'ROOT', source), \
             patch.object(wine_audio.importlib.util, 'spec_from_file_location', return_value=spec), \
             patch.object(wine_audio.importlib.util, 'module_from_spec', return_value=types.SimpleNamespace(elf=lambda _: dict(actual))):
            def check(value):
                (payload / 'bridge-build.json').write_text(json.dumps(value))
                return wine_audio.bridge_identity(runtime, payload, 'a' * 40, lock)
            self.assertEqual(check(receipt)['plugin'], actual)
            actual['needed'] = ['ld-linux-aarch64.so.1', 'libasound.so.2', 'libc.so.6']
            self.assertEqual(check(receipt)['plugin'], actual)
            actual['needed'] = ['libasound.so.2', 'libc.so.6', 'libstdc++.so.6']
            with self.assertRaisesRegex(ValueError, 'binary-contract-mismatch'):
                check(receipt)
            actual['needed'] = ['libasound.so.2', 'libc.so.6']
            for key, wrong in (('integrationRevision', 'c' * 40), ('inputLockSha256', 'c' * 64),
                               ('runtimeArchiveSha256', 'd' * 64), ('sources', {}), ('formatVersion', True),
                               ('binaries', {wine_audio.PLUGIN: dict(actual, sha256='d' * 64)})):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    check(dict(receipt, **{key: wrong}))
            (runtime / 'alsa.so').write_bytes(bytes(image) + b'changed')
            with self.assertRaisesRegex(ValueError, 'size-mismatch'):
                check(receipt)

    def test_configuration_is_exclusive_and_uses_the_real_private_plugin(self):
        wine_audio.configure(self.root, '/esteria-qualification')
        text = (self.root / 'alsa-qualification.conf').read_text()
        self.assertIn('pcm_type.esteria { lib "/esteria-qualification/libasound_module_pcm_esteria.so" }', text)
        self.assertIn('format S16_LE rate 48000 channels 2', text)
        with self.assertRaises(FileExistsError):
            wine_audio.configure(self.root, '/esteria-qualification')


if __name__ == '__main__':
    unittest.main()
