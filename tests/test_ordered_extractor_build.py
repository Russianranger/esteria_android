"""Separate target-build and source-replay guards; no synthetic native claims."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import build_ordered_extractors as build,prepare_ordered_extractors as prepare


def identity(raw):return dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


class OrderedBuildGuards(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='ordered-build-guards-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name)

    def test_host_never_claims_native_and_existing_outputs_are_untouched(self):
        output=self.root/'existing';output.mkdir();(output/'saved').write_bytes(b'keep')
        with patch.object(build.platform,'machine',return_value='x86_64'),self.assertRaisesRegex(ValueError,'native-arm64'):
            build.build(self.root,self.root,self.root,self.root,self.root,output,integration_revision='a'*40)
        self.assertEqual((output/'saved').read_bytes(),b'keep')

    def test_pin_binds_four_only_tool_sources_and_separate_pending_flags(self):
        pin=prepare.load_pin();self.assertEqual(len(pin['baseFiles']),4)
        self.assertEqual(set(pin['baseFiles']),set(pin['adaptedFiles']))
        self.assertTrue(all(n.startswith(('src/tools/map_extractor/','src/tools/vmap4_extractor/')) for n in pin['baseFiles']))
        self.assertEqual(build.TARGETS,('map_extractor','vmap4_extractor'))
        self.assertEqual(len(pin['baseServerSource']['patches']),7)
        self.assertFalse(pin['globalServerPatchListChanged']);self.assertFalse(pin['nativeAdaptedToolsQualified'])
        self.assertFalse(pin['sourceCompanionComplete']);self.assertFalse(pin['clientMpqConversionQualified'])

    def test_changed_declared_planner_or_applicator_recipe_refuses_same_input_lock(self):
        pin=prepare.load_pin();files={r['file'] for r in (pin['patch'],pin['header'])}|set(pin['recipes'])
        for name in files:
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((prepare.ROOT/name).read_bytes())
        lock=self.root/'lock.json';lock.write_bytes(prepare.engine.canonical(pin))
        for name in pin['recipes']:
            path=self.root/name;raw=path.read_bytes();path.write_bytes(raw+b'\n# changed synthetic recipe\n')
            with self.subTest(recipe=name),patch.object(prepare,'ROOT',self.root),patch.object(prepare,'LOCK',lock):
                with self.assertRaisesRegex(ValueError,'recipe-changed'):prepare.load_pin()
            path.write_bytes(raw)

    def test_client_policy_reader_requires_complete_exact_source_and_git_blob(self):
        policy=self.root/'policy';policy.mkdir();name='Source/Fixture.cpp';raw=b'// explicit synthetic source fixture\n'
        target=policy/name;target.parent.mkdir();target.write_bytes(raw)
        row=dict(identity(raw),gitBlob=hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest())
        pin=dict(clientRevision='a'*40,clientSources={name:row})
        receipt=dict(formatVersion=1,scope='exact-client-order-policy-source-readback',clientRevision=pin['clientRevision'],
            files=pin['clientSources'],fullClientRepositoryFetched=False,clientAssetsFetched=False)
        (policy/'policy-source-receipt.json').write_bytes(prepare.engine.canonical(receipt));build.verify_policy(policy,pin)
        target.write_bytes(raw+b'changed')
        with self.assertRaisesRegex(ValueError,'source-changed'):build.verify_policy(policy,pin)
        target.write_bytes(raw);(policy/'extra').write_bytes(b'refused')
        with self.assertRaisesRegex(ValueError,'file-set'):build.verify_policy(policy,pin)

    def test_overlay_rejects_extra_files_changed_inputs_and_self_rebound_metadata(self):
        original=self.root/'original';adapted=self.root/'adapted';original.mkdir();adapted.mkdir()
        before={'source/a.cpp':identity(b'before')}
        for root,data in ((original,b'before'),(adapted,b'after')):
            (root/'source').mkdir();(root/'source/a.cpp').write_bytes(data)
        (adapted/'source/header.h').write_bytes(b'new header');(adapted/'extractor-adaptation.json').write_bytes(b'fixed receipt')
        expected_receipt=build.files.identity(adapted/'extractor-adaptation.json')
        pin=dict(adaptedFiles={'a.cpp':identity(b'after')},header=dict(installedPath='header.h',**identity(b'new header')))
        build.verify_overlay(original,adapted,before,pin,expected_receipt)
        (adapted/'extractor-adaptation.json').write_bytes(b'other receipt')
        with self.assertRaisesRegex(ValueError,'unapproved'):build.verify_overlay(original,adapted,before,pin,expected_receipt)
        (adapted/'extractor-adaptation.json').write_bytes(b'fixed receipt');(original/'source/a.cpp').write_bytes(b'drift')
        with self.assertRaisesRegex(ValueError,'unapproved'):build.verify_overlay(original,adapted,before,pin,expected_receipt)

    def test_client_policy_existing_output_is_preserved_before_network(self):
        output=self.root/'existing';output.mkdir();(output/'saved').write_bytes(b'keep')
        with patch.object(build.urllib.request,'urlopen') as network,self.assertRaisesRegex(ValueError,'existing-client-order'):
            build.client_policy(output)
        network.assert_not_called();self.assertEqual((output/'saved').read_bytes(),b'keep')

    def test_actual_cache_requires_both_explicit_empty_launchers(self):
        cache=self.root/'CMakeCache.txt'
        clean='CMAKE_C_COMPILER_LAUNCHER:UNINITIALIZED=\nCMAKE_CXX_COMPILER_LAUNCHER:UNINITIALIZED=\n'
        cache.write_text(clean)
        self.assertEqual(build.compiler_launchers(cache),dict(CMAKE_C_COMPILER_LAUNCHER='',CMAKE_CXX_COMPILER_LAUNCHER=''))
        for changed in (clean.replace('LAUNCHER:UNINITIALIZED=\n','LAUNCHER:UNINITIALIZED=/usr/bin/ccache\n',1),
                        clean.splitlines(keepends=True)[0],clean+clean.splitlines(keepends=True)[0]):
            cache.write_text(changed)
            with self.subTest(cache=changed),self.assertRaisesRegex(ValueError,'launcher-enabled-or-absent'):
                build.compiler_launchers(cache)

    def test_native_observation_requires_two_links_bound_to_measured_programs(self):
        programs={name:dict(identity(name.encode()),elf={'machine':183}) for name in build.TARGETS}
        commands=identity(b'compile commands')
        receipt=dict(objectElfMachines=[183],observedObjects=210,dependenciesNotNewerThanObject=True,
                     compileCommands=commands,observedLinks=2,linkElfMachines=[183],
                     linkDependenciesNotNewerThanOutput=True,linkInputsCopied=False,systemLinkSourcesCopied=False)
        observation=dict(links={'bin/'+name:dict(identity=identity(name.encode()),elfMachine=183,elfType='DYN')
                                for name in build.TARGETS})
        build.verify_native_observation(receipt,observation,programs,commands)
        for key,value in (('observedLinks',1),('linkElfMachines',[62]),
                          ('linkDependenciesNotNewerThanOutput',False),('linkInputsCopied',True),
                          ('systemLinkSourcesCopied',True)):
            changed=dict(receipt,**{key:value})
            with self.subTest(field=key),self.assertRaisesRegex(ValueError,'native-link-observation'):
                build.verify_native_observation(changed,observation,programs,commands)
        changed=copy.deepcopy(observation);changed['links']['bin/map_extractor']['identity']=identity(b'other program')
        with self.assertRaisesRegex(ValueError,'final-link-output-differs'):
            build.verify_native_observation(receipt,changed,programs,commands)
        changed=copy.deepcopy(observation);changed['links']['bin/unknown']=changed['links'].pop('bin/map_extractor')
        with self.assertRaisesRegex(ValueError,'native-link-observation'):
            build.verify_native_observation(receipt,changed,programs,commands)


if __name__=='__main__':unittest.main()
