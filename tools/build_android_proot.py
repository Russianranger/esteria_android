#!/usr/bin/env python3
"""Build a pinned Bionic ARM64 PRoot/loader provider in a new directory.

Adapted from Russianranger/fta-launcher tools/build_client_bridge.py and its source-pinned
UO recipe; see runtime/proot/FTA-MIT-LICENSE.txt and runtime/proot/README.md.
Acquisition is explicit. Build inputs and output identities are recorded; the
built Android executables are never run by this host tool.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import subprocess
import tarfile
import zipfile

try:
    from . import android_elf, prepare_runtime as packages
except ImportError:
    import android_elf
    import prepare_runtime as packages

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'runtime/proot/sources.lock.json'


def digest(path):
    with packages.plain_file(path) as stream:
        return packages.hash_stream(stream, os.fstat(stream.fileno()).st_size)


def replace_exact(text, old, new, count=1):
    packages.require(text.count(old) == count, 'pinned-build-recipe-differs')
    return text.replace(old, new)


def safe_name(name):
    path = PurePosixPath(name)
    packages.require(name and not path.is_absolute() and '..' not in path.parts and
                     '\\' not in name and '\0' not in name, 'unsafe-archive-path')
    return path


def recover_sources(bundle, directory, components):
    selected = set()
    with packages.plain_file(bundle) as stream, tarfile.open(fileobj=stream, mode='r|gz') as archive:
        for item in archive:
            name = item.name.removeprefix('launcher-source/')
            if name not in components:
                continue
            packages.require(name not in selected and item.isfile() and 0 < item.size <= 1024 * 1024,
                             'invalid-source-component')
            data = archive.extractfile(item).read(item.size + 1)
            packages.require(len(data) == item.size and hashlib.sha256(data).hexdigest() == components[name],
                             'source-component-identity-mismatch')
            target = directory / safe_name(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(data)
            selected.add(name)
    packages.require(selected == set(components), 'missing-source-components')


def extract_ndk(archive, destination):
    # Extract only the Linux toolchain and its notices; preserve contained compiler
    # symlinks. The complete downloaded archive is already exact-hash verified.
    prefix = 'android-ndk-r28c/'
    with zipfile.ZipFile(archive) as source:
        packages.require(len(source.infolist()) < 100000, 'ndk-inventory-limit')
        selected = set()
        total = 0
        for entry in source.infolist():
            if not (entry.filename.startswith(prefix + 'toolchains/llvm/prebuilt/linux-x86_64/') or
                    entry.filename in (prefix + 'source.properties', prefix + 'NOTICE',
                                       prefix + 'meta/abis.json', prefix + 'meta/platforms.json')):
                continue
            name = safe_name(entry.filename)
            packages.require(str(name) not in selected, 'duplicate-ndk-member')
            selected.add(str(name))
            total += entry.file_size
            packages.require(total <= 6 * 1024**3 and entry.file_size <= 512 * 1024**2, 'ndk-size-limit')
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = entry.external_attr >> 16
            if entry.is_dir():
                target.mkdir(exist_ok=True)
            elif stat.S_ISLNK(mode):
                packages.require(entry.file_size <= 4096, 'ndk-link-limit')
                link = source.read(entry).decode()
                packages.require(not Path(link).is_absolute() and
                    (target.parent / link).resolve().is_relative_to(destination / prefix), 'escaping-ndk-link')
                target.symlink_to(link)
            else:
                packages.require(not mode or stat.S_ISREG(mode), 'ndk-special-file')
                with source.open(entry) as incoming, target.open('xb') as output:
                    shutil.copyfileobj(incoming, output, packages.BUFFER)
                target.chmod(mode & 0o777)
    return destination / prefix


def license_text(archive, name):
    with tarfile.open(archive) as source:
        matches = [item for item in source if item.isfile() and item.name == name]
        packages.require(len(matches) == 1 and 0 < matches[0].size <= 128 * 1024, 'component-license-missing')
        return source.extractfile(matches[0]).read()


def identity(path, *, loader=False):
    with packages.plain_file(path) as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), elf=android_elf.inspect(data, loader=loader))


def build(source_archive, ndk_archive, work):
    pin = json.loads(LOCK.read_text())
    packages.require(pin['schema'] == 1 and pin['target'] == dict(abi='arm64-v8a', api=26, minimumLoadAlignment=16384),
                     'unsupported-proot-lock')
    source_archive, ndk_archive = source_archive.absolute(), ndk_archive.absolute()
    for path, component in ((source_archive, 'source'), (ndk_archive, 'ndk')):
        with packages.plain_file(path) as stream:
            packages.verify_stream(stream, pin[component])
    patch = ROOT / pin['ownershipPatch']['path']
    packages.require(digest(patch) == pin['ownershipPatch']['sha256'], 'ownership-patch-differs')
    work = Path(os.path.abspath(work))
    packages.directory(work.parent, create=True)
    packages.require(not work.is_relative_to(ROOT) and not os.path.lexists(work), 'use-new-work-directory-outside-repository')
    # One native compiler job and a minimum free-memory threshold avoid competing
    # with the much larger server build. MemAvailable is the usable host estimate.
    info = dict(re.findall(r'^(\w+):\s+(\d+) kB$', Path('/proc/meminfo').read_text(), re.M))
    packages.require(int(info.get('MemAvailable', 0)) >= 512 * 1024, 'insufficient-available-build-memory')
    packages.require(shutil.disk_usage(work.parent).free >= 6 * 1024**3, 'insufficient-build-disk')
    work.mkdir(mode=0o700)
    original = work / 'original'; original.mkdir()
    recover_sources(source_archive, original, pin['components'])
    ndk = extract_ndk(ndk_archive, work / 'toolchain')
    packages.require(re.search(r'^Pkg.Revision\s*=\s*' + re.escape(pin['ndk']['version']) + r'\s*$',
                               (ndk / 'source.properties').read_text(), re.M), 'ndk-version-mismatch')
    project = work / 'project'
    native = project / 'native'; native.mkdir(parents=True)
    for name in ('proot-sysvipc.patch', 'proot-acceleration.patch'):
        shutil.copyfile(original / 'native' / name, native / name)
    source = project / 'runtime-work/native'; source.mkdir(parents=True)
    shutil.copyfile(original / 'talloc-2.4.3.tar.gz', source / 'talloc.tar.gz')
    proot = source / 'proot'; proot.mkdir()
    with tarfile.open(original / 'proot-source.tar.gz') as archive:
        archive.extractall(proot, filter='data')
    with tarfile.open(original / 'talloc-2.4.3.tar.gz') as archive:
        archive.extractall(source, filter='data')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=proot, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=proot, check=True)
    makefile = proot / 'src/GNUmakefile'
    makefile.write_text(replace_exact(makefile.read_text(),
        '$(ROSEGMENT),-z,noexecstack', '$(ROSEGMENT),-z,noexecstack,-z,max-page-size=16384'))
    recipe = (original / 'build-proot.sh').read_text()
    recipe = replace_exact(recipe, 'repo_root="$(cd "$(dirname "$0")/.." && pwd)"', 'repo_root=' + shlex.quote(str(project)))
    recipe = replace_exact(recipe, 'ndk_path="${ANDROID_NDK_HOME:-${ANDROID_HOME:?Set ANDROID_HOME}/ndk/27.2.12479018}"',
                           'ndk_path=' + shlex.quote(str(ndk)))
    recipe = replace_exact(recipe, 'if [ ! -f talloc.tar.gz ]; then curl --fail --location --retry 3 https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz -o talloc.tar.gz; fi',
                           'test -f talloc.tar.gz # Pinned local input; no build-time download.')
    recipe = replace_exact(recipe, 'if [ ! -d proot ]; then git clone https://github.com/termux/proot.git proot; fi\ngit -C proot checkout 7266fb3e8516535682f5a9c8f3a7e70f6506eddb',
                           '# Exact archived source was checked and extracted by the build driver.')
    recipe = replace_exact(recipe, '-j2', '-j1', count=2)
    script = work / 'build.sh'; script.write_text(recipe)
    # Do not inherit compiler/linker overrides. Proxy variables remain available;
    # the exact transformed recipe performs no downloads.
    env = dict(os.environ, MAKEFLAGS='', MFLAGS='')
    for name in ('CC', 'CXX', 'CFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
        env.pop(name, None)
    with (work / 'build.log').open('x') as log:
        subprocess.run(['bash', str(script)], cwd=work, env=env, check=True, stdout=log, stderr=log, timeout=1800)
    built = project / 'app/src/main/jniLibs/arm64-v8a'
    provider = work / 'provider'
    libs = provider / 'jniLibs/arm64-v8a'; libs.mkdir(parents=True)
    assets = provider / 'assets/proot'; assets.mkdir(parents=True)
    payloads = {}
    for name in ('libproot.so', 'libproot-loader.so'):
        payloads[name] = identity(built / name, loader=name == 'libproot-loader.so')
        packages.require({k: payloads[name][k] for k in ('bytes', 'sha256')} == pin['expectedPayloads'][name],
                         'cross-built-payload-differs-from-pin')
        shutil.copyfile(built / name, libs / name)
        (libs / name).chmod(0o755)
    (assets / 'proot-COPYING.txt').write_bytes(license_text(original / 'proot-source.tar.gz', 'COPYING'))
    (assets / 'talloc-COPYING.txt').write_bytes(license_text(original / 'talloc-2.4.3.tar.gz', 'talloc-2.4.3/LICENSE'))
    shutil.copyfile(ROOT / 'LICENSE', assets / 'GNU-GPL-3.txt')
    shutil.copyfile(ROOT / 'runtime/proot/FTA-MIT-LICENSE.txt', assets / 'FTA-MIT-LICENSE.txt')
    (assets / 'NOTICE.txt').write_text('Termux PRoot ' + pin['prootCommit'] + ': GPL-2.0-or-later.\n'
        'Samba talloc 2.4.3, statically linked: LGPL-3.0-or-later.\n'
        'Build/ownership adaptation from Russianranger/fta-launcher at ' + pin['recipeReference']['commit'] + ': MIT.\n'
        'Esteria Android integration: GPL-3.0. Exact sources, patches and build driver accompany this build.\n'
        'Build-only ARM64 Android payloads; Android execution and game runtime are not qualified.\n')
    evidence = dict(formatVersion=1, scope='android-arm64-proot-build-only', buildJobs=1,
        sourceArchiveSha256=pin['source']['sha256'], sourceComponents=pin['components'],
        ownershipPatchSha256=digest(patch), ndkArchiveSha256=pin['ndk']['sha256'],
        ndkVersion=pin['ndk']['version'], androidApi=26, sourceLockSha256=digest(LOCK),
        builderSha256=digest(Path(__file__)), elfValidatorSha256=digest(ROOT / 'tools/android_elf.py'),
        payloads=payloads, androidBridgeBuilt=True, androidBridgeExecuted=False,
        androidRuntimeQualified=False, gameLoginQualified=False)
    packages.write_json(assets / 'build-evidence.json', evidence)
    packages.write_json(work / 'build-evidence.json', evidence)
    # Include all corresponding code and relinkable talloc objects, rather than
    # relying solely on a third party URL. Never include NDK proprietary tools.
    with tarfile.open(work / 'proot-corresponding-source.tar.gz', 'w:gz') as archive:
        archive.add(original, arcname='original')
        for name in ('tools/build_android_proot.py', 'tools/android_elf.py', 'tools/prepare_runtime.py',
                     'runtime/proot', 'LICENSE'):
            archive.add(ROOT / name, arcname='esteria/' + name)
        archive.add(source / 'talloc-2.4.3/bin/default', arcname='talloc-build-objects',
                    filter=lambda entry: entry if entry.isdir() or entry.name.endswith('.o') else None)
        archive.add(work / 'build-evidence.json', arcname='build-evidence.json')
    return provider, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--ndk-zip', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    provider, evidence = build(args.sources, args.ndk_zip, args.work)
    print(json.dumps(dict(provider=str(provider), androidBridgeBuilt=evidence['androidBridgeBuilt'],
                          androidBridgeExecuted=False)))


if __name__ == '__main__':
    main()
