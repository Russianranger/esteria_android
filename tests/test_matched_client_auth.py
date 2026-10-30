import copy
import hashlib
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest import mock
import zipfile
from tools import prepare_matched_client_auth as selected
from tools import qualify_client_auth as auth


class MatchedInputs(unittest.TestCase):
    def test_separate_selection_matches_actual_current_component_and_seven_patch_programs(self):
        pin,digest=selected.inputs()
        self.assertEqual(len(digest),64)
        self.assertEqual(pin['clientInput']['sourceRevision'],'471ee42faadf4a97a1d0a86989cf1452621f2dc5')
        self.assertFalse(pin['thisTupleCompiledAuthQualified'])
        self.assertEqual(pin['server']['programs']['authserver']['bytes'],1709864)

    def test_changed_client_component_or_runtime_cannot_reuse_prior_gates(self):
        pin,_=selected.inputs();raw=selected.client.small
        for change in ('client','runtime','qualified'):
            bad=copy.deepcopy(pin)
            if change=='client':bad['clientInput']['sourceRevision']='a'*40
            elif change=='runtime':bad['runtimeArchiveSha256']='0'*64
            else:bad['thisTupleCompiledAuthQualified']=True
            def read(path,*args):return json.dumps(bad).encode() if path==selected.LOCK else raw(path,*args)
            with self.subTest(change=change),mock.patch.object(selected.client,'small',side_effect=read),self.assertRaises(ValueError):
                selected.inputs()

    def test_existing_output_is_preserved_before_api_or_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);(output/'sentinel').write_text('preserve');api=mock.Mock()
            with self.assertRaises(ValueError):selected.fetch(output,api)
            api.json.assert_not_called();self.assertEqual((output/'sentinel').read_text(),'preserve')

    def test_whole_archive_identity_precedes_zip_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/'input.zip';path.write_bytes(b'not-a-zip')
            with mock.patch.object(selected.client,'checked_zip',side_effect=AssertionError('unverified input parsed')):
                with self.assertRaises(ValueError):selected.extract(path,root/'output',{'artifact':dict(bytes=9,sha256='0'*64)})
            self.assertFalse((root/'output').exists())

    def test_unsafe_or_link_members_are_refused_before_engine_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for number,(name,mode) in enumerate((('server-engine-package/../../escape',stat.S_IFREG|0o444),
                                                ('server-engine-package/package-receipt.json',stat.S_IFLNK|0o777))):
                path=root/str(number)
                with zipfile.ZipFile(path,'w') as archive:
                    item=zipfile.ZipInfo(name);item.create_system=3;item.external_attr=mode<<16;archive.writestr(item,b'x')
                with mock.patch.object(selected.engine,'extract',side_effect=AssertionError('unsafe extraction reached engine')):
                    with self.assertRaises(ValueError):selected.extract(path,root/('output'+str(number)),{'artifact':selected.client.identity(path)})
            self.assertFalse((root/'escape').exists())

    def test_candidate_private_pe_profile_requires_explicit_selection_before_receipt_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile=auth.wine.PRIVATE_PE_ENVIRONMENT
            with mock.patch.object(auth.wine,'runtime_selection',return_value=({},'a'*64,{'wineEnvironment':profile},{})), \
                    mock.patch.object(auth.wine,'read_json',side_effect=AssertionError('profile not selected')), \
                    self.assertRaisesRegex(ValueError,'profile-must-be-selected'):
                auth.prepared_wine(Path(tmp),Path('/selected'),False)

    def test_prepared_candidate_profile_keeps_bound_components_and_preparer_readback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'rootfs').mkdir();(root/'rootfs/component').write_bytes(b'actual')
            package=dict(archive={'sha256':'a'*64},manifest={'sha256':'b'*64},wineEnvironment=auth.wine.PRIVATE_PE_ENVIRONMENT,
                         components={'component':dict(bytes=6,sha256=hashlib.sha256(b'actual').hexdigest())})
            receipt=dict(archiveSha256='a'*64,manifestSha256='b'*64,
                packagePinSha256=hashlib.sha256(json.dumps(package,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                preparerSha256=hashlib.sha256(Path(auth.client.archives.__file__).read_bytes()).hexdigest(),
                archiveExtracted=True,stagedFilesReadBack=True)
            with mock.patch.object(auth.wine,'runtime_selection',return_value=({},'c'*64,package,auth.wine.PRIVATE_PE_ENVIRONMENT)), \
                    mock.patch.object(auth.wine,'read_json',return_value=(receipt,'d'*64)):
                result=auth.prepared_wine(root,Path('/selected'),True)
                self.assertEqual(result['wineEnvironment'],{'WINE_ANDROID_PRIVATE_PE_COPY':'1'})
                (root/'rootfs/component').write_bytes(b'tamper')
                with self.assertRaises(ValueError):auth.prepared_wine(root,Path('/selected'),True)


if __name__=='__main__':unittest.main()
