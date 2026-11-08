import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools import stock_renderer_provider as renderer


class RendererProviderTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.compat = self.root/'review.json'
        self.assets = self.root/renderer.client.ASSETS
        self.assets.mkdir(parents=True)
        self.previous = {
            renderer.BASE+renderer.client.ARCHIVE: dict(bytes=120, sha256='c'*64),
            renderer.BASE+'NOTICE.txt': self.put('NOTICE.txt', b'original notice'),
            renderer.BASE+'provider.json': dict(bytes=81, sha256='d'*64),
            'shader-tools/shader-tools-arm64.archive': dict(bytes=77, sha256='e'*64),
            'turnip/provider.json': dict(bytes=17, sha256='a'*64),
        }
        pin = self.put(renderer.client.ARCHIVE, b'fixture archive')
        self.item = {key:'f'*64 for key in renderer.HASHES}
        self.item.update(formatVersion=1, scope=renderer.SCOPE, preparedClientRevision=renderer.STOCK,
                         executableRevision=renderer.EXECUTABLE, sourceDiffSha256=renderer.SOURCE_DIFF, executableSha256='1'*64, previousClientArchiveSha256='c'*64,
                         clientArchiveSha256=pin['sha256'], shaderToolsArchiveSha256='e'*64)
        self.save(self.item)
        self.put('provider.json', renderer.client.encoded(dict(
            sourceRevision=renderer.EXECUTABLE, sourceLockSha256='f'*64, requiredWineArchiveSha256='f'*64,
            archive={**pin, 'assetPath':renderer.BASE+renderer.client.ARCHIVE},
            requiredFiles={'bin/WowClient64.exe':{'sha256':'1'*64}})))

    def put(self, name, data):
        path = self.assets/name
        path.write_bytes(data)
        return renderer.client.identity(path)

    def save(self, value):
        data = renderer.client.encoded(value)
        self.compat.write_bytes(data)
        self.put(renderer.DESCRIPTOR, data)

    def test_exact_review_and_apk_subtree(self):
        actual = renderer.apk_members(self.previous, self.compat, self.root)
        self.assertEqual(set(actual) - self.previous.keys(), {renderer.BASE+renderer.DESCRIPTOR})
        self.assertEqual(actual['turnip/provider.json'], self.previous['turnip/provider.json'])
        self.assertEqual(actual[renderer.BASE+'NOTICE.txt'], self.previous[renderer.BASE+'NOTICE.txt'])
        self.assertEqual(renderer.descriptor(self.compat), self.item)

    def test_changed_installed_asset_and_wrong_donor_are_rejected(self):
        for name in ('NOTICE.txt', renderer.client.ARCHIVE, renderer.DESCRIPTOR):
            with self.subTest(name=name):
                old = (self.assets/name).read_bytes()
                self.put(name, old+b'x')
                with self.assertRaises(ValueError):
                    renderer.apk_members(self.previous, self.compat, self.root)
                self.put(name, old)
        altered = copy.deepcopy(self.previous)
        altered[renderer.BASE+renderer.client.ARCHIVE]['sha256'] = '1'*64
        with self.assertRaisesRegex(ValueError, 'donor'):
            renderer.apk_members(altered, self.compat, self.root)
        self.put('unexpected', b'')
        with self.assertRaisesRegex(ValueError, 'file-set'):
            renderer.apk_members(self.previous, self.compat, self.root)

    def test_strict_descriptor_types_and_new_identities(self):
        for change in ({'formatVersion':True}, {'unknown':1}, {'scope':'stock'}, {'scope':'stock-renderer-only'}, {'executableRevision':renderer.STOCK},
                       {'sourceDiffSha256':'AA'*32}, {'previousExecutableSha256':self.item['executableSha256']}):
            self.save(dict(self.item, **change))
            with self.subTest(change=change), self.assertRaises(ValueError):
                renderer.descriptor(self.compat)
        self.compat.write_text(json.dumps(self.item))
        with self.assertRaises(ValueError):
            renderer.descriptor(self.compat)

    def test_git_diff_is_restricted_to_exact_reviewed_files(self):
        source = self.root/'client'
        source.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',source,*args])
        git('init','-q')
        git('config','user.name','Fixture')
        git('config','user.email','fixture@example.invalid')
        git('commit','--allow-empty','-qm','base')
        base = git('rev-parse','HEAD').decode().strip()
        for name in renderer.REVIEWED_FILES:
            target = source/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('fixture\n')
        git('add','--all')
        git('commit','-qm','renderer')
        head = git('rev-parse','HEAD').decode().strip()
        expected = renderer.digest(git('diff','--binary','--full-index','--no-renames',base,head))
        self.assertEqual(renderer.changed_files(source, base, head, renderer.REVIEWED_FILES), expected)
        with self.assertRaisesRegex(ValueError, 'renderer-diff-paths'):
            renderer.changed_files(source, base, head, renderer.LOADER_FILES)
        (source/'protocol.h').write_text('fixture')
        git('add','--all')
        git('commit','-qm','unreviewed')
        with self.assertRaisesRegex(ValueError,'renderer-diff-paths'):
            renderer.changed_files(source, base, git('rev-parse','HEAD').decode().strip(), renderer.REVIEWED_FILES)

    def test_codec_and_notice_inventory_must_be_identical(self):
        member = dict(bytes=10,sha256='a'*64)
        old = dict(sourceRevision=renderer.STOCK, sourceLockSha256=renderer.client.identity(renderer.client.SOURCE_LOCK)['sha256'],
                   archive={'sha256':'c'*64}, requiredFiles={'bin/WowClient64.exe':member,'bin/XvidDecoder.dll':member,
                   'notices/license':member}, protocol={'slots':254}, capabilities={}, requiredWineRuntime={},
                   requiredWineArchiveSha256='f'*64, selectedInputs={})
        new = copy.deepcopy(old)
        new.update(sourceRevision=renderer.EXECUTABLE, archive={'sha256':'b'*64})
        new['requiredFiles']['bin/WowClient64.exe'] = dict(member, sha256='9'*64)
        shader = dict(clientRevision=renderer.STOCK, archive={'sha256':'e'*64}, toolManifestSha256='d'*64)
        self.assertEqual(renderer.issue(self.previous, old, shader, new, '4'*64)['executableSha256'], '9'*64)
        for key in ('bin/XvidDecoder.dll','notices/license'):
            bad = copy.deepcopy(new)
            bad['requiredFiles'][key]['sha256'] = 'f'*64
            with self.subTest(key=key), self.assertRaisesRegex(ValueError,'renderer-provider-bytes-changed'):
                renderer.issue(self.previous, old, shader, bad, '4'*64)
