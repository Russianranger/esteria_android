#!/usr/bin/env python3
"""Build an emulator-only x86_64 PRoot + real Debian glibc execution probe.

Production ARM64 source locks, provider builders and payloads are unchanged.
No guest executes during this build. Corresponding sources accompany the output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
from urllib.parse import urlsplit

try:
    from . import build_android_proot as proot, prepare_runtime as packages
except ImportError:
    import build_android_proot as proot
    import prepare_runtime as packages

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / 'native/proot-probe'
NATIVE_PINS = {
    'libproot_probe.so': {'bytes': 277512, 'sha256': '4e06b8d9037dd62b92983a2e4202e8f7aeb750329160fdf7f8bfe83324415263'},
    'libproot_probe_loader.so': {'bytes': 18344, 'sha256': '4a324117c6a16fe996af18ea388191379f5517309e963c80186fd3563a78410a'},
    'libproot_probe_control.so': {'bytes': 277512, 'sha256': 'aea88557d140c04ec60a7e3687dc5b78e7c85ccfece436fd1bb955f336a9fe92'},
}


def identity(path):
    return dict(bytes=path.stat().st_size, sha256=proot.digest(path))


def build(args):
    work = args.work.absolute()
    packages.require(not work.is_relative_to(ROOT) and not os.path.lexists(work), 'probe-needs-new-external-work-directory')
    packages.directory(work.parent, create=True)
    ndk = args.ndk.resolve(strict=True)
    common = json.loads(proot.LOCK.read_text())
    glibc = json.loads((INPUTS / 'glibc.lock.json').read_text())
    packages.require(re.search(r'^Pkg.Revision\s*=\s*' + re.escape(common['ndk']['version']) + r'\s*$',
                     (ndk / 'source.properties').read_text(), re.M), 'wrong-ndk-version')
    llvm = ndk / 'toolchains/llvm/prebuilt/linux-x86_64/bin'
    with packages.plain_file(args.sources) as incoming:
        packages.verify_stream(incoming, common['source'])
    patch = ROOT / common['ownershipPatch']['path']
    packages.require(proot.digest(patch) == common['ownershipPatch']['sha256'], 'ownership-patch-differs')
    work.mkdir(mode=0o700)
    original = work / 'original'; original.mkdir()
    proot.recover_sources(args.sources, original, common['components'])
    cache = args.cache.absolute()
    inputs = []
    for entry in glibc['packages'] + glibc['sources']:
        pin = dict(entry, file=urlsplit(entry['url']).path.rsplit('/', 1)[1])
        path = cache / pin['file']
        if args.download:
            path = packages.fetch(pin, cache)
        else:
            with packages.plain_file(path) as incoming:
                packages.verify_stream(incoming, pin)
        inputs.append((pin, path))
    project = work / 'project'; native = project / 'native'; native.mkdir(parents=True)
    for name in ('proot-sysvipc.patch', 'proot-acceleration.patch'):
        shutil.copyfile(original / 'native' / name, native / name)
    source = project / 'runtime-work/native'; source.mkdir(parents=True)
    shutil.copyfile(original / 'talloc-2.4.3.tar.gz', source / 'talloc.tar.gz')
    tracer = source / 'proot'; tracer.mkdir()
    with tarfile.open(original / 'proot-source.tar.gz') as archive:
        archive.extractall(tracer, filter='data')
    with tarfile.open(original / 'talloc-2.4.3.tar.gz') as archive:
        archive.extractall(source, filter='data')
    subprocess.run(['git', 'apply', '--check', str(patch)], cwd=tracer, check=True)
    subprocess.run(['git', 'apply', str(patch)], cwd=tracer, check=True)
    makefile = tracer / 'src/GNUmakefile'
    makefile.write_text(proot.replace_exact(makefile.read_text(),
        '$(ROSEGMENT),-z,noexecstack', '$(ROSEGMENT),-z,noexecstack,-z,max-page-size=16384'))
    recipe = (original / 'build-proot.sh').read_text()
    substitutions = [
        ('repo_root="$(cd "$(dirname "$0")/.." && pwd)"', 'repo_root=' + shlex.quote(str(project)), 1),
        ('ndk_path="${ANDROID_NDK_HOME:-${ANDROID_HOME:?Set ANDROID_HOME}/ndk/27.2.12479018}"', 'ndk_path=' + shlex.quote(str(ndk)), 1),
        ('if [ ! -f talloc.tar.gz ]; then curl --fail --location --retry 3 https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz -o talloc.tar.gz; fi', 'test -f talloc.tar.gz # Pinned local input.', 1),
        ('if [ ! -d proot ]; then git clone https://github.com/termux/proot.git proot; fi\ngit -C proot checkout 7266fb3e8516535682f5a9c8f3a7e70f6506eddb', '# Exact archived source checked and extracted.', 1),
        ('aarch64-linux-android26-clang', 'x86_64-linux-android26-clang', 1),
        ('"aarch64"', '"x86_64"', 1), ('arm64-v8a', 'x86_64', 6), ('-j2', '-j1', 2),
    ]
    for old, new, count in substitutions:
        recipe = proot.replace_exact(recipe, old, new, count=count)
    script = work / 'build-proot.sh'; script.write_text(recipe)
    environment = dict(os.environ, MAKEFLAGS='', MFLAGS='')
    for name in ('CC', 'CXX', 'CFLAGS', 'CPPFLAGS', 'LDFLAGS', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
        environment.pop(name, None)
    with (work / 'build.log').open('x') as log:
        subprocess.run(['bash', str(script)], env=environment, check=True, stdout=log, stderr=log, timeout=1800)
    binary = project / 'app/src/main/jniLibs/x86_64'
    saved = work / 'native-binaries'; saved.mkdir()
    for name in ('libproot.so', 'libproot-loader.so'):
        shutil.copyfile(binary / name, saved / name)
    # Negative control is byte-pinned and packaged only by the emulator/debug
    # profile. Its only source difference is omission of mandatory EXITKILL.
    subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)], cwd=tracer, check=True)
    subprocess.run(['git', 'apply', '--reverse', str(patch)], cwd=tracer, check=True)
    with (work / 'control-build.log').open('x') as log:
        subprocess.run(['bash', str(script)], env=environment, check=True, stdout=log, stderr=log, timeout=1800)
    shutil.copyfile(binary / 'libproot.so', saved / 'libproot-control.so')
    # Extract authenticated data packages only. dpkg-deb --extract never runs
    # maintainer scripts; each complete archive was size/hash verified above.
    sysroot = work / 'glibc-sysroot'; sysroot.mkdir()
    for pin, path in inputs[:len(glibc['packages'])]:
        subprocess.run(['dpkg-deb', '--extract', str(path), str(sysroot)], check=True, timeout=120)
    objects = work / 'guest-build'; objects.mkdir()
    cc = [str(llvm / 'clang'), '--target=x86_64-linux-gnu', '--sysroot=' + str(sysroot),
          '-isystem', str(sysroot / 'usr/include/x86_64-linux-gnu'), '-O2', '-Wall', '-Wextra', '-Werror',
          '-fno-stack-protector', '-fuse-ld=lld', '-nostdlib', '-Wl,-z,noexecstack,-z,max-page-size=16384',
          '-L' + str(sysroot / 'usr/lib/x86_64-linux-gnu'), '-L' + str(sysroot / 'lib/x86_64-linux-gnu')]
    startup = sysroot / 'usr/lib/x86_64-linux-gnu'
    commands = [
        cc + ['-fPIE', '-pie', '-Wl,--dynamic-linker=/lib64/ld-linux-x86-64.so.2',
              str(startup / 'Scrt1.o'), str(startup / 'crti.o'), str(INPUTS / 'guest.c'),
              '-lc', str(startup / 'crtn.o'), '-o', str(objects / 'probe')],
        cc + ['-fPIC', '-shared', str(INPUTS / 'plugin.c'), '-lc', '-o', str(objects / 'probe-plugin.so')],
        cc + ['-fPIE', '-pie', '-Wl,--dynamic-linker=/lib64/ld-linux-x86-64.so.2',
              str(startup / 'Scrt1.o'), str(startup / 'crti.o'), str(INPUTS / 'ownership_guest.c'),
              '-lc', str(startup / 'crtn.o'), '-o', str(objects / 'probe-owner')],
    ]
    with (work / 'guest-build.log').open('x') as log:
        for command in commands:
            subprocess.run(command, env=environment, stdout=log, stderr=log, check=True, timeout=120)
    provider = work / 'provider'
    libs = provider / 'jniLibs/x86_64'; libs.mkdir(parents=True)
    assets = provider / 'assets/proot-probe'; assets.mkdir(parents=True)
    rootfs = assets / 'rootfs'; rootfs.mkdir()
    for original_name, name in [('libproot.so', 'libproot_probe.so'), ('libproot-loader.so', 'libproot_probe_loader.so'),
                                ('libproot-control.so', 'libproot_probe_control.so')]:
        packages.require(identity(saved / original_name) == NATIVE_PINS[name], 'probe-native-build-differs-from-pin')
        shutil.copyfile(saved / original_name, libs / name); (libs / name).chmod(0o755)
    files = {
        'probe': objects / 'probe', 'probe-plugin.so': objects / 'probe-plugin.so',
        'probe-owner': objects / 'probe-owner',
        'lib/x86_64-linux-gnu/libc.so.6': sysroot / 'lib/x86_64-linux-gnu/libc.so.6',
        'lib64/ld-linux-x86-64.so.2': sysroot / 'lib/x86_64-linux-gnu/ld-linux-x86-64.so.2',
    }
    root_files = {}
    for name, incoming in files.items():
        destination = rootfs / name; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(incoming, destination); root_files[name] = identity(destination)
    notices = assets / 'notices'; notices.mkdir()
    for package in ('libc6', 'libc6-dev', 'linux-libc-dev'):
        shutil.copyfile(sysroot / 'usr/share/doc' / package / 'copyright', notices / (package + '-copyright.txt'))
    (notices / 'proot-COPYING.txt').write_bytes(proot.license_text(original / 'proot-source.tar.gz', 'COPYING'))
    (notices / 'talloc-COPYING.txt').write_bytes(proot.license_text(original / 'talloc-2.4.3.tar.gz', 'talloc-2.4.3/LICENSE'))
    shutil.copyfile(ROOT / 'LICENSE', notices / 'ESTERIA-GPL-3.txt')
    shutil.copyfile(ROOT / 'runtime/proot/FTA-MIT-LICENSE.txt', notices / 'FTA-MIT-LICENSE.txt')
    evidence = dict(formatVersion=1, scope='android-13-x86_64-proot-glibc-probe-build-only',
        ndkVersion=common['ndk']['version'], compilerSha256=proot.digest((llvm / 'clang').resolve(strict=True)),
        prootSourceLockSha256=proot.digest(proot.LOCK), glibcLockSha256=proot.digest(INPUTS / 'glibc.lock.json'),
        builderSha256=proot.digest(Path(__file__)), guestSourceSha256=proot.digest(INPUTS / 'guest.c'),
        pluginSourceSha256=proot.digest(INPUTS / 'plugin.c'), ownershipPatchSha256=proot.digest(patch),
        ownershipGuestSourceSha256=proot.digest(INPUTS / 'ownership_guest.c'), unpatchedControlIncluded=True,
        nativeFiles=NATIVE_PINS, rootfsFiles=root_files, glibcVersion='2.36',
        androidProotExecuted=False, arm64GuestExecuted=False, gameplayQualified=False)
    packages.write_json(assets / 'build-evidence.json', evidence)
    packages.write_json(work / 'build-evidence.json', evidence)
    with tarfile.open(work / 'corresponding-source.tar.gz', 'w:gz') as archive:
        archive.add(original, arcname='original-proot')
        for pin, path in inputs:
            archive.add(path, arcname='original-debian/' + pin['file'])
        for name in ('native/proot-probe', 'tools/build_android_proot_probe.py', 'tools/verify_android_proot_probe.py', 'tools/build_android_proot.py',
                     'tools/prepare_runtime.py', 'tools/android_elf.py', 'runtime/proot', 'LICENSE'):
            archive.add(ROOT / name, arcname='esteria/' + name)
        archive.add(source / 'talloc-2.4.3/bin/default', arcname='talloc-relinkable-objects',
                    filter=lambda entry: entry if entry.isdir() or entry.name.endswith('.o') else None)
        archive.add(work / 'build-evidence.json', arcname='build-evidence.json')
    return provider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--ndk', type=Path, required=True, help='SDK-installed pinned NDK root; compiler identity recorded')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--download', action='store_true', help='Explicitly acquire exact pinned Debian archives')
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(dict(provider=str(build(args)), androidProotExecuted=False)))


if __name__ == '__main__':
    main()
