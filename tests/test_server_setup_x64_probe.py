"""Real ELF guards and qualification separation for the x64 SQL-tool bring-up."""
import json
from pathlib import Path
import platform
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch
from tools import build_server_setup_x64_probe as tool


class ServerSetupX64Probe(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)

    def test_context_pins_architecture_snapshot_hash_gate_and_mysql_without_database(self):
        proof=tool.context(self.root/'context');text=(self.root/'context/Dockerfile').read_text()
        self.assertIn(tool.BASE,text);self.assertIn('sha256sum --check /opt/esteria-setup/inrelease.SHA256SUMS',text)
        self.assertIn('libmysqlclient-dev=8.0.46-0ubuntu0.24.04.4',text)
        self.assertNotIn('mysql-server-core',text);self.assertNotIn('initialize',text)
        self.assertEqual(proof['files']['runtime/server/ubuntu.sources'],tool.files.identity(tool.ROOT/'runtime/server/ubuntu.sources'))
        self.assertTrue(all(proof[name] is False for name in tool.FALSE_FLAGS))
        with self.assertRaisesRegex(ValueError,'existing-output-preserved'):tool.context(self.root/'context')

    def test_actual_host_elf_and_arm64_header_mutation(self):
        if platform.machine()!='x86_64':self.skipTest('Actual native x64 ELF required')
        source=Path(shutil.which('true')).resolve();actual=tool.elf64_x64(source)
        self.assertEqual(actual['machine'],62);self.assertGreater(actual['loadSegments'],0)
        raw=bytearray(source.read_bytes());struct.pack_into('<H',raw,18,183)
        changed=self.root/'arm64-header';changed.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'wrong-elf-architecture'):tool.elf64_x64(changed)
        raw=bytearray(source.read_bytes());struct.pack_into('<Q',raw,32,len(raw))
        changed.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'invalid-program-table'):tool.elf64_x64(changed)

    def test_needed_refuses_paths_duplicates_and_unbounded_names(self):
        self.assertEqual(tool.needed('(NEEDED) Shared library: [libc.so.6]'),['libc.so.6'])
        for name in ('../libc.so','/tmp/libc.so','lib'+('x'*129)):
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'invalid-needed-library'):
                tool.needed('(NEEDED) Shared library: ['+name+']')
        with self.assertRaisesRegex(ValueError,'invalid-needed-library'):
            tool.needed('(NEEDED) [libc.so.6]\n(NEEDED) [libc.so.6]')

    def test_actual_system_library_closure_has_package_source_binding_and_complete_copies(self):
        if platform.machine()!='x86_64' or not shutil.which('dpkg-query') or not shutil.which('readelf'):
            self.skipTest('Native Debian x64 dependency inspection tools required')
        libraries,packages=tool.closure([Path(shutil.which('true')).resolve()],self.root/'closure')
        self.assertIn('lib64/ld-linux-x86-64.so.2',libraries)
        self.assertIn('usr/lib/x86_64-linux-gnu/libc.so.6',libraries)
        self.assertTrue(packages)
        for name,row in libraries.items():
            self.assertEqual(tool.files.identity(self.root/'closure'/name),{key:row[key] for key in ('bytes','sha256')})
            self.assertEqual(row['elf']['machine'],62)
            self.assertIn(row['package']['binaryPackage'],packages)
            self.assertTrue(row['package']['package']);self.assertTrue(row['package']['version'])

    def test_wrong_architecture_stops_before_source_reads_or_output(self):
        output=self.root/'absent'
        with patch.object(tool.platform,'machine',return_value='aarch64'),patch.object(tool.isolated,'verify_prepared') as verify:
            with self.assertRaisesRegex(ValueError,'native-x86-64-linux-required'):
                tool.build(output,output,output,'a'*40)
        self.assertFalse(output.exists());verify.assert_not_called()

    def test_source_capture_refuses_nonbuild_before_network(self):
        output=self.root/'output';(output/'payload').mkdir(parents=True)
        (output/'payload/build-receipt.json').write_text(json.dumps({'scope':'foreign','actualCompileSucceeded':True}))
        with patch.object(tool.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'real-build-receipt-required'):
            tool.capture(output,self.root/'ca.pem')
        run.assert_not_called()


if __name__=='__main__':unittest.main()
