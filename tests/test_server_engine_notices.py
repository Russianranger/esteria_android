"""Notice transactions use synthetic ELFs/source bytes and execute no server."""
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_server_engine_notices as notices


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def git_identity(raw):
    return dict(identity(raw), gitBlob=hashlib.sha1(('blob ' + str(len(raw)) + '\0').encode() + raw).hexdigest(),
                gitMode='100644')


def tar_bytes(members, *, pax=False):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT if pax else tarfile.GNU_FORMAT) as archive:
            for name, raw in sorted(members.items()):
                item = tarfile.TarInfo(name); item.size = len(raw); item.mode = 0o644
                if pax: item.pax_headers = {'comment': 'synthetic unexpected metadata'}
                archive.addfile(item, io.BytesIO(raw))
    return output.getvalue()


class SyntheticNoticePackages(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = self.root / 'engine'; self.engine.mkdir()
        self.sources = self.root / 'sources'; self.sources.mkdir()
        self.output = self.root / 'notices'
        self.audit_path = self.root / 'audit.json'
        patcher = patch.object(notices, 'AUDIT', self.audit_path)
        patcher.start(); self.addCleanup(patcher.stop)
        self.lock_raw = notices.SOURCE_LOCK.read_bytes(); self.lock = identity(self.lock_raw)
        self.server = json.loads(self.lock_raw)['sources']['server']
        # Valid header fixture only: never execute or claim it was stripped.
        raw = bytearray(256); raw[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHI', raw, 16, 3, 183, 1); struct.pack_into('<Q', raw, 32, 64)
        struct.pack_into('<HHH', raw, 52, 64, 56, 2)
        interpreter = b'/lib/ld-linux-aarch64.so.1\0'
        struct.pack_into('<IIQQQQQQ', raw, 64, 1, 5, 0, 0, 0, len(raw), len(raw), 4096)
        struct.pack_into('<IIQQQQQQ', raw, 120, 3, 4, 176, 176, 176, len(interpreter), len(interpreter), 1)
        raw[176:176 + len(interpreter)] = interpreter
        self.runtime_bytes = bytes(raw)
        self.runtime_members = {'bin/' + name: self.runtime_bytes for name in notices.engine.PROGRAMS}
        self.runtime_members.update({name: b'# original immutable template fixture\n' for name in notices.engine.MAIN_CONFIGS})
        original = identity(b'original-unstripped-fixture' + self.runtime_bytes)
        self.build = dict(schemaVersion=1, architecture='Linux-ARM64', sourceCheckoutAndPatchesVerified=True,
            serverSource=self.server, sourcesLock=self.lock, integrationRevision='a' * 40, buildId='fixture.1',
            files=[dict(path=name, **(original if name.startswith('bin/') else identity(value)),
                        **({'elf': {'machine': 'AArch64'}} if name.startswith('bin/') else {}))
                   for name, value in self.runtime_members.items()])
        build_raw = notices.engine.canonical(self.build)
        self.compiled = dict(formatVersion=1, scope='compiled-server-module-selection', source=self.server,
            sourceLockSha256=self.lock['sha256'], serverBuild=identity(build_raw),
            generatedListsMatchInstalledBinaries=True, enabledModules=[], configFiles=[],
            binaries={name: original for name in ('worldserver', 'dbimport')})
        compiled_raw = notices.engine.canonical(self.compiled)
        self.derivative = dict(formatVersion=1, scope='paired-linux-arm64-server-engine-derivative',
            runtimeMount='/esteria-server-programs', originalReceiptsPreserved=True,
            originalBuild=identity(build_raw), originalModules=identity(compiled_raw), sourcesLock=self.lock,
            serverSource=self.server, integrationRevision='a' * 40, buildId='fixture.1', enabledModules=[], configFiles=[],
            programs={name: dict(original=original, stripped=identity(self.runtime_bytes), runtimeBytesPreserved=True,
                                debugLinkVerified=True, serverExecuted=False) for name in notices.engine.PROGRAMS})
        self.runtime_members.update({'provenance/server-build.json': build_raw,
            'provenance/server-modules.json': compiled_raw, 'provenance/sources.lock.json': self.lock_raw,
            'provenance/server-engine-derivative.json': notices.engine.canonical(self.derivative)})
        payload = self.root / 'runtime'
        for name, value in self.runtime_members.items():
            path = payload / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
        archive = self.engine / 'server-engine-runtime-arm64.tar.gz'
        inventory = notices.engine.write_archive(payload, archive)
        self.engine_receipt = dict(formatVersion=1, scope='unsealed-server-engine-packaging', derivative=self.derivative,
            archiveReadbackVerified=True, androidProviderCreated=False, sourceCompanionComplete=False,
            packages={'runtime': dict(archiveFile=archive.name, archive=notices.files.identity(archive), inventory=inventory),
                      'debug': {'archive': identity(b'separately retained debug fixture')}})
        (self.engine / 'package-receipt.json').write_bytes(notices.engine.canonical(self.engine_receipt))
        self.source_bytes = {}
        pristine = dict(server={}, eluna={}, integration={'sources.lock.json': git_identity(self.lock_raw)})
        self.source_bytes['integration/sources.lock.json'] = self.lock_raw
        candidates = []
        paths = ['LICENSE', 'AUTHORS'] + ['deps/component-' + str(n) + '/LICENSE' for n in range(62)]
        paths += [notices.engine.content.ELUNA + '/LICENSE']
        for name in paths:
            raw = ('Original synthetic notice bytes for ' + name + '\n').encode()
            row = git_identity(raw); self.source_bytes['source/' + name] = raw
            candidate = dict(path=name, bytes=len(raw), mode='100644', gitBlobSha1=row['gitBlob'])
            if name.startswith(notices.engine.content.ELUNA + '/'):
                pristine['eluna'][name[len(notices.engine.content.ELUNA) + 1:]] = row
                candidate['gitRepository'] = 'Eluna'
            else: pristine['server'][name] = row
            candidates.append(candidate)
        self.audit = dict(formatVersion=1, serverRevision=self.server['commit'], noticeCandidates=candidates)
        audit_raw = notices.engine.canonical(self.audit); self.audit_path.write_bytes(audit_raw)
        self.lua_license = b'Synthetic license-bearing complete Lua document fixture; never original source.\n'
        lua = tar_bytes({notices.LUA_NOTICE: self.lua_license})
        for owner, name, value in ((notices.sources, 'LUA_SHA256', identity(lua)['sha256']),
                                    (notices, 'LUA_NOTICE_IDENTITY', identity(self.lua_license))):
            patcher = patch.object(owner, name, value); patcher.start(); self.addCleanup(patcher.stop)
        local = {'metadata/server-build.json': build_raw, 'metadata/server-modules.json': compiled_raw,
                 'metadata/source-selection-audit.json': audit_raw, notices.LUA_PATH: lua}
        self.source_bytes.update(local)
        self.manifest = dict(formatVersion=1, scope='unsealed-engine-source-input-preservation',
            originalBuild=self.derivative['originalBuild'], originalCompiledModules=self.derivative['originalModules'],
            sourceLock=self.lock, source=self.server, originalIntegrationRevision='a' * 40, buildId='fixture.1',
            enabledModules=[], sourceSelectionAudit=identity(audit_raw), luaOriginalArchiveRetained=True,
            selectedSourceNoticesRetained=True, sourceCompanionComplete=False, pristineGitFiles=pristine,
            localInputs={name: git_identity(raw) for name, raw in local.items()})
        self.write_sources()

    def write_sources(self, *, pax=False):
        manifest_raw = notices.engine.canonical(self.manifest)
        self.source_bytes['metadata/source-inputs.json'] = manifest_raw
        inventory = notices.source_inventory(self.manifest)
        inventory['metadata/source-inputs.json'] = identity(manifest_raw)
        raw = tar_bytes(self.source_bytes, pax=pax)
        (self.sources / notices.SOURCE_ARCHIVE).write_bytes(raw)
        self.source_receipt = dict(formatVersion=1, scope='unsealed-engine-source-input-package',
            completeArchiveReadbackVerified=True, sourceCompanionComplete=False,
            originalBuild=self.derivative['originalBuild'], originalCompiledModules=self.derivative['originalModules'],
            sourceLock=self.lock, archive=dict(file=notices.SOURCE_ARCHIVE, **identity(raw)),
            archiveFiles=inventory, manifest=identity(manifest_raw))
        self.write_source_receipt()

    def write_source_receipt(self):
        (self.sources / notices.SOURCE_RECEIPT).write_bytes(notices.engine.canonical(self.source_receipt))

    def run_build(self):
        return notices.build(self.engine, self.sources, self.output)

    def test_original_runtime_and_all_65_notices_plus_lua_are_preserved(self):
        before = {path: notices.files.identity(path) for root in (self.engine, self.sources) for path in root.iterdir()}
        receipt = self.run_build()
        self.assertEqual(len(receipt['notices']), 66)
        self.assertEqual(set(receipt['archiveFiles']), set(self.runtime_members) | set(receipt['notices']))
        self.assertEqual({p.name for p in self.output.iterdir()}, {notices.ARCHIVE, 'package-receipt.json'})
        with tarfile.open(self.output / notices.ARCHIVE, 'r:gz') as archive:
            for name, raw in self.runtime_members.items(): self.assertEqual(archive.extractfile(name).read(), raw)
            for row in self.audit['noticeCandidates']:
                name = 'notices/source/' + row['path']
                self.assertEqual(archive.extractfile(name).read(), self.source_bytes['source/' + row['path']])
                self.assertEqual(archive.getmember(name).mode, 0o444)
            self.assertEqual(archive.extractfile('notices/external/' + notices.LUA_NOTICE).read(), self.lua_license)
            self.assertNotIn(notices.LUA_PATH, archive.getnames())
        self.assertEqual(before, {path: notices.files.identity(path) for path in before})
        for flag in ('sourceCompanionComplete', 'serverExecuted', 'androidProviderCreated', 'androidRuntimeQualified', 'gameplayQualified'):
            self.assertIs(receipt[flag], False)

    def test_source_build_module_or_lock_cannot_be_substituted(self):
        for field in ('originalBuild', 'originalCompiledModules', 'sourceLock'):
            value = copy.deepcopy(self.source_receipt); value[field]['sha256'] = '0' * 64
            (self.sources / notices.SOURCE_RECEIPT).write_bytes(notices.engine.canonical(value))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'engine-provenance'):
                self.run_build()
            self.assertFalse(self.output.exists())

    def test_actual_manifest_must_bind_same_engine_and_complete_inventory(self):
        self.manifest['buildId'] = 'other.1'; self.write_sources()
        with self.assertRaisesRegex(ValueError, 'manifest-engine-binding'): self.run_build()
        self.assertFalse(self.output.exists())

    def test_changed_source_member_even_with_rebound_archive_hash_is_refused(self):
        self.source_bytes['source/LICENSE'] = b'changed original notice'
        self.write_sources()
        with self.assertRaisesRegex(ValueError, 'member-metadata|file-identity'): self.run_build()
        self.assertFalse(self.output.exists())

    def test_extra_source_member_cannot_hide_outside_manifest(self):
        self.source_bytes['private/database-secret'] = b'never copied'
        self.write_sources()
        with self.assertRaisesRegex(ValueError, 'member-set'): self.run_build()
        self.assertFalse(self.output.exists())

    def test_rebound_notice_git_blob_cannot_override_audit(self):
        self.manifest['pristineGitFiles']['server']['LICENSE']['gitBlob'] = '0' * 40
        self.write_sources()
        with self.assertRaisesRegex(ValueError, 'file-identity'): self.run_build()

    def test_source_pax_headers_refused_before_extraction(self):
        self.write_sources(pax=True)
        with self.assertRaisesRegex(ValueError, 'unsupported-tar-encoding'): self.run_build()
        self.assertFalse(self.output.exists())

    def test_lua_archive_and_complete_license_file_are_separately_pinned(self):
        with self.assertRaisesRegex(ValueError, 'original-lua-archive'):
            notices.lua_notice(self.source_bytes[notices.LUA_PATH] + b'changed')
        with patch.object(notices, 'LUA_NOTICE_IDENTITY', dict(bytes=len(self.lua_license), sha256='0' * 64)), \
                self.assertRaisesRegex(ValueError, 'license-bearing-file'):
            notices.lua_notice(self.source_bytes[notices.LUA_PATH])

    def test_existing_output_and_input_overlap_preserved_before_verification(self):
        self.output.mkdir(); (self.output / 'saved').write_bytes(b'preserve')
        with patch.object(notices.runtime, 'load_receipt') as read, self.assertRaisesRegex(ValueError, 'output-exists'):
            self.run_build()
        read.assert_not_called(); self.assertEqual((self.output / 'saved').read_bytes(), b'preserve')
        for output in (self.engine / 'new', self.sources / 'new', self.engine, self.root):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'output-exists-or-overlaps'):
                notices.build(self.engine, self.sources, output)

    def test_changed_runtime_archive_cannot_be_augmented(self):
        path = self.engine / 'server-engine-runtime-arm64.tar.gz'; path.write_bytes(path.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'archive-changed'): self.run_build()
        self.assertFalse(self.output.exists())

    def test_changed_receipt_during_copy_never_publishes(self):
        original = notices.engine.write_archive
        def changed(*args):
            result = original(*args)
            receipt = self.sources / notices.SOURCE_RECEIPT
            receipt.write_bytes(receipt.read_bytes() + b'\n')
            return result
        with patch.object(notices.engine, 'write_archive', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'receipt-changed-during'):
            self.run_build()
        self.assertFalse(self.output.exists())
        self.assertTrue(any(path.name.startswith('.notices.stage-') for path in self.root.iterdir()))

    def test_changed_source_archive_during_copy_never_publishes(self):
        original = notices.engine.write_archive
        def changed(*args):
            result = original(*args)
            archive = self.sources / notices.SOURCE_ARCHIVE
            archive.write_bytes(archive.read_bytes() + b'changed after verification')
            return result
        with patch.object(notices.engine, 'write_archive', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'archive-changed-during'):
            self.run_build()
        self.assertFalse(self.output.exists())


@unittest.skipUnless(os.environ.get('ESTERIA_ENGINE_NOTICES_REAL_INPUTS'), 'exact retained engine/source inputs not supplied')
class ExactRetainedInputs(unittest.TestCase):
    def test_complete_actual_archives_preserve_60_runtime_files_and_66_notices(self):
        inputs = Path(os.environ['ESTERIA_ENGINE_NOTICES_REAL_INPUTS']).resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix='actual-engine-notices-') as temporary:
            output = Path(temporary) / 'package'
            receipt = notices.build(inputs / 'package', inputs / 'source-inputs', output)
            self.assertEqual(len(receipt['notices']), 66)
            self.assertEqual(len(receipt['archiveFiles']), 126)
            self.assertTrue(receipt['originalRuntimeFilesUnchanged'])
            self.assertFalse(receipt['sourceCompanionComplete']); self.assertFalse(receipt['androidProviderCreated'])
            pin=json.loads(notices.PROVIDER_LOCK.read_text())
            self.assertEqual(receipt['archive'],pin['archive'])
            self.assertEqual(notices.files.identity(output/'package-receipt.json'),notices.engine.identity(pin['packageReceipt']))
            notices.engine.verify_archive(output / notices.ARCHIVE, receipt['archiveFiles'])


class NoticeSourceBinding(unittest.TestCase):
    def test_reviewed_client_only_change_reuses_archived_source_and_rejects_server_profile_drift(self):
        provider=json.loads(notices.PROVIDER_LOCK.read_text())
        derivative=dict(serverSource=provider['serverSource'],sourcesLock=provider['serverBuildSourceLock'])
        notices.validate_source_selection(derivative)
        with tempfile.TemporaryDirectory(prefix='notice-source-binding-') as temporary:
            root=Path(temporary);current=json.loads(notices.SOURCE_LOCK.read_text())
            current['sources']['client']['commit']='a'*40
            path=root/'current.lock.json';pin=root/'provider.lock.json'
            def select(document):
                raw=notices.engine.canonical(document);path.write_bytes(raw)
                provider['appSourceLock']=identity(raw);pin.write_bytes(notices.engine.canonical(provider))
            select(current)
            with patch.object(notices,'SOURCE_LOCK',path),patch.object(notices,'PROVIDER_LOCK',pin):
                notices.validate_source_selection(derivative)
                for kind in ('patch','submodule','profile'):
                    changed=copy.deepcopy(current)
                    if kind=='patch':changed['sources']['server']['patches'][0]['sha256']='0'*64
                    elif kind=='submodule':changed['sources']['server']['submodules']['src/server/game/LuaEngine']='b'*40
                    else:changed['compatibility']['extended_limits']=1
                    select(changed)
                    with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'not-current|compatibility-profile-differs'):
                        notices.validate_source_selection(derivative)


if __name__ == '__main__': unittest.main()
