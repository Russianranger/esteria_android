#!/usr/bin/env python3
"""Reconstruct and compare the isolated Wine provider, then check exact APK bytes."""
import argparse
from pathlib import Path
import tempfile
try:
    from . import build_android_wine_probe as builder, verify_android_proot_probe as proot
except ImportError:
    import build_android_wine_probe as builder, verify_android_proot_probe as proot

require=builder.require
MAX_APK=512*1024**2


def inventory(root):
    result={}
    require(root.is_dir() and not root.is_symlink(),'wine-provider-root')
    for path in root.rglob('*'):
        require(not path.is_symlink(),'wine-provider-symlink')
        if path.is_dir(): continue
        require(path.is_file(),'wine-provider-special-file')
        name=path.relative_to(root).as_posix()
        require(len(result)<256 and name.startswith('assets/wine-probe/'),'wine-provider-inventory')
        result[name]=builder.identity(path)
    return result


def verify(provider,proot_provider,runtime_package,client_artifact,client_source,apk=None):
    proot.verify(proot_provider)
    # Rebuild from independently pinned original inputs. An edited provider.json
    # cannot authorize extra files, changed test scripts or substituted images.
    with tempfile.TemporaryDirectory(prefix='wine-provider-verify-') as temporary:
        recreated=Path(temporary)/'provider'
        proof=builder.build(runtime_package,client_artifact,client_source,recreated)
        expected=inventory(recreated)
        require(inventory(provider)==expected,'wine-provider-differs-from-pinned-inputs')
        if apk is not None:
            require(22<=apk.stat().st_size<=MAX_APK,'wine-probe-apk-size-limit')
            expected.update({path.relative_to(proot_provider).as_posix().replace('jniLibs/','lib/',1):builder.identity(path)
                             for path in proot_provider.rglob('*') if path.is_file()})
            with builder.client.archives.plain_file(apk) as incoming, builder.client.checked_zip(incoming,
                    required=expected,maximum_bytes=MAX_APK,maximum_entries=10000,maximum_directory=4*1024**2) as package:
                names=package.namelist()
                native={name for name in names if name.startswith('lib/') and not name.endswith('/')}
                jni={'lib/x86_64/libesteria_process.so','lib/x86_64/libesteria_probe_process.so'}
                require(native=={'lib/x86_64/'+name for name in proot.builder.NATIVE_PINS}|jni,'wine-probe-native-inventory')
                for name in jni:
                    member=package.getinfo(name);require(64<=member.file_size<=16*1024**2,'wine-probe-jni-size')
                    proot.elf(package.read(member),'owner')
                selected={name for name in names if name.startswith(('assets/wine-probe/','assets/proot-probe/')) and not name.endswith('/')}
                require(selected=={name for name in expected if name.startswith('assets/')},'wine-probe-apk-asset-inventory')
                require(not any(name.startswith(('assets/mysql-probe/','assets/server-runtime/','assets/client-runtime/','assets/guest-bridges/',
                                                'assets/shader-tools/','assets/proot/'))
                                for name in names),'wine-probe-unexpected-runtime-provider')
                for name,pin in expected.items():
                    member=package.getinfo(name);require(member.file_size==pin['bytes'],'wine-probe-apk-member-size')
                    if name=='assets/wine-probe/'+builder.ARCHIVE:require(member.compress_type==0,'wine-probe-runtime-must-be-stored')
                    with package.open(member) as stream:
                        require(builder.client.archives.hash_stream(stream,pin['bytes'])==pin['sha256'],'wine-probe-apk-byte-mismatch')
    return dict(providerVerified=True,apkVerified=apk is not None,scope=builder.SCOPE,
                runtimeArchive=proof['archive'],clientRevision=proof['clientInput']['sourceRevision'],
                androidRuntimeQualified=False,arm64Qualified=False,gameplayQualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('provider','proot-provider','runtime-package','client-artifact','client-source'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--apk',type=Path)
    args=parser.parse_args();print(builder.encoded(verify(args.provider,args.proot_provider,args.runtime_package,
                                                       args.client_artifact,args.client_source,args.apk)).decode(),end='')


if __name__=='__main__':main()
