#!/usr/bin/env python3
"""Check one APK against all exact public-cohort assets and selected source locks."""
import argparse
import json
from pathlib import Path
import zipfile

try:
    from . import fetch_wine_cohort as consumer
except ImportError:
    import fetch_wine_cohort as consumer

release=consumer.release
require=release.require


def apk_assets(apk,assets,inputs):
    """Validate complete selected APK subtrees; other product providers are separate."""
    expected={'assets/'+name:pin for name,pin in assets.items()}
    expected.update(inputs)
    prefixes={'assets/'+name+'/' for name in release.PROVIDERS}
    with release.client.archives.plain_file(apk) as raw,release.client.checked_zip(raw,expected,
            maximum_bytes=2<<30,maximum_entries=8192) as archive:
        names=set(archive.namelist())
        require({name for name in names if any(name.startswith(prefix) for prefix in prefixes)}==
            {name for name in expected if any(name.startswith(prefix) for prefix in prefixes)},'cohort-apk-provider-subtree-set')
        for name,pin in expected.items():
            item=archive.getinfo(name)
            require(item.file_size==pin['bytes'] and not item.is_dir(),'cohort-apk-member-size:'+name)
            if name.endswith('.archive'):require(item.compress_type==zipfile.ZIP_STORED,'cohort-apk-archive-must-be-stored:'+name)
            with archive.open(item) as incoming:
                require(release.client.archives.hash_stream(incoming,item.file_size)==pin['sha256'],'cohort-apk-member-hash:'+name)
    return dict(assets=len(expected),providerSubtrees=len(prefixes),allExpectedAssetBytesVerified=True)


def verify(apk,directory,lock_path,source):
    lock,source=consumer.selection(lock_path,source)
    expected=consumer.expected_assets(lock)
    for name,pin in expected.items():release.client.verify_identity(directory/name,pin)
    require(consumer.recipe_verify(source,lock_path,directory)==expected,'cohort-apk-complete-source-and-provider-receipt')
    assets=json.loads(release.client.small(directory/'provider-assets-receipt.json'))
    x11=lock['recipeInputs'].get('runtime/wine-arm64-adoption/x11-runtime.lock.json')
    require(x11 is not None,'cohort-apk-selected-x11-closure-not-retained')
    inputs={'assets/sources.lock.json':lock['selectedInputs']['sources.lock.json'],
        'assets/runtime-sources.lock.json':lock['selectedInputs']['runtime/runtime-sources.lock.json'],
        'assets/x11-runtime.lock.json':x11}
    result=apk_assets(apk,assets['members'],inputs)
    return dict(formatVersion=1,scope='coherent-source-owned-wine-cohort-apk-bytes-only',apk=release.identity(apk),
        releaseSelection=release.identity(lock_path),cohortTag=lock['tag'],cohortRecipe=lock['targetCommit'],
        runtimeArchiveSha256=release.measured.RUNTIME,selectedInputs=lock['selectedInputs'],**result,
        allProviderAndCorrespondingSourceBytesReadBack=True,publicPublicationVerifiedHere=False,
        completeWineSourceReadBackHere=False,persistentSigningQualified=False,androidExecutionQualified=False,
        hardwareQualified=False,commonMainQualified=False,assetsQualified=False,gameplayQualified=False)


def complete(args):
    from tools import qualify_server_providers as stock, verify_android_proot as proot
    from tools import package_combined_android as combined
    proof=verify(args.apk,args.cohort_release,args.release_lock,args.packaging_source)
    proof['proot']=proot.verify(args.proot_provider,args.apk)
    proof['prootCorrespondingSources']=combined.proot_sources(args.proot_sources,args.proot_provider)
    proof['serverProviders']=stock.verify_final(args.server_providers,args.dependency_provider,args.apk)
    notices=combined.ndk_notices(args.ndk_archive)
    directories=[args.proot_provider,args.dependency_provider,
        *(args.server_providers/name for name in ('programs','extractors','content'))]
    assets=json.loads(release.client.small(args.cohort_release/'provider-assets-receipt.json'))
    expected={'assets/'+name for name in assets['members']}
    for directory in directories:
        for path in (directory/'assets').rglob('*'):
            if path.is_file():expected.add('assets/'+str(path.relative_to(directory/'assets')))
    expected.update({'assets/'+directory+'/'+name for directory,names in combined.HELPER_SETS.items()
        for name in (*names,'manifest.json')})
    expected.update({'assets/'+name for name in ('sources.lock.json','runtime-sources.lock.json','x11-runtime.lock.json',
        'runtime.properties','notices/ESTERIA-GPL-3.0.txt','notices/FTA-MIT-LICENSE.txt',
        'notices/LLVM-RUNTIME-NOTICE.txt','notices/NDK-28.2.13676358-NOTICE.txt','notices/NDK-SYSROOT-NOTICE.txt')})
    with release.client.archives.plain_file(args.apk) as incoming,zipfile.ZipFile(incoming) as archive:
        names=archive.namelist();require(len(names)==len(set(names)),'coherent-apk-duplicate')
        require({n for n in names if n.startswith('assets/') and not n.endswith('/')}==expected,'coherent-apk-complete-asset-set')
        require({n for n in names if n.startswith('lib/') and not n.endswith('/')}==combined.NATIVE_FILES,'coherent-apk-native-ABI-set')
        combined.verify_helpers(archive);combined.verify_ndk_notices(archive,notices)
        for name in ('sources.lock.json','runtime-sources.lock.json','x11-runtime.lock.json'):
            source=release.ROOT/('sources.lock.json' if name=='sources.lock.json' else
                'runtime/runtime-sources.lock.json' if name=='runtime-sources.lock.json' else 'runtime/bridges/x11-runtime.lock.json')
            require(archive.read('assets/'+name)==release.client.small(source),'coherent-apk-current-source-profile')
        require(archive.read('assets/runtime.properties')==release.client.small(release.ROOT/'app/src/main/assets/runtime.properties'),
            'coherent-apk-current-runtime-properties')
    proof.update(scope='source-and-paired-debug-verified-stock-and-selected-wine-coherent-apk-bytes',
        completeAssetInventoryVerified=True,exactCurrentHelperClosureVerified=True,ndkNotices=notices,
        stockServerProgramsContentAndExtractorsIncluded=True,composedDataToolsIncluded=False,
        debugAndSourceCompanionsKeptOutsideApk=True,serverProgramsExecuted=False,sqlExecuted=False)
    return proof


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('apk','cohort-release','release-lock','packaging-source','output'):parser.add_argument('--'+name,type=Path,required=True)
    for name in ('proot-provider','proot-sources','ndk-archive','server-providers','dependency-provider'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();require(not args.output.exists(),'cohort-apk-evidence-output-exists')
    result=complete(args)
    release.wine.write_new(args.output,release.encoded(result));print(json.dumps(result,indent=2))


if __name__=='__main__':main()
