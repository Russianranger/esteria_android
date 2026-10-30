"""Small actual host GCC/Ninja observations; never an ARM64/source-seal claim."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import capture_ordered_extractor_dependencies as capture


class DependencyParsing(unittest.TestCase):
    def test_stale_malformed_duplicate_or_wrong_count_records_refuse(self):
        good='a.o: #deps 1, deps mtime 1 (VALID)\n    ../source/a.c\n\n'
        self.assertEqual(capture.parse_dependencies(good)['a.o']['dependencies'], ['../source/a.c'])
        for bad in (good.replace('VALID','STALE'),good.replace('#deps 1','#deps 2'),good+good,
                    'orphan\n',good.replace('    ../','../')):
            with self.subTest(text=bad), self.assertRaises(ValueError):capture.parse_dependencies(bad)

    def test_repeated_include_spellings_preserve_exact_advertised_raw_count(self):
        raw='a.o: #deps 2, deps mtime 1 (VALID)\n    ../source/a.c\n    ../source/a.c\n\n'
        self.assertEqual(capture.parse_dependencies(raw)['a.o']['dependencies'],['../source/a.c','../source/a.c'])
        with self.assertRaisesRegex(ValueError,'count differs'):
            capture.parse_dependencies(raw.replace('#deps 2','#deps 3'))

    def test_duplicate_compile_objects_or_ambiguous_arguments_refuse(self):
        row=dict(directory='/build',file='/source/a.c',command='/usr/bin/gcc -c /source/a.c -o a.o')
        self.assertEqual(len(capture.compile_database(json.dumps([row]).encode(),Path('/build'))),1)
        with self.assertRaisesRegex(ValueError,'duplicate compile database object'):
            capture.compile_database(json.dumps([row,row]).encode(),Path('/build'))
        for command in ('gcc -c a.c -o a.o -o b.o','gcc -c a.c -o a.o && other'):
            with self.assertRaises(ValueError):
                capture.compile_database(json.dumps([dict(row,command=command)]).encode(),Path('/build'))


@unittest.skipUnless(shutil.which('gcc') and shutil.which('ninja'), 'actual host GCC and Ninja required')
class ActualHostDependencies(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='ordered-dependency-host-')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name).resolve()
        self.prepared=self.root/'prepared';self.build=self.root/'build';self.build.mkdir()
        for name in ('source','external','integration'):(self.prepared/name).mkdir(parents=True)
        self.gcc=Path(shutil.which('gcc')).resolve();self.ninja=Path(shutil.which('ninja')).resolve()
        (self.prepared/'source/shared.h').write_text('#define SHARED 7\n')
        (self.build/'generated.h').write_text('#define GENERATED 9\n')
        self.rows=[];ninja=['rule cc','  command = '+str(self.gcc)+' -MD -MF $out.d -I'+str(self.build)+' -c $in -o $out',
            '  depfile = $out.d','  deps = gcc','rule link','  command = '+str(self.gcc)+' $in -o $out']
        for name in capture.TARGETS:
            source=self.prepared/'source'/(name+'.c')
            source.write_text('#include <stddef.h>\n#include "shared.h"\n#include "generated.h"\nint main(void){return SHARED+GENERATED;}\n')
            obj=name+'.o';ninja.extend(['build '+obj+': cc '+str(source),'build '+name+': link '+obj])
            self.rows.append(dict(directory=str(self.build),file=str(source),
                arguments=[str(self.gcc),'-I'+str(self.build),'-c',str(source),'-o',obj]))
        (self.build/'build.ninja').write_text('\n'.join(ninja)+'\n')
        subprocess.run([str(self.ninja),'-C',str(self.build),*capture.TARGETS],check=True,capture_output=True,timeout=30)
        self.commands=self.build/'compile_commands.json';self.commands.write_text(json.dumps(self.rows))
        self.logs=self.root/'logs';self.logs.mkdir();self.calls=[]

    def run_command(self,argv,label,timeout):
        self.calls.append((argv,label,timeout));log=self.logs/(label+'.log')
        result=subprocess.run(argv,capture_output=True,timeout=timeout,check=True)
        self.assertFalse(result.stderr);log.write_bytes(result.stdout);return log

    def observe(self,**kwargs):
        return capture.capture(self.build,self.prepared,self.commands,self.ninja,kwargs.get('run',self.run_command),
                               kwargs.get('output',self.root/'observation'))

    def test_actual_built_units_project_system_and_generated_headers_are_closed(self):
        proof=self.observe();self.assertTrue(proof['actualTargetSourceDependencyObservation'])
        self.assertTrue(proof['dependenciesNotNewerThanObject'])
        self.assertEqual(proof['observedObjects'],2);self.assertGreater(proof['observedSystemHeaders'],0)
        self.assertEqual(proof['observedGeneratedFiles'],1);self.assertFalse(proof['sourceCompanionComplete'])
        self.assertFalse(proof['androidRuntimeQualified']);self.assertFalse(proof['systemHeaderSourcesCopied'])
        output=self.root/'observation';data=json.loads((output/'observation.json').read_text())
        self.assertIn('source/shared.h',data['projectFiles']);self.assertIn('generated.h',data['generatedFiles'])
        self.assertEqual((output/'generated/generated.h').read_bytes(),(self.build/'generated.h').read_bytes())
        self.assertEqual(set(proof['outputFiles']),{p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()})
        for name,row in proof['outputFiles'].items():self.assertEqual(capture.identity(output/name),row)
        self.assertFalse(any(p.suffix in ('.o','.a','.so') for p in output.rglob('*')))
        self.assertEqual(self.calls,[
            ([str(self.ninja),'-C',str(self.build),'-t','deps'],'ordered-ninja-deps',120),
            ([str(self.ninja),'-C',str(self.build),'-t','commands',*capture.TARGETS],'ordered-ninja-commands',120)])

    def test_callback_failure_cannot_produce_an_observation_receipt(self):
        def failed(argv,label,timeout):
            raise RuntimeError('bounded parent command failed')
        with self.assertRaisesRegex(RuntimeError,'parent command failed'):
            self.observe(run=failed)
        self.assertFalse((self.root/'observation/observation.json').exists())

    def test_existing_output_refuses_before_running_Ninja(self):
        output=self.root/'saved';output.mkdir();(output/'keep').write_bytes(b'kept')
        with self.assertRaisesRegex(ValueError,'fresh dependency'):
            self.observe(output=output)
        self.assertEqual(self.calls,[]);self.assertEqual((output/'keep').read_bytes(),b'kept')

    def test_unmatched_compiler_command_and_unknown_dependency_root_refuse(self):
        self.rows[0]['arguments'].insert(1,'-DCHANGED=1');self.commands.write_text(json.dumps(self.rows))
        with self.assertRaisesRegex(ValueError,'target command differs'):self.observe()
        self.rows[0]['arguments'].remove('-DCHANGED=1');self.commands.write_text(json.dumps(self.rows))
        outside=self.root/'unknown.h';outside.write_text('#define UNKNOWN 1\n')
        def injected(argv,label,timeout):
            log=self.run_command(argv,label,timeout)
            if label.endswith('deps'):
                text=log.read_text();text=text.replace('    '+str(self.prepared/'source/shared.h'),'    '+str(outside))
                log.write_text(text)
            return log
        with self.assertRaisesRegex(ValueError,'unknown non-system'):
            self.observe(run=injected,output=self.root/'unknown-observation')

    def test_changed_dependency_during_observation_is_refused(self):
        original=capture.identity;header=self.prepared/'source/shared.h';seen=0
        def mutating(path):
            nonlocal seen
            row=original(path)
            if path==header:
                seen+=1
                if seen==1:header.write_text('#define SHARED 8\n')
            return row
        with patch.object(capture,'identity',side_effect=mutating):
            with self.assertRaisesRegex(ValueError,'dependency changed|dependency newer'):
                self.observe()

    def test_header_changed_after_compile_refuses_until_actual_targets_are_rebuilt(self):
        header=self.build/'generated.h';header.write_text('#define GENERATED 10\n')
        with self.assertRaisesRegex(ValueError,'dependency newer than compiled object; replay target build'):
            self.observe()
        self.assertFalse((self.root/'observation/observation.json').exists())
        subprocess.run([str(self.ninja),'-C',str(self.build),*capture.TARGETS],
                       check=True,capture_output=True,timeout=30)
        self.logs=self.root/'replay-logs';self.logs.mkdir()
        proof=self.observe(output=self.root/'replayed-observation')
        self.assertTrue(proof['dependenciesNotNewerThanObject'])
        self.assertEqual((self.root/'replayed-observation/generated/generated.h').read_bytes(),header.read_bytes())

    def test_invalid_object_or_dependency_count_cannot_be_metadata_success(self):
        path=self.build/(capture.TARGETS[0]+'.o');before=path.stat()
        path.write_bytes(b'not an ELF object');os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        with self.assertRaisesRegex(ValueError,'ELF64 relocatable'):
            self.observe()

    def test_explicit_single_target_keeps_the_same_closed_dependency_checks(self):
        build=self.root/'single-build';build.mkdir();target=capture.TARGETS[0]
        (build/'generated.h').write_bytes((self.build/'generated.h').read_bytes())
        (build/'build.ninja').write_text((self.build/'build.ninja').read_text().replace(str(self.build),str(build)))
        row=dict(self.rows[0]);row['directory']=str(build)
        row['arguments']=[value.replace(str(self.build),str(build)) for value in row['arguments']]
        commands=build/'compile_commands.json';commands.write_text(json.dumps([row]))
        subprocess.run([str(self.ninja),'-C',str(build),target],check=True,capture_output=True,timeout=30)
        proof=capture.capture(build,self.prepared,commands,self.ninja,self.run_command,
            self.root/'single-observation',targets=(target,))
        self.assertEqual(proof['targets'],[target]);self.assertEqual(proof['observedObjects'],1)
        self.assertEqual(proof['scope'],'actual-target-source-and-dependency-observation')
        self.assertTrue(proof['dependenciesNotNewerThanObject']);self.assertFalse(proof['sourceCompanionComplete'])
        calls=len(self.calls)
        for invalid in ((),['map_extractor'],('--bad-option',),(target,target)):
            with self.subTest(targets=invalid),self.assertRaisesRegex(ValueError,'safe target tuple'):
                capture.capture(build,self.prepared,commands,self.ninja,self.run_command,self.root/'invalid',targets=invalid)
        self.assertEqual(len(self.calls),calls)


if __name__=='__main__':unittest.main()
