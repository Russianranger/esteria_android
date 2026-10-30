"""Synthetic package contracts; these never execute Wine or qualify ARM64."""
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

from tools import package_wine_arm64_candidate as package
from tools import prepare_runtime, qualify_wine_arm64


def identity(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def image(machine=None):
    if machine is None:
        data = bytearray(64); data[:6] = b'\x7fELF\x02\x01'; struct.pack_into('<H', data, 18, 183)
    else:
        data = bytearray(256); data[:2] = b'MZ'; struct.pack_into('<I', data, 60, 128)
        data[128:132] = b'PE\0\0'; struct.pack_into('<H', data, 132, machine)
        struct.pack_into('<H', data, 152, 0x10b if machine == 0x14c else 0x20b)
    return bytes(data)


class Arm64Candidate(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.export = self.root / 'export.tar'
        self.measured = self.root / 'runtime.json'; self.output = self.root / 'output'
        self.lock = json.loads(package.LOCK.read_bytes())
        # Fixture-only notice bodies keep these tests independent of downloads.
        self.notices = {package.NOTICE_ROOT + 'COPYING.LIB': b'Synthetic Wine license fixture\n',
                        package.NOTICE_ROOT + 'fex/LICENSE': b'Synthetic FEX license fixture\n',
                        package.NOTICE_ROOT + 'toolchain/LICENSE.TXT': b'Synthetic toolchain license fixture\n'}
        self.lock['wine']['licenseFileSha256'] = identity(self.notices[package.NOTICE_ROOT + 'COPYING.LIB'])['sha256']
        self.lock['licenses']['fex-license'] = identity(self.notices[package.NOTICE_ROOT + 'fex/LICENSE'])
        self.lock['toolchain']['bundledNotices'] = {'LICENSE.TXT': identity(self.notices[package.NOTICE_ROOT + 'toolchain/LICENSE.TXT'])}
        self.lock_path = self.root / 'sources.lock.json'; self.lock_path.write_text(json.dumps(self.lock))
        self.override = patch.object(package, 'LOCK', self.lock_path); self.override.start(); self.addCleanup(self.override.stop)
        self.icd = dict(file_format_version='1.0.0', ICD=dict(api_version='1.1.230',
                       library_path=package.IMAGES['lavapipe'][0]))
        self.data = {package.ICD: package.encoded(self.icd), package.ALSA: b'# synthetic ALSA fixture\n',
                     'usr/lib/os-release': b'ID=debian\nVERSION_ID="12"\n'}
        self.doc = dict(formatVersion=1, scope='source-built-native-arm64-wine-candidate', architecture='arm64',
                        sourceLockSha256=identity(self.lock_path.read_bytes())['sha256'],
                        baseImage=self.lock['baseImage']['reference'], snapshot=self.lock['snapshot']['id'],
                        wineRevision=self.lock['wine']['revision'], wineSourceArchiveSha256=self.lock['wine']['sourceArchive']['sha256'],
                        fexRevision=self.lock['fex']['revision'], fexSourceArchiveSha256=self.lock['fex']['archive']['sha256'],
                        toolchainArchiveSha256=self.lock['toolchain']['archive']['sha256'],
                        privatePeCopyProfile=self.lock['wine']['androidPrivatePeCopy'], wineVersion='wine-10.13',
                        packages=[dict(package='libc6:arm64', version='1-fixture', architecture='arm64',
                                       sourcePackage='glibc', sourceVersion='1-fixture')],
                        sourcePackages=[dict(package='glibc', version='1-fixture')], images={},
                        data={name: identity(data) for name, data in self.data.items()},
                        notices={name: identity(data) for name, data in self.notices.items()}, softwareGraphicsIcd=self.icd,
                        prefixInitialized=False, clientIncluded=False, androidQualified=False, gameplayQualified=False)
        self.images = {}
        for name, (path, allowed) in package.IMAGES.items():
            machine = allowed[0] if allowed is not None else None
            data = image(machine); self.images[path[1:]] = data
            self.doc['images'][name] = dict(path=path, **identity(data),
                **(dict(peMachine=hex(machine)) if machine is not None else dict(elfMachine=183, elfClass=2)))

    def prepare(self, extra=(), image_changes=None, data_changes=None):
        raw = package.encoded(self.doc); self.measured.write_bytes(raw)
        items = {**self.images, **self.data, **self.notices, package.MARKER: raw}
        items.update(image_changes or {}); items.update(data_changes or {})
        with tarfile.open(self.export, 'w', format=tarfile.GNU_FORMAT) as archive:
            for name, data in [*items.items(), *extra]:
                member = tarfile.TarInfo(name); member.mode = 0o755
                if isinstance(data, bytes):
                    member.size = len(data); archive.addfile(member, io.BytesIO(data))
                else:
                    member.type, member.linkname = data; archive.addfile(member)

    def test_measured_candidate_prepares_with_new_profiles_and_explicit_copy_budget(self):
        self.prepare([('usr/lib/wine-hardlink', (tarfile.LNKTYPE, 'opt/wine/bin/wine')),
                      ('usr/share/doc/synthetic-debian/copyright', b'preserved Debian notice\n')])
        report = package.build(self.export, self.measured, self.output)
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {package.ARCHIVE, package.MANIFEST, 'runtime.json', 'sources.lock.json',
                          'candidate-runtime.lock.json', 'package-build-receipt.json'})
        self.assertTrue(report['archiveReadBack']); self.assertTrue(report['sourceCompanionRequired'])
        self.assertEqual(report['maximumHardLinkCopies'], 1); self.assertEqual(report['maximumHardLinkCopyBytes'], 64)
        self.assertEqual(report['maximumPhysicalFileBytes'], report['archiveFileBytes'] + 64)
        candidate = json.loads((self.output / 'candidate-runtime.lock.json').read_bytes())
        self.assertEqual(candidate['scope'], 'separate-native-arm64-wine-candidate')
        selected = candidate['packages']['wine-arm64']
        self.assertEqual(len(selected['sourceArchives']), 3)
        self.assertEqual(selected['wineEnvironment'], {'WINE_ANDROID_PRIVATE_PE_COPY': '1'})
        for profile in ('softwareGraphics', 'softwareAudio'):
            self.assertEqual(candidate[profile]['runtimeArchiveSha256'], selected['archive']['sha256'])
        self.assertEqual(candidate['softwareGraphics']['icdApiVersion'], '1.1.230')
        self.assertEqual(candidate['softwareGraphics']['icdLibrary'], package.IMAGES['lavapipe'][0])
        staged = self.root / 'prepared'
        audit = prepare_runtime.prepare(selected, self.output, staged)
        self.assertTrue(audit['archiveExtracted']); self.assertTrue(audit['stagedFilesReadBack'])
        self.assertFalse(audit['androidRuntimeQualified'])
        self.assertEqual((staged / 'rootfs/usr/share/doc/synthetic-debian/copyright').read_bytes(), b'preserved Debian notice\n')
        for name, data in self.notices.items():
            self.assertEqual((staged / 'rootfs' / name).read_bytes(), data)
        lock, _, _, environment = qualify_wine_arm64.runtime_selection(self.output / 'candidate-runtime.lock.json', True)
        self.assertEqual(lock, candidate); self.assertEqual(environment, selected['wineEnvironment'])

    def test_existing_outputs_are_never_overwritten(self):
        self.output.mkdir(); saved = self.output / 'saved'; saved.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'output-exists'):
            package.build(self.export, self.measured, self.output)
        self.assertEqual(saved.read_bytes(), b'keep')

    def test_metadata_requires_exact_sources_inventories_profiles_and_unqualified_flags(self):
        raw = package.encoded(self.doc); package.metadata(raw)
        changes = {'sourceLockSha256': '0' * 64, 'wineRevision': 'a' * 40, 'fexRevision': 'b' * 40,
                   'wineSourceArchiveSha256': 'c' * 64, 'fexSourceArchiveSha256': 'd' * 64,
                   'toolchainArchiveSha256': 'e' * 64, 'baseImage': 'debian:bookworm', 'snapshot': 'latest',
                   'privatePeCopyProfile': {}, 'images': {}, 'data': {}, 'sourcePackages': [],
                   'prefixInitialized': True, 'clientIncluded': True, 'androidQualified': True,
                   'arm64Qualified': True, 'graphicsQualified': True, 'gameplayQualified': True,
                   'architecture': 'amd64', 'formatVersion': True}
        for key, wrong in changes.items():
            changed = copy.deepcopy(self.doc); changed[key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                package.metadata(package.encoded(changed))
        changed = copy.deepcopy(self.doc); changed['packages'][0]['architecture'] = 'amd64'
        with self.assertRaisesRegex(ValueError, 'package-identity'):
            package.metadata(package.encoded(changed))
        for field in ('version', 'sourceVersion'):
            changed = copy.deepcopy(self.doc); changed['packages'][0][field] = 'placeholder'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'package-selector'):
                package.metadata(package.encoded(changed))

    def test_mixed_pe_machines_are_allowed_only_for_named_arm64ec_and_i386_images(self):
        for name in ('libarm64ecfex.dll', 'vcruntime140_1.dll'):
            changed = copy.deepcopy(self.doc); changed['images'][name]['peMachine'] = '0xa641'
            package.metadata(package.encoded(changed))
        for name, wrong in (('kernel32.dll', '0x8664'), ('libwow64fex.dll', '0xa641'),
                            ('i386Ntdll', '0xaa64'), ('libarm64ecfex.dll', '0x14c')):
            changed = copy.deepcopy(self.doc); changed['images'][name]['peMachine'] = wrong
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'pe-architecture'):
                package.metadata(package.encoded(changed))
        original = copy.deepcopy(self.doc)
        ec_images = {}
        for name in ('libarm64ecfex.dll', 'vcruntime140_1.dll'):
            data = image(0xa641); self.doc['images'][name].update(identity(data), peMachine='0xa641')
            ec_images[package.IMAGES[name][0][1:]] = data
        self.prepare(image_changes=ec_images)
        package.build(self.export, self.measured, self.root / 'ec-output')
        self.doc = copy.deepcopy(original)
        for name, data in [('wine', image(0xaa64)), ('kernel32.dll', image(0x8664)), ('i386Ntdll', image(0xaa64))]:
            path = package.IMAGES[name][0][1:]
            # Keep byte hashes truthful so actual header validation must reject it.
            self.doc['images'][name].update(identity(data))
            self.prepare(image_changes={path: data})
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'component-(elf|pe)-mismatch'):
                package.build(self.export, self.measured, self.output)
            self.assertFalse(self.output.exists())
            self.doc = copy.deepcopy(original)

    def test_notices_and_actual_icd_cannot_be_substituted_by_metadata_assertions(self):
        for name in self.notices:
            changed = copy.deepcopy(self.doc); changed['notices'].pop(name)
            with self.subTest(name=name), self.assertRaises(ValueError):
                package.metadata(package.encoded(changed))
        changed = copy.deepcopy(self.doc); changed['notices'][package.NOTICE_ROOT + 'fex/LICENSE']['sha256'] = 'a' * 64
        with self.assertRaisesRegex(ValueError, 'original-notice'):
            package.metadata(package.encoded(changed))
        actual_icd = package.encoded(dict(self.icd, ICD=dict(self.icd['ICD'], api_version='1.2.999')))
        self.doc['data'][package.ICD] = identity(actual_icd)
        self.prepare(data_changes={package.ICD: actual_icd})
        with self.assertRaisesRegex(ValueError, 'actual-icd-mismatch'):
            package.build(self.export, self.measured, self.output)
        self.assertFalse(self.output.exists())

    def test_state_unsafe_links_and_changed_backing_bytes_fail_without_publication(self):
        for name in ('root/.wine/system.reg', 'home/a/.wine/user.reg', 'work/state', 'prefix/drive_c/test.exe',
                     'client/client.json', 'session/log', 'private-pe-fixtures/test.exe',
                     'private-pe-evidence/receipt.json', 'esteria-qualification/receipt.json'):
            self.prepare([(name, b'old state')])
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'wine-prefix-or-session-state'):
                package.build(self.export, self.measured, self.output)
            self.assertFalse(self.output.exists())
        for item in [('escape', (tarfile.SYMTYPE, '../../escape')), ('var/lib/mysql/auto.cnf', b'private state'),
                     ('root/.my.cnf', b'private credential')]:
            self.prepare([item])
            with self.subTest(item=item), self.assertRaises(ValueError):
                package.build(self.export, self.measured, self.output)
            self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
