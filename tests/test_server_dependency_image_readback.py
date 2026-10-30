"""Synthetic filesystem guards; actual native container execution is a CI gate."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import verify_server_dependency_image as image


class DependencyImageReadback(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.guest = self.root / 'guest'; self.guest.mkdir()
        self.receipt = self.root / 'context-receipt.json'
        self.native = patch.object(image.platform, 'machine', return_value='aarch64')
        self.native.start(); self.addCleanup(self.native.stop)
        self.python = patch.object(image, 'running_python_matches', return_value=True)
        self.python.start(); self.addCleanup(self.python.stop)
        self.metadata = dict(formatVersion=1, scope='built-linux-arm64-server-dependencies',
            architecture='arm64', sourceLockSha256='a'*64, expectedMysqlSqlVersion='8.0.46', images={},
            databaseInitialized=False, serverIncluded=False, serverExecuted=False,
            androidRuntimeQualified=False, gameLoginQualified=False)
        for index, (name, relative) in enumerate(image.COMPONENTS.items()):
            raw = bytearray(128 + index); raw[:7] = b'\x7fELF\x02\x01\x01'
            struct.pack_into('<H', raw, 18, 183)
            path = self.guest / relative[1:]; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.metadata['images'][name] = dict(path=relative, bytes=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(), elfMachine=183)
        self.expected = dict(formatVersion=1, scope='verified-server-dependency-image-context-only',
            architecture='arm64', completeSourceCompanionReverified=True,
            archiveGraphAndComponentsReverified=True, databaseInitialized=False, serverIncluded=False,
            sourceLock={'sha256':'a'*64}, expectedMysqlSqlVersion='8.0.46',
            archive={'sha256':'b'*64}, sourceCompanion={'sha256':'c'*64})
        self.write_metadata()

    def write_metadata(self):
        raw = json.dumps(self.metadata).encode()
        path = self.guest / 'etc/esteria-server-runtime.json'
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
        self.expected.update(runtimeMetadata=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
                             components=self.metadata['images'])
        self.receipt.write_text(json.dumps(self.expected))

    def verify(self):
        return image.verify(self.receipt, self.guest)

    def test_exact_metadata_and_all_three_components_are_read_back_without_sql(self):
        result = self.verify()
        self.assertEqual(set(result['components']), set(image.COMPONENTS))
        self.assertTrue(result['actualImageMetadataAndElfHashesVerified'])
        for key in ('mysqlServerExecuted','databaseInitialized','esteriaServerExecuted','gameplayQualified'):
            self.assertFalse(result[key])

    def test_wrong_native_architecture_rejected_before_receipt_or_guest_reads(self):
        with patch.object(image.platform, 'machine', return_value='x86_64'), \
                patch.object(image, 'metadata') as metadata, self.assertRaisesRegex(ValueError, 'native-arm64'):
            self.verify()
        metadata.assert_not_called()

    def test_changed_component_bytes_and_wrong_elf_architecture_rejected(self):
        path = self.guest / image.COMPONENTS['mysqld'][1:]
        raw = path.read_bytes(); path.write_bytes(raw[:-1] + b'x')
        with self.assertRaisesRegex(ValueError, 'component-hash'): self.verify()
        changed = bytearray(raw); struct.pack_into('<H', changed, 18, 62); path.write_bytes(changed)
        self.metadata['images']['mysqld']['sha256'] = hashlib.sha256(changed).hexdigest(); self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'component-architecture'): self.verify()

    def test_metadata_mismatch_or_existing_database_is_never_accepted(self):
        path = self.guest / 'etc/esteria-server-runtime.json'
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'runtime-metadata-changed'): self.verify()
        self.write_metadata()
        state = self.guest / 'var/lib/mysql'; state.mkdir(parents=True)
        marker = state / 'auto.cnf'; marker.write_bytes(b'existing-owned-state')
        with self.assertRaisesRegex(ValueError, 'private-state-present'): self.verify()
        self.assertEqual(marker.read_bytes(), b'existing-owned-state')

    def test_linked_component_refused_even_when_content_hash_would_match(self):
        path = self.guest / image.COMPONENTS['mysql'][1:]
        other = self.root / 'same-bytes'; other.write_bytes(path.read_bytes())
        path.unlink(); path.symlink_to(other)
        with self.assertRaises(OSError): self.verify()

    def test_running_interpreter_must_be_the_exact_checked_image_file(self):
        with patch.object(image, 'running_python_matches', return_value=False), \
                self.assertRaisesRegex(ValueError, 'running-interpreter-mismatch'):
            self.verify()

    def test_missing_source_closure_and_rebound_component_path_refused(self):
        self.expected['completeSourceCompanionReverified'] = False
        self.receipt.write_text(json.dumps(self.expected))
        with self.assertRaisesRegex(ValueError, 'context-receipt-required'): self.verify()
        self.expected['completeSourceCompanionReverified'] = True
        self.metadata['images']['mysql']['path'] = '/tmp/foreign-program'; self.write_metadata()
        with self.assertRaisesRegex(ValueError, 'component-path'): self.verify()


if __name__ == '__main__': unittest.main()
