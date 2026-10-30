import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from tools import build_android_mysql_probe as build, verify_android_mysql_probe as verify, qualify_android_mysql as qualify


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class MySqlProbe(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.archive = self.root / 'docker.tar'; self.measured = self.root / 'metadata.json'; self.output = self.root / 'provider'
        lock = json.loads(build.LOCK.read_text())
        elf = bytearray(64); elf[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', elf, 18, 62); self.elf = bytes(elf)
        self.doc = dict(formatVersion=1, scope='built-linux-x86-64-mysql-probe', architecture='amd64',
            sourceLockSha256=hashlib.sha256(build.LOCK.read_bytes()).hexdigest(), baseImage=lock['baseImage']['reference'],
            snapshot=lock['snapshot']['id'], expectedMysqlSqlVersion=lock['mysql']['expectedRuntimeVersion'],
            databaseInitialized=False, serverIncluded=False, serverExecuted=False, androidRuntimeQualified=False, gameLoginQualified=False,
            packages=[dict(package=row['package'], version=row['version'], architecture='amd64') for row in lock['mysql']['binaryPackages']],
            images={name: dict(path=path, elfMachine=62, **identity(self.elf)) for name, path in
                    [('mysql', '/usr/bin/mysql'), ('mysqld', '/usr/sbin/mysqld'), ('python3', '/usr/bin/python3.12')]})

    def prepare_export(self, extra=(), machine=62):
        elf = bytearray(self.elf); struct.pack_into('<H', elf, 18, machine)
        for row in self.doc['images'].values(): row.update(identity(elf))
        raw = build.encoded(self.doc); self.measured.write_bytes(raw)
        with tarfile.open(self.archive, 'w', format=tarfile.GNU_FORMAT) as tar:
            members = [(build.MARKER, raw), ('usr/lib/os-release', b'ID=ubuntu\nVERSION_ID="24.04"\n')]
            members += [(row['path'][1:], bytes(elf)) for row in self.doc['images'].values()]
            members += [('usr/share/doc/mysql/copyright', b'synthetic license fixture')] + list(extra)
            for name, content in members:
                item = tarfile.TarInfo(name); item.mode = 0o755
                if isinstance(content, bytes): item.size = len(content); tar.addfile(item, io.BytesIO(content))
                else: item.type, item.linkname = content; tar.addfile(item)

    def package(self):
        return build.build(self.archive, self.measured, self.output)

    def test_actual_archive_readback_and_independent_provider_verification(self):
        self.prepare_export([('lib/mysql-copy', (tarfile.LNKTYPE, 'usr/bin/mysql'))])
        proof = self.package()
        self.assertFalse(proof['androidMysqlQualified']); self.assertEqual(proof['maximumHardLinkCopies'], 1)
        self.assertEqual(proof['maximumHardLinkCopyBytes'], len(self.elf)); self.assertTrue(proof['archiveReadBack'])
        with patch.object(verify.proot, 'verify', return_value={}):
            self.assertTrue(verify.verify(self.output, self.root)['providerVerified'])
        with self.assertRaisesRegex(ValueError, 'output-exists'): self.package()
        archive = self.output / 'assets/mysql-probe' / build.ARCHIVE
        archive.write_bytes(archive.read_bytes() + b'tamper')
        with patch.object(verify.proot, 'verify', return_value={}), self.assertRaisesRegex(ValueError, 'archive-identity'):
            verify.verify(self.output, self.root)

    def test_arm64_image_or_claimed_android_qualification_refused(self):
        for key, value in [('architecture', 'arm64'), ('androidRuntimeQualified', True), ('scope', 'built-linux-arm64-server-dependencies')]:
            with self.subTest(key=key):
                altered = dict(self.doc); altered[key] = value
                with self.assertRaises(ValueError): build.metadata(build.encoded(altered))
        self.prepare_export(machine=183)
        with self.assertRaisesRegex(ValueError, 'component-elf-mismatch'): self.package()
        self.assertFalse(self.output.exists())

    def test_state_credentials_and_escaping_links_are_not_packaged(self):
        for extra in [('var/lib/mysql/auto.cnf', b'old-state'), ('root/.my.cnf', b'old-secret'),
                      ('bad', (tarfile.SYMTYPE, '../../escape'))]:
            with self.subTest(extra=extra):
                self.prepare_export([extra])
                with self.assertRaises(ValueError): self.package()
                self.assertFalse(self.output.exists())

    def test_receipt_requires_all_actual_results_and_exact_inputs(self):
        proof = dict(expectedMysqlSqlVersion='8.0.46-0ubuntu0.24.04.4', archive=dict(sha256='a'*64)); raw = build.encoded(proof)
        proot = {'fixture': 'pinned-only'}
        good = dict(formatVersion=1, scope=qualify.SCOPE, sourceRevision='b'*40, fingerprint='fixture', abi='x86_64', api=33,
                    targetSdk=35, guestLaunches=4, mysqlVersion=proof['expectedMysqlSqlVersion'], runtimeProviderSha256=hashlib.sha256(raw).hexdigest(),
                    runtimeArchiveSha256='a'*64, runtimeGeneration='c'*64, prootBuildEvidence=proot,
                    **{name: True for name in qualify.FLAGS}, **{name: False for name in qualify.FALSE_FLAGS})
        qualify.validate_receipt(good, 'b'*40, 'fixture', raw, proot)
        mutations = {name: False for name in qualify.FLAGS}
        mutations.update({name: True for name in qualify.FALSE_FLAGS})
        mutations.update(mysqlVersion='8.0.46-other', runtimeProviderSha256='d'*64, runtimeArchiveSha256='d'*64,
                         prootBuildEvidence={}, guestLaunches=3, api=32, targetSdk=28, abi='arm64-v8a', formatVersion=True)
        for key, value in mutations.items():
            changed = copy.deepcopy(good); changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): qualify.validate_receipt(changed, 'b'*40, 'fixture', raw, proot)

    def test_source_lock_keeps_production_and_debug_architectures_separate(self):
        source = json.loads(build.LOCK.read_text()); production = json.loads((build.ROOT / 'runtime/server/sources.lock.json').read_text())
        self.assertEqual(source['architecture'], 'amd64'); self.assertEqual(production['architecture'], 'arm64')
        self.assertNotEqual(source['baseImage']['reference'], production['baseImage']['reference'])
        self.assertEqual(source['mysql']['expectedRuntimeVersion'], production['mysql']['expectedRuntimeVersion'])
        self.assertEqual(source['mysql']['sourceArchives'], production['mysql']['sourceArchives'])
        self.assertTrue(all(row['architecture']=='amd64' for row in source['mysql']['binaryPackages']))


if __name__ == '__main__': unittest.main()
