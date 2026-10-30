#!/usr/bin/env python3
"""Compose a separate source companion for the measured ordered extractor pair.

All inputs are local and immutable. No compiler, server, downloader or Git writer
is run. The original native receipt remains unsealed and byte-for-byte unchanged;
only the new receipt describes this composed corresponding-source companion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import build_ordered_extractors as ordered
from tools import capture_ordered_extractor_dependencies as dependencies
from tools import manifest_server_content as content, package_server_content as transaction
from tools import package_server_engine as engine, prepare_ordered_extractors as adaptation
from tools import prepare_runtime as archives, prepare_server_isolated_sources as preparation
from tools import qualify_server_isolated_build as isolated, verify_server_build as files
from tools import verify_target_dependency_observation as dependency_readback

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/ordered-tools-inputs.lock.json'
SOURCE_ARCHIVE = 'ordered-extractor-complete-sources.tar.gz'
RECEIPT = 'ordered-source-receipt.json'
ORIGINAL_ARCHIVE = 'server-engine-complete-sources.tar.gz'
MAX_FILES = 20000
MAX_EXPANDED = 768 << 20
MAX_MEMBER = 128 << 20
TARGETS = ('map_extractor', 'vmap4_extractor')
EXPECTED_OBJECTS = 210
EXPECTED_MACHINES = [183]
FALSE_FLAGS = ('sourceCompanionComplete', 'androidRuntimeQualified', 'gameplayQualified',
               'customEsteriaDataLoadOrderQualified', 'clientMpqConversionQualified')
SEALING_RECIPES = ('tools/seal_ordered_extractor_sources.py', 'tests/test_ordered_extractor_sources.py',
                  'tools/verify_target_dependency_observation.py', 'tests/test_target_dependency_observation.py',
                  'tools/prepare_ordered_extractor_sources.py', 'tests/test_ordered_source_inputs.py',
                  '.github/workflows/server-ordered-sources.yml',
                  'runtime/server/ORDERED-SOURCE-SEAL.md', 'runtime/server/ordered-tools-inputs.lock.json', 'LICENSE')
require = files.require


def identity(row):
    require(type(row) is dict and type(row.get('bytes')) is int and 0 <= row['bytes'] <= MAX_MEMBER and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'ordered-source-invalid-file-identity')
    return {key: row[key] for key in ('bytes', 'sha256')}


def read_json(path, limit=16 << 20):
    def unique(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'ordered-source-duplicate-json-key')
            result[key] = value
        return result
    with files.plain_file(path) as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'ordered-source-json-byte-bound')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: require(False, 'nonfinite-json')), \
        dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def load_pin():
    pin, _ = read_json(LOCK)
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'exact-ordered-server-data-tools-packaging-inputs' and
            pin.get('state') == 'measured-native-dependency-capture', 'ordered-source-measured-input-pin-required')
    require(all(pin.get(name) is False for name in FALSE_FLAGS), 'ordered-source-input-qualification-flags')
    native = pin['nativeBuild']
    require(re.fullmatch('[0-9a-f]{40}', native.get('integrationRevision', '')) and
            all(type(native.get(k)) is int and native[k] > 0 for k in ('workflowRun', 'job')),
            'ordered-source-native-build-pin')
    for name in ('receipt', 'dependencyObservation'):
        identity(native[name])
    for name in ('payloadArtifact', 'evidenceArtifact'):
        row = native[name]
        require(type(row) is dict and type(row.get('id')) is int and row['id'] > 0,
                'ordered-source-artifact-pin')
        identity(row)
    original_artifact = pin['originalSourceArtifact']
    identity(original_artifact)
    require(all(type(original_artifact.get(k)) is int and original_artifact[k] > 0 for k in ('id', 'workflowRun')) and
            re.fullmatch('[0-9a-f]{40}', original_artifact.get('integrationRevision', '')),
            'ordered-source-original-artifact-pin')
    require(set(native.get('programs', {})) == set(TARGETS), 'ordered-source-native-program-pin')
    for row in native['programs'].values():
        identity(row)
        require(row.get('elf', {}).get('machine') == 'AArch64', 'ordered-source-native-program-architecture')
    selected, _ = read_json(ROOT / 'runtime/server/programs-provider.lock.json')
    require(pin['originalSourceQualification'] == selected['sourceQualification'] and
            pin['serverBuildSourceLock'] == selected['serverBuildSourceLock'] and
            pin['adaptationLock'] == files.identity(adaptation.LOCK), 'ordered-source-original-selection-pin')
    for row in pin['originalSourceQualification'].values():
        identity(row)
    readme = pin['clientPolicyReadme']
    identity(readme)
    require(readme.get('file') == 'README.md' and readme.get('gitMode') == '100644' and
            re.fullmatch('[0-9a-f]{40}', readme.get('gitBlob', '')) and
            readme.get('clientRevision') == adaptation.load_pin()['clientRevision'], 'ordered-source-client-readme-pin')
    return pin


def inventory(root):
    return {path.relative_to(root).as_posix(): files.identity(path) for path in files.installed_files(root)}


def check_inventory(root, expected, *, extra=()):
    require(type(expected) is dict and 0 < len(expected) <= MAX_FILES, 'ordered-source-inventory-bound')
    for name, row in expected.items():
        content.safe_path(name); identity(row)
    actual = inventory(root)
    require(set(actual) == set(expected) | set(extra), 'ordered-source-input-file-set')
    require(all(actual[name] == identity(row) for name, row in expected.items()), 'ordered-source-input-file-changed')
    return actual


def extract_original(archive, expected, destination):
    """Read back every original source member, retaining its fixed archive mode."""
    require(type(expected) is dict and 0 < len(expected) <= MAX_FILES, 'ordered-source-original-inventory-bound')
    require(sum(identity(row)['bytes'] for row in expected.values()) <= MAX_EXPANDED,
            'ordered-source-original-expanded-bound')
    engine.verify_archive(archive, expected)
    seen = set()
    with files.plain_file(archive) as raw, archives.bounded_tar(raw,
            dict(entries=MAX_FILES, pathBytes=4096, fileBytes=MAX_MEMBER)) as stream:
        for member in stream:
            content.safe_path(member.name)
            require(member.isfile() and member.name in expected and member.name not in seen,
                    'ordered-source-original-member-set')
            row = expected[member.name]
            require(member.size == row['bytes'] and member.mode == row['mode'] == 0o444 and
                    member.uid == member.gid == member.mtime == 0 and not member.uname and not member.gname,
                    'ordered-source-original-member-metadata')
            target = destination / member.name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with stream.extractfile(member) as incoming, target.open('xb') as outgoing:
                require(archives.hash_stream(incoming, member.size, outgoing) == row['sha256'],
                        'ordered-source-original-member-sha256')
                outgoing.flush(); os.fsync(outgoing.fileno())
            target.chmod(0o444); seen.add(member.name); stream.members.clear()
    require(seen == set(expected), 'ordered-source-original-members-missing')


def verify_original(directory, pin, destination):
    expected = pin['originalSourceQualification']
    names = {'archive': ORIGINAL_ARCHIVE, 'qualification': 'qualification.json', 'receipt': 'sealed-source-receipt.json'}
    for name, filename in names.items():
        require(files.identity(directory / filename) == identity(expected[name]), 'ordered-source-original-triple-changed')
    sealed, _ = read_json(directory / names['receipt'])
    qualified, _ = read_json(directory / names['qualification'])
    require(sealed.get('scope') == 'complete-isolated-server-source-rebuild-companion' and
            all(sealed.get(k) is True for k in ('archiveReadbackVerified', 'sourceCompanionComplete',
                'isolatedSourceRebuildQualified', 'originalUnsealedReceiptsUnchanged')) and
            sealed.get('sourceLock') == pin['serverBuildSourceLock'] and
            sealed.get('archive') == dict(file=ORIGINAL_ARCHIVE, **identity(expected['archive'])) and
            sealed.get('qualification') == identity(expected['qualification']), 'ordered-source-original-seal-binding')
    require(qualified.get('scope') == 'actual-native-arm64-isolated-server-source-rebuild' and
            qualified.get('phase') == 'complete' and all(qualified.get(k) is True for k in
                ('sourceCompanionComplete', 'isolatedSourceRebuildQualified', 'transitiveIncludeClosureProved',
                 'fullCompileObserved', 'noCompilerCacheUsed', 'fullBuildAndReferencesPassed', 'originalSelectionPreserved')) and
            qualified.get('sourceLock') == pin['serverBuildSourceLock'] and
            all(qualified.get(k, {}).get('exitCode') == 0 for k in ('configure', 'fullBuild', 'referenceBuild', 'install')),
            'ordered-source-original-full-compile-required')
    require(all(doc.get(k) is False for doc in (qualified, sealed) for k in ('androidRuntimeQualified', 'gameplayQualified')),
            'ordered-source-original-native-only')
    rows = sealed['archiveFiles']
    require(identity(rows['qualification/qualification.json']) == identity(expected['qualification']) and
            identity(rows['inputs/source-inputs/server-engine-source-inputs.tar.gz']) == sealed['sourceInputArchive'] and
            identity(rows['inputs/source-inputs/source-inputs-receipt.json']) == sealed['sourceInputReceipt'],
            'ordered-source-original-inner-bindings')
    extract_original(directory / ORIGINAL_ARCHIVE, rows, destination)
    require(files.identity(destination / 'qualification/qualification.json') == identity(expected['qualification']),
            'ordered-source-original-embedded-qualification')
    return sealed


def verify_native(payload, pin):
    q, qid = read_json(payload / 'ordered-build.json')
    native = pin['nativeBuild']
    require(qid == identity(native['receipt']) and q.get('formatVersion') == 1 and
            q.get('scope') == 'native-arm64-separate-ordered-extractor-target-build-and-synthetic-lookups' and
            q.get('phase') == 'complete' and q.get('integrationRevision') == native['integrationRevision'] and
            q.get('targets') == list(TARGETS), 'ordered-source-exact-native-receipt-required')
    require(all(q.get(k) is True for k in ('actualTargetCompileSucceeded', 'nativeOrderedLookupQualified',
                'onlyRequestedToolsBuilt', 'compilerCacheDisabled', 'originalInputsUnchanged')) and
            all(q.get(k) is False for k in FALSE_FLAGS + ('globalServerPatchListChanged', 'serverProgramsReplaced',
                'isolatedFullServerRebuildQualified', 'proprietaryClientDataSupplied')) and
            q.get('network') == dict(interfaces=['lo'], externalNetworkingAvailable=False),
            'ordered-source-native-scope-or-gates')
    require(all(q.get(k, {}).get('exitCode') == 0 for k in ('configure', 'compile',
                'generatedMetadataStabilizationBuild', 'syntheticLookupTests', *(t+'Capability' for t in TARGETS))) and
            all(q.get(k, {}).get('relevantBuildEnvironmentMatched') is True for k in ('environmentBefore', 'environmentAfter')),
            'ordered-source-native-successful-target-build-required')
    require(q.get('serverBuildSourceLock') == pin['serverBuildSourceLock'] and
            q.get('adaptationLock') == pin['adaptationLock'] and q.get('programs') == native['programs'],
            'ordered-source-native-input-bindings')
    rows = check_inventory(payload, q['payloadFiles'], extra=('ordered-build.json',))
    require({n for n in rows if n.startswith('bin/')} == {'bin/'+t for t in TARGETS},
            'ordered-source-unexpected-program')
    for target in TARGETS:
        require(rows['bin/'+target] == identity(native['programs'][target]) and
                files.elf_header(payload/'bin'/target, executable=True) == native['programs'][target]['elf'],
                'ordered-source-native-executable-changed')
    return q, qid, rows


def recipe_names(source):
    names = set()
    for name in source.files:
        path = Path(name)
        if (path.parts[0] in ('tools', 'runtime', 'tests') and path.suffix == '.py' and
                not name.startswith('runtime/evidence/')) or \
           (path.parts[0] == 'tests' and path.suffix in ('.c', '.cpp', '.h', '.hpp', '.cmake')) or \
           (name.startswith('runtime/') and path.suffix == '.json' and not name.startswith('runtime/evidence/')) or \
           (name.startswith('runtime/server/') and path.suffix == '.md') or \
           (name.startswith('config/') and path.suffix == '.json'):
            names.add(name)
    names.update(('LICENSE', 'sources.lock.json', '.github/workflows/server-extractor-order.yml',
        'runtime/server/extractor-order/EsteriaArchiveOrder.h',
        'runtime/server/extractor-order/0001-explicit-ordered-providers.patch'))
    require(0 < len(names) <= 3000, 'ordered-source-integration-recipe-count')
    require(all(name in source.files and source.files[name]['kind'] == 'blob' and
                source.files[name]['mode'] in ('100644', '100755') for name in names),
            'ordered-source-integration-recipe-missing-or-nonregular')
    return names


def export_recipes(git_root, revision, payload, destination):
    source = content.GitObjects(git_root, revision, allow_fetch=False)
    names = recipe_names(source)
    # Every declared recipe is verified against the native commit, including
    # files outside the closure rule (which are then explicitly retained too).
    supplied = {p.relative_to(payload/'recipes').as_posix(): p for p in files.installed_files(payload/'recipes')}
    require(set(supplied) <= set(source.files), 'ordered-source-untracked-native-recipe')
    names.update(supplied)
    rows = source.identities(names, True)
    require(sum(identity(row)['bytes'] for row in rows.values()) <= MAX_EXPANDED,
            'ordered-source-integration-recipe-byte-bound')
    for name, path in supplied.items():
        require(files.identity(path) == identity(rows[name]), 'ordered-source-native-recipe-not-git-blob')
    batch = transaction.GitBatch(source)
    try:
        for name, row in sorted(rows.items()):
            target = destination/name; target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            reader = batch.blob(row)
            with target.open('xb') as output:
                while block := reader.read(files.BUFFER): output.write(block)
                output.flush(); os.fsync(output.fileno())
            batch.finish_blob(reader); target.chmod(0o444)
    finally:
        batch.close()
    return dict(integrationRevision=revision, integrationTree=source.tree, files=rows,
        selection='committed Python, test C/C++/CMake, runtime JSON except evidence, config JSON, server docs and exact ordered resources',
        suppliedNativeRecipesAllMatchGitBlobs=True, gitNetworkFetchAllowed=False, gitMetadataIncluded=False)


def reconstruct(original, payload, q, work):
    lock = payload/'original-inputs/sources.lock.json'
    acquired = original/'inputs'
    original_prep = original/'preparation/preparation-receipt.json'
    require(files.identity(lock) == q['serverBuildSourceLock'] and
            files.identity(acquired/'source-inputs/server-engine-source-inputs.tar.gz') == q['sourceInputArchive'] and
            files.identity(acquired/'source-inputs/source-inputs-receipt.json') == q['sourceInputReceipt'],
            'ordered-source-original-input-selection-changed')
    for name in ('server-engine-source-inputs.tar.gz', 'source-inputs-receipt.json'):
        require(files.identity(payload/'original-inputs'/name) == files.identity(acquired/'source-inputs'/name),
                'ordered-source-native-original-input-copy-changed')
    require(files.identity(original_prep) == q['originalPreparationReceipt'] ==
            files.identity(payload/'provenance/original-preparation-receipt.json'), 'ordered-source-original-preparation-pin')
    for root, native_root in (('environment', 'original-environment'), ('supplements', 'supplements')):
        require(inventory(acquired/root) == inventory(payload/native_root), 'ordered-source-native-original-input-tree-changed')
    prepared = work/'prepared'
    preparation.prepare(acquired/'source-inputs', prepared, acquired/'supplements', original_lock=lock)
    preparation_receipt, _, _ = isolated.verify_prepared(prepared, acquired, original_lock=lock)
    require(files.identity(prepared/'preparation-receipt.json') == q['originalPreparationReceipt'],
            'ordered-source-original-preparation-replay-differs')
    require(q['originalBuild'] == preparation_receipt['originalBuild'] and
            q['originalModules'] == preparation_receipt['originalCompiledModules'],
            'ordered-source-native-original-build-or-module-binding')
    before = inventory(prepared)
    adapted = work/'adapted'; adaptation.prepare(prepared, adapted)
    apin = adaptation.load_pin()
    adaptation_id = files.identity(adapted/'extractor-adaptation.json')
    require(adaptation_id == files.identity(payload/'provenance/extractor-adaptation.json'),
            'ordered-source-adaptation-replay-differs')
    ordered.verify_overlay(prepared, adapted, before, apin, adaptation_id)
    ordered.verify_policy(payload/'client-policy', apin)
    require(q['clientRevision'] == apin['clientRevision'] and q['clientPolicySources'] == apin['clientSources'],
            'ordered-source-client-policy-source-selection')
    return prepared, adapted, before, apin


def verify_observation(payload, q, pin, adapted_inventory, apin):
    """Apply the ordered pair's native policy to the shared retained graph verifier."""
    return dependency_readback.verify(payload, q['targetSourceDependencies'], adapted_inventory, q['compileCommands'],
        targets=TARGETS, machines=tuple(EXPECTED_MACHINES), expected_objects=EXPECTED_OBJECTS,
        expected_links=len(TARGETS), observation_identity=pin['nativeBuild']['dependencyObservation'],
        required_sources=tuple('source/'+name for name in apin['adaptedFiles']),
        required_link_programs={name: identity(q['programs'][name]) for name in TARGETS})


def verify_readme(path, pin):
    expected = pin['clientPolicyReadme']
    require(files.identity(path) == identity(expected), 'ordered-source-client-readme-changed')
    with files.plain_file(path) as stream:
        raw = stream.read(MAX_MEMBER+1)
    require(hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest() == expected['gitBlob'],
            'ordered-source-client-readme-blob-changed')
    return dict(clientRevision=expected['clientRevision'], readme=expected, rootLicenseFound=False,
        applicablePolicyNoticeFiles=[], licenseGrantVerified=False,
        clientPolicyLicenseInferredFromServerLicense=False,
        policySourcesAreReferenceMaterial=True)


def sealing_recipes(root=ROOT, creation_revision=None):
    """Record current creation inputs separately from the older native Git tree."""
    require(creation_revision is None or re.fullmatch('[0-9a-f]{40}', creation_revision),
            'ordered-source-creation-integration-revision')
    selected = {'sealing-recipes/'+name: Path(root)/name for name in SEALING_RECIPES}
    rows = {name: files.identity(path) for name, path in selected.items()}
    return selected, dict(scope='current-source-companion-creation-recipes', files=rows,
        creationIntegrationRevision=creation_revision,
        claimedToBeNativeBuildGitRecipes=False, creationGitBlobClosureClaimed=False)


def verify_sealing_recipes(selected, recorded):
    require(set(selected) == set(recorded['files']) and
            all(files.identity(path) == identity(recorded['files'][name]) for name, path in selected.items()),
            'ordered-source-sealing-recipe-changed-before-publication')


def replay_plan(q, sealed, original_seal_identity, native_inventory, recipe_inventory):
    """Enumerate every offline staging copy, mode and subsequent command."""
    copies = []
    for name, row in sorted(recipe_inventory.items()):
        copies.append(dict(sourceTree='bundle', source='integration/'+name, destination='integration/'+name,
                           identity=identity(row), mode=0o755 if row['gitMode'] == '100755' else 0o444))
    for name, row in sorted(sealed['archiveFiles'].items()):
        if name.startswith(('inputs/source-inputs/', 'inputs/environment/', 'inputs/supplements/')) or name == 'inputs/acquisition.json':
            copies.append(dict(sourceTree='original', source=name, destination='acquired/'+name[len('inputs/'):],
                               identity=identity(row), mode=0o444))
    for name, row in sorted(native_inventory.items()):
        if name.startswith('client-policy/'):
            copies.append(dict(sourceTree='bundle', source='ordered/'+name,
                destination='policy_sources/'+name[len('client-policy/'):], identity=identity(row), mode=0o444))
    for source, destination in (('original-inputs/sources.lock.json', 'original-lock/sources.lock.json'),
                                ('build/environment-before.json', 'environment/input.json')):
        copies.append(dict(sourceTree='bundle', source='ordered/'+source, destination=destination,
                           identity=identity(native_inventory[source]), mode=0o444))
    require(len({r['destination'] for r in copies}) == len(copies), 'ordered-source-replay-copy-collision')
    require({r['destination'] for r in copies if r['destination'].startswith('acquired/')} ==
            {'acquired/'+name[len('inputs/'):] for name in sealed['archiveFiles'] if name.startswith(
                ('inputs/source-inputs/', 'inputs/environment/', 'inputs/supplements/')) or name == 'inputs/acquisition.json'},
            'ordered-source-replay-acquired-file-set')
    directories = set()
    for row in copies:
        for parent in Path(row['destination']).parents:
            if parent != Path('.'): directories.add(parent.as_posix())
    return dict(formatVersion=1, scope='offline-ordered-two-target-source-replay-plan',
        originalArchive=dict(file='original/'+ORIGINAL_ARCHIVE, **identity(sealed['archive'])),
        originalSeal=dict(file='original/sealed-source-receipt.json', **identity(original_seal_identity)),
        nativeIntegrationRevision=q['integrationRevision'], copies=copies,
        directories={name: 0o700 for name in sorted(directories)}, outputDirectoryMode=0o700,
        commands=[dict(phase='original-source-preparation', cwd='.', argv=['python3',
            'integration/tools/prepare_server_isolated_sources.py', '--source-inputs', 'acquired/source-inputs',
            '--supplements', 'acquired/supplements', '--original-lock', 'original-lock/sources.lock.json', '--output', 'base']),
            dict(phase='native-two-target-driver', cwd='.', argv=['python3', 'integration/tools/build_ordered_extractors.py',
                'build', '--prepared', 'base', '--inputs', 'acquired', '--original-lock', 'original-lock/sources.lock.json',
                '--environment', 'environment/input.json', '--client-policy', 'policy_sources', '--output', 'native',
                '--integration-revision', q['integrationRevision']])],
        commandPathsRelativeToStagingRoot=True, pythonInterpreterCommand='python3',
        prepareReplayRunsCompilerOrNativeProgram=False,
        retainedPreparedTreeIsReadbackReference=True, rebuildPreparationRestoresRecordedGitAndLuaModes=True,
        executionPrerequisites='native AArch64 matching retained relevant ABI/toolchain, loopback-only network namespace',
        externalNetworkingRequired=False, sourceRepositoryFetchRequired=False, clientAssetsRequiredForBuild=False,
        serverProgramsBuildRequired=False, newNativeCompilationPerformed=False)


def replay_script():
    """Standalone stdlib staging helper. It records commands; it never runs them."""
    return r'''#!/usr/bin/env python3
"""Stage exact source-replay inputs; do not run a compiler or native program."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile

LIMIT = 128 << 20
def require(value, message):
    if not value: raise ValueError(message)
def safe(name):
    path = PurePosixPath(name)
    require(name and not path.is_absolute() and '..' not in path.parts and str(path) == name and
            '\\' not in name and all(ord(c) >= 32 for c in name) and '.git' not in path.parts, 'unsafe replay path')
    return Path(name)
def plain_directory(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents): require(stat.S_ISDIR(part.lstat().st_mode), 'linked replay directory')
    return path
def read(path):
    plain_directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    require(stat.S_ISREG(os.fstat(fd).st_mode), 'nonregular replay input')
    return os.fdopen(fd, 'rb')
def digest(path):
    with read(path) as stream:
        size = os.fstat(stream.fileno()).st_size; require(0 <= size <= LIMIT, 'replay input byte bound')
        h = hashlib.sha256(); total = 0
        while block := stream.read(131072): h.update(block); total += len(block); require(total <= size, 'growing input')
        require(total == size, 'short input'); return dict(bytes=size, sha256=h.hexdigest())
def unique(rows):
    result = {}
    for k, v in rows: require(k not in result, 'duplicate replay JSON key'); result[k] = v
    return result
def document(path):
    with read(path) as stream: raw = stream.read((16 << 20)+1)
    require(len(raw) <= 16 << 20, 'replay JSON byte bound')
    return json.loads(raw, object_pairs_hook=unique)
def expected(row): return {k: row[k] for k in ('bytes', 'sha256')}
def parents(path, root):
    require(root in path.parents, 'replay output outside stage')
    for parent in reversed(path.parents):
        if parent == root or root in parent.parents:
            parent.mkdir(mode=0o700, exist_ok=True); plain_directory(parent)
def copy(source, destination, row, root):
    pin = row['identity']; require(digest(source) == expected(pin), 'changed replay staging input')
    parents(destination, root)
    with read(source) as incoming, destination.open('xb') as outgoing:
        total = 0
        while block := incoming.read(min(131072, pin['bytes']-total+1)):
            total += len(block); require(total <= pin['bytes'], 'growing replay copy'); outgoing.write(block)
        outgoing.flush(); os.fsync(outgoing.fileno())
    require(digest(destination) == expected(pin) and digest(source) == expected(pin), 'changed replay copy')
    destination.chmod(row['mode'])
class SourceInfo(tarfile.TarInfo):
    def _proc_pax(self, archive): raise ValueError('replay PAX unsupported')
    def _proc_sparse(self, archive): raise ValueError('replay sparse unsupported')
    def _proc_gnulong(self, archive):
        require(self.type == tarfile.GNUTYPE_LONGNAME and 0 < self.size <= 4096, 'replay longname bound')
        return super()._proc_gnulong(archive)
def extract(bundle, plan, stage):
    archive = bundle/safe(plan['originalArchive']['file']); seal = bundle/safe(plan['originalSeal']['file'])
    require(digest(archive) == expected(plan['originalArchive']) and digest(seal) == expected(plan['originalSeal']),
            'changed original source anchors')
    rows = document(seal)['archiveFiles']; require(0 < len(rows) <= 20000, 'original inventory bound')
    seen = set(); total = 0
    with read(archive) as raw, gzip.GzipFile(fileobj=raw) as compressed:
        with tarfile.open(fileobj=compressed, mode='r|', tarinfo=SourceInfo) as tar:
            for item in tar:
                name = safe(item.name); require(item.isfile() and item.name in rows and item.name not in seen, 'original member set')
                row = rows[item.name]; total += item.size
                require(item.size == row['bytes'] and item.size <= LIMIT and total <= 512 << 20 and
                        item.mode == row['mode'] == 0o444 and item.uid == item.gid == item.mtime == 0 and
                        not item.uname and not item.gname, 'original member metadata')
                target = stage/'original'/name; parents(target, stage)
                h = hashlib.sha256(); count = 0
                with tar.extractfile(item) as incoming, target.open('xb') as outgoing:
                    while block := incoming.read(131072):
                        count += len(block); require(count <= item.size, 'long original member'); h.update(block); outgoing.write(block)
                    outgoing.flush(); os.fsync(outgoing.fileno())
                require(count == row['bytes'] and h.hexdigest() == row['sha256'], 'original member hash')
                target.chmod(0o444); seen.add(item.name); tar.members.clear()
        padding = 0
        while block := compressed.read(131072):
            padding += len(block); require(padding <= 10240 and not any(block), 'original trailing data')
    require(seen == set(rows) and digest(archive) == expected(plan['originalArchive']) and
            digest(seal) == expected(plan['originalSeal']), 'original readback incomplete or changed')
def prepare(bundle, output):
    bundle = plain_directory(bundle); output = Path(os.path.abspath(output)); plain_directory(output.parent)
    require(not os.path.lexists(output) and output not in bundle.parents and bundle not in output.parents and output != bundle,
            'existing or overlapping replay output')
    plan_path = bundle/'replay-plan.json'; plan_id = digest(plan_path); plan = document(plan_path)
    require(plan.get('scope') == 'offline-ordered-two-target-source-replay-plan' and
            plan.get('outputDirectoryMode') == 0o700 and plan.get('prepareReplayRunsCompilerOrNativeProgram') is False,
            'replay plan contract')
    require(0 < len(plan['copies']) <= 20000 and len(plan['directories']) <= 20000 and
            sum(row['identity']['bytes'] for row in plan['copies']) <= 768 << 20, 'replay staging byte/count bound')
    stage = Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-', dir=output.parent))
    try:
        extract(bundle, plan, stage); destinations = set()
        for name, mode in plan['directories'].items():
            safe(name); require(mode == 0o700, 'replay directory mode'); parents(stage/name/'sentinel', stage)
        for row in plan['copies']:
            source = safe(row['source']); destination = safe(row['destination'])
            require(row['sourceTree'] in ('bundle', 'original') and row['mode'] in (0o444, 0o755) and
                    destination.parts[0] in ('acquired', 'integration', 'policy_sources', 'original-lock', 'environment') and
                    str(destination) not in destinations, 'replay staging copy contract')
            destinations.add(str(destination))
            copy((bundle if row['sourceTree'] == 'bundle' else stage/'original')/source,
                 stage/destination, row, stage)
        require(digest(plan_path) == plan_id, 'replay plan changed while staging')
        # Paths remain relative so they survive publication of the private stage.
        commands = dict(scope='offline-source-replay-staged-commands', cwd=str(output), commands=plan['commands'],
            commandsExecuted=False, nativeCompilationPerformed=False, sourceCompanionComplete=False)
        with (stage/'commands.json').open('x') as stream:
            json.dump(commands, stream, sort_keys=True, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        (stage/'commands.json').chmod(0o444)
        # A destination created during staging is preserved. Linux renameat2
        # supplies atomic no-replace publication without an overwrite race.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True); rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        require(rename(-100, os.fsencode(stage), -100, os.fsencode(output), 1) == 0, 'replay no-replace publication failed')
        return commands
    finally:
        if stage.exists(): shutil.rmtree(stage)
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); print(json.dumps(prepare(args.bundle, args.output), sort_keys=True, indent=2))
'''.encode()


def seal(ordered_payload, original_sealed, integration_git_root, client_readme, output):
    pin = load_pin()  # Pending measurements fail before creating any output.
    roots = [archives.directory(Path(os.path.abspath(p))) for p in
             (ordered_payload, original_sealed, integration_git_root)]
    payload, original, git_root = roots
    client_readme = Path(os.path.abspath(client_readme)); output = Path(os.path.abspath(output))
    archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(not dependencies.inside(output, p) and
            not dependencies.inside(p, output) for p in roots) and not dependencies.inside(client_readme, output),
            'ordered-source-output-exists-or-overlaps')
    input_lock = files.identity(LOCK); readme_audit = verify_readme(client_readme, pin)
    creation_files, creation = sealing_recipes(ROOT, os.environ.get('GITHUB_SHA'))
    require(creation['files']['sealing-recipes/runtime/server/ordered-tools-inputs.lock.json'] == input_lock,
            'ordered-source-creation-input-lock-differs')
    q, qid, payload_inventory = verify_native(payload, pin)
    stage = Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-', dir=output.parent))
    try:
        work = stage/'work'; public = stage/'public'; work.mkdir(); public.mkdir()
        sealed = verify_original(original, pin, work/'original')
        prepared, adapted, before, apin = reconstruct(work/'original', payload, q, work)
        after = inventory(adapted)
        observation = verify_observation(payload, q, pin, after, apin)
        recipes = export_recipes(git_root, q['integrationRevision'], payload, work/'integration')
        coverage = dict(formatVersion=1, scope='ordered-extractor-composed-source-coverage',
            basePreparedFiles=before, orderedPreparedFiles=after,
            approvedOrderedAdaptation=dict(before=apin['baseFiles'], after=apin['adaptedFiles'], header=apin['header'],
                receipt=files.identity(adapted/'extractor-adaptation.json')),
            dependencyObservation=observation, integrationRecipes=recipes, sealingRecipes=creation, clientPolicy=readme_audit,
            nativeReceipt=qid, originalNativeReceiptUnchanged=True,
            originalNativeSourceCompanionComplete=q['sourceCompanionComplete'],
            newNativeCompilationPerformed=False)
        engine.put_metadata(work/'source-coverage.json', coverage)
        replay = replay_plan(q, sealed, pin['originalSourceQualification']['receipt'], payload_inventory, recipes['files'])
        engine.put_metadata(work/'replay-plan.json', replay)
        preparation.write_new(work/'prepare-replay.py', replay_script(), 0o444)
        selected = {'source-coverage.json': work/'source-coverage.json', 'replay-plan.json': work/'replay-plan.json',
                    'prepare-replay.py': work/'prepare-replay.py', 'client-reference/README.md': client_readme,
                    **creation_files}
        for name in (ORIGINAL_ARCHIVE, 'qualification.json', 'sealed-source-receipt.json'):
            selected['original/'+name] = original/name
        for name in payload_inventory:
            if not name.startswith('bin/'):
                selected['ordered/'+name] = payload/name
        for prefix, directory in (('integration', work/'integration'), ('prepared', adapted)):
            for path in files.installed_files(directory):
                selected[prefix+'/'+path.relative_to(directory).as_posix()] = path
        require(all(Path(name).suffix.lower() not in ('.o', '.obj', '.a', '.so', '.exe', '.dll', '.debug', '.pdb')
                    and '.git' not in Path(name).parts for name in selected), 'ordered-source-binary-or-git-member')
        selected_ids = {name: files.identity(path) for name, path in selected.items()}
        archive_path = public/SOURCE_ARCHIVE
        rows = isolated.write_source_archive(archive_path, selected)
        require(all(identity(rows[name]) == expected for name, expected in selected_ids.items()),
                'ordered-source-selected-input-changed-during-archive')
        # Both mutable path sets and every immutable public anchor are checked
        # again before the only positive receipt can become visible.
        check_inventory(payload, q['payloadFiles'], extra=('ordered-build.json',))
        require(files.identity(payload/'ordered-build.json') == qid and inventory(prepared) == before and
                inventory(adapted) == after and files.identity(LOCK) == input_lock,
                'ordered-source-input-changed-before-publication')
        for key, name in (('archive', ORIGINAL_ARCHIVE), ('qualification', 'qualification.json'), ('receipt', 'sealed-source-receipt.json')):
            require(files.identity(original/name) == pin['originalSourceQualification'][key],
                    'ordered-source-original-triple-changed-before-publication')
        require(all(files.identity(path) == selected_ids[name] for name, path in selected.items()),
                'ordered-source-retained-input-changed-before-publication')
        verify_sealing_recipes(creation_files, creation)
        engine.verify_archive(archive_path, rows)
        proof = dict(formatVersion=1, scope='complete-ordered-extractor-corresponding-source-companion',
            inputLock=input_lock, archive=dict(file=SOURCE_ARCHIVE, **files.identity(archive_path)), archiveFiles=rows,
            archiveReadbackVerified=True, orderedSourceCompanionComplete=True,
            originalSourceQualification=pin['originalSourceQualification'], originalSourceArchiveFiles=len(sealed['archiveFiles']),
            nativeBuild=pin['nativeBuild'], nativeReceipt=qid, dependencyObservation=observation['observation'],
            sourceInputArchive=q['sourceInputArchive'], sourceInputReceipt=q['sourceInputReceipt'],
            serverBuildSourceLock=pin['serverBuildSourceLock'], adaptationLock=pin['adaptationLock'],
            originalNativeReceiptUnchanged=True, originalNativeSourceCompanionComplete=False,
            sourceCoverage=selected_ids['source-coverage.json'], replayPlan=selected_ids['replay-plan.json'],
            replayPreparationScript=selected_ids['prepare-replay.py'], sealingRecipes=creation,
            fullBaseAndApprovedOverlayVerified=True, actualTargetDependencyObservationVerified=True,
            integrationRecipesAllReadFromNativeGitBlobs=True, clientPolicy=readme_audit,
            newNativeCompilationPerformed=False, globalServerPatchListChanged=False, serverProgramsReplaced=False,
            worldQualified=False, androidRuntimeQualified=False, clientMpqConversionQualified=False,
            customEsteriaDataLoadOrderQualified=False, gameplayQualified=False)
        engine.put_metadata(public/RECEIPT, proof)
        archives.sync_directory(public); transaction.publish_directory(public, output); archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('ordered-payload', 'original-sealed', 'integration-git-root', 'client-readme', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(seal(args.ordered_payload, args.original_sealed, args.integration_git_root,
                          args.client_readme, args.output), sort_keys=True, indent=2))


if __name__ == '__main__': main()
