import hashlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest import mock
from tools import verify_wine_cohort_apk as checker
from tools import plan_wine_cohort_adoption as adoption


class CohortApk(unittest.TestCase):
    def test_adoption_plan_is_seven_file_read_only_and_keeps_native_and_recovery_producers_separate(self):
        value=adoption.plan()
        self.assertEqual(len(value['files']),7);self.assertFalse(value['productionLocksMutated'])
        self.assertIn('runtime/bridges/x11-runtime.lock.json',value['files'])
        self.assertTrue(all(row['current']==checker.release.identity(adoption.ROOT/name) for name,row in value['files'].items()))

    def test_source_recovery_cannot_be_relabelled_as_original_native_binary_run(self):
        read=adoption.release.client.small
        path=adoption.ROOT/adoption.ROSTER['runtime/turnip/android-provider.lock.json']
        pin=json.loads(read(path));pin['artifact']['originalNativeBuildArtifact']['runId']=41079114080
        def chosen(candidate,*args):return json.dumps(pin).encode() if candidate==path else read(candidate,*args)
        with mock.patch.object(adoption.release.client,'small',side_effect=chosen),self.assertRaisesRegex(ValueError,'remain-distinct'):
            adoption.plan()

    def test_all_four_provider_subtrees_and_source_profiles_are_exact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            assets={name+'/payload.archive':b'package-'+name.encode() for name in checker.release.PROVIDERS}
            inputs={'assets/runtime-sources.lock.json':b'fixed-wine-profile','assets/x11-runtime.lock.json':b'selected-49-ELF-closure'}
            pins=lambda rows:{name:dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for name,raw in rows.items()}
            for kind in ('valid','missing','extra','changed','compressed','old-runtime','duplicate'):
                path=root/(kind+'.apk')
                with zipfile.ZipFile(path,'w') as archive:
                    for name,raw in assets.items():
                        if kind=='missing' and name.startswith('turnip/'):continue
                        if kind=='changed' and name.startswith('guest-bridges/'):raw=b'wrong'
                        archive.writestr('assets/'+name,raw,compress_type=zipfile.ZIP_DEFLATED if kind=='compressed' else zipfile.ZIP_STORED)
                    for name,raw in inputs.items():archive.writestr(name,b'old' if kind=='old-runtime' else raw)
                    if kind=='extra':archive.writestr('assets/shader-tools/unexpected',b'extra')
                    if kind=='duplicate':
                        # A duplicate outside the selected subtree is still rejected.
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore');archive.writestr('duplicate',b'a');archive.writestr('duplicate',b'b')
                if kind=='valid':self.assertEqual(checker.apk_assets(path,pins(assets),pins(inputs))['providerSubtrees'],4)
                else:
                    with self.subTest(kind=kind),self.assertRaises(ValueError):checker.apk_assets(path,pins(assets),pins(inputs))


if __name__=='__main__':unittest.main()
