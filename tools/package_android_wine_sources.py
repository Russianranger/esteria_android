#!/usr/bin/env python3
"""Retain verified full Wine/Debian, client/Xvid, PRoot and integration sources.

This source companion is separate from APK assets. It never executes a guest or
assigns runtime qualification, and refuses existing outputs and extra files.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import runpy
import shutil
import stat
import struct
import subprocess
import tempfile
from urllib.parse import urlsplit
import zipfile

try:
    from . import build_android_wine_probe as wine, provider_client_runtime as client
    from . import build_android_proot_probe as probe, package_combined_android as combined
    from .verify_android_proot_probe import verify as verify_proot
    from .release_server_dependencies import validate_dsc, zip_read, verify_zip_member
except ImportError:
    import build_android_wine_probe as wine, provider_client_runtime as client
    import build_android_proot_probe as probe, package_combined_android as combined
    from verify_android_proot_probe import verify as verify_proot
    from release_server_dependencies import validate_dsc, zip_read, verify_zip_member

ROOT = Path(__file__).resolve().parents[1]
require = client.require
identity = client.identity
MAX_SOURCE_BYTES = 10 * 1024**3


@contextmanager
def source_zip(path):
    """Bound ordinary or ZIP64 central directories before ZipFile allocates."""
    with client.archives.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(22 <= size <= MAX_SOURCE_BYTES, 'wine-source-zip-size-limit')
        stream.seek(max(0, size-65557)); tail = stream.read(65557)
        offset = tail.rfind(b'PK\x05\x06')
        require(offset >= 0 and len(tail)-offset >= 22, 'wine-source-zip-directory-missing')
        disk, first, disk_count, count, length, start, comment = struct.unpack_from('<4H2IH',tail,offset+4)
        end = size-len(tail)+offset
        require(disk == first == 0 and len(tail) == offset+22+comment, 'wine-source-multipart-or-trailing-zip')
        if count == 65535 or length == 0xffffffff or start == 0xffffffff:
            require(end >= 76, 'wine-source-zip64-truncated')
            stream.seek(end-20); locator=stream.read(20)
            require(locator[:4] == b'PK\x06\x07', 'wine-source-zip64-locator')
            locator_disk, position, disks = struct.unpack_from('<IQI',locator,4)
            require(locator_disk == 0 and disks == 1 and position == end-76, 'wine-source-zip64-layout')
            stream.seek(position); record=stream.read(56)
            require(len(record)==56 and record[:4]==b'PK\x06\x06', 'wine-source-zip64-record')
            record_size, _, _, disk, first, disk_count, count, length, start = struct.unpack_from('<Q2H2I4Q',record,4)
            require(record_size==44 and disk==first==0, 'wine-source-zip64-size-or-disks')
            end=position
        require(disk_count==count and 0<count<=4096 and 0<length<=2*1024**2 and start+length==end,
                'wine-source-central-directory-limit')
        with zipfile.ZipFile(stream) as archive:
            members={}; total=0
            require(len(archive.infolist())==count, 'wine-source-zip-entry-count')
            for item in archive.infolist():
                name=item.filename; mode=stat.S_IFMT(item.external_attr>>16)
                require(name not in members and str(PurePosixPath(name))==name and not name.startswith('/') and
                        '\\' not in name and all(part not in ('','.','..') for part in name.split('/')) and
                        0<len(name.encode())<=4096 and all(ord(c)>=32 for c in name) and
                        mode in (0,stat.S_IFREG) and not item.is_dir() and not item.flag_bits&1 and
                        item.compress_type in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED), 'wine-source-zip-entry-type-or-path')
                require(0<item.file_size<=2*1024**3, 'wine-source-member-limit')
                total+=item.file_size; require(total<=MAX_SOURCE_BYTES, 'wine-source-expanded-byte-limit')
                members[name]=item
            yield archive,members


def runtime_sources(path, pin, runtime_raw):
    """Check the source-package union, every descriptor/archive and wrappers."""
    client.verify_identity(path,pin['sourcesArtifact'])
    runtime,_=wine.runtime.metadata(runtime_raw)
    source_lock=wine.runtime.LOCK.read_bytes(); lock=json.loads(source_lock)
    recorder=runpy.run_path(str(ROOT/'runtime/wine-probe/record_runtime.py'))
    with source_zip(path) as (archive,members):
        manifest_raw=zip_read(archive,members['debian/SOURCE-MANIFEST.json'])
        require(dict(bytes=len(manifest_raw),sha256=hashlib.sha256(manifest_raw).hexdigest())==pin['sourceManifest'],
                'wine-source-manifest-pin')
        manifest=json.loads(manifest_raw)
        build_raw=zip_read(archive,members['wine/build-packages.tsv'],131072)
        build=recorder['package_inventory'](build_raw.decode('utf-8'))
        selected=recorder['source_inventory'](build+runtime['packages'])
        require(manifest.get('formatVersion')==1 and
                manifest.get('scope')=='installed-debian-runtime-and-wine-build-corresponding-sources' and
                manifest.get('sourceLockSha256')==hashlib.sha256(source_lock).hexdigest() and
                manifest.get('runtimeManifestSha256')==hashlib.sha256(runtime_raw).hexdigest() and
                manifest.get('sourcePackages')==selected, 'wine-source-package-provenance')
        rows=manifest.get('files',[]); require(0<len(rows)<=2048, 'wine-source-file-count')
        files={row['file']:row for row in rows}
        require(len(files)==len(rows), 'wine-source-duplicate-file')
        for name,row in files.items():
            require(re.fullmatch('[A-Za-z0-9][A-Za-z0-9.+_~:-]*',name) and type(row.get('bytes')) is int and
                    0<row['bytes']<=2*1024**3 and re.fullmatch('[a-f0-9]{64}',row.get('sha256','')) and
                    set(row)=={'file','bytes','sha256'}, 'wine-source-manifest-file')
        require(sum(row['bytes'] for row in rows)==manifest.get('fileBytes')<=8*1024**3,
                'wine-source-manifest-total')
        wrappers={'wine/wine-arm64ec-source.tar.gz','wine/Wine-COPYING.LIB','wine/wine-build-config.log',
                  'wine/build-packages.tsv','wine/runtime.json','debian/runtime.json','debian/sources.lock.json',
                  'debian/SOURCE-MANIFEST.json','integration-source.tar','integration-revision.txt'}
        require(set(members)==wrappers|{'debian/'+name for name in files}, 'wine-source-unexpected-or-missing-member')
        for name,expected in (('wine/runtime.json',runtime_raw),('debian/runtime.json',runtime_raw),
                              ('debian/sources.lock.json',source_lock),
                              ('integration-revision.txt',(pin['sourceRevision']+'\n').encode())):
            require(zip_read(archive,members[name])==expected, 'wine-source-wrapper-content')
        require(re.fullmatch('[a-f0-9]{40}',pin['sourceRevision']), 'wine-source-build-revision')
        verify_zip_member(archive,members['wine/wine-arm64ec-source.tar.gz'],lock['wine']['sourceArchive'])
        license_raw=zip_read(archive,members['wine/Wine-COPYING.LIB'])
        require(hashlib.sha256(license_raw).hexdigest()==lock['wine']['licenseFileSha256'], 'wine-source-license')
        descriptors=set()
        for name,row in files.items():
            verify_zip_member(archive,members['debian/'+name],row)
            if name.endswith('.dsc'):
                pair=validate_dsc(zip_read(archive,members['debian/'+name]),files)
                require(pair not in descriptors, 'wine-source-duplicate-descriptor'); descriptors.add(pair)
        require(descriptors=={(row['package'],row['version']) for row in selected}, 'wine-source-package-closure')
        wrapper_proof={}
        for name in sorted(wrappers):
            limit=32*1024**2 if name=='integration-source.tar' else (64*1024**2 if name.endswith('tar.gz') else 2*1024**2)
            item=members[name];require(item.file_size<=limit,'wine-source-wrapper-size')
            with archive.open(item) as incoming:
                wrapper_proof[name]=dict(bytes=item.file_size,sha256=client.archives.hash_stream(incoming,item.file_size))
    return dict(archive=identity(path),sourcePackages=len(descriptors),debianFileBytes=manifest['fileBytes'],
                originalDebianFiles=len(files),wrappers=wrapper_proof,allFilesReadBack=True)


def proot_sources(path,provider):
    """Verify original archives, tracked recipes and real x64 relinkable objects."""
    verify_proot(provider)
    common=json.loads(probe.proot.LOCK.read_text());glibc=json.loads((probe.INPUTS/'glibc.lock.json').read_text())
    expected={'original-proot/'+name:digest for name,digest in common['components'].items()}
    for item in glibc['packages']+glibc['sources']:
        expected['original-debian/'+urlsplit(item['url']).path.rsplit('/',1)[1]]=item['sha256']
    paths=('native/proot-probe','app/src/prootProbe','app/proot-probe.gradle',
           'app/src/androidTest/java/io/github/russianranger/esteria/runtime/RemoteOwnerDeathProbe.java',
           'tools/build_android_proot_probe.py','tools/verify_android_proot_probe.py','tools/build_android_proot.py',
           'tools/prepare_runtime.py','tools/android_elf.py','runtime/proot','LICENSE')
    names=subprocess.check_output(['git','ls-files','--',*paths],cwd=ROOT,text=True).splitlines()
    for name in names: expected['esteria/'+name]=identity(ROOT/name)['sha256']
    evidence_raw=client.small(provider/'assets/proot-probe/build-evidence.json')
    expected['build-evidence.json']=hashlib.sha256(evidence_raw).hexdigest()
    object_pins=json.loads(evidence_raw).get('tallocRelinkableObjects',{})
    require(type(object_pins) is dict and 0<len(object_pins)<=128 and 'talloc.c.5.o' in object_pins,
            'wine-proot-relink-object-pins-missing')
    limits=dict(entries=4096,memberBytes=128*1024**2,fileBytes=256*1024**2,pathBytes=1024)
    seen=set();files={};objects=[];total=0
    with client.archives.plain_file(path) as incoming,combined.bounded_source_tar(incoming,limits) as archive:
        for item in archive:
            name=item.name
            require(name not in seen and str(PurePosixPath(name))==name and not name.startswith('/') and
                    '\\' not in name and all(part not in ('','.','..') for part in name.split('/')) and
                    len(name.encode())<=1024 and all(ord(c)>=32 for c in name), 'wine-proot-source-path')
            seen.add(name); require(len(seen)<=limits['entries'] and
                    not any(key.startswith('GNU.sparse') for key in item.pax_headers), 'wine-proot-source-count-or-sparse')
            if item.isdir():
                require(any(key.startswith(name+'/') for key in expected) or name=='talloc-relinkable-objects' or
                        name.startswith('talloc-relinkable-objects/'), 'wine-proot-source-extra-directory')
                archive.members.clear(); continue
            obj=name.startswith('talloc-relinkable-objects/') and name.endswith('.o')
            require((name in expected or obj) and item.isfile() and not item.issparse() and
                    0<item.size<=limits['memberBytes'], 'wine-proot-source-type-or-member')
            total+=item.size;require(total<=limits['fileBytes'],'wine-proot-source-byte-limit')
            with archive.extractfile(item) as source:
                header=source.read(min(20,item.size));digest=hashlib.sha256(header);count=len(header)
                while block:=source.read(128*1024):
                    count+=len(block);require(count<=item.size,'wine-proot-source-overflow');digest.update(block)
            require(count==item.size,'wine-proot-source-truncated')
            if obj:
                require(len(header)==20 and header[:6]==b'\x7fELF\x02\x01' and
                        struct.unpack_from('<HH',header,16)==(1,62), 'wine-proot-object-not-x64-relocatable')
                require(object_pins.get(name.removeprefix('talloc-relinkable-objects/'))==dict(bytes=item.size,sha256=digest.hexdigest()),
                        'wine-proot-object-build-identity')
                objects.append(name)
            else:require(digest.hexdigest()==expected[name],'wine-proot-source-hash')
            files[name]=dict(bytes=item.size,sha256=digest.hexdigest());archive.members.clear()
    require(set(expected)<=set(files) and {name.removeprefix('talloc-relinkable-objects/') for name in objects}==set(object_pins),
            'wine-proot-source-or-relink-closure-incomplete')
    return dict(archive=identity(path),files=files,relinkableX64Objects=len(objects),allFilesReadBack=True)


def seal(args):
    require(not os.path.lexists(args.output),'wine-sources-output-exists; existing-files-preserved')
    runtime_pin,client_pin=wine.pins()
    wine.runtime_package(args.runtime_package,runtime_pin)
    runtime_proof=runtime_sources(args.runtime_sources,runtime_pin,client.small(args.runtime_package/'runtime.json',131072))
    proot_proof=proot_sources(args.proot_sources,args.proot_provider)
    require(re.fullmatch('[a-f0-9]{40}',args.revision),'wine-sources-integration-revision')
    for directory,revision in ((ROOT,args.revision),(args.client_source,client_pin['sourceRevision'])):
        client.fetch_sources.verify_checkout(directory,dict(commit=revision,submodules={}),[])
    # The packager itself must be committed in the revision retained below.
    require(client.source_blob(ROOT,args.revision,'tools/package_android_wine_sources.py')==Path(__file__).read_bytes(),
            'wine-sources-uncommitted-packager')
    recipe=client.source_blob(args.client_source,client_pin['sourceRevision'],'cmake/XvidPortable.cmake').decode()
    match=re.search(r'URL_HASH SHA256=([a-f0-9]{64})\s',recipe)
    require(match is not None and re.search(r'URL https://downloads\.xvid\.com/downloads/xvidcore-1\.3\.7\.tar\.gz\s',recipe),
            'wine-client-xvid-source-pin')
    xvid=identity(args.xvid_source);require(0<xvid['bytes']<=16*1024**2 and xvid['sha256']==match.group(1),'wine-client-xvid-original')
    output=Path(os.path.abspath(args.output));client.archives.directory(output.parent,create=True)
    stage=Path(tempfile.mkdtemp(prefix='.wine-sources-',dir=output.parent))
    try:
        for source,name,pin in ((args.runtime_sources,'wine-debian-corresponding-sources.zip',runtime_pin['sourcesArtifact']),
                                (args.proot_sources,'proot-corresponding-source.tar.gz',proot_proof['archive']),
                                (args.xvid_source,'xvidcore-1.3.7.tar.gz',xvid)):
            combined.copy_verified(source,stage/name,pin)
        for source,revision,name in ((ROOT,args.revision,'integration-source.tar.gz'),
                                    (args.client_source,client_pin['sourceRevision'],'client-source.tar.gz')):
            with (stage/name).open('xb') as stream:
                subprocess.run(['git','archive','--format=tar.gz',revision],cwd=source,stdout=stream,check=True,timeout=120)
                stream.flush();os.fsync(stream.fileno())
            require((stage/name).stat().st_size<=256*1024**2,'wine-git-source-size-limit')
        files={path.name:identity(path) for path in sorted(stage.iterdir())}
        receipt=dict(formatVersion=1,scope='retained-android-x64-wine-probe-corresponding-sources',
                     sourceRevision=args.revision,clientRevision=client_pin['sourceRevision'],wineRuntimeInput=runtime_pin,
                     files=files,wineDebianSources=runtime_proof,prootSources=proot_proof,
                     clientGitTreeRetained=True,xvidOriginalRetained=True,
                     androidRuntimeQualified=False,arm64Qualified=False,gameplayQualified=False)
        (stage/'source-receipt.json').write_bytes(client.encoded(receipt))
        client.publish_directory(stage,output);client.archives.sync_directory(output.parent)
        return receipt
    finally:
        if stage.exists():shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-package','runtime-sources','proot-sources','proot-provider','client-source','xvid-source','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--revision',required=True)
    args=parser.parse_args();print(json.dumps(seal(args),indent=2))


if __name__=='__main__':main()
