"""Shared upload-only draft policy for validated dependency releases.

No tag creation, release creation/finalization, settings changes or replacement.
The network transport is the already qualified repository-bound server helper.
"""
import time
from urllib.parse import quote

try:
    from . import release_server_dependencies as transport
except ImportError:
    import release_server_dependencies as transport

Github = transport.Github
require = transport.require


class DraftPublication:
    def __init__(self, lock, body, verifier):
        self.lock, self.body, self.verifier = lock, body, verifier

    def check_release(self, release):
        body = release.get('body')
        require(release['tag_name'] == self.lock['tag'] and release['prerelease'] is True and
                isinstance(body, str) and body.replace('\r\n', '\n') == self.body,
                'existing-release-identity-mismatch; release-preserved')

    def check_ref(self, api, optional=False):
        ref = api.json('/git/ref/tags/' + quote(self.lock['tag'], safe=''), missing=optional)
        require((optional and ref is None) or (ref is not None and ref['object']['type'] == 'commit' and
                ref['object']['sha'] == self.lock['targetCommit']), 'existing-tag-target-mismatch; tag-preserved')

    def find_release(self, api):
        matches = []
        for page in range(1, 11):
            rows = api.json('/releases?per_page=100&page=' + str(page))
            matches.extend(row for row in rows if row['tag_name'] == self.lock['tag'])
            if len(rows) < 100: break
        else:
            raise ValueError('release-list-bound; no-mutation')
        require(len(matches) == 1, 'exact-owned-UI-draft-required; no-release-created')
        self.check_release(matches[0])
        return matches[0]

    def stored_assets(self, api, release_id, identities):
        rows = api.json('/releases/' + str(release_id) + '/assets?per_page=100')
        assets = {item['name']: item for item in rows}
        require(len(assets) == len(rows) and set(assets).issubset(identities), 'unexpected-existing-release-assets')
        for name, row in assets.items(): transport.check_stored_asset(api, row, identities[name])
        return assets

    def verify_published(self, api, candidate, wait_seconds=0):
        require(type(wait_seconds) is int and 0 <= wait_seconds <= 1200, 'publication-wait-bound')
        identities = self.verifier(candidate)
        deadline = time.monotonic() + wait_seconds
        while True:
            release = api.json('/releases/tags/' + quote(self.lock['tag'], safe=''), missing=True)
            if release is not None and release['draft'] is False: break
            require(time.monotonic() < deadline, 'published-release-not-yet-available; no-mutation')
            time.sleep(min(15, max(0, deadline - time.monotonic())))
        self.check_release(release)
        self.check_ref(api)
        assets = self.stored_assets(api, release['id'], identities)
        require(set(assets) == set(identities), 'published-release-missing-assets; no-repair-or-overwrite')
        return transport.publication_receipt(release, assets, identities, self.lock)

    def upload_draft(self, api, candidate):
        identities = self.verifier(candidate)
        release = self.find_release(api)
        if release['draft'] is False:
            return dict(draft=False, completeAssetSetVerified=True,
                        published=self.verify_published(api, candidate))
        require(release['draft'] is True and release['target_commitish'] == self.lock['targetCommit'],
                'UI-draft-must-bind-exact-packaging-commit')
        self.check_ref(api, optional=True)
        release_id = release['id']
        assets = self.stored_assets(api, release_id, identities)
        for name, expected in identities.items():
            if name not in assets:
                current = api.json('/releases/' + str(release_id))
                self.check_release(current)
                require(current['draft'] is True and current['target_commitish'] == self.lock['targetCommit'],
                        'UI-draft-changed-before-upload; no-metadata-mutation')
                assets[name] = api.upload(release_id, name, candidate / name, expected)
                transport.check_stored_asset(api, assets[name], expected)
        current = api.json('/releases/' + str(release_id))
        self.check_release(current)
        require(current['draft'] is True and current['target_commitish'] == self.lock['targetCommit'],
                'UI-draft-changed-before-receipt')
        return dict(formatVersion=1, repository=transport.REPOSITORY, tag=self.lock['tag'],
                    targetCommit=self.lock['targetCommit'], releaseId=release_id, draft=True,
                    completeAssetSetVerified=True, publicationQualified=False,
                    assets={name: dict(identities[name]) for name in sorted(identities)})
