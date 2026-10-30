import hashlib
import copy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest import mock
from tools import verify_wine_cohort_apk as checker
from tools import plan_wine_cohort_adoption as adoption


class CohortApk(unittest.TestCase):
    def test_stock_default_and_local_game_require_explicit_complete_selection(self):
        args=SimpleNamespace(server_providers=Path('/stock'))
        self.assertEqual(checker.server_profile_paths(args),('stock',
            [Path('/stock')/name for name in ('programs','extractors','content')]))
        args.server_profile='local-game';args.playerbots_programs_provider=Path('/helper')
        args.data_tools_provider=Path('/data4')
        self.assertEqual(checker.server_profile_paths(args),('local-game',
            [Path('/helper'),Path('/data4'),Path('/stock/content')]))
        for profile,programs,data in [('unknown',None,None),('stock',Path('/helper'),None),
                ('stock',None,Path('/data4')),('local-game',None,None),
                ('local-game',Path('/helper'),None),('local-game',None,Path('/data4'))]:
            args.server_profile=profile;args.playerbots_programs_provider=programs;args.data_tools_provider=data
            with self.subTest(profile=profile,programs=programs,data=data),mock.patch.object(checker,'verify') as expensive:
                with self.assertRaises(ValueError):checker.complete(args)
                expensive.assert_not_called()

    def test_optional_factories_recheck_all_source_and_debug_closures_and_failures_propagate(self):
        from tools import provider_playerbots_programs as programs,provider_server_data_tools as data
        from tools import qualify_server_providers as stock
        args=SimpleNamespace(server_providers=Path('/stock'),dependency_provider=Path('/dependencies'),apk=Path('/actual.apk'),
            playerbots_programs_provider=Path('/helper'),data_tools_provider=Path('/data4'))
        with mock.patch.object(programs,'verify',return_value={'helperSourcesVerified':True}) as p,\
                mock.patch.object(data,'verify',return_value={'dataSourcesVerified':True}) as d,\
                mock.patch.object(stock.content,'verify',return_value={'contentVerified':True}) as c,\
                mock.patch.object(stock.dependencies,'verify',return_value={'dependenciesVerified':True}) as deps,\
                mock.patch.object(stock.files,'identity',return_value={'bytes':123,'sha256':'a'*64}):
            result=checker.server_profile_checks(args,'local-game')
            p.assert_called_once_with(args.playerbots_programs_provider,apk=args.apk)
            d.assert_called_once_with(args.data_tools_provider,apk=args.apk)
            c.assert_called_once_with(args.server_providers/'content',apk=args.apk)
            deps.assert_called_once_with(args.dependency_provider,apk=args.apk)
            self.assertEqual(set(result['providers']),{'programs','dataTools','content','dependencies'})
            self.assertFalse(result['localWorldReadinessQualified']);self.assertFalse(result['sqlExecuted'])
            self.assertFalse(result['androidRuntimeQualified']);self.assertFalse(result['playerbotsAiQualified'])
            for failing in (p,d,c,deps):
                failing.side_effect=ValueError('actual-source-or-paired-debug-rejected')
                with self.assertRaisesRegex(ValueError,'actual-source-or-paired-debug-rejected'):
                    checker.server_profile_checks(args,'local-game')
                failing.side_effect=None
        with mock.patch.object(stock,'verify_final',return_value={'historical':True}) as original:
            self.assertEqual(checker.server_profile_checks(args,'stock'),{'historical':True})
            original.assert_called_once_with(args.server_providers,args.dependency_provider,args.apk)

    def test_local_game_complete_asset_inventory_rejects_stock_extractors_or_missing_helpers(self):
        from tools import package_combined_android as combined,verify_android_proot as proot
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);server=root/'stock';cohort=root/'cohort';cohort.mkdir()
            payloads={}
            for dirname,asset in [('proot','proot'),('dependencies','server-runtime'),
                    ('helper','server-programs'),('data4','server-data-tools'),('stock/content','server-content')]:
                folder=root/dirname/'assets'/asset;folder.mkdir(parents=True)
                (folder/'provider.json').write_bytes(b'qualified-separately')
                payloads['assets/'+asset+'/provider.json']=b'qualified-separately'
            cohort_members={'client-runtime/payload.archive':{'bytes':7,'sha256':hashlib.sha256(b'payload').hexdigest()}}
            (cohort/'provider-assets-receipt.json').write_text(json.dumps({'members':cohort_members}))
            payloads['assets/client-runtime/payload.archive']=b'payload'
            for directory,names in combined.HELPER_SETS.items():
                records={}
                for name in names:
                    raw=(combined.ROOT/combined.helper_source_path(directory,name)).read_bytes()
                    payloads['assets/'+directory+'/'+name]=raw
                    records[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
                payloads['assets/'+directory+'/manifest.json']=json.dumps({'formatVersion':1,'files':records}).encode()
            notices={name:{'bytes':6,'sha256':hashlib.sha256(b'notice').hexdigest()} for name in combined.NDK_NOTICES}
            for name in ('ESTERIA-GPL-3.0.txt','FTA-MIT-LICENSE.txt',*notices):payloads['assets/notices/'+name]=b'notice'
            for target,source in [('sources.lock.json','sources.lock.json'),('runtime-sources.lock.json','runtime/runtime-sources.lock.json'),
                    ('x11-runtime.lock.json','runtime/bridges/x11-runtime.lock.json'),('runtime.properties','app/src/main/assets/runtime.properties')]:
                payloads['assets/'+target]=(checker.release.ROOT/source).read_bytes()
            payloads.update({name:b'native-verified-separately' for name in combined.NATIVE_FILES})
            args=SimpleNamespace(server_profile='local-game',server_providers=server,dependency_provider=root/'dependencies',
                playerbots_programs_provider=root/'helper',data_tools_provider=root/'data4',proot_provider=root/'proot',
                cohort_release=cohort,release_lock=root/'release-lock',packaging_source=root/'recipe',
                proot_sources=root/'sources.tar.gz',ndk_archive=root/'ndk.zip')
            for kind in ('valid','stock-extractors','missing-helper','changed-source','extra-native'):
                args.apk=root/(kind+'.apk');selected=dict(payloads)
                if kind=='stock-extractors':selected['assets/server-extractors/provider.json']=b'wrong-profile'
                if kind=='missing-helper':del selected['assets/server-session/server_session.py']
                if kind=='changed-source':selected['assets/sources.lock.json']=b'foreign-source'
                if kind=='extra-native':selected['lib/x86_64/libproot.so']=b'wrong-ABI'
                with zipfile.ZipFile(args.apk,'w') as apk:
                    for name,raw in selected.items():apk.writestr(name,raw)
                with self.subTest(kind=kind),mock.patch.object(checker,'verify',return_value={}),\
                        mock.patch.object(checker,'server_profile_checks',return_value={}),\
                        mock.patch.object(proot,'verify',return_value={}),mock.patch.object(combined,'proot_sources',return_value={}),\
                        mock.patch.object(combined,'ndk_notices',return_value=notices):
                    if kind=='valid':
                        result=checker.complete(args)
                        self.assertTrue(result['composedDataToolsIncluded']);self.assertFalse(result['stockExtractorsIncluded'])
                        self.assertFalse(result['deviceTestCandidate']);self.assertFalse(result['localWorldReadinessQualified'])
                    else:
                        with self.assertRaises(ValueError):checker.complete(args)

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
