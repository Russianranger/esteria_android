"""Unmeasured composed data tools cannot become a positive provider."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import provider_server_data_tools as provider


class PendingDataToolsProvider(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='pending-data-tools-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)
        # Pending-state refusals remain explicit fixtures after the production
        # pin advances to a real source-only or fully measured selection.
        self.pin=json.loads(provider.LOCK.read_text())
        self.pin.update(state='pending-ordered-source-and-derived-native-cli',sourceCompanionComplete=False,
                        nativeArgumentConfigQualified=False,originalNoticesPreserved=False)
        for name in ('archive','archiveEntries','archiveFileBytes','packageReceipt','programPairs','nativeCliReceipt',
                     'files','toolSelection','actualOrderedSourceQualification','orderedStripReceipt','debugArchives'):
            self.pin[name]=None
        self.pending_lock=self.root/'pending-provider.lock.json';self.pending_lock.write_bytes(provider.encoded(self.pin))
        selected=patch.object(provider,'LOCK',self.pending_lock);selected.start();self.addCleanup(selected.stop)
        self.pin=provider.load_pin()

    def locked(self,pin):
        path=self.root/'pin.json';path.write_bytes(provider.encoded(pin));return patch.object(provider,'LOCK',path)

    def test_pending_contract_has_no_guessed_measured_values(self):
        self.assertEqual(self.pin['state'],'pending-ordered-source-and-derived-native-cli')
        self.assertEqual(self.pin['guestMount'],'/esteria-server-extractors')
        self.assertEqual(self.pin['packageKey'],'server-data-tools-arm64')
        for name in ('archive','archiveEntries','archiveFileBytes','programPairs','actualOrderedSourceQualification','toolSelection'):
            self.assertIsNone(self.pin[name])
        self.assertFalse(self.pin['sourceCompanionComplete']);self.assertFalse(self.pin['nativeArgumentConfigQualified'])
        self.assertFalse(self.pin['originalNoticesPreserved'])
        self.assertEqual(self.pin['configuration']['bytes'],7888)

    def test_build_verify_and_descriptor_refuse_pending_without_touching_outputs(self):
        output=self.root/'saved';output.mkdir();(output/'private-save').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError,'real-ordered-source'):
            provider.build(self.root,self.root,output)
        with self.assertRaisesRegex(ValueError,'real-ordered-source'):provider.verify(output)
        with self.assertRaisesRegex(ValueError,'pending-descriptor'):provider.descriptor(self.pin)
        self.assertEqual((output/'private-save').read_bytes(),b'keep')
        self.assertEqual(set(self.root.iterdir()),{output,self.pending_lock})

    def test_positive_flags_cannot_replace_measured_native_dependency_capture(self):
        from tools import seal_ordered_extractor_sources as ordered
        pin=copy.deepcopy(self.pin)
        pin.update(state='sealed-source-and-native-cli',sourceCompanionComplete=True,
            nativeArgumentConfigQualified=True,originalNoticesPreserved=True)
        pending=self.root/'pending-native.lock.json'
        pending.write_text(json.dumps(dict(formatVersion=1,scope='exact-ordered-server-data-tools-packaging-inputs',
                                          state='pending-native-dependency-capture')))
        with self.locked(pin),patch.object(ordered,'LOCK',pending),self.assertRaisesRegex(ValueError,'measured-input-pin-required'):
            provider.load_pin(sealed=True)

    def test_source_runtime_config_program_and_scope_drift_refuse(self):
        for kind in ('app','runtime','config','program','client','schema'):
            pin=copy.deepcopy(self.pin)
            if kind=='app':pin['appSourceLock']['sha256']='0'*64
            elif kind=='runtime':pin['requiredServerRuntimeArchive']['sha256']='0'*64
            elif kind=='config':pin['configuration']['sha256']='0'*64
            elif kind=='program':pin['programNames'][0]='arbitrary-user-program'
            elif kind=='client':pin['clientRevision']='0'*40
            else:pin['formatVersion']=True
            with self.subTest(kind=kind),self.locked(pin),self.assertRaises(ValueError):provider.load_pin()

    def test_separate_source_anchor_cannot_enable_runtime_before_derived_cli(self):
        from tools import seal_ordered_extractor_sources as ordered
        pin=copy.deepcopy(self.pin)
        measured=dict(nativeBuild=dict(receipt=dict(bytes=1,sha256='1'*64),
                                       dependencyObservation=dict(bytes=2,sha256='2'*64)))
        qualified=dict(archive=dict(bytes=3,sha256='3'*64),receipt=dict(bytes=4,sha256='4'*64),
                       nativeBuild=measured['nativeBuild']['receipt'],
                       dependencyObservation=measured['nativeBuild']['dependencyObservation'])
        pin.update(state='source-sealed-pending-derived-native-cli',sourceCompanionComplete=True,
                   actualOrderedSourceQualification=qualified)
        with self.locked(pin),patch.object(ordered,'load_pin',return_value=measured):
            source=provider.load_source_qualification()
            self.assertEqual(source['actualOrderedSourceQualification'],qualified)
            self.assertFalse(source['nativeArgumentConfigQualified']);self.assertIsNone(source['archive'])
            with self.assertRaisesRegex(ValueError,'real-derived-native-cli-required'):provider.load_pin(sealed=True)
            with self.assertRaisesRegex(ValueError,'pending-descriptor'):provider.descriptor(source)
        pin['actualOrderedSourceQualification']['nativeBuild']=dict(bytes=5,sha256='5'*64)
        with self.locked(pin),patch.object(ordered,'load_pin',return_value=measured):
            with self.assertRaisesRegex(ValueError,'measured-native-source-inputs-differ'):provider.load_source_qualification()
        with self.assertRaisesRegex(ValueError,'real-ordered-source-qualification-required'):provider.load_source_qualification()

    def test_native_reference_image_must_match_the_required_runtime_and_safe_readback_scope(self):
        image=dict(formatVersion=1,scope='native-arm64-dependency-image-readback',
                   runtimeArchive=self.pin['requiredServerRuntimeArchive'],
                   actualImageMetadataAndElfHashesVerified=True,nativePythonExecuted=True,
                   mysqlServerExecuted=False,databaseInitialized=False,esteriaServerExecuted=False,
                   androidRuntimeQualified=False,gameplayQualified=False)
        cli=dict(referenceImageReadback=dict(identity=dict(bytes=7,sha256='7'*64),receipt=image))
        provider.verify_reference_image(cli,self.pin)
        for key,value in (('runtimeArchive',dict(bytes=1,file='other.tar.gz',sha256='0'*64)),
                          ('nativePythonExecuted',False),('databaseInitialized',True),('androidRuntimeQualified',True)):
            changed=copy.deepcopy(cli);changed['referenceImageReadback']['receipt'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'reference-image-selection-or-gates'):
                provider.verify_reference_image(changed,self.pin)
        with self.assertRaisesRegex(ValueError,'reference-image-receipt-required'):
            provider.verify_reference_image({},self.pin)


class ActualNativeReceiptAdmission(unittest.TestCase):
    def setUp(self):
        self.pin=provider.load_pin(sealed=True)
        path=provider.ROOT/'runtime/evidence/non-custom-v7-data-tools-native.json'
        retained=json.loads(path.read_text())['nativeCliReceipt']
        self.cli=retained['receipt']
        self.assertEqual(retained['identity'],self.pin['nativeCliReceipt'])

    def test_actual_retained_native_tuple_has_five_cli_two_capabilities_and_exact_current_no_skip_lookups(self):
        provider.validate_native_cli(self.cli,self.pin)
        self.assertEqual(len(self.cli['cliCases']),5)
        self.assertEqual(len(self.cli['capabilities']),2)
        self.assertEqual(self.cli['lookupTestNames'],provider.required_lookup_names())
        self.assertEqual(self.cli['lookupTestsRun'],len(provider.required_lookup_names()))
        self.assertEqual(self.cli['lookupTestsSkipped'],0)
        self.assertFalse(self.pin['androidRuntimeQualified'])
        self.assertFalse(self.pin['clientMpqConversionQualified'])

    def test_foreign_package_modified_runtime_missing_roles_and_partial_native_results_refuse(self):
        for kind in ('package','runtime','case','case-output','capability','lookup-count','lookup-skip','lookup-duplicate','lookup-type','lookup-partial','lookup-foreign','gameplay'):
            cli=copy.deepcopy(self.cli)
            if kind=='package':cli['packageReceipt']['sha256']='0'*64
            elif kind=='runtime':cli['shippedRuntimeFilesUnchanged']=False
            elif kind=='case':cli['cliCases'].pop(next(iter(cli['cliCases'])))
            elif kind=='case-output':cli['cliCases']['map-usage']['output']='unrelated program'
            elif kind=='capability':cli['capabilities'].pop('map_extractor')
            elif kind=='lookup-count':cli['lookupTestsRun']=0
            elif kind=='lookup-skip':cli['lookupTestsSkipped']=1
            elif kind=='lookup-duplicate':cli['lookupTestNames'][-1]=cli['lookupTestNames'][0]
            elif kind=='lookup-type':cli['lookupTestsRun']=True
            elif kind=='lookup-partial':
                cli['lookupTestNames'].pop();cli['lookupTestsRun']=len(cli['lookupTestNames'])
            elif kind=='lookup-foreign':cli['lookupTestNames'][-1]='tests.test_extractor_order.RealArchiveReader.test_unrelated'
            else:cli['gameplayQualified']=True
            with self.subTest(kind=kind),self.assertRaises(ValueError):provider.validate_native_cli(cli,self.pin)


if __name__=='__main__':unittest.main()
