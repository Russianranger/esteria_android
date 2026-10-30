#!/usr/bin/env python3
"""Read back a public Wine provider cohort using its exact retained recipe checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote

try:
    from . import release_wine_cohort as release
except ImportError:
    import release_wine_cohort as release

require=release.require
encoded=release.encoded


def selection(lock_path,source):
    lock=release.wine.shared.small_json(lock_path)
    require(type(lock) is dict and set(lock)=={'formatVersion','scope','repository','tag','targetCommit','selectedInputs','recipeInputs','files'} and
        type(lock.get('formatVersion')) is int and lock['formatVersion']==1 and lock['scope']==release.SCOPE and
        lock['repository']==release.wine.shared.REPOSITORY and lock['tag']==release.TAG and
        re.fullmatch('[0-9a-f]{40}',lock.get('targetCommit','')) and set(lock['files'])==release.PAYLOAD and
        set(lock['selectedInputs'])==set(release.INPUTS),'public-cohort-separate-selection-schema')
    source=release.client.archives.directory(Path(os.path.abspath(source)))
    environment=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_NO_LAZY_FETCH='1')
    git=['git','-c','safe.directory='+str(source),'-C',str(source)]
    def query(*args):return subprocess.check_output(git+list(args),env=environment,stderr=subprocess.DEVNULL,timeout=30)
    require(query('rev-parse','HEAD').decode().strip()==lock['targetCommit'],'public-cohort-exact-recipe-checkout')
    try:producer=query('cat-file','-t',release.measured.PRODUCER)
    except subprocess.CalledProcessError:
        raise ValueError('public-cohort-original-producer-history-missing-in-frozen-checkout') from None
    require(producer==b'commit\n','public-cohort-original-producer-object-type')
    flags=query('ls-files','-v','-z')
    require(len(flags)<=32<<20 and all(not row or row.startswith(b'H ') for row in flags.split(b'\0')),
        'public-cohort-recipe-hidden-index-flags')
    query('diff-index','--quiet','--cached','HEAD','--');query('diff-files','--quiet','--')
    require(query('ls-files','--others','--exclude-standard','-z')==b'','public-cohort-untracked-recipe-files')
    recipe=lock['recipeInputs'];require(type(recipe) is dict and 1<=len(recipe)<=160 and
        {'tools/release_wine_cohort.py','tools/dependency_publication.py','tools/prepare_runtime.py'}<=recipe.keys(),
        'public-cohort-recipe-roster')
    total=0
    for name,pin in recipe.items():
        require(release.client.archives.member_path(name)==name,'public-cohort-recipe-path')
        size=int(query('cat-file','-s',lock['targetCommit']+':'+name));total+=size
        require(0<size<=2<<20 and total<=24<<20,'public-cohort-recipe-byte-bound')
        raw=query('cat-file','blob',lock['targetCommit']+':'+name)
        require(len(raw)==size and release.wine.bytes_identity(raw)==pin and release.identity(source/name)==pin,
            'public-cohort-retained-recipe-git-blob:'+name)
    return lock,source


def expected_assets(lock):
    files=dict(lock['files'])
    manifest=dict(formatVersion=1,scope=release.SCOPE,targetCommit=lock['targetCommit'],tag=release.TAG,
        selectedInputs=lock['selectedInputs'],assets=lock['files'])
    files['release-manifest.json']=release.wine.bytes_identity(encoded(manifest))
    sums=''.join(pin['sha256']+'  '+name+'\n' for name,pin in sorted(files.items()))
    files['SHA256SUMS']=release.wine.bytes_identity(sums.encode())
    require(set(files)==release.ALL_FILES,'public-cohort-asset-roster')
    return files


def public_identity(api,lock,publication,expected):
    require(type(publication.get('formatVersion')) is int and publication['formatVersion']==1 and
        publication.get('repository')==lock['repository'] and publication.get('tag')==lock['tag'] and
        publication.get('targetCommit')==lock['targetCommit'] and publication.get('publisherNeverOverwrites') is True and
        set(publication.get('assets',{}))==set(expected),'public-cohort-publication-receipt')
    base='https://github.com/'+lock['repository']+'/releases/'
    require(publication.get('url')==base+'tag/'+lock['tag'],'public-cohort-release-url')
    for name,pin in expected.items():require(publication['assets'][name]==dict(pin,url=base+'download/'+lock['tag']+'/'+name),
        'public-cohort-stored-asset-pin:'+name)
    row=api.json('/releases/tags/'+quote(lock['tag'],safe=''))
    require(row.get('id')==publication.get('releaseId') and row.get('draft') is False and row.get('prerelease') is True and
        row.get('tag_name')==lock['tag'] and row.get('body','').replace('\r\n','\n')==release.body(lock) and
        row.get('immutable')==publication.get('githubImmutable'),'public-cohort-live-release')
    ref=api.json('/git/ref/tags/'+quote(lock['tag'],safe=''))
    require(ref.get('object',{}).get('type')=='commit' and ref['object'].get('sha')==lock['targetCommit'],'public-cohort-exact-tag-target')
    rows=row.get('assets',[]);stored={x['name']:x for x in rows}
    require(len(rows)==len(stored) and set(stored)==set(expected),'public-cohort-live-asset-roster')
    for name,pin in expected.items():
        item=stored[name]
        require(item.get('state')=='uploaded' and item.get('size')==pin['bytes'] and item.get('digest')=='sha256:'+pin['sha256'] and
            item.get('browser_download_url')==publication['assets'][name]['url'],'public-cohort-live-asset:'+name)


def recipe_verify(source,lock_path,directory):
    # Imports execute only after every pinned recipe file and Git blob matched.
    environment=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',GIT_OPTIONAL_LOCKS='0',GIT_NO_LAZY_FETCH='1')
    for name in ('PYTHONPATH','GITHUB_TOKEN'):environment.pop(name,None)
    with tempfile.TemporaryDirectory(prefix='.cohort-python-cache-',dir=directory.parent) as cache:
        result=subprocess.run([sys.executable,'-B','-X','pycache_prefix='+cache,str(source/'tools/release_wine_cohort.py'),'verify',
            '--release-lock',str(lock_path.resolve()),'--inputs',str(directory.resolve())],cwd=source,env=environment,
            stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=1800)
    require(result.returncode==0 and len(result.stdout)<=1<<20 and len(result.stderr)<=1<<20,
        'public-cohort-exact-recipe-source-and-provider-readback')
    return json.loads(result.stdout)


def restore(directory,output):
    release.fresh(output)
    assets=json.loads(release.client.small(directory/'provider-assets-receipt.json'))
    with tempfile.TemporaryDirectory(prefix='.restore-cohort-',dir=output.parent) as tmp:
        tree=Path(tmp);release.read_archive(directory/'provider-assets.tar.gz',assets['members'],tree)
        for name,(provider,_) in release.PROVIDERS.items():
            target=output/provider/'assets';target.mkdir(parents=True);shutil.move(tree/name,target/name)
            if name=='turnip':
                sources=output/provider/'sources';sources.mkdir()
                release.retain(directory/'turnip-source-complete.zip',sources/release.turnip.SOURCE)
                release.copy(directory/'turnip-source-receipt.json',sources/'source-receipt.json')
    return {name:release.identity(output/provider/'assets'/name/'provider.json') for name,(provider,_) in release.PROVIDERS.items()}


def fetch(lock_path,receipt_path,source,output,providers=None,api=None):
    output=Path(os.path.abspath(output));require(not os.path.lexists(output) and
        (providers is None or not os.path.lexists(providers)),'public-cohort-existing-output-preserved')
    lock,source=selection(lock_path,source);expected=expected_assets(lock)
    publication=release.wine.shared.small_json(receipt_path)
    api=api if api is not None else release.PUBLICATION.Github() # public read, no application token
    public_identity(api,lock,publication,expected)
    release.client.archives.directory(output.parent,create=True)
    stage=Path(tempfile.mkdtemp(prefix='.public-cohort-',dir=output.parent))
    try:
        package=stage/'release';package.mkdir()
        for name,pin in sorted(expected.items()):
            api.download(publication['assets'][name]['url'],package/name,pin)
            release.client.verify_identity(package/name,pin)
        readback=recipe_verify(source,lock_path,package)
        require(readback==expected,'public-cohort-recipe-result-inventory')
        proof=dict(formatVersion=1,scope='public-selected471-wine-cohort-source-and-provider-readback',
            release=publication,selection=release.identity(lock_path),recipeGitAndWorkingFilesVerified=True,
            entireProviderAndSourceAssetsReadBack=True,providerSourcesComplete=True,
            completeWineSourceReadBackHere=False,wineSourceReleaseSeparatelyPinned=True,
            restoredProviders=providers is not None,binariesRecompiled=False,binariesExecuted=False,
            androidQualified=False,hardwareQualified=False,gameplayQualified=False)
        if providers is not None:proof['providerDescriptors']=restore(package,Path(os.path.abspath(providers)))
        (stage/'consumer.json').write_bytes(encoded(proof));release.copy(lock_path,stage/'dependency-release.lock.json')
        release.copy(receipt_path,stage/'published-release.json')
        release.client.publish_directory(stage,output)
        return proof
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('release-lock','publication-receipt','packaging-source','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--providers',type=Path);args=parser.parse_args()
    print(json.dumps(fetch(args.release_lock,args.publication_receipt,args.packaging_source,args.output,args.providers),indent=2))


if __name__=='__main__':main()
