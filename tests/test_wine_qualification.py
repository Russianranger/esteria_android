import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_wine_arm64 as qualification


def image(machine=0xaa64, dll=False):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 64)
    data[64:68] = b'PE\0\0'
    struct.pack_into('<H', data, 68, machine)
    struct.pack_into('<H', data, 86, 2 | (0x2000 if dll else 0))
    struct.pack_into('<H', data, 88, 0x20b)
    return bytes(data)


class WineQualification(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def inputs(self):
        files = []
        for name in ('WowClient64.exe', 'XvidDecoder.dll'):
            data = image(dll=name.endswith('.dll'))
            (self.root / name).write_bytes(data)
            files.append(dict(name=name, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
                              pe={'machine': '0xaa64'}, imports=['MSVCP140.dll', 'VCRUNTIME140.dll']))
        manifest = dict(schema_version=1, architecture='ARM64', evidence='build-only', source_revision='a' * 40,
                        build_id='synthetic', files=files, protocol=dict(build=12340, container_slots=254,
                                                                      quest_slots=25, max_class_id=32))
        (self.root / 'client-build.json').write_text(json.dumps(manifest))
        driver = self.root / 'test_xvid_adapter.exe'
        driver.write_bytes(image())
        return manifest, driver

    def test_exact_arm64_images_and_actual_build_hashes(self):
        manifest, driver = self.inputs()
        actual, evidence = qualification.client_inputs(self.root, driver)
        self.assertEqual(actual, manifest)
        self.assertEqual(evidence['sourceRevision'], 'a' * 40)
        self.assertEqual(evidence['files']['XvidDecoder.dll']['peMachine'], '0xaa64')
        (self.root / 'XvidDecoder.dll').write_bytes(image() + b'mutation')
        with self.assertRaises(ValueError):
            qualification.client_inputs(self.root, driver)

    def test_wrong_architecture_or_dll_flags_are_rejected(self):
        path = self.root / 'image.exe'
        for data, dll in ((image(0x8664), False), (image(dll=True), False), (image(), True)):
            with self.subTest(machine=data[68:70], dll=dll):
                path.write_bytes(data)
                with self.assertRaisesRegex(ValueError, 'native-arm64'):
                    qualification.pe_identity(path, dll)

    def test_import_report_uses_actual_arm64_manifest_and_local_codec(self):
        manifest, _ = self.inputs()
        manifest['files'][0]['imports'] += ['XvidDecoder.dll', 'api-ms-win-crt-runtime-l1-1-0.dll']
        report = qualification.imports_report(manifest, {'windowsArm64Modules': {
            'msvcp140.dll': {'peMachine': '0xaa64'}, 'vcruntime140.dll': {'peMachine': '0xaa64'},
            'vcruntime140_1.dll': {'peMachine': '0x8664'}}})
        self.assertNotIn('vcruntime140_1.dll', report)
        self.assertEqual(report['xviddecoder.dll']['provider'], 'client-build')
        self.assertTrue(report['api-ms-win-crt-runtime-l1-1-0.dll']['apiSetName'])
        self.assertFalse(report['api-ms-win-crt-runtime-l1-1-0.dll']['resolutionQualified'])

    def test_namespace_command_owns_detached_children_and_disables_network(self):
        command = qualification.namespace_command(Path('/tool.py'), Path('/runtime'), Path('/evidence'), True)
        for flag in ('--mount', '--pid', '--fork', '--kill-child=SIGKILL', '--mount-proc', '--net'):
            self.assertIn(flag, command)
        self.assertIn('--namespace-worker', command)
        self.assertNotIn('sudo', command)
        with self.assertRaises(ValueError):
            qualification.namespace_command(Path('/tool.py'), Path('/r'), Path('/o'), False)

    def test_guest_environment_does_not_inherit_host_credentials(self):
        command = qualification.guest_command(Path('/rootfs'), '/opt/wine/bin/wine', 'fixture.exe')
        self.assertEqual(command[:4], ['chroot', '/rootfs', '/usr/bin/env', '-i'])
        self.assertIn('WINEPREFIX=/esteria-qualification/prefix', command)
        self.assertNotIn('HOME=/root', command)
        self.assertTrue(all('TOKEN' not in part for part in command))

    def test_forced_vulkan_driver_and_observed_device_identity(self):
        command = qualification.guest_command(Path('/r'), 'fixture', graphics={'icdPath': 'usr/share/vulkan/icd.d/lvp.json'})
        self.assertIn('VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/lvp.json', command)
        self.assertIn('LIBGL_ALWAYS_SOFTWARE=1', command)
        code = ('import os\nos.write(1,b"Vulkan adapter: llvmp")\n'
                'os.write(1,b"ipe (LLVM); driver 0\\nVulkan validation callback: unavailable\\nPASS\\n")')
        capture = qualification.Capture([sys.executable, '-c', code], self.root / 'graphics.log', needle=b'PASS',
            line_prefixes=(b'Vulkan adapter:', b'Vulkan validation callback:'))
        self.assertEqual(capture.wait(3).exit_code, 0)
        self.assertTrue(capture.finish(2))
        self.assertTrue(capture.matched.is_set())
        self.assertEqual(capture.lines['Vulkan adapter:'], 'Vulkan adapter: llvmpipe (LLVM); driver 0')

    def test_graphics_receipt_keeps_codec_and_presentation_scope_separate(self):
        result = dict(displayReady=True, networkIsolated=True, prefixExit=0, fixtureExit=0, codecMessageMatched=True,
                      wineStopExit=0, logStreamsDrained=True, logsWithinLimit=True, logWritesSucceeded=True,
                      graphics={'presentation': dict(exitCode=0, messageMatched=True, softwareAdapterMatched=True,
                                                      validationCallbackActive=False),
                                'texture': dict(exitCode=1, messageMatched=False, softwareAdapterMatched=False)})
        flags = qualification.qualification_flags(result, ['presentation', 'texture'])
        self.assertTrue(flags['linuxArm64CodecQualified'])
        self.assertTrue(flags['linuxArm64VulkanPresentationQualified'])
        self.assertFalse(flags['linuxArm64VulkanTextureLifecycleQualified'])
        result['logStreamsDrained'] = False
        self.assertFalse(any(qualification.qualification_flags(result, ['presentation', 'texture']).values()))

    def test_checked_in_graphics_pin_matches_runtime_and_requires_real_identities(self):
        lock = json.loads(qualification.packages.DEFAULT_LOCK.read_text())
        graphics = lock['softwareGraphics']
        self.assertEqual(graphics['runtimeArchiveSha256'], lock['packages']['wine-arm64']['archive']['sha256'])
        self.assertEqual(graphics['icdApiVersion'], '1.1.230')
        for name, expected in graphics['components'].items():
            qualification.packages.pin_identity(dict(file=Path(name).name, **expected))
        with self.assertRaises(FileNotFoundError):
            qualification.graphics_identity(self.root, lock)

    def test_unqualified_host_or_direct_worker_invocation_never_starts_processes(self):
        with patch.object(qualification.platform, 'machine', return_value='x86_64'), \
             patch.object(qualification.subprocess, 'Popen', side_effect=AssertionError('must not execute')):
            with self.assertRaisesRegex(ValueError, 'native-arm64-host-required'):
                qualification.qualify(self.root, self.root, self.root / 'driver', self.root / 'output')
        with patch.object(qualification.os, 'getpid', return_value=222), \
             patch.object(qualification.subprocess, 'run', side_effect=AssertionError('must not mount')):
            with self.assertRaisesRegex(ValueError, 'owned-pid-namespace'):
                qualification.worker(self.root, self.root)

    def test_log_cap_does_not_limit_large_guest_files(self):
        data = self.root / 'prefix-dll'
        code = ('import pathlib,sys\n'
                'with pathlib.Path(sys.argv[1]).open("wb") as out:\n'
                ' for _ in range(272): out.write(b"x" * 65536)\n'
                'print("done")\n')
        capture = qualification.Capture([sys.executable, '-c', code, str(data)], self.root / 'output.log', limit=1024)
        self.assertEqual(capture.wait(10).exit_code, 0)
        self.assertTrue(capture.finish(2))
        self.assertEqual(data.stat().st_size, 17 * 1024 * 1024)
        self.assertEqual((self.root / 'output.log').read_bytes(), b'done\n')
        self.assertFalse(capture.truncated)

    def test_output_overflow_is_drained_and_keeps_file_bounded(self):
        code = 'import os\nfor _ in range(64): os.write(1,b"x"*65536)\nos.write(1,b"finished")'
        path = self.root / 'capped.log'
        capture = qualification.Capture([sys.executable, '-c', code], path, limit=2048, needle=b'finished')
        self.assertEqual(capture.wait(10).exit_code, 0)
        self.assertTrue(capture.finish(2))
        self.assertEqual(path.stat().st_size, 2048)
        self.assertTrue(capture.truncated)
        self.assertTrue(capture.matched.is_set())
        self.assertIsNone(capture.error)

    @unittest.skipUnless(hasattr(os, 'fork'), 'Linux inherited-pipe behavior')
    def test_inherited_pipe_does_not_block_child_wait_or_bounded_join(self):
        code = 'import os,time\nif os.fork(): os._exit(0)\ntime.sleep(0.4)\nos._exit(0)'
        capture = qualification.Capture([sys.executable, '-c', code], self.root / 'inherited.log')
        self.assertEqual(capture.wait(2).exit_code, 0)
        self.assertFalse(capture.finish(0.01))
        self.assertTrue(capture.finish(2))


if __name__ == '__main__':
    unittest.main()
