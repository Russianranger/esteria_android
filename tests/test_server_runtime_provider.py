import copy
import hashlib
import json
from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch
import zipfile

from tests import test_server_runtime_package as fixtures
from tools import provider_server_runtime as provider


class ServerProvider(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ServerRuntimePackage();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.fixture.archive(extra=[('mysql-copy', (tarfile.LNKTYPE, 'usr/bin/mysql'))])
        receipt=self.fixture.execute();self.package=self.fixture.output
        def pin(path):
            data=path.read_bytes();return dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        self.lock=self.root/'provider-lock.json'
        self.lock.write_bytes(provider.encoded(dict(formatVersion=1,scope='measured-server-runtime-provider-inputs',
            archive=receipt['archive'],archiveEntries=receipt['archiveEntries'],archiveFileBytes=receipt['archiveFileBytes'],
            packageReceipt=pin(self.package/'package-receipt.json'),runtimeMetadata=pin(self.package/'server-runtime.json'),
            sourceLock=pin(self.package/'sources.lock.json'),sourceCompanion=dict(scope='synthetic-test-only'),androidRuntimeQualified=False)))
        self.patches=[patch.object(provider,'LOCK',self.lock),patch.object(provider,'SOURCE_LOCK',self.fixture.lock)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        self.output=self.root/'provider'

    def test_build_binds_complete_archive_and_hardlink_copy_budget(self):
        proof=provider.build(self.package,self.output)
        self.assertEqual(proof['maximumHardLinkCopies'],1)
        self.assertEqual(proof['maximumHardLinkCopyBytes'],len(self.fixture.elf))
        self.assertEqual(proof['maximumPhysicalFileBytes'],proof['archiveFileBytes']+len(self.fixture.elf))
        self.assertEqual(proof['freshSetupFreeBytes'],proof['archive']['bytes']+proof['maximumPhysicalFileBytes']+proof['limits']['metadataBytes']+(64<<20))
        self.assertFalse(proof['androidRuntimeQualified'])
        self.assertTrue(provider.verify(self.output)['providerVerified'])
        with self.assertRaisesRegex(ValueError,'output-exists'):provider.build(self.package,self.output)

    def test_tampered_receipt_cannot_authorize_modified_archive(self):
        path=self.package/'package-receipt.json';row=json.loads(path.read_text());row['archive']['sha256']='0'*64;path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'identity-mismatch'):provider.build(self.package,self.output)
        self.assertFalse(self.output.exists())

    def test_changed_source_lock_and_provider_descriptor_fail(self):
        provider.build(self.package,self.output)
        descriptor=self.output/'assets/server-runtime/provider.json';descriptor.write_text(descriptor.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'descriptor-or-notice'):provider.verify(self.output)
        self.fixture.lock.write_text(self.fixture.lock.read_text()+' ')
        with self.assertRaisesRegex(ValueError,'source-lock-changed'):provider.verify(self.output)

    def test_apk_requires_exact_uncompressed_archive_and_complete_metadata(self):
        provider.build(self.package,self.output)
        for compressed in (False,True):
            apk=self.root/('compressed.apk' if compressed else 'stored.apk')
            with zipfile.ZipFile(apk,'w',compression=zipfile.ZIP_DEFLATED if compressed else zipfile.ZIP_STORED) as z:
                for path in (self.output/'assets/server-runtime').iterdir():z.write(path,str(path.relative_to(self.output)))
            if compressed:
                with self.assertRaisesRegex(ValueError,'must-be-uncompressed'):provider.verify(self.output,apk)
            else:self.assertTrue(provider.verify(self.output,apk)['apkBytesVerified'])


if __name__=='__main__':unittest.main()
