import copy
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zipfile
from tools import qualify_android_proot as qualification
from tools import verify_android_proot_probe as verifier
from tests.test_android_jni_elf import fixture


class ProbeContracts(unittest.TestCase):
    def test_owner_elf_checks_real_abi_and_bounds(self):
        data=fixture();struct.pack_into('<H',data,18,62);verifier.elf(data,'owner')
        for offset,fmt,value in [(18,'<H',183),(24,'<Q',384),(64+48,'<Q',4096),(64+4,'<I',7),(64+3*56+4,'<I',7)]:
            invalid=bytearray(data);struct.pack_into(fmt,invalid,offset,value)
            with self.subTest(offset=offset),self.assertRaises(ValueError):verifier.elf(invalid,'owner')
    def test_guest_cannot_be_substituted_for_native_owner(self):
        data=fixture();struct.pack_into('<H',data,18,62)
        for role in ('guest','tracer','loader','plugin','libc','ld'):
            with self.subTest(role=role),self.assertRaises(ValueError):verifier.elf(data,role)
    def test_exact_receipt_checks_all_runtime_results(self):
        build={'pinned':'fixture-only'}
        good=dict(formatVersion=1,scope=qualification.SCOPE,sourceRevision='a'*40,fingerprint='fixture',abi='x86_64',
                  glibcVersion='2.36',api=33,targetSdk=35,guestLaunches=6,guestChildExit=17,buildEvidence=build,
                  controlSurvivors=3,patchedSurvivors=0,detachedTraceesPerCase=3,gracefulSavedFilesRestored=3,
                  controlObservationMillis=900,patchedObservationMillis=300,
                  arm64GuestExecuted=False,appDeathQualified=False,wineQualified=False,gameplayQualified=False)
        good.update({flag:True for flag in qualification.FLAGS})
        qualification.validate_receipt(good,'a'*40,'fixture',build)
        changes={flag:False for flag in qualification.FLAGS}
        changes.update(arm64GuestExecuted=True,appDeathQualified=True,wineQualified=True,gameplayQualified=True,
                       sourceRevision='b'*40,fingerprint='different',api=32,targetSdk=28,guestLaunches=1,guestChildExit=0,
                       controlSurvivors=0,patchedSurvivors=1,detachedTraceesPerCase=2,gracefulSavedFilesRestored=0,
                       controlObservationMillis=25000,patchedObservationMillis=-1,
                       glibcVersion='2.39',abi='arm64-v8a',buildEvidence={})
        for name,value in changes.items():
            invalid=copy.deepcopy(good);invalid[name]=value
            with self.subTest(name=name),self.assertRaises(ValueError):qualification.validate_receipt(invalid,'a'*40,'fixture',build)
        invalid=copy.deepcopy(good);invalid['formatVersion']=True
        with self.assertRaises(ValueError):qualification.validate_receipt(invalid,'a'*40,'fixture',build)


@unittest.skipUnless(os.environ.get('ESTERIA_PROOT_PROBE_PROVIDER'), 'requires actual source-built probe provider')
class BuiltProbeBounds(unittest.TestCase):
    def test_oversized_apk_and_compressed_owner_refused_before_read(self):
        provider=Path(os.environ['ESTERIA_PROOT_PROBE_PROVIDER'])
        verifier.verify(provider)
        with tempfile.TemporaryDirectory() as raw:
            apk=Path(raw)/'oversized.apk'
            with apk.open('wb') as stream:stream.truncate(64*1024**2+1)
            with self.assertRaisesRegex(ValueError,'probe-apk-size-limit'):verifier.verify(provider,apk)
            with zipfile.ZipFile(apk,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                for name in verifier.builder.NATIVE_PINS:archive.writestr('lib/x86_64/'+name,b'fixture')
                archive.writestr('lib/x86_64/libesteria_probe_process.so',b'fixture')
                with archive.open('lib/x86_64/libesteria_process.so','w') as entry:
                    for _ in range(17):entry.write(bytes(1024**2))
            with mock.patch.object(zipfile.ZipFile,'read',side_effect=AssertionError('must reject size before inflate')):
                with self.assertRaisesRegex(ValueError,'probe-owner-size-limit'):verifier.verify(provider,apk)


if __name__=='__main__':unittest.main()
