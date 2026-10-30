"""Synthetic transactions plus optional exact retained SQL-source readback."""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_server_content as provider
from tests import test_runtime_server_content as fixtures


class ContentProvider(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.RuntimeContent(methodName='runTest');self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.base=self.fixture.base;self.package=self.base/'package';self.package.mkdir()
        self.refresh()

    def refresh(self):
        f=self.fixture
        r=copy.deepcopy(f.receipt)
        for field,name in (('compiledModules','compiled-modules'),('contentManifest','content-manifest'),('luaMap','lua-map')):
            r[field]=provider.files.identity(f.root/('metadata/'+name+'.json'))
        plan={k:v for k,v in r.items() if k not in ('archive','archiveFiles','archiveReadBackVerified','deterministicArchive')}
        (f.root/'metadata/package-plan.json').write_bytes(provider.encoded(plan))
        for name,row in r['archiveFiles'].items():row.update(provider.files.identity(f.root/name))
        archive=self.package/'server-content.tar.gz'
        with archive.open('wb') as raw,gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w|',format=tarfile.GNU_FORMAT) as tar:
                for name,row in sorted(r['archiveFiles'].items()):
                    item=tarfile.TarInfo(name);item.size=row['bytes'];item.mode=0o644
                    with (f.root/name).open('rb') as source:tar.addfile(item,source)
        r['archive']=provider.files.identity(archive)
        receipt=self.package/'package-receipt.json';receipt.write_bytes(provider.encoded(r))
        self.receipt=r
        self.pin=dict(archive=dict(r['archive'],file='server-content.tar.gz'),receipt=provider.files.identity(receipt),
            appSourceLock={'bytes':2170,'sha256':f.lock},serverBuildSourceLock={'bytes':2170,'sha256':f.lock},
            serverBuildSourceLockText='synthetic fixture, not a production source lock',
            serverBuildCompatibility={'fixture':True},serverSource=f.source,compiledModules=r['compiledModules'],
            originalBuild=f.compiled['serverBuild'],requiredFiles={n:r['archiveFiles'][n] for n in provider.content.METADATA},
            archiveEntries=len(r['archiveFiles']),archiveFileBytes=sum(row['bytes'] for row in r['archiveFiles'].values()),
            limits=dict(entries=128,memberBytes=max(row['bytes'] for row in r['archiveFiles'].values()),
                fileBytes=sum(row['bytes'] for row in r['archiveFiles'].values()),pathBytes=4096,metadataBytes=16<<20),
            requiredServerRuntimeArchiveSha256='a'*64)

    def build(self,output=None):
        with patch.object(provider,'load_pin',return_value=self.pin):
            return provider.build(self.package,output or self.base/'provider')

    def test_original_archive_receipt_and_four_required_metadata_are_preserved(self):
        proof=self.build();assets=self.base/'provider/assets/server-content'
        self.assertEqual((assets/provider.ARCHIVE).read_bytes(),(self.package/'server-content.tar.gz').read_bytes())
        self.assertEqual((assets/'package-receipt.json').read_bytes(),(self.package/'package-receipt.json').read_bytes())
        self.assertEqual(set(proof['requiredFiles']),provider.content.METADATA)
        self.assertEqual(proof['scope'],'android-server-content-install-only')
        self.assertFalse(proof['elfIncluded']);self.assertTrue(proof['luaDisabled']);self.assertFalse(proof['sqlExecuted'])

    def test_changed_archive_and_existing_output_do_not_publish_or_overwrite(self):
        target=self.base/'existing';target.mkdir();(target/'marker').write_text('preserved')
        with self.assertRaisesRegex(ValueError,'output-exists'):self.build(target)
        self.assertEqual((target/'marker').read_text(),'preserved')
        archive=self.package/'server-content.tar.gz';archive.write_bytes(archive.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'input-identity'):self.build()
        self.assertFalse((self.base/'provider').exists())

    def test_active_lua_is_rejected_even_with_matching_archive_member_hashes(self):
        path=self.fixture.root/'metadata/lua-map.json'
        lua=json.loads(path.read_bytes());lua['mode']='mapped';path.write_bytes(provider.encoded(lua));self.refresh()
        with self.assertRaisesRegex(ValueError,'disabled Lua'):self.build()

    def test_other_compiled_build_cannot_be_rebound_to_same_source_names(self):
        self.pin['originalBuild']={'bytes':1,'sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'compiled-build-selection'):self.build()

    def test_elf_bytes_are_never_accepted_as_plain_source_content(self):
        name='source/LICENSE';path=self.fixture.root/name;path.write_bytes(b'\x7fELFsynthetic fixture')
        self.refresh()
        with self.assertRaisesRegex(ValueError,'hash-or-ELF'):self.build()

    def apk(self,compression=zipfile.ZIP_STORED,changed_receipt=False):
        path=self.base/('compressed.apk' if compression else 'stored.apk')
        assets=self.base/'provider/assets/server-content'
        with zipfile.ZipFile(path,'w') as archive:
            for item in assets.iterdir():
                raw=item.read_bytes()+(b'changed' if changed_receipt and item.name=='package-receipt.json' else b'')
                archive.writestr('assets/server-content/'+item.name,raw,
                    compress_type=compression if item.name==provider.ARCHIVE else zipfile.ZIP_DEFLATED)
        return path

    def test_final_apk_verifies_all_original_assets_and_requires_stored_archive(self):
        self.build()
        with patch.object(provider,'load_pin',return_value=self.pin):
            self.assertTrue(provider.verify(self.base/'provider',self.apk())['apkBytesVerified'])
            with self.assertRaisesRegex(ValueError,'must-be-stored'):
                provider.verify(self.base/'provider',self.apk(zipfile.ZIP_DEFLATED))
            with self.assertRaisesRegex(ValueError,'asset-size'):
                provider.verify(self.base/'provider',self.apk(changed_receipt=True))


@unittest.skipUnless(os.environ.get('ESTERIA_SERVER_CONTENT_PACKAGE'),'exact original source package not supplied')
class ActualOriginalContent(unittest.TestCase):
    def test_actual_complete_4063_member_source_and_notice_inventory(self):
        package=Path(os.environ['ESTERIA_SERVER_CONTENT_PACKAGE']).resolve(strict=True)
        proof=provider.descriptor(package,provider.load_pin())
        self.assertEqual(proof['archiveEntries'],4063);self.assertEqual(proof['archiveFileBytes'],654243888)
        self.assertEqual(proof['archive']['sha256'],'0f41b2deea5344fcea4cbc70bbddf0bab1dfda1cd0346e23e92592aac63056e6')
        self.assertTrue(proof['originalNoticesPreserved']);self.assertFalse(proof['sqlExecuted'])


if __name__=='__main__':unittest.main()
