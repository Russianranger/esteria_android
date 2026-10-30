import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest

from tools import package_server_runtime as pack


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class ServerRuntimePackage(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'package'
        self.export = self.root / 'export.tar'
        self.metadata = self.root / 'runtime.json'
        self.lock = self.root / 'lock.json'
        lock = dict(baseImage=dict(reference='synthetic-only'), snapshot=dict(id='test'),
                    mysql=dict(expectedRuntimeVersion='test-mysql'))
        self.lock.write_text(json.dumps(lock))
        elf = bytearray(64)
        elf[:6] = b'\x7fELF\x02\x01'
        struct.pack_into('<H', elf, 18, 183)
        self.elf = bytes(elf)
        doc = dict(formatVersion=1, scope='built-linux-arm64-server-dependencies', architecture='arm64',
                   sourceLockSha256=hashlib.sha256(self.lock.read_bytes()).hexdigest(),
                   baseImage='synthetic-only', snapshot='test', expectedMysqlSqlVersion='test-mysql',
                   databaseInitialized=False, serverIncluded=False, serverExecuted=False,
                   androidRuntimeQualified=False, gameLoginQualified=False,
                   images={name: dict(path='/usr/bin/' + name, elfMachine=183, **identity(self.elf))
                           for name in ('mysql', 'mysqld', 'python3')})
        self.metadata.write_text(json.dumps(doc))
        self.members = [(pack.MARKER, self.metadata.read_bytes()),
                        ('usr/lib/os-release', b'ID=ubuntu\nVERSION_ID="24.04"\n'),
                        ('usr/share/doc/mysql/copyright', b'synthetic-license-test'),
                        ('etc/hostname', b'docker-host-identity'),
                        ('etc/resolv.conf', b'nameserver 192.0.2.1\n')]
        self.members += [('usr/bin/' + name, self.elf) for name in ('mysql', 'mysqld', 'python3')]

    def archive(self, extra=(), replace=None):
        members = self.members if replace is None else replace
        with tarfile.open(self.export, 'w', format=tarfile.PAX_FORMAT) as tar:
            for name, content in members + list(extra):
                item = tarfile.TarInfo(name)
                item.uid = item.gid = 1234
                item.mtime = 1234.5  # Exercises bounded Docker PAX acceptance.
                item.mode = 0o6755
                if isinstance(content, bytes):
                    item.size = len(content)
                    tar.addfile(item, io.BytesIO(content))
                else:
                    item.type, item.linkname = content
                    tar.addfile(item)

    def execute(self):
        return pack.package(self.export, self.metadata, self.lock, self.output)

    def test_normalizes_without_executing_and_preserves_licenses(self):
        self.archive(extra=[('dev', (tarfile.DIRTYPE, '')), ('dev/null', (tarfile.CHRTYPE, '')),
                            ('var/log/runtime.log', b'host log'), ('bin', (tarfile.SYMTYPE, 'usr/bin')),
                            ('mysql-hard', (tarfile.LNKTYPE, 'usr/bin/mysql'))])
        receipt = self.execute()
        self.assertTrue(receipt['archiveReadBack'])
        self.assertFalse(receipt['databaseInitialized'])
        self.assertFalse(receipt['serverIncluded'])
        self.assertFalse(receipt['androidRuntimeQualified'])
        self.assertEqual(receipt['omittedEntries'], 2)
        with tarfile.open(self.output / receipt['archive']['file'], 'r:gz') as tar:
            names = tar.getnames()
            self.assertNotIn('dev/null', names)
            self.assertNotIn('var/log/runtime.log', names)
            self.assertEqual(tar.extractfile('etc/hostname').read(), b'esteria-local\n')
            self.assertEqual(tar.extractfile('etc/machine-id').read(), b'')
            self.assertEqual(tar.extractfile('usr/share/doc/mysql/copyright').read(), b'synthetic-license-test')
            for item in tar:
                self.assertEqual(item.uid, 0)
                self.assertEqual(item.gid, 0)
                self.assertEqual(item.mtime, 0)
                self.assertFalse(item.mode & 0o6000)
                self.assertEqual(item.pax_headers, {})

    def test_database_content_and_credentials_refused_without_publication(self):
        for name in ('var/lib/mysql/auto.cnf', 'esteria-state/characters.db', 'root/.my.cnf', 'root/.mysql_history'):
            with self.subTest(name=name):
                self.archive([(name, b'secret')])
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(self.output.exists())
                self.assertEqual(list(self.root.glob('.package.stage-*')), [])

    def test_unsafe_paths_links_duplicates_special_files_refused(self):
        for extra in ([('../bad', b'x')], [('usr/bin/mysql', b'changed')],
                      [('elsewhere/fifo', (tarfile.FIFOTYPE, ''))],
                      [('hard', (tarfile.LNKTYPE, 'missing'))],
                      [('link', (tarfile.SYMTYPE, '/usr/bin')), ('link/child', b'x')],
                      [('link/child', b'x'), ('link', (tarfile.SYMTYPE, '/usr/bin'))],
                      [('link', (tarfile.SYMTYPE, '../../outside'))]):
            with self.subTest(extra=extra):
                self.archive(extra)
                with self.assertRaises(ValueError):
                    self.execute()
                self.assertFalse(self.output.exists())

    def test_component_and_exact_metadata_bytes_bound_to_receipt(self):
        for target in ('usr/bin/mysqld', pack.MARKER):
            with self.subTest(target=target):
                self.archive(replace=[(name, data + b' ' if name == target else data) for name, data in self.members])
                with self.assertRaisesRegex(ValueError, 'component-identity-mismatch'):
                    self.execute()
                self.assertFalse(self.output.exists())

    def test_existing_output_and_source_lock_preserved(self):
        self.archive()
        self.output.mkdir()
        (self.output / 'saved').write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'destination-exists'):
            self.execute()
        self.assertEqual((self.output / 'saved').read_bytes(), b'keep')
        self.lock.write_text(self.lock.read_text() + ' ')
        with self.assertRaisesRegex(ValueError, 'source-lock-mismatch'):
            self.execute()

    def test_input_pax_allocation_is_bounded(self):
        with tarfile.open(self.export, 'w', format=tarfile.GNU_FORMAT) as tar:
            item = tarfile.TarInfo('extended')
            item.type = tarfile.XHDTYPE
            item.size = pack.MAX_PAX + 1
            tar.addfile(item, io.BytesIO(b'x' * item.size))
        with self.assertRaisesRegex(ValueError, 'input-pax-size-limit'):
            self.execute()
        self.assertFalse(self.output.exists())

    def test_wrong_elf_architecture_rejected_even_with_matching_metadata_hash(self):
        wrong = bytearray(self.elf)
        struct.pack_into('<H', wrong, 18, 62)
        doc = json.loads(self.metadata.read_text())
        doc['images']['mysql'].update(identity(wrong))
        self.metadata.write_text(json.dumps(doc))
        members = [(name, self.metadata.read_bytes() if name == pack.MARKER else
                    bytes(wrong) if name == 'usr/bin/mysql' else data) for name, data in self.members]
        self.archive(replace=members)
        with self.assertRaisesRegex(ValueError, 'component-elf-mismatch'):
            self.execute()
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
