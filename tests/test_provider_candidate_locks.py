"""Separate measured-input selection; synthetic fixtures never qualify execution."""
import copy
import json
from unittest.mock import patch
import unittest
import zipfile

from tools import provider_guest_bridges as bridges, provider_shader_tools as shaders, provider_turnip as turnip
from tests import test_guest_bridge_provider as bridge_fixtures
from tests import test_shader_provider as shader_fixtures
from tests import test_turnip_provider as turnip_fixtures


class CandidateProviderLocks(unittest.TestCase):
    def fixture(self, kind):
        fixture = kind('test_deterministic_archive_full_readback_and_no_replace' if kind is shader_fixtures.ShaderProvider
                       else 'test_deterministic_build_and_full_required_inventory' if kind is bridge_fixtures.GuestBridgeProvider
                       else 'test_deterministic_readback_companion_and_existing_destination_preserved')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        return fixture

    def test_shader_descriptor_binds_supplied_lock_and_default_cannot_verify_it(self):
        fixture = self.fixture(shader_fixtures.ShaderProvider)
        selected = fixture.root/'selected.json'; selected.write_text(json.dumps(json.loads(fixture.lock.read_bytes())))
        proof = shaders.build(fixture.bundle,fixture.output,selected)
        self.assertEqual(proof['inputLockSha256'],shaders.bundle.identity(selected)['sha256'])
        self.assertNotEqual(proof['inputLockSha256'],shaders.bundle.identity(fixture.lock)['sha256'])
        self.assertTrue(shaders.verify(fixture.output,input_lock=selected)['providerVerified'])
        with self.assertRaisesRegex(ValueError,'metadata-mismatch'):shaders.verify(fixture.output)
        selected.write_bytes(b'{}')
        with self.assertRaises(ValueError):shaders.verify(fixture.output,input_lock=selected)

    def test_turnip_companion_and_descriptor_use_same_explicit_measured_input(self):
        fixture = self.fixture(turnip_fixtures.TurnipProvider)
        pin = dict(fixture.pin,formatVersion=1,scope='measured-turnip-kgsl-provider-inputs',nativeNoGpuQualified=True,
                   **{name:False for name in turnip.FALSE_FLAGS})
        selected = fixture.root/'selected.json'; selected.write_bytes(turnip.encoded(pin))
        with patch.object(turnip,'validate_metadata'):
            proof = turnip.build(fixture.artifact,fixture.output,selected)
            self.assertEqual(proof['inputLockSha256'],turnip.files.identity(selected)['sha256'])
            self.assertTrue(turnip.verify(fixture.output,input_lock=selected)['sourceCompanionVerified'])
            with self.assertRaises((KeyError,ValueError)):turnip.verify(fixture.output)
        self.assertEqual((fixture.output/'sources'/turnip.SOURCE).read_bytes(),fixture.artifact.read_bytes())

    def test_bridge_new_source_binding_requires_exact_retained_override_and_new_provider_lock(self):
        fixture = self.fixture(bridge_fixtures.GuestBridgeProvider)
        original_raw = fixture.payload[bridges.SOURCE_LOCK]
        original_path = fixture.root/'runtime/bridges/sources.lock.json';original_path.parent.mkdir(parents=True)
        original_path.write_bytes(original_raw)
        value = json.loads(original_raw);value['runtimeArchiveSha256']='c'*64
        actual = bridges.encoded(value);selected_source = fixture.root/'selected-source.json';selected_source.write_bytes(actual)
        fixture.payload[bridges.SOURCE_LOCK] = actual
        receipt = json.loads(fixture.payload[bridges.RECEIPT]);receipt['runtimeArchiveSha256']='c'*64
        receipt['inputLockSha256']=bridges.identity(actual)['sha256'];fixture.payload[bridges.RECEIPT]=bridges.encoded(receipt)
        candidate = copy.deepcopy(fixture.pin)
        for name in (bridges.SOURCE_LOCK,bridges.RECEIPT):candidate['files'][name].update(bridges.identity(fixture.payload[name]))
        candidate['repositoryInputs']['runtime/bridges/sources.lock.json']=dict(installedPath=bridges.SOURCE_LOCK,**bridges.identity(actual))
        with zipfile.ZipFile(fixture.artifact,'w') as archive:
            for name,data in fixture.payload.items():archive.writestr('export/'+name,data)
        candidate['artifact'].update(bridges.identity(fixture.artifact.read_bytes()))
        selected = fixture.root/'selected.json';selected.write_bytes(bridges.encoded(candidate))
        with self.assertRaisesRegex(ValueError,'source-input-changed'):bridges.load_pin(selected)
        proof = bridges.build(fixture.artifact,fixture.output,input_lock=selected,bridge_input_lock=selected_source)
        self.assertEqual(proof['requiredWineArchiveSha256'],'c'*64)
        self.assertEqual(proof['inputLockSha256'],bridges.identity(selected.read_bytes())['sha256'])
        self.assertTrue(bridges.verify(fixture.output,input_lock=selected,bridge_input_lock=selected_source)['providerVerified'])
        self.assertEqual(original_path.read_bytes(),original_raw)
        with self.assertRaisesRegex(ValueError,'metadata-mismatch|file-identity'):
            bridges.verify(fixture.output)
        selected_source.write_bytes(original_raw)
        with self.assertRaisesRegex(ValueError,'source-input-changed'):
            bridges.verify(fixture.output,input_lock=selected,bridge_input_lock=selected_source)


if __name__ == '__main__':unittest.main()
