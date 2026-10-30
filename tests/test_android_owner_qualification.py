import copy
import struct
import tempfile
from pathlib import Path
import unittest
import zipfile
from tools import qualify_android_owner as owner

class OwnerQualification(unittest.TestCase):
    def test_scope_requires_every_actual_check_and_exact_identity(self):
        receipt=dict(formatVersion=1,scope='android-13-x86_64-native-owner-system-shell',sourceRevision='a'*40,
            fingerprint='test',abi='x86_64',api=33,targetSdk=35,groupsPassed=9,logReadBytesPerPipe=9000000,logStoredBytesPerPipe=8388608,
            appDeathQualified=False,arm64GuestExecuted=False,androidProotExecuted=False,gameplayQualified=False,
            worldShutdownQualified=False,characterPersistenceQualified=False)
        receipt.update({key:True for key in owner.FLAGS}); owner.validate_receipt(receipt,'a'*40,'test')
        for key,value in [(key,False) for key in owner.FLAGS]+[('sourceRevision','b'*40),('fingerprint','other'),('api',True),('targetSdk',28),('groupsPassed',0),('gameplayQualified',True),('appDeathQualified',True),('worldShutdownQualified',True),('characterPersistenceQualified',True)]:
            changed=copy.deepcopy(receipt); changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):owner.validate_receipt(changed,'a'*40,'test')
    def test_usage_scope_and_denial_never_make_partial_totals(self):
        receipt=dict(formatVersion=1,scope='visible-owned-native-group-members-only',sourceRevision='a'*40,fingerprint='test',abi='x86_64',api=33,targetSdk=35,diagnosticsAbiLength=5,
            nativeOwnerUsageExecuted=True,knownReapVerified=True,unknownHandleRefused=True,immutableLogPathsVerified=True,
            flags=4129,visibleSetStable=True,wholeGroupMembershipVerified=False,visibleMembers=3,rssMeasuredMembers=3,pssMeasuredMembers=2,cpuMeasuredMembers=3,rssBytes=300,pssBytes=None,cpuNanos=1,
            startedMonotonicNanos=1,durationNanos=2,wholeGuestUsageQualified=False,combinedMemoryQualified=False,botPopulationQualified=False,gameplayQualified=False)
        owner.validate_usage_receipt(receipt,'a'*40,'test')
        for key,value in [('scope','combined-memory'),('flags',True),('visibleSetStable',False),('pssBytes',200),('rssMeasuredMembers',4),('botPopulationQualified',True),('knownReapVerified',False),('sourceRevision','b'*40)]:
            changed=copy.deepcopy(receipt);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):owner.validate_usage_receipt(changed,'a'*40,'test')
        receipt.update(flags=4131,visibleSetStable=False,rssBytes=None,cpuNanos=None);owner.validate_usage_receipt(receipt,'a'*40,'test')
        receipt['rssBytes']=300
        with self.assertRaises(ValueError):owner.validate_usage_receipt(receipt,'a'*40,'test')
    def test_apk_must_have_only_x64_owner_and_real_elf_header(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'fixture.apk'; header=bytearray(64); header[:7]=b'\x7fELF\x02\x01\x01'; struct.pack_into('<HH',header,16,3,62)
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('lib/x86_64/libesteria_process.so',header)
            self.assertEqual(owner.apk_identity(path)['bytes'],path.stat().st_size)
            for member,machine in [('lib/arm64-v8a/libesteria_process.so',183),('lib/x86_64/libesteria_process.so',183),('lib/x86_64/libother.so',62)]:
                struct.pack_into('<H',header,18,machine)
                with zipfile.ZipFile(path,'w') as archive:archive.writestr(member,header)
                with self.subTest(member=member,machine=machine),self.assertRaises(ValueError):owner.apk_identity(path)

if __name__=='__main__':unittest.main()
