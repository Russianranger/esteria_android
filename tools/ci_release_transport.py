"""Read exact public CI inputs through GitHub's asset endpoint when its browser CDN is unavailable."""
import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import quote, urlsplit
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from tools import prepare_runtime

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


def fetch_external(repository, asset_id, url, expected, target):
    """Read only one pinned asset in either of the two upstream release repositories."""
    github.require(repository in {'Russianranger/wowdecomp_esteria','Russianranger/uo-android-launcher'}
                   and type(asset_id) is int and asset_id > 0
                   and url.startswith(f'https://github.com/{repository}/releases/download/'),
                   'unexpected-external-release')
    opener = build_opener(github.NoRedirect)
    api = f'https://api.github.com/repos/{repository}/releases/assets/{asset_id}'
    stamp = f"{os.environ.get('GITHUB_RUN_ID','0')}-{os.environ.get('GITHUB_RUN_ATTEMPT','0')}"
    github.require(re.fullmatch('[0-9]+-[0-9]+',stamp), 'invalid-ci-readback-id')
    def open_asset(source, timeout):
        github.require(source == url, 'external-release-source-changed')
        headers = {'Accept':'application/octet-stream','User-Agent':'esteria-public-ci'}
        token = os.environ.get('CI_PUBLIC_RELEASE_TOKEN')
        if token:
            headers['Authorization'] = 'Bearer '+token
        try:
            return opener.open(Request(api+'?run='+stamp, headers=headers), timeout=timeout)
        except HTTPError as error:
            if error.code not in (301,302,303,307,308):
                raise ValueError(f'upstream public asset {asset_id} HTTP {error.code}') from None
            location = error.headers['Location']
            host = urlsplit(location)
            github.require(host.scheme == 'https' and host.hostname and not host.username and not host.password
                           and host.hostname.endswith(('.githubusercontent.com','.blob.core.windows.net')),
                           'unexpected-external-asset-redirect')
        # Fresh request. An object-store redirect never receives authorization.
        try:
            return opener.open(Request(location,headers={'User-Agent':'esteria-public-ci'}),timeout=timeout)
        except HTTPError as error:
            raise ValueError(f'upstream public asset {asset_id} redirected HTTP {error.code}') from None
    return prepare_runtime.fetch(dict(expected,file=target.name,url=url),target.parent,opener=open_asset)


def client_inputs(output, revision, build):
    receipt = github.small_json(ROOT/'runtime/evidence/non-custom-v19-public-client-inputs.json')
    name = 'client-ARM64-'+revision+'.zip'
    tag = 'stock-client-arm64-'+revision
    repository = 'Russianranger/wowdecomp_esteria'
    github.require(receipt['commit'] == revision and receipt['tag'] == tag
                   and receipt['workflowRun'] == build['workflowRun']
                   and receipt['windowsArm64OriginalArtifact'] == build['artifactId']
                   and receipt['completeAnonymousReadback'] is True, 'client-public-source-mismatch')
    rows = {a['name']:a for a in receipt['assets']}
    github.require(len(rows) == len(receipt['assets']) == 3 and set(rows) == {name,'client-corresponding-source.tar.gz','source-receipt.json'}
                   and all(rows[name][k] == build['artifact'][k] for k in ('bytes','sha256')), 'client-release-roster')
    for n,row in rows.items():
        url = f'https://github.com/{repository}/releases/download/{tag}/{n}'
        github.require(row['publicUrl'] == url,'client-asset-url')
        target = output/('client-original.zip' if n == name else n)
        fetch_external(repository,row['id'],url,dict(bytes=row['bytes'],sha256=row['sha256']),target)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=('server-dependencies','shader-cohort','wine-cohort','wine-runtime','proot-original'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--packaging-source', type=Path)
    parser.add_argument('--providers', type=Path)
    args = parser.parse_args()
    if args.component == 'server-dependencies':
        lock, pin = github.load_lock()
        result = github.fetch_published(LockedRelease(lock['published']), args.output, lock, pin, candidate=True)
        print(json.dumps(result, sort_keys=True))
    elif args.component == 'proot-original':
        pin = github.small_json(ROOT/'runtime/proot/sources.lock.json')['source']
        fetch_external('Russianranger/uo-android-launcher',578164402,pin['url'],pin,args.output)
    elif args.component == 'wine-runtime':
        from tools import fetch_wine_arm64_release
        parent = ROOT/'runtime/wine-arm64-publication'
        receipt = parent/'published-release.json'
        publication = github.small_json(receipt)
        proof = fetch_wine_arm64_release.fetch(parent/'dependency-release.lock.json',receipt,args.output,LockedRelease(publication))
        print(json.dumps(proof, sort_keys=True))
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
