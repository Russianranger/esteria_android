"""Guest admission/real Preparation host fixtures, never native SQL/Android proof.

Tiny synthetic ELF headers and positive-shaped metadata below are not executable
qualification inputs. No production ARM admission function is patched or used to
admit them. Source SQL selection runs against the existing explicit host content
fixture, and no source SQL, synthetic ELF or debug guest process is executed.
"""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from runtime import mysql_bootstrap as db
from tests import test_runtime_playerbots_setup as pb_fixture

ENTRY = Path(__file__).parent / 'android-installation-x64/installation_x64_entry.py'
spec = importlib.util.spec_from_file_location('installation_x64_guest_fixture', ENTRY)
entry = importlib.util.module_from_spec(spec); sys.modules[spec.name] = entry; spec.loader.exec_module(entry)


def pin(raw): return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
def encoded(value): return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def elf(*, interpreter=None, machine=62, suffix=b''):
    count = 2 if interpreter else 1; size = 64 + 56 * count
    value = b'' if interpreter is None else interpreter.encode() + b'\0'
    size += len(value) + len(suffix); raw = bytearray(size)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', raw, 16, 3, machine, 1)
    struct.pack_into('<Q', raw, 32, 64); struct.pack_into('<HHH', raw, 52, 64, 56, count)
    struct.pack_into('<IIQQQQQQ', raw, 64, 1, 5, 0, 0, 0, size, size, 4096)
    if interpreter:
        struct.pack_into('<IIQQQQQQ', raw, 120, 3, 4, 176, 0, 0, len(value), len(value), 1)
        raw[176:176 + len(value)] = value
    if suffix: raw[-len(suffix):] = suffix
    return bytes(raw)


class InstallationX64Guest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name); self.root = self.base / 'programs'; self.root.mkdir(mode=0o700)
        self.authority = self.base / 'installation-x64-inputs.json'
        self.source_lock = {'sources': {'server': {'commit': 'f' * 40}}}
        self.source = {'commit': 'f' * 40}
        self.origin_build = {'fixtureOnly': 'original architecture-neutral content packaging origin'}
        self.modules = {'fixtureOnly': 'original compiled modules'}
        self.content_pin = pin(b'explicit synthetic content receipt')
        self.make_fixture()

    def put(self, name, raw, mode=0o444):
        path = self.root / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists(): path.chmod(0o600)
        path.write_bytes(raw); path.chmod(mode); return pin(raw)

    def document(self, name, value): return self.put(name, encoded(value))

    def make_fixture(self):
        origin = dict(originalBuild=self.document('provenance/server-build.json', self.origin_build),
            compiledModules=self.document('provenance/server-modules.json', self.modules),
            sourceLock=self.document('provenance/sources.lock.json', self.source_lock), source=self.source)
        self.build = dict(formatVersion=1, scope='source-built-x86-64-server-setup-tools-only', phase='built-unqualified-inputs',
            integrationRevision='a' * 40, targets=['dbimport', 'esteria_playerbots_database_reference'],
            actualCompileSucceeded=True, originalDbimportExecutableBuilt=True,
            originalDbimportTargetAndFullStaticModuleScriptLinkGraphBuilt=True,
            originalArm64ReceiptReusedForX64Qualification=False, statementsDeclared=52,
            originalArm64Build=origin['originalBuild'], originalArm64Modules=origin['compiledModules'],
            sourceLock=origin['sourceLock'], serverSource=self.source,
            **{name: False for name in ('sqlExecuted', 'androidRuntimeQualified', 'productionArm64ProviderQualified',
                'fourSchemaCoordinatorQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')})
        libraries = {}
        for index, name in enumerate((entry.LOADER, 'usr/lib/x86_64-linux-gnu/libc.so.6')):
            raw = elf(suffix=('synthetic library ' + str(index)).encode())
            identity = self.put('libraries/' + name, raw)
            libraries[name] = dict(**identity, elf=dict(machine=62, elfClass=2, interpreter=None, loadSegments=1))
        self.build['libraries'] = libraries
        self.put('libexec/ld-linux-x86-64.so.2', (self.root / 'libraries' / entry.LOADER).read_bytes(), 0o555)
        executables = {}
        for role, (_, actual) in entry.ROLES.items():
            raw = elf(interpreter='/lib64/ld-linux-x86-64.so.2', suffix=role.encode())
            identity = self.put(actual, raw, 0o555)
            executables[role] = dict(**identity, elf=dict(machine=62, elfClass=2,
                interpreter='/lib64/ld-linux-x86-64.so.2', loadSegments=1),
                original=pin(b'synthetic original ' + role.encode()), pairedDebug=pin(b'synthetic debug ' + role.encode()))
        self.build['executables'] = executables
        self.native = dict(formatVersion=1, scope='disposable-native-x64-measured-setup-four-schema-sql', phase='complete',
            inputSelection=pin(b'synthetic exact native SQL selection'),
            buildProducer=dict(workflowRun=111, job=222, integrationRevision=self.build['integrationRevision']),
            actualX64BuildReceipt=pin(b'updated below'), actualX64LibrarySourceReadback=pin(b'synthetic full library-source proof'),
            contentOriginBuild=origin['originalBuild'], compiledModules=origin['compiledModules'], source=self.source,
            sourceLockSha256=origin['sourceLock']['sha256'], contentOriginIsOriginalArm64Packaging=True,
            originalArm64ReceiptReusedForX64Qualification=False, contentReceipt=self.content_pin,
            originalMysqlArchive=pin(b'synthetic original measured mysql archive'), mysqlVersion='8.0.46',
            mysqlUuid='01234567-89ab-4cde-8fab-0123456789ab', selectedSourceBaseFiles=29, selectedSourceUpdates=31,
            preparedStatementCount=52, checkedInvocations={}, databaseSnapshot={'hostMetadataFixtureOnly': True},
            actualLoaderReentry=dict(exitCode=0, preparedStatementCount=52),
            **{name: True for name in entry.POSITIVE}, **{name: False for name in entry.FALSE_FLAGS})
        for role, actual in executables.items():
            self.native['checkedInvocations'][role] = dict(path='/native-fixture/invocations/' + role,
                invocation=pin(('synthetic native invocation ' + role).encode()), actualExecutable=entry._scalar(actual),
                loader=entry._scalar(libraries[entry.LOADER]), invocationIsOriginalElf=False, originalElfBytesChanged=False)
        self.closure = dict(formatVersion=1, scope='android-x64-original-setup-elf-closure',
            buildReceipt=pin(b'updated below'), nativeSqlReceipt=pin(b'updated below'),
            nativeInputSelection=self.native['inputSelection'], nativeBuildSourceReadback=self.native['actualX64LibrarySourceReadback'],
            buildProducer=self.native['buildProducer'], sourceOrigin=origin,
            libraries={name: entry._scalar(row) for name, row in libraries.items()},
            loader=dict(path='libexec/ld-linux-x86-64.so.2', **entry._scalar(libraries[entry.LOADER])),
            originalElfBytesChanged=False, nativeInvocationScriptsReused=False, androidRuntimeQualified=False, executables={})
        self.refresh_scripts(); self.refresh()

    def refresh_scripts(self):
        for role, (script, actual) in entry.ROLES.items():
            raw = entry.invocation_source(self.build, role)
            self.closure['executables'][role] = dict(actualPath=actual, actualExecutable=entry._scalar(self.build['executables'][role]),
                invocationPath=script, invocation=self.put(script, raw, 0o555))

    def refresh(self):
        build_pin = self.document('provenance/playerbots-helper-build.json', self.build)
        self.closure['buildReceipt'] = self.native['actualX64BuildReceipt'] = build_pin
        self.native['playerbotsFirst'] = dict(scope=entry.playerbots.SCOPE, mysqlUuid=self.native['mysqlUuid'],
            mysqlVersion=self.native['mysqlVersion'], helperBuildReceipt=build_pin,
            helperExecutable=self.native['checkedInvocations']['playerbots-schema']['invocation'],
            originalBuild=self.native['contentOriginBuild'], compiledModules=self.native['compiledModules'],
            sourceLockSha256=self.native['sourceLockSha256'], contentReceipt=self.native['contentReceipt'], preparedStatementCount=52,
            databaseSnapshot=self.native['databaseSnapshot'], compiledPlayerbotsLoaderExecuted=True,
            playerbotsSchemaInitialized=True, exactSourceLedgerVerified=True, coreSchemasLedgersCredentialsAccountPreserved=True)
        self.closure['nativeSqlReceipt'] = self.document('provenance/playerbots-native-sql.json', self.native)
        self.refresh_closure()

    def refresh_closure(self):
        row = self.document('provenance/x64-closure.json', self.closure)
        self.authority.write_bytes(encoded(dict(formatVersion=1, scope='android-x64-installation-fixed-inputs', closure=row)))

    def admit(self): return entry._admit(self.root, self.authority)

    def test_closed_fixture_metadata_and_elf_bytes_are_read_without_execution(self):
        selected = self.admit(); self.assertEqual(selected.native, self.native)
        self.assertEqual(selected.verify().authority_identity, pin(self.authority.read_bytes()))
        self.assertFalse(selected.closure['androidRuntimeQualified'])
        self.assertNotEqual(selected.closure['executables']['dbimport']['invocation'],
            selected.native['checkedInvocations']['dbimport']['invocation'])

    def test_all_positive_native_sql_boundaries_and_no_runtime_claims_are_required(self):
        original = copy.deepcopy(self.native)
        for name in entry.POSITIVE:
            with self.subTest(boundary=name):
                self.native = dict(original, **{name: False}); self.refresh()
                with self.assertRaisesRegex(db.BootstrapError, 'positive native SQL required'): self.admit()
        for name in entry.FALSE_FLAGS:
            with self.subTest(claim=name):
                self.native = dict(original, **{name: True}); self.refresh()
                with self.assertRaisesRegex(db.BootstrapError, 'positive native SQL required'): self.admit()

    def test_arm_or_foreign_selection_source_build_counts_and_reentry_refuse(self):
        original = copy.deepcopy(self.native)
        for field, value in (('scope', 'disposable-native-arm64-product-playerbots-schema'),
                ('inputSelection', pin(b'foreign native selection')), ('buildProducer', dict(workflowRun=1)),
                ('actualX64LibrarySourceReadback', pin(b'foreign source closure')),
                ('contentOriginBuild', pin(b'foreign original build')), ('compiledModules', pin(b'foreign modules')),
                ('sourceLockSha256', '0' * 64), ('originalArm64ReceiptReusedForX64Qualification', True),
                ('preparedStatementCount', 52.0), ('selectedSourceUpdates', 30), ('selectedSourceBaseFiles', 28),
                ('actualLoaderReentry', dict(exitCode=1, preparedStatementCount=52)),
                ('failureCode', 'synthetic'), ('worldserverExecuted', True)):
            with self.subTest(field=field):
                self.native = dict(original, **{field: value}); self.refresh()
                with self.assertRaises(db.BootstrapError): self.admit()

    def test_companion_and_closure_no_caller_authority_or_untyped_flags(self):
        for value in ({'formatVersion': 1, 'scope': 'android-x64-installation-fixed-inputs', 'closure': pin(b'x'), 'path': '/caller'},
                {'formatVersion': True, 'scope': 'android-x64-installation-fixed-inputs', 'closure': pin(b'x')}):
            self.authority.write_bytes(encoded(value))
            with self.assertRaises(db.BootstrapError): self.admit()
        self.refresh_closure()
        for field, value in (('androidRuntimeQualified', True), ('nativeInvocationScriptsReused', True),
                ('originalElfBytesChanged', True), ('enabled', True)):
            original = copy.deepcopy(self.closure); self.closure[field] = value; self.refresh_closure()
            with self.subTest(field=field), self.assertRaises(db.BootstrapError): self.admit()
            self.closure = original
        self.refresh_closure(); self.authority.write_bytes(b'{"scope":1,"scope":1}')
        with self.assertRaisesRegex(db.BootstrapError, 'duplicate'): self.admit()

    def test_changed_or_shared_or_symlinked_inputs_and_stale_authority_refuse(self):
        selected = self.admit()
        target = self.root / 'libraries' / entry.LOADER; original = target.read_bytes()
        target.chmod(0o644); target.write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
        with self.assertRaises(db.BootstrapError): self.admit()
        target.write_bytes(original)
        os.link(target, self.base / 'foreign-link')
        with self.assertRaises(db.BootstrapError): self.admit()
        (self.base / 'foreign-link').unlink(); target.unlink(); target.symlink_to(self.root / 'libexec/ld-linux-x86-64.so.2')
        with self.assertRaises((db.BootstrapError, OSError)): self.admit()
        target.unlink(); target.write_bytes(original)
        self.authority.write_bytes(self.authority.read_bytes() + b' ')
        with self.assertRaises(db.BootstrapError): selected.verify()

    def test_wrong_actual_machine_and_changed_canonical_invocation_are_rejected_even_when_repinned(self):
        actual = 'bin/dbimport.elf'; raw = elf(machine=183, interpreter='/lib64/ld-linux-x86-64.so.2')
        identity = self.put(actual, raw, 0o555)
        self.build['executables']['dbimport'].update(identity)
        self.closure['executables']['dbimport']['actualExecutable'] = identity
        self.native['checkedInvocations']['dbimport']['actualExecutable'] = identity
        self.refresh_scripts(); self.refresh()
        with self.assertRaisesRegex(db.BootstrapError, 'ELF62'): self.admit()
        self.make_fixture()
        script = 'helpers/playerbots-schema'
        self.closure['executables']['playerbots-schema']['invocation'] = self.put(script, b'#!/bin/sh\nexit 0\n', 0o555)
        self.refresh_closure()
        with self.assertRaisesRegex(db.BootstrapError, 'source-owned invocation changed'): self.admit()

    def test_paths_loader_and_native_invocation_identity_cannot_be_relabelled(self):
        for kind in ('actual-path', 'invocation-path', 'native-script', 'library-path', 'loader'):
            self.make_fixture()
            if kind == 'actual-path': self.closure['executables']['dbimport']['actualPath'] = '../caller'
            elif kind == 'invocation-path': self.closure['executables']['dbimport']['invocationPath'] = '/caller'
            elif kind == 'native-script':
                self.closure['executables']['dbimport']['invocation'] = self.native['checkedInvocations']['dbimport']['invocation']
            elif kind == 'library-path':
                self.build['libraries']['usr/lib/x86_64-linux-gnu/../caller'] = self.build['libraries'][entry.LOADER]
                self.closure['libraries']['usr/lib/x86_64-linux-gnu/../caller'] = entry._scalar(self.build['libraries'][entry.LOADER])
            else: self.closure['loader']['path'] = '/lib64/ld-linux-x86-64.so.2'
            self.refresh()
            with self.subTest(kind=kind), self.assertRaises(db.BootstrapError): self.admit()

    def test_real_source_sql_selection_produces_actual_preparation_and_rechecks_before_retry(self):
        fixture = pb_fixture.RuntimePlayerbotsSetup(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        self.source = fixture.content.manifest['source']
        self.origin_build = {'explicitHostFixture': 'original content packaging metadata'}
        build_pin = pin(encoded(self.origin_build)); lock_pin = pin(encoded(self.source_lock))
        fixture.fixture.compiled['serverBuild'] = build_pin
        fixture.fixture.lock = lock_pin['sha256']
        fixture.fixture.manifest['sourceLockSha256'] = fixture.fixture.compiled['sourceLockSha256'] = lock_pin['sha256']
        fixture.fixture.receipt['sourceLockSha256'] = lock_pin['sha256']
        fixture.fixture.write()
        # This fixture normally gives producer JSON an intentionally different
        # identity from canonical archived metadata. Here the actual guest
        # provenance uses those exact archived bytes, so bind both explicitly.
        fixture.fixture.receipt['compiledModules'] = pin(encoded(fixture.fixture.compiled))
        package_plan = fixture.fixture.root / 'metadata/package-plan.json'
        plan_metadata = json.loads(package_plan.read_bytes())
        plan_metadata['compiledModules'] = fixture.fixture.receipt['compiledModules']
        raw = encoded(plan_metadata); package_plan.write_bytes(raw)
        fixture.fixture.receipt['archiveFiles']['metadata/package-plan.json'] = pin(raw)
        fixture.fixture.pin_receipt(); verified = fixture.fixture.verify()
        self.modules = fixture.fixture.compiled; self.content_pin = verified.identities['receipt']; self.make_fixture()
        selected = self.admit(); plan = selected._preparation(verified, fixture.mysql, version='8.0.46')
        self.assertIsInstance(plan, entry.playerbots.Preparation); self.assertIs(plan.content, verified)
        self.assertEqual(len(plan.expected), 31)
        self.assertEqual(plan.executable, self.root / 'helpers/playerbots-schema')
        self.assertEqual(plan.binding['helperExecutable'], self.closure['executables']['playerbots-schema']['invocation'])
        self.assertEqual(plan.helper_receipt_identity, self.closure['buildReceipt'])
        self.assertEqual(plan.mysql, fixture.mysql)
        with self.assertRaisesRegex(db.BootstrapError, 'MySQL version differs'):
            selected._preparation(verified, fixture.mysql, version='8.0.45')
        target = self.root / 'helpers/playerbots-schema.elf'; target.chmod(0o755); target.write_bytes(target.read_bytes() + b'changed')
        with self.assertRaises(db.BootstrapError): selected._preparation(verified, fixture.mysql, version='8.0.46')

    def test_guest_cli_has_only_fixed_inputs_and_pending_refusal_creates_no_result(self):
        arguments = ['--expected-version', '8.0.46', '--operation-id', 'a' * 32,
            '--service-operation-id', 'b' * 32, '--instance-uuid', '01234567-89ab-4cde-8fab-0123456789ab']
        # Current source has no measured companion. The debug entry therefore
        # refuses before opening SQL or creating a result, even on a host.
        environment = dict(os.environ, PYTHONPATH=str(ENTRY.parents[2]))
        done = subprocess.run([sys.executable, str(ENTRY), *arguments], cwd=self.base,
            env=environment, capture_output=True, text=True)
        self.assertEqual(done.returncode, 1); self.assertNotIn('completed', done.stdout)
        self.assertIn('private diagnostics retained', done.stderr)
        self.assertNotIn(str(self.base), done.stderr)
        rejected = subprocess.run([sys.executable, str(ENTRY), *arguments, '--programs-root', str(self.root)],
            cwd=self.base, env=environment, capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        tree = ast.parse(ENTRY.read_text())
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue({'_run', '_finish_playerbots', '_selected_content'} <= names)
        self.assertNotIn('_helper_inputs', names)
        self.assertFalse(any(isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('tools')
            for node in ast.walk(tree)))


if __name__ == '__main__': unittest.main()
