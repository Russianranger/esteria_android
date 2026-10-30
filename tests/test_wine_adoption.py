import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import prepare_wine_arm64_adoption as adoption
from tools import wine_arm64_requalification as retained
from tools import package_wine_arm64_candidate as package
import tests.test_wine_arm64_candidate as fixtures
from tests import historical_wine_inputs as historical


class WineAdoptionInputs(unittest.TestCase):
    def fixture(self):
        pin, client = retained.pins()
        fixture = fixtures.Arm64Candidate('test_existing_outputs_are_never_overwritten')
        fixture.setUp(); self.addCleanup(fixture.doCleanups); fixture.prepare()
        package.build(fixture.export, fixture.measured, fixture.output)
        pin['files'] = {p.name: retained.client.identity(p) for p in fixture.output.iterdir()}
        proof, candidate = retained.runtime_package(fixture.output, pin)
        return fixture, pin, client, proof, candidate

    def test_android_plan_uses_measured_limits_without_duplicate_metadata_or_historical_notices(self):
        fixture, pin, _, proof, candidate = self.fixture()
        previous = historical.value('runtime/runtime-sources.lock.json')
        original = copy.deepcopy(candidate)
        value = adoption.proposal(candidate, proof, pin, previous, adoption.release_tag(pin))
        selected = value['packages']['wine-arm64']; profile = value['androidInstallation']
        self.assertEqual(candidate, original)
        self.assertEqual(set(profile['requiredMetadata']), {package.MARKER, 'usr/lib/os-release'})
        self.assertFalse(selected['components'].keys() & profile['requiredMetadata'].keys())
        self.assertNotIn('etc/memento-client-packages.txt', profile['requiredMetadata'])
        self.assertEqual(selected['archive']['sha256'], proof['archive']['sha256'])
        self.assertEqual(selected['sourceCompanion']['sha256'], pin['sourcesArtifact']['sha256'])
        self.assertEqual(selected['wineEnvironment'], {'WINE_ANDROID_PRIVATE_PE_COPY': '1'})
        self.assertEqual(selected['limits'], {k: proof['installLimits'][k]
                         for k in ('entries', 'memberBytes', 'fileBytes', 'pathBytes')})
        self.assertLessEqual(len(adoption.encoded(value)), 128*1024)
        self.assertEqual(value['androidBridge'], previous['androidBridge'])
        self.assertEqual(value['server'], previous['server'])

    def test_relabelled_archive_profile_and_changed_production_base_are_rejected(self):
        _, pin, _, proof, candidate = self.fixture()
        previous = historical.value('runtime/runtime-sources.lock.json')
        for key in ('archive', 'wineEnvironment'):
            bad = copy.deepcopy(candidate)
            bad['packages']['wine-arm64'][key] = {}
            with self.subTest(key=key), self.assertRaises(ValueError):
                adoption.proposal(bad, proof, pin, previous, adoption.release_tag(pin))
        previous['packages']['wine-arm64']['archive']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'base-changed'):
            adoption.proposal(candidate, proof, pin, previous, adoption.release_tag(pin))
        with self.assertRaisesRegex(ValueError, 'release-tag'):
            adoption.proposal(candidate, proof, pin, previous, '../old-release')

    def test_preparation_preserves_all_current_pins_and_copies_only_new_build_inputs(self):
        fixture, pin, client, _, _ = self.fixture()
        before = {name: retained.client.identity(adoption.ROOT/name) for name in adoption.BOUND_INPUTS}
        output = fixture.root/'adoption'
        legacy=historical.materialize(fixture.root/'legacy-production',adoption.BOUND_INPUTS)
        with patch.object(retained, 'pins', return_value=(pin, client)), \
                patch.object(adoption,'ROOT',legacy),patch.object(adoption,'RUNTIME_LOCK',legacy/'runtime/runtime-sources.lock.json'):
            report = adoption.prepare(fixture.output, output)
        self.assertEqual(before, {name: retained.client.identity(adoption.ROOT/name) for name in adoption.BOUND_INPUTS})
        self.assertEqual(set(p.name for p in output.iterdir()),
                         {'runtime-sources.proposed.lock.json', 'adoption-preparation.json',
                          'bridge-build-context', 'turnip-build-context'})
        for key in ('productionPinsChanged', 'providersRelabelled', 'readyForProductionSelection',
                    'runtimeRecompiled', 'runtimeExpandedLocally', 'androidQualified', 'gameplayQualified'):
            self.assertIs(report[key], False)
        self.assertNotEqual(report['originalNativeClientRevision'], report['selectedClientRevision'])
        archive = report['proposedRuntimeArchiveSha256']
        for kind, path in (('bridge', 'runtime/bridges'), ('turnip', 'runtime/turnip')):
            source = json.loads((legacy/path/'sources.lock.json').read_bytes())
            rebuilt = json.loads((output/(kind+'-build-context')/'sources.lock.json').read_bytes())
            source['runtimeArchiveSha256'] = archive
            self.assertEqual(rebuilt, source)
            self.assertTrue(report['buildContexts'][kind]['rebuildRequired'])
            self.assertFalse(report['buildContexts'][kind]['actualBinaryOrProviderQualified'])

    def test_existing_output_is_preserved_before_reading_runtime_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'saved'; output.mkdir(); (output/'save').write_bytes(b'keep')
            with patch.object(retained, 'pins') as pins, self.assertRaisesRegex(ValueError, 'output-exists'):
                adoption.prepare(Path('/not-selected'), output)
            pins.assert_not_called(); self.assertEqual((output/'save').read_bytes(), b'keep')

    def test_actual_selected_host_evidence_requires_all_nine_component_gates_and_exact_pair(self):
        pin, client = retained.pins()
        path = adoption.ROOT/'runtime/evidence/wine-arm64-selected471-41069065089.json'
        proof = adoption.selected_host_evidence(path, pin, client)
        self.assertTrue(proof['allNineNativeComponentGatesPassed'])
        with tempfile.TemporaryDirectory() as temporary:
            value = json.loads(path.read_bytes()); changed = Path(temporary)/'host.json'
            value['qualification']['worker']['wineWaitExit'] = 1
            changed.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'host-gates'):
                adoption.selected_host_evidence(changed, pin, client)
            changed_client = copy.deepcopy(client); changed_client['sourceRevision'] = '0'*40
            with self.assertRaisesRegex(ValueError, 'host-evidence'):
                adoption.selected_host_evidence(path, pin, changed_client)

    def test_context_requires_original_runtime_binding_before_writing_new_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root/'source'; source.mkdir()
            (source/'sources.lock.json').write_text(json.dumps({'runtimeArchiveSha256': 'wrong'}))
            with self.assertRaisesRegex(ValueError, 'binding-changed'):
                adoption.rebound_context(source, root/'out', 'new', 'old')
            self.assertEqual(json.loads((source/'sources.lock.json').read_bytes())['runtimeArchiveSha256'], 'wrong')


if __name__ == '__main__': unittest.main()
