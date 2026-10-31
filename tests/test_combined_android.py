import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import package_combined_android as bundle


class CombinedPackageGuards(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_only_the_pinned_adapted_wine_profile_passes_explicit_client_runtime_selection(self):
        path=self.root/'runtime/runtime-sources.lock.json';path.parent.mkdir()
        def write(environment,include=True):
            selected={'wineEnvironment':environment} if include else {}
            path.write_text(json.dumps({'packages':{'wine-arm64':selected}}))
        with patch.object(bundle,'ROOT',self.root):
            write(None,include=False);self.assertEqual(bundle.selected_client_runtime_options(),{})
            write({});self.assertEqual(bundle.selected_client_runtime_options(),{})
            write({'WINE_ANDROID_PRIVATE_PE_COPY':'1'})
            self.assertEqual(bundle.selected_client_runtime_options(),{'runtime_lock':path})
            for invalid in (None,True,{'WINE_ANDROID_PRIVATE_PE_COPY':1},{'WINE_ANDROID_PRIVATE_PE_COPY':'0'},
                    {'WINE_ANDROID_PRIVATE_PE_COPY':'1','UNSELECTED':'1'}):
                write(invalid)
                with self.assertRaisesRegex(ValueError,'unsupported-wine-environment'):
                    bundle.selected_client_runtime_options()

    def test_existing_output_preserves_everything_before_validation(self):
        output = self.root / 'existing'; output.mkdir(); marker = output / 'save'; marker.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'existing-artifacts-preserved'):
            bundle.seal(SimpleNamespace(output=output))
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_final_apk_requires_exact_arm64_native_set(self):
        path = self.root / 'test-only-not-an-apk.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in bundle.NATIVE_FILES | {'lib/x86_64/debug-test.so'}: archive.writestr(name, b'unexecuted fixture')
        with self.assertRaisesRegex(ValueError, 'native-inventory'):
            bundle.apk_inventory(path, {})

    def helper_fixture(self, changed_service=False, changed_manifest=False, manifest_version=1):
        # Source-byte packaging fixtures only; these Python snippets are never executed.
        repository = self.root / 'helper-repository'; (repository / 'runtime').mkdir(parents=True)
        for directory, names in bundle.HELPER_SETS.items():
            for name in names:
                source = repository / bundle.helper_source_path(directory, name); source.parent.mkdir(parents=True, exist_ok=True)
                source.write_bytes(('fixture source: ' + name + '\n').encode())
        path = self.root / 'helpers.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for directory, names in bundle.HELPER_SETS.items():
                records = {}
                for name in names:
                    source = repository / bundle.helper_source_path(directory, name)
                    records[name] = bundle.identity(source)
                    data = source.read_bytes()
                    if changed_service and directory == 'database-service' and name == 'mysql_service.py':
                        data = b'X' * len(data)
                    archive.writestr('assets/' + directory + '/' + name, data)
                if changed_manifest and directory == 'database-service':
                    records['mysql_service.py']['sha256'] = '0' * 64
                archive.writestr('assets/' + directory + '/manifest.json', json.dumps(dict(formatVersion=manifest_version, files=records)))
        return repository, path

    def test_setup_and_service_helpers_are_both_exact_source_bound(self):
        self.assertEqual(bundle.HELPER_SETS, {'stock-client': ('stock_content_inspection.py', 'stock_shader_generation.py', 'shader_generation.py',
                'extractor_order.py', 'server_data_preflight.py'),
            'database-setup': ('mysql_bootstrap.py', 'android_database_setup.py'),
                                            'database-service': ('mysql_bootstrap.py', 'mysql_service.py'),
                                            'server-schema': ('android_server_schema_setup.py', 'mysql_bootstrap.py', 'mysql_service.py',
                                                              'server_content.py', 'server_schema_setup.py', 'server_schema_baseline.py',
                                                              'server_schema_adaptations.py', 'server/appearance-schema-v1.sql',
                                                              'server/appearance-schema.lock.json'),
            'server-installation': ('android_server_installation_setup.py', 'android_server_schema_setup.py', 'mysql_bootstrap.py',
                'mysql_service.py', 'server_content.py', 'server_schema_setup.py', 'server_schema_baseline.py', 'server_schema_adaptations.py',
                'server_update_setup.py', 'server_updater.py', 'server_playerbots_setup.py', 'owned_process_group.py', 'server_config.py', 'provision_local_realm.py',
                'provision_local_account.py', 'server/appearance-schema-v1.sql', 'server/appearance-schema.lock.json', 'local-server.json'),
            'server-data': ('server_data_generation.py', 'server_data_preflight.py', 'shader_generation.py',
                'extractor_order.py', 'owned_process_group.py'),
            'server-session': ('server_session.py', 'server_session_process.py', 'android_server_schema_setup.py',
                'mysql_bootstrap.py', 'mysql_service.py', 'server_content.py', 'server_schema_setup.py',
                'server_schema_baseline.py', 'server_schema_adaptations.py', 'server_update_setup.py', 'server_updater.py',
                'server_playerbots_setup.py', 'owned_process_group.py', 'server_config.py', 'provision_local_realm.py',
                'provision_local_account.py', 'server_data_generation.py', 'server_data_preflight.py', 'shader_generation.py',
                'extractor_order.py', 'server/appearance-schema-v1.sql', 'server/appearance-schema.lock.json', 'local-server.json')})
        repository, path = self.helper_fixture()
        with patch.object(bundle, 'ROOT', repository), zipfile.ZipFile(path) as archive:
            bundle.verify_helpers(archive)

    def test_session_exact23_source_closure_and_nested_manifest_tamper_refused(self):
        repository, path = self.helper_fixture()
        self.assertEqual(len(bundle.HELPER_SETS['server-session']), 23)
        with zipfile.ZipFile(path) as archive:
            original = {name:archive.read(name) for name in archive.namelist()}
        prefix = 'assets/server-session/'
        for mutation, reason in [('extra','helper-inventory'),('missing','helper-inventory'),
                                 ('nested','helper-source'),('profile','helper-source'),('manifest','helper-manifest')]:
            changed = dict(original)
            if mutation == 'extra': changed[prefix+'unexpected.py']=b'unapproved'
            if mutation == 'missing': del changed[prefix+'server_session_process.py']
            if mutation in ('nested','profile'):
                name=prefix+('server/appearance-schema-v1.sql' if mutation=='nested' else 'local-server.json')
                changed[name]=b'X'*len(changed[name])
            if mutation=='manifest':
                name=prefix+'manifest.json'; changed[name]=changed[name].replace(b'{',b'{"formatVersion":1,',1)
            output=self.root/('session-'+mutation+'.zip')
            with zipfile.ZipFile(output,'w') as archive:
                for name,raw in changed.items():archive.writestr(name,raw)
            with patch.object(bundle,'ROOT',repository),zipfile.ZipFile(output) as archive:
                with self.assertRaisesRegex(ValueError,reason):bundle.verify_helpers(archive)

    def test_same_size_modified_database_service_helper_is_rejected(self):
        repository, path = self.helper_fixture(changed_service=True)
        with patch.object(bundle, 'ROOT', repository), zipfile.ZipFile(path) as archive:
            with self.assertRaisesRegex(ValueError, 'helper-source-mismatch'):
                bundle.verify_helpers(archive)

    def test_service_manifest_cannot_claim_different_helper_bytes(self):
        repository, path = self.helper_fixture(changed_manifest=True)
        with patch.object(bundle, 'ROOT', repository), zipfile.ZipFile(path) as archive:
            with self.assertRaisesRegex(ValueError, 'helper-manifest-mismatch'):
                bundle.verify_helpers(archive)

    def test_helper_manifest_boolean_format_is_not_integer_one(self):
        repository, path = self.helper_fixture(manifest_version=True)
        with patch.object(bundle, 'ROOT', repository), zipfile.ZipFile(path) as archive:
            with self.assertRaisesRegex(ValueError, 'helper-manifest-mismatch'):
                bundle.verify_helpers(archive)

    def test_installation_helper_manifest_inventory_and_profile_are_strict(self):
        repository, path = self.helper_fixture()
        self.assertEqual(len(bundle.HELPER_SETS['server-installation']), 18)
        self.assertTrue((repository / 'config/local-server.json').is_file())
        with zipfile.ZipFile(path) as archive:
            original = {name: archive.read(name) for name in archive.namelist()}
        for change, reason in [('extra', 'helper-inventory'), ('missing', 'helper-inventory'),
                               ('changed', 'helper-source'), ('profile', 'helper-source'), ('duplicate_json', 'helper-manifest')]:
            contents = dict(original); prefix = 'assets/server-installation/'
            if change == 'extra': contents[prefix + 'server/unapproved.py'] = b'unapproved'
            if change == 'missing': del contents[prefix + 'server/appearance-schema.lock.json']
            if change in ('changed', 'profile'):
                name = prefix + ('local-server.json' if change == 'profile' else 'server/appearance-schema-v1.sql')
                contents[name] = b'X' * len(contents[name])
            if change == 'duplicate_json':
                name = prefix + 'manifest.json'; contents[name] = contents[name].replace(b'{', b'{"formatVersion":1,', 1)
            modified = self.root / ('installation-' + change + '.zip')
            with zipfile.ZipFile(modified, 'w') as archive:
                for name, raw in contents.items(): archive.writestr(name, raw)
            with self.subTest(change=change), patch.object(bundle, 'ROOT', repository), zipfile.ZipFile(modified) as archive:
                with self.assertRaisesRegex(ValueError, reason): bundle.verify_helpers(archive)

    def test_unknown_assets_still_fail_the_exact_inventory_gate(self):
        path = self.root / 'foreign-assets.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name in bundle.NATIVE_FILES:
                archive.writestr(name, b'unexecuted header-free fixture')
            archive.writestr('assets/database-service/unapproved.py', b'unapproved private fixture')
        with self.assertRaisesRegex(ValueError, 'combined-apk-asset-inventory-mismatch'):
            bundle.apk_inventory(path, {})

    def test_complete_asset_inventory_binds_x11_lock_and_rejects_missing_or_changed_bytes(self):
        # ZIP inventory/source-byte fixture only; the separate provider/ELF
        # verifiers handle executable content before any actual publication.
        payload = {name: b'unexecuted fixture' for name in bundle.NATIVE_FILES}
        for prefix, names in [('assets/proot/', bundle.proot.NOTICES | {'build-evidence.json'}),
                              ('assets/' + bundle.server.ASSET_DIR + '/', bundle.server.NAMES),
                              ('assets/' + bundle.guest.ASSET_DIR + '/', bundle.guest.NAMES),
                              (bundle.client.ASSETS + '/', {bundle.client.ARCHIVE, 'provider.json', 'NOTICE.txt'})]:
            payload.update({prefix + name: b'provider fixture' for name in names})
        for directory, names in bundle.HELPER_SETS.items():
            records = {}
            for name in names:
                source = bundle.ROOT / bundle.helper_source_path(directory, name)
                payload['assets/' + directory + '/' + name] = source.read_bytes()
                records[name] = bundle.identity(source)
            payload['assets/' + directory + '/manifest.json'] = json.dumps(dict(formatVersion=1, files=records)).encode()
        for name, source in [('sources.lock.json', 'sources.lock.json'),
                             ('runtime-sources.lock.json', 'runtime/runtime-sources.lock.json'),
                             ('x11-runtime.lock.json', 'runtime/bridges/x11-runtime.lock.json'),
                             ('runtime.properties', 'app/src/main/assets/runtime.properties')]:
            payload['assets/' + name] = (bundle.ROOT / source).read_bytes()
        notices = {}
        for name in bundle.NDK_NOTICES:
            data = b'fixed test toolchain notice'; payload['assets/notices/' + name] = data
            notices[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        for name in ('ESTERIA-GPL-3.0.txt', 'FTA-MIT-LICENSE.txt'):
            payload['assets/notices/' + name] = b'fixture notice'
        for mutation, reason in [('none', None), ('missing', 'asset-inventory'),
                                 ('changed', 'embedded-source-lock'), ('extra', 'asset-inventory'),
                                 ('schema_missing', 'asset-inventory'), ('schema_changed', 'helper-source-mismatch'),
                                 ('schema_extra', 'asset-inventory'), ('installation_missing', 'asset-inventory'),
                                 ('installation_changed', 'helper-source-mismatch'), ('installation_extra', 'asset-inventory'),
                                 ('installation_profile', 'helper-source-mismatch'), ('installation_manifest', 'helper-manifest-mismatch')]:
            contents = dict(payload)
            if mutation == 'missing': del contents['assets/x11-runtime.lock.json']
            if mutation == 'changed': contents['assets/x11-runtime.lock.json'] = b'X' * len(contents['assets/x11-runtime.lock.json'])
            if mutation == 'extra': contents['assets/foreign-private-file'] = b'never permitted'
            if mutation == 'schema_missing': del contents['assets/server-schema/server/appearance-schema-v1.sql']
            if mutation == 'schema_changed':
                name = 'assets/server-schema/server/appearance-schema-v1.sql'; contents[name] = b'X' * len(contents[name])
            if mutation == 'schema_extra': contents['assets/server-schema/server/unapproved.py'] = b'never permitted'
            if mutation == 'installation_missing': del contents['assets/server-installation/server/appearance-schema.lock.json']
            if mutation == 'installation_changed':
                name = 'assets/server-installation/server/appearance-schema-v1.sql'; contents[name] = b'X' * len(contents[name])
            if mutation == 'installation_extra': contents['assets/server-installation/unapproved.py'] = b'never permitted'
            if mutation == 'installation_profile':
                name = 'assets/server-installation/local-server.json'; contents[name] = b'X' * len(contents[name])
            if mutation == 'installation_manifest':
                name = 'assets/server-installation/manifest.json'; proof = json.loads(contents[name]); proof['files'].pop('owned_process_group.py')
                contents[name] = json.dumps(proof).encode()
            path = self.root / (mutation + '.zip')
            with zipfile.ZipFile(path, 'w') as archive:
                for name, data in contents.items(): archive.writestr(name, data)
            with self.subTest(mutation=mutation):
                if reason:
                    with self.assertRaisesRegex(ValueError, reason): bundle.apk_inventory(path, notices)
                else:
                    self.assertEqual(bundle.apk_inventory(path, notices), sorted(bundle.NATIVE_FILES))

    def test_verified_copy_never_replaces_existing_output_or_accepts_wrong_bytes(self):
        source = self.root / 'source'; source.write_bytes(b'actual original')
        target = self.root / 'target'; target.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError): bundle.copy_verified(source, target, bundle.identity(source))
        self.assertEqual(target.read_bytes(), b'preserve')
        wrong = dict(bytes=source.stat().st_size, sha256='0' * 64)
        with self.assertRaisesRegex(ValueError, 'hash-changed'):
            bundle.copy_verified(source, self.root / 'partial', wrong)

    def fixture(self, extra=None, missing_object=False, wrong_object=False, changed_recipe=False, pax=None):
        # Synthetic ELF header only, never executable or build qualification.
        repo = self.root / 'repository'; repo.mkdir()
        component = b'original fixture source'
        pin = dict(components={'source.tar.gz': hashlib.sha256(component).hexdigest()})
        paths = ['tools/build_android_proot.py', 'tools/android_elf.py', 'tools/prepare_runtime.py', 'LICENSE',
                 'runtime/proot/sources.lock.json', 'runtime/proot/README.md']
        for name in paths:
            destination = repo / name; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((json.dumps(pin) if name.endswith('.json') else 'fixture recipe ' + name).encode())
        provider = self.root / 'provider'; (provider / 'assets/proot').mkdir(parents=True)
        (provider / 'assets/proot/build-evidence.json').write_bytes(b'{}\n')
        payload = {'original/source.tar.gz': component, 'build-evidence.json': b'{}\n'}
        payload.update({'esteria/' + name: (repo / name).read_bytes() for name in paths})
        if changed_recipe: payload['esteria/LICENSE'] = b'changed'
        if not missing_object:
            header = bytearray(20); header[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<HH', header, 16, 1, 62 if wrong_object else 183)
            payload['talloc-build-objects/talloc.c.5.o'] = bytes(header)
        if extra: payload[extra] = b'private fixture data'
        archive_path = self.root / 'sources.tar.gz'
        with tarfile.open(archive_path, 'w:gz') as archive:
            for name, data in payload.items():
                item = tarfile.TarInfo(name); item.size = len(data)
                if pax is not None: item.pax_headers = pax
                archive.addfile(item, io.BytesIO(data))
        return repo, provider, archive_path

    def audit(self, **kwargs):
        repo, provider, archive_path = self.fixture(**kwargs)
        with (patch.object(bundle, 'ROOT', repo), patch.object(bundle.proot_build, 'LOCK', repo / 'runtime/proot/sources.lock.json'),
              patch.object(bundle.subprocess, 'check_output', return_value='runtime/proot/sources.lock.json\nruntime/proot/README.md\n')):
            return bundle.proot_sources(archive_path, provider)

    def test_originals_recipes_and_relinkable_arm64_objects_are_all_read_back(self):
        proof = self.audit(pax={'mtime': '1780058300.123456'})
        self.assertEqual(proof['relinkableArm64Objects'], 1)
        self.assertIn('original/source.tar.gz', proof['files'])
        self.assertIn('esteria/LICENSE', proof['files'])

    def test_private_extra_is_rejected_even_if_builder_directory_contained_it(self):
        with self.assertRaisesRegex(ValueError, 'unexpected-proot-source-file'):
            self.audit(extra='esteria/runtime/proot/private-signing-key')

    def test_oversized_pax_is_rejected_before_metadata_allocation(self):
        with self.assertRaisesRegex(ValueError, 'pax-size-limit'):
            self.audit(pax={'comment': 'x' * 20000})

    def test_same_size_modified_toolchain_notice_is_rejected(self):
        path = self.root / 'notices.zip'; expected = {}
        with zipfile.ZipFile(path, 'w') as archive:
            for name in bundle.NDK_NOTICES:
                original = b'exact original notice'
                expected[name] = dict(bytes=len(original), sha256=hashlib.sha256(original).hexdigest())
                archive.writestr('assets/notices/' + name, b'X' * len(original))
        with zipfile.ZipFile(path) as archive, self.assertRaisesRegex(ValueError, 'notice-hash-mismatch'):
            bundle.verify_ndk_notices(archive, expected)

    def test_missing_relinkable_object_wrong_machine_and_modified_recipe_fail(self):
        for options in (dict(missing_object=True), dict(wrong_object=True), dict(changed_recipe=True)):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                previous = self.root; self.root = Path(temporary)
                try:
                    with self.assertRaises(ValueError): self.audit(**options)
                finally: self.root = previous


if __name__ == '__main__': unittest.main()
