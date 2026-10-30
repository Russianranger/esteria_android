import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import tarfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
from tools import package_android_wine_sources as sources
from tools import fetch_android_wine_probe as acquire


def identity(data):
    return dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())


class WineSources(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def fixture(self,change=None,adapted=False):
        runtime_raw=b'{"scope":"synthetic-unexecuted"}\n'
        runtime=dict(packages=[dict(sourcePackage='base',sourceVersion='1')])
        payload={};rows=[]
        for name in ('base','builder'):
            original=(name+' synthetic source bytes').encode();archive=name+'_1.orig.tar.xz'
            dsc=('Source: '+name+'\nVersion: 1\nChecksums-Sha256:\n '+identity(original)['sha256']+' '+
                 str(len(original))+' '+archive+'\n').encode()
            for file,data in ((archive,original),(name+'_1.dsc',dsc)):
                payload['debian/'+file]=data;rows.append(dict(file=file,**identity(data)))
        wine=b'unexecuted original Wine fixture';license=b'fixture license'
        lock=dict(wine=dict(sourceArchive=identity(wine),licenseFileSha256=identity(license)['sha256']))
        if adapted:
            patch_bytes=b'exact synthetic Wine patch';fixture_bytes=b'exact synthetic PE fixture'
            lock['wine']['androidPrivatePeCopy']=dict(environment={'WINE_ANDROID_PRIVATE_PE_COPY':'1'},
                patches=[dict(file='image.patch',**identity(patch_bytes))],testSources={'fixture.c':identity(fixture_bytes)})
            payload['wine/android-private-pe-copy/image.patch']=patch_bytes
            payload['wine/android-private-pe-copy/fixture.c']=fixture_bytes
        raw=json.dumps(lock).encode();lock_path=self.root/'sources.lock.json';lock_path.write_bytes(raw)
        manifest=dict(formatVersion=1,scope='installed-debian-runtime-and-wine-build-corresponding-sources',
                      sourceLockSha256=identity(raw)['sha256'],runtimeManifestSha256=identity(runtime_raw)['sha256'],
                      sourcePackages=[dict(package=name,version='1') for name in ('base','builder')],
                      files=rows,fileBytes=sum(row['bytes'] for row in rows))
        payload.update({'wine/wine-arm64ec-source.tar.gz':wine,'wine/Wine-COPYING.LIB':license,
                        'wine/wine-build-config.log':b'fixture configure arguments',
                        'wine/build-packages.tsv':b'builder\t1\tamd64\tbuilder\t1\n',
                        'wine/runtime.json':runtime_raw,'debian/runtime.json':runtime_raw,'debian/sources.lock.json':raw,
                        'integration-source.tar':b'fixture git tree','integration-revision.txt':b'a'*40+b'\n'})
        if change:change(payload,manifest)
        payload['debian/SOURCE-MANIFEST.json']=json.dumps(manifest).encode()
        archive=self.root/'sources.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for name,data in payload.items():z.writestr(name,data)
        pin=dict(sourcesArtifact=sources.identity(archive),sourceManifest=identity(payload['debian/SOURCE-MANIFEST.json']),sourceRevision='a'*40)
        return archive,pin,runtime_raw,runtime,lock_path

    def check(self,change=None,adapted=False):
        archive,pin,raw,runtime,lock=self.fixture(change,adapted)
        with patch.object(sources.wine.runtime,'LOCK',lock),patch.object(sources.wine.runtime,'metadata',return_value=(runtime,{})):
            return sources.runtime_sources(archive,pin,raw)

    def test_full_runtime_and_build_source_union_readback(self):
        result=self.check();self.assertEqual(result['sourcePackages'],2);self.assertEqual(result['originalDebianFiles'],4)
        self.assertTrue(result['allFilesReadBack'])

    def test_missing_build_sources_do_not_become_runtime_only_success(self):
        def remove(payload,manifest):
            manifest['sourcePackages']=manifest['sourcePackages'][:1]
        with self.assertRaisesRegex(ValueError,'package-provenance'):self.check(remove)

    def test_descriptor_requires_exact_original_source_archive(self):
        def modify(payload,manifest):
            payload['debian/base_1.orig.tar.xz']=b'X'*len(payload['debian/base_1.orig.tar.xz'])
        with self.assertRaisesRegex(ValueError,'hash-mismatch'):self.check(modify)

    def test_missing_descriptor_and_private_extra_rejected(self):
        def missing(payload,manifest):
            payload.pop('debian/builder_1.dsc');manifest['files']=[r for r in manifest['files'] if r['file']!='builder_1.dsc']
            manifest['fileBytes']=sum(r['bytes'] for r in manifest['files'])
        with self.assertRaisesRegex(ValueError,'package-closure'):self.check(missing)
        def extra(payload,manifest):payload['private-key']=b'not permitted'
        with self.assertRaisesRegex(ValueError,'unexpected-or-missing'):self.check(extra)

    def test_build_source_revision_cannot_be_relabelled(self):
        def modify(payload,manifest):payload['integration-revision.txt']=b'b'*40+b'\n'
        with self.assertRaisesRegex(ValueError,'wrapper-content'):self.check(modify)

    def test_adaptation_patch_and_test_source_closure_is_exact(self):
        good=self.check(adapted=True)
        self.assertIn('wine/android-private-pe-copy/image.patch',good['wrappers'])
        def corrupt(payload,manifest):
            key='wine/android-private-pe-copy/image.patch';payload[key]=b'X'*len(payload[key])
        with self.assertRaisesRegex(ValueError,'hash-mismatch'):self.check(corrupt,adapted=True)
        def missing(payload,manifest):payload.pop('wine/android-private-pe-copy/fixture.c')
        with self.assertRaisesRegex(ValueError,'unexpected-or-missing'):self.check(missing,adapted=True)

    def test_zip64_directory_is_bounded_and_readable(self):
        archive,pin,raw,runtime,lock=self.fixture()
        data=archive.read_bytes();eocd=data[-22:];values=struct.unpack_from('<4H2IH',eocd,4)
        disk,first,disk_count,count,length,start,comment=values;position=len(data)-22
        record=b'PK\x06\x06'+struct.pack('<Q2H2I4Q',44,45,45,0,0,disk_count,count,length,start)
        locator=b'PK\x06\x07'+struct.pack('<IQI',0,position,1)
        end=b'PK\x05\x06'+struct.pack('<4H2IH',0,0,65535,65535,0xffffffff,0xffffffff,0)
        archive.write_bytes(data[:-22]+record+locator+end)
        with sources.source_zip(archive) as (z,members):self.assertIn('debian/SOURCE-MANIFEST.json',members)
        corrupt=bytearray(archive.read_bytes());struct.pack_into('<Q',corrupt,position+40,3*1024**2);archive.write_bytes(corrupt)
        with self.assertRaisesRegex(ValueError,'central-directory-limit'):
            with sources.source_zip(archive):pass

    def test_existing_output_never_overwritten(self):
        output=self.root/'existing';output.mkdir();marker=output/'save';marker.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'existing-files-preserved'):sources.seal(SimpleNamespace(output=output))
        self.assertEqual(marker.read_bytes(),b'keep')

    def test_artifact_selection_requires_same_successful_run_and_exact_bytes(self):
        run=dict(id=123,head_sha='a'*40,status='completed',conclusion='success')
        artifact=dict(id=456,expired=False,workflow_run=dict(id=123,head_sha='a'*40),size_in_bytes=100,digest='sha256:'+'b'*64)
        api=SimpleNamespace(json=lambda path:run if '/runs/' in path else artifact)
        pin=dict(bytes=100,sha256='b'*64)
        acquire.successful_input(api,123,'a'*40,456,pin)
        for target,key,value in ((run,'conclusion','failure'),(run,'head_sha','c'*40),(artifact,'expired',True),
                                 (artifact,'size_in_bytes',101),(artifact,'digest','sha256:'+'c'*64),
                                 (artifact,'workflow_run',dict(id=999,head_sha='a'*40))):
            old=target[key];target[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):acquire.successful_input(api,123,'a'*40,456,pin)
            target[key]=old


@unittest.skipUnless(os.environ.get('ESTERIA_PROOT_PROBE_BUILD'),'requires actual source-built x64 probe')
class ActualProotSources(unittest.TestCase):
    def test_complete_actual_originals_recipes_and_relink_objects(self):
        build=Path(os.environ['ESTERIA_PROOT_PROBE_BUILD'])
        result=sources.proot_sources(build/'corresponding-source.tar.gz',build/'provider')
        self.assertGreaterEqual(result['relinkableX64Objects'],1);self.assertTrue(result['allFilesReadBack'])

    def test_same_machine_object_body_mutation_and_missing_object_are_rejected(self):
        build=Path(os.environ['ESTERIA_PROOT_PROBE_BUILD'])
        for remove in (False,True):
            with self.subTest(remove=remove),tempfile.TemporaryDirectory() as temporary:
                changed=Path(temporary)/'changed.tar.gz';found=False
                with tarfile.open(build/'corresponding-source.tar.gz','r|gz') as incoming,tarfile.open(str(changed),'w|gz') as outgoing:
                    for item in incoming:
                        if item.name=='talloc-relinkable-objects/talloc.c.5.o':
                            found=True
                            if remove:continue
                            body=bytearray(incoming.extractfile(item).read());body[-1]^=1
                            outgoing.addfile(item,io.BytesIO(body))
                        else:outgoing.addfile(item,incoming.extractfile(item) if item.isfile() else None)
                        incoming.members.clear()
                self.assertTrue(found)
                with self.assertRaisesRegex(ValueError,'object-build-identity|relink-closure-incomplete'):
                    sources.proot_sources(changed,build/'provider')


if __name__=='__main__':unittest.main()
