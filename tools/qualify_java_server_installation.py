#!/usr/bin/env python3
"""Build and run the real Java installation coordinator with native PRoot/SQL.

The only Java replacements are Android filesystem/asset facades and the Linux
PRoot payload locator. Production installer, transaction, process and SQL code
remain unchanged. A compiled harness is not an executed SQL qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prepare_runtime as archives, verify_server_build as files
from tools import provider_playerbots_programs as programs, provider_server_content as content
from tools import provider_server_runtime as dependencies

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests/native-java-installation'
JSON_COMMIT = 'f9b5587c87aaf02e4a5ed1991d48d6c05993624a'
JSON_REPOSITORY = 'https://github.com/stleary/JSON-java.git'
APP_CLASSES = ('ServerRuntimeSetup', 'ServerProgramsSetup', 'ServerContentSetup', 'ServerSourceSelection',
    'GuestHelperAssets', 'ServerDatabaseSetup', 'ServerDatabaseService', 'ServerInstallationSetup',
    'ProotProcess', 'NativeProcessBridge')
require = files.require


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def new_directory(path):
    path = Path(os.path.abspath(path)); archives.directory(path.parent, create=True)
    require(not os.path.lexists(path), 'existing-java-installation-qualification-output-preserved')
    path.mkdir(mode=0o700)
    return path


def write(path, value):
    with path.open('xb') as output:
        output.write(value); output.flush(); os.fsync(output.fileno())


def copy(source, target):
    expected = files.identity(source); target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with files.plain_file(source) as incoming, target.open('xb') as outgoing:
        require(archives.hash_stream(incoming, expected['bytes'], outgoing) == expected['sha256'],
            'java-installation-asset-copy-changed')
    require(files.identity(target) == expected, 'java-installation-asset-copy-readback-differs')


def helper_assets(output, script, variable, prefix, special=None):
    text = (ROOT / script).read_text()
    match = re.search(r'def ' + re.escape(variable) + r' = \[(.*?)\]', text, re.S)
    require(match is not None, 'java-installation-helper-gradle-list-absent')
    names = re.findall(r"'([^']+)'", match.group(1))
    require(0 < len(names) <= 32 and len(names) == len(set(names)), 'java-installation-helper-list-bound')
    selected = {name: ROOT / 'runtime' / name for name in names}
    if special:
        require(special[0] not in selected, 'java-installation-helper-special-collision')
        selected[special[0]] = ROOT / special[1]
    records = {}
    for name, source in sorted(selected.items()):
        row = files.identity(source); require(0 < row['bytes'] <= 131072, 'java-installation-helper-size')
        copy(source, output / prefix / name); records[name] = row
    write(output / prefix / 'manifest.json', (json.dumps(dict(formatVersion=1, files=records),
        separators=(',', ':')) + '\n').encode())
    return records


def prepare(dependency_provider, programs_provider, content_provider, output):
    roots = [archives.directory(Path(os.path.abspath(path))) for path in
        (dependency_provider, programs_provider, content_provider)]
    verified = dict(dependencies=dependencies.verify(roots[0]), programs=programs.verify(roots[1]),
        content=content.verify(roots[2]))
    output = new_directory(output)
    require(all(output not in root.parents and root not in output.parents and root != output for root in roots),
        'java-installation-input-output-overlap')
    assets = output / 'assets'; assets.mkdir(mode=0o700)
    for provider, prefix in zip(roots, ('server-runtime', 'server-programs', 'server-content')):
        source = provider / 'assets' / prefix
        for path in sorted(source.iterdir()):
            require(path.is_file() and not path.is_symlink(), 'java-installation-provider-assets-must-be-flat-plain-files')
            copy(path, assets / prefix / path.name)
    copy(ROOT / 'sources.lock.json', assets / 'sources.lock.json')
    helpers = {}
    for script, variable, prefix, special in (
            ('app/database-setup.gradle', 'databaseHelpers', 'database-setup', None),
            ('app/database-service.gradle', 'serviceHelpers', 'database-service', None),
            ('app/server-installation.gradle', 'installationHelpers', 'server-installation', ('local-server.json', 'config/local-server.json'))):
        helpers[prefix] = helper_assets(assets, script, variable, prefix, special)
    copy(FIXTURES / 'restart_probe.py', assets / 'qualification/restart_probe.py')
    proof = dict(formatVersion=1, scope='exact-native-java-installation-assets', providerVerification=verified,
        sourceLock=files.identity(ROOT / 'sources.lock.json'), helpers=helpers,
        qualificationSqlProbe=files.identity(FIXTURES / 'restart_probe.py'),
        javaCoordinatorExecuted=False, sqlExecuted=False, slotPromoted=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    write(output / 'preparation.json', encode(proof))
    return proof


def command(arguments, log, *, timeout=120):
    subprocess.run([str(part) for part in arguments], cwd=ROOT, check=True, timeout=timeout, stdout=log, stderr=log)


def build(json_source, java_home, output):
    json_source, java_home = (archives.directory(Path(os.path.abspath(path))) for path in (json_source, java_home))
    sha = subprocess.check_output(['git', '-C', str(json_source), 'rev-parse', 'HEAD'], text=True).strip()
    require(sha == JSON_COMMIT and not subprocess.check_output(['git', '-C', str(json_source),
        'status', '--porcelain', '--untracked-files=all'], text=True).strip(), 'exact-clean-pinned-json-java-source-required')
    output = new_directory(output); classes = output / 'classes'; classes.mkdir(); native = output / 'native'; native.mkdir()
    generated = output / 'generated/io/github/russianranger/esteria'; generated.mkdir(parents=True)
    selected = json.loads(programs.LOCK.read_bytes()); stock = programs.stock.load_pin(sealed=True)
    fields = dict(SOURCE_REVISION=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        SERVER_PROGRAMS_PIN=files.identity(programs.LOCK)['sha256'], SERVER_PROGRAMS_STOCK_PIN=files.identity(programs.stock.LOCK)['sha256'],
        SERVER_PROGRAMS_STOCK_ARCHIVE_SHA256=stock['archive']['sha256'], SERVER_PROGRAMS_REVISION=selected['serverRevision'],
        SERVER_CONTENT_PIN=files.identity(content.LOCK)['sha256'])
    require(re.fullmatch('[a-f0-9]{40}', fields['SOURCE_REVISION']), 'java-installation-source-revision-required')
    text = 'package io.github.russianranger.esteria;\npublic final class BuildConfig {\n'
    text += 'public static final boolean DEBUG=false,SERVER_INSTALLATION_PROBE_PACKAGED=false;\n'
    text += 'public static final String SERVER_INSTALLATION_PROBE_PIN="";\n'
    text += 'public static final boolean SERVER_PROGRAMS_PACKAGED=true,SERVER_CONTENT_PACKAGED=true;\n'
    for name, value in fields.items():
        require(re.fullmatch('[a-f0-9]{40}|[a-f0-9]{64}', value), 'java-installation-build-constant-format')
        text += 'public static final String ' + name + '=' + json.dumps(value) + ';\n'
    text += 'public static final long SERVER_PROGRAMS_STOCK_ARCHIVE_BYTES=' + str(stock['archive']['bytes']) + 'L;\n}\n'
    build_config = generated / 'BuildConfig.java'; write(build_config, text.encode())
    core = sorted((ROOT / 'core/src/main/java').rglob('*.java'))
    production = [ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime' / (name + '.java') for name in APP_CLASSES]
    fixtures = sorted((FIXTURES / 'src').rglob('*.java'))
    json_java = sorted((json_source / 'src/main/java/org/json').glob('*.java'))
    require(10 <= len(json_java) <= 100 and all(path.is_file() and not path.is_symlink() for path in json_java),
        'pinned-real-json-java-source-closure-required')
    native_sources = [ROOT / 'native/process-owner' / name for name in ('process_owner.cpp', 'process_usage.cpp', 'jni_bridge.cpp')]
    native_inputs = native_sources + [ROOT / 'native/process-owner' / name for name in ('process_owner.h', 'process_usage.h')]
    inputs = {str(path.relative_to(ROOT)): files.identity(path) for path in core + production + fixtures + native_inputs}
    with (output / 'build.log').open('xb') as log:
        command([java_home / 'bin/javac', '-encoding', 'UTF-8', '-d', classes, *core, *production, *fixtures, *json_java, build_config], log)
        command(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', '-pthread', '-fvisibility=hidden',
            '-Wl,-z,noexecstack', '-I' + str(java_home / 'include'), '-I' + str(java_home / 'include/linux'),
            *native_sources, '-o', native / 'libesteria_process.so'], log)
    require(inputs == {str(path.relative_to(ROOT)): files.identity(path) for path in core + production + fixtures + native_inputs},
        'java-installation-source-changed-during-compilation')
    proof = dict(formatVersion=1, scope='compiled-native-java-installation-coordinator-harness',
        integrationRevision=fields['SOURCE_REVISION'], productionFiles=inputs, javaBuildConfig=fields,
        jsonJava=dict(repository=JSON_REPOSITORY, revision=JSON_COMMIT,
            files={str(path.relative_to(json_source)): files.identity(path) for path in json_java},
            license=files.identity(json_source / 'LICENSE')),
        nativeJniLibrary=files.identity(native / 'libesteria_process.so'), hostMachine=os.uname().machine,
        classFiles={str(path.relative_to(classes)): files.identity(path) for path in sorted(classes.rglob('*.class'))},
        replacedAndroidClasses=['android.content.Context', 'android.content.pm.ApplicationInfo', 'android.content.res.AssetManager',
            'android.content.res.AssetFileDescriptor', 'io.github.russianranger.esteria.runtime.InstalledProot'],
        productionProotProcessCompiled=True, productionCoordinatorCompiled=True,
        javaCoordinatorExecuted=False, sqlExecuted=False, slotPromoted=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    write(output / 'build-receipt.json', encode(proof))
    return proof


def run(build_directory, assets, proot, java_home, private_root, output, private_log):
    require(sys.platform == 'linux' and os.uname().machine == 'aarch64', 'native-arm64-java-installation-execution-required')
    build_directory, assets, proot, java_home = (archives.directory(Path(os.path.abspath(path))) for path in
        (build_directory, assets, proot, java_home))
    proof, _ = programs.modules.read_json(build_directory / 'build-receipt.json', limit=2 << 20)
    require(proof.get('scope') == 'compiled-native-java-installation-coordinator-harness' and
        proof.get('hostMachine') == 'aarch64' and proof.get('productionCoordinatorCompiled') is True and
        proof.get('productionProotProcessCompiled') is True and proof.get('sqlExecuted') is False and
        files.identity(build_directory / 'native/libesteria_process.so') == proof['nativeJniLibrary'],
        'native-java-installation-build-receipt-differs')
    classes = build_directory / 'classes'
    require(proof.get('classFiles') and proof['classFiles'] == {str(path.relative_to(classes)): files.identity(path)
        for path in sorted(classes.rglob('*.class'))}, 'native-java-installation-compiled-class-closure-differs')
    for path in (private_root, output, private_log):
        require(path.is_absolute() and path.parent.resolve() == path.parent and not os.path.lexists(path),
            'new-canonical-native-java-installation-execution-path-required')
    with private_log.open('xb') as log:
        command([java_home / 'bin/java', '-Xmx256m', '-Djava.library.path=' + str(build_directory / 'native'),
            '-Desteria.native.proot.dir=' + str(proot), '-Desteria.native.proot.receipt=' + str(proot / 'ownership-evidence.json'),
            '-cp', build_directory / 'classes', 'io.github.russianranger.esteria.runtime.NativeJavaInstallation',
            assets, private_root, output], log, timeout=90 * 60)
    result, _ = programs.modules.read_json(output, limit=128 << 10)
    validate_result(result, proof['integrationRevision'])
    return result


def validate_result(result, revision):
    """Fail closed on incomplete or overstated actual execution receipts."""
    required = ('qualificationSucceeded', 'javaCoordinatorExecuted', 'actualSqlExecuted', 'slotPromoted',
        'productionProotProcessExecuted', 'completedSelectionReadBack', 'activeFreshInitializationRefused',
        'restartedSameLiveSqlUuid', 'actualCoreAccountRealmAndBotSqlPreserved',
        'privateJournalsAndCredentialsPreserved', 'twoCleanDatabaseStopsVerified')
    require(type(result.get('formatVersion')) is int and result['formatVersion'] == 1 and
        result.get('scope') == 'native-arm64-java-owned-installation-promotion-and-restart' and
        result.get('integrationRevision') == revision and result.get('phase') == 'complete' and
        all(result.get(name) is True for name in required) and
        all(result.get(name) is False for name in ('androidRuntimeQualified', 'androidApiExecuted',
            'androidBionicProotLocatorExecuted', 'worldserverExecuted', 'authserverExecuted', 'serverDataQualified',
            'characterPersistenceQualified', 'playerbotsAiQualified', 'gameplayQualified')),
        'actual-native-java-installation-result-incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest='operation', required=True)
    prepare_parser = sub.add_parser('prepare')
    for name in ('dependency-provider', 'programs-provider', 'content-provider', 'output'):
        prepare_parser.add_argument('--' + name, type=Path, required=True)
    compile_parser = sub.add_parser('build')
    for name in ('json-source', 'java-home', 'output'):
        compile_parser.add_argument('--' + name, type=Path, required=True)
    execute = sub.add_parser('run')
    for name in ('build-directory', 'assets', 'proot', 'java-home', 'private-root', 'output', 'private-log'):
        execute.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if args.operation == 'prepare': result = prepare(args.dependency_provider, args.programs_provider, args.content_provider, args.output)
    elif args.operation == 'build': result = build(args.json_source, args.java_home, args.output)
    else: result = run(args.build_directory, args.assets, args.proot, args.java_home, args.private_root, args.output, args.private_log)
    print(encode(result).decode(), end='')


if __name__ == '__main__':
    main()
