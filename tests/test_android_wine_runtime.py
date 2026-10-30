import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import tarfile
import tempfile
import unittest
from tools import package_android_wine_runtime as package


def identity(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class WineRuntime(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name)
        self.export = self.root / 'export.tar'; self.metadata = self.root / 'runtime.json'; self.output = self.root / 'package'
        lock = json.loads(package.LOCK.read_text())
        self.elf = bytearray(64); self.elf[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', self.elf, 18, 62)
        self.pe = bytearray(256); self.pe[:2] = b'MZ'; struct.pack_into('<I', self.pe, 60, 128)
        self.pe[128:132] = b'PE\0\0'; struct.pack_into('<H', self.pe, 132, 0x8664); struct.pack_into('<H', self.pe, 152, 0x20b)
        self.doc = dict(formatVersion=1, scope='built-linux-x86-64-wine-probe', architecture='amd64',
            sourceLockSha256=hashlib.sha256(package.LOCK.read_bytes()).hexdigest(), baseImage=lock['baseImage']['reference'],
            snapshot=lock['snapshot']['id'], wineRevision=lock['wine']['revision'],
            wineSourceArchiveSha256=lock['wine']['sourceArchive']['sha256'], wineVersion='wine-10.13',
            privatePeCopyProfile=lock['wine'].get('androidPrivatePeCopy'),
            packages=[dict(package='libc6:amd64', version='fixture', architecture='amd64', sourcePackage='glibc', sourceVersion='fixture')],
            sourcePackages=[dict(package='glibc', version='fixture')], images={},
            **{flag:False for flag in ('prefixInitialized','clientIncluded','clientExecuted','androidRuntimeQualified','arm64Qualified','gameplayQualified')})

    def prepare(self, extra=(), bad_elf=False, bad_pe=False):
        elf = bytearray(self.elf); pe = bytearray(self.pe)
        if bad_elf: struct.pack_into('<H', elf, 18, 183)
        if bad_pe: struct.pack_into('<H', pe, 132, 0xaa64)
        images = []
        for name, path in package.IMAGES.items():
            is_pe = path.endswith('.dll'); data = bytes(pe if is_pe else elf)
            self.doc['images'][name] = dict(path=path, **identity(data),
                **(dict(peMachine='0x8664') if is_pe else dict(elfMachine=62,elfClass=2)))
            images.append((path[1:], data))
        raw = (json.dumps(self.doc) + '\n').encode(); self.metadata.write_bytes(raw)
        with tarfile.open(self.export, 'w', format=tarfile.GNU_FORMAT) as tar:
            for name, data in [(package.MARKER,raw),('usr/lib/os-release',b'ID=debian\nVERSION_ID="12"\n')] + images + list(extra):
                member = tarfile.TarInfo(name); member.mode=0o755
                if isinstance(data,bytes): member.size=len(data); tar.addfile(member,io.BytesIO(data))
                else: member.type,member.linkname=data; tar.addfile(member)

    def test_streaming_readback_and_explicit_copy_budget(self):
        self.prepare([('usr/lib/wine-alias',(tarfile.LNKTYPE,'opt/wine/bin/wine'))])
        report=package.build(self.export,self.metadata,self.output)
        self.assertTrue(report['archiveReadBack']); self.assertFalse(report['androidRuntimeQualified'])
        self.assertFalse(report['clientIncluded']); self.assertEqual(1,report['maximumHardLinkCopies'])
        self.assertEqual(64,report['maximumHardLinkCopyBytes'])
        self.assertEqual(report['archiveFileBytes']+64,report['maximumPhysicalFileBytes'])
        with self.assertRaisesRegex(ValueError,'output-exists'): package.build(self.export,self.metadata,self.output)

    def test_actual_elf_and_pe_machines_are_checked(self):
        for args in (dict(bad_elf=True),dict(bad_pe=True)):
            self.prepare(**args)
            with self.subTest(args=args),self.assertRaisesRegex(ValueError,'component-(elf|pe)-mismatch'):
                package.build(self.export,self.metadata,self.output)
            self.assertFalse(self.output.exists())

    def test_exact_source_scope_and_complete_inventory(self):
        self.prepare(); raw=self.metadata.read_bytes(); package.metadata(raw)
        changes={'wineRevision':'a'*40,'wineSourceArchiveSha256':'b'*64,'sourceLockSha256':'c'*64,
                 'architecture':'arm64','sourcePackages':[],'images':{},'prefixInitialized':True,
                 'clientExecuted':True,'androidRuntimeQualified':True,'gameplayQualified':True}
        changes['privatePeCopyProfile']={'unverified':'different'}
        for key,value in changes.items():
            changed=copy.deepcopy(self.doc);changed[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): package.metadata(json.dumps(changed).encode())

    def test_escaping_link_and_private_state_refused(self):
        for extra in [('bad',(tarfile.SYMTYPE,'../../escape')),('var/lib/mysql/auto.cnf',b'old-state'),('root/.my.cnf',b'old-secret')]:
            self.prepare([extra])
            with self.subTest(extra=extra),self.assertRaises(ValueError): package.build(self.export,self.metadata,self.output)
            self.assertFalse(self.output.exists())

    def test_forged_false_marker_cannot_package_existing_wine_prefix(self):
        for path in ('root/.wine/system.reg','home/alice/.wine/user.reg','work/prefix/system.reg',
                     'prefix/drive_c/old.exe','client/Esteria-entry-check.json','session/old-log',
                     'private-pe-fixtures/private-pe-check.exe','private-pe-evidence/receipt.json'):
            self.prepare([(path,b'old-session')])
            self.assertFalse(self.doc['prefixInitialized'])
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'wine-prefix-or-session-state'):
                package.build(self.export,self.metadata,self.output)
            self.assertFalse(self.output.exists())


if __name__=='__main__': unittest.main()
