"""Read exact public CI inputs through GitHub's asset endpoint when its browser CDN is unavailable."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import quote

from tools import release_server_dependencies as github

ROOT = Path(__file__).resolve().parents[1]


class LockedRelease(github.Github):
    """The existing HTTPS transport sends authorization only to the repository API."""
    def __init__(self, publication):
        super().__init__(os.environ.get('CI_PUBLIC_RELEASE_TOKEN'))
        self.publication = publication
        self.assets = None

    def download(self, url, target, expected):
        release = self.publication
        name = target.name
        prefix = f"https://github.com/{github.REPOSITORY}/releases/download/{release['tag']}/"
        github.require(re.fullmatch(r'[A-Za-z0-9_.-]+', name) and url == prefix + name, 'exact-release-asset-required')
        pin = release['assets'][name]
        github.require(pin['url'] == url and pin['bytes'] == expected['bytes'] and pin['sha256'] == expected['sha256'],
                       'release-asset-pin-mismatch')
        if self.assets is None:
            live = self.json(f"/releases/{int(release['releaseId'])}")
            reference = self.json('/git/ref/tags/' + quote(release['tag'], safe=''))
            github.require(live['id'] == release['releaseId'] and live['tag_name'] == release['tag']
                           and live['draft'] is False and reference['object'] == dict(type='commit', sha=release['targetCommit'],
                               url=github.API + '/git/commits/' + release['targetCommit']), 'release-source-mismatch')
            self.assets = {asset['name']:asset for asset in live['assets']}
            github.require(len(self.assets) == len(live['assets']), 'ambiguous-release-asset')
        asset = self.assets[name]
        asset_id = asset['id']
        github.require(type(asset_id) is int and asset_id > 0 and asset['state'] == 'uploaded'
                       and asset['browser_download_url'] == url and asset['size'] == expected['bytes']
                       and asset['digest'] == 'sha256:' + expected['sha256']
                       and pin.get('assetId',asset_id) == asset_id, 'live-release-asset-mismatch')
        # A run-unique query prevents reuse of a cached expired object-store redirect.
        stamp = f"{os.environ.get('GITHUB_RUN_ID','0')}-{os.environ.get('GITHUB_RUN_ATTEMPT','0')}"
        github.require(re.fullmatch('[0-9]+-[0-9]+',stamp), 'invalid-ci-readback-id')
        super().download(f'{github.API}/releases/assets/{asset_id}?run={stamp}', target, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=('server-dependencies','shader-cohort','wine-cohort'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--packaging-source', type=Path)
    parser.add_argument('--providers', type=Path)
    args = parser.parse_args()
    if args.component == 'server-dependencies':
        lock, pin = github.load_lock()
        result = github.fetch_published(LockedRelease(lock['published']), args.output, lock, pin, candidate=True)
        print(json.dumps(result, sort_keys=True))
    else:
        cohort = ROOT/'runtime/wine-cohort-publication'
        receipt = cohort/'published-release.json'
        publication = github.small_json(receipt)
        if args.component == 'wine-cohort':
            from tools import fetch_wine_cohort
            if args.packaging_source is None or args.providers is None:
                parser.error('wine-cohort needs --packaging-source and --providers')
            proof = fetch_wine_cohort.fetch(cohort/'dependency-release.lock.json', receipt,
                                           args.packaging_source, args.output, args.providers, LockedRelease(publication))
            print(json.dumps(proof, sort_keys=True))
            return
        name = 'provider-assets.tar.gz'
        row = publication['assets'][name]
        LockedRelease(publication).download(row['url'], args.output/name, row)


if __name__ == '__main__':
    main()
