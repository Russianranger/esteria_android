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
import textwrap
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
            for row in mutation['observations']['hardlinkAfterCreateAttempt'].values():
                row[field]=mutation['observations']['regularInitial']['work'][field]
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'hardlink-count-change-not-visible'):
                stat_probe.validate_guests(mutation,self.relaunch)

    def test_platform_denied_hardlink_requires_exact_unchanged_metadata(self):
        for outcome in ('blocked-eacces','blocked-eperm'):
            mutation=copy.deepcopy(self.mutation);mutation['hardlinkOperation']=outcome
            mutation['hardlinkErrno']=13 if outcome=='blocked-eacces' else 1
            for name in ('hardlinkAfterCreateAttempt','hardlinkAfterRemoveAttempt'):
                mutation['observations'][name]=copy.deepcopy(mutation['observations']['regularInitial'])
            checked=stat_probe.validate_guests(mutation,self.relaunch)
            self.assertTrue(checked['hardlinkMutationDeniedAndUnchanged'])
            self.assertFalse(checked['hardlinkAddDeleteChangedLinkCountAndCtime'])
            self.assertFalse(checked['linkMutationQualified']);self.assertTrue(checked['linkDenialObserved'])
            self.assertEqual(checked['linkAttemptOutcome'],'denied')
            mutation['observations']['hardlinkAfterCreateAttempt']['work']['nlink']='2'
            with self.assertRaises(ValueError):stat_probe.validate_guests(mutation,self.relaunch)

    def test_explicit_injected_link_denial_runs_real_c_refusal_branch(self):
        # This is a named negative control, not evidence that the host platform
        # denies links. The actual Android result must retain its own errno.
        for error in (13,1):
            with self.subTest(errno=error),tempfile.TemporaryDirectory(prefix='stat-link-denial-control-') as temporary:
                root=Path(temporary);source=root/'deny.c';library=root/'deny.so'
                source.write_text('#include <errno.h>\nint link(const char *a,const char *b){(void)a;(void)b;errno='+str(error)+';return -1;}\n')
                subprocess.run([shutil.which('cc'),'-shared','-fPIC','-Wall','-Wextra','-Werror',str(source),'-o',str(library)],
                    stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=10)
                generation=root/'generation';(generation/'data').mkdir(parents=True);values=[]
                for mode in ('mutate','verify'):
                    child=subprocess.run([str(self.executable),mode,str(generation),str(generation)],
                        env=dict(os.environ,LD_PRELOAD=str(library)),stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True,timeout=5)
                    values.append(json.loads(child.stdout))
                checked=stat_probe.validate_guests(*values)
                self.assertTrue(checked['linkDenialObserved']);self.assertFalse(checked['linkMutationQualified'])
                self.assertEqual(checked['linkAttemptErrno'],error)
                self.assertFalse((generation/'data/hardlink').exists())

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


class StatWorkflowCleanup(unittest.TestCase):
    """Execute the exact workflow guard against disposable host files only."""
    @classmethod
    def setUpClass(cls):
        workflow=(stat_probe.fixture.ROOT/'.github/workflows/android-proot-stat.yml').read_text()
        begin='# BEGIN GUARDED STAT BUILD INPUT CLEANUP';end='# END GUARDED STAT BUILD INPUT CLEANUP'
        if workflow.count(begin)!=1 or workflow.count(end)!=1:raise AssertionError('Unique workflow cleanup guard required')
        source=textwrap.dedent(workflow.split(begin,1)[1].split(end,1)[0])
        namespace={'__name__':'stat_cleanup_host_guard_only'};exec(compile(source,'workflow-stat-cleanup','exec'),namespace)
        cls.cleanup=staticmethod(namespace['cleanup_stat_build_inputs'])

    def setUp(self):
        import hashlib
        self.temporary=tempfile.TemporaryDirectory(prefix='stat-cleanup-guard-');self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.sdk=self.root/'esteria-stat-sdk'
        self.ndk=self.sdk/'ndk/28.2.13676358';self.ndk.mkdir(parents=True);(self.ndk/'build-only').write_bytes(b'ndk fixture')
        self.download=self.root/'android-commandline.zip';self.download.write_bytes(b'downloaded fixture')
        self.sources=self.root/'stat-probe/corresponding-source.tar.gz';self.sources.parent.mkdir();self.sources.write_bytes(b'complete source guard fixture')
        self.proot=self.root/'proot-probe/provider/assets/proot-probe/build-evidence.json';self.proot.parent.mkdir(parents=True);self.proot.write_bytes(b'original retained receipt fixture')
        identity=lambda p:dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        self.proof=dict(scope=stat_probe.fixture.SCOPE,sourceSnapshotExact=True,
            sourceCompanion=identity(self.sources),prootBuildEvidence=identity(self.proot))
        self.receipt=self.root/'stat-probe/provider/assets/proot-stat-probe/build-evidence.json';self.receipt.parent.mkdir(parents=True)
        self.external=self.root/'stat-probe/build-evidence.json';self.write_proof()
        self.platform_tools=self.sdk/'platform-tools/retained-tool';self.platform_tools.parent.mkdir();self.platform_tools.write_bytes(b'emulator still needs this')

    def write_proof(self):
        raw=json.dumps(self.proof).encode();self.receipt.write_bytes(raw);self.external.write_bytes(raw)

    def retained_after_refusal(self):
        self.assertTrue((self.ndk/'build-only').is_file());self.assertTrue(self.download.is_file())
        self.assertTrue(self.platform_tools.is_file())

    def test_actual_cleanup_deletes_only_completed_job_ndk_and_download(self):
        retained={p:p.read_bytes() for p in (self.sources,self.proot,self.receipt,self.external,self.platform_tools)}
        report=self.cleanup(str(self.root),str(self.sdk))
        self.assertEqual(report['removed'],['esteria-stat-sdk/ndk/28.2.13676358','android-commandline.zip'])
        self.assertFalse(self.ndk.exists());self.assertFalse(self.download.exists())
        for path,raw in retained.items():self.assertEqual(path.read_bytes(),raw)

    def test_foreign_sdk_or_aliased_directory_refuses_before_any_deletion(self):
        with self.assertRaisesRegex(ValueError,'exact job-owned stat SDK'):
            self.cleanup(str(self.root),str(self.root/'foreign-sdk'))
        self.retained_after_refusal()
        alias=self.root/'runner-alias';alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'canonical runner'):
            self.cleanup(str(alias),str(alias/'esteria-stat-sdk'))
        self.retained_after_refusal()
        saved=self.ndk.with_name('saved-ndk');self.ndk.rename(saved);self.ndk.symlink_to(saved,target_is_directory=True)
        try:
            with self.assertRaisesRegex(ValueError,'plain job-owned NDK'):
                self.cleanup(str(self.root),str(self.sdk))
            self.assertTrue((saved/'build-only').is_file());self.assertTrue(self.download.is_file())
        finally:self.ndk.unlink();saved.rename(self.ndk)

    def test_changed_missing_or_uncommitted_retention_refuses_before_deletion(self):
        original=self.sources.read_bytes();self.sources.write_bytes(b'changed corresponding source')
        with self.assertRaisesRegex(ValueError,'corresponding source'):self.cleanup(str(self.root),str(self.sdk))
        self.retained_after_refusal();self.sources.write_bytes(original)
        self.proof['sourceSnapshotExact']=False;self.write_proof()
        with self.assertRaisesRegex(ValueError,'exact committed fixture'):self.cleanup(str(self.root),str(self.sdk))
        self.retained_after_refusal();self.proof['sourceSnapshotExact']=True;self.write_proof()
        self.proot.unlink()
        with self.assertRaisesRegex(ValueError,'canonical regular file'):self.cleanup(str(self.root),str(self.sdk))
        self.retained_after_refusal()


if __name__=='__main__':unittest.main()
