import importlib.util
import io
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'runtime/turnip'


def module(name):
    spec = importlib.util.spec_from_file_location('turnip_' + name, DIR / (name + '.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


fetch = module('fetch_sources'); record = module('record_build'); probe = module('run_probe')


class TurnipBuild(unittest.TestCase):
    def test_exact_source_snapshot_and_runtime_boundary(self):
        lock = json.loads((DIR / 'sources.lock.json').read_text())
        base = json.loads((ROOT / 'runtime/bridges/sources.lock.json').read_text())
        for name in ('snapshot', 'keyring', 'inRelease', 'indexes', 'runtimeArchiveSha256'):
            self.assertEqual(lock[name], base[name])
        self.assertEqual(lock['upstream']['mesa']['sha256'], '072705caa9adf4740f1489194b13e278ad959166863b5271fe423a86353c9ab6')
        self.assertEqual(lock['upstream']['mesa']['bytes'], 77677128)
        pins = {p['package']: p for p in lock['packages']}
        self.assertEqual(set((DIR / 'packages.txt').read_text().splitlines()), {p['package']+'='+p['version'] for p in pins.values()})
        sources = {(s['package'],s['version']) for s in lock['sources']}
        self.assertTrue(all((p['sourcePackage'],p['sourceVersion']) in sources for p in pins.values()))
        self.assertNotIn('libdrm-dev', pins)
        self.assertEqual(lock['upstream']['spirv-tools']['revision'],'0cfe9e7219148716dfd30b37f4d21753f098707a')
        self.assertEqual(lock['upstream']['spirv-headers']['revision'],'2acb319af38d43be3ea76bfabf3998e5281d8d12')

    def test_probe_environment_binds_exact_icd_and_disables_inherited_layers(self):
        env=probe.environment(Path('/private/output'),Path('/private/output/exclusive-icd.json'))
        self.assertEqual(env['VK_ICD_FILENAMES'],env['VK_DRIVER_FILES'])
        self.assertEqual(env['VK_LOADER_LAYERS_DISABLE'],'~all~')
        self.assertEqual(env['VK_IMPLICIT_LAYER_PATH'],'/private/output/empty')
        self.assertFalse(any(key.startswith('LD_') for key in env))

    def test_hardware_result_requires_all_pixels_and_narrow_scope(self):
        value=dict(formatVersion=1,scope='linux-arm64-turnip-kgsl-component-probe',icdLoaded=True,
            noKgslHostVerified=False,turnip740ShaderReadbackQualified=True,pixelsVerified=4096,
            vendorId=0x5143,deviceId=740,deviceName='FD740',x11PresentationQualified=False,
            androidQualified=False,gameplayQualified=False)
        probe.validate(value,False)
        for key,bad in (('pixelsVerified',0),('deviceName','llvmpipe'),('vendorId',1),('androidQualified',True),('icdLoaded',False)):
            with self.subTest(key=key),self.assertRaises(ValueError):probe.validate(dict(value,**{key:bad}),False)

    def test_absent_gpu_receipt_cannot_claim_hardware_or_android(self):
        value = dict(formatVersion=1, scope='linux-arm64-turnip-kgsl-component-probe', icdLoaded=True,
            noKgslHostVerified=True, turnip740ShaderReadbackQualified=False, pixelsVerified=0,
            vendorId=0, deviceId=0, deviceName='', x11PresentationQualified=False, androidQualified=False, gameplayQualified=False)
        record.validate_no_gpu(value)
        for key in ('turnip740ShaderReadbackQualified','androidQualified','x11PresentationQualified','gameplayQualified'):
            with self.subTest(key=key), self.assertRaises(ValueError): record.validate_no_gpu(dict(value, **{key:True}))
        for key, bad in (('icdLoaded',False),('noKgslHostVerified',False),('pixelsVerified',4096),('vendorId',False)):
            with self.subTest(key=key), self.assertRaises(ValueError): record.validate_no_gpu(dict(value, **{key:bad}))

    def archive(self, root, members):
        archive = root / 'input.tar'
        with tarfile.open(archive,'w') as output:
            for name, data, link in members:
                item = tarfile.TarInfo(name)
                if link is not None: item.type = tarfile.SYMTYPE; item.linkname = link
                else: item.size = len(data)
                output.addfile(item, None if link is not None else io.BytesIO(data))
        return archive

    def test_source_unpack_allows_only_confined_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.archive(root,[('src/a/file',b'code',None),('src/link',b'','a/file')])
            fetch.unpack(archive,dict(prefix='src'),root/'out')
            self.assertEqual((root/'out/link').read_bytes(),b'code')
        for target in ('../../escape','/absolute'):
            with tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);archive=self.archive(root,[('src/a/link',b'',target)])
                with self.assertRaises(ValueError):fetch.unpack(archive,dict(prefix='src'),root/'out')

    def test_source_unpack_rejects_traversal_duplicates_and_link_parent_collision(self):
        cases = [[('src/../escape',b'x',None)], [('src/a',b'x',None),('src/a',b'y',None)],
                 [('src/a',b'','b'),('src/a/child',b'x',None)]]
        for members in cases:
            with self.subTest(members=members), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary);archive=self.archive(root,members)
                with self.assertRaises(ValueError):fetch.unpack(archive,dict(prefix='src'),root/'out')


if __name__ == '__main__': unittest.main()
