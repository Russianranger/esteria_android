#!/usr/bin/env python3
"""Build a separate Android x64 Wine/client diagnostic provider from measured inputs."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import types
try:
    from . import package_android_wine_runtime as runtime, provider_client_runtime as client
except ImportError:
    import package_android_wine_runtime as runtime, provider_client_runtime as client

ROOT = Path(__file__).resolve().parents[1]
CLIENT_LOCK = ROOT / 'runtime/wine-probe/client-input.lock.json'
RUNTIME_LOCK = ROOT / 'runtime/wine-probe/runtime-input.lock.json'
ASSET = 'wine-probe'
ARCHIVE = 'wine-x86-64.archive'
SCOPE = 'android-x86-64-wine-client-probe-build-only'
CLIENT_FILES = {'bin/Win/WowClient64.exe': 'client/WowClient64.exe',
                'bin/Win/XvidDecoder.dll': 'client/XvidDecoder.dll',
                'bin/Win/client-build.json': 'client/client-build.json',
                'build/client/generated/limits/limits.json': 'client/limits.json'}
VALIDATORS = ('verify_client_entry.py', 'verify_client_offline.py', 'verify_client_loopback.py')
INPUTS = ('runtime/wine-probe/guest_check.py', 'app/wine-probe.gradle',
          'app/src/wineProbeAndroidTest/java/io/github/russianranger/esteria/runtime/WineExecutionTest.java',
          'tools/build_android_wine_probe.py', 'tools/verify_android_wine_probe.py', 'tools/qualify_android_wine.py',
          'tools/package_android_wine_sources.py', 'tools/fetch_android_wine_probe.py')
NOTICE = b'''Emulator-only x86_64 Debian/Wine/reconstructed-client diagnostics.
The executable is rebuilt from the pinned Esteria source, never stock Wow.exe.
Wine is LGPL2.1-or-later; installed Debian copyright notices remain in the rootfs.
Client original notices retain their terms; no top-level client license is assigned.
Complete Wine/Debian runtime+build sources, client Git/Xvid sources and integration
recipe must accompany redistribution. No game data, accounts or existing prefix.
This package establishes no Android, ARM64, rendering, audio or gameplay pass.
'''
require = client.require
identity = client.identity
encoded = client.encoded


def pins():
    runtime_pin = json.loads(client.small(RUNTIME_LOCK)); client_pin = json.loads(client.small(CLIENT_LOCK))
    require(runtime_pin.get('formatVersion') == 1 and runtime_pin.get('scope') == 'measured-x86-64-wine-runtime-inputs' and
            runtime_pin.get('sourceBuildPassed') is True, 'wine-probe-runtime-pin')
    require(client_pin.get('formatVersion') == 1 and client_pin.get('scope') == 'measured-reconstructed-x64-diagnostic-inputs' and
            client_pin.get('windowsEntryOfflineLoopbackPassed') is True and
            re.fullmatch('[a-f0-9]{40}', client_pin.get('sourceRevision', '')), 'wine-probe-client-pin')
    return runtime_pin, client_pin


def copy_verified(source, target, pin):
    target.parent.mkdir(parents=True, exist_ok=True)
    with client.archives.plain_file(source) as incoming, target.open('xb') as outgoing:
        require(os.fstat(incoming.fileno()).st_size == pin['bytes'] and
                client.archives.hash_stream(incoming, pin['bytes'], outgoing) == pin['sha256'], 'wine-probe-copy-mismatch')


def runtime_package(package, pin):
    require(set(pin['files']) == {'wine-x86-64.tar.gz','package-receipt.json','runtime.json','sources.lock.json'}, 'wine-runtime-file-set')
    require({path.name for path in package.iterdir()} == set(pin['files']), 'wine-runtime-package-inventory')
    for name, expected in pin['files'].items(): client.verify_identity(package / name, expected)
    raw = client.small(package / 'runtime.json', 131072); value, components = runtime.metadata(raw)
    proof = json.loads(client.small(package / 'package-receipt.json'))
    require(proof.get('formatVersion') == 1 and proof.get('scope') == 'packaged-linux-x86-64-wine-probe-build-only' and
            proof.get('archiveReadBack') is True and proof.get('sourceCompanionRequired') is True, 'wine-runtime-package-scope')
    for flag in ('clientIncluded','androidRuntimeQualified','arm64Qualified','gameplayQualified'):
        require(proof.get(flag) is False, 'wine-runtime-package-overclaim')
    require(proof.get('archive') == dict(file='wine-x86-64.tar.gz', **pin['files']['wine-x86-64.tar.gz']) and
            proof.get('sourceLockSha256') == identity(runtime.LOCK)['sha256'] and
            proof.get('runtimeMetadataSha256') == hashlib.sha256(raw).hexdigest(), 'wine-runtime-package-identity')
    require(client.small(package / 'sources.lock.json') == runtime.LOCK.read_bytes(), 'wine-runtime-source-lock')
    require(all(proof['requiredFiles'].get(name) == expected for name, expected in components.items()), 'wine-runtime-required-files')
    return proof, value


def client_payload(artifact, source, assets, pin):
    client.fetch_sources.verify_checkout(source, dict(commit=pin['sourceRevision'], submodules={}), [])
    client.verify_identity(artifact, pin['artifact'])
    with client.archives.plain_file(artifact) as incoming, client.checked_zip(incoming, required=CLIENT_FILES) as archive:
        for original, destination in CLIENT_FILES.items():
            info = archive.getinfo(original)
            require(0 < info.file_size <= (64*1024**2 if destination.endswith(('.exe','.dll')) else client.META_LIMIT), 'wine-client-member-size')
            target = assets / destination; target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as stream, target.open('xb') as outgoing:
                client.archives.hash_stream(stream, info.file_size, outgoing)
    manifest_raw = client.small(assets / 'client/client-build.json')
    require(hashlib.sha256(manifest_raw).hexdigest() == pin['buildManifestSha256'], 'wine-client-manifest-pin')
    parser = types.ModuleType('pinned_x64_client_manifest')
    exec(compile(client.source_blob(source,pin['sourceRevision'],'Tools/RuntimeManifest/generate.py'),
                 'pinned-client/Tools/RuntimeManifest/generate.py','exec'),parser.__dict__)
    images = [parser.inspect_file(assets/'client'/name,'x64',name.endswith('.dll')) for name in client.BINARIES]
    expected = dict(schema_version=1,component='esteria-reconstructed-client',evidence='build-only',architecture='x64',
                    source_revision=pin['sourceRevision'],build_id=pin['buildId'],protocol=dict(parser.PROTOCOL),
                    descriptor_manifest=parser.descriptor_info(assets/'client/limits.json'),files=images)
    selected_capabilities=client.capabilities(parser)
    if selected_capabilities is not None:expected['capabilities']=selected_capabilities
    require(client.encoded(json.loads(manifest_raw)) == client.encoded(expected), 'wine-client-manifest-actual-images')
    for name in client.BINARIES: client.no_delay_imports(assets/'client'/name)
    for name in VALIDATORS:
        target=assets/'helpers'/name; target.parent.mkdir(exist_ok=True)
        target.write_bytes(client.source_blob(source,pin['sourceRevision'],'Tools/PlatformTests/'+name))
    tracked=client.fetch_sources.run('git','ls-tree','-r','--name-only',pin['sourceRevision'],cwd=source).splitlines()
    notices=[name for name in tracked if re.fullmatch(r'(?:license|copying|notice|copyright)(?:[._-].*)?',PurePosixPath(name).name,re.I)]
    notices += ['ThirdParty/zlib/README','ThirdParty/freetype/docs/FTL.txt','ThirdParty/freetype/docs/GPL.txt',
                'ThirdParty/freetype/src/autohint/CatharonLicense.txt']
    require(len(set(notices)) <= 128, 'wine-client-notice-count')
    for name in sorted(set(notices)):
        target=assets/'notices'/name; target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(client.source_blob(source,pin['sourceRevision'],name))
    return expected


def build(package, artifact, source, output):
    runtime_pin, client_pin=pins(); runtime_proof, runtime_value=runtime_package(package,runtime_pin)
    output=Path(os.path.abspath(output)); client.archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'wine-probe-output-exists')
    stage=Path(tempfile.mkdtemp(prefix='.'+output.name+'.stage-',dir=output.parent))
    try:
        assets=stage/'assets'/ASSET; assets.mkdir(parents=True)
        copy_verified(package/'wine-x86-64.tar.gz',assets/ARCHIVE,runtime_pin['files']['wine-x86-64.tar.gz'])
        manifest=client_payload(artifact,source,assets,client_pin)
        (assets/'helpers/guest_check.py').write_bytes((ROOT/'runtime/wine-probe/guest_check.py').read_bytes())
        for name,data in {'runtime.json':(package/'runtime.json').read_bytes(),'runtime-package.json':(package/'package-receipt.json').read_bytes(),
                          'runtime-input.lock.json':RUNTIME_LOCK.read_bytes(),'client-input.lock.json':CLIENT_LOCK.read_bytes(),
                          'sources.lock.json':runtime.LOCK.read_bytes(),'NOTICE.txt':NOTICE}.items(): (assets/name).write_bytes(data)
        files={path.relative_to(assets).as_posix():identity(path) for path in sorted(assets.rglob('*')) if path.is_file()}
        require(len(files)<=256,'wine-probe-file-count')
        proof=dict(formatVersion=1,scope=SCOPE,architecture='x86_64',packageKey='wine-probe-x86-64',
                   runtimeInput=runtime_pin,clientInput=client_pin,clientBuildManifest=manifest,
                   archive={**runtime_proof['archive'],'assetPath':ASSET+'/'+ARCHIVE},
                   **{key:runtime_proof[key] for key in ('requiredFiles','archiveEntries','archiveFileBytes','limits','maximumPhysicalFileBytes')},
                   wineVersion=runtime_value['wineVersion'],files=files,sourceInputs={name:identity(ROOT/name) for name in INPUTS},
                   sourceCompanionRequired=True,androidRuntimeQualified=False,arm64Qualified=False,gameplayQualified=False)
        raw=encoded(proof); require(len(raw)<=65536,'wine-probe-proof-size')
        (assets/'provider.json').write_bytes(raw)
        client.archives.sync_directory(assets); client.publish_directory(stage,output); client.archives.sync_directory(output.parent)
        return proof
    finally:
        if stage.exists(): shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-package','client-artifact','client-source','output'): parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(); print(json.dumps(build(args.runtime_package,args.client_artifact,args.client_source,args.output),indent=2))


if __name__=='__main__': main()
