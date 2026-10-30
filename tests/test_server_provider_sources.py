"""Current client changes never relabel archived server receipts or payloads."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import provider_server_programs as programs, provider_server_content as content
from tools import provider_server_extractors as extractors, server_provider_sources as sources

ROOT = programs.ROOT
PROVIDERS = (programs, content, extractors)


class ServerSourceBinding(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='server-source-binding-')
        self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)
        self.original = (ROOT / 'sources.lock.json').read_bytes()
        self.current = json.loads(self.original)
        self.current['sources']['client']['commit'] = '1'*40
        deps = self.root / 'runtime/server/android-provider.lock.json'
        deps.parent.mkdir(parents=True); deps.write_bytes((ROOT / 'runtime/server/android-provider.lock.json').read_bytes())

    def selected(self, provider, mutate=None):
        pin = json.loads(provider.LOCK.read_bytes())
        current = copy.deepcopy(self.current)
        if mutate: mutate(current)
        current_path = self.root / 'sources.lock.json'
        current_path.write_bytes(programs.encoded(current))
        pin['appSourceLock'] = programs.files.identity(current_path)
        path = self.root / (provider.__name__.split('_')[-1] + '-pin.json')
        path.write_bytes(programs.encoded(pin))
        return pin, path

    def test_reviewed_client_only_current_app_change_accepts_all_three_unchanged_server_payloads(self):
        for provider in PROVIDERS:
            pin, path = self.selected(provider)
            with self.subTest(provider=provider.__name__), patch.object(provider, 'ROOT', self.root), patch.object(provider, 'LOCK', path):
                actual = provider.load_pin()
                self.assertNotEqual(actual['appSourceLock'], actual['serverBuildSourceLock'])
                self.assertEqual(actual['serverBuildSourceLock'], programs.files.identity(ROOT / 'sources.lock.json'))
                sources.validate_archived(self.original, actual)
                fields = sources.descriptor_fields(actual)
                self.assertEqual(fields['appSourceLockSha256'], pin['appSourceLock']['sha256'])
                self.assertEqual(fields['serverBuildSourceLockSha256'], actual['serverBuildSourceLock']['sha256'])

    def test_client_change_without_reviewed_current_app_pin_is_refused(self):
        for provider in PROVIDERS:
            pin, path = self.selected(provider)
            pin['appSourceLock'] = programs.files.identity(ROOT / 'sources.lock.json'); path.write_bytes(programs.encoded(pin))
            with self.subTest(provider=provider.__name__), patch.object(provider, 'ROOT', self.root), patch.object(provider, 'LOCK', path):
                with self.assertRaisesRegex(ValueError, 'current-app-source-lock'): provider.load_pin()

    def test_boolean_schema_is_not_an_integer_source_lock_version(self):
        for provider in PROVIDERS:
            _,path=self.selected(provider,lambda d:d.update(schema=True))
            with self.subTest(provider=provider.__name__),patch.object(provider,'ROOT',self.root),patch.object(provider,'LOCK',path):
                with self.assertRaisesRegex(ValueError,'source-lock-schema'):provider.load_pin()

    def test_server_commit_patch_order_hash_and_submodule_drift_are_refused(self):
        mutations = [lambda d:d['sources']['server'].update(commit='2'*40),
            lambda d:d['sources']['server']['patches'].reverse(),
            lambda d:d['sources']['server']['patches'][0].update(sha256='3'*64),
            lambda d:d['sources']['server']['submodules'].update({'src/server/game/LuaEngine':'4'*40})]
        for provider in PROVIDERS:
            for i, mutate in enumerate(mutations):
                _, path = self.selected(provider,mutate)
                with self.subTest(provider=provider.__name__,mutation=i), patch.object(provider,'ROOT',self.root), patch.object(provider,'LOCK',path):
                    with self.assertRaisesRegex(ValueError,'current-source-selection'): provider.load_pin()

    def test_protocol_profile_values_types_extra_and_missing_fields_are_refused(self):
        mutations = [lambda d:d['compatibility'].update(container_slots=255),
            lambda d:d['compatibility'].update(base_client_build=12341),
            lambda d:d['compatibility'].update(extended_limits=1),
            lambda d:d['compatibility'].update(client_class_capacity=32.0),
            lambda d:d['compatibility'].update(unapproved_protocol=True),
            lambda d:d['compatibility'].pop('quest_log_slots')]
        for provider in PROVIDERS:
            for i, mutate in enumerate(mutations):
                _,path=self.selected(provider,mutate)
                with self.subTest(provider=provider.__name__,mutation=i), patch.object(provider,'ROOT',self.root), patch.object(provider,'LOCK',path):
                    with self.assertRaisesRegex(ValueError,'compatibility-profile'): provider.load_pin()

    def test_original_archived_receipt_lock_cannot_be_rewritten_to_current_app_lock(self):
        pin,_=self.selected(programs)
        with self.assertRaisesRegex(ValueError,'archived-build-source-lock'):
            sources.validate_archived(programs.encoded(self.current),pin)
        sources.validate_archived(self.original,pin)

    def test_current_and_declared_profile_cannot_relabel_unchanged_archived_build(self):
        for provider in PROVIDERS:
            pin,path=self.selected(provider,lambda d:d['compatibility'].update(container_slots=255))
            pin['serverBuildCompatibility']['container_slots']=255;path.write_bytes(programs.encoded(pin))
            with self.subTest(provider=provider.__name__),patch.object(provider,'ROOT',self.root),patch.object(provider,'LOCK',path):
                with self.assertRaisesRegex(ValueError,'archived-build-profile'):provider.load_pin()

    def test_descriptor_current_app_changes_leave_stable_component_source_pin(self):
        for provider in PROVIDERS:
            pin,path=self.selected(provider)
            fields=sources.descriptor_fields(pin)
            self.assertNotEqual(fields['appSourceLockSha256'],fields['serverBuildSourceLockSha256'])
            current_changed=copy.deepcopy(pin);current_changed['appSourceLock']['sha256']='5'*64
            changed=sources.descriptor_fields(current_changed)
            self.assertEqual(fields['serverBuildSourceLockSha256'],changed['serverBuildSourceLockSha256'])
            self.assertEqual(fields['serverSource'],changed['serverSource'])
            self.assertEqual(fields['serverBuildCompatibility'],changed['serverBuildCompatibility'])


if __name__=='__main__':unittest.main()
