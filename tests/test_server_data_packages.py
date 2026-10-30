"""Real files/storage only. Synthetic headers never qualify usable world data."""
import errno
import hashlib
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
from runtime import server_data_generation as data
from tests import test_server_data_generation as fixtures


def dbc(fields=66, stride=264, value=0):
    return struct.pack('<4s4I', b'WDBC', 1, fields, stride, 1) + value.to_bytes(stride, 'little') + b'\0'


class SuppliedDataTests(unittest.TestCase):
    setUp = fixtures.ServerDataGenerationTests.setUp
    generate = fixtures.ServerDataGenerationTests.generate
    fake_execute = fixtures.ServerDataGenerationTests.fake_execute

    def package(self, mode='overlay', files=None, order='none'):
        namespace = self.import_root / 'data/EsteriaServerData'; namespace.mkdir(exist_ok=True)
        manifest = ('format=1\nscope=esteria-user-supplied-server-data\nserverRevision=' + data.formats.SERVER_REVISION +
            '\nclientBuild=12340\nmode=' + mode + '\nprovenance=user-supplied-format-checked\nclientProviderOrderSha256=' + order + '\n')
        (namespace / 'manifest.properties').write_text(manifest)
        payload = namespace / 'data'; payload.mkdir(exist_ok=True)
        selected = files if files is not None else {'dbc/Map.dbc': dbc(value=7)}
        for name, raw in selected.items():
            target = payload / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        return namespace

    def full(self):
        return {'dbc/Map.dbc': dbc(value=7),
            'maps/0000000.map': struct.pack('<4s10I', b'MAPS', 9, 12340, *([0]*8)),
            'Cameras/test.m2': b'MD20' + struct.pack('<I',264),
            'vmaps/000.vmtree': b'VMAP_4.8', 'mmaps/000.mmap': b'\0'*28}

    def prior(self):
        self.store.mkdir(); (self.store/'current').write_text('f'*64+'\n')

    def test_complete_declared_format_checked_input_skips_all_conversion_and_keeps_source_scope(self):
        payload=self.full();self.package('complete',payload)
        with patch.object(data,'execute',side_effect=AssertionError('complete external data must not run conversion')):
            proof=self.generate()
        self.assertEqual(proof['inputs']['formatVersion'],2)
        self.assertEqual(proof['inputs']['serverDataPackage']['scope'],'user-supplied-format-checked')
        self.assertEqual(proof['inputs']['preparationHelperGeneration'],data.preparation_helper_generation())
        self.assertFalse(proof['worldQualified']);self.assertFalse(proof['androidQualified']);self.assertFalse(proof['gameplayQualified'])
        root=self.store/'generations'/proof['generation']/'data'
        self.assertEqual({n:(root/n).read_bytes() for n in payload},payload)

    def test_overlay_preserves_base_phase_bytes_and_separate_continuation_directory(self):
        supplied={'dbc/Map.dbc':dbc(value=99),'dbc-continuations/Map.dbc1-new':dbc(value=123),
            'dbc-continuations/wxl-dbc.manifest':b'Map.dbc1-new\n'}
        self.package(files=supplied)
        with patch.object(data,'execute',side_effect=self.fake_execute):proof=self.generate()
        root=self.store/'generations'/proof['generation']/'data'
        self.assertEqual((root/'dbc/Map.dbc').read_bytes(),supplied['dbc/Map.dbc'])
        self.assertEqual((root/'dbc-continuations/Map.dbc1-new').read_bytes(),supplied['dbc-continuations/Map.dbc1-new'])
        original=self.store/'staging'/proof['generation']/'maps-dbc-cameras-complete/data/dbc/Map.dbc'
        self.assertEqual(original.read_bytes(),struct.pack('<4s4I',b'WDBC',0,66,264,1)+b'\0')
        self.assertEqual(proof['preflight']['continuations']['order'],['Map.dbc1-new'])

    def test_replacement_import_generation_never_reuses_prior_continuations(self):
        self.package(files={'dbc-continuations/Map.dbc1-old':dbc(value=1)})
        with patch.object(data,'execute',side_effect=self.fake_execute):first=self.generate()
        self.generation='e'*64;self.import_root=self.game/'generations'/self.generation
        (self.import_root/'data').mkdir(parents=True)
        (self.import_root/'complete').write_text('format=1\nclientBuild=12340\nrequest='+self.generation+'\nsource='+'b'*64+'\n')
        (self.import_root/'journal.tsv').write_text('new private synthetic importer record\n')
        (self.game/'current').write_text(self.generation+'\n')
        self.package(files={'dbc/Map.dbc':dbc(value=2)})
        with patch.object(data,'execute',side_effect=self.fake_execute):second=self.generate()
        self.assertNotEqual(first['generation'],second['generation'])
        self.assertFalse((self.store/'generations'/second['generation']/'data/dbc-continuations').exists())
        self.assertTrue((self.store/'generations'/first['generation']/'data/dbc-continuations/Map.dbc1-old').is_file())

    def test_invalid_source_manifest_missing_complete_groups_and_wrong_client_binding_preserve_active(self):
        self.prior();namespace=self.package('complete')
        for change in ('incomplete','foreign-server','foreign-client-order'):
            with self.subTest(change=change):
                self.package('complete',self.full() if change!='incomplete' else {},order='0'*64 if change=='foreign-client-order' else 'none')
                path=namespace/'manifest.properties'
                if change=='foreign-server':path.write_text(path.read_text().replace(data.formats.SERVER_REVISION,'0'*40))
                with patch.object(data,'execute',side_effect=AssertionError('invalid supplied input executed')):
                    with self.assertRaises(ValueError):self.generate()
                self.assertEqual((self.store/'current').read_text(),'f'*64+'\n')

    def test_known_continuation_wrong_layout_refuses_before_conversion_or_promotion(self):
        self.prior();self.package(files={'dbc-continuations/Map.dbc1-new':dbc(fields=2,stride=8)})
        with patch.object(data,'execute',side_effect=AssertionError('wrong known layout must refuse before conversion')),\
                self.assertRaisesRegex(ValueError,'pinned server DBC layout'):
            self.generate()
        self.assertEqual((self.store/'current').read_text(),'f'*64+'\n')

    def test_complete_cache_does_not_reinspect_source_payload_or_execute_and_helper_changes_invalidate(self):
        self.package('complete',self.full())
        with patch.object(data,'execute',side_effect=AssertionError('complete data executes no extractor')):
            first=self.generate()
            with patch.object(data.formats,'check_server_package',side_effect=AssertionError('unchanged immutable payload rescanned')):
                second=self.generate()
            self.assertEqual(first,second)
            with patch.object(data,'preparation_helper_generation',return_value='9'*64):third=self.generate()
        self.assertNotEqual(first['generation'],third['generation'])
        self.assertTrue((self.store/'generations'/first['generation']).is_dir())

    def test_provider_order_binding_and_receipt_source_selection_are_exact(self):
        order=hashlib.sha256(data.order.canonical(self.plan)).hexdigest();self.package('complete',self.full(),order)
        proof=self.generate();root=self.store/'generations'/proof['generation']
        self.assertEqual(proof['inputs']['serverDataPackage']['clientProviderOrderSha256'],order)
        changed=dict(proof['inputs']);changed['preparationHelperGeneration']='0'*64
        with self.assertRaisesRegex(ValueError,'generation/source selection'):
            data.verify_completed(root,changed)

    def test_copy_fallback_cancellation_never_overwrites_existing_target(self):
        source=self.root/'source';target=self.root/'target';source.mkdir();target.mkdir()
        (source/'data').write_bytes(b'new'*100000);(target/'data').write_bytes(b'old')
        checks=0
        def cancelled():
            nonlocal checks;checks+=1;return checks>=4
        with patch.object(data.os,'link',side_effect=OSError(errno.EPERM,'fixture denied')):
            with self.assertRaisesRegex(ValueError,'cancelled'):data.merge_supplied(source,target,cancelled=cancelled)
        self.assertEqual((target/'data').read_bytes(),b'old')
        self.assertEqual({path.name for path in target.iterdir()},{'data'})

    def test_continuation_manifest_uses_source_tier_then_explicit_order_and_refuses_ambiguous_paths(self):
        root=self.root/'continuations';base=self.root/'dbc';root.mkdir();base.mkdir()
        (base/'Map.dbc').write_bytes(dbc())
        for name in ('Map.dbc1-z','Map.dbc1-a','Map.dbc2-a'):(root/name).write_bytes(dbc())
        (root/'wxl-dbc.manifest').write_text('Map.dbc2-a\nMap.dbc1-z\nMap.dbc1-a\n')
        checked=data.formats.continuation_order(root,base)
        self.assertEqual(checked['order'],['Map.dbc1-z','Map.dbc1-a','Map.dbc2-a'])
        (root/'nested').mkdir();(root/'nested/Map.dbc1-a').write_bytes(dbc())
        (root/'wxl-dbc.manifest').unlink()
        with self.assertRaisesRegex(ValueError,'ambiguous continuation order'):data.formats.continuation_order(root,base)
        for unsafe in ('../Map.dbc1-a','/Map.dbc1-a','missing.dbc1-a'):
            (root/'wxl-dbc.manifest').write_text(unsafe+'\n')
            with self.subTest(unsafe=unsafe),self.assertRaisesRegex(ValueError,'unsafe or absent'):
                data.formats.continuation_order(root,base)

    def test_manifest_text_controls_cannot_change_source_line_boundaries(self):
        namespace=self.package();raw=(namespace/'manifest.properties').read_bytes()
        for changed in (raw.replace(b'\n',b'\r'),raw.replace(b'\n',b'\v',1),raw.replace(b'\n',b'\f',1)):
            with self.subTest(changed=changed[:25]),self.assertRaises(ValueError):data.formats.parse_server_manifest(changed)
        self.assertEqual(data.formats.parse_server_manifest(raw.replace(b'\n',b'\r\n'))['mode'],'overlay')
        root=namespace/'data/dbc-continuations';root.mkdir()
        (root/'Map.dbc1-a').write_bytes(dbc())
        for invalid in (b'\rMap.dbc1-a\n',b'Map.dbc1-a\v\n',b'Map.dbc1-a\rMap.dbc1-a\n'):
            (root/'wxl-dbc.manifest').write_bytes(invalid)
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):data.formats.continuation_order(root,namespace/'data/dbc')


if __name__=='__main__':unittest.main()
