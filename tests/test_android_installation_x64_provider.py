"""Host byte/transaction fixtures only; no native SQL or Android execution."""
import ast
import copy
import gzip
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import provider_android_installation_x64 as provider


class AndroidInstallationX64Provider(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def put(self, name, raw=b'host-fixture-not-an-elf', mode=0o444):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw); path.chmod(mode); return path

    def test_pending_gate_refuses_before_output_or_source_admission(self):
        target = self.root / 'must-not-exist'
        pending=dict(formatVersion=1,scope=provider.gate.SCOPE,repository='Russianranger/esteria_android',
            enabled=False,state=provider.gate.PENDING,nativeSql=None,provider=None,providerReadback=None,
            **{name:False for name in provider.gate.FALSE_FLAGS})
        lock=self.put('pending.json',json.dumps(pending).encode())
        with patch.object(provider.gate,'LOCK',lock),patch.object(provider, 'source_snapshot') as source, \
                patch.object(provider.native, 'admit_component') as component, \
                self.assertRaisesRegex(ValueError, 'native-sql-measurement-required'):
            provider.build(self.root / 'missing-input', target)
        source.assert_not_called(); component.assert_not_called(); self.assertFalse(target.exists())
        with patch.object(provider.gate,'LOCK',lock),self.assertRaisesRegex(ValueError,'native-sql-measurement-required'):
            provider.readback(self.root/'missing-product')

    def test_default_external_profile_refuses_before_frozen_checkout_or_runtime_access(self):
        with patch.object(provider.gate.frozen_mysql,'inspect') as frozen, \
                patch.object(provider.subprocess,'run') as command, \
                self.assertRaisesRegex(ValueError,'measured-native-sql-and-provider-required'):
            provider.verify_external(*(self.root/name for name in ('provider','source','mysql','proot')))
        frozen.assert_not_called();command.assert_not_called()

    def test_wrong_frozen_recipe_cannot_select_or_execute_a_verifier(self):
        with patch.object(provider.gate,'load_pin',return_value={'enabled':True}) as gate, \
                patch.object(provider.gate.frozen_mysql,'inspect',side_effect=ValueError('frozen-exact-checkout-required')) as frozen, \
                patch.object(provider.subprocess,'run') as command, \
                self.assertRaisesRegex(ValueError,'frozen-exact-checkout-required'):
            provider.verify_external(*(self.root/name for name in ('provider','source','mysql','proot')))
        gate.assert_called_once_with(require_enabled=True);frozen.assert_called_once_with(self.root/'source');command.assert_not_called()

    def test_actual_current_checkout_cannot_be_used_as_historical_runtime_recipe(self):
        with patch.object(provider.gate,'load_pin',return_value={'enabled':True}), \
                self.assertRaisesRegex(ValueError,'mysql-frozen-consumer-checkout-revision'):
            provider.verify_external(self.root/'missing-provider',provider.ROOT,self.root/'missing-mysql',self.root/'missing-proot')

    def test_real_measurement_and_activation_commits_can_differ_only_in_selected_pins(self):
        repo=self.root/'git';repo.mkdir()
        def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL)
        git('init','-q');(repo/'source.py').write_bytes(b'unchanged source fixture\n');(repo/'selection.json').write_bytes(b'provider-pending\n')
        git('add','.');git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','measurement')
        measured=git('rev-parse','HEAD').decode().strip()
        recipe=dict(repository='Russianranger/esteria_android',commit=measured,files={'source.py':provider.files.identity(repo/'source.py')})
        original=self.root/'original';original.mkdir();(original/'source.py').write_bytes((repo/'source.py').read_bytes())
        (repo/'selection.json').write_bytes(b'actual measured provider pin fixture\n');git('add','selection.json')
        git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-qm','activation')
        self.assertNotEqual(measured,git('rev-parse','HEAD').decode().strip())
        with patch.object(provider,'ROOT',repo),patch.object(provider,'recipe_names',return_value=['source.py']):
            provider.verify_recipe(recipe,original);provider.require_current_code(recipe)
            (repo/'source.py').write_bytes(b'different executable source\n')
            with self.assertRaisesRegex(ValueError,'file-changed'):provider.require_current_code(recipe)

    def original_zip_fixture(self):
        companion=self.root/'companion';metadata=companion/'original-mysql-metadata';metadata.mkdir(parents=True)
        selected={}
        for name in ('provider.json','runtime.json','sources.lock.json','SOURCE-MANIFEST.json'):
            raw=('synthetic old metadata '+name).encode();(metadata/name).write_bytes(raw)
            selected['SOURCE-MANIFEST.json' if name=='SOURCE-MANIFEST.json' else 'provider/assets/mysql-probe/'+name]=provider.identity_bytes(raw)
        raw=b'synthetic original source zip byte fixture';archive=companion/'original-mysql-proot-completeSources.zip';archive.write_bytes(raw)
        frozen=dict(files=selected,artifacts=dict(completeSources=provider.identity_bytes(raw)))
        return companion,frozen

    def test_original_source_zip_is_pinned_before_original_member_reader(self):
        companion,frozen=self.original_zip_fixture()
        (companion/'original-mysql-proot-completeSources.zip').write_bytes(b'foreign source zip whose manifest was repinned')
        with patch.object(provider.mysql,'restore_sources') as reader,self.assertRaisesRegex(ValueError,'file-changed'):
            provider.original_mysql_source_readback(companion,frozen,{})
        reader.assert_not_called()

    def test_original_source_metadata_and_full_member_inventory_are_rechecked(self):
        companion,frozen=self.original_zip_fixture();actual=dict(allOriginalSourceZipMembers={'original/recipe.py':provider.identity_bytes(b'original source')})
        with patch.object(provider.mysql,'restore_sources',return_value=actual) as reader:
            self.assertEqual(provider.original_mysql_source_readback(companion,frozen,actual),actual)
            self.assertEqual(reader.call_args.args[2],frozen)
        with patch.object(provider.mysql,'restore_sources',return_value=actual),self.assertRaisesRegex(ValueError,'source-zip-members-differ'):
            provider.original_mysql_source_readback(companion,frozen,dict(allOriginalSourceZipMembers={}))
        (companion/'original-mysql-metadata/runtime.json').write_bytes(b'foreign runtime metadata')
        with patch.object(provider.mysql,'restore_sources') as reader,self.assertRaisesRegex(ValueError,'engine-copy-readback-mismatch'):
            provider.original_mysql_source_readback(companion,frozen,actual)
        reader.assert_not_called()

    def test_archive_streams_normalized_exec_modes_and_rejects_tamper(self):
        tree = self.root / 'tree'
        self.put('tree/bin/dbimport', b'#!/usr/bin/python3\n', 0o500)
        self.put('tree/helpers/playerbots-schema', b'#!/usr/bin/python3\n', 0o500)
        self.put('tree/libexec/ld-linux-x86-64.so.2', mode=0o500)
        self.put('tree/provenance/receipt.json', b'{}\n', 0o400)
        first = self.root / 'first.tar.gz'; second = self.root / 'second.tar.gz'
        inventory = provider.write_archive(tree, first)
        self.assertEqual(provider.write_archive(tree, second), inventory)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        for name in ('bin/dbimport', 'helpers/playerbots-schema', 'libexec/ld-linux-x86-64.so.2'):
            self.assertEqual(inventory[name]['mode'], 0o555)
        self.assertEqual(inventory['provenance/receipt.json']['mode'], 0o444)
        changed = copy.deepcopy(inventory); changed['helpers/playerbots-schema']['mode'] = 0o444
        with self.assertRaisesRegex(ValueError, 'member-metadata'):
            provider.engine.verify_archive(first, changed)

    def test_program_plan_marks_actual_elf_roles_and_requires_notice_inventory(self):
        tree=self.root/'tree'
        for name in ('bin/dbimport.elf','helpers/playerbots-schema.elf','libexec/ld-linux-x86-64.so.2',
                'libraries/usr/lib/x86_64-linux-gnu/libc.so.6'):
            self.put('tree/'+name,mode=0o555)
        self.put('tree/bin/dbimport',b'#!/usr/bin/python3\n',0o555)
        self.put('tree/provenance/x64-closure.json',b'{}\n')
        self.put('tree/notices/source/COPYING',b'synthetic original license fixture\n')
        actual=provider.programs_descriptor(tree,self.root/'actual.archive')
        for name,row in actual['requiredFiles'].items():
            self.assertEqual(row.get('elfMachine',0),62 if name.startswith(('libexec/','libraries/')) or name.endswith('.elf') else 0)
        (tree/'notices/source/COPYING').unlink()
        omitted=provider.programs_descriptor(tree,self.root/'omitted.archive')
        self.assertNotEqual(actual,omitted)
        self.assertNotIn('notices/source/COPYING',omitted['requiredFiles'])

    def test_archive_refuses_symlink_without_following_payload(self):
        tree = self.root / 'tree'; tree.mkdir()
        (tree / 'foreign').symlink_to(self.put('secret', b'fixture-private-data'))
        with self.assertRaises(ValueError): provider.write_archive(tree, self.root / 'refused.gz')

    def build_fixture(self):
        libraries = {}
        for name in ('lib64/ld-linux-x86-64.so.2', 'usr/lib/x86_64-linux-gnu/libc.so.6'):
            path = self.put('payload/libraries/' + name, ('synthetic-' + name).encode())
            libraries[name] = dict(provider.files.identity(path), elf=dict(machine=62))
        executables = {}
        for role in provider.ROLES:
            path = self.put('payload/bin/' + role, ('synthetic-' + role).encode())
            executables[role] = dict(provider.files.identity(path), elf=dict(machine=62))
        return dict(libraries=libraries, executables=executables)

    def test_android_invocations_bind_original_bytes_have_distinct_identity_and_preserve_exec_roles(self):
        build = self.build_fixture(); output = self.root / 'programs'; output.mkdir()
        report = dict(checkedInvocations={role: dict(invocation=provider.identity_bytes(b'native-sql-script')) for role in provider.ROLES})
        result = provider.invocations(self.root / 'payload', build, output, report)
        for role, row in result.items():
            self.assertEqual(row['actualExecutable'], provider.native.identity(build['executables'][role]))
            self.assertNotEqual(row['invocation'], report['checkedInvocations'][role]['invocation'])
            script = output / row['invocationPath']; ast.parse(script.read_text())
            self.assertTrue(script.stat().st_mode & 0o111)
            self.assertIn(provider.GUEST + '/' + row['actualPath'], script.read_text())
            self.assertIn("os.execv(PLAN['loader']", script.read_text())
            self.assertNotIn('/sql-work/', script.read_text())
        self.assertTrue((output / 'libexec/ld-linux-x86-64.so.2').stat().st_mode & 0o111)

    def test_foreign_machine_or_changed_original_is_refused_before_script_publication(self):
        build = self.build_fixture(); build['executables']['dbimport']['elf']['machine'] = 183
        output = self.root / 'programs'; output.mkdir()
        with self.assertRaisesRegex(ValueError, 'original-elf62-required'):
            provider.invocations(self.root / 'payload', build, output, {})
        self.assertFalse((output / 'bin/dbimport').exists())

    def original_fixture(self):
        payload = self.root / 'payload'; source = payload / 'corresponding-source/source-inputs'; source.mkdir(parents=True)
        rows = {}; raw_metadata = {}
        for name in provider.ORIGINALS:
            raw_metadata[name] = json.dumps(dict(originalSourceMember=name)).encode()
            rows[name] = provider.identity_bytes(raw_metadata[name])
        archive = source / 'server-engine-source-inputs.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            for name, raw in raw_metadata.items():
                member = tarfile.TarInfo(name); member.size = len(raw); bundle.addfile(member, io.BytesIO(raw))
        (source / 'source-inputs-receipt.json').write_text(json.dumps(dict(archive=provider.files.identity(archive), archiveFiles=rows)))
        build = dict(originalArm64Build=rows['metadata/server-build.json'], originalArm64Modules=rows['metadata/server-modules.json'],
            sourceLock=rows['integration/sources.lock.json'])
        return payload, build

    def test_original_source_metadata_is_exact_and_remains_original_origin(self):
        payload, build = self.original_fixture(); output = self.root / 'programs'; output.mkdir()
        provider.original_metadata(payload, build, output)
        self.assertEqual(provider.files.identity(output / 'provenance/server-build.json'), build['originalArm64Build'])
        self.assertEqual(provider.files.identity(output / 'provenance/server-modules.json'), build['originalArm64Modules'])
        self.assertEqual(provider.files.identity(output / 'provenance/sources.lock.json'), build['sourceLock'])
        self.assertIn('source/src/tools/dbimport/dbimport.conf.dist', (output / 'etc/dbimport.conf.dist').read_text())
        bad = dict(build, originalArm64Build=provider.identity_bytes(b'foreign origin'))
        failed = self.root / 'failed'; failed.mkdir()
        with self.assertRaisesRegex(ValueError, 'file-changed'):
            provider.original_metadata(payload, bad, failed)

    def test_source_snapshot_requires_clean_recipe_before_any_git_blob_adoption(self):
        with patch.object(provider.subprocess, 'check_output', return_value=b' M tools/changed.py\n') as git, \
                self.assertRaisesRegex(ValueError, 'clean-packaging-recipe-required'):
            provider.source_snapshot()
        self.assertEqual(git.call_count, 1)

    def test_source_companion_recipe_requires_original_git_bytes(self):
        source=self.put('recipe/tools/fixture.py',b'original-source-fixture\n')
        recipe=dict(repository='Russianranger/esteria_android',commit='a'*40,
            files={'tools/fixture.py':provider.files.identity(source)})
        with patch.object(provider,'recipe_names',return_value=['tools/fixture.py']), \
                patch.object(provider.subprocess,'check_output',return_value=source.read_bytes()) as git:
            provider.verify_recipe(recipe,self.root/'recipe')
            self.assertEqual(git.call_args.args[0][-1],'a'*40+':tools/fixture.py')
        with patch.object(provider,'recipe_names',return_value=['tools/fixture.py']), \
                patch.object(provider.subprocess,'check_output',return_value=b'foreign-source\n'), \
                self.assertRaisesRegex(ValueError,'source-recipe-differs-from-git'):
            provider.verify_recipe(recipe,self.root/'recipe')
        with self.assertRaisesRegex(ValueError,'source-recipe-schema'):
            provider.verify_recipe(recipe,self.root/'recipe')

    def helpers_fixture(self):
        root=self.root/'provider';assets=root/'assets/installation-probe-helpers';assets.mkdir(parents=True)
        recipe={name:provider.identity_bytes(('synthetic recipe '+name).encode()) for name in provider.recipe_names()}
        rows={}
        for name in provider.HELPERS:
            source=('config/local-server.json' if name=='local-server.json' else
                'tests/android-installation-x64/'+name if name=='installation_x64_entry.py' else 'runtime/'+name)
            target=assets/name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(('synthetic recipe '+source).encode());rows[name]=provider.files.identity(target)
        closure=provider.identity_bytes(b'synthetic closure pin')
        provider.engine.put_metadata(assets/provider.GENERATED_HELPER,dict(formatVersion=1,
            scope='android-x64-installation-fixed-inputs',closure=closure))
        rows[provider.GENERATED_HELPER]=provider.files.identity(assets/provider.GENERATED_HELPER)
        provider.engine.put_metadata(assets/'manifest.json',dict(formatVersion=1,files=rows))
        provider.engine.put_metadata(root/provider.PREFIX/'programs.json',dict(closure=closure,
            requiredFiles={'provenance/x64-closure.json':closure}))
        path=root/provider.PREFIX/'restart_probe.py';path.write_bytes(b'synthetic recipe tests/native-java-installation/restart_probe.py')
        return root,dict(currentPackagingRecipe=dict(files=recipe),helpers=rows)

    def test_packaged_helpers_bind_original_source_even_when_descriptor_hashes_are_rewritten(self):
        root,descriptor=self.helpers_fixture();provider.verify_helpers(root,descriptor)
        path=root/'assets/installation-probe-helpers/android_server_installation_setup.py'
        path.write_bytes(b'foreign helper whose metadata was repinned\n')
        descriptor['helpers']['android_server_installation_setup.py']=provider.files.identity(path)
        manifest=root/'assets/installation-probe-helpers/manifest.json';manifest.chmod(0o600)
        manifest.write_bytes(provider.encode(dict(formatVersion=1,files=descriptor['helpers'])))
        with self.assertRaisesRegex(ValueError,'packaged-helper-differs-from-original-source'):
            provider.verify_helpers(root,descriptor)

    def test_generated_authority_manifest_and_observation_script_cannot_drift_from_recipe(self):
        root,descriptor=self.helpers_fixture()
        source=root/'assets/installation-probe/restart_probe.py';source.write_bytes(b'foreign read-only observer')
        with self.assertRaisesRegex(ValueError,'file-changed'):provider.verify_helpers(root,descriptor)
        source.write_bytes(b'synthetic recipe tests/native-java-installation/restart_probe.py')
        authority=root/'assets/installation-probe-helpers'/provider.GENERATED_HELPER;authority.chmod(0o600)
        authority.write_bytes(provider.encode(dict(formatVersion=1,scope='android-x64-installation-fixed-inputs',
            closure=provider.identity_bytes(b'foreign closure'))))
        descriptor['helpers'][provider.GENERATED_HELPER]=provider.files.identity(authority)
        with self.assertRaisesRegex(ValueError,'generated-helper-closure-differs'):provider.verify_helpers(root,descriptor)


if __name__ == '__main__': unittest.main()
