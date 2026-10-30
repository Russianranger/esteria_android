#!/usr/bin/env python3
"""Read exact public Wine inputs and full original sources without Actions expiry.

The historical producer recipe is checked against its Git blobs. This consumer's
own code identity is recorded separately; it never impersonates that producer.
No runtime executes and no release or production pin is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import quote

try:
    from . import release_wine_arm64 as release
except ImportError:
    import release_wine_arm64 as release

require = release.require
archives = release.archives
encoded = release.encoded


def selection(path):
    lock = release.shared.small_json(path)
    require(type(lock) is dict and set(lock) == {'formatVersion','repository','scope','tag','targetCommit',
            'runtimeInputFile','runtimeInput','recipeInputs'} and type(lock.get('formatVersion')) is int and
            lock['formatVersion'] == 1 and lock['repository'] == release.shared.REPOSITORY and
            lock['scope'] == release.SCOPE and lock['tag'] == release.TAG and
            re.fullmatch('[0-9a-f]{40}',lock.get('targetCommit','')), 'public-wine-release-selection')
    require(lock['runtimeInputFile'] == release.INPUT_IDENTITY and
            hashlib.sha256(encoded(lock['runtimeInput'])).hexdigest() == release.INPUT_CANONICAL_SHA256,
            'public-wine-original-input-changed')
    recipe = lock['recipeInputs']
    require(type(recipe) is dict and 1 <= len(recipe) <= 128 and release.RECIPE_ROOTS <= recipe.keys(),
            'public-wine-producer-recipe-roster')
    for name, expected in recipe.items():
        require(release.bytes_identity(release.git_blob(lock['targetCommit'],name)) == expected,
                'public-wine-producer-git-blob-mismatch:' + name)
    return lock


def expected_assets(lock):
    pin = lock['runtimeInput']
    assets = dict(pin['files'], **{release.SOURCE_ZIP:pin['sourcesArtifact'], release.INPUT_LOCK:lock['runtimeInputFile'],
                                  'NOTICE.txt':release.bytes_identity(release.NOTICE)})
    assets['release-manifest.json'] = release.bytes_identity(encoded(release.manifest(lock,assets)))
    assets['SHA256SUMS'] = release.bytes_identity(release.checksums(assets))
    require(set(assets) == release.RELEASE_FILES, 'public-wine-asset-roster')
    return assets


def public_identity(api, lock, publication, expected):
    require(publication.get('formatVersion') == 1 and publication.get('repository') == lock['repository'] and
            publication.get('tag') == lock['tag'] and publication.get('targetCommit') == lock['targetCommit'] and
            publication.get('publisherNeverOverwrites') is True and set(publication.get('assets',{})) == set(expected),
            'public-wine-publication-receipt')
    base = 'https://github.com/' + lock['repository'] + '/releases/'
    require(publication.get('url') == base+'tag/'+lock['tag'], 'public-wine-release-url')
    for name,pin in expected.items():
        require(publication['assets'][name] == dict(pin,url=base+'download/'+lock['tag']+'/'+name),
                'public-wine-stored-asset-pin:' + name)
    row = api.json('/releases/tags/' + quote(lock['tag'],safe=''))
    require(row.get('id') == publication.get('releaseId') and row.get('draft') is False and
            row.get('prerelease') is True and row.get('tag_name') == lock['tag'] and
            row.get('body','').replace('\r\n','\n') == release.release_body(lock) and
            row.get('immutable') == publication.get('githubImmutable'), 'public-wine-live-release-mismatch')
    ref = api.json('/git/ref/tags/' + quote(lock['tag'],safe=''))
    require(ref.get('object',{}).get('type') == 'commit' and ref.get('object',{}).get('sha') == lock['targetCommit'],
            'public-wine-tag-target-mismatch')
    rows = row.get('assets',[]); stored = {a['name']:a for a in rows}
    require(len(stored) == len(rows) and set(stored) == set(expected), 'public-wine-live-asset-set')
    for name,pin in expected.items():
        asset = stored[name]
        require(asset.get('state') == 'uploaded' and asset.get('size') == pin['bytes'] and
                asset.get('digest') == 'sha256:'+pin['sha256'] and
                asset.get('browser_download_url') == publication['assets'][name]['url'],
                'public-wine-live-asset-mismatch:' + name)


def fetch(lock_path, receipt_path, output, api=None):
    output = Path(os.path.abspath(output)); require(not os.path.lexists(output), 'public-wine-output-exists')
    archives.directory(output.parent)
    lock = selection(lock_path); publication = release.shared.small_json(receipt_path); expected = expected_assets(lock)
    api = api if api is not None else release.publication.Github()
    public_identity(api,lock,publication,expected)
    stage = Path(tempfile.mkdtemp(prefix='.'+output.name+'.',dir=output.parent))
    try:
        downloaded = stage/'release';downloaded.mkdir(mode=0o700)
        for name,pin in sorted(expected.items()):
            api.download(publication['assets'][name]['url'],downloaded/name,pin)
            require(release.identity(downloaded/name) == pin, 'public-wine-download-readback:' + name)
        release.verify_envelope(downloaded,lock,{k:v for k,v in expected.items() if k in release.PAYLOAD_FILES})
        pin = release.checked_input(release.retained.client.small(downloaded/release.INPUT_LOCK))
        package = stage/'runtime-package';package.mkdir(mode=0o700)
        for name in release.retained.RUNTIME_FILES: os.link(downloaded/name,package/name,follow_symlinks=False)
        release.retained.runtime_package(package,pin)
        os.link(downloaded/release.SOURCE_ZIP,stage/'sources.zip',follow_symlinks=False)
        original = release.retained.extract_sources(stage/'sources.zip',stage/'sources-export',pin)
        source = release.retained.original_sources.verify(original,package/'runtime.json',pin['sourceRevision'])
        require(source.get('allOriginalSourcesReadBack') is True and source.get('completeIntegrationTreeReadBack') is True and
                all(source.get(k) is False for k in ('androidQualified','gameClientQualified','gameplayQualified')) and
                release.bytes_identity((json.dumps(source,indent=2)+'\n').encode()) == pin['sourceReadbackReceipt'],
                'public-wine-full-original-source-readback')
        evidence = dict(formatVersion=1,scope='verified-retained-native-arm64-runtime-and-full-sources-only',
            runtimeInput=pin,sourceReadback=source,inputTransport='public-write-once-prerelease',
            publicRelease=publication,releaseSelection=release.identity(lock_path),
            consumerSource=release.identity(Path(__file__)),historicalProducerRecipeGitBlobsVerified=True,
            originalWholeSourceZipReadBack=True,runtimeRecompiled=False,selectedClientExecuted=False,
            androidQualified=False,gameplayQualified=False)
        (stage/'input-evidence.json').write_bytes(encoded(evidence))
        # The raw six files and original ZIP remain hardlinked above. Keep the
        # small publication records; avoid retaining a second directory alias.
        metadata = stage/'publication';metadata.mkdir()
        for name in ('release-manifest.json','SHA256SUMS','NOTICE.txt',release.INPUT_LOCK):
            shutil.copyfile(downloaded/name,metadata/name)
        (metadata/'published-release.json').write_bytes(encoded(publication))
        (metadata/'dependency-release.lock.json').write_bytes(encoded(lock))
        shutil.rmtree(downloaded)
        release.retained.publish_directory(stage,output);archives.sync_directory(output.parent)
        return evidence
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release-lock',type=Path,required=True)
    parser.add_argument('--publication-receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(fetch(args.release_lock,args.publication_receipt,args.output),indent=2))


if __name__ == '__main__':main()
