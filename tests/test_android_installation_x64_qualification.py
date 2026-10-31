"""Source/export, receipt and refusal host fixtures; no Android or SQL execution.

Positive-shaped JSON is synthetic mutation-test data. Emulator-path fixtures
patch only host input preparation to reach negative admission checks; none can
produce a qualified receipt. Real committed selections remain disabled.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools import qualify_android_installation_x64 as qualification
from tests.test_android_handoff import axml


def fixture():
    descriptor = dict(mysqlVersion='8.0.46', currentPackagingRecipe=dict(commit='b' * 40),
        nativeSqlReceipt=dict(bytes=1, sha256='c' * 64), nativeInputSelection=dict(bytes=1, sha256='d' * 64))
    native = dict(mysqlVersion='8.0.46', mysqlUuid='01234567-89ab-4cde-8fab-0123456789ab',
        contentReceipt=dict(bytes=1, sha256='e' * 64), sourceLockSha256='f' * 64,
        databaseSnapshot=dict(tableCount=33, updateCount=31))
    mysql = dict(archive=dict(sha256='1' * 64)); programs = dict(archive=dict(sha256='2' * 64))
    provider_pin = dict(bytes=123, sha256='3' * 64)
    value = dict(formatVersion=1, scope=qualification.APP_SCOPE, sourceRevision='a' * 40,
        providerSha256=provider_pin['sha256'], api=33, abi='x86_64', phase='complete',
        mysqlUuid='11234567-89ab-4cde-8fab-0123456789ab', mysqlVersion='8.0.46',
        runtimeArchiveSha256=mysql['archive']['sha256'], programsArchiveSha256=programs['archive']['sha256'],
        contentReceiptSha256=native['contentReceipt']['sha256'], sourceLockSha256=native['sourceLockSha256'],
        playerbotsTableCount=33, playerbotsUpdateCount=31,
        **{name: True for name in qualification.POSITIVE}, **{name: False for name in qualification.FALSE_FLAGS})
    return descriptor, native, mysql, programs, provider_pin, value


class AndroidInstallationQualification(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup); self.root = Path(temporary.name)

    def check(self, value):
        descriptor, native, mysql, programs, provider_pin, _ = fixture()
        return qualification.validate_receipt(value, 'a' * 40, descriptor, native, mysql, programs, provider_pin)

    def test_exact_positive_shape_is_separate_from_native_and_has_all_lifecycle_boundaries(self):
        *_, value = fixture(); self.assertEqual(self.check(value), value)
        self.assertNotEqual(value['mysqlUuid'], fixture()[1]['mysqlUuid'])
        self.assertFalse(value['productionArm64ProviderQualified']); self.assertFalse(value['gameplayQualified'])

    def test_each_actual_coordinator_sql_promotion_restart_and_two_stop_flag_is_required(self):
        *_, original = fixture()
        for name in qualification.POSITIVE:
            for rejected in (False, 1, 'true', None):
                with self.subTest(flag=name, value=rejected), self.assertRaisesRegex(ValueError, 'lifecycle-incomplete'):
                    self.check(dict(original, **{name: rejected}))

    def test_runtime_hardware_world_character_and_ai_overclaims_refuse(self):
        *_, original = fixture()
        for name in qualification.FALSE_FLAGS:
            for rejected in (True, 0, 'false', None):
                with self.subTest(flag=name, value=rejected), self.assertRaisesRegex(ValueError, 'runtime-overclaim'):
                    self.check(dict(original, **{name: rejected}))

    def test_foreign_provider_revision_native_instance_hashes_counts_phase_and_unknown_fields_refuse(self):
        *_, original = fixture()
        for name, changed in (('formatVersion', True), ('api', True), ('api', 34), ('abi', 'arm64-v8a'),
                ('scope', 'android-13-x86_64-mysql-bootstrap-and-restart'), ('sourceRevision', 'b' * 40),
                ('providerSha256', '0' * 64), ('phase', 'second-clean-stop'), ('mysqlUuid', fixture()[1]['mysqlUuid']),
                ('mysqlUuid', '../caller'), ('mysqlVersion', '8.0.45'), ('runtimeArchiveSha256', '0' * 64),
                ('programsArchiveSha256', '0' * 64), ('contentReceiptSha256', '0' * 64), ('sourceLockSha256', '0' * 64),
                ('playerbotsTableCount', 32), ('playerbotsTableCount', True), ('playerbotsUpdateCount', 0),
                ('playerbotsUpdateCount', 31.0), ('privateCredential', 'must-never-be-exported'), ('failureType', 'IOException')):
            with self.subTest(field=name), self.assertRaises(ValueError): self.check(dict(original, **{name: changed}))
        missing = dict(original); del missing['twoCleanDatabaseStopsVerified']
        with self.assertRaises(ValueError): self.check(missing)
        with self.assertRaisesRegex(ValueError, 'duplicate-field'): qualification._json('{"phase":1,"phase":1}')

    def repository(self):
        root = self.root / 'source'; root.mkdir()
        def git(*words):
            return subprocess.check_output(['git', '-C', str(root), *words], stderr=subprocess.DEVNULL)
        git('init', '-q'); (root / 'script.py').write_text('print("source-only fixture")\n')
        (root / 'script.py').chmod(0o755); (root / 'empty').write_bytes(b'')
        git('add', '.')
        git('-c', 'user.name=Source Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'source fixture')
        revision = git('rev-parse', 'HEAD').decode().strip(); archive = self.root / 'activation-source.tar.gz'
        git('archive', '--format=tar.gz', '--output=' + str(archive), revision)
        return root, revision, archive, git

    def test_actual_git_source_and_full_canonical_export_include_empty_files_and_modes(self):
        root, revision, archive, _ = self.repository()
        result = qualification.source_snapshot(revision, archive, root=root)
        self.assertEqual(result['sourceRevision'], revision); self.assertEqual(result['sourceFiles'], 2)
        self.assertEqual(result['sourceInputs']['empty']['bytes'], 0)
        self.assertEqual(result['sourceInputs']['script.py']['mode'], '100755')
        self.assertTrue(result['allCanonicalSourceBytesMatchExactGitBlobs']); self.assertTrue(result['allWorkingSourceBytesVerified'])
        self.assertTrue(result['entireCommittedSourceExportVerified']); self.assertFalse(result['androidCoordinatorExecuted'])

    def test_tracked_symlink_cannot_admit_an_unbound_resolved_compilation_input(self):
        root, _, _, git = self.repository()
        (root / 'link').symlink_to('script.py'); git('add', 'link')
        git('-c', 'user.name=Source Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'tracked symlink')
        revision = git('rev-parse', 'HEAD').decode().strip(); archive = self.root / 'symlink-source.tar.gz'
        git('archive', '--format=tar.gz', '--output=' + str(archive), revision)
        with self.assertRaisesRegex(ValueError, 'complete-source-tree-required'):
            qualification.source_snapshot(revision, archive, root=root)

    def test_fresh_declared_batch_checkout_has_one_explicit_canonical_conversion(self):
        root, _, _, git = self.repository()
        (root / '.gitattributes').write_bytes(b'*.bat text eol=crlf\n')
        (root / 'gradlew.bat').write_bytes(b'@echo off\necho source fixture\n')
        git('add', '.gitattributes', 'gradlew.bat')
        git('-c', 'user.name=Source Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'batch attribute')
        revision = git('rev-parse', 'HEAD').decode().strip(); archive = self.root / 'declared-source.tar.gz'
        git('archive', '--format=tar.gz', '--output=' + str(archive), revision)
        (root / 'gradlew.bat').unlink(); git('checkout', '--', 'gradlew.bat')
        self.assertIn(b'\r\n', (root / 'gradlew.bat').read_bytes())
        self.assertEqual(git('status', '--porcelain'), b'')
        result = qualification.source_snapshot(revision, archive, root=root)
        conversion, = result['validatedCheckoutConversions']
        self.assertEqual(conversion['path'], 'gradlew.bat'); self.assertEqual(conversion['conversion'], 'declared-lf-to-crlf')
        self.assertNotEqual(conversion['canonical'], conversion['checkout'])
        (root / 'gradlew.bat').write_bytes(b'@echo off\r\necho foreign\r\n')
        git('update-index', '--assume-unchanged', 'gradlew.bat')
        with self.assertRaisesRegex(ValueError, 'undeclared-checkout-conversion'):
            qualification.source_snapshot(revision, archive, root=root)

    def test_assume_unchanged_cannot_hide_foreign_working_bytes_and_export_cannot_be_relabelled(self):
        root, revision, archive, git = self.repository()
        git('update-index', '--assume-unchanged', 'script.py'); (root / 'script.py').write_text('print("different bytes")\n')
        with self.assertRaisesRegex(ValueError, 'differs-from-git-blob'):
            qualification.source_snapshot(revision, archive, root=root)
        (root / 'script.py').write_text('print("source-only fixture")\n')
        archive.write_bytes(archive.read_bytes() + b'foreign bytes')
        with self.assertRaisesRegex(ValueError, 'canonical-source-export-differs'):
            qualification.source_snapshot(revision, archive, root=root)

    def test_git_replace_cannot_relabel_foreign_working_source_and_archive_as_activation_revision(self):
        root, revision, _, git = self.repository()
        (root / 'script.py').write_text('print("foreign replacement fixture")\n'); git('add', 'script.py')
        git('-c', 'user.name=Source Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-q', '-m', 'foreign tree')
        foreign = git('rev-parse', 'HEAD').decode().strip()
        git('replace', revision, foreign); git('reset', '--hard', revision)
        self.assertEqual(git('status', '--porcelain'), b'')
        archive = self.root / 'foreign-replaced-export.tar.gz'
        git('archive', '--format=tar.gz', '--output=' + str(archive), revision)
        with self.assertRaises(ValueError): qualification.source_snapshot(revision, archive, root=root)

    def test_dirty_untracked_wrong_head_and_symlink_file_substitution_refuse(self):
        root, revision, archive, git = self.repository()
        with self.assertRaisesRegex(ValueError, 'head-differs'):
            qualification.source_snapshot('0' * 40, archive, root=root)
        (root / 'untracked').write_bytes(b'unknown input')
        with self.assertRaisesRegex(ValueError, 'untracked-source'):
            qualification.source_snapshot(revision, archive, root=root)
        (root / 'untracked').unlink(); (root / 'script.py').unlink(); (root / 'script.py').symlink_to('empty')
        with self.assertRaises(ValueError): qualification.source_snapshot(revision, archive, root=root)

    def test_actual_compiled_app_manifest_requires_default_package_debug_and_target35(self):
        qualification._manifest(axml(enabled=False))
        for value in (axml(enabled=False, debug=False), axml(enabled=False, target_sdk=34), b'<manifest/>'):
            with self.assertRaises(ValueError): qualification._manifest(value)
        with self.assertRaisesRegex(ValueError, 'default-package'):
            qualification._manifest(axml(enabled=False), testing=True)

    def test_pending_fixture_refuses_before_artifact_or_apk_or_source_or_adb_or_output(self):
        output = self.root / 'must-not-exist'
        pending=dict(formatVersion=1,scope=qualification.gate.SCOPE,repository='Russianranger/esteria_android',
            enabled=False,state=qualification.gate.PENDING,nativeSql=None,provider=None,providerReadback=None,
            **{name:False for name in qualification.gate.FALSE_FLAGS})
        lock=self.root/'pending.json';lock.write_text(json.dumps(pending))
        with patch.object(qualification.gate,'LOCK',lock),patch.object(qualification.provider, 'verify') as provider, patch.object(qualification, 'verify_apks') as apk, \
                patch.object(qualification, 'source_snapshot') as source, patch.object(qualification, 'run_bounded') as adb, \
                self.assertRaisesRegex(ValueError, 'measured-native-sql-and-provider-required'):
            qualification.qualify(*([self.root / 'missing'] * 6), 'a' * 40, self.root / 'source.tar.gz', output)
        for guard in (provider, apk, source, adb): guard.assert_not_called()
        self.assertFalse(output.exists())

    def refused_device(self, responses):
        descriptor, native, mysql, programs, provider_pin, _ = fixture()
        selected = dict(provider=provider_pin); output = self.root / 'evidence'
        calls = []
        def command(words, destination, timeout, limit):
            calls.append(words)
            if 'force-stop' in words: return 0, ''
            try: return responses(len(calls), words)
            except IndexError: return 1, ''  # Best-effort diagnostic fixture is unavailable.
        def small(path, maximum): return mysql if 'mysql-probe' in str(path) else programs
        with patch.object(qualification, '_inputs', return_value=(selected, descriptor, native)), \
                patch.object(qualification, 'source_snapshot', return_value={'hostNegativeFixtureOnly': True}), \
                patch.object(qualification, 'verify_apks', return_value={'hostNegativeFixtureOnly': True}), \
                patch.object(qualification.gate, 'small', side_effect=small), \
                patch.object(qualification, 'run_bounded', side_effect=command), self.assertRaisesRegex(ValueError, 'sanitized receipt retained'):
            qualification.qualify(*([self.root / 'missing'] * 6), 'a' * 40, self.root / 'source.tar.gz', output)
        report = json.loads((output / 'qualification.json').read_bytes())
        self.assertFalse(report['androidX64CoordinatorQualified'])
        return calls, report, output

    def test_physical_device_is_refused_without_install_or_stop_and_raw_serial_is_not_exported(self):
        calls, report, output = self.refused_device(lambda *_: (0, 'private-device-serial\n'))
        self.assertEqual(len(calls), 1); self.assertNotIn('private-device-serial', (output / 'qualification.json').read_text())
        self.assertNotIn('appEvidence', report)
        self.assertEqual({path.name for path in output.iterdir()}, {'qualification.json', 'source-companion.json'})

    def test_preexisting_app_is_refused_without_install_or_force_stop(self):
        values = ['emulator-5554\n', '1\n', '33\n', 'x86_64\n', 'fresh-emulator-fingerprint\n', 'package:existing.apk\n']
        calls, report, _ = self.refused_device(lambda index, *_: (0, values[index-1]))
        self.assertEqual(len(calls), 6); self.assertFalse(any('install' in words or 'force-stop' in words for words in calls))
        self.assertEqual(report['phase'], 'emulator-admission')

    def test_malformed_private_receipt_never_enters_artifacts_and_fixed_test_gets_no_authority_args(self):
        values = ['emulator-5554\n', '1\n', '33\n', 'x86_64\n', 'fresh-emulator-fingerprint\n', '', '',
            'Success\n', 'Success\n', 'OK (1 test)\nINSTRUMENTATION_CODE: -1\n',
            '{"privateCredential":"not-for-artifacts","callerPath":"/private/foreign"}', '']
        calls, report, output = self.refused_device(lambda index, *_: (0, values[index-1]))
        instrument = next(words for words in calls if 'instrument' in words)
        self.assertEqual(instrument[1:], ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class', qualification.TEST,
            qualification.PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'])
        self.assertEqual(calls[-1][1:], ['shell', 'am', 'force-stop', qualification.PACKAGE])
        self.assertEqual(report['phase'], 'private-receipt-validation'); self.assertNotIn('appEvidence', report)
        for path in output.iterdir():
            self.assertNotIn('not-for-artifacts', path.read_text()); self.assertNotIn('/private/foreign', path.read_text())

    def test_private_java_output_exports_only_known_classes_and_owned_source_line_locations(self):
        owner = qualification.NAMESPACE + '.runtime.ServerInstallationSetup'
        raw = ('INSTRUMENTATION_STATUS: stack=java.io.IOException: password=NEVER_EXPORT /private/db\n'
            '\tat ' + owner + '$Handle.secretValue(ServerInstallationSetup.java:42)\n'
            '\tat ' + owner + '.method(/private/foreign.java:4)\n'
            '\tat foreign.password.Secret.method(Secret.java:4)\n'
            'Caused by: java.lang.AssertionError: nonce=NEVER_EXPORT\n'
            'private.username.Exception: NEVER_EXPORT\n')
        observed = qualification.java_failure_locations(raw)
        self.assertEqual(observed['exceptionTypes'], ['java.io.IOException', 'java.lang.AssertionError'])
        self.assertEqual(observed['sourceFrames'], [dict(className=owner, file='ServerInstallationSetup.java', line=42)])
        self.assertNotIn('NEVER_EXPORT', json.dumps(observed)); self.assertNotIn('secretValue', json.dumps(observed))
        self.assertNotIn('/private', json.dumps(observed))

    def test_failed_private_receipt_projects_exact_identity_phase_and_classes_never_private_extras(self):
        *_, provider_pin, original = fixture()
        value = dict(original, qualificationSucceeded=False, phase='fresh-core-sql', failureType='IOException',
            cleanupFailureType='AssertionError', privateCredentials='NEVER_EXPORT', callerPath='/private/foreign', pid=4567)
        observed = qualification.failed_app_receipt(json.dumps(value), 'a' * 40, provider_pin)
        self.assertEqual(observed, dict(sourceRevision='a' * 40, providerSha256=provider_pin['sha256'],
            phase='fresh-core-sql', qualificationSucceeded=False, failureType='IOException', cleanupFailureType='AssertionError'))
        for change in (dict(sourceRevision='b' * 40), dict(providerSha256='0' * 64), dict(phase='NEVER_EXPORT'),
                dict(failureType='NEVER_EXPORT'), dict(cleanupFailureType='/private/path'), dict(api=True), dict(gameplayQualified=True)):
            with self.subTest(change=change), self.assertRaises(ValueError):
                qualification.failed_app_receipt(json.dumps(dict(value, **change)), 'a' * 40, provider_pin)

    def test_guest_log_discards_messages_paths_queries_and_unknown_helper_symbols(self):
        raw = ('Traceback (most recent call last):\n'
            '  File "/work/helpers/' + 'a' * 64 + '/mysql_bootstrap.py", line 42, in privateSecretMethod\n'
            '  File "/private/password/foreign.py", line 42, in main\n'
            'PermissionError: [Errno 13] NEVER_EXPORT credentials=/private/db\n'
            'Database setup failed (PermissionError; errno=13; helperFrames=main:98,setup:42,NEVER_EXPORT:9); persistent state was preserved for recovery\n'
            'Local database service failed (BootstrapError); private value NEVER_EXPORT\n')
        observed = qualification.guest_failure_locations(raw)
        self.assertEqual(observed['exceptionTypes'], ['BootstrapError', 'PermissionError'])
        self.assertEqual(observed['sourceFrames'], [dict(module='mysql_bootstrap.py', line=42)])
        self.assertEqual(observed['helperFrames'], [dict(function='main', line=98), dict(function='setup', line=42)])
        self.assertEqual(observed['errno'], [13]); self.assertNotIn('NEVER_EXPORT', json.dumps(observed))
        self.assertNotIn('/private', json.dumps(observed)); self.assertNotIn('privateSecretMethod', json.dumps(observed))

    def test_diagnostics_use_only_fixed_log_families_and_strict_owned_operation_paths(self):
        *_, provider_pin, original = fixture(); calls = []
        failed = dict(original, qualificationSucceeded=False, phase='fresh-core-sql', failureType='IOException', secret='NEVER_EXPORT')
        def command(label, words, *, timeout):
            self.assertGreater(timeout, 0); self.assertLessEqual(timeout, 15)
            calls.append((label, words))
            if label == 'failed-app-receipt': return json.dumps(failed)
            if label.startswith('guest-inventory-'):
                family = words[4].split('/')[-1]
                return '\n'.join(['files/state/' + family + '/' + 'b' * 32 + '/logs/stderr.log',
                    'files/state/' + family + '/../accounts/database-secret',
                    'files/state/' + family + '/' + 'b' * 32 + '/logs/engine-private.log',
                    'files/state/' + family + '/1234/logs/stdout.log', '/private/NEVER_EXPORT'])
            return 'Database setup failed (PermissionError; errno=13; helperFrames=setup:42); NEVER_EXPORT\n'
        observed = qualification.failure_diagnostics(command, 'java.io.IOException: NEVER_EXPORT\n', 'a' * 40, provider_pin)
        self.assertFalse(observed['qualificationSucceeded']); self.assertEqual(len(observed['guest']), 3)
        reads = [words for _, words in calls if '65536' in words]
        self.assertEqual(len(reads), 3)
        for words, family in zip(reads, qualification.LOG_FAMILIES):
            self.assertEqual(words, ['exec-out', 'run-as', qualification.PACKAGE, 'head', '-c', '65536',
                'files/state/' + family + '/' + 'b' * 32 + '/logs/stderr.log'])
        self.assertNotIn('b' * 32, json.dumps(observed)); self.assertNotIn('NEVER_EXPORT', json.dumps(observed))
        self.assertNotIn('engine-private', json.dumps(observed)); self.assertNotIn('database-secret', json.dumps(observed))
        self.assertFalse(any('(' in words or ')' in words for _, words in calls))

    def test_expired_diagnostic_budget_stops_reads_without_changing_failure_scope(self):
        *_, provider_pin, _ = fixture()
        with patch.object(qualification.time, 'monotonic', side_effect=[0, 46, 46]), \
                patch('builtins.print'), patch.object(qualification, 'java_failure_locations', return_value={}), \
                patch.object(qualification, 'failed_app_receipt') as receipt:
            calls = []
            observed = qualification.failure_diagnostics(lambda *args, **kwargs: calls.append(args), '', 'a' * 40, provider_pin)
        self.assertEqual(calls, []); receipt.assert_not_called()
        self.assertTrue(observed['diagnosticBudgetExhausted']); self.assertFalse(observed['qualificationSucceeded'])

    def test_failed_instrumentation_collects_safe_failure_before_unchanged_force_stop(self):
        *_, provider_pin, original = fixture()
        failed = dict(original, qualificationSucceeded=False, phase='fresh-core-sql', failureType='IOException', secret='NEVER_EXPORT')
        startup = ['emulator-5554\n', '1\n', '33\n', 'x86_64\n', 'fresh-emulator-fingerprint\n', '', '', 'Success\n', 'Success\n']
        def response(index, words):
            if index <= len(startup): return 0, startup[index-1]
            if 'instrument' in words: return 0, 'INSTRUMENTATION_STATUS: stack=java.io.IOException: NEVER_EXPORT\nFAILURES!!!\n'
            if words[-1] == 'files/installation-x64-qualification.json': return 0, json.dumps(failed)
            if 'find' in words: return 0, ''
            return 1, 'NEVER_EXPORT'
        calls, report, output = self.refused_device(response)
        self.assertEqual(report['phase'], 'actual-four-schema-coordinator'); self.assertNotIn('appEvidence', report)
        self.assertEqual(report['failureDiagnostics']['appFailure']['phase'], 'fresh-core-sql')
        self.assertEqual(report['failureDiagnostics']['java']['exceptionTypes'], ['java.io.IOException'])
        self.assertEqual(calls[-1][1:], ['shell', 'am', 'force-stop', qualification.PACKAGE])
        self.assertNotIn('NEVER_EXPORT', (output / 'qualification.json').read_text())


if __name__ == '__main__': unittest.main()
