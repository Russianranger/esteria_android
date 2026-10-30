import copy
import hashlib
import io
import json
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile
from urllib.error import HTTPError

from tools import release_server_dependencies as release


def pin(data):
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


class SourceValidation(unittest.TestCase):
    def fixture(self, directory, *, extra=None, changed_archive=False, descriptor_version='1.0'):
        original = b'original source archive bytes'
        descriptor = ('Format: 3.0 (quilt)\nSource: fixture\nVersion: ' + descriptor_version +
                      '\nChecksums-Sha256:\n ' + pin(original)['sha256'] + ' ' + str(len(original)) + ' fixture_1.0.orig.tar.xz\n').encode()
        originals = {'fixture_1.0.orig.tar.xz': original, 'fixture_1.0.dsc': descriptor}
        metadata = {'sourcePackages': [{'package': 'fixture', 'version': '1.0'}]}
        runtime = release.encoded(metadata); source_lock = b'{}\n'; license_bytes = b'original fixture license\n'
        manifest = dict(formatVersion=1, scope='installed-ubuntu-package-corresponding-sources',
                        runtimeManifestSha256=pin(runtime)['sha256'], sourceLockSha256=pin(source_lock)['sha256'],
                        sourcePackages=metadata['sourcePackages'],
                        files=[dict(file=name, **pin(data)) for name, data in originals.items()],
                        fileBytes=sum(map(len, originals.values())))
        encoded = release.encoded(manifest)
        path = directory / 'sources.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in originals.items():
                z.writestr(release.SOURCE_PREFIX + name, b'corrupt' if changed_archive and name.endswith('.xz') else data)
            for name, data in [('SOURCE-MANIFEST.json', encoded), ('server-runtime.json', runtime), ('sources.lock.json', source_lock)]:
                z.writestr(release.SOURCE_PREFIX + name, data)
            z.writestr('LICENSE', license_bytes)
            if extra:
                z.writestr(extra, b'not dependency material')
        lock = {'artifactInputs': {'sources': release.identity(path)}, 'sourceCompanionWrappers': {'LICENSE': pin(license_bytes)}}
        measured = {'runtimeMetadata': pin(runtime), 'sourceLock': pin(source_lock),
                    'sourceCompanion': {'manifestSha256': pin(encoded)['sha256'], 'sourcePackages': 1,
                                        'files': 2, 'fileBytes': manifest['fileBytes']}}
        return path, lock, measured, metadata

    def test_all_source_bytes_and_descriptor_closure_are_checked(self):
        with tempfile.TemporaryDirectory() as name:
            values = self.fixture(Path(name))
            _, proof = release.validate_sources(*values)
            self.assertEqual(proof['sourcePackages'], 1)
            self.assertEqual(proof['originalArchives'], 2)

    def test_source_corruption_extra_files_and_wrong_version_fail(self):
        for options in ({'changed_archive': True}, {'extra': 'private-state/accounts/password'}, {'descriptor_version': '2.0'}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as name:
                values = self.fixture(Path(name), **options)
                with self.assertRaises(ValueError):
                    release.validate_sources(*values)

    def test_zip_traversal_symlinks_duplicate_and_oversize_metadata_rejected(self):
        for entry_names in (['../outside'], ['/absolute'], ['x', 'x'], ['a\\b']):
            with self.subTest(names=entry_names), tempfile.TemporaryDirectory() as name:
                path = Path(name) / 'bad.zip'
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(path, 'w') as z:
                        for entry in entry_names:
                            z.writestr(entry, b'x')
                with zipfile.ZipFile(path) as z, self.assertRaises(ValueError):
                    release.zip_members(z)
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / 'bad.zip'
            entry = zipfile.ZipInfo('link'); entry.create_system = 3
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr(entry, '/outside')
            with zipfile.ZipFile(path) as z, self.assertRaises(ValueError):
                release.zip_members(z)

    def test_every_package_copyright_resolves_to_a_nonempty_file(self):
        with tempfile.TemporaryDirectory() as name:
            archive = Path(name) / 'runtime.tar.gz'
            with tarfile.open(archive, 'w:gz', format=tarfile.GNU_FORMAT) as tar:
                item = tarfile.TarInfo('usr/share/doc/source/copyright'); item.size = 7
                tar.addfile(item, io.BytesIO(b'license'))
                link = tarfile.TarInfo('usr/share/doc/library'); link.type = tarfile.SYMTYPE; link.linkname = 'source'
                tar.addfile(link)
            limits = dict(entries=20, pathBytes=4096, fileBytes=1024)
            metadata = {'packages': [{'package': 'source'}, {'package': 'library:arm64'}]}
            self.assertEqual(release.validate_notices(archive, metadata, limits),
                             dict(binaryPackages=2, resolvedCopyrightFiles=1))
            metadata['packages'].append({'package': 'missing'})
            with self.assertRaisesRegex(ValueError, 'copyright'):
                release.validate_notices(archive, metadata, limits)

    def test_current_publication_pin_preserves_measured_provider_lock(self):
        lock, measured = release.load_lock()
        self.assertEqual(lock['targetCommit'], measured['integrationRevision'])
        self.assertEqual(lock['artifactInputs']['sources']['bytes'], 954236077)


class FakeGithub:
    """Transport fixture for mutation policy only; no network/release claim."""
    def __init__(self, lock, identities, *, existing=True, draft=False):
        self.lock, self.identities = lock, identities
        self.mutations, self.downloads = [], []
        self.ref = {'object': {'type': 'commit', 'sha': lock['targetCommit']}} if existing else None
        self.release = dict(id=1, tag_name=lock['tag'], draft=draft, prerelease=True,
                            body=release.release_body(lock), html_url='https://github.com/example', immutable=False) if existing else None
        self.assets = {name: self.asset(name, values, index + 1) for index, (name, values) in enumerate(identities.items())} if existing else {}

    def asset(self, name, values, id_):
        return dict(name=name, id=id_, state='uploaded', size=values['bytes'], digest='sha256:' + values['sha256'],
                    browser_download_url='https://github.com/' + release.REPOSITORY + '/releases/download/' + self.lock['tag'] + '/' + name)

    def json(self, path, *, method='GET', value=None, missing=False):
        if method != 'GET':
            self.mutations.append((method, path))
            if path == '/git/refs':
                self.ref = {'object': {'type': 'commit', 'sha': value['sha']}}; return self.ref
            if path == '/releases':
                self.release = dict(id=1, **value, html_url='https://github.com/example', immutable=False); return self.release
            if path == '/releases/1':
                self.release.update(value); return self.release
            raise AssertionError(path)
        if path.startswith('/git/ref/'):
            return self.ref
        if path.startswith('/releases/tags/'):
            return self.release
        if path == '/releases/1/assets?per_page=100':
            return list(self.assets.values())
        raise AssertionError(path)

    def upload(self, release_id, name, path, values):
        self.mutations.append(('UPLOAD', name))
        self.assets[name] = self.asset(name, values, len(self.assets) + 1)
        return self.assets[name]

    def download(self, url, target, expected):
        self.downloads.append(url)


class PublicationGuards(unittest.TestCase):
    def setUp(self):
        self.lock = dict(tag='deps-server-arm64-test', targetCommit='a' * 40, workflowRun=10)
        self.identities = {name: pin(name.encode()) for name in sorted(release.RELEASE_FILES)}
        self.check = patch.object(release, 'verify_candidate', return_value=self.identities)
        self.check.start(); self.addCleanup(self.check.stop)

    def test_exact_published_release_is_read_only_and_every_asset_is_read_back(self):
        api = FakeGithub(self.lock, self.identities)
        result = release.publish(api, Path('/fixture'), self.lock, {})
        self.assertEqual(api.mutations, [])
        self.assertEqual(len(api.downloads), len(self.identities))
        self.assertFalse(result['githubImmutable'])
        self.assertTrue(result['publisherNeverOverwrites'])

    def test_changed_tag_asset_or_unknown_asset_is_never_modified(self):
        for change in ('tag', 'asset', 'extra'):
            api = FakeGithub(self.lock, self.identities, draft=True)
            if change == 'tag': api.ref['object']['sha'] = 'b' * 40
            elif change == 'asset': next(iter(api.assets.values()))['digest'] = 'sha256:' + '0' * 64
            else: api.assets['game.mpq'] = api.asset('game.mpq', pin(b'game'), 99)
            with self.subTest(change=change), self.assertRaises(ValueError):
                release.publish(api, Path('/fixture'), self.lock, {})
            self.assertEqual(api.mutations, [])

    def test_published_missing_asset_cannot_be_repaired(self):
        api = FakeGithub(self.lock, self.identities)
        api.assets.pop(next(iter(api.assets)))
        with self.assertRaisesRegex(ValueError, 'no-repair'):
            release.publish(api, Path('/fixture'), self.lock, {})
        self.assertEqual(api.mutations, [])

    def test_new_release_stays_draft_until_every_asset_has_been_uploaded_and_checked(self):
        api = FakeGithub(self.lock, self.identities, existing=False)
        result = release.publish(api, Path('/fixture'), self.lock, {})
        self.assertEqual(api.mutations[:2], [('POST', '/git/refs'), ('POST', '/releases')])
        self.assertEqual(api.mutations[-1], ('PATCH', '/releases/1'))
        self.assertEqual(sum(kind == 'UPLOAD' for kind, _ in api.mutations), len(self.identities))
        self.assertEqual(len(api.downloads), len(self.identities))
        self.assertEqual(result['targetCommit'], 'a' * 40)

    def test_owned_partial_draft_resumes_missing_assets_without_replacement(self):
        api = FakeGithub(self.lock, self.identities, draft=True)
        name = api.assets.pop(next(iter(api.assets)))['name']
        release.publish(api, Path('/fixture'), self.lock, {})
        self.assertEqual(api.mutations, [('UPLOAD', name), ('PATCH', '/releases/1')])


class NetworkBoundary(unittest.TestCase):
    def test_github_credential_never_follows_object_store_redirect(self):
        client = release.Github('fixture-token-only')
        requests = []
        class Opener:
            def open(self, request, **kwargs):
                requests.append(request)
                if len(requests) == 1:
                    raise HTTPError(request.full_url, 302, 'redirect',
                                    {'Location': 'https://release-assets.githubusercontent.com/object?signature=fixture'}, None)
                return io.BytesIO(b'fixture')
        client.opener = Opener()
        with client.open(release.API + '/actions/artifacts/1/zip') as response:
            self.assertEqual(response.read(), b'fixture')
        self.assertEqual(requests[0].get_header('Authorization'), 'Bearer fixture-token-only')
        self.assertIsNone(requests[1].get_header('Authorization'))

    def test_other_repository_and_unexpected_redirect_are_rejected(self):
        client = release.Github('fixture-token-only')
        with self.assertRaisesRegex(ValueError, 'repository-boundary'):
            client.open('https://api.github.com/repos/other/repository/releases')
        class Opener:
            def open(self, request, **kwargs):
                raise HTTPError(request.full_url, 302, 'redirect', {'Location': 'https://unrelated.example/object'}, None)
        client.opener = Opener()
        with self.assertRaisesRegex(ValueError, 'unexpected-download-redirect'):
            client.open(release.API + '/actions/artifacts/1/zip')


if __name__ == '__main__':
    unittest.main()
