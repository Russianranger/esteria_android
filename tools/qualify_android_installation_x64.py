#!/usr/bin/env python3
"""Execute the measured coordinator fixture only on a fresh Android13 x64 emulator.

Provider measurement P, historical runtime producers and current activation Q
retain separate identities. No receipt from those earlier gates is Android
coordinator execution. Private app receipts, JUnit output and bounded wrapper
logs are parsed in temporary storage. Only whitelisted source locations and
failure identities are exported; no raw output, database state, journals,
credentials or logcat enter artifacts. A missing measured selection refuses
before output or ADB activity.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time

if not __package__:
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import android_installation_x64_inputs as gate
from tools import provider_android_installation_x64 as provider
from tools import provider_client_runtime as zips
from tools import qualify_android_handoff as manifest
from tools.qualify_android_installer import instrument_passed, run_bounded

ROOT = Path(__file__).resolve().parents[1]
NAMESPACE = 'io.github.russianranger.esteria'
PACKAGE = NAMESPACE + '.stock'
TEST_CLASS = NAMESPACE + '.runtime.ServerInstallationX64Test'
TEST = TEST_CLASS + '#actualAndroidCoordinatorInitializesFourSchemasPromotesAndRestarts'
SCOPE = 'android-13-x86_64-current-java-four-schema-installation-and-restart'
APP_SCOPE = 'android13-x64-owned-four-schema-installation-and-restart'
POSITIVE = ('qualificationSucceeded', 'androidJavaCoordinatorExecuted', 'actualFourSchemaSqlExecuted',
    'sourceBoundGuestHelpersExecuted', 'ordinaryNativeOwnerExecuted', 'androidBionicProotLocatorExecuted',
    'slotPromoted', 'completedSelectionReadBack', 'activeFreshInitializationRefused', 'restartedSameLiveSqlUuid',
    'actualCoreAccountRealmAndBotSqlPreserved', 'privateJournalsAndCredentialsPreserved', 'twoCleanDatabaseStopsVerified')
FALSE_FLAGS = ('productionArm64ProviderQualified', 'thorQualified', 'authserverExecuted', 'worldserverExecuted',
    'serverDataQualified', 'characterPersistenceQualified', 'playerbotsAiQualified', 'gameplayQualified')
HELPERS = {'database-setup': ('mysql_bootstrap.py', 'android_database_setup.py'),
    'database-service': ('mysql_bootstrap.py', 'mysql_service.py')}
require = gate.require
JAVA_FAILURES = {'java.io.IOException', 'java.lang.AssertionError', 'java.lang.IllegalStateException',
    'java.lang.IllegalArgumentException', 'java.lang.SecurityException', 'java.lang.NullPointerException',
    'java.lang.UnsatisfiedLinkError', 'java.lang.RuntimeException', 'java.lang.Exception',
    'java.util.concurrent.CancellationException', 'java.nio.file.FileSystemException',
    'java.nio.file.NoSuchFileException', 'java.nio.file.AccessDeniedException',
    'java.nio.file.FileAlreadyExistsException', 'org.json.JSONException'}
PYTHON_FAILURES = {'BootstrapError', 'SchemaCancelled', 'ContentCancelled', 'UpdateCancelled', 'FileNotFoundError',
    'PermissionError', 'OSError', 'ValueError', 'TypeError', 'RuntimeError', 'Exception', 'JSONDecodeError',
    'KeyError', 'AssertionError', 'OverflowError', 'UnicodeDecodeError', 'TimeoutError', 'ImportError', 'ModuleNotFoundError'}
FAILURE_PHASES = {'fresh-core-sql', 'actual-fourth-schema', 'clean-stop-promotion', 'refuse-active-reinitialization',
    'restart-same-instance', 'second-clean-stop', 'complete'}
LOG_FAMILIES = ('database-operations', 'database-service-operations', 'server-installation-processes')


def _java_sources():
    rows = {}
    for name in ('ServerInstallationSetup', 'ServerDatabaseSetup', 'ServerDatabaseService', 'GuestHelperAssets',
            'ProotProcess', 'NativeProcessBridge', 'ServerSourceSelection'):
        rows[NAMESPACE + '.runtime.' + name] = 'app/src/main/java/io/github/russianranger/esteria/runtime/' + name + '.java'
    for name in ('ServerInstallationX64Test', 'InstallationX64Inputs', 'InstallationX64Lifetime'):
        rows[NAMESPACE + '.runtime.' + name] = 'app/src/androidTest/java/io/github/russianranger/esteria/runtime/' + name + '.java'
    for family, names in (('install', ('FreshServerInstallations', 'RuntimeInstaller', 'RuntimeFiles', 'RuntimeWork')),
            ('process', ('OwnedProcess', 'ProotLaunch'))):
        for name in names:
            rows[NAMESPACE + '.core.runtime.' + family + '.' + name] = 'core/src/main/java/io/github/russianranger/esteria/core/runtime/' + family + '/' + name + '.java'
    for name in ('ExclusiveFileLease', 'ServiceOperationGuard'):
        rows[NAMESPACE + '.core.runtime.' + name] = 'core/src/main/java/io/github/russianranger/esteria/core/runtime/' + name + '.java'
    return rows


def _source_lines(name):
    path = ROOT / name
    return len(path.read_bytes().splitlines()) if path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 << 10 else 0


def java_failure_locations(raw):
    """Keep known exception classes and source-owned locations, never messages."""
    require(type(raw) is str and len(raw.encode()) <= 256 << 10, 'installation-private-java-output-bound')
    kinds = set(); frames = []; sources = _java_sources()
    for line in raw.splitlines():
        for prefix in ('INSTRUMENTATION_STATUS: stack=', 'INSTRUMENTATION_RESULT: shortMsg=', 'Caused by: ', 'Suppressed: '):
            if line.startswith(prefix): line = line[len(prefix):]
        kind = re.match(r'^([A-Za-z_][A-Za-z0-9_.]*)(?::|$)', line)
        if kind and kind[1] in JAVA_FAILURES: kinds.add(kind[1])
        frame = re.fullmatch(r'\s*at ([A-Za-z0-9_.$]+)\.[A-Za-z0-9_$<>]+\(([A-Za-z0-9_$]+\.java):([0-9]{1,5})\)\s*', line)
        if frame:
            outer = frame[1].split('$', 1)[0]; source = sources.get(outer)
            if source and Path(source).name == frame[2] and 0 < int(frame[3]) <= _source_lines(source):
                row = dict(className=outer, file=Path(source).name, line=int(frame[3]))
                if row not in frames and len(frames) < 32: frames.append(row)
    return dict(exceptionTypes=sorted(kinds), sourceFrames=frames)


def failed_app_receipt(raw, revision, provider_pin):
    """Select only fixed identity/phase/class fields from a private failed result."""
    require(type(raw) is str and len(raw.encode()) <= 128 << 10, 'installation-private-failed-receipt-bound')
    value = _json(raw)
    require(type(value) is dict and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
        value.get('scope') == APP_SCOPE and value.get('sourceRevision') == revision and
        value.get('providerSha256') == provider_pin['sha256'] and type(value.get('api')) is int and value['api'] == 33 and
        value.get('abi') == 'x86_64' and type(value.get('phase')) is str and value['phase'] in FAILURE_PHASES and
        type(value.get('qualificationSucceeded')) is bool and all(value.get(name) is False for name in FALSE_FLAGS),
        'installation-private-failed-receipt-identity')
    result = dict(sourceRevision=revision, providerSha256=provider_pin['sha256'], phase=value['phase'], qualificationSucceeded=False)
    allowed = {name.rsplit('.', 1)[-1] for name in JAVA_FAILURES}
    for name in ('failureType', 'cleanupFailureType'):
        if name in value:
            require(type(value[name]) is str and value[name] in allowed, 'installation-private-failure-class-refused')
            result[name] = value[name]
    return result


def guest_failure_locations(raw):
    """Parse only known Python modules/functions, exception classes and errno."""
    require(type(raw) is str and len(raw.encode()) <= 64 << 10, 'installation-private-guest-log-bound')
    modules = {name: 'runtime/' + name for name in provider.HELPERS if name.endswith('.py')}
    modules['android_database_setup.py'] = 'runtime/android_database_setup.py'
    modules['installation_x64_entry.py'] = 'tests/android-installation-x64/installation_x64_entry.py'
    functions = set()
    for source in modules.values():
        if _source_lines(source):
            functions.update(node.name for node in ast.walk(ast.parse((ROOT / source).read_bytes()))
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
    kinds = set(); frames = []; helpers = []; errnos = set()
    for line in raw.splitlines():
        exception = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)(?::|$)', line)
        if exception and exception[1] in PYTHON_FAILURES: kinds.add(exception[1])
        frame = re.fullmatch(r'\s*File "/work/(?:helpers|service-helpers|installation-helpers)/[a-f0-9]{64}/([A-Za-z_][A-Za-z0-9_]*\.py)", line ([0-9]{1,5}), in [A-Za-z_][A-Za-z0-9_]*\s*', line)
        if frame and frame[1] in modules and 0 < int(frame[2]) <= _source_lines(modules[frame[1]]):
            row = dict(module=frame[1], line=int(frame[2]))
            if row not in frames and len(frames) < 32: frames.append(row)
        failure = re.fullmatch(r'(Database setup|Local database service|Owned installation|Debug x64 installation) failed \(([A-Za-z_][A-Za-z0-9_]*)([^\n]*)\);[^\n]*', line)
        if failure and failure[2] in PYTHON_FAILURES:
            kinds.add(failure[2])
            # Only the setup entry emits this source-defined structural detail.
            if failure[1] == 'Database setup':
                detail = re.fullmatch(r'(?:; errno=([0-9]{1,4}))?(?:; helperFrames=([A-Za-z0-9_:,]+))?', failure[3])
                if detail:
                    if detail[1] and int(detail[1]) <= 4095: errnos.add(int(detail[1]))
                    for item in (detail[2] or '').split(','):
                        parsed = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*):([0-9]{1,5})', item)
                        if parsed and parsed[1] in functions and 0 < int(parsed[2]) <= max(_source_lines(name) for name in modules.values()):
                            row = dict(function=parsed[1], line=int(parsed[2]))
                            if row not in helpers and len(helpers) < 16: helpers.append(row)
    return dict(exceptionTypes=sorted(kinds), sourceFrames=frames, helperFrames=helpers, errno=sorted(errnos))


def failure_diagnostics(command, instrumentation, revision, provider_pin):
    """Best-effort fixed reads; no diagnostic failure grants qualification."""
    deadline = time.monotonic() + 45
    def read(label, words):
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise TimeoutError('Diagnostic budget exhausted')
        return command(label, words, timeout=min(15, remaining))
    result = dict(formatVersion=1, scope='sanitized-owned-installation-failure-locations-only',
        java=java_failure_locations(instrumentation), guest=[], qualificationSucceeded=False)
    try:
        raw = read('failed-app-receipt', ['exec-out', 'run-as', PACKAGE, 'head', '-c', '131073',
            'files/installation-x64-qualification.json'])
        result['appFailure'] = failed_app_receipt(raw, revision, provider_pin)
    except Exception: result['failedAppReceiptUnavailable'] = True
    for family_index, family in enumerate(LOG_FAMILIES):
        if time.monotonic() >= deadline:
            result['diagnosticBudgetExhausted'] = True; break
        try:
            raw = read('guest-inventory-' + str(family_index), ['exec-out', 'run-as', PACKAGE, 'find',
                'files/state/' + family, '-mindepth', '3', '-maxdepth', '3', '-type', 'f'])
            pattern = re.compile(r'files/state/' + re.escape(family) + r'/[a-f0-9]{32}/logs/(stdout|stderr)\.log')
            candidates = sorted({line for line in raw.splitlines() if pattern.fullmatch(line)})[:4]
            for index, path in enumerate(candidates):
                if time.monotonic() >= deadline:
                    result['diagnosticBudgetExhausted'] = True; break
                try:
                    raw = read('guest-read-' + str(family_index) + '-' + str(index),
                        ['exec-out', 'run-as', PACKAGE, 'head', '-c', '65536', path])
                    parsed = guest_failure_locations(raw)
                    result['guest'].append(dict(role=family, stream=pattern.fullmatch(path)[1], **parsed))
                except Exception: result['guestLogUnavailable'] = True
        except Exception: result['guestInventoryUnavailable'] = True
    return result


def _identity(path, maximum=4 << 30):
    row = provider.files.identity(Path(path)); require(0 < row['bytes'] <= maximum, 'installation-qualification-file-bound')
    return row


def _json(raw): return json.loads(raw, object_pairs_hook=gate._unique)


def source_snapshot(revision, archive, *, root=ROOT):
    """Verify every current tracked byte and the exact canonical full Git export."""
    require(type(revision) is str and re.fullmatch('[a-f0-9]{40}', revision), 'installation-activation-full-revision-required')
    root = Path(root); environment = dict(os.environ, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1',
        GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')
    command = ['git', '-C', str(root)]
    def git(*words):
        return subprocess.check_output([*command, *words], env=environment, stderr=subprocess.DEVNULL, timeout=30)
    require(git('rev-parse', 'HEAD').decode().strip() == revision, 'installation-activation-head-differs')
    for words in (('diff', '--exit-code', '--quiet'), ('diff', '--cached', '--exit-code', '--quiet')):
        require(subprocess.run([*command, *words], env=environment, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL).returncode == 0, 'installation-activation-source-dirty')
    require(not git('ls-files', '--others', '--exclude-standard', '-z'), 'installation-activation-untracked-source')
    rows = {}; total = 0; conversions = []
    for record in git('ls-tree', '-rz', '--full-tree', revision).split(b'\0'):
        if not record: continue
        header, name = record.split(b'\t', 1); mode, kind, blob = header.decode().split(' '); name = name.decode('utf-8')
        provider.engine.content.safe_path(name)
        require(kind == 'blob' and mode in ('100644', '100755') and name not in rows,
            'installation-activation-complete-source-tree-required')
        path = root / name; info = path.lstat(); count = 0; sha256 = hashlib.sha256(); chunks = []
        sha1 = hashlib.sha1(b'blob ' + str(info.st_size).encode() + b'\0')
        require(stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o111) == (mode == '100755') and
            0 <= info.st_size <= 64 << 20, 'installation-activation-source-mode-or-bound')
        with provider.files.plain_file(path) as stream:
            before = os.fstat(stream.fileno())
            for block in iter(lambda: stream.read(128 << 10), b''):
                count += len(block); require(count <= info.st_size, 'installation-activation-source-grew')
                sha1.update(block); sha256.update(block)
                if name == 'gradlew.bat' and info.st_size <= 128 << 10: chunks.append(block)
            after = os.fstat(stream.fileno())
        stamp = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        require(stamp(info) == stamp(before) == stamp(after) == stamp(path.lstat()),
            'installation-activation-source-changed')
        require(count == info.st_size, 'installation-activation-source-differs-from-git-blob')
        identity = dict(bytes=count, sha256=sha256.hexdigest())
        if sha1.hexdigest() != blob:
            require(name == 'gradlew.bat' and info.st_size <= 128 << 10 and mode == '100644',
                'installation-activation-source-differs-from-git-blob')
            canonical = git('cat-file', 'blob', revision + ':gradlew.bat')
            attributes = git('cat-file', 'blob', revision + ':.gitattributes')
            require(len(canonical) <= 64 << 10 and b'\r' not in canonical and
                b'*.bat text eol=crlf' in attributes.splitlines() and b''.join(chunks) == canonical.replace(b'\n', b'\r\n') and
                hashlib.sha1(b'blob ' + str(len(canonical)).encode() + b'\0' + canonical).hexdigest() == blob,
                'installation-activation-undeclared-checkout-conversion')
            checkout = identity; identity = provider.identity_bytes(canonical)
            conversions.append(dict(path=name, conversion='declared-lf-to-crlf', canonical=identity, checkout=checkout))
        rows[name] = dict(identity, gitBlob=blob, mode=mode)
        total += identity['bytes']; require(len(rows) <= 100000 and total <= 256 << 20, 'installation-activation-source-total-bound')
    require(rows, 'installation-activation-empty-source-refused')
    archive_identity = _identity(archive, 128 << 20)
    with tempfile.TemporaryFile() as errors:
        child = subprocess.Popen([*command, 'archive', '--format=tar.gz', revision], env=environment,
            stdout=subprocess.PIPE, stderr=errors)
        digest = hashlib.sha256(); size = 0
        try:
            for block in iter(lambda: child.stdout.read(128 << 10), b''):
                size += len(block); require(size <= 128 << 20, 'installation-activation-export-bound'); digest.update(block)
            require(child.wait(timeout=30) == 0, 'installation-activation-export-failed')
        finally:
            child.stdout.close()
            if child.poll() is None: child.kill(); child.wait()
    require(dict(bytes=size, sha256=digest.hexdigest()) == archive_identity,
        'installation-activation-full-canonical-source-export-differs')
    return dict(formatVersion=1, scope='exact-current-android-installation-activation-source-only', sourceRevision=revision,
        sourceArchive=archive_identity, sourceFiles=len(rows), sourceFileBytes=total,
        sourceInputs=rows, validatedCheckoutConversions=conversions, allCanonicalSourceBytesMatchExactGitBlobs=True,
        allWorkingSourceBytesVerified=True, entireCommittedSourceExportVerified=True,
        androidCoordinatorExecuted=False, **{name: False for name in FALSE_FLAGS})


def _inputs(selected_provider, mysql_provider, proot_provider, frozen_source):
    selected = gate.load_pin(require_enabled=True)
    # Transport authority is separate from both native SQL and the descriptor.
    from tools import android_installation_x64_provider_artifacts as artifacts
    artifacts.load_pin(require_enabled=True)
    descriptor = provider.verify(Path(selected_provider), selected['provider'])
    readback = provider.readback(Path(selected_provider).parent); gate._provider_readback(readback, selected)
    provider.verify_external(Path(selected_provider), Path(frozen_source), Path(mysql_provider), Path(proot_provider))
    native = gate.record(selected['nativeSql']['qualification'])
    return selected, descriptor, native


def _manifest(raw, *, testing=False):
    nodes = manifest.manifest_nodes(raw)
    roots = [row for row in nodes if row['name'] == 'manifest' and not row['parents']]
    require(len(roots) == 1 and roots[0]['attributes'].get((None, 'package')) == PACKAGE + ('.test' if testing else ''),
        'installation-apk-default-package-required')
    applications = [row for row in nodes if row['name'] == 'application' and row['parents'] == ('manifest',)]
    require(len(applications) == 1 and applications[0]['attributes'].get((manifest.ANDROID, 'debuggable')) is True,
        'installation-apk-debug-required')
    sdk = [row for row in nodes if row['name'] == 'uses-sdk' and row['parents'] == ('manifest',)]
    require(len(sdk) == 1 and type(sdk[0]['attributes'].get((manifest.ANDROID, 'targetSdkVersion'))) is int and
        sdk[0]['attributes'][(manifest.ANDROID, 'targetSdkVersion')] == 35, 'installation-apk-target35-required')
    if testing:
        instrumentation = [row for row in nodes if row['name'] == 'instrumentation' and row['parents'] == ('manifest',)]
        require(len(instrumentation) == 1 and instrumentation[0]['attributes'].get((manifest.ANDROID, 'name')) ==
            'androidx.test.runner.AndroidJUnitRunner' and
            instrumentation[0]['attributes'].get((manifest.ANDROID, 'targetPackage')) == PACKAGE,
            'installation-fixed-test-target-required')


def verify_apks(apk, test_apk, selected_provider, mysql_provider, proot_provider, descriptor, revision):
    """Stream every selected APK asset; inspect actual manifests and JNI ELFs."""
    expected = {'assets/installation-probe/provider.json': Path(selected_provider) / provider.PREFIX / 'provider.json'}
    expected.update({name: Path(selected_provider) / name for name in descriptor['packagedFiles']})
    for path in provider.files.installed_files(Path(mysql_provider)):
        name = path.relative_to(mysql_provider).as_posix(); require(name.startswith('assets/mysql-probe/'), 'installation-mysql-provider-namespace')
        expected[name] = path
    for path in provider.files.installed_files(Path(proot_provider)):
        name = path.relative_to(proot_provider).as_posix().replace('jniLibs/', 'lib/', 1)
        require(name.startswith(('assets/proot-probe/', 'lib/x86_64/')), 'installation-proot-provider-namespace')
        expected[name] = path
    selected_prefixes = ('assets/installation-probe/', 'assets/installation-probe-helpers/', 'assets/mysql-probe/', 'assets/proot-probe/')
    jni = {'lib/x86_64/libesteria_process.so', 'lib/x86_64/libesteria_probe_process.so'}
    artifact = _identity(apk); testing = _identity(test_apk, 64 << 20)
    with provider.files.plain_file(apk) as incoming, zips.checked_zip(incoming, required=expected,
            maximum_bytes=4 << 30, maximum_entries=20000, maximum_directory=8 << 20) as archive:
        names = archive.namelist()
        require({name for name in names if name.startswith(selected_prefixes) and not name.endswith('/')} ==
            {name for name in expected if name.startswith('assets/')}, 'installation-apk-fixed-asset-closure')
        require({name for name in names if name.startswith('lib/') and not name.endswith('/')} ==
            {name for name in expected if name.startswith('lib/')} | jni, 'installation-apk-fixed-native-closure')
        require(not any(name.startswith(('assets/client-runtime/', 'assets/wine-probe/', 'assets/server-runtime/',
            'assets/server-programs/', 'assets/server-content/', 'assets/guest-bridges/')) for name in names),
            'installation-apk-production-runtime-mixed-with-fixture')
        for name, path in expected.items():
            wanted = _identity(path); item = archive.getinfo(name)
            require(item.file_size == wanted['bytes'], 'installation-apk-asset-size-differs')
            if name.endswith('.archive'): require(item.compress_type == 0, 'installation-apk-archives-must-be-stored')
            with archive.open(item) as stream:
                require(provider.native.archives.hash_stream(stream, item.file_size) == wanted['sha256'],
                    'installation-apk-asset-bytes-differ')
        for name in jni:
            item = archive.getinfo(name); require(64 <= item.file_size <= 16 << 20, 'installation-apk-owner-bound')
            provider.mysql.retained.verify.proot.elf(archive.read(item), 'owner')
        item = archive.getinfo('AndroidManifest.xml'); require(item.file_size <= 1 << 20, 'installation-apk-manifest-bound')
        _manifest(archive.read(item))
        dex = [archive.getinfo(name) for name in names if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)]
        require(0 < len(dex) <= 16 and all(item.file_size <= 32 << 20 for item in dex), 'installation-apk-dex-bound')
        contents = [archive.read(item) for item in dex]
        for token in (revision.encode(), _identity(expected['assets/installation-probe/provider.json'])['sha256'].encode(),
                b'Lio/github/russianranger/esteria/runtime/ServerInstallationSetup$Handle;'):
            require(any(token in raw for raw in contents), 'installation-apk-current-compiled-selection-required')
        for directory, helpers in HELPERS.items():
            row = archive.getinfo('assets/' + directory + '/manifest.json'); require(row.file_size <= 16384, 'installation-database-helper-manifest-bound')
            proof = _json(archive.read(row)); require(proof == dict(formatVersion=1,
                files={name: _identity(ROOT / 'runtime' / name, 128 << 10) for name in helpers}),
                'installation-database-helper-current-source-differs')
            for name, wanted in proof['files'].items():
                item = archive.getinfo('assets/' + directory + '/' + name)
                require(item.file_size == wanted['bytes'] and item.file_size <= 128 << 10 and
                    archive.read(item) == (ROOT / 'runtime' / name).read_bytes(), 'installation-database-helper-apk-differs')
    with provider.files.plain_file(test_apk) as incoming, zips.checked_zip(incoming, required=('AndroidManifest.xml',),
            maximum_bytes=64 << 20, maximum_entries=10000) as archive:
        names = archive.namelist(); require(not any(name.startswith('lib/') or name.endswith(('.archive', '.so', '.exe', '.dll')) for name in names),
            'installation-test-apk-runtime-payload-refused')
        item = archive.getinfo('AndroidManifest.xml'); require(item.file_size <= 1 << 20, 'installation-test-manifest-bound')
        _manifest(archive.read(item), testing=True)
        dex = [archive.getinfo(name) for name in names if re.fullmatch(r'classes(?:[2-9]|[1-9][0-9]+)?\.dex', name)]
        require(0 < len(dex) <= 16 and all(item.file_size <= 32 << 20 for item in dex), 'installation-test-dex-bound')
        marker = ('L' + TEST_CLASS.replace('.', '/') + ';').encode()
        require(any(marker in archive.read(item) for item in dex), 'installation-exact-coordinator-test-class-required')
    require(_identity(apk) == artifact and _identity(test_apk, 64 << 20) == testing, 'installation-apk-changed-during-verification')
    return dict(apk=artifact, testApk=testing,
        compiledProviderSha256=_identity(expected['assets/installation-probe/provider.json'])['sha256'],
        defaultPackageVerified=True, fixedTestClassVerified=True, exactSelectedAssetsVerified=True,
        currentDatabaseHelperBytesVerified=True, targetSdk=35, apkBuiltForActivationRevision=revision)


def validate_receipt(value, revision, descriptor, native, mysql, programs, provider_pin):
    keys = {'formatVersion', 'scope', 'sourceRevision', 'providerSha256', 'api', 'abi', 'phase', 'mysqlUuid', 'mysqlVersion',
        'runtimeArchiveSha256', 'programsArchiveSha256', 'contentReceiptSha256', 'sourceLockSha256',
        'playerbotsTableCount', 'playerbotsUpdateCount', *POSITIVE, *FALSE_FLAGS}
    require(type(value) is dict and set(value) == keys and type(value.get('formatVersion')) is int and value['formatVersion'] == 1 and
        value.get('scope') == APP_SCOPE and value.get('sourceRevision') == revision and value.get('phase') == 'complete' and
        type(value.get('api')) is int and value['api'] == 33 and value.get('abi') == 'x86_64' and
        value.get('providerSha256') == provider_pin['sha256'], 'installation-android-receipt-identity-differs')
    require(all(value.get(name) is True for name in POSITIVE), 'installation-android-required-lifecycle-incomplete')
    require(all(value.get(name) is False for name in FALSE_FLAGS), 'installation-android-runtime-overclaim')
    require(value.get('mysqlVersion') == native['mysqlVersion'] == descriptor['mysqlVersion'] and
        value.get('runtimeArchiveSha256') == mysql['archive']['sha256'] and
        value.get('contentReceiptSha256') == native['contentReceipt']['sha256'] and
        value.get('sourceLockSha256') == native['sourceLockSha256'], 'installation-android-runtime-content-binding-differs')
    require(value.get('programsArchiveSha256') == programs['archive']['sha256'], 'installation-android-programs-selection-differs')
    uuid = value.get('mysqlUuid')
    require(type(uuid) is str and re.fullmatch('[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}', uuid) and uuid != native['mysqlUuid'],
        'installation-new-android-sql-instance-required')
    for name, field in (('playerbotsTableCount', 'tableCount'), ('playerbotsUpdateCount', 'updateCount')):
        require(type(value.get(name)) is int and value[name] > 0 and
            type(native['databaseSnapshot'][field]) is int and value[name] == native['databaseSnapshot'][field],
            'installation-android-real-schema-count-differs')
    return value


def qualify(apk, test_apk, selected_provider, mysql_provider, proot_provider, frozen_source, revision, source_archive, output, adb='adb'):
    selected, descriptor, native = _inputs(selected_provider, mysql_provider, proot_provider, frozen_source)
    require(descriptor['currentPackagingRecipe']['commit'] != revision, 'installation-provider-measurement-and-activation-revisions-must-be-distinct')
    source = source_snapshot(revision, source_archive)
    verified = verify_apks(apk, test_apk, selected_provider, mysql_provider, proot_provider, descriptor, revision)
    mysql = gate.small(Path(mysql_provider) / 'assets/mysql-probe/provider.json', 128 << 10)
    programs = gate.small(Path(selected_provider) / provider.PREFIX / 'programs.json', 2 << 20)
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    (output / 'source-companion.json').write_text(json.dumps(source, sort_keys=True, indent=2) + '\n')
    report = dict(formatVersion=1, scope=SCOPE, sourceRevision=revision, providerMeasurementRevision=descriptor['currentPackagingRecipe']['commit'],
        providerDescriptor=selected['provider'], nativeSqlReceipt=descriptor['nativeSqlReceipt'],
        nativeInputSelection=descriptor['nativeInputSelection'], activationSource=source, artifacts=verified,
        androidX64CoordinatorQualified=False, historicalJavaServiceEvidenceAppliesToCurrentCaller=False,
        **{name: False for name in FALSE_FLAGS})
    attempted_install = False; failure = None; phase = 'emulator-admission'; summaries = []; instrumentation = ''
    def command(label, words, timeout=180, allow_failure=False):
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix='esteria-installation-private-adb-') as temporary:
            code, raw = run_bounded([adb, *words], Path(temporary) / 'output', timeout, limit=256 << 10)
        summaries.append(dict(role=label, exitCode=code, elapsedMilliseconds=int((time.monotonic()-started)*1000)))
        require(code == 0 or allow_failure, 'installation-android-command-failed-' + label)
        return raw
    try:
        require(re.fullmatch('emulator-[0-9]+', command('serial', ['get-serialno']).strip()), 'installation-physical-or-remote-device-refused')
        properties = {name: command(name, ['shell', 'getprop', name]).strip() for name in
            ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi', 'ro.build.fingerprint')}
        require(tuple(properties[name] for name in ('ro.kernel.qemu', 'ro.build.version.sdk', 'ro.product.cpu.abi')) == ('1', '33', 'x86_64') and
            0 < len(properties['ro.build.fingerprint']) <= 2048 and all(32 <= ord(character) < 127 for character in properties['ro.build.fingerprint']),
            'installation-disposable-android13-x64-required')
        report['emulatorProperties'] = properties
        for label, package in (('app', PACKAGE), ('tests', PACKAGE + '.test')):
            require('package:' not in command('preexisting-' + label, ['shell', 'pm', 'path', package], allow_failure=True),
                'installation-preexisting-package-refused')
        phase = 'install-current-activation'; attempted_install = True
        command('install-app', ['install', str(apk)]); command('install-tests', ['install', str(test_apk)])
        phase = 'actual-four-schema-coordinator'
        instrumentation = command('instrument', ['shell', 'am', 'instrument', '-w', '-r', '-e', 'class', TEST,
            PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner'], timeout=3600, allow_failure=True)
        if summaries[-1]['exitCode'] != 0 or not instrument_passed(instrumentation):
            try: report['failureDiagnostics'] = failure_diagnostics(command, instrumentation, revision, selected['provider'])
            except Exception: report['diagnosticUnavailable'] = True
            raise ValueError('installation-coordinator-instrumentation-did-not-pass')
        phase = 'private-receipt-validation'
        raw = command('receipt', ['exec-out', 'run-as', PACKAGE, 'cat', 'files/installation-x64-qualification.json'])
        require(len(raw.encode()) <= 128 << 10, 'installation-android-receipt-bound')
        value = validate_receipt(_json(raw), revision, descriptor, native, mysql, programs, selected['provider'])
        report['appEvidence'] = value; report['actualInstrumentationPassed'] = True
        require(source_snapshot(revision, source_archive) == source, 'installation-activation-source-changed-during-execution')
        require(provider.verify(Path(selected_provider), selected['provider']) == descriptor, 'installation-selected-provider-changed-during-execution')
        phase = 'complete'; report['androidX64CoordinatorQualified'] = True
    except Exception as error:
        failure = error; report['failureType'] = type(error).__name__
        if phase in ('actual-four-schema-coordinator', 'private-receipt-validation') and 'failureDiagnostics' not in report:
            try: report['failureDiagnostics'] = failure_diagnostics(command, instrumentation, revision, selected['provider'])
            except Exception: report['diagnosticUnavailable'] = True
    finally:
        if attempted_install:
            try: command('stop-owned-fixture', ['shell', 'am', 'force-stop', PACKAGE])
            except Exception as error:
                report['androidX64CoordinatorQualified'] = False; report['cleanupFailureType'] = type(error).__name__; failure = failure or error
        report.update(phase=phase, commandResults=summaries, completedAtUnix=int(time.time()))
        (output / 'qualification.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n')
    if failure is not None: raise ValueError('Android installation qualification failed; sanitized receipt retained') from None
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--adb', default='adb')
    for name in ('apk', 'test-apk', 'provider', 'mysql-provider', 'proot-provider', 'frozen-source', 'source-archive', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--source-revision', required=True); args = parser.parse_args()
    result = qualify(args.apk, args.test_apk, args.provider, args.mysql_provider, args.proot_provider,
        args.frozen_source, args.source_revision, args.source_archive, args.output, args.adb)
    print(json.dumps({name: result[name] for name in ('scope', 'sourceRevision', 'androidX64CoordinatorQualified',
        'productionArm64ProviderQualified', 'thorQualified', 'gameplayQualified')}, sort_keys=True))


if __name__ == '__main__': main()
