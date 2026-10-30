"""Host orchestration/retention fixtures only; no native C++ or SQL claims."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import qualify_playerbots_helper_sources as setup


class PlayerbotsHelperSources(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);self.prepared=self.root/'prepared';self.acquired=self.root/'acquired'
        for name in ('source','external','integration'):(self.prepared/name).mkdir(parents=True)
        self.acquired.mkdir();self.original_lock=self.root/'original-lock.json'
        self.original_lock.write_bytes((setup.ROOT/'runtime/server/server-build-sources.lock.json').read_bytes())
        self.original,self.original_identity=setup.measured.load_pin()
        for name in setup.REQUIRED_SOURCES:
            path=self.prepared/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('// host source fixture, never compiled\n')
        header=self.prepared/setup.HEADER;header.parent.mkdir(parents=True,exist_ok=True)
        header.write_text('enum PlayerbotsDatabaseStatements : uint32 {'+','.join(
            ['PLAYERBOTS_TEST_'+str(i) for i in range(52)]+['MAX_PLAYERBOTS_STATEMENTS'])+'};\n')
        (self.prepared/'external/lua-fixture.h').write_text('// external source fixture\n')
        for name in ('acquisition.json','environment/cache-environment.json','source-inputs/server-engine-source-inputs.tar.gz',
                     'source-inputs/source-inputs-receipt.json','supplements/modules/ModulesScriptLoader.h'):
            path=self.acquired/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'host input fixture\n')
        self.environment=self.root/'environment.json';self.environment.write_bytes(b'{"fixture":true}\n')
        self.output=self.root/'result';self.revision='a'*40;self.executed=[];self.capture_calls=[]
        self.prep=dict(originalBuild=self.original['originalBuild'],originalCompiledModules=self.original['originalModules'],
                       sourceLock=self.original['sourceLock'])
        self.prep_identity=dict(bytes=17,sha256='1'*64)
        self.first_bytes=b'HOST INITIAL HELPER FIXTURE\0ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements=\0'
        self.final_bytes=b'HOST FINAL HELPER FIXTURE\0ESTERIA_PLAYERBOTS_DATABASE_REFERENCE_COMPLETE statements=\0'
        self.mutate_capture=None;self.mutate_receipt=None;self.readback_calls=[]

    def initial_build(self,prepared,acquired,lock,environment,output,*,integration_revision):
        self.assertEqual(integration_revision,self.revision)
        for name in ('build','diagnostics','payload/bin','payload/build','payload/source-inputs'):(output/name).mkdir(parents=True,exist_ok=True)
        executable=output/'build'/setup.component.TARGET;executable.write_bytes(self.first_bytes);executable.chmod(0o755)
        (output/'payload/bin/playerbots-schema').write_bytes(self.first_bytes)
        commands=output/'build/compile_commands.json';commands.write_bytes(b'[]\n')
        (output/'payload/build/compile_commands.json').write_bytes(commands.read_bytes())
        cache=output/'build/CMakeCache.txt';cache.write_text('CMAKE_C_COMPILER_LAUNCHER:STRING=\nCMAKE_CXX_COMPILER_LAUNCHER:STRING=\n')
        compiler=Path(sys.executable).resolve()
        rows=[dict(phase='configure',argv=[str(compiler),'-S',str(prepared/'source'),'-B',str(output/'build'),'-G','Ninja']),
              dict(phase='component-build',argv=[str(compiler),'--build',str(output/'build'),'--parallel','2','--target',setup.component.TARGET])]
        for path in (output/'diagnostics/commands.json',output/'payload/build/commands.json'):path.write_text(json.dumps(rows))
        (output/'payload/source-inputs/original-sources.lock.json').write_bytes(lock.read_bytes())
        for name in setup.component.RECIPES:
            path=output/'payload/recipes'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes((setup.ROOT/name).read_bytes())
        statement=setup.component.files.identity(prepared/setup.HEADER)
        initial=dict(formatVersion=1,scope='source-built-playerbots-schema-helper',phase='built-component',
            actualCompileSucceeded=True,actualDatabaseSourcesAndDefinitionVerified=True,databaseExecuted=False,
            preparedStatementCountDeclared=52,originalBuild=self.original['originalBuild'],originalModules=self.original['originalModules'],
            sourceLock=self.original['sourceLock'],serverSource=self.original['serverSource'],sourceInputArchive=self.original['sourceInputArchive'],
            sourceInputReceipt=self.original['sourceInputReceipt'],sourceSupplements={},originalCompileCommands=dict(bytes=9,sha256='2'*64),
            newCompileCommands=setup.files.identity(commands),executable=setup.files.identity(executable),referenceInputs={'fixture':statement},
            cmakeOptions=dict(APPS_BUILD='all',TOOLS_BUILD='all'),compilerExecutables={'gcc':dict(path=str(compiler),**setup.files.identity(compiler))},
            cmakeExecutable=dict(path=str(compiler),**setup.files.identity(compiler)))
        raw=(json.dumps(initial,sort_keys=True,indent=2)+'\n').encode()
        (output/'qualification.json').write_bytes(raw);(output/'payload/helper-build.json').write_bytes(raw)
        self.initial=initial;self.initial_raw=raw
        return initial

    def environment_check(self,acquired,path,**kwargs):
        path.write_bytes(b'{"hostEnvironmentFixture":true}\n');return dict(relevantBuildEnvironmentMatched=True)

    def run_command(self,argv,log,environment,**kwargs):
        self.executed.append([str(value) for value in argv]);log.write_bytes(b'host command fixture; no compiler executed\n')
        if log.name=='target-metadata-stabilization.log':
            path=self.output/'component/build'/setup.component.TARGET;path.write_bytes(self.final_bytes);path.chmod(0o755)
        return dict(exitCode=0,output=setup.files.identity(log))

    def capture(self,build,prepared,commands,ninja,run,output,*,targets):
        self.capture_calls.append(targets);self.assertEqual(targets,setup.TARGETS)
        run([str(ninja),'-C',str(build),'-t','deps'],'ordered-ninja-deps',120)
        run([str(ninja),'-C',str(build),'-t','commands',*targets],'ordered-ninja-commands',120)
        output.mkdir();(output/'generated').mkdir()
        for name,raw in (('ninja-deps.txt',b'host dependency fixture\n'),('ninja-target-commands.txt',b'host target fixture\n'),
                         ('generated/revision.h',b'// host generated fixture\n')):(output/name).write_bytes(raw)
        observed=dict(projectFiles=setup.prepared_inventory(prepared),objects={str(i)+'.o':dict(source=str(prepared/name))
            for i,name in enumerate(setup.REQUIRED_SOURCES)})
        if self.mutate_capture:self.mutate_capture(observed)
        (output/'observation.json').write_text(json.dumps(observed))
        receipt=dict(formatVersion=1,scope='actual-target-source-and-dependency-observation',targets=list(targets),
            objectElfMachines=[183],observedObjects=4,compileCommands=setup.files.identity(commands),dependenciesNotNewerThanObject=True,
            observedLinks=1,linkElfMachines=[183],linkDependenciesNotNewerThanOutput=True,
            outputFiles={path.relative_to(output).as_posix():setup.files.identity(path) for path in setup.files.installed_files(output)})
        if self.mutate_receipt:self.mutate_receipt(receipt)
        return receipt

    def readback(self,payload,receipt,prepared,compile_commands,**kwargs):
        self.readback_calls.append(kwargs)
        self.assertEqual(kwargs['expected_links'],1)
        self.assertEqual(kwargs['required_link_programs'],{setup.component.TARGET:setup.files.identity(payload/'bin/playerbots-schema')})
        self.assertEqual(kwargs['required_sources'],setup.REQUIRED_SOURCES)
        return dict(observedObjectMetadataReadback=True,originalObjectBytesIndependentlyReadback=False,
            observedLinkMetadataReadback=True,originalLinkInputBytesIndependentlyReadback=False)

    def run_build(self,**extra):
        contexts=[patch.object(setup.platform,'machine',return_value='aarch64'),
            patch.object(setup.component.isolated,'require_offline',return_value=dict(interfaces=['lo'],externalNetworkingAvailable=False)),
            patch.object(setup,'committed_recipes',side_effect=lambda *_:{name:setup.files.identity(setup.ROOT/name)
                for name in set(setup.component.RECIPES)|set(setup.RECIPES)}),
            patch.object(setup.component,'build',side_effect=self.initial_build),
            patch.object(setup.component.isolated,'verify_prepared',return_value=(self.prep,self.prep_identity,{})),
            patch.object(setup.component.inputs,'verify_environment',side_effect=self.environment_check),
            patch.object(setup.component.isolated,'run_owned',side_effect=self.run_command),
            patch.object(setup.component.reference,'commands',side_effect=setup.files.identity),
            patch.object(setup.files,'elf_header',return_value=dict(machine='AArch64')),
            patch.object(setup.files,'bounded_command',return_value=''),
            patch.object(setup.shutil,'which',return_value=sys.executable),
            patch.object(setup.capture,'capture',side_effect=self.capture),
            patch.object(setup.readback,'verify',side_effect=self.readback)]
        # reference.commands has three positional arguments; its fixture hashes
        # only the selected compile database without emulating real definitions.
        contexts[7]=patch.object(setup.component.reference,'commands',side_effect=lambda path,*_:setup.files.identity(path))
        started=[]
        try:
            for active in contexts:active.start();started.append(active)
            return setup.build(self.prepared,self.acquired,self.original_lock,self.environment,self.output,integration_revision=self.revision,**extra)
        finally:
            for active in reversed(started):active.stop()

    def test_wrong_arch_existing_and_overlapping_output_refuse_before_build(self):
        with patch.object(setup.platform,'machine',return_value='x86_64'),patch.object(setup.component,'build') as build, \
                self.assertRaisesRegex(ValueError,'native-arm64'):
            setup.build(self.prepared,self.acquired,self.original_lock,self.environment,self.output,integration_revision=self.revision)
        build.assert_not_called();self.assertFalse(self.output.exists())
        for output in (self.prepared/'nested',self.acquired/'nested',self.prepared):
            with patch.object(setup.platform,'machine',return_value='aarch64'),patch.object(setup.component,'build') as build, \
                    self.assertRaisesRegex(ValueError,'output-preserved'):
                setup.build(self.prepared,self.acquired,self.original_lock,self.environment,output,integration_revision=self.revision)
            build.assert_not_called()

    def test_orchestration_stabilizes_only_helper_and_keeps_initial_receipt_immutable(self):
        result=self.run_build();payload=self.output/'payload'
        self.assertEqual(result['scope'],setup.SCOPE);self.assertTrue(result['qualificationSucceeded'])
        self.assertEqual(self.capture_calls,[setup.TARGETS])
        self.assertEqual(len(self.readback_calls),1);self.assertTrue(result['observedLinkMetadataReadback'])
        self.assertEqual(result['targetSourceDependencies']['observedLinks'],1)
        self.assertEqual(self.executed[0][1:],['--build',str(self.output/'component/build'),'--parallel','2','--target',setup.component.TARGET])
        self.assertEqual((payload/'provenance/helper-source-build.json').read_bytes(),self.initial_raw)
        self.assertEqual((self.output/'component/qualification.json').read_bytes(),self.initial_raw)
        self.assertEqual((payload/'provenance/first-pass-playerbots-schema').read_bytes(),self.first_bytes)
        self.assertEqual((payload/'bin/playerbots-schema').read_bytes(),self.final_bytes)
        self.assertNotEqual(result['initialExecutable'],result['executable'])
        self.assertEqual(result['helperSourceBuildReceipt'],setup.files.identity(payload/'provenance/helper-source-build.json'))
        self.assertEqual(result['compileCommands'],result['newCompileCommands'])
        self.assertEqual(json.loads((payload/'source-build.json').read_bytes()),result)
        self.assertEqual(set(result['payloadFiles']),{path.relative_to(payload).as_posix() for path in setup.files.installed_files(payload)}-{'source-build.json'})
        for name,pin in result['payloadFiles'].items():self.assertEqual(setup.files.identity(payload/name),pin)
        for flag in ('sourceCompanionComplete','transitiveIncludeClosureSealed','selectedNewHelperSqlQualified',
                     'originalHelperNativeSqlQualificationTransferred','originalMeasuredHelperReplaced','databaseExecuted',
                     'fullServerCompileSucceeded','playerbotsAiQualified','worldserverQualified','androidRuntimeQualified','gameplayQualified'):
            self.assertIs(result[flag],False)

    def test_retains_exact_acquired_tree_and_required_source_observation_layout(self):
        result=self.run_build();payload=self.output/'payload'
        for path in setup.files.installed_files(self.acquired):
            self.assertEqual((payload/'acquired'/path.relative_to(self.acquired)).read_bytes(),path.read_bytes())
        for name in ('observation.json','ninja-deps.txt','ninja-target-commands.txt','generated/revision.h'):
            self.assertEqual(setup.files.identity(payload/'build/dependency-observation'/name),result['targetSourceDependencies']['outputFiles'][name])
        self.assertEqual((payload/'source-inputs/original-sources.lock.json').read_bytes(),self.original_lock.read_bytes())
        for name in setup.RECIPES:self.assertEqual((payload/'recipes'/name).read_bytes(),(setup.ROOT/name).read_bytes())

    def test_old_measured_hash_may_match_without_transferring_sql_qualification(self):
        original=copy.deepcopy(self.original);original['executable']=dict(bytes=len(self.final_bytes),sha256=hashlib.sha256(self.final_bytes).hexdigest())
        with patch.object(setup.measured,'load_pin',return_value=(original,self.original_identity)):
            result=self.run_build()
        self.assertTrue(result['finalExecutableMatchesMeasuredHelper'])
        self.assertFalse(result['selectedNewHelperSqlQualified']);self.assertFalse(result['originalHelperNativeSqlQualificationTransferred'])

    def test_unknown_dependency_or_missing_actual_required_unit_fails_truthfully(self):
        for kind in ('unknown','missing-unit','changed-source'):
            def mutate(observed):
                if kind=='unknown':observed['projectFiles']['source/unknown.h']=dict(bytes=1,sha256='0'*64)
                elif kind=='missing-unit':observed['objects'].pop('0.o')
                else:(self.prepared/setup.HEADER).write_bytes((self.prepared/setup.HEADER).read_bytes()+b' ')
            self.mutate_capture=mutate
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.run_build()
            value=json.loads((self.output/'qualification.json').read_bytes())
            self.assertFalse(value['qualificationSucceeded']);self.assertFalse(value['actualTargetSourceDependencyObservation'])
            self.assertEqual(value['phase'],'failed')
            # Each case is a new fixture output; existing failed state is kept.
            self.output=self.root/('result-'+kind)

    def test_target_command_policy_rejects_world_third_build_and_missing_stabilization(self):
        build=Path('/owned/build')
        configure=dict(phase='configure',argv=['cmake','-S','/source','-B',str(build)])
        target=dict(phase='build',argv=['cmake','--build',str(build),'--target',setup.component.TARGET])
        setup.target_builds([configure,target,target],build)
        for rows in ([configure,target],[configure,target,target,target],
                     [configure,target,dict(target,argv=['cmake','--build',str(build),'--target','worldserver'])]):
            with self.assertRaises(ValueError):setup.target_builds(rows,build)

    def test_missing_extra_wrong_machine_or_stale_final_link_refuses_before_success(self):
        for name,value in (('observedLinks',0),('observedLinks',2),('observedLinks',True),
                           ('linkElfMachines',[62]),('linkDependenciesNotNewerThanOutput',False)):
            self.mutate_receipt=lambda receipt:receipt.update({name:value})
            with self.subTest(field=name,value=value),self.assertRaisesRegex(ValueError,'actual-native-object-observation'):
                self.run_build()
            proof=json.loads((self.output/'qualification.json').read_bytes())
            self.assertFalse(proof['qualificationSucceeded']);self.assertFalse(proof['actualTargetSourceDependencyObservation'])
            self.assertFalse(self.readback_calls)
            self.output=self.root/('bad-link-'+str(len(list(self.root.iterdir()))))

    def test_retained_recipe_or_acquired_drift_cannot_claim_source_observation_success(self):
        original=setup.retain
        def changed(*args):
            inventory,receipt=original(*args)
            inventory['recipes/tools/qualify_playerbots_helper_sources.py']=dict(bytes=1,sha256='0'*64)
            return inventory,receipt
        with patch.object(setup,'retain',side_effect=changed),self.assertRaisesRegex(ValueError,'retained-committed-recipes'):
            self.run_build()
        proof=json.loads((self.output/'qualification.json').read_bytes())
        self.assertFalse(proof['qualificationSucceeded']);self.assertFalse(proof['actualTargetSourceDependencyObservation'])

    def test_committed_recipe_check_uses_exact_head_read_only_git_and_rejects_changed_blob(self):
        recipes=sorted(set(setup.component.RECIPES)|set(setup.RECIPES));calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            if argv[-2:]==['rev-parse','HEAD']:return SimpleNamespace(stdout=(self.revision+'\n').encode())
            name=argv[-1].split(':',1)[1]
            return SimpleNamespace(stdout=(setup.ROOT/name).read_bytes())
        with patch.object(setup.subprocess,'run',side_effect=run):result=setup.committed_recipes(self.revision)
        self.assertEqual(set(result),set(recipes))
        for argv,kwargs in calls:
            self.assertEqual(argv[:3],['git','-c','safe.directory='+str(setup.ROOT)])
            self.assertEqual(kwargs['env']['GIT_NO_LAZY_FETCH'],'1');self.assertEqual(kwargs['env']['GIT_OPTIONAL_LOCKS'],'0')
            self.assertNotIn('write-tree',argv);self.assertNotIn('read-tree',argv)
        with patch.object(setup.subprocess,'run',return_value=SimpleNamespace(stdout=b'0'*40+b'\n')):
            with self.assertRaisesRegex(ValueError,'integration-head'):setup.committed_recipes(self.revision)
        def bad(argv,**kwargs):
            value=run(argv,**kwargs)
            return value if argv[-2:]==['rev-parse','HEAD'] else SimpleNamespace(stdout=value.stdout+b'changed')
        with patch.object(setup.subprocess,'run',side_effect=bad):
            with self.assertRaisesRegex(ValueError,'not-committed'):setup.committed_recipes(self.revision)


if __name__=='__main__':unittest.main()
