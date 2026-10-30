#!/usr/bin/env python3
"""Add original source notices to a separately identified engine runtime archive.

The original engine/debug and source-input packages remain unchanged. This is a
notice-preservation layer, not a complete source companion or Android provider.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import manifest_server_modules as modules, package_server_content as transaction
from tools import package_server_engine as engine, package_server_engine_source_inputs as sources
from tools import prepare_runtime as archives, verify_server_build as files
from tools import verify_server_engine_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]
SOURCE_LOCK = ROOT / 'sources.lock.json'
AUDIT = ROOT / 'runtime/server/engine-source-audit.json'
ARCHIVE = 'server-programs-runtime-arm64.tar.gz'
SOURCE_ARCHIVE = 'server-engine-source-inputs.tar.gz'
SOURCE_RECEIPT = 'source-inputs-receipt.json'
LUA_PATH = 'external/lua-5.2.4.tar.gz'
LUA_NOTICE = 'lua-5.2.4/doc/readme.html'
LUA_NOTICE_IDENTITY = dict(bytes=13160, sha256='a686d9158c8878ee4c6e1c90d719949c2b70031b74d6e945e6e218a063ebcb20')
MAX_SOURCE_FILES = 20000
MAX_SOURCE_BYTES = 4 * 1024**3
MAX_CAPTURE = 16 * 1024**2
require = files.require


def parsed(raw):
    def pairs(rows):
        result = {}
        for name, value in rows:
            require(name not in result, 'duplicate-notice-input-json-key')
            result[name] = value
        return result
    value = json.loads(raw, object_pairs_hook=pairs)
    require(isinstance(value, dict), 'notice-input-json-object-required')
    return value


def plain_identity(row):
    return engine.identity(row)


def git_identity(row):
    plain_identity(row)
    require(re.fullmatch('[0-9a-f]{40}', row.get('gitBlob', '')) and
            row.get('gitMode') in ('100644', '100755'), 'notice-source-git-identity-required')
    return {key: row[key] for key in ('bytes', 'sha256', 'gitBlob')}


def load_audit():
    audit, identity = modules.read_json(AUDIT)
    rows = audit.get('noticeCandidates')
    require(audit.get('formatVersion') == 1 and isinstance(rows, list) and len(rows) == 65,
            'complete-reviewed-engine-notice-audit-required')
    seen = set()
    for row in rows:
        engine.content.safe_path(row['path'])
        require(row['path'].casefold() not in seen and type(row.get('bytes')) is int and
                0 < row['bytes'] <= MAX_CAPTURE and re.fullmatch('[0-9a-f]{40}', row.get('gitBlobSha1', '')) and
                row.get('mode') == '100644' and row.get('gitRepository') in (None, 'Eluna'),
                'invalid-engine-notice-candidate')
        seen.add(row['path'].casefold())
    return audit, identity


def source_inventory(manifest):
    """Reconstruct every archive member from the actual preserved manifest."""
    require(isinstance(manifest.get('pristineGitFiles'), dict) and
            set(manifest['pristineGitFiles']) == {'server', 'eluna', 'integration'} and
            isinstance(manifest.get('localInputs'), dict), 'complete-source-input-manifest-required')
    expected = {}
    def add(target, row, origin, source):
        engine.content.safe_path(target)
        require(target not in expected, 'source-input-manifest-target-collision')
        expected[target] = dict(git_identity(row), origin=origin, source=source)
    for origin, rows in manifest['pristineGitFiles'].items():
        require(isinstance(rows, dict) and len(rows) <= MAX_SOURCE_FILES, 'source-pristine-file-bound')
        for name, row in rows.items():
            engine.content.safe_path(name)
            target = ('integration/' + name if origin == 'integration' else
                      'source/' + (engine.content.ELUNA + '/' if origin == 'eluna' else '') + name)
            add(target, row, origin, ('integration/' if origin == 'integration' else '') + name)
    for name, row in manifest['localInputs'].items():
        add(name, row, 'local', 'local/' + name)
    require(len(expected) < MAX_SOURCE_FILES and len(expected) == len({name.casefold() for name in expected}),
            'source-input-manifest-file-bound-or-case-collision')
    return expected


def read_sources(source_inputs, derivative, audit, audit_identity):
    receipt_path = source_inputs / SOURCE_RECEIPT
    receipt, receipt_identity = modules.read_json(receipt_path)
    require(receipt.get('formatVersion') == 1 and receipt.get('scope') == 'unsealed-engine-source-input-package' and
            receipt.get('completeArchiveReadbackVerified') is True and receipt.get('sourceCompanionComplete') is False and
            receipt.get('originalBuild') == derivative['originalBuild'] and
            receipt.get('originalCompiledModules') == derivative['originalModules'] and
            receipt.get('sourceLock') == derivative['sourcesLock'], 'source-input-engine-provenance-mismatch')
    archive = source_inputs / SOURCE_ARCHIVE
    require(receipt.get('archive', {}).get('file') == SOURCE_ARCHIVE and
            files.identity(archive) == plain_identity(receipt['archive']), 'source-input-archive-identity-mismatch')
    inventory = receipt.get('archiveFiles')
    require(isinstance(inventory, dict) and 1 <= len(inventory) <= MAX_SOURCE_FILES,
            'source-input-archive-inventory-bound')
    total = 0
    for name, row in inventory.items():
        engine.content.safe_path(name); total += plain_identity(row)['bytes']
    require(total <= MAX_SOURCE_BYTES, 'source-input-archive-byte-bound')
    notice_members = {'source/' + row['path'] for row in audit['noticeCandidates']}
    capture = notice_members | {LUA_PATH, 'metadata/source-inputs.json', 'metadata/source-selection-audit.json'}
    seen, captured = set(), {}
    with files.plain_file(archive) as compressed, archives.bounded_tar(compressed,
            dict(entries=MAX_SOURCE_FILES, pathBytes=4096, fileBytes=MAX_SOURCE_BYTES)) as package:
        for item in package:
            engine.content.safe_path(item.name)
            require(item.isfile() and item.name in inventory and item.name not in seen,
                    'source-input-archive-member-set')
            row = inventory[item.name]
            require(item.size == row['bytes'] and item.mode == 0o644 and item.uid == item.gid == item.mtime == 0 and
                    not item.uname and not item.gname, 'source-input-archive-member-metadata')
            require(item.name not in capture or item.size <= MAX_CAPTURE, 'notice-capture-size-bound')
            digest = hashlib.sha256(); blob = hashlib.sha1(('blob ' + str(item.size) + '\0').encode())
            chunks = []
            with package.extractfile(item) as stream:
                remaining = item.size
                while remaining:
                    block = stream.read(min(files.BUFFER, remaining))
                    require(block, 'source-input-archive-short-read')
                    remaining -= len(block); digest.update(block); blob.update(block)
                    if item.name in capture: chunks.append(block)
                require(not stream.read(1), 'source-input-archive-file-overrun')
            require(digest.hexdigest() == row['sha256'] and
                    ('gitBlob' not in row or blob.hexdigest() == row['gitBlob']),
                    'source-input-archive-file-identity-mismatch')
            if item.name in capture: captured[item.name] = b''.join(chunks)
            seen.add(item.name); package.members.clear()
    require(seen == set(inventory) and capture <= seen, 'source-input-archive-members-missing')
    manifest_raw = captured['metadata/source-inputs.json']
    require(dict(bytes=len(manifest_raw), sha256=hashlib.sha256(manifest_raw).hexdigest()) == receipt.get('manifest'),
            'source-input-manifest-identity-mismatch')
    manifest = parsed(manifest_raw)
    require(manifest.get('formatVersion') == 1 and manifest.get('scope') == 'unsealed-engine-source-input-preservation' and
            manifest.get('originalBuild') == derivative['originalBuild'] and
            manifest.get('originalCompiledModules') == derivative['originalModules'] and
            manifest.get('sourceLock') == derivative['sourcesLock'] and manifest.get('source') == derivative['serverSource'] and
            manifest.get('originalIntegrationRevision') == derivative['integrationRevision'] and
            manifest.get('buildId') == derivative['buildId'] and
            manifest.get('enabledModules') == derivative['enabledModules'] and
            manifest.get('sourceSelectionAudit') == audit_identity and
            manifest.get('luaOriginalArchiveRetained') is True and
            manifest.get('selectedSourceNoticesRetained') is True and
            manifest.get('sourceCompanionComplete') is False, 'source-input-manifest-engine-binding-mismatch')
    expected = source_inventory(manifest)
    expected['metadata/source-inputs.json'] = receipt['manifest']
    require(inventory == expected, 'source-input-archive-differs-from-actual-manifest')
    audit_raw = captured['metadata/source-selection-audit.json']
    require(dict(bytes=len(audit_raw), sha256=hashlib.sha256(audit_raw).hexdigest()) == audit_identity and
            parsed(audit_raw) == audit, 'source-input-audit-differs-from-reviewed-notice-selection')
    for name, expected_identity in (('metadata/server-build.json', derivative['originalBuild']),
                                    ('metadata/server-modules.json', derivative['originalModules']),
                                    ('integration/sources.lock.json', derivative['sourcesLock'])):
        require(name in inventory and plain_identity(inventory[name]) == expected_identity,
                'source-input-original-receipt-binding-mismatch')
    return receipt, receipt_identity, manifest, captured


def lua_notice(raw):
    require(len(raw) <= sources.LUA_MAX_BYTES and hashlib.sha256(raw).hexdigest() == sources.LUA_SHA256,
            'original-lua-archive-required-for-notice')
    result = None; seen = set()
    with archives.bounded_tar(io.BytesIO(raw), dict(entries=512, pathBytes=4096, fileBytes=8 * 1024**2)) as archive:
        for item in archive:
            engine.content.safe_path(item.name)
            require(item.name not in seen and (item.isfile() or item.isdir()), 'lua-original-member-contract')
            seen.add(item.name)
            if item.name == LUA_NOTICE:
                require(item.isfile() and item.size == LUA_NOTICE_IDENTITY['bytes'], 'lua-notice-member-contract')
                with archive.extractfile(item) as stream: result = stream.read(MAX_CAPTURE + 1)
            archive.members.clear()
    require(result is not None and dict(bytes=len(result), sha256=hashlib.sha256(result).hexdigest()) == LUA_NOTICE_IDENTITY,
            'lua-original-license-bearing-file-mismatch')
    return result


def write_notice(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    path.chmod(0o444)


def build(engine_package, source_inputs, output):
    inputs = [archives.directory(Path(os.path.abspath(value))) for value in (engine_package, source_inputs)]
    engine_package, source_inputs = inputs
    output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output) and all(value != output and value not in output.parents and output not in value.parents
            for value in inputs), 'notice-output-exists-or-overlaps-input')
    original, original_identity, _ = runtime.load_receipt(engine_package / 'package-receipt.json')
    derivative = original['derivative']
    require(derivative['sourcesLock'] == files.identity(SOURCE_LOCK), 'notice-engine-source-lock-is-not-current')
    audit, audit_identity = load_audit()
    require(audit.get('serverRevision') == derivative['serverSource']['commit'], 'notice-audit-server-revision-mismatch')
    source_receipt, source_identity, manifest, captured = read_sources(source_inputs, derivative, audit, audit_identity)
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        payload = stage / 'runtime'
        runtime.extract(engine_package / 'package-receipt.json', payload)
        compiled, _ = modules.read_json(payload / 'provenance/server-modules.json')
        runtime.verify_install(payload, compiled, payload / 'provenance/sources.lock.json', engine_package / 'package-receipt.json')
        notices = {}
        for row in audit['noticeCandidates']:
            name = row['path']; source_name = 'source/' + name
            origin = 'eluna' if row.get('gitRepository') == 'Eluna' else 'server'
            pristine_name = name[len(engine.content.ELUNA) + 1:] if origin == 'eluna' else name
            pristine = manifest['pristineGitFiles'][origin].get(pristine_name, {})
            raw = captured[source_name]
            require(len(raw) == row['bytes'] and pristine.get('bytes') == row['bytes'] and
                    pristine.get('gitBlob') == row['gitBlobSha1'] and pristine.get('gitMode') == row['mode'],
                    'audited-source-notice-identity-mismatch:' + name)
            target = 'notices/source/' + name
            write_notice(payload / target, raw)
            notices[target] = dict(plain_identity(pristine), gitBlob=row['gitBlobSha1'], sourcePath=name,
                                   sourceArchivePath=source_name, originalBytesPreserved=True)
        raw = lua_notice(captured[LUA_PATH])
        target = 'notices/external/' + LUA_NOTICE
        write_notice(payload / target, raw)
        notices[target] = dict(LUA_NOTICE_IDENTITY, sourcePath=LUA_NOTICE, sourceArchivePath=LUA_PATH,
                               originalBytesPreserved=True)
        archive = stage / ARCHIVE
        inventory = engine.write_archive(payload, archive)
        previous = original['packages']['runtime']['inventory']
        require(set(inventory) == set(previous) | set(notices) and
                all(inventory[name] == row for name, row in previous.items()) and
                all(inventory[name] == dict(plain_identity(row), mode=0o444) for name, row in notices.items()),
                'notice-runtime-changed-original-files-or-notice-bytes')
        require(files.identity(engine_package / 'package-receipt.json') == original_identity and
                files.identity(source_inputs / SOURCE_RECEIPT) == source_identity,
                'original-input-receipt-changed-during-notice-packaging')
        require(files.identity(engine_package / original['packages']['runtime']['archiveFile']) ==
                original['packages']['runtime']['archive'] and
                files.identity(source_inputs / SOURCE_ARCHIVE) == plain_identity(source_receipt['archive']),
                'original-input-archive-changed-during-notice-packaging')
        receipt = dict(formatVersion=1, scope='notice-augmented-server-programs-runtime',
            archive=dict(file=ARCHIVE, **files.identity(archive)), archiveFiles=inventory,
            derivative=derivative, originalEnginePackageReceipt=original_identity,
            originalRuntimeArchive=original['packages']['runtime']['archive'],
            sourceInputs=dict(receipt=source_identity, archive=source_receipt['archive'], manifest=source_receipt['manifest']),
            noticeAudit=audit_identity, notices=notices, originalRuntimeFilesUnchanged=True,
            originalReceiptsPreserved=True, originalNoticeBytesPreserved=True, archiveReadbackVerified=True,
            luaOriginalArchive=dict(plain_identity(source_receipt['archiveFiles'][LUA_PATH]),
                                    retainedInSeparateSourceInputs=True, includedInRuntime=False),
            sourceCompanionRequired=True, sourceCompanionComplete=False,
            serverExecuted=False, androidProviderCreated=False, androidRuntimeQualified=False, gameplayQualified=False)
        engine.put_metadata(stage / 'package-receipt.json', receipt)
        shutil.rmtree(payload); archives.sync_directory(stage)
        transaction.publish_directory(stage, output); archives.sync_directory(output.parent)
        return receipt
    except BaseException:
        if stage.exists(): print('Unpublished notice packaging retained at ' + str(stage), file=sys.stderr)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('engine-package', 'source-inputs', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = build(args.engine_package, args.source_inputs, args.output)
    print(json.dumps(dict(scope=result['scope'], archive=result['archive'], notices=len(result['notices']),
                         archiveReadbackVerified=True, sourceCompanionComplete=False, androidProviderCreated=False)))


if __name__ == '__main__': main()
