#!/usr/bin/env python3
"""Preserve exact local server providers and sources in an owned UI draft.

This packages and reads existing source/native-qualified bytes. No compiler,
guest program, SQL, game asset, initialized database or private saved state is
used. Publication only adds missing exact assets; it never creates/finalizes a
release, overwrites assets, moves tags or changes repository settings.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.parse import quote

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import dependency_publication as publication, release_server_dependencies as transport
from tools import qualify_server_providers as stock, qualify_playerbots_programs as helper
from tools import prepare_data_tools_provider as data, provider_server_data_tools as data_provider
from tools import provider_server_extractors as extractors, provider_server_content as content
from tools import package_server_engine as engine, verify_server_build as files, prepare_runtime as archives

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server-components-publication/dependency-release.lock.json'
TAG = 'deps-local-server-f35f04d-21ce4e1b-b7d9b72c'
SCOPE = 'local-server-source-debug-provider-write-once-prerelease'
MAX_BUNDLE = 1900 << 20
MAX_ASSET = (2 << 30) - 1
MAX_RECIPE = 32 << 20
MAX_ROWS = 4096
require = files.require
encoded = engine.canonical
identity = files.identity
SELECTED = ('sources.lock.json', 'runtime/server/server-build-sources.lock.json',
    'runtime/server/programs-provider.lock.json', 'runtime/server/programs-playerbots-provider.lock.json',
    'runtime/server/extractors-provider.lock.json', 'runtime/server/content-provider.lock.json',
    'runtime/server/data-tools-provider.lock.json', 'runtime/server/data-tools-qualified-artifacts.lock.json',
    'runtime/server/playerbots-helper-source-qualified.lock.json', 'runtime/server/installation-native-inputs.lock.json',
    'runtime/server/provider-qualification.lock.json', 'runtime/server/dependency-release.lock.json')
BUNDLES = {
    'server-programs-playerbots-provider.tar.gz': ('helper-providers/programs', helper.provider.verify),
    'server-data-tools-provider.tar.gz': ('data-providers/provider', data_provider.verify),
    'server-extractors-original-provider.tar.gz': ('stock-providers/extractors', extractors.verify),
    'server-content-provider.tar.gz': ('stock-providers/content', content.verify)}
FIXED = {
    'server-dependency-release.lock.json': ROOT / 'runtime/server/dependency-release.lock.json',
    'server-dependency-publication.json': ROOT / 'runtime/evidence/server-dependency-publication-41003838795.json'}
PAYLOAD = set(BUNDLES) | set(FIXED) | {'providers-receipt.json', 'integration-recipe.tar.gz',
    'integration-recipe-receipt.json', 'NOTICE.txt'}
ALL_FILES = PAYLOAD | {'release-manifest.json', 'SHA256SUMS'}
CONSUMER_DIRECTORIES = {'server-programs-playerbots-provider.tar.gz': 'programs',
    'server-data-tools-provider.tar.gz': 'data-tools', 'server-extractors-original-provider.tar.gz': 'extractors',
    'server-content-provider.tar.gz': 'content'}
FALSE_FLAGS = ('compilerExecuted', 'helperExecuted', 'sqlExecuted', 'androidGuestExecuted',
    'androidRuntimeQualified', 'worldserverQualified', 'playerbotsAiQualified', 'gameplayQualified')
NOTICE = b'''Local Esteria ARM64 server programs, schema helper, data tools and content providers.
The helper programs bundle contains its original stock provider, complete original
corresponding sources and paired debug. The composed data-tool and original stock
extractor bundles retain their complete source/debug companions. Original nested
archives, receipts and license notices remain byte-identical. The complete exact
integration recipe is retained separately. The Ubuntu MySQL dependency runtime and
its complete corresponding sources remain in their separately pinned public release.
The original b7 helper's native SQL proof and the separately observed f327 helper's
source evidence are distinct; no proof is transferred to a different executable.
This release qualifies preservation and packaging only, not Android execution,
normal client login, world entry, bot AI or gameplay. No game data, private accounts,
credentials, initialized database/prefix, saves or signing keys are included.
Individual component licenses/notices apply; nothing here relicenses a component.
'''


def selected_inputs():
    return {name: identity(ROOT / name) for name in SELECTED}


def fresh(path):
    path = Path(os.path.abspath(path)); archives.directory(path.parent, create=True)
    require(not os.path.lexists(path), 'local-server-release-existing-output-preserved')
    path.mkdir(mode=0o700)
    return path


def validate_inventory(rows, maximum=MAX_BUNDLE):
    require(type(rows) is dict and 0 < len(rows) <= MAX_ROWS, 'local-server-release-inventory-bound')
    total = 0; names = set()
    for name, row in rows.items():
        require(type(name) is str and len(name.encode()) <= 4096, 'local-server-release-path-bound')
        engine.content.safe_path(name)
        require(name.casefold() not in names and type(row) is dict and set(row) == {'bytes', 'sha256', 'mode'} and
            type(row['bytes']) is int and 0 <= row['bytes'] <= MAX_BUNDLE and
            re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')) and row.get('mode') in (0o444, 0o555),
            'local-server-release-member-identity-or-mode')
        names.add(name.casefold()); total += row['bytes']
    require(total <= maximum, 'local-server-release-expanded-bound')
    return total


def inventory(root):
    rows = {p.relative_to(root).as_posix(): dict(identity(p), mode=0o555 if p.stat().st_mode & 0o111 else 0o444)
        for p in files.installed_files(root)}
    validate_inventory(rows)
    return rows


def write_bundle(root, target, rows):
    """Stored gzip gives deterministic bytes without re-compressing original archives."""
    validate_inventory(rows)
    require(not os.path.lexists(target), 'local-server-release-existing-bundle-preserved')
    with target.open('xb') as raw:
        with gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0, compresslevel=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                for name, row in sorted(rows.items()):
                    item = tarfile.TarInfo(name); item.size, item.mode = row['bytes'], row['mode']
                    item.uid = item.gid = item.mtime = 0; item.uname = item.gname = ''
                    with files.plain_file(root / name) as incoming:
                        reader = engine.package.HashReader(incoming, row)
                        archive.addfile(item, reader); reader.finish()
        raw.flush(); os.fsync(raw.fileno())
    require(target.stat().st_size <= MAX_ASSET, 'local-server-release-asset-must-stay-below-two-GiB')
    read_bundle(target, rows)


def read_bundle(path, rows, output=None, maximum=MAX_BUNDLE):
    validate_inventory(rows, maximum)
    if output is not None:
        require(not os.path.lexists(output), 'local-server-release-existing-extraction-preserved')
        archives.directory(output.parent); output.mkdir(mode=0o700)
    seen = set()
    with files.plain_file(path) as raw, archives.bounded_tar(raw,
            dict(entries=MAX_ROWS, pathBytes=4096, fileBytes=maximum)) as archive:
        for member in archive:
            require(member.isfile() and member.name in rows and member.name not in seen,
                    'local-server-release-member-set-or-type')
            row = rows[member.name]
            require(member.size == row['bytes'] and member.mode == row['mode'] and
                member.uid == member.gid == member.mtime == 0 and not member.uname and not member.gname,
                'local-server-release-member-metadata')
            if output is None:
                with archive.extractfile(member) as incoming:
                    require(archives.hash_stream(incoming, member.size) == row['sha256'],
                            'local-server-release-member-hash')
            else:
                target = output / member.name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(member) as incoming, target.open('xb') as outgoing:
                    require(archives.hash_stream(incoming, member.size, outgoing) == row['sha256'],
                            'local-server-release-member-hash')
                    outgoing.flush(); os.fsync(outgoing.fileno())
                target.chmod(row['mode'])
            seen.add(member.name); archive.members.clear()
    require(seen == set(rows), 'local-server-release-members-missing')
    # The bounded first pass protects parsing/extraction. The existing strict
    # server archive checker additionally rejects nonzero data after tar EOF,
    # rather than authenticating bytes outside the declared member closure.
    engine.verify_archive(path, rows)


def recipe_inputs(revision):
    require(re.fullmatch('[0-9a-f]{40}', revision or ''), 'local-server-release-exact-recipe-commit-required')
    raw = subprocess.check_output(['git', 'ls-tree', '-rlz', revision], cwd=ROOT, timeout=30)
    require(len(raw) <= 2 << 20, 'local-server-release-git-roster-bound')
    rows = {}; total = 0
    for entry in raw.split(b'\0'):
        if not entry: continue
        metadata, name = entry.split(b'\t', 1); mode, kind, blob, size = metadata.split()
        require(mode in (b'100644', b'100755') and kind == b'blob',
                'local-server-release-recipe-plain-git-files-required')
        name = name.decode('utf-8'); engine.content.safe_path(name)
        require(name not in rows and len(name.encode()) <= 4096, 'local-server-release-recipe-path')
        require(0 <= int(size) <= MAX_RECIPE - total and len(rows) < MAX_ROWS,
                'local-server-release-recipe-git-byte-bound')
        body = subprocess.check_output(['git', 'cat-file', 'blob', blob.decode()], cwd=ROOT, timeout=30)
        total += len(body)
        require(len(body) == int(size) and total <= MAX_RECIPE and len(rows) < MAX_ROWS and
            hashlib.sha1(b'blob ' + str(len(body)).encode() + b'\0' + body).hexdigest() == blob.decode(),
            'local-server-release-recipe-git-byte-bound')
        row = dict(bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), mode=0o555 if mode == b'100755' else 0o444)
        require(checkout_matches(name, body, row),
                'local-server-release-executing-recipe-changed:' + name)
        rows[name] = row
    validate_inventory(rows, MAX_RECIPE)
    require('tools/release_local_server_components.py' in rows and
        '.github/workflows/preserve-local-server-components.yml' in rows,
        'local-server-release-recipe-not-yet-published')
    return dict(sorted(rows.items()))


def checkout_matches(name, body, row):
    if identity(ROOT / name) == {k: row[k] for k in ('bytes', 'sha256')}: return True
    # Git's committed .gitattributes deliberately checks the Windows wrapper
    # out with CRLF, while the canonical blob uses LF. This sole known checkout
    # conversion is not a source edit; arbitrary files or line changes still fail.
    if name != 'gradlew.bat' or b'\r' in body or len(body) > 64 << 10: return False
    with files.plain_file(ROOT / '.gitattributes') as source: attributes = source.read((64 << 10) + 1)
    if len(attributes) > 64 << 10 or b'*.bat text eol=crlf' not in attributes.splitlines(): return False
    expected = body.replace(b'\n', b'\r\n')
    with files.plain_file(ROOT / name) as source: actual = source.read(len(expected) + 1)
    return actual == expected


def write_recipe(revision, rows, target):
    """Archive canonical Git blob bytes, independently of checkout EOL filters."""
    validate_inventory(rows, MAX_RECIPE)
    with tempfile.TemporaryDirectory(prefix='esteria-local-server-recipe-', dir=target.parent) as tmp:
        tree = Path(tmp)
        for name, row in rows.items():
            raw = subprocess.check_output(['git', 'cat-file', 'blob', revision + ':' + name], cwd=ROOT, timeout=30)
            require(dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()) ==
                {k: row[k] for k in ('bytes', 'sha256')}, 'local-server-release-canonical-recipe-blob-differs')
            path = tree / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with path.open('xb') as output: output.write(raw)
            path.chmod(row['mode'])
        write_bundle(tree, target, rows)


def prepare(output, api=None):
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output), 'local-server-release-existing-inputs-preserved')
    archives.directory(output.parent, create=True)
    require(shutil.disk_usage(output.parent).free >= 20 << 30, 'local-server-release-preparation-requires-twenty-GiB-free')
    output.mkdir(mode=0o700)
    api = api or publication.Github(os.environ.get('GITHUB_TOKEN'))
    stock.acquire(output / 'stock-inputs', api)
    stock.build(output / 'stock-inputs', output / 'stock-providers')
    helper.acquire(output / 'helper-inputs', api)
    helper.build(output / 'stock-providers', output / 'helper-inputs', output / 'helper-providers')
    data.acquire(output / 'data-inputs', api)
    data.build(output / 'data-inputs', output / 'data-providers')
    proof = dict(formatVersion=1, scope='source-and-debug-verified-local-server-publication-inputs',
        selectedInputs=selected_inputs(), providers={name: verify(output / relative)
            for name, (relative, verify) in BUNDLES.items()}, **{k: False for k in FALSE_FLAGS})
    engine.put_metadata(output / 'preparation.json', proof)
    return proof


def dependency_binding(directory):
    locked = transport.small_json(directory / 'server-dependency-release.lock.json')
    published = transport.small_json(directory / 'server-dependency-publication.json')
    selected = helper.provider.load_pin()[0]
    archive = selected['requiredServerRuntimeArchive']
    require(locked['tag'] == published['tag'] == 'deps-server-arm64-b06de55-21a9e8020aac' and
        locked['repository'] == published['repository'] == transport.REPOSITORY and
        locked['targetCommit'] == published['targetCommit'] and published['publisherNeverOverwrites'] is True and
        published['assets'][archive['file']]['sha256'] == archive['sha256'] and
        published['assets'][archive['file']]['bytes'] == archive['bytes'],
        'local-server-release-durable-dependency-binding-differs')


def validate_payload(directory, lock):
    for name, path in FIXED.items():
        require(identity(directory / name) == identity(path), 'local-server-release-fixed-binding-differs')
    require((directory / 'NOTICE.txt').read_bytes() == NOTICE, 'local-server-release-notice-differs')
    dependency_binding(directory)
    receipt = transport.small_json(directory / 'providers-receipt.json')
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'complete-local-server-provider-bundles' and
        receipt.get('selectedInputs') == lock['selectedInputs'] and set(receipt.get('providers', {})) == set(BUNDLES) and
        all(receipt.get(k) is False for k in FALSE_FLAGS), 'local-server-release-provider-receipt-selection')
    for name, (_, verifier) in BUNDLES.items():
        row = receipt['providers'][name]
        require(set(row) == {'archive', 'members'} and row['archive'] == identity(directory / name),
                'local-server-release-provider-archive-binding')
        with tempfile.TemporaryDirectory(prefix='esteria-local-server-release-readback-') as tmp:
            provider = Path(tmp) / 'provider'
            read_bundle(directory / name, row['members'], provider)
            verifier(provider)
    recipe = transport.small_json(directory / 'integration-recipe-receipt.json')
    require(set(recipe) == {'formatVersion', 'scope', 'targetCommit', 'archive', 'members'} and
        recipe['formatVersion'] == 1 and recipe['scope'] == 'exact-local-server-integration-recipe' and
        recipe['targetCommit'] == lock['targetCommit'] and recipe['members'] == lock['recipeInputs'] and
        recipe['archive'] == identity(directory / 'integration-recipe.tar.gz'), 'local-server-release-recipe-receipt')
    read_bundle(directory / 'integration-recipe.tar.gz', recipe['members'], maximum=MAX_RECIPE)


def load_lock(path, *, pending=False):
    value = transport.small_json(path)
    require(type(value) is dict and set(value) == {'formatVersion', 'scope', 'repository', 'tag',
        'state', 'targetCommit', 'ownedDraftReleaseId', 'selectedInputs', 'recipeInputs', 'files'} and
        type(value['formatVersion']) is int and value['formatVersion'] == 1 and value['scope'] == SCOPE and
        value['repository'] == transport.REPOSITORY and value['tag'] == TAG,
        'local-server-release-lock-schema')
    if value['state'] == 'pending-measurement':
        require(pending and all(value[k] is None for k in
            ('targetCommit', 'ownedDraftReleaseId', 'selectedInputs', 'recipeInputs', 'files')),
            'local-server-release-real-measurement-required')
        return value
    require(value['state'] in ('measured-unbound', 'owned-draft-bound') and
        value['selectedInputs'] == selected_inputs() and value['recipeInputs'] == recipe_inputs(value['targetCommit']) and
        type(value['files']) is dict and set(value['files']) == PAYLOAD,
        'local-server-release-exact-measured-lock-required')
    for row in value['files'].values():
        require(type(row) is dict and set(row) == {'bytes', 'sha256'} and type(row['bytes']) is int and
            0 < row['bytes'] <= MAX_ASSET and re.fullmatch('[0-9a-f]{64}', row['sha256']),
            'local-server-release-asset-pin')
    require((value['state'] == 'measured-unbound' and value['ownedDraftReleaseId'] is None) or
        (value['state'] == 'owned-draft-bound' and type(value['ownedDraftReleaseId']) is int and
            value['ownedDraftReleaseId'] > 0), 'local-server-release-owned-draft-binding-required')
    return value


def stage(inputs, target, output, lock_output=None, existing_lock=None):
    inputs, output = Path(os.path.abspath(inputs)), Path(os.path.abspath(output))
    require(not os.path.lexists(output) and (lock_output is None or not os.path.lexists(lock_output)) and
        inputs != output and output not in inputs.parents and inputs not in output.parents,
        'local-server-release-existing-or-overlapping-output-preserved')
    recipe, selected = recipe_inputs(target), selected_inputs()
    validated = {name: verifier(inputs / relative) for name, (relative, verifier) in BUNDLES.items()}
    output = fresh(output); providers = {}
    for name, (relative, _) in BUNDLES.items():
        root = inputs / relative; rows = inventory(root)
        write_bundle(root, output / name, rows)
        providers[name] = dict(archive=identity(output / name), members=rows)
    engine.put_metadata(output / 'providers-receipt.json', dict(formatVersion=1,
        scope='complete-local-server-provider-bundles', selectedInputs=selected, providers=providers,
        **{k: False for k in FALSE_FLAGS}))
    write_recipe(target, recipe, output / 'integration-recipe.tar.gz')
    engine.put_metadata(output / 'integration-recipe-receipt.json', dict(formatVersion=1,
        scope='exact-local-server-integration-recipe', targetCommit=target,
        archive=identity(output / 'integration-recipe.tar.gz'), members=recipe))
    for name, path in FIXED.items(): engine.copy_verified(path, output / name, identity(path))
    (output / 'NOTICE.txt').write_bytes(NOTICE)
    measured = {p.name: identity(p) for p in sorted(output.iterdir())}
    require(set(measured) == PAYLOAD, 'local-server-release-payload-file-set')
    lock = dict(formatVersion=1, scope=SCOPE, repository=transport.REPOSITORY, tag=TAG,
        state='measured-unbound', targetCommit=target, ownedDraftReleaseId=None,
        selectedInputs=selected, recipeInputs=recipe, files=measured)
    if existing_lock is not None:
        comparison = dict(existing_lock, state='measured-unbound', ownedDraftReleaseId=None)
        require(lock == comparison, 'local-server-release-reproduction-differs')
        lock = existing_lock
    manifest = dict(formatVersion=1, scope=SCOPE, targetCommit=target, tag=TAG,
        selectedInputs=selected, assets=measured)
    engine.put_metadata(output / 'release-manifest.json', manifest)
    sums = dict(measured, **{'release-manifest.json': identity(output / 'release-manifest.json')})
    (output / 'SHA256SUMS').write_text(''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(sums.items())))
    verify(output, lock)
    if lock_output is not None: engine.put_metadata(Path(lock_output), lock)
    return dict(lock=lock, inputProvidersVerified=validated)


def verify(directory, lock):
    directory = archives.directory(directory)
    require({p.name for p in directory.iterdir()} == ALL_FILES, 'local-server-release-file-set')
    for name, row in lock['files'].items():
        require(identity(directory / name) == row, 'local-server-release-whole-asset-hash-differs:' + name)
    manifest = dict(formatVersion=1, scope=SCOPE, targetCommit=lock['targetCommit'], tag=TAG,
        selectedInputs=lock['selectedInputs'], assets=lock['files'])
    require((directory / 'release-manifest.json').read_bytes() == encoded(manifest),
            'local-server-release-manifest-differs')
    sums = dict(lock['files'], **{'release-manifest.json': identity(directory / 'release-manifest.json')})
    require((directory / 'SHA256SUMS').read_bytes() == ''.join(row['sha256'] + '  ' + name + '\n'
        for name, row in sorted(sums.items())).encode(), 'local-server-release-checksums-differ')
    validate_payload(directory, lock)
    return {p.name: identity(p) for p in sorted(directory.iterdir())}


def body(lock):
    return ('Dependency-only archival prerelease: Esteria local ARM64 server providers.\n\n'
        'Exact packaging recipe `' + lock['targetCommit'] + '`. Original stock programs/source/debug, '
        'the source-sealed original b7 schema helper, composed data4 tools and original stock extractors '
        'are preserved with full source/debug and notices. The complete integration recipe and exact '
        'separate public Ubuntu MySQL runtime/source release are pinned. All original nested archives '
        'and receipts remain byte-identical.\n\n'
        'Preservation and install packaging only. Android execution, normal client login, world entry, '
        'bot AI and gameplay remain unqualified. No APK, game data, credentials, initialized database, '
        'prefix, saves or signing keys.\n\n'
        'This uploader only adds missing exact assets to the explicitly bound owned UI draft. '
        'It never creates/finalizes releases, moves tags, replaces assets or changes repository settings.\n')


class OwnedDraftPublication(publication.DraftPublication):
    def check_release(self, release):
        super().check_release(release)
        require(type(self.lock.get('ownedDraftReleaseId')) is int and
            release.get('id') == self.lock['ownedDraftReleaseId'],
            'local-server-release-owned-draft-id-differs; no-mutation')

    def upload_draft(self, api, candidate):
        require(self.lock.get('state') == 'owned-draft-bound' and
            type(self.lock.get('ownedDraftReleaseId')) is int and self.lock['ownedDraftReleaseId'] > 0,
            'local-server-release-owned-draft-binding-required-before-upload')
        return super().upload_draft(api, candidate)


def fetch_published(output, lock, api=None):
    """Anonymous complete public download: no Actions artifact is requested."""
    require(lock.get('state') == 'owned-draft-bound' and type(lock.get('ownedDraftReleaseId')) is int,
            'local-server-release-owned-public-selection-required')
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output), 'local-server-release-existing-public-download-preserved')
    archives.directory(output.parent, create=True)
    require(shutil.disk_usage(output.parent).free >= 6 << 30, 'local-server-release-public-readback-requires-six-GiB-free')
    api = publication.Github() if api is None else api
    publisher = OwnedDraftPublication(lock, body(lock), lambda _: {})
    release = api.json('/releases/tags/' + quote(lock['tag'], safe=''))
    publisher.check_release(release); publisher.check_ref(api)
    require(release.get('draft') is False, 'local-server-release-must-be-public-before-download')
    rows = api.json('/releases/' + str(release['id']) + '/assets?per_page=100')
    assets = {row['name']: row for row in rows}
    require(len(assets) == len(rows) and set(assets) == ALL_FILES,
            'local-server-release-public-asset-closure')
    expected = dict(lock['files'])
    manifest = encoded(dict(formatVersion=1, scope=SCOPE, targetCommit=lock['targetCommit'], tag=TAG,
        selectedInputs=lock['selectedInputs'], assets=lock['files']))
    expected['release-manifest.json'] = dict(bytes=len(manifest), sha256=hashlib.sha256(manifest).hexdigest())
    sums = ''.join(row['sha256'] + '  ' + name + '\n' for name, row in sorted(expected.items())).encode()
    expected['SHA256SUMS'] = dict(bytes=len(sums), sha256=hashlib.sha256(sums).hexdigest())
    for name, row in assets.items():
        require(row.get('state') == 'uploaded' and row.get('size') == expected[name]['bytes'] and
            row.get('digest') == 'sha256:' + expected[name]['sha256'],
            'local-server-release-public-asset-metadata-differs')
    output = fresh(output)
    for name, row in sorted(assets.items()):
        api.download(transport.API + '/releases/assets/' + str(row['id']), output / name, expected[name])
    verified = verify(output, lock)
    return dict(formatVersion=1, scope='anonymous-complete-local-server-public-source-debug-readback',
        releaseId=release['id'], targetCommit=lock['targetCommit'], assets=verified,
        allStoredBytesReadBack=True, completeOriginalSourceAndPairedDebugVerified=True,
        actionsArtifactsUsed=False, **{k: False for k in FALSE_FLAGS})


def consume(directory, output, lock):
    """Restore production provider directories from a fully verified release."""
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output), 'local-server-release-existing-consumer-output-preserved')
    directory = archives.directory(Path(os.path.abspath(directory)))
    verify(directory, lock)
    output = fresh(output)
    receipt = transport.small_json(directory / 'providers-receipt.json')
    providers = {}
    for name, (_, verifier) in BUNDLES.items():
        target = output / CONSUMER_DIRECTORIES[name]
        read_bundle(directory / name, receipt['providers'][name]['members'], target)
        providers[CONSUMER_DIRECTORIES[name]] = verifier(target)
    return dict(formatVersion=1, scope='public-local-server-provider-directories-restored',
        selectedInputs=lock['selectedInputs'], providers=providers, actionsArtifactsUsed=False,
        completeOriginalSourceAndPairedDebugVerified=True, **{k: False for k in FALSE_FLAGS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'stage', 'verify', 'body', 'upload-draft', 'verify-published',
        'fetch-published', 'consume'))
    parser.add_argument('--release-lock', type=Path, default=LOCK); parser.add_argument('--inputs', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--target'); parser.add_argument('--wait-seconds', type=int, default=0)
    args = parser.parse_args()
    if args.operation == 'prepare': result = prepare(args.output)
    elif args.operation == 'stage':
        require(args.target and args.inputs and args.output, 'local-server-release-stage-inputs-required')
        selected = load_lock(args.release_lock, pending=True)
        existing = None if selected['state'] == 'pending-measurement' else selected
        lock_output = args.output.parent / 'measured-release.lock.json' if existing is None else None
        result = stage(args.inputs, args.target, args.output, lock_output, existing)
    else:
        lock = load_lock(args.release_lock)
        if args.operation == 'body': print(body(lock), end=''); return
        if args.operation == 'verify': result = verify(args.inputs, lock)
        elif args.operation == 'fetch-published': result = fetch_published(args.output, lock)
        elif args.operation == 'consume': result = consume(args.inputs, args.output, lock)
        else:
            publisher = OwnedDraftPublication(lock, body(lock), lambda path: verify(path, lock))
            api = publication.Github(os.environ.get('GITHUB_TOKEN'))
            result = (publisher.upload_draft(api, args.inputs) if args.operation == 'upload-draft' else
                publisher.verify_published(api, args.inputs, args.wait_seconds))
    if args.output and args.operation not in ('prepare', 'stage', 'fetch-published', 'consume'): engine.put_metadata(args.output, result)
    else: print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__': main()
