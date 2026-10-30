"""Actual host mutation fixture and strict Android receipt admission guards.

Host execution never qualifies Android/PRoot alias translation or production use.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools import qualify_android_proot_stat as stat_probe


class StatQualification(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=shutil.which('cc')
        if compiler is None:raise unittest.SkipTest('host C compiler unavailable; Android execution remains unqualified')
        cls.temporary=tempfile.TemporaryDirectory(prefix='esteria-stat-host-')
        cls.root=Path(cls.temporary.name);cls.executable=cls.root/'probe-stat'
        subprocess.run([compiler,'-O2','-Wall','-Wextra','-Werror',str(stat_probe.fixture.ROOT/'native/proot-stat-probe/stat_probe.c'),
            '-o',str(cls.executable)],check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
        generation=cls.root/'generation';(generation/'data').mkdir(parents=True)
        cls.mutation=cls.execute('mutate',generation,generation)
        cls.relaunch=cls.execute('verify',generation,generation)

    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    @classmethod
    def execute(cls,mode,primary,alias):
        result=subprocess.run([str(cls.executable),mode,str(primary),str(alias)],check=True,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5)
        if len(result.stdout)>65536:raise AssertionError('host stat report exceeded byte bound')
        return json.loads(result.stdout)

    def test_actual_host_mutations_and_reaped_relaunch(self):
        proof=stat_probe.validate_guests(self.mutation,self.relaunch)
        self.assertTrue(proof['sameLengthWriteRestoredMtimeChangedCtime'])
        self.assertTrue(proof['directoryAddDeleteWithRestoredMtimeChangedCtime'])
        self.assertTrue(proof['hardlinkAddDeleteChangedLinkCountAndCtime'])
        self.assertTrue(proof['reapedGuestRelaunchTuplesStable'])
        for name in ('productionCacheEnabled','arm64Qualified','gameplayQualified','unchangedMetadataCorruptionDetectionClaimed'):
            self.assertIs(proof[name],False)

    def test_host_symlink_is_not_a_substitute_for_a_real_bind_alias(self):
        primary=self.root/'not-a-bind';(primary/'data').mkdir(parents=True)
        alias=self.root/'symlink-alias';alias.symlink_to(primary,target_is_directory=True)
        child=subprocess.run([str(self.executable),'mutate',str(primary),str(alias)],stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,timeout=5)
        self.assertNotEqual(child.returncode,0)
        self.assertIn(b'stable alias/syscall tuples',child.stderr)

    def test_missing_aliased_field_or_raw_syscall_disagreement_refuses(self):
        for changed in ('missing','mismatch'):
            mutation=copy.deepcopy(self.mutation)
            row=mutation['observations']['regularInitial']['rawData']
            if changed=='missing':row.pop('ctimeNs')
            else:row['ino']=str(int(row['ino'])+1)
            with self.subTest(changed=changed),self.assertRaises(ValueError):stat_probe.validate_guests(mutation,self.relaunch)

    def test_restored_mtime_write_cannot_pass_with_an_unchanged_ctime(self):
        mutation=copy.deepcopy(self.mutation)
        for row in mutation['observations']['rewritten'].values():row['ctimeNs']=mutation['observations']['mtimeFixed']['work']['ctimeNs']
        with self.assertRaisesRegex(ValueError,'write-not-visible-in-ctime'):stat_probe.validate_guests(mutation,self.relaunch)

    def test_hidden_hardlink_count_or_ctime_change_refuses(self):
        for field in ('nlink','ctimeNs'):
            mutation=copy.deepcopy(self.mutation)
            for row in mutation['observations']['hardlinkAdded'].values():
                row[field]=mutation['observations']['regularInitial']['work'][field]
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'hardlink-count-change-not-visible'):
                stat_probe.validate_guests(mutation,self.relaunch)

    def test_second_precision_or_invisible_directory_change_refuses(self):
        for changed in ('precision','directory'):
            mutation=copy.deepcopy(self.mutation)
            if changed=='precision':
                for name in ('mtimeFixed','rewritten'):
                    for row in mutation['observations'][name].values():row['mtimeNs']='1700000000000000000'
            else:
                for row in mutation['observations']['directoryAdded'].values():row['ctimeNs']=mutation['observations']['directoryInitial']['work']['ctimeNs']
            with self.subTest(changed=changed),self.assertRaises(ValueError):stat_probe.validate_guests(mutation,self.relaunch)

    def receipt(self):
        return dict(formatVersion=1,scope=stat_probe.SCOPE,sourceRevision='a'*40,fingerprint='host-synthetic-admission-only',
            api=33,targetSdk=35,abi='x86_64',guestLaunches=2,buildEvidence={},statBuildEvidence={},
            aliases=dict(work='/work/server-data/generations/'+'a'*64,data='/esteria-data'),
            childExitCodes=[0,0],forcedChildren=[False,False],remainingNativeMembers=[0,0],noFollowAncestorOpenRejected=True,
            mutation=self.mutation,relaunch=self.relaunch,productionCacheEnabled=False,arm64Qualified=False,
            hardwareQualified=False,unchangedMetadataCorruptionDetectionClaimed=False,gameplayQualified=False)

    def test_android_admission_requires_exact_source_aliases_reaping_and_narrow_scope(self):
        original=self.receipt()
        stat_probe.validate_receipt(original,'a'*40,'host-synthetic-admission-only',{}, {})
        for field,value in (('sourceRevision','b'*40),('api',34),('abi','arm64-v8a'),('forcedChildren',[True,False]),
            ('remainingNativeMembers',[1,0]),('productionCacheEnabled',True),('arm64Qualified',True),
            ('unchangedMetadataCorruptionDetectionClaimed',True),('noFollowAncestorOpenRejected',False),('guestLaunches',True)):
            changed=copy.deepcopy(original);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                stat_probe.validate_receipt(changed,'a'*40,'host-synthetic-admission-only',{}, {})


if __name__=='__main__':unittest.main()
