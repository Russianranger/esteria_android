#!/usr/bin/env python3
"""Run original/fixed Linux PRoot against a bounded synthetic detached process tree.

Builds one native host job; this does not qualify Android PRoot execution.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import tarfile
import time

try:
    from . import build_android_proot as builder, prepare_runtime as packages
except ImportError:
    import build_android_proot as builder
    import prepare_runtime as packages

# Adapted from Russianranger/fta-launcher at 7a9ce45988f295824d20c9ff7436a77a0baa4f07.
# MIT notice: runtime/proot/FTA-MIT-LICENSE.txt.
ROOT = builder.ROOT
PIN = json.loads(builder.LOCK.read_text())
INPUTS = PIN['components']
SOURCE_SHA = PIN['source']['sha256']
replace_exact, require, digest = builder.replace_exact, packages.require, builder.digest

def recover_sources(bundle, directory):
    return builder.recover_sources(bundle, directory, INPUTS)

def check_jobs(jobs):
    require(jobs == 1, 'ownership-build-requires-one-job')
    info = dict(re.findall(r'^(\w+):\s+(\d+) kB$', Path('/proc/meminfo').read_text(), re.M))
    require(int(info.get('MemAvailable', 0)) >= 512 * 1024, 'insufficient-build-memory')

HELPER = '''import subprocess,sys
symbols={}
for line in subprocess.check_output(['readelf','-s',sys.argv[1]],text=True).splitlines():
    cols=line.split()
    if len(cols)>=8 and cols[-1] in ('_start','pokedata_workaround'): symbols[cols[-1]]=int(cols[1],16)
print('#include <unistd.h>')
print('const ssize_t offset_to_pokedata_workaround=%d;' % (symbols['pokedata_workaround']-symbols['_start']))
'''


def fixture_identity(executable, maps, fixture, loader):
    # PRoot executes its freestanding loader instead of the requested image
    # (original translate_execve_enter). Check both kernel entry and mapped code.
    if executable not in (fixture, loader) or len(maps) > 128 * 1024:
        return False
    for line in maps.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) == 6 and 'x' in fields[1] and fields[5] == str(fixture):
            return True
    return False


def run_case(proot, fixture, directory, owned):
    handles = []; tracer = None; tracer_fd = None
    with (directory / ('owned.log' if owned else 'baseline.log')).open('wb') as log:
        try:
            tracer = subprocess.Popen([str(proot), '-r', '/', '-w', str(directory), str(fixture)],
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=log, start_new_session=True,
                env=dict(os.environ, PROOT_LOADER=str(directory / 'loader')))
            tracer_fd = os.pidfd_open(tracer.pid)
            with selectors.DefaultSelector() as ready:
                ready.register(tracer.stdout, selectors.EVENT_READ)
                data = b''; deadline = time.monotonic() + 10
                while data.count(b'\n') < 3 and time.monotonic() < deadline:
                    if not ready.select(0.1):
                        continue
                    chunk = os.read(tracer.stdout.fileno(), 1024)
                    require(chunk and len(data) + len(chunk) <= 256, 'Fixture did not report three bounded PIDs')
                    data += chunk
            lines = data.decode('ascii').splitlines()
            require(len(lines) == 3 and all(re.fullmatch(r'ESTERIA_PROOT_FIXTURE_PID [1-9][0-9]*', line) for line in lines), 'Invalid fixture PIDs')
            pids = [int(line.split()[1]) for line in lines]
            require(len(set(pids)) == 3, 'Duplicate fixture PIDs')
            for pid in pids:
                fd = os.pidfd_open(pid)
                try:
                    with Path(f'/proc/{pid}/maps').open() as incoming:
                        maps = incoming.read(128 * 1024 + 1)
                    require(fixture_identity(Path(f'/proc/{pid}/exe').resolve(strict=True), maps,
                        fixture, directory / 'loader'), 'PID does not belong to our fixture')
                except BaseException:
                    os.close(fd)
                    raise
                # Never put an unverified PID in the cleanup signal set.
                handles.append(fd)
            require(sum(os.getsid(pid) == pid for pid in pids) >= 2, 'Fixture descendants did not detach sessions')
            signal.pidfd_send_signal(tracer_fd, signal.SIGKILL)
            require(tracer.wait(timeout=5) == -signal.SIGKILL, 'Tracer did not receive forced kill')
            with selectors.DefaultSelector() as terminated:
                for fd in handles:
                    terminated.register(fd, selectors.EVENT_READ)
                exited = set(); deadline = time.monotonic() + (5 if owned else 0.5)
                while time.monotonic() < deadline and len(exited) < 3:
                    for key, _ in terminated.select(min(0.1, max(0, deadline-time.monotonic()))):
                        exited.add(key.fd); terminated.unregister(key.fd)
            require(len(exited) == (3 if owned else 0), 'Unexpected descendant survival after tracer kill')
            return dict(detachedSessionLeaders=2, tracees=3, terminatedAfterTracerKill=len(exited))
        finally:
            if tracer_fd is not None:
                # Before the intentional kill, let PRoot's normal failure cleanup
                # handle any tree that did not reach the bounded PID handshake.
                if tracer.poll() is None:
                    try: signal.pidfd_send_signal(tracer_fd, signal.SIGTERM)
                    except ProcessLookupError: pass
                    try: tracer.wait(timeout=2)
                    except subprocess.TimeoutExpired: pass
                try: signal.pidfd_send_signal(tracer_fd, signal.SIGKILL)
                except ProcessLookupError: pass
                os.close(tracer_fd)
            for fd in handles:
                try: signal.pidfd_send_signal(fd, signal.SIGKILL)
                except ProcessLookupError: pass
                os.close(fd)
            if tracer:
                tracer.wait(timeout=5)
                if tracer.stdout: tracer.stdout.close()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                try:
                    if os.waitpid(-1, os.WNOHANG)[0] == 0: time.sleep(0.01)
                except ChildProcessError: break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    args = parser.parse_args()
    require(not args.sources.is_symlink() and digest(args.sources) == SOURCE_SHA, 'Wrong source archive')
    work = args.work.resolve(); require(not work.exists() and not work.is_relative_to(ROOT), 'Use a new directory outside Git')
    check_jobs(1); work.mkdir(parents=True)
    require(ctypes.CDLL(None).prctl(36, 1, 0, 0, 0) == 0, 'Subreaper unavailable')
    original = work / 'original'; original.mkdir(); recover_sources(args.sources, original)
    for source, target in [('talloc-2.4.3.tar.gz', work), ('proot-source.tar.gz', work / 'proot')]:
        target.mkdir(exist_ok=True)
        with tarfile.open(original / source) as archive: archive.extractall(target, filter='data')
    env = dict(os.environ, CC='gcc', AR='ar', RANLIB='ranlib', CFLAGS='-O2 -fPIC', LDFLAGS='', MAKEFLAGS='', MFLAGS='')
    prefix = work / 'prefix'; (prefix / 'include').mkdir(parents=True); (prefix / 'lib').mkdir()
    source = work / 'proot'; patch = ROOT / 'runtime/proot/proot-exitkill.patch'
    require(digest(patch) == PIN['ownershipPatch']['sha256'], 'Ownership patch differs')
    with (work / 'build.log').open('w') as log:
        def run(args, cwd):
            subprocess.run(args, cwd=cwd, env=env, check=True, stdout=log, stderr=log, timeout=900)
        talloc = work / 'talloc-2.4.3'
        run(['./configure', '--prefix=' + str(prefix), '--disable-python', '--disable-rpath'], talloc)
        run(['make', '-j1'], talloc)
        shutil.copyfile(talloc / 'talloc.h', prefix / 'include/talloc.h')
        run(['ar', 'rcs', str(prefix / 'lib/libtalloc.a')] + [str(p) for p in sorted((talloc / 'bin/default').glob('talloc*.o'))], talloc)
        for name in ('proot-acceleration.patch', 'proot-sysvipc.patch'):
            run(['git', 'apply', str(original / 'native' / name)], source)
        header = source / 'src/extension/ashmem_memfd/ashmem_memfd.c'
        header.write_text('#include <string.h>\n' + header.read_text())
        make = source / 'src/GNUmakefile'
        make.write_text(replace_exact(make.read_text(), 'readelf -s $< | awk -f loader/loader-info.awk > $@',
                                     'python3 loader/loader-info.py $< > $@'))
        (source / 'src/loader/loader-info.py').write_text(HELPER)
        command = ['make', '-C', 'src', '-j1', 'CC=gcc', 'LD=gcc',
            'CPPFLAGS=-D_FILE_OFFSET_BITS=64 -D_GNU_SOURCE -I. -I' + str(source / 'src') + ' -I' + str(prefix / 'include'),
            # This fixture runs native ELF64 only. GCC on AArch64 has no -m32;
            # suppress the makefile's optional ARM32 loader build dependency.
            # Keep the tracer's original arch.h and both Android loaders intact.
            'LDFLAGS=-L' + str(prefix / 'lib') + ' -ltalloc -Wl,-z,noexecstack',
            'PROOT_UNBUNDLE_LOADER=/unused', 'HAS_LOADER_32BIT=']
        run(command, source)
        baseline = work / 'proot-baseline'; shutil.copyfile(source / 'src/proot', baseline); baseline.chmod(0o755)
        run(['git', 'apply', '--check', str(patch)], source); run(['git', 'apply', str(patch)], source)
        run(command, source)
        owned = work / 'proot-owned'; shutil.copyfile(source / 'src/proot', owned); owned.chmod(0o755)
        loader = work / 'loader'; shutil.copyfile(source / 'src/loader/loader', loader); loader.chmod(0o755)
        fixture = work / 'fixture'
        run(['gcc', '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O2', '-Wall', '-Wextra', '-Werror',
             str(ROOT / 'runtime/proot/ownership_fixture.c'), '-o', str(fixture)], work)
    normal = subprocess.run([str(owned), '-r', '/', '-w', str(work), str(fixture), '--normal'],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
        env=dict(os.environ, PROOT_LOADER=str(loader)))
    (work / 'normal.log').write_bytes(normal.stdout + normal.stderr)
    require(normal.returncode == 0 and normal.stdout.count(b'ESTERIA_PROOT_FIXTURE_PID ') == 3, 'Normal tree exit failed')
    negative = run_case(baseline, fixture, work, False)
    positive = run_case(owned, fixture, work, True)
    evidence = dict(formatVersion=1, scope='native-linux-proot-ownership', sourceArchiveSha256=SOURCE_SHA,
        sourceComponents=INPUTS, ownershipPatchSha256=digest(patch), buildJobs=1,
        machine=os.uname().machine, linuxGuestScope='native ELF64 only',
        normalTreeExit=0, baseline=negative, fixed=positive,
        fixtureSha256=digest(fixture), loaderSha256=digest(loader),
        baselineProotSha256=digest(baseline), ownedProotSha256=digest(owned),
        linuxTracerDeathOwnershipQualified=True, androidBridgeExecuted=False, androidRuntimeQualified=False,
        gameLoginQualified=False)
    (work / 'ownership-evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'normalExit': 0, 'baselineSurvivors': 3, 'ownedSurvivors': 0}))


if __name__ == '__main__':
    main()
