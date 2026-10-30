"""Native environment and acquisition guards; no downloads or compiler execution."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import Mock, patch

from tools import prepare_server_isolated_build as build


class IsolatedEnvironment(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = dict(platform='aarch64',os='ID=ubuntu\nVERSION_ID="24.04"\nVERSION_CODENAME=noble\n',packages='fixture\t1\n',
            compiler_sha256='a'*64,compiler_version='fixture GCC\n',compiler_target='aarch64-linux-gnu\n',
            cmake_version='fixture CMake\n',ccache_version='fixture ccache\n')
        self.inputs = self.root/'inputs';(self.inputs/'environment').mkdir(parents=True)
        raw=json.dumps(self.expected).encode();self.environment=self.inputs/'environment/cache-environment.json'
        self.environment.write_bytes(raw)
        # The app client may advance independently of the retained server build.
        provider=json.loads((build.ROOT/'runtime/server/programs-provider.lock.json').read_text())
        self.original_lock=self.root/'original-sources.lock.json'
        self.original_lock.write_text(provider['serverBuildSourceLockText'])
        self.pin=copy.deepcopy(build.load_pin(self.original_lock))
        self.pin['originalBuildEnvironment']['files']['cache-environment.json']=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
        self.pin['originalBuildEnvironment']['relevantPackages']={'fixture':'1'}

    def verify(self,observed,path=None):
        with patch.object(build,'load_pin',return_value=self.pin):
            return build.verify_environment(self.inputs,path or self.root/'comparison.json',observed)

    def test_exact_relevant_environment_matches_and_retains_full_fingerprints(self):
        result=self.verify(dict(self.expected));self.assertTrue(result['exactEnvironmentMatched'])
        self.assertTrue(result['relevantBuildEnvironmentMatched'])
        self.assertFalse(result['sourceCompanionComplete']);self.assertFalse(result['isolatedSourceRebuildQualified'])

    def test_package_or_compiler_drift_emits_false_typed_receipt_and_refuses(self):
        for field in ('packages','compiler_sha256','cmake_version','os'):
            actual=dict(self.expected)
            actual[field] = ('fixture\t2\n' if field=='packages' else
                             actual[field].replace('ubuntu','debian') if field=='os' else actual[field]+'changed')
            target=self.root/(field+'.json')
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'environment-differs'):
                self.verify(actual,target)
            receipt=json.loads(target.read_bytes())
            self.assertFalse(receipt['exactEnvironmentMatched']);self.assertEqual(receipt['mismatchFields'],[field])
            self.assertFalse(receipt['relevantBuildEnvironmentMatched'])

    def test_unrelated_runner_packages_and_disabled_cache_version_are_evidence_only(self):
        actual=dict(self.expected);actual['packages']+='unrelated-fonts\t2\n';actual['ccache_version']='not installed; disabled'
        result=self.verify(actual)
        self.assertFalse(result['exactEnvironmentMatched']);self.assertTrue(result['relevantBuildEnvironmentMatched'])
        self.assertEqual(result['relevantMismatchFields'],[])

    def test_gcc_resolved_executable_alias_preserves_vendor_version_and_binary_gate(self):
        original='g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0\nCopyright (C) 2023 FSF\n'
        resolved=original.replace('g++ (','aarch64-linux-gnu-g++-13 (',1)
        self.assertEqual(build.compiler_banner_identity(original),build.compiler_banner_identity(resolved))
        self.assertNotEqual(build.compiler_banner_identity(original),build.compiler_banner_identity(resolved.replace('13.3.0','13.4.0')))
        self.assertNotEqual(build.compiler_banner_identity(original),build.compiler_banner_identity(resolved.replace('Ubuntu','Other')))

    def test_original_environment_bytes_and_existing_receipt_are_never_rebound(self):
        self.environment.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'environment-bytes-changed'):self.verify(self.expected)
        self.assertFalse((self.root/'comparison.json').exists())
        self.environment.write_text(json.dumps(self.expected));(self.root/'comparison.json').write_text('preserved')
        with self.assertRaisesRegex(ValueError,'receipt-preserved'):self.verify(self.expected)
        self.assertEqual((self.root/'comparison.json').read_text(),'preserved')

    def test_wrong_native_architecture_stops_before_tool_execution(self):
        with patch.object(build.platform,'machine',return_value='x86_64'),\
             patch.object(build.files,'bounded_command') as run,\
             self.assertRaisesRegex(ValueError,'native-arm64'):
            build.observed_environment()
        run.assert_not_called()

    def test_low_disk_and_existing_output_precede_network(self):
        api=Mock();output=self.root/'new'
        with patch.object(build.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(20,20,0)),\
             self.assertRaisesRegex(ValueError,'16-GiB-free'):
            build.acquire(output,api,original_lock=self.original_lock)
        api.json.assert_not_called();api.download.assert_not_called();self.assertFalse(output.exists())
        output.mkdir();(output/'marker').write_text('preserved')
        with self.assertRaisesRegex(ValueError,'inputs-preserved'):build.acquire(output,api,original_lock=self.original_lock)
        self.assertEqual((output/'marker').read_text(),'preserved')

    def test_remote_artifact_substitution_refused_before_download(self):
        api=Mock();api.json.return_value={'id':0}
        with patch.object(build.shutil,'disk_usage',return_value=shutil._ntuple_diskusage(32*1024**3,0,32*1024**3)),\
             self.assertRaisesRegex(ValueError,'remote-artifact-mismatch'):
            build.acquire(self.root/'new',api,original_lock=self.original_lock)
        api.download.assert_not_called();self.assertFalse((self.root/'new/acquisition.json').exists())

    def test_protocol_pin_reader_rejects_other_client_before_network(self):
        pin=json.loads(build.client.small(build.client.PIN));pin['sourceRevision']='0'*40
        with patch.object(build.client,'small',return_value=json.dumps(pin).encode()),\
             patch.object(build.archives,'fetch') as fetch,\
             self.assertRaisesRegex(ValueError,'client-source-mismatch'):
            build.protocol_inputs(self.root/'protocol')
        fetch.assert_not_called()

    def test_protocol_extraction_uses_actual_build_identity_and_limits_without_pe_execution(self):
        pin=json.loads(build.client.small(build.client.PIN))
        # Self-contained published-artifact fixture: a newer current client may
        # be selected before its dependency release has a published section.
        protocol_root=self.root/'protocol-root';(protocol_root/'runtime/client').mkdir(parents=True)
        (protocol_root/'sources.lock.json').write_bytes((build.ROOT/'sources.lock.json').read_bytes())
        (protocol_root/'runtime/client/dependency-release.lock.json').write_text(json.dumps(dict(
            sourceRevision=pin['sourceRevision'],published=dict(assets={
                'reconstructed-client-arm64-original.zip':dict(pin['artifact'])}))))
        original=self.root/'client.zip';manifest=b'{"fixture":"client build only"}\n';limits=b'{"fixture":"limits only"}\n'
        with zipfile.ZipFile(original,'w') as archive:
            archive.writestr('bin/Win/ARM64/client-build.json',manifest)
            archive.writestr('build/client/generated/limits/limits.json',limits)
        pin['buildManifestSha256']=hashlib.sha256(manifest).hexdigest()
        with patch.object(build,'ROOT',protocol_root),\
             patch.object(build.client,'small',return_value=json.dumps(pin).encode()),\
             patch.object(build.archives,'fetch',return_value=original),\
             patch.object(build.client,'checked_zip',side_effect=lambda source:zipfile.ZipFile(source)):
            receipt=build.protocol_inputs(self.root/'protocol')
        self.assertEqual((self.root/'protocol/limits.json').read_bytes(),limits)
        self.assertFalse(receipt['clientExecuted'])


if __name__=='__main__':unittest.main()
