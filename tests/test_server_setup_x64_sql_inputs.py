"""Fail-closed selection plus actual archive, ELF debug-link and CRC behavior."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from tools import server_setup_x64_sql_inputs as inputs


def ident(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class ServerSetupX64SqlInputs(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.pending=dict(formatVersion=1,scope='x64-server-setup-sql-input-selection',
            repository='Russianranger/esteria_android',enabled=False,
            state='pending-x64-compile-source-measurement',minimumFreeBytes=16<<30,
            build=None,mysql=None,serverContent=None,**{name:False for name in inputs.FALSE_FLAGS})

    def test_actual_selection_is_strict_measured_or_honest_pending(self):
        pin=inputs.load_pin()
        self.assertTrue(all(pin[name] is False for name in inputs.FALSE_FLAGS))
        if pin['enabled']:
            self.assertEqual(pin['state'],'measured-component-inputs')
            self.assertEqual(inputs.load_pin(require_enabled=True),pin)
            return
        self.assertEqual(pin,self.pending)

    def test_explicit_pending_required_mode_refuses_without_side_effects(self):
        path=self.root/'pending.json';path.write_text(json.dumps(self.pending))
        with patch.object(inputs,'LOCK',path):
            pin=inputs.load_pin()
            with self.assertRaisesRegex(ValueError,'measured-build-required'):inputs.load_pin(require_enabled=True)
        self.assertIsNone(pin['build']);self.assertIsNone(pin['mysql']);self.assertIsNone(pin['serverContent'])

    def test_pending_cannot_smuggle_unmeasured_or_enabled_or_runtime_claims(self):
        pin=self.pending;path=self.root/'selection.json'
        for change in (dict(enabled=1),dict(build={}),dict(mysql={}),dict(state='measured-component-inputs'),
                dict(sqlExecuted=True),dict(productionArm64ProviderQualified=True),dict(extra='ignored')):
            value=dict(pin,**change);path.write_text(json.dumps(value))
            with self.subTest(change=change),patch.object(inputs,'LOCK',path),self.assertRaises(ValueError):inputs.load_pin()

    def test_pending_component_and_archive_admission_refuse_before_creating_output(self):
        pin=self.pending;output=self.root/'absent'
        with self.assertRaisesRegex(ValueError,'measured-build-required'):
            inputs.restore_component_zip(self.root/'missing.zip',output,pin)
        with self.assertRaisesRegex(ValueError,'measured-build-required'):inputs.admit_component(output,pin)
        self.assertFalse(output.exists())

    def test_actual_split_elf_debug_crc_detects_mutated_or_foreign_debug_file(self):
        for tool in ('objcopy','strip','readelf'):
            if not shutil.which(tool):self.skipTest('Real GNU ELF tools required')
        program=self.root/'fixture';shutil.copyfile(Path(shutil.which('true')).resolve(),program)
        debug=self.root/'fixture.debug'
        subprocess.run(['objcopy','--remove-section=.gnu_debuglink',program],check=True,capture_output=True)
        subprocess.run(['objcopy','--only-keep-debug',program,debug],check=True,capture_output=True)
        subprocess.run(['strip','--strip-debug',program],check=True,capture_output=True)
        subprocess.run(['objcopy','--add-gnu-debuglink='+str(debug),program],check=True,capture_output=True)
        inputs.debug_pair(program,debug,'fixture')
        debug.write_bytes(debug.read_bytes()+b'altered-source-debug-companion')
        with self.assertRaisesRegex(ValueError,'paired-debug-crc'):inputs.debug_pair(program,debug,'fixture')
        with self.assertRaisesRegex(ValueError,'debug-link-section'):inputs.debug_pair(program,debug,'foreign')

    def source_fixture(self,raw=b'bounded synthetic source, never compiled or executed'):
        folder=self.root/'payload/corresponding-source/source-inputs';folder.mkdir(parents=True,exist_ok=True)
        archive=folder/'server-engine-source-inputs.tar.gz'
        with tarfile.open(archive,'w:gz') as output:
            member=tarfile.TarInfo('source/fixture.cpp');member.size=len(raw);output.addfile(member,io.BytesIO(raw))
        receipt=dict(scope='unsealed-engine-source-input-package',completeArchiveReadbackVerified=True,
            archive=inputs.files.identity(archive),archiveFiles={'source/fixture.cpp':ident(raw)})
        (folder/'source-inputs-receipt.json').write_text(json.dumps(receipt))
        build=dict(sourceInputs={'source-inputs/server-engine-source-inputs.tar.gz':inputs.files.identity(archive)})
        return folder,receipt,build

    def test_actual_nested_original_source_archive_is_fully_read_and_changed_member_refused(self):
        folder,receipt,build=self.source_fixture()
        proof=inputs.original_sources(self.root/'payload',build)
        self.assertEqual(proof['members'],1);self.assertTrue(proof['everyOriginalSourceMemberReadBack'])
        receipt['archiveFiles']['source/fixture.cpp']['sha256']='0'*64
        (folder/'source-inputs-receipt.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ValueError,'source-member-changed'):inputs.original_sources(self.root/'payload',build)

    def test_original_source_missing_and_wrong_scope_cannot_claim_closure(self):
        folder,receipt,build=self.source_fixture()
        for key,value in (('scope','already-qualified-gameplay'),('archiveFiles',{})):
            changed=dict(receipt,**{key:value});(folder/'source-inputs-receipt.json').write_text(json.dumps(changed))
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'original-source-archive-receipt'):
                inputs.original_sources(self.root/'payload',build)

    def test_changed_original_artifact_and_foreign_zip_member_fail_before_admission(self):
        path=self.root/'component.zip'
        with zipfile.ZipFile(path,'w') as archive:archive.writestr('foreign/private-database',b'must never be accepted')
        pin=dict(enabled=True,build=dict(artifacts=dict(complete=inputs.files.identity(path))))
        with patch.object(inputs,'admit_component') as admit,self.assertRaisesRegex(ValueError,'original-member-selection'):
            inputs.restore_component_zip(path,self.root/'out',pin)
        admit.assert_not_called()
        pin['build']['artifacts']['complete']['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'file-changed'):inputs.restore_component_zip(path,self.root/'untouched',pin)
        self.assertFalse((self.root/'untouched').exists())

    def test_actual_build_flags_do_not_accept_arm64_receipt_or_compile_count_claims(self):
        pin=dict(build=dict(producer=dict(integrationRevision='a'*40)))
        # Schema fixture only: no compiler or SQL qualification is claimed by
        # this test. Real ELF and archive bytes are exercised independently.
        value=dict(formatVersion=1,scope='source-built-x86-64-server-setup-tools-only',phase='built-unqualified-inputs',
            integrationRevision='a'*40,targets=list(inputs.builder.TARGETS),
            buildNetwork=dict(interfaces=['lo'],externalNetworkingAvailable=False),actualCompileSucceeded=True,
            correspondingSourcesCaptured=False,statementsDeclared=52,originalArm64ReceiptReusedForX64Qualification=False,
            originalDbimportTargetAndFullStaticModuleScriptLinkGraphBuilt=True,originalDbimportExecutableBuilt=True,
            dbimportSqlQualified=False,runtimeOverlayCompatibilityQualified=False,librarySourceCaptureRequired=True,
            serverSource=json.loads((inputs.ROOT/'sources.lock.json').read_bytes())['sources']['server'],
            sourceLock=inputs.files.identity(inputs.builder.inputs.ARCHIVED_LOCK),
            originalArm64Build=inputs.builder.bots.ORIGINAL_BUILD,originalArm64Modules=inputs.builder.bots.ORIGINAL_MODULES,
            actualPlayerbotsCompileInputs=ident(b'fixture compile metadata'),compileCommands=ident(b'fixture compile metadata'),
            compilerLaunchers={'CMAKE_C_COMPILER_LAUNCHER':'','CMAKE_CXX_COMPILER_LAUNCHER':''},
            **{name:False for name in inputs.FALSE_FLAGS})
        value['executables']={name:dict(**ident(b'schema fixture'),original=ident(b'original fixture'),
            pairedDebug=ident(b'debug fixture'),elf=dict(machine=62,elfClass=2,interpreter='/lib64/ld-linux-x86-64.so.2',loadSegments=4),
            originalFile='originals/'+name,debugFile='debug/'+name+'.debug') for name in ('dbimport','playerbots-schema')}
        inputs.validate_build(value,pin)
        for change in (dict(scope='source-built-playerbots-schema-helper'),dict(statementsDeclared=52.0),
                dict(originalArm64ReceiptReusedForX64Qualification=True),dict(sqlExecuted=True)):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'actual-x64-build-required'):
                inputs.validate_build(dict(value,**change),pin)
        wrong=copy.deepcopy(value);wrong['executables']['dbimport']['elf']['machine']=183
        with self.assertRaisesRegex(ValueError,'executable-metadata-abi'):inputs.validate_build(wrong,pin)


if __name__=='__main__':unittest.main()
