"""Unsealed source-input fixtures; no real server or source rebuild is qualified."""
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from tools import package_server_engine_source_inputs as source


def git(root, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=root, stderr=subprocess.PIPE).decode().strip()


def repository(root, members):
    root.mkdir(parents=True)
    git(root, 'init'); git(root, 'config', 'user.email', 'source-fixture@example.invalid')
    git(root, 'config', 'user.name', 'Source Fixture')
    for name, raw in members.items():
        path = root/name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw.encode() if isinstance(raw, str) else raw)
    git(root, 'add', '.'); git(root, 'commit', '-m', 'synthetic source fixture')
    return git(root, 'rev-parse', 'HEAD')


def commands(path, *, extra=None, missing_include=False):
    prefix = '/original-ci/sources/server'
    rows = []
    for filename in ('src/server/apps/worldserver/Main.cpp', 'src/tools/dbimport/Main.cpp'):
        rows.append(dict(directory='/original-ci/out/server', file=prefix+'/'+filename,
            arguments=['c++', '-I'+prefix+'/src', '-I', prefix+'/modules/mod-one/libs',
                '-DAC_MODULES_LIST="mod-one,"', '-DCONFIG_FILE_LIST="one.conf,"', '-c', prefix+'/'+filename]))
    if extra: rows.append(dict(directory='/original-ci/out/server', file=prefix+'/'+extra,
        arguments=['c++','-I'+prefix+'/src','-c',prefix+'/'+extra]))
    if missing_include: rows[0]['arguments'] += ['-isystem', prefix+'/missing/headers']
    path.write_text(json.dumps(rows)+'\n')
    return rows


class SelectionAndCoverage(unittest.TestCase):
    def test_shallow_checkout_uses_separate_exact_commit_fetch(self):
        revision='a'*40; objects=object()
        with patch.object(source.subprocess,'run',side_effect=[SimpleNamespace(returncode=1),
                SimpleNamespace(returncode=0), SimpleNamespace(returncode=0)]) as command, \
             patch.object(source.content,'GitObjects',return_value=objects) as reader:
            with source.integration_objects(revision) as actual: self.assertIs(actual,objects)
        self.assertEqual(command.call_args_list[-1].args[0],
            ['git','fetch','--depth','1','--no-tags',source.INTEGRATION_URL,revision])
        self.assertNotEqual(command.call_args_list[-1].kwargs['cwd'],source.ROOT)
        self.assertEqual(reader.call_args.args[1:],(revision,False))

    def test_selected_code_and_notices_exclude_assets_and_unselected_modules(self):
        selection, _ = source.rules()
        names = set(selection['rootFiles']) | {'src/main.cpp', 'deps/fmt/LICENSE', 'conf/dist/world.conf.dist',
            'deps/acore/mysql-tools/bin/mysql.exe', 'Harvested/data.DBC', 'modules/CMakeLists.txt',
            'modules/mod-one/CMakeLists.txt', 'modules/mod-one/src/One.cpp', 'modules/mod-one/libs/json.hpp',
            'modules/mod-one/conf/one.conf.dist', 'modules/mod-one/lua/third-party/COPYRIGHT',
            'modules/mod-one/data/texture.blp', 'modules/mod-two/src/Two.cpp'}
        fake = type('Objects', (), {'files': {name:dict(kind='blob',mode='100644') for name in names}})()
        selected = source.select_server(fake, ['mod-one'], selection)
        for name in ('src/main.cpp','deps/fmt/LICENSE','modules/CMakeLists.txt', 'modules/mod-one/libs/json.hpp',
                     'modules/mod-one/CMakeLists.txt', 'modules/mod-one/conf/one.conf.dist',
                     'modules/mod-one/lua/third-party/COPYRIGHT'):
            self.assertIn(name, selected)
        self.assertFalse(any(name in selected for name in ('Harvested/data.DBC','deps/acore/mysql-tools/bin/mysql.exe',
            'modules/mod-one/data/texture.blp', 'modules/mod-two/src/Two.cpp')))
        fake.files['src/main.cpp']['mode'] = '120000'
        with self.assertRaisesRegex(ValueError, 'nonregular-engine-source'): source.select_server(fake, ['mod-one'], selection)

    def test_compiler_source_and_include_coverage_are_required_without_transitive_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'compile_commands.json'
            commands(path, extra='modules/mod-one/src/One.cpp')
            selected = {'src/server/apps/worldserver/Main.cpp','src/tools/dbimport/Main.cpp',
                        'modules/mod-one/src/One.cpp','modules/mod-one/libs/json.hpp'}
            proof = source.compiler_coverage(path, selected)
            self.assertTrue(proof['observedSourceFilesCovered']); self.assertFalse(proof['transitiveIncludeClosureProved'])
            with self.assertRaisesRegex(ValueError, 'compiled-server-source-not-selected'):
                source.compiler_coverage(path, selected-{'modules/mod-one/src/One.cpp'})
            commands(path, missing_include=True)
            with self.assertRaisesRegex(ValueError, 'include-directory-empty'): source.compiler_coverage(path, selected)

    def test_external_archive_requires_exact_original_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); lock = source.ROOT/'sources.lock.json'
            command_path = root/'commands.json'; commands(command_path)
            selected, command_identity = source.modules.extract_commands(command_path)
            build = dict(schemaVersion=1, architecture='Linux-ARM64', sourceCheckoutAndPatchesVerified=True,
                serverSource=source.fetch_sources.load_lock(lock)['sources']['server'],
                sourcesLock=source.files.identity(lock), integrationRevision='a'*40, buildId='synthetic.1')
            build_path=root/'build.json'; build_path.write_bytes(source.package.canonical(build))
            compiled = dict(formatVersion=1, scope='compiled-server-module-selection',
                generatedListsMatchInstalledBinaries=True, source=build['serverSource'],
                sourceLockSha256=build['sourcesLock']['sha256'], serverBuild=source.files.identity(build_path),
                compileCommands=command_identity, enabledModules=selected['modules'], configFiles=selected['configFiles'])
            compiled_path=root/'modules.json'; compiled_path.write_bytes(source.package.canonical(compiled))
            lua=root/'lua.tar.gz'; lua.write_bytes(b'synthetic archive; no Lua source claim')
            with patch.object(source.fetch_sources, 'verify_checkout'):
                with self.assertRaisesRegex(ValueError, 'original-lua-5.2.4'):
                    source.validate_inputs(root, build_path, compiled_path, command_path, lock, lua)
                with patch.object(source, 'LUA_SHA256', source.files.identity(lua)['sha256']):
                    proof=source.validate_inputs(root, build_path, compiled_path, command_path, lock, lua)
                self.assertEqual(proof['commands'], command_identity)
                build['serverSource']=copy.deepcopy(build['serverSource']); build['serverSource']['patches']=[]
                build_path.write_bytes(source.package.canonical(build))
                with self.assertRaisesRegex(ValueError, 'source-build-selection-mismatch'):
                    source.validate_inputs(root, build_path, compiled_path, command_path, lock, lua)


class RealGitInputArchive(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name); self.server=self.root/'server'
        server_members={name:'synthetic root fixture\n' for name in source.rules()[0]['rootFiles']}
        server_members['.gitmodules']='[submodule "fixture"]\n path = '+source.content.ELUNA+'\n url = https://example.invalid/fixture.git\n'
        server_members.update({'src/server/apps/worldserver/Main.cpp':'int pristine_world=1;\n',
            'src/tools/dbimport/Main.cpp':'int fixture_import=2;\n', 'deps/fmt/LICENSE':'fixture dependency notice\n',
            'conf/dist/world.conf.dist':'# fixture\n', 'modules/CMakeLists.txt':'# root module build\n',
            'modules/mod-one/CMakeLists.txt':'# module build\n', 'modules/mod-one/src/One.cpp':'int module=3;\n',
            'modules/mod-one/libs/json.hpp':'// fixture embedded notice\n',
            'modules/mod-one/conf/one.conf.dist':'# fixture\n', 'modules/mod-one/LICENSE':'fixture module notice\n',
            'modules/mod-one/data/private.mpq':'excluded proprietary-fixture marker',
            'deps/acore/mysql-tools/bin/mysql.exe':'excluded binary-fixture marker',
            'Harvested/private.DBC':'excluded data-fixture marker'})
        repository(self.server, server_members)
        self.eluna=self.server/source.content.ELUNA
        eluna_commit=repository(self.eluna, {'LICENSE':'fixture Eluna notice\n','Eluna.cpp':'int lua_fixture=4;\n',
            'extensions/StackTracePlus/LICENSE':'fixture extension notice\n','docs/README.md':'whole-tree fixture\n'})
        git(self.server,'update-index','--add','--cacheinfo','160000,'+eluna_commit+','+source.content.ELUNA)
        git(self.server,'commit','-m','record synthetic Eluna gitlink')
        server_commit=git(self.server,'rev-parse','HEAD')
        self.pin=dict(commit=server_commit, submodules={source.content.ELUNA:eluna_commit}, patches=[])
        self.lock=self.root/'lock.json'; self.lock.write_text(json.dumps({'fixture':True,'sources':{'server':self.pin}})+'\n')
        integration_members={name:'# fixture build input\n' for name in (
            'LICENSE','.github/workflows/server.yml','config/local-server.json','runtime/server-lua-map.json',
            'runtime/server/Dockerfile','runtime/server/sources.lock.json','runtime/server/ubuntu.sources',
            'runtime/server/inrelease.SHA256SUMS','runtime/server/mysql-binaries.SHA256SUMS',
            'tools/fetch_sources.py','tests/srp6_reference.cmake','tests/srp6_reference.cpp','runtime/mysql_bootstrap.py')}
        integration_members['sources.lock.json']=self.lock.read_bytes()
        self.integration=self.root/'integration'; integration_commit=repository(self.integration,integration_members)
        self.build_path=self.root/'server-build.json'
        self.build_path.write_text(json.dumps(dict(buildId='synthetic.1', integrationRevision=integration_commit))+'\n')
        self.compiled_path=self.root/'modules.json'; self.compiled_path.write_text('{"fixture":true}\n')
        self.commands=self.root/'commands.json'; commands(self.commands, extra='modules/mod-one/src/One.cpp')
        self.lua=self.root/'lua.tar.gz'; self.lua.write_bytes(b'synthetic original archive fixture')
        self.proof=dict(source=self.pin, sourceLock=source.files.identity(self.lock),
            build=json.loads(self.build_path.read_bytes()), buildIdentity=source.files.identity(self.build_path),
            compiled={'enabledModules':['mod-one']}, compiledIdentity=source.files.identity(self.compiled_path),
            commands=source.files.identity(self.commands), lua=source.local_identity(self.lua))
        adapted=self.server/'src/server/apps/worldserver/Main.cpp'; adapted.write_text('int adapted_world=7;\n')
        git(self.server,'add','src/server/apps/worldserver/Main.cpp')

    def build(self, output):
        with patch.object(source,'ROOT',self.integration), \
             patch.object(source,'validate_inputs',return_value=copy.deepcopy(self.proof)), \
             patch.object(source.content,'adaptation_records',return_value=[{'fixture':'indexed adapted source'}]):
            return source.build(output,self.server,self.build_path,self.compiled_path,self.commands,self.lock,self.lua)

    def test_real_git_archive_preserves_pristine_adapted_notices_and_false_flags(self):
        output=self.root/'source-inputs'; receipt=self.build(output)
        self.assertTrue(receipt['completeArchiveReadbackVerified'])
        self.assertFalse(receipt['sourceCompanionComplete']); self.assertFalse(receipt['isolatedSourceRebuildQualified'])
        archive=output/receipt['archive']['file']
        source.package.verify_archive(archive,receipt['archiveFiles'])
        with tarfile.open(archive,'r:gz') as package:
            self.assertEqual(package.extractfile('source/src/server/apps/worldserver/Main.cpp').read(), b'int pristine_world=1;\n')
            self.assertEqual(package.extractfile('adapted-source/src/server/apps/worldserver/Main.cpp').read(), b'int adapted_world=7;\n')
            self.assertEqual(package.extractfile('source/'+source.content.ELUNA+'/LICENSE').read(),b'fixture Eluna notice\n')
            self.assertIn('source/modules/mod-one/LICENSE',package.getnames())
            self.assertIn('integration/tests/srp6_reference.cpp',package.getnames())
            self.assertIn('external/lua-5.2.4.tar.gz',package.getnames())
            self.assertFalse(any('private.mpq' in name or 'private.DBC' in name or 'mysql.exe' in name for name in package.getnames()))
            manifest=json.loads(package.extractfile('metadata/source-inputs.json').read())
            self.assertFalse(manifest['transitiveIncludeClosureProved'])
            self.assertEqual(len(manifest['adaptedFiles']),1)
            self.assertNotEqual(manifest['adaptedFiles'][0]['pristine']['sha256'],manifest['adaptedFiles'][0]['adapted']['sha256'])
        other=self.root/'source-inputs-repeat'; repeated=self.build(other)
        self.assertEqual(receipt['archive'],repeated['archive'])
        self.assertEqual(self.lua.read_bytes(),b'synthetic original archive fixture')

    def test_existing_or_overlapping_output_preserved_before_source_verification(self):
        output=self.root/'existing'; output.mkdir(); (output/'marker').write_text('preserved')
        for path in (output,self.server/'new-package'):
            with patch.object(source,'validate_inputs') as checked, self.assertRaisesRegex(ValueError,'output-exists-or-overlaps'):
                source.build(path,self.server,self.build_path,self.compiled_path,self.commands,self.lock,self.lua)
            checked.assert_not_called()
        self.assertEqual((output/'marker').read_text(),'preserved')

    def test_changed_local_input_during_archive_creation_is_not_published(self):
        original=source.package.write_archive
        def corrupt_then_write(*args,**kwargs):
            self.lua.write_bytes(b'changed fixture archive after verification')
            return original(*args,**kwargs)
        output=self.root/'rejected'
        with patch.object(source.package,'write_archive',side_effect=corrupt_then_write), \
             patch('sys.stderr',new_callable=io.StringIO), self.assertRaisesRegex(ValueError,'SHA-256 mismatch|truncated package input'):
            self.build(output)
        self.assertFalse(output.exists())
        stages=list(self.root.glob('.rejected.stage-*')); self.assertEqual(len(stages),1)
        self.assertEqual(stages[0].stat().st_mode & 0o777,0o700)


if __name__=='__main__': unittest.main()
