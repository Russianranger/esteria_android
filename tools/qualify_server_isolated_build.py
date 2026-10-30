#!/usr/bin/env python3
"""Actually rebuild the selected server from an offline, asset-free source export.

Only observed zero-exit configure/build/reference checks can seal source closure.
Failures retain private build/install/logs and a false qualification receipt.
No database, auth listener, world session or Android runtime is started.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, package_server_content as transaction
from tools import package_server_engine as engine, package_server_engine_source_inputs as source_inputs
from tools import prepare_runtime as archives, prepare_server_isolated_build as inputs
from tools import prepare_server_isolated_sources as preparation, provider_client_runtime as client
from tools import verify_protocol as protocol, verify_server_build as files
from tools.owned_process_group import OwnedGroup

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/server-isolated-build.yml'
MAX_LOG = 64 * 1024**2
MAX_BUILD_SECONDS = 3 * 60 * 60
MAX_SOURCE_ARCHIVE_BYTES = 512 * 1024**2
SOURCE_ARCHIVE = 'server-engine-complete-sources.tar.gz'
REFERENCES = ('esteria_srp_reference', 'esteria_auth_srp_reference', 'esteria_playerbots_database_reference')
require = files.require


def write_json(path, value):
    raw = engine.canonical(value)
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path); archives.sync_directory(path.parent)


def require_offline(path=Path('/proc/net/dev')):
    names = {line.split(':', 1)[0].strip() for line in path.read_text().splitlines() if ':' in line}
    require(names == {'lo'}, 'isolated-rebuild-requires-loopback-only-network-namespace')
    return dict(interfaces=['lo'], externalNetworkingAvailable=False)


def build_environment(output):
    # Inherit no compiler flags, launcher settings, API credentials or Git config.
    return dict(PATH=os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'), LANG='C.UTF-8', LC_ALL='C.UTF-8',
        PYTHONDONTWRITEBYTECODE='1', CCACHE_DISABLE='1', CMAKE_BUILD_PARALLEL_LEVEL='2',
        TMPDIR=str(output / 'tmp'), GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1')


def run_owned(arguments, log, environment, *, cwd=None, timeout=MAX_BUILD_SECONDS, maximum=MAX_LOG):
    """Drain bounded output while retaining the child/group identity until cleanup."""
    require(not os.path.lexists(log), 'existing-isolated-command-log-preserved')
    started = time.monotonic()
    process = subprocess.Popen([str(value) for value in arguments], cwd=cwd, env=environment,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    owner = OwnedGroup(process); selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    count = 0
    try:
        with log.open('xb') as output:
            while selector.get_map():
                require(time.monotonic() - started < timeout, 'isolated-command-timeout')
                for key, _ in selector.select(.1):
                    block = os.read(key.fd, files.BUFFER)
                    if not block:
                        selector.unregister(key.fd); continue
                    require(count + len(block) <= maximum, 'isolated-command-log-bound')
                    output.write(block); count += len(block)
            status = owner.wait(max(.01, timeout - (time.monotonic() - started)))
            output.flush(); os.fsync(output.fileno())
        require(status == 0, 'isolated-command-nonzero-exit:' + str(status))
        return dict(exitCode=status, output=files.identity(log), observedSeconds=round(time.monotonic() - started, 3))
    finally:
        selector.close(); process.stdout.close(); owner.stop(graceful_timeout=0)


def verify_prepared(prepared, acquired):
    """Rehash the exact prepared source, semantic patches, metadata and Lua tree."""
    pin = inputs.load_pin()
    acquisition, _ = modules.read_json(acquired / 'acquisition.json')
    require(acquisition.get('formatVersion') == 1 and acquisition.get('scope') == 'isolated-source-build-inputs-acquired' and
            acquisition.get('inputLock') == files.identity(inputs.LOCK), 'isolated-acquisition-receipt-mismatch')
    for name, expected in pin['originalBuildEnvironment']['files'].items():
        require(files.identity(acquired / 'environment' / name) == expected, 'isolated-environment-input-changed')
    require({path.relative_to(acquired / 'environment').as_posix() for path in files.installed_files(acquired / 'environment')} ==
            set(pin['originalBuildEnvironment']['files']), 'isolated-environment-input-file-set-changed')
    source_root = acquired / 'source-inputs'
    require({path.relative_to(source_root).as_posix() for path in files.installed_files(source_root)} ==
            {pin['sourceInputs'][field]['file'] for field in ('archive', 'receipt')},
            'isolated-original-source-input-file-set-changed')
    for field in ('archive', 'receipt'):
        row = pin['sourceInputs'][field]
        require(files.identity(source_root / row['file']) == {key: row[key] for key in ('bytes', 'sha256')},
                'isolated-original-source-input-changed')
    original_receipt, _ = modules.read_json(source_root / pin['sourceInputs']['receipt']['file'], limit=8 * 1024**2)
    receipt, receipt_identity = modules.read_json(prepared / 'preparation-receipt.json')
    manifest, manifest_identity = modules.read_json(prepared / 'provenance/metadata/source-inputs.json', limit=8 * 1024**2)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'isolated-server-source-preparation-only' and
            receipt.get('sourceInputReceipt') == files.identity(source_root / pin['sourceInputs']['receipt']['file']) and
            receipt.get('sourceInputArchive') == files.identity(source_root / pin['sourceInputs']['archive']['file']) and
            receipt.get('sourceManifest') == manifest_identity == original_receipt.get('manifest') and
            receipt.get('sourceLock') == original_receipt.get('sourceLock') == files.identity(ROOT / 'sources.lock.json') and
            receipt.get('semanticPatchReplay', {}).get('exactAdaptedCopiesReproduced') is True and
            receipt.get('gitMetadataPresent') is False and receipt.get('assetTreesIncluded') is False,
            'isolated-prepared-source-receipt-mismatch')
    require(manifest.get('sourceLock') == receipt['sourceLock'] and manifest.get('originalBuild') == receipt.get('originalBuild') and
            manifest.get('originalCompiledModules') == receipt.get('originalCompiledModules') and
            manifest.get('originalBuild') == original_receipt.get('originalBuild') and
            manifest.get('originalCompiledModules') == original_receipt.get('originalCompiledModules') and
            manifest.get('compileCommands') == receipt.get('compileCommands'), 'isolated-prepared-source-bindings-mismatch')
    original_build, original_build_identity = modules.read_json(prepared / 'provenance/metadata/server-build.json')
    require(original_build_identity == manifest['originalBuild'], 'isolated-original-build-bytes-changed')
    # Independently regenerate the two allowed metadata adaptations from their
    # original, content-addressed files. The caller cannot nominate arbitrary
    # source edits merely by changing a preparation receipt.
    with tempfile.TemporaryDirectory(prefix='isolated-revision-verification-') as directory:
        reference = Path(directory)
        for name in ('src/cmake/genrev.cmake', 'src/genrev/CMakeLists.txt'):
            original = prepared / 'provenance/source-export-adaptations' / name
            require(files.identity(original) == {key: manifest['pristineGitFiles']['server'][name][key]
                    for key in ('bytes', 'sha256')}, 'isolated-original-revision-recipe-changed')
            target = reference / 'source' / name; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
        archival = preparation.adapt_revision(reference, original_build)
    require(receipt['archivalRevision'] == archival, 'isolated-revision-adaptation-differs-from-verified-recipe')
    expected = dict(manifest['pristineGitFiles']['server'])
    expected.update({engine.content.ELUNA + '/' + name: row for name, row in manifest['pristineGitFiles']['eluna'].items()})
    for row in manifest['adaptedFiles']: expected[row['path']] = row['adapted']
    for row in archival['buildMetadataAdaptations']: expected[row['path']] = row['prepared']
    for root, rows in ((prepared / 'source', expected), (prepared / 'integration', manifest['pristineGitFiles']['integration'])):
        actual = {path.relative_to(root).as_posix() for path in files.installed_files(root)}
        require(actual == set(rows), 'isolated-prepared-tree-file-set-changed')
        for name, row in rows.items():
            require(files.identity(root / name) == {key: row[key] for key in ('bytes', 'sha256')},
                    'isolated-prepared-tree-bytes-changed:' + name)
    for row in manifest['localInputs'].items():
        require(files.identity(prepared / 'provenance' / row[0]) == {key: row[1][key] for key in ('bytes', 'sha256')},
                'isolated-prepared-provenance-changed')
    revision = receipt['archivalRevision']
    require(files.identity(prepared / revision['file']) == revision['identity'], 'isolated-archival-revision-changed')
    lua = prepared / 'provenance/external/lua-5.2.4.tar.gz'
    require(files.identity(lua) == receipt['originalLua']['originalArchive'], 'isolated-original-lua-changed')
    seen = set()
    with files.plain_file(lua) as stream, archives.bounded_tar(stream,
            dict(entries=512, pathBytes=512, fileBytes=8 * 1024**2)) as archive:
        for item in archive:
            if item.isdir(): continue
            require(item.isfile() and item.name.startswith('lua-5.2.4/'), 'isolated-lua-source-member-contract')
            path = prepared / 'external' / item.name
            with archive.extractfile(item) as original:
                expected_identity = dict(bytes=item.size, sha256=archives.hash_stream(original, item.size))
            require(files.identity(path) == expected_identity, 'isolated-lua-extracted-file-changed')
            seen.add(item.name)
    require({p.relative_to(prepared / 'external').as_posix() for p in files.installed_files(prepared / 'external')} == seen,
            'isolated-lua-source-file-set-changed')
    require(not any(p.name == '.git' for p in prepared.rglob('.git')), 'isolated-git-metadata-present')
    return receipt, receipt_identity, manifest


def configure_arguments(cmake, prepared, output):
    return [str(cmake), '-S', str(prepared / 'source'), '-B', str(output / 'build'), '-G', 'Ninja',
        '-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DCMAKE_INSTALL_PREFIX=' + str(output / 'install'),
        '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON', '-DCMAKE_PROJECT_INCLUDE=' + str(prepared / 'integration/tests/srp6_reference.cmake'),
        '-DCMAKE_C_COMPILER_LAUNCHER=', '-DCMAKE_CXX_COMPILER_LAUNCHER=',
        '-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF', '-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF',
        '-DSCRIPTS=static', '-DMODULES=static', '-DAPPS_BUILD=all', '-DTOOLS_BUILD=all', '-DELUNA=ON',
        '-DLUA_VERSION=lua52', '-DLUA_STATIC=ON', '-DNOPCH=1', '-DWITHOUT_GIT=ON',
        '-DESTERIA_ARCHIVAL_REVISION_FILE=' + str(prepared / 'provenance/archival-revision.txt'),
        '-DFETCHCONTENT_SOURCE_DIR_LUA52=' + str(prepared / 'external/lua-5.2.4'),
        '-DFETCHCONTENT_FULLY_DISCONNECTED=ON']


def verify_selection(commands, install, original, manifest, prepared):
    selection, command_identity = modules.extract_commands(commands)
    require(selection['modules'] == original['enabledModules'] and selection['configFiles'] == original['configFiles'],
            'isolated-rebuild-compiled-selection-changed')
    programs = {}
    for name in files.REQUIRED_APPS + files.REQUIRED_TOOLS:
        path = install / 'bin' / name
        programs[name] = dict(files.identity(path), elf=files.elf_header(path, executable=True))
    for name in ('worldserver', 'dbimport'):
        literals = [selection['moduleLiteral']] + ([selection['configLiteral']] if name == 'worldserver' else [])
        modules.verify_literals(install / 'bin' / name, {key: programs[name][key] for key in ('bytes', 'sha256')}, literals)
    selected = set(manifest['pristineGitFiles']['server']) | {
        engine.content.ELUNA + '/' + name for name in manifest['pristineGitFiles']['eluna']}
    coverage = source_inputs.compiler_coverage(commands, selected)
    original_coverage = manifest['compilerCoverage']
    require(len(original_coverage['observedServerSources']) == 2199 and
            len(original_coverage['observedServerIncludeDirectories']) == 340,
            'isolated-original-source-coverage-profile-changed')
    for key in ('observedServerSources', 'observedServerIncludeDirectories'):
        require(coverage[key] == original_coverage[key], 'isolated-rebuild-observed-source-coverage-changed:' + key)
    allowed_external = (prepared / 'external/lua-5.2.4', prepared / 'integration', commands.parent)
    require(all(any(Path(name).is_relative_to(root) for root in allowed_external)
                for name in coverage['externalOrGeneratedSources']), 'isolated-build-external-source-path-not-owned')
    return dict(compileCommands=command_identity, enabledModules=selection['modules'], configFiles=selection['configFiles'],
                programs=programs, compilerCoverage=coverage, originalModuleReceiptUnchanged=True,
                newBinariesIdentifiedSeparately=True)


def protocol_check(prepared, manifest_path):
    pin = json.loads(client.small(client.PIN))
    current = json.loads((ROOT / 'sources.lock.json').read_text())['sources']['client']['commit']
    build, build_identity = modules.read_json(manifest_path.parent / 'client-build.json')
    identity = files.identity(manifest_path)
    require(pin['sourceRevision'] == current and build_identity['sha256'] == pin['buildManifestSha256'] and
            build.get('source_revision') == current and build.get('descriptor_manifest', {}).get('sha256') == identity['sha256'] and
            build['descriptor_manifest'].get('size') == identity['bytes'], 'actual-pinned-client-layout-manifest-required')
    report = protocol.verify(json.loads(manifest_path.read_text()), (prepared / 'source' / protocol.FIELD_HEADER).read_text())
    return dict(report, actualClientSourceRevision=current, limits=identity, clientBuild=build_identity,
                clientExecuted=False, runtimeProtocolQualified=False)


def collect_source_files(prepared, acquired, output, protocol_manifest, proof):
    """Retain reconstructable inputs/recipes, never any rebuilt executable/object."""
    selected = {}
    def add(name, path):
        engine.content.safe_path(name)
        require(name not in selected, 'complete-source-path-collision')
        selected[name] = path
    for path in files.installed_files(acquired / 'source-inputs'):
        add('inputs/source-inputs/' + path.name, path)
    for path in files.installed_files(acquired / 'environment'):
        add('inputs/environment/' + path.name, path)
    add('inputs/acquisition.json', acquired / 'acquisition.json')
    add('recipes/runtime/server/isolated-build.lock.json', inputs.LOCK)
    add('recipes/.github/workflows/server-isolated-build.yml', WORKFLOW)
    for name in ('LICENSE', 'sources.lock.json', 'config/local-server.json', 'runtime/server-lua-map.json',
                 'runtime/server/engine-source-audit.json', 'runtime/server/engine-reference.lock.json',
                 'runtime/server/sources.lock.json', 'runtime/client/android-provider.lock.json',
                 'runtime/client/dependency-release.lock.json'):
        add('recipes/' + name, ROOT / name)
    for root in ('tools', 'runtime', 'tests'):
        for path in sorted((ROOT / root).rglob('*')):
            if path.is_file() and path.suffix in (('.py',) if root in ('tools', 'runtime') else ('.py', '.c', '.cpp', '.h', '.hpp', '.cmake')):
                add('recipes/' + path.relative_to(ROOT).as_posix(), path)
    for path in files.installed_files(prepared / 'provenance'):
        # The original 48MB compile commands and source manifest are retained.
        add('preparation/provenance/' + path.relative_to(prepared / 'provenance').as_posix(), path)
    add('preparation/preparation-receipt.json', prepared / 'preparation-receipt.json')
    add('new-build/compile_commands.json', output / 'build/compile_commands.json')
    add('new-build/CMakeCache.txt', output / 'build/CMakeCache.txt')
    for path in files.installed_files(output / 'build'):
        if path.suffix in ('.h', '.hpp', '.inc', '.inl'):
            add('new-build/generated/' + path.relative_to(output / 'build').as_posix(), path)
    add('protocol/limits.json', protocol_manifest)
    add('protocol/client-build.json', protocol_manifest.parent / 'client-build.json')
    for path in files.installed_files(output / 'diagnostics'):
        if path.suffix == '.json': add('qualification/' + path.name, path)
    add('qualification/qualification.json', proof)
    add('rebuild-plan.json', proof.parent / 'rebuild-plan.json')
    return selected


def write_source_archive(path, selected):
    inventory, total = {}, 0
    require(0 < len(selected) <= 20000, 'complete-source-member-count-bound')
    with path.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
            for name, source in sorted(selected.items()):
                engine.content.safe_path(name)
                require('.git' not in Path(name).parts and Path(name).suffix.lower() not in preparation.ASSET_SUFFIXES and
                        Path(name).suffix.lower() not in ('.o', '.a', '.so', '.exe', '.dll'), 'binary-or-asset-in-complete-source')
                identity = files.identity(source); total += identity['bytes']
                require(total <= MAX_SOURCE_ARCHIVE_BYTES, 'complete-source-expanded-bound')
                with files.plain_file(source) as stream:
                    require(stream.read(4) != b'\x7fELF', 'elf-binary-in-complete-source'); stream.seek(0)
                    info = tarfile.TarInfo(name); info.size = identity['bytes']; info.mode = 0o444
                    reader = transaction.HashReader(stream, identity); archive.addfile(info, reader); reader.finish()
                inventory[name] = dict(identity, mode=0o444)
    engine.verify_archive(path, inventory)
    return inventory


def qualify(prepared, acquired, protocol_manifest, output):
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'native-arm64-isolated-rebuild-required')
    prepared = archives.directory(Path(os.path.abspath(prepared))); acquired = archives.directory(Path(os.path.abspath(acquired)))
    protocol_manifest = Path(os.path.abspath(protocol_manifest))
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(root != output and root not in output.parents and output not in root.parents
            for root in (prepared, acquired)), 'existing-or-overlapping-isolated-build-output-preserved')
    network = require_offline()
    output.mkdir(mode=0o700); (output / 'diagnostics').mkdir(); (output / 'tmp').mkdir()
    evidence = dict(formatVersion=1, scope='actual-native-arm64-isolated-server-source-rebuild', phase='verify-inputs',
        network=network, sourceCompanionComplete=False, isolatedSourceRebuildQualified=False,
        transitiveIncludeClosureProved=False, fullCompileObserved=False, noCompilerCacheUsed=True,
        sourceBitIdenticalBinaryClaimed=False, sqlExecuted=False, worldserverSessionStarted=False,
        androidRuntimeQualified=False, gameplayQualified=False)
    write_json(output / 'qualification.json', evidence)
    started = time.monotonic(); environment = build_environment(output); stage = None
    def command(args, name, timeout=MAX_BUILD_SECONDS):
        remaining = MAX_BUILD_SECONDS - (time.monotonic() - started)
        require(remaining > 0, 'isolated-build-overall-deadline')
        return run_owned(args, output / 'diagnostics' / (name + '.log'), environment,
                         cwd=ROOT, timeout=min(timeout, remaining))
    try:
        prep, prep_identity, manifest = verify_prepared(prepared, acquired)
        evidence.update(preparationReceipt=prep_identity, originalBuild=prep['originalBuild'],
                        originalCompiledModules=prep['originalCompiledModules'], sourceLock=prep['sourceLock'])
        before_environment = inputs.verify_environment(acquired, output / 'diagnostics/environment-before.json')
        require(before_environment.get('relevantBuildEnvironmentMatched') is True,
                'isolated-relevant-build-environment-differs-before-build')
        evidence['environmentBefore'] = before_environment
        layout = protocol_check(prepared, protocol_manifest); write_json(output / 'diagnostics/protocol-layout.json', layout)
        cmake_path = shutil.which('cmake'); require(cmake_path is not None, 'isolated-cmake-missing')
        cmake = Path(cmake_path).resolve(strict=True)
        evidence['cmakeExecutable'] = dict(path=str(cmake), **files.identity(cmake))
        compilers = {name: shutil.which(name) for name in ('gcc', 'g++')}
        require(all(compilers.values()), 'isolated-actual-compiler-missing')
        compilers = {name: str(Path(path).resolve(strict=True)) for name, path in compilers.items()}
        evidence['phase'] = 'configure'; write_json(output / 'qualification.json', evidence)
        arguments = configure_arguments(cmake, prepared, output) + ['-DCMAKE_C_COMPILER=' + compilers['gcc'],
                                                                  '-DCMAKE_CXX_COMPILER=' + compilers['g++']]
        evidence['configure'] = command(arguments, 'configure', 900)
        cache = files.cmake_options(output / 'build/CMakeCache.txt')
        cache_text = (output / 'build/CMakeCache.txt').read_text()
        require(all(re.findall(r'^' + name + r':[^=]+=(.*)$', cache_text, re.MULTILINE) == ['']
                    for name in ('CMAKE_C_COMPILER_LAUNCHER', 'CMAKE_CXX_COMPILER_LAUNCHER')),
                'isolated-compiler-launcher-not-disabled')
        evidence['cmakeOptions'] = cache
        evidence['phase'] = 'full-clean-build'; write_json(output / 'qualification.json', evidence)
        evidence['fullBuild'] = command([cmake, '--build', output / 'build', '--parallel', '2'], 'build')
        evidence['fullCompileObserved'] = True
        evidence['referenceBuild'] = command([cmake, '--build', output / 'build', '--parallel', '2', '--target', *REFERENCES], 'references')
        evidence['install'] = command([cmake, '--install', output / 'build'], 'install', 900)
        original, _ = modules.read_json(prepared / 'provenance/metadata/server-modules.json')
        selection = verify_selection(output / 'build/compile_commands.json', output / 'install', original, manifest, prepared)
        write_json(output / 'diagnostics/new-engine-selection.json', selection)
        revision = prep['archivalRevision']['recordedRevision']; versions = {}
        for name in ('authserver', 'worldserver'):
            log_name = name + '-version'
            command([output / 'install/bin' / name, '--version'], log_name, 30)
            text = (output / 'diagnostics' / (log_name + '.log')).read_text().strip()
            expected = 'AzerothCore rev. ' + revision['hash'] + ' ' + revision['date'] + ' (Archived source package branch) (Unix, RelWithDebInfo, Static)'
            require(text == expected, 'isolated-archival-version-output-mismatch')
            versions[name] = text
        for name in REFERENCES: files.elf_header(output / 'build' / name, executable=True)
        command([output / 'build/esteria_srp_reference'], 'srp-reference', 30)
        srp = json.loads((output / 'diagnostics/srp-reference.log').read_text())
        require(srp.get('scope') == 'actual-server-common-SRP6-fixed-vector' and all(srp.get(key) is True for key in
            ('asciiNormalizationVerified', 'sourceVectorVerified', 'wrongPasswordRejected', 'wrongByteOrderRejected', 'wrongSaltRejected')),
            'isolated-real-srp-reference-did-not-pass')
        reference_environment = dict(environment, ESTERIA_AUTH_SRP_REFERENCE=str(output / 'build/esteria_auth_srp_reference'))
        remaining = MAX_BUILD_SECONDS - (time.monotonic() - started)
        run_owned([sys.executable, '-m', 'unittest', 'tests.test_auth_protocol', '-v'], output / 'diagnostics/reference-tests.log',
                  reference_environment, cwd=ROOT, timeout=min(600, remaining))
        after_environment = inputs.verify_environment(acquired, output / 'diagnostics/environment-after.json')
        require(after_environment.get('relevantBuildEnvironmentMatched') is True,
                'isolated-relevant-build-environment-differs-after-build')
        evidence['environmentAfter'] = after_environment
        require(verify_prepared(prepared, acquired)[1] == prep_identity, 'isolated-inputs-changed-during-build')
        evidence.update(phase='complete', fullBuildAndReferencesPassed=True, authWorldVersionExecuted=True,
            recordedArchivalVersions=versions, originalSelectionPreserved=True, fieldLayoutOnly=layout,
            actualInstalledPrograms=selection['programs'], observedSourcesCovered=len(selection['compilerCoverage']['observedServerSources']),
            observedIncludeDirectoriesCovered=len(selection['compilerCoverage']['observedServerIncludeDirectories']),
            playerbotsReferenceBuilt=True, playerbotsDatabaseExecuted=False,
            sourceCompanionComplete=True, isolatedSourceRebuildQualified=True, transitiveIncludeClosureProved=True)
        stage = Path(tempfile.mkdtemp(prefix='.sealed.stage-', dir=output))
        engine.put_metadata(stage / 'qualification.json', evidence)
        engine.put_metadata(stage / 'rebuild-plan.json', dict(formatVersion=1,
            scope='offline-native-arm64-source-rebuild-recipe', workingDirectory='archive-root',
            originalSourceInputsRetained='inputs/source-inputs', sourcePreparationCommand=[
                'python3', 'recipes/tools/prepare_server_isolated_sources.py', '--source-inputs', 'inputs/source-inputs',
                '--output', 'prepared'], buildCommand=['python3', 'recipes/tools/qualify_server_isolated_build.py',
                '--prepared', 'prepared', '--inputs', 'inputs', '--protocol-manifest', 'protocol/limits.json', '--output', 'rebuild'],
            requiresNativeLinuxArm64=True, requiresLoopbackOnlyNetworkNamespace=True,
            environmentContract='recipes/runtime/server/isolated-build.lock.json',
            compilerCacheDisabled=True, sourceRepositoryFetchRequired=False, gameAssetsRequired=False,
            originalBinaryBitIdentityRequired=False))
        selected = collect_source_files(prepared, acquired, output, protocol_manifest, stage / 'qualification.json')
        archive = stage / SOURCE_ARCHIVE; inventory = write_source_archive(archive, selected)
        sealed = dict(formatVersion=1, scope='complete-isolated-server-source-rebuild-companion',
            archive=dict(file=SOURCE_ARCHIVE, **files.identity(archive)), archiveFiles=inventory,
            qualification=files.identity(stage / 'qualification.json'), sourceInputArchive=prep['sourceInputArchive'],
            sourceInputReceipt=prep['sourceInputReceipt'], originalBuild=prep['originalBuild'],
            originalCompiledModules=prep['originalCompiledModules'], sourceLock=prep['sourceLock'],
            originalUnsealedReceiptsUnchanged=True, archiveReadbackVerified=True,
            sourceCompanionComplete=True, isolatedSourceRebuildQualified=True,
            bitIdenticalOriginalBinariesClaimed=False, sqlExecuted=False, androidRuntimeQualified=False, gameplayQualified=False)
        engine.put_metadata(stage / 'sealed-source-receipt.json', sealed); archives.sync_directory(stage)
        transaction.publish_directory(stage, output / 'sealed'); archives.sync_directory(output)
        write_json(output / 'qualification.json', evidence)
        return sealed
    except BaseException as error:
        evidence.update(sourceCompanionComplete=False, isolatedSourceRebuildQualified=False,
                        transitiveIncludeClosureProved=False, failureClass=type(error).__name__,
                        failurePhase=evidence['phase'], phase='failed')
        write_json(output / 'qualification.json', evidence)
        if stage is not None and stage.exists() and (stage / 'qualification.json').exists():
            write_json(stage / 'qualification.json', evidence)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('prepared', 'inputs', 'protocol-manifest', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    try:
        result = qualify(args.prepared, args.inputs, args.protocol_manifest, args.output)
        print(json.dumps({key: result[key] for key in ('scope', 'archive', 'sourceCompanionComplete',
                                                     'isolatedSourceRebuildQualified', 'androidRuntimeQualified', 'gameplayQualified')}))
    except BaseException:
        raise SystemExit('Isolated server rebuild failed; private build and typed false receipt retained') from None


if __name__ == '__main__': main()
