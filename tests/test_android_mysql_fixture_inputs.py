"""Actual ZIP/source transactions for the isolated retained x64 SQL fixture."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from tools import fetch_android_mysql_fixture as fixture


class AndroidMysqlFixtureInputs(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.output = self.root / 'output'; self.output.mkdir()
        self.revision = 'a' * 40
        self.payload = {name: ('fixture-only: ' + name).encode() for name in
            ['SOURCE-MANIFEST.json', 'probe.apk', 'tests.apk'] + [
                'provider/assets/mysql-probe/' + name for name in sorted(fixture.retained.builder.NAMES)]}
        identities = {name: fixture.bytes_identity(raw) for name, raw in self.payload.items()}
        self.receipt = dict(formatVersion=1, scope='retained-fresh-android-x86-64-mysql-fixture-inputs-only',
            sourceRevision=self.revision, files=identities, rootfsAndApkBytesReadBack=True,
            emulatorFilesystemCopied=False, databaseStateCopied=False, offlineConsumerPinCreated=False,
            androidExecutionSucceeded=False, **{name: False for name in fixture.FALSE_FLAGS})
        self.payload['retention.json'] = fixture.encode(self.receipt)
        self.pin = dict(files=identities, producer=dict(integrationRevision=self.revision),
            retentionReceipt=fixture.bytes_identity(self.payload['retention.json']), artifacts={})

    def zip(self, name, payload):
        path = self.root / name
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
            for member, raw in payload.items(): archive.writestr(member, raw)
        return path

    def test_original_selection_remains_exact_when_current_recipe_changes(self):
        from tools import fetch_android_mysql_fixture_frozen as frozen
        pin = frozen.input_selection()
        expected = {name: fixture.files.identity(fixture.ROOT / name) for name in fixture.retained.builder.INPUTS}
        if expected == pin['providerSourceInputs']:
            self.assertEqual(fixture.load_pin(), pin)
        else:
            # The default consumer must keep refusing a new adapter as the old
            # producer. Explicit frozen-recipe reuse has a separate source gate.
            with self.assertRaisesRegex(ValueError, 'current-provider-recipe-differs'): fixture.load_pin()
        self.assertEqual(len(pin['files']), 9)
        self.assertEqual(pin['producer']['workflowRun'], 41109642918)
        self.assertEqual(pin['artifacts']['completeSources']['id'], 13006281602)
        self.assertFalse(pin['arm64Qualified']); self.assertFalse(pin['serverSchemasQualified'])

    def test_exact_zip_restores_only_nine_public_inputs_and_historical_receipt(self):
        path = self.zip('inputs.zip', self.payload)
        self.pin['artifacts']['inputs'] = fixture.files.identity(path)
        observed = fixture.restore_inputs(path, self.output, self.pin)
        self.assertEqual(observed, self.receipt)
        self.assertEqual({str(p.relative_to(self.output)) for p in self.output.rglob('*') if p.is_file()}, set(self.payload))
        for name, raw in self.payload.items(): self.assertEqual((self.output / name).read_bytes(), raw)
        self.assertFalse(observed['androidExecutionSucceeded'])

    def test_changed_missing_extra_and_duplicate_zip_members_fail_closed(self):
        for kind in ('changed', 'missing', 'extra', 'duplicate'):
            with self.subTest(kind=kind):
                payload = dict(self.payload)
                if kind == 'changed': payload['probe.apk'] = b'same fixture no claimed execution'
                elif kind == 'missing': del payload['probe.apk']
                elif kind == 'extra': payload['database-secret'] = b'private sibling must not be imported'
                path = self.zip(kind + '.zip', payload)
                if kind == 'duplicate':
                    with zipfile.ZipFile(path, 'a') as archive:
                        import warnings
                        with warnings.catch_warnings():
                            warnings.simplefilter('ignore', UserWarning)
                            archive.writestr('probe.apk', payload['probe.apk'])
                self.pin['artifacts']['inputs'] = fixture.files.identity(path)
                out = self.root / kind; out.mkdir()
                with self.assertRaises((ValueError, OSError)): fixture.restore_inputs(path, out, self.pin)

    def test_source_artifact_reads_every_member_and_rejects_changed_actual_source_bytes(self):
        runtime = fixture.encode(dict(sourcePackages=[dict(package='fixture-source', version='1.0')]))
        body = b'synthetic complete source archive; not executable or qualified'
        row = dict(file='fixture-source_1.0.orig.tar.gz', **fixture.bytes_identity(body))
        lock = fixture.encode(dict(mysql=dict(sourceArchives=[row])))
        manifest = fixture.encode(dict(formatVersion=1, scope='installed-ubuntu-package-corresponding-sources',
            runtimeManifestSha256=fixture.bytes_identity(runtime)['sha256'], sourceLockSha256=fixture.bytes_identity(lock)['sha256'],
            sourcePackages=json.loads(runtime)['sourcePackages'], files=[row], fileBytes=len(body)))
        self.pin['completeInstalledSources'] = dict(manifest=fixture.bytes_identity(manifest), archiveFiles=1, archiveBytes=len(body))
        assets = self.output / 'provider/assets/mysql-probe'; assets.mkdir(parents=True)
        (assets / 'runtime.json').write_bytes(runtime); (assets / 'sources.lock.json').write_bytes(lock)
        (self.output / 'SOURCE-MANIFEST.json').write_bytes(manifest)
        payload = {'out/mysql-sources/SOURCE-MANIFEST.json': manifest,
            'out/mysql-sources/server-runtime.json': runtime, 'out/mysql-sources/sources.lock.json': lock,
            'out/mysql-sources/' + row['file']: body, 'runtime/mysql-probe/README.md': b'original source recipe',
            'proot-probe/corresponding-source.tar.gz': b'synthetic separately named source companion'}
        path = self.zip('sources.zip', payload)
        self.pin['artifacts']['completeSources'] = fixture.files.identity(path)
        proof = fixture.restore_sources(path, self.root / 'sources', self.pin, self.output)
        self.assertEqual(proof['installedSourceArchiveFiles'], 1)
        self.assertEqual(proof['installedSourceArchiveBytes'], len(body))
        self.assertEqual(set(proof['allOriginalSourceZipMembers']), set(payload))
        payload['out/mysql-sources/' + row['file']] = b'x' * len(body)
        path = self.zip('bad-sources.zip', payload)
        self.pin['artifacts']['completeSources'] = fixture.files.identity(path)
        with self.assertRaisesRegex(ValueError, 'source-file-changed'):
            fixture.restore_sources(path, self.root / 'bad-sources', self.pin, self.output)

    def test_foreign_production_scope_and_execution_claim_in_retention_are_refused(self):
        for changed in (dict(scope='production-arm64'), dict(arm64Qualified=True), dict(androidExecutionSucceeded=True)):
            with self.subTest(changed=changed):
                receipt = dict(self.receipt, **changed); payload = dict(self.payload, **{'retention.json': fixture.encode(receipt)})
                path = self.zip(str(len(list(self.root.glob('bad*')))) + '-bad.zip', payload)
                pin = copy.deepcopy(self.pin); pin['artifacts']['inputs'] = fixture.files.identity(path)
                pin['retentionReceipt'] = fixture.bytes_identity(payload['retention.json'])
                out = self.root / ('bad-' + str(len(list(self.root.glob('bad*'))))); out.mkdir()
                with self.assertRaisesRegex(ValueError, 'retention-scope'): fixture.restore_inputs(path, out, pin)

    def test_existing_output_and_insufficient_space_refuse_before_remote_access(self):
        existing = self.root / 'saved'; existing.mkdir(); (existing / 'keep').write_bytes(b'private saved fixture')
        with patch.object(fixture, 'load_pin', return_value=dict(minimumFreeBytes=6 << 30)), \
                self.assertRaisesRegex(ValueError, 'existing-output'):
            fixture.acquire(existing, api=object())
        self.assertEqual((existing / 'keep').read_bytes(), b'private saved fixture')
        with patch.object(fixture, 'load_pin', return_value=dict(minimumFreeBytes=6 << 30)), \
                patch.object(fixture.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)), \
                self.assertRaisesRegex(ValueError, '6-GiB-free'):
            fixture.acquire(self.root / 'new', api=object())
        self.assertFalse((self.root / 'new').exists())

    def test_failure_diagnostics_export_only_fixed_guard_tokens(self):
        self.assertEqual(fixture.failure_context(ValueError('mysql-fixture-input-zip-identity'))['guard'],
            'mysql-fixture-input-zip-identity')
        for body in ('https://signed.invalid/?credential=private', '/private/accounts/secret',
                'mysql-fixture-private\nconfiguration'):
            self.assertEqual(fixture.failure_context(ValueError(body)), dict(exceptionType='ValueError', guard='unavailable'))


if __name__ == '__main__': unittest.main()
