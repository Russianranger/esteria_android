"""Source-derived ordering plus actual libmpq reads of synthetic MPQs/folders."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from runtime import extractor_order as order
from tools import prepare_ordered_extractors as adaptation

PROFILE=dict(classical=True,trial=False,streaming=False,directAccess=False,
             retailVirtualProviders=False,parentDataVisible=False,installDataVisible=False)


class Planner(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='extractor-order-')
        self.addCleanup(temporary.cleanup);self.base=Path(temporary.name);self.root=self.base/'assets';self.root.mkdir()
        self.put('Data/common.MPQ');self.put('Data/enUS/locale-enUS.MPQ');self.put('Data/enUS/speech-enUS.MPQ')

    def put(self,name,data=b'explicit synthetic header fixture, not a real game archive'):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);return path

    def plan(self,locale='enUS',profile=None):return order.plan(self.root,locale,profile=profile or PROFILE)

    def test_arbitrary_suffixes_use_full_case_insensitive_lexical_paths_not_numbers(self):
        for name in ('Data/patch.MPQ','Data/enUS/patch-enUS.MPQ','Data/patch-10.MPQ','Data/patch-2.MPQ',
                     'Data/patch-Esteria-2026.MPQ','Data/enUS/patch-enUS-z-custom.MPQ'):self.put(name)
        patches=[r['path'] for r in self.plan()['providers'] if r['role']=='patch']
        self.assertEqual(patches,['Data/patch-Esteria-2026.MPQ','Data/patch-2.MPQ','Data/patch-10.MPQ',
            'Data/enUS/patch-enUS-z-custom.MPQ','Data/patch.MPQ','Data/enUS/patch-enUS.MPQ'])

    def test_locale_root_relative_lexical_precedence_and_selected_locale_only(self):
        for name in ('Data/ruRU/locale-ruRU.MPQ','Data/ruRU/speech-ruRU.MPQ','Data/ruRU/patch-ruRU-a.MPQ',
                     'Data/patch-z.MPQ','Data/enUS/patch-enUS-z.MPQ'):self.put(name)
        rows=self.plan('ruRU')['providers']
        self.assertEqual([r['path'] for r in rows if r['role']=='patch'],['Data/ruRU/patch-ruRU-a.MPQ','Data/patch-z.MPQ'])
        self.assertNotIn('Data/enUS/locale-enUS.MPQ',[r['path'] for r in rows])

    def test_locale_rotation_matches_source_and_common3_is_below_common2_and_common(self):
        self.put('Data/common-2.MPQ');self.put('Data/common-3.MPQ')
        plan=self.plan('deDE');self.assertEqual(plan['effectiveLocale'],'enUS')
        positions={r['path']:r['priority'] for r in plan['providers']}
        self.assertEqual([positions['Data/'+n] for n in ('common.MPQ','common-2.MPQ','common-3.MPQ')],[47,46,38])

    def test_folder_patches_and_alternate_views_have_exact_effective_priority(self):
        self.put('Data/patch-a.MPQ');self.put('Data/patch-z.MPQ/alternate/World/Maps/Test/Test.wdt',b'folder')
        self.put('Data/alternate.MPQ/World/Maps/Test/Test.wdt',b'alternate')
        rows=self.plan()['providers'];self.assertEqual([r['role'] for r in rows[:5]],
            ['alternate-view','alternate-view','alternate-base','patch','patch'])
        self.assertEqual(rows[0]['path'],'Data/patch-z.MPQ/alternate')
        self.assertEqual(rows[1]['path'],'Data/patch-a.MPQ');self.assertEqual(rows[1]['prefix'],'alternate')

    def test_chinese_prefix_views_exist_without_alternate_base_but_other_locales_do_not(self):
        self.put('Data/patch-a.MPQ');self.put('Data/zhCN/locale-zhCN.MPQ');self.put('Data/zhCN/speech-zhCN.MPQ')
        self.assertEqual(self.plan('enUS')['providers'][0]['role'],'patch')
        self.assertEqual(self.plan('zhCN')['providers'][0]['role'],'alternate-view')

    def test_unsupported_profiles_path_aliases_symlinks_and_missing_required_inputs_refuse(self):
        for name in PROFILE:
            bad=dict(PROFILE);bad[name]=not bad[name]
            with self.subTest(profile=name),self.assertRaisesRegex(order.OrderError,'unsupported client extraction profile'):
                self.plan(profile=bad)
        bad=dict(PROFILE,classical=1)
        with self.assertRaises(order.OrderError):self.plan(profile=bad)
        self.put('Data/PATCH-A.MPQ');self.put('Data/patch-a.mpq')
        with self.assertRaisesRegex(order.OrderError,'case-insensitive'):self.plan()
        (self.root/'Data/patch-a.mpq').unlink();(self.root/'Data/PATCH-A.MPQ').unlink()
        (self.root/'Data/patch-link.MPQ').symlink_to(self.root/'Data/common.MPQ')
        with self.assertRaisesRegex(order.OrderError,'linked'):self.plan()
        (self.root/'Data/patch-link.MPQ').unlink();(self.root/'Data/enUS/speech-enUS.MPQ').unlink()
        with self.assertRaisesRegex(order.OrderError,'mandatory'):self.plan()

    def test_wire_order_and_original_not_conversion_qualification_are_explicit(self):
        self.put('Data/patch-custom-long.MPQ/DBFilesClient/Map.dbc',b'loose fixture')
        plan=self.plan();wire=order.wire(plan)
        self.assertTrue(wire.startswith(b'ESTERIA-ORDER-1\tenUS\t'))
        self.assertIn(b'P\tdirectory\tData/patch-custom-long.MPQ\t-\t0\t-\n',wire)
        self.assertIn(b'F\tDBFilesClient/Map.dbc\t13\t',wire)
        self.assertFalse(plan['clientMpqConversionQualified']);self.assertFalse(plan['androidRuntimeQualified'])

    def test_unrelated_names_outside_Data_do_not_invalidate_the_archive_order(self):
        before=self.plan();self.put('WTF/Account/Пользователь/SavedVariables/settings.lua',b'unrelated')
        self.put('Screenshots/extra.png',b'unrelated')
        self.assertEqual(self.plan(),before)


@unittest.skipUnless(os.environ.get('ESTERIA_EXTRACTOR_SOURCE'),'exact original extractor source export not supplied')
class RealArchiveReader(Planner):
    @classmethod
    def setUpClass(cls):
        cls.source=Path(os.environ['ESTERIA_EXTRACTOR_SOURCE']).resolve(strict=True)
        cls.pin=adaptation.load_pin();temporary=tempfile.TemporaryDirectory(prefix='extractor-libmpq-build-')
        cls.addClassCleanup(temporary.cleanup);cls.build=Path(temporary.name)
        for name,pin in cls.pin['libraryFiles'].items():
            if adaptation.files.identity(cls.source/name)!=pin:raise ValueError('actual libmpq fixture source differs:'+name)
        includes=['-I'+str(cls.source/'deps/libmpq'),'-I'+str(cls.source/'deps/bzip2')];objects=[]
        for source in sorted((cls.source/'deps/libmpq/libmpq').glob('*.c')):
            target=cls.build/(source.stem+'.o')
            subprocess.run(['gcc','-std=c11','-D_DEFAULT_SOURCE',*includes,'-c',str(source),'-o',str(target)],
                           check=True,capture_output=True,timeout=60);objects.append(str(target))
        cls.executable=cls.build/'order-reference'
        subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',*includes,
            '-I'+str(adaptation.ROOT/'runtime/server/extractor-order'),str(adaptation.ROOT/'tests/extractor_order_reference.cpp'),
            *objects,'-l:libbz2.so.1.0','-lz','-lcrypto','-o',str(cls.executable)],check=True,capture_output=True,timeout=60)
        adapted=cls.build/'adapted'
        for name in cls.pin['baseFiles']:
            target=adapted/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(cls.source/name,target)
        adaptation.apply(adapted,cls.pin);cls.bridges=[]
        for tool in ('map_extractor','vmap4_extractor'):
            target=cls.build/(tool+'-mpqfile-reference')
            subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-Werror',*includes,
                '-I'+str(cls.source/'src/tools'/tool),'-I'+str(cls.source/'src/common'),'-I'+str(adapted/'src/tools'),
                str(adaptation.ROOT/'tests/extractor_mpqfile_reference.cpp'),str(adapted/'src/tools'/tool/'mpq_libmpq.cpp'),
                *objects,'-l:libbz2.so.1.0','-lz','-lcrypto','-o',str(target)],check=True,capture_output=True,timeout=60)
            cls.bridges.append(str(target))

    def setUp(self):
        super().setUp()
        for name in ('Data/common.MPQ','Data/enUS/locale-enUS.MPQ','Data/enUS/speech-enUS.MPQ'):self.archive(name,{})

    def archive(self,name,members):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True)
        source=self.base/('fixture-'+str(len(list(self.base.glob('fixture-*'))))+'.tsv')
        rows=[]
        for logical,value in members.items():
            if isinstance(value,tuple):data,flags,locale,*unpacked=value
            else:data,flags,locale,unpacked=value,0x81000000,0,[]
            fields=[logical,str(flags),str(locale),data.hex() or '-']
            if unpacked:fields.append(str(unpacked[0]))
            rows.append('\t'.join(fields))
        source.write_text('\n'.join(rows)+('\n' if rows else ''))
        subprocess.run([str(self.executable),'--create-fixture',str(path),str(source)],check=True,capture_output=True,timeout=10)
        return path

    def invoke(self,member='World/Maps/Test/Test.wdt',locale='enUS',wire=None,extra=(),sha=None):
        wire=wire if wire is not None else order.wire(self.plan(locale))
        manifest=self.base/'ordered.tsv';manifest.write_bytes(wire)
        args=['--esteria-order',str(manifest),'--esteria-input-root',str(self.root),
              '--esteria-order-sha256',sha or hashlib.sha256(wire).hexdigest(),*extra]
        if member is not None:args+=['--esteria-order-member-probe',member]
        selected=json.loads(os.environ.get('ESTERIA_ORDERED_EXTRACTOR_PROGRAMS','[]')) or self.bridges
        results=[subprocess.run([program,*args],cwd=self.base,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=10)
                 for program in selected]
        for got in results[1:]:self.assertEqual((got.returncode,got.stdout),(results[0].returncode,results[0].stdout),got.stderr)
        return results[0]

    def result(self,member='World/Maps/Test/Test.wdt',locale='enUS'):
        got=self.invoke(member,locale);self.assertEqual(got.returncode,0,got.stderr);return json.loads(got.stdout)

    def test_actual_bootstrap_accepts_data_conversion_argv_without_legacy_input_selectors(self):
        wire=order.wire(self.plan('enUS'));manifest=self.base/'conversion-ordered.tsv';manifest.write_bytes(wire)
        selection=['--esteria-order',str(manifest),'--esteria-input-root',str(self.root),
                   '--esteria-order-sha256',hashlib.sha256(wire).hexdigest()]
        for mode,tail in [('map',['-o','owned-output','-e','7']),('vmap',[])]:
            command=[str(self.executable),'--check-'+mode+'-conversion-argv',*selection,*tail]
            result=subprocess.run(command,capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{'scope':'actual-ordered-bootstrap-only','conversionExecuted':False})
            for legacy in ('-i','-d'):
                rejected=subprocess.run([*command,legacy,str(self.root)],capture_output=True,text=True,timeout=10)
                self.assertNotEqual(rejected.returncode,0)
                self.assertIn('legacy input selection is forbidden',rejected.stderr)

    def test_actual_encrypted_table_mpqs_follow_lexical_order_not_numeric(self):
        logical='World/Maps/Test/Test.wdt'
        self.archive('Data/common.MPQ',{logical:b'base'})
        self.archive('Data/patch-10.MPQ',{logical:b'ten'})
        self.archive('Data/patch-2.MPQ',{logical:b'two'})
        self.assertEqual(self.result()['sha256'],hashlib.sha256(b'two').hexdigest())

    def test_actual_reader_full_capability_c_string_matches_native_packager(self):
        from tools import build_ordered_extractors as build
        programs=json.loads(os.environ.get('ESTERIA_ORDERED_EXTRACTOR_PROGRAMS','[]')) or self.bridges
        expected=self.pin['contract']+build.CAPABILITY_SUFFIX
        for program in programs:
            result=subprocess.run([program,'--esteria-order-capabilities'],capture_output=True,text=True,timeout=10)
            self.assertEqual((result.returncode,result.stdout),(0,expected+'\n'),result.stderr)
            adaptation.engine.modules.verify_literals(Path(program),adaptation.files.identity(Path(program)),[expected])
            with self.assertRaisesRegex(ValueError,'literal absent'):
                adaptation.engine.modules.verify_literals(Path(program),adaptation.files.identity(Path(program)),[self.pin['contract']])

    def test_loose_folder_wins_in_same_order_and_its_case_insensitive_member_is_read(self):
        logical='World/Maps/Test/Test.wdt';self.archive('Data/patch-a.MPQ',{logical:b'archive'})
        self.put('Data/patch-z-extra.MPQ/world/maps/test/test.WDT',b'loose')
        self.assertEqual(self.result()['sha256'],hashlib.sha256(b'loose').hexdigest())

    def test_alternate_prefix_views_outrank_direct_patch_and_alternate_base(self):
        logical='World/Maps/Test/Test.wdt'
        self.archive('Data/alternate.MPQ',{logical:b'alternate-base'})
        self.archive('Data/patch-z.MPQ',{logical:b'direct', 'alternate/'+logical:b'prefixed'})
        self.assertEqual(self.result()['sha256'],hashlib.sha256(b'prefixed').hexdigest())

    def test_tombstone_stops_lower_provider_and_non_neutral_hash_record_is_ignored(self):
        logical='World/Maps/Test/Test.wdt';self.archive('Data/common.MPQ',{logical:b'base'})
        self.archive('Data/patch-a.MPQ',{logical:(b'x',0x83000000,0)})
        got=self.invoke();self.assertEqual(got.returncode,3);self.assertFalse(json.loads(got.stdout)['found'])
        self.archive('Data/patch-a.MPQ',{logical:(b'wrong-locale',0x81000000,1033)})
        self.assertEqual(self.result()['sha256'],hashlib.sha256(b'base').hexdigest())

    def test_zero_and_one_byte_files_do_not_turn_into_fallback_or_tombstones(self):
        logical='World/Maps/Test/Test.wdt';self.archive('Data/common.MPQ',{logical:b'base'})
        for value in (b'',b'x'):
            self.archive('Data/patch-a.MPQ',{logical:value})
            got=self.result();self.assertEqual(got['bytes'],len(value));self.assertEqual(got['sha256'],hashlib.sha256(value).hexdigest())

    def test_decode_failure_and_delta_patch_refuse_instead_of_reading_lower(self):
        logical='World/Maps/Test/Test.wdt';self.archive('Data/common.MPQ',{logical:b'base'})
        self.archive('Data/patch-a.MPQ',{logical:(b'\x02bad',0x81000200,0,20)})
        got=self.invoke();self.assertEqual(got.returncode,2);self.assertIn('decode failed',got.stderr)
        self.archive('Data/patch-a.MPQ',{logical:(b'patch-delta',0x81100000,0)})
        got=self.invoke();self.assertEqual(got.returncode,2);self.assertIn('delta-patch',got.stderr)

    def test_encrypted_member_is_refused_without_falling_back_or_emitting_garbage(self):
        logical='World/Maps/Test/Test.wdt';self.archive('Data/common.MPQ',{logical:b'base'})
        for flags in (0x81010000,0x80010000):
            self.archive('Data/patch-a.MPQ',{logical:(b'encrypted fixture payload',flags,0)})
            got=self.invoke();self.assertEqual(got.returncode,2);self.assertIn('encrypted ordered MPQ members unsupported',got.stderr)

    def test_changed_archive_or_loose_member_and_manifest_sha_never_fall_back(self):
        logical='World/Maps/Test/Test.wdt';archive=self.archive('Data/patch-a.MPQ',{logical:b'a'})
        wire=order.wire(self.plan());archive.write_bytes(archive.read_bytes()+b'changed')
        got=self.invoke(wire=wire);self.assertEqual(got.returncode,2);self.assertIn('size differs',got.stderr)
        archive.unlink();file=self.put('Data/patch-z.MPQ/World/Maps/Test/Test.wdt',b'first')
        wire=order.wire(self.plan());file.write_bytes(b'other')
        got=self.invoke(wire=wire);self.assertEqual(got.returncode,2);self.assertIn('loose file SHA256',got.stderr)
        got=self.invoke(sha='0'*64);self.assertEqual(got.returncode,2);self.assertIn('manifest SHA256 differs',got.stderr)

    def test_new_unlisted_loose_file_is_refused_instead_of_reading_lower_archive(self):
        self.archive('Data/common.MPQ',{'World/Maps/Test/Test.wdt':b'base'})
        self.put('Data/patch-z.MPQ/known.txt',b'known')
        wire=order.wire(self.plan());self.put('Data/patch-z.MPQ/World/Maps/Test/Test.wdt',b'new')
        got=self.invoke(wire=wire);self.assertEqual(got.returncode,2);self.assertIn('folder inventory changed',got.stderr)

    def test_listfile_union_is_case_insensitive_and_excludes_deleted_members(self):
        self.archive('Data/common.MPQ',{'DBFilesClient/Map.dbc':b'base','DBFilesClient/Other.dbc':b'other'})
        self.archive('Data/patch-a.MPQ',{'DBFilesClient/Map.dbc':(b'x',0x83000000,0)})
        self.put('Data/patch-z.MPQ/dbfilesclient/new.DBC',b'new')
        got=self.invoke(member=None,extra=('--esteria-order-list',));self.assertEqual(got.returncode,0,got.stderr)
        self.assertEqual({n.lower() for n in got.stdout.splitlines()},{'dbfilesclient\\other.dbc','dbfilesclient\\new.dbc'})

    def test_separate_patch_replays_only_four_tools_and_retains_default_path(self):
        output=self.base/'source-copy'
        for name in self.pin['baseFiles']:
            target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.source/name,target)
        proof=adaptation.apply(output)
        self.assertFalse(proof['globalServerPatchListChanged']);self.assertFalse(proof['sourceCompanionComplete'])
        for name,row in self.pin['adaptedFiles'].items():self.assertEqual(adaptation.files.identity(output/name),row)
        self.assertTrue((output/'src/tools/EsteriaArchiveOrder.h').is_file())
        self.assertFalse((output/'.git').exists())

    def test_patch_replay_does_not_discover_the_parent_integration_checkout(self):
        with tempfile.TemporaryDirectory(prefix='ordered-patch-child-',dir=adaptation.ROOT) as directory:
            source=Path(directory)/'source';source.mkdir()
            for name in self.pin['baseFiles']:
                target=source/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.source/name,target)
            adaptation.apply(source)
            for name,row in self.pin['adaptedFiles'].items():self.assertEqual(adaptation.files.identity(source/name),row)


if __name__=='__main__':unittest.main()
