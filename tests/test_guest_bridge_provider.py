import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import provider_guest_bridges as provider


class GuestBridgeProvider(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.output=self.root/'provider';self.lock=self.root/'pin.json'
        self.payload={}
        def add(path,data):self.payload[path]=data
        source='guest-bridges/fixture.c';source_data=b'/* test-only source */\n'
        add(provider.SHARE+'corresponding-source/'+source,source_data)
        sources=[dict(package='libxtst',version='fixture',archives=[dict(file=name,**provider.identity(data))
                for name,data in [('source.tar.gz',b'original'),('source.diff.gz',b'changes'),('source.dsc',b'metadata')]])]
        for name,data in [('source.tar.gz',b'original'),('source.diff.gz',b'changes'),('source.dsc',b'metadata')]:
            add(provider.SHARE+'corresponding-source/original-archives/'+name,data)
        source_lock=dict(runtimeArchiveSha256='f'*64,packages=[dict(package='compiler',version='test')],sources=sources)
        add(provider.SOURCE_LOCK,provider.encoded(source_lock))
        manifest=dict(formatVersion=1,scope='original-archives-for-locked-direct-build-and-static-link-inputs',completeGuestRootfsSourceClosure=False,
                      files=[dict(package=s['package'],version=s['version'],**a) for s in sources for a in s['archives']])
        add(provider.SHARE+'corresponding-source/original-archives/SOURCE-MANIFEST.json',provider.encoded(manifest))
        binaries={}
        for name,path in provider.BINARY_PATHS.items():
            data=b'\x7fELF-synthetic-guard-test-'+name.encode();add(path,data)
            binaries[name]=dict(provider.identity(data),architecture='arm64',needed=['libc.so.6'],maxGlibc='2.17',interpreter=None)
        receipt=dict(formatVersion=1,scope='linux-arm64-guest-bridge-build-only',integrationRevision='a'*40,
                     inputLockSha256=provider.identity(self.payload[provider.SOURCE_LOCK])['sha256'],runtimeArchiveSha256='f'*64,
                     binaries=binaries,sources={source:provider.identity(source_data)},selectedPackages={'compiler':'test'},compiled=True,
                     guestExecutionQualified=False,androidQualified=False,gameAudioQualified=False,presentationQualified=False,inputQualified=False)
        add(provider.RECEIPT,provider.encoded(receipt))
        current=self.root/'native'/source;current.parent.mkdir(parents=True);current.write_bytes(source_data)
        self.artifact=self.root/'artifact.zip'
        with zipfile.ZipFile(self.artifact,'w') as z:
            for name,data in self.payload.items():z.writestr('export/'+name,data)
        self.pin=dict(formatVersion=1,scope='measured-guest-bridge-provider-inputs',integrationRevision='a'*40,
                      artifact=dict(id=1,**provider.identity(self.artifact.read_bytes())),androidRuntimeQualified=False,
                      files={name:dict(zipEntry='export/'+name,payloadPath=name,**provider.identity(data)) for name,data in self.payload.items()},
                      repositoryInputs={'native/'+source:dict(installedPath=provider.SHARE+'corresponding-source/'+source,**provider.identity(source_data))})
        self.lock.write_bytes(provider.encoded(self.pin))
        self.patches=[patch.object(provider,'LOCK',self.lock),patch.object(provider,'ROOT',self.root),
                      patch.object(provider,'elf',side_effect=lambda path:dict(binaries[path.name],**provider.identity(path.read_bytes())))]
        for item in self.patches:item.start();self.addCleanup(item.stop)

    def test_deterministic_build_and_full_required_inventory(self):
        first=provider.build(self.artifact,self.output)
        second=provider.build(self.artifact,self.root/'second')
        self.assertEqual(first,second)
        rebuilt=self.root/'rebuilt';rebuilt.mkdir()
        for name,data in self.payload.items():
            path=rebuilt/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.assertEqual(first,provider.build(None,self.root/'rebuilt-provider',rebuilt))
        self.assertEqual(first['archiveEntries'],len(self.payload)+len(provider.GENERATED))
        self.assertEqual(first['archiveEntries'],len(first['requiredFiles']))
        self.assertFalse(first['androidRuntimeQualified']);self.assertFalse(first['gameAudioQualified'])
        self.assertTrue(provider.verify(self.output)['providerVerified'])
        with self.assertRaisesRegex(ValueError,'output-exists'):provider.build(self.artifact,self.output)

    def test_modified_artifact_and_source_fail_before_publication(self):
        self.artifact.write_bytes(self.artifact.read_bytes()+b'changed')
        with self.assertRaisesRegex(ValueError,'artifact-identity'):provider.build(self.artifact,self.output)
        self.assertFalse(self.output.exists())
        (self.root/'native/guest-bridges/fixture.c').write_bytes(b'new source')
        with self.assertRaisesRegex(ValueError,'source-input-changed'):provider.load_pin()

    def test_altered_receipt_cannot_promote_execution_or_replace_binary(self):
        payload=dict(self.payload,**provider.GENERATED)
        row=json.loads(payload[provider.RECEIPT]);row['androidQualified']=True
        payload[provider.RECEIPT]=provider.encoded(row)
        with self.assertRaisesRegex(ValueError,'file-identity'):provider.validate_payload(payload,self.pin)
        with patch.object(provider,'elf',return_value={'architecture':'x86_64'}):
            with self.assertRaisesRegex(ValueError,'elf-receipt'):provider.validate_payload(dict(self.payload,**provider.GENERATED),self.pin)

    def test_archive_rejects_links_duplicate_and_traversal(self):
        for kind in ('link','duplicate','traversal'):
            path=self.root/(kind+'.tar.gz')
            with tarfile.open(path,'w:gz',format=tarfile.GNU_FORMAT) as t:
                item=tarfile.TarInfo('../escape' if kind=='traversal' else 'file');item.mode=0o644
                if kind=='link':item.type=tarfile.SYMTYPE;item.linkname='/tmp/escape'
                t.addfile(item)
                if kind=='duplicate':t.addfile(item)
            with self.assertRaises(ValueError):provider.read_archive(path)

    def test_descriptor_and_apk_integrity_and_storage_policy(self):
        provider.build(self.artifact,self.output)
        assets=self.output/'assets'/provider.ASSET_DIR
        for compression in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED):
            apk=self.root/(str(compression)+'.apk')
            with zipfile.ZipFile(apk,'w',compression=compression) as z:
                for path in assets.iterdir():z.write(path,str(path.relative_to(self.output)))
            if compression==zipfile.ZIP_STORED:self.assertTrue(provider.verify(self.output,apk)['apkBytesVerified'])
            else:
                with self.assertRaisesRegex(ValueError,'uncompressed-in-apk'):provider.verify(self.output,apk)
        proof=assets/'provider.json';proof.write_bytes(proof.read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'metadata-mismatch'):provider.verify(self.output)


if __name__=='__main__':unittest.main()
