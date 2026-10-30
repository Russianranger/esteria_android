#!/usr/bin/env python3
"""Acquire measured source/build inputs and enforce the original native toolchain.

No server source repository or asset tree is fetched. Relevant compiler and ABI
inputs must match; differences in unrelated runner packages remain evidence.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys

if not __package__: sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import prepare_runtime as archives, prepare_server_requalification as reference
from tools import provider_client_runtime as client, verify_server_build as files

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/server/isolated-build.lock.json'
require = files.require


def canonical_hash(value):
    # Match the original server cache-environment producer exactly.
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def load_pin():
    pin, _ = reference.modules.read_json(LOCK)
    require(pin.get('formatVersion') == 1 and pin.get('scope') == 'measured-seven-patch-isolated-source-rebuild-inputs' and
            pin.get('minimumFreeBytes') == 16 * 1024**3 and
            files.identity(ROOT/'sources.lock.json')['sha256'] == pin.get('sourceLockSha256'),
            'isolated-build-input-selection-mismatch')
    for field in ('sourceInputs', 'originalBuildEnvironment'):
        row = pin[field]; item = row['artifact']
        require(type(row['workflowRun']) is int and re.fullmatch('[0-9a-f]{40}', row['integrationRevision']) and
                type(item['id']) is int and type(item['bytes']) is int and 22 <= item['bytes'] <= 64 * 1024**2 and
                re.fullmatch('[0-9a-f]{64}', item['sha256']), 'isolated-build-artifact-pin')
    packages = pin['originalBuildEnvironment']['directPackages']
    require(len(packages) == 10 and len(set(packages)) == 10 and
            all(re.fullmatch('[a-z0-9][a-z0-9+.-]*=[A-Za-z0-9+:.~_-]+', row) for row in packages),
            'isolated-build-package-selection')
    relevant = pin['originalBuildEnvironment'].get('relevantPackages')
    require(isinstance(relevant,dict) and 50 <= len(relevant) <= 128 and
            relevant.get('libstdc++-13-dev:arm64') and relevant.get('libmysqlclient-dev') and
            relevant.get('binutils') and 'nodejs' not in relevant and 'ccache' not in relevant,
            'isolated-relevant-build-package-selection')
    return pin


def copy_member(archive, members, name, target, expected):
    selected = reference.unique_member(members, name)
    require(members[selected].file_size == expected['bytes'], 'isolated-input-member-size')
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with archive.open(selected) as source, target.open('xb') as output:
        require(archives.hash_stream(source, expected['bytes'], output) == expected['sha256'],
                'isolated-input-member-hash')
        output.flush(); os.fsync(output.fileno())
    target.chmod(0o444)


def acquire(output, api=None):
    pin = load_pin(); output = Path(os.path.abspath(output)); archives.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'existing-isolated-inputs-preserved')
    require(shutil.disk_usage(output.parent).free >= pin['minimumFreeBytes'], 'isolated-build-requires-16-GiB-free')
    api = api or reference.Github(os.environ.get('GITHUB_TOKEN'))
    output.mkdir(mode=0o700)
    for field in ('sourceInputs', 'originalBuildEnvironment'):
        row = pin[field]; expected = row['artifact']
        actual = api.json('/actions/artifacts/' + str(expected['id']))
        require(actual.get('id') == expected['id'] and actual.get('expired') is False and
                actual.get('size_in_bytes') == expected['bytes'] and actual.get('digest') == 'sha256:' + expected['sha256'] and
                actual.get('workflow_run', {}).get('id') == row['workflowRun'] and
                actual.get('workflow_run', {}).get('head_sha') == row['integrationRevision'],
                'isolated-build-remote-artifact-mismatch')
        target = output/(field+'.zip')
        api.download(reference.API+'/actions/artifacts/'+str(expected['id'])+'/zip', target, expected)
        require(files.identity(target) == {key:expected[key] for key in ('bytes','sha256')},
                'isolated-build-downloaded-artifact-mismatch')
        with reference.bounded_zip(target) as (archive,members):
            if field == 'sourceInputs':
                require(set(members) == {row['archive']['file'], row['receipt']['file']}, 'isolated-source-artifact-members')
                for key in ('archive','receipt'):
                    copy_member(archive,members,row[key]['file'],output/'source-inputs'/row[key]['file'],row[key])
            else:
                for name, identity in row['files'].items():
                    copy_member(archive,members,name,output/'environment'/name,identity)
        target.unlink()
    expected = json.loads((output/'environment/cache-environment.json').read_text())
    require(canonical_hash(expected) == pin['originalBuildEnvironment']['canonicalEnvironmentSha256'] and
            expected['compiler_sha256'] == pin['originalBuildEnvironment']['compilerSha256'],
            'original-build-environment-fingerprint-mismatch')
    receipt = dict(formatVersion=1,scope='isolated-source-build-inputs-acquired',
        inputLock=files.identity(LOCK),sourceArtifact=pin['sourceInputs']['artifact'],
        originalEnvironmentArtifact=pin['originalBuildEnvironment']['artifact'],
        originalEnvironmentFingerprint=canonical_hash(expected), sourceRepositoryFetched=False,
        assetTreesFetched=False,sourceCompanionComplete=False,isolatedSourceRebuildQualified=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    reference.write_new(output/'acquisition.json',reference.encoded(receipt))
    return receipt


def observed_environment():
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'native-arm64-build-environment-required')
    def executable(name):
        path = shutil.which(name); require(path is not None,'build-tool-missing:'+name)
        return Path(path).resolve(strict=True)
    compiler = executable('g++')
    def command(name,*arguments):
        return files.bounded_command([str(executable(name)),*arguments],timeout=30,limit=2*1024**2)
    return dict(platform=platform.machine(),os=Path('/etc/os-release').read_text(),
        packages=command('dpkg-query','-W'),compiler_sha256=files.identity(compiler)['sha256'],
        compiler_version=command('g++','--version'),compiler_target=command('g++','-dumpmachine'),
        cmake_version=command('cmake','--version'),
        ccache_version=command('ccache','--version') if shutil.which('ccache') else '<absent; cache disabled>')


def package_versions(text):
    rows={}
    for line in text.splitlines():
        parts=line.split('\t');require(len(parts)==2 and parts[0] not in rows,'build-package-list-contract')
        rows[parts[0]]=parts[1]
    return rows


def os_family(text):
    fields={}
    for line in text.splitlines():
        if '=' in line:
            key,value=line.split('=',1);fields[key]=value.strip('"')
    return {key:fields.get(key) for key in ('ID','VERSION_ID','VERSION_CODENAME')}


def observed_binary_inputs(inputs):
    """These current identities are evidence; unknown original hashes are never invented."""
    paths=set()
    for name in ('g++','gcc','ld','ninja','cmake'):
        if shutil.which(name):paths.add(Path(shutil.which(name)).resolve())
    cache=inputs/'environment/CMakeCache.txt'
    for line in cache.read_text().splitlines():
        if re.match(r'(Boost_.*LIBRARY_RELEASE|MYSQL_LIBRARY|OPENSSL_(CRYPTO|SSL)_LIBRARY|READLINE_LIBRARY|ZLIB_LIBRARY_RELEASE):',line):
            value=line.split('=',1)[1]
            if value.startswith('/usr/') and Path(value).is_file():paths.add(Path(value).resolve())
    return {str(path):files.identity(path) for path in sorted(paths)}


def verify_environment(inputs, output, observed=None):
    pin = load_pin(); expected_path = inputs/'environment/cache-environment.json'
    require(files.identity(expected_path) == pin['originalBuildEnvironment']['files']['cache-environment.json'],
            'original-build-environment-bytes-changed')
    expected = json.loads(expected_path.read_text()); actual = observed if observed is not None else observed_environment()
    mismatch = sorted(key for key in set(expected)|set(actual) if expected.get(key) != actual.get(key))
    fatal=[key for key in ('platform','compiler_sha256','compiler_version','compiler_target','cmake_version')
           if expected.get(key)!=actual.get(key)]
    if os_family(expected.get('os',''))!=os_family(actual.get('os','')):fatal.append('os-family')
    versions=package_versions(actual['packages']); original_versions=package_versions(expected['packages'])
    relevant=pin['originalBuildEnvironment']['relevantPackages']
    require(all(original_versions.get(name)==value for name,value in relevant.items()),
            'relevant-package-pins-differ-from-original-metadata')
    package_mismatch=sorted(name for name,value in relevant.items() if versions.get(name)!=value)
    fatal += ['package:'+name for name in package_mismatch]
    receipt = dict(formatVersion=1,scope='measured-original-relevant-native-build-environment-comparison',
        expectedEnvironmentFingerprint=canonical_hash(expected),observedEnvironmentFingerprint=canonical_hash(actual),
        mismatchFields=mismatch,exactEnvironmentMatched=not mismatch,
        relevantMismatchFields=fatal,relevantBuildEnvironmentMatched=not fatal,
        relevantPackageVersions=relevant,compilerCacheDisabled=True,
        observedBinaryInputs=observed_binary_inputs(inputs) if observed is None else {},
        observedBinaryInputsComparedToUnknownOriginalHashes=False,
        sourceCompanionComplete=False,isolatedSourceRebuildQualified=False,
        androidRuntimeQualified=False,gameplayQualified=False)
    require(not os.path.lexists(output), 'existing-build-environment-receipt-preserved')
    reference.write_new(output,reference.encoded(receipt))
    require(not fatal,'relevant-build-environment-differs:'+','.join(fatal))
    return receipt


def protocol_inputs(output):
    """Only actual generated layout metadata is extracted; client PEs never execute."""
    lock = json.loads((ROOT/'runtime/client/dependency-release.lock.json').read_text())
    pin = json.loads(client.small(client.PIN))
    require(pin.get('formatVersion')==1 and pin.get('scope')=='measured-reconstructed-client-provider-inputs',
            'isolated-protocol-client-pin-contract')
    require(lock['sourceRevision'] == pin['sourceRevision'] and
            pin['sourceRevision'] == json.loads((ROOT/'sources.lock.json').read_text())['sources']['client']['commit'],
            'isolated-protocol-client-source-mismatch')
    row = lock['published']['assets']['reconstructed-client-arm64-original.zip']
    require({key:row[key] for key in ('bytes','sha256')} == pin['artifact'],'isolated-protocol-client-artifact-mismatch')
    archives.directory(output,create=True)
    original = archives.fetch(dict(row,file='reconstructed-client-arm64-original.zip'),output)
    with archives.plain_file(original) as source,client.checked_zip(source) as archive:
        for name,target in (('bin/Win/ARM64/client-build.json','client-build.json'),
                            ('build/client/generated/limits/limits.json','limits.json')):
            item=archive.getinfo(name);require(item.file_size<=1024**2,'client-protocol-metadata-bound')
            raw=archive.read(item)
            if target=='client-build.json':require(hashlib.sha256(raw).hexdigest()==pin['buildManifestSha256'],
                                                  'client-protocol-build-manifest-changed')
            reference.write_new(output/target,raw)
    return dict(clientSourceRevision=pin['sourceRevision'],originalArtifact=pin['artifact'],
                limits=files.identity(output/'limits.json'),clientExecuted=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='operation',required=True)
    p=sub.add_parser('acquire');p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('packages')
    p=sub.add_parser('environment');p.add_argument('--inputs',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('protocol');p.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.operation=='packages':print('\n'.join(load_pin()['originalBuildEnvironment']['directPackages']));return
    if args.operation=='acquire':result=acquire(args.output)
    elif args.operation=='environment':result=verify_environment(args.inputs,args.output)
    else:result=protocol_inputs(args.output)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
