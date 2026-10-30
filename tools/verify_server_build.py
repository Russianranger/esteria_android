#!/usr/bin/env python3
"""Verify installed Linux ARM64 server artifacts without treating them as a runtime.

Inspect ELF metadata with readelf (never ldd). The optional --loader-smoke only
executes source-confirmed auth/world --version on a native Linux ARM64 host.
It never initializes databases, starts listeners or claims Android/gameplay.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import selectors
import signal
import stat
import struct
import subprocess
import tempfile
import time

try:
    from . import fetch_sources
except ImportError:
    import fetch_sources

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_APPS = ('authserver', 'worldserver')
REQUIRED_TOOLS = ('dbimport', 'map_extractor', 'mmaps_generator', 'vmap4_assembler', 'vmap4_extractor')
BUFFER = 128 * 1024
MAX_FILES = 10000
MAX_FILE = 4 * 1024 ** 3
MAX_METADATA = 16 * 1024 ** 2


def require(condition, message):
    if not condition:
        raise ValueError(message)


@contextmanager
def plain_file(path):
    path = Path(path).absolute()
    for parent in path.parents:
        require(stat.S_ISDIR(parent.lstat().st_mode), 'symlinked-or-invalid-parent')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), 'not-a-regular-file')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            yield stream
    finally:
        if descriptor is not None:
            os.close(descriptor)


def identity(path):
    with plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(size <= MAX_FILE, 'installed-file-size-limit')
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            block = stream.read(min(BUFFER, remaining))
            require(block, 'installed-file-short-read')
            digest.update(block)
            remaining -= len(block)
        require(not stream.read(1), 'installed-file-changed-size')
    return {'bytes': size, 'sha256': digest.hexdigest()}


def bounded_command(command, *, timeout=30, limit=MAX_METADATA, cwd=None):
    """Bound diagnostic bytes and time without executing through a shell."""
    child = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'})
    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ)
    chunks, count = [], 0
    deadline = time.monotonic() + timeout
    try:
        while selector.get_map():
            require(time.monotonic() < deadline, 'diagnostic-command-timeout')
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                block = os.read(key.fd, BUFFER)
                if not block:
                    selector.unregister(key.fd)
                    continue
                count += len(block)
                require(count <= limit, 'diagnostic-command-output-limit')
                chunks.append(block)
        exit_code = child.wait(timeout=max(0.01, deadline - time.monotonic()))
        text = b''.join(chunks).decode('utf-8', errors='replace')
        require(exit_code == 0, f'diagnostic-command-failed: {command[0]}: {text[:1024]}')
        return text
    finally:
        selector.close()
        child.stdout.close()
        # Kill owned descendants even if a short-lived parent retained no pipe.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)


def elf_header(path, executable=False):
    with plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        header = stream.read(64)
        require(len(header) == 64 and header[:7] == b'\x7fELF\x02\x01\x01', 'not-little-endian-elf64')
        elf_type, machine, version = struct.unpack_from('<HHI', header, 16)
        require(machine == 183 and version == 1 and elf_type in (2, 3), 'not-aarch64-executable-or-shared-object')
        phoff = struct.unpack_from('<Q', header, 32)[0]
        ehsize, phentsize, phnum = struct.unpack_from('<HHH', header, 52)
        require(ehsize == 64 and phentsize == 56 and 0 < phnum <= 8192 and
                64 <= phoff <= size and phnum * phentsize <= size - phoff, 'invalid-elf-program-headers')
        stream.seek(phoff)
        headers = stream.read(phnum * phentsize)
        interpreter, load_segments = None, 0
        for offset in range(0, len(headers), phentsize):
            kind, flags, start, vaddr, paddr, filesz, memsz, align = struct.unpack_from('<IIQQQQQQ', headers, offset)
            require(start <= size and filesz <= size - start, 'elf-segment-out-of-bounds')
            if kind == 1:
                require(filesz <= memsz, 'elf-load-size-mismatch')
                load_segments += 1
            elif kind == 3:
                require(interpreter is None and 2 <= filesz <= 4096, 'invalid-elf-interpreter')
                stream.seek(start)
                raw = stream.read(filesz)
                require(raw.endswith(b'\0') and b'\0' not in raw[:-1], 'invalid-elf-interpreter')
                interpreter = raw[:-1].decode('utf-8', errors='strict')
                require(interpreter == '/lib/ld-linux-aarch64.so.1', 'unexpected-linux-arm64-interpreter')
        require(load_segments > 0, 'elf-has-no-load-segments')
        if executable:
            require(interpreter is not None and os.fstat(stream.fileno()).st_mode & 0o111, 'server-executable-missing-interpreter-or-mode')
    return {'class': 'ELF64', 'endianness': 'little', 'machine': 'AArch64',
            'type': 'EXEC' if elf_type == 2 else 'DYN', 'interpreter': interpreter}


def dynamic_metadata(text):
    needed = re.findall(r'\(NEEDED\).*Shared library: \[([^\]\n]+)\]', text)
    require(len(set(needed)) == len(needed), 'duplicate-needed-library')
    result = {'needed': sorted(needed), 'rpath': [], 'runpath': [], 'versionRequirements': {}}
    for field in ('RPATH', 'RUNPATH'):
        result[field.lower()] = re.findall(r'\(' + field + r'\).*\[([^\]\n]*)\]', text)
    # Version definitions describe exports; only the needs section constrains
    # the runtime. Preserve library association, including non-GLIBC namespaces.
    in_needs, library = False, None
    for line in text.splitlines():
        if line.startswith('Version needs section'):
            in_needs, library = True, None
        elif line.startswith('Version ') and 'section' in line:
            in_needs, library = False, None
        if not in_needs:
            continue
        match = re.search(r'File: (\S+)\s+Cnt:', line)
        if match:
            library = match.group(1)
            result['versionRequirements'].setdefault(library, [])
        match = re.search(r'Name: ([A-Za-z0-9_.]+)\s', line)
        if match:
            require(library is not None, 'version-need-without-library')
            result['versionRequirements'][library].append(match.group(1))
    for name, versions in result['versionRequirements'].items():
        result['versionRequirements'][name] = sorted(set(versions))
    glibc = {version for versions in result['versionRequirements'].values() for version in versions
             if re.fullmatch(r'GLIBC_[0-9]+(?:\.[0-9]+)+', version)}
    result['maximumGlibcVersionRequired'] = max(glibc, key=lambda v: tuple(map(int, v[6:].split('.')))) if glibc else None
    result['dependencyClosureQualified'] = False
    return result


def installed_files(root):
    require(stat.S_ISDIR(root.lstat().st_mode), 'install-root-must-be-a-plain-directory')
    found = []
    for base, directories, files in os.walk(root, followlinks=False):
        for name in directories:
            require(stat.S_ISDIR((Path(base) / name).lstat().st_mode), 'installed-directory-is-a-symlink')
        for name in files:
            path = Path(base) / name
            require(stat.S_ISREG(path.lstat().st_mode), 'installed-file-is-not-plain')
            found.append(path)
            require(len(found) <= MAX_FILES, 'installed-file-count-limit')
    return sorted(found)


def cmake_options(path):
    with plain_file(path) as stream:
        raw = stream.read(MAX_METADATA + 1)
    require(len(raw) <= MAX_METADATA, 'cmake-cache-size-limit')
    options = {}
    for line in raw.decode('utf-8').splitlines():
        match = re.match(r'([^/#][^:=]*):[^=]*=(.*)$', line)
        if match:
            require(match.group(1) not in options, 'duplicate-cmake-cache-option')
            options[match.group(1)] = match.group(2)
    expected = {'APPS_BUILD': 'all', 'TOOLS_BUILD': 'all', 'SCRIPTS': 'static', 'MODULES': 'static',
                'LUA_VERSION': 'lua52', 'CMAKE_BUILD_TYPE': 'RelWithDebInfo'}
    for key, value in expected.items():
        require(options.get(key) == value, f'unexpected-cmake-option: {key}')
    for key in ('ELUNA', 'LUA_STATIC'):
        require(options.get(key, '').upper() in ('1', 'ON', 'TRUE', 'YES'), f'cmake-option-disabled: {key}')
    for name in REQUIRED_APPS:
        require(options.get('APP_' + name.upper(), 'default') != 'disabled', f'disabled-application: {name}')
    for name in REQUIRED_TOOLS:
        require(options.get('TOOL_' + name.upper(), 'default') != 'disabled', f'disabled-tool: {name}')
    return {key: options[key] for key in sorted(set(expected) | {'ELUNA', 'LUA_STATIC'})}


def verify(install, server, lock_path, cache, packages, host, revision, build_id, *, readelf='readelf', loader_smoke=False):
    require(re.fullmatch('[0-9a-f]{40}', revision), 'full-integration-revision-required')
    require(re.fullmatch('[A-Za-z0-9_.-]{1,128}', build_id), 'invalid-build-identifier')
    lock = fetch_sources.load_lock(lock_path)
    source = lock['sources']['server']
    patches = fetch_sources.patch_inputs(source, lock_path.parent)
    fetch_sources.verify_checkout(server, source, patches)
    require(fetch_sources.run('git', 'rev-parse', 'HEAD', cwd=lock_path.parent) == revision,
            'integration-revision-mismatch')
    expected = {f'bin/{name}' for name in REQUIRED_APPS + REQUIRED_TOOLS}
    # These CMake files enumerate the corresponding directories, lowercase the
    # names and install targets to bin. Changes require reviewing this contract.
    source_contract = ['src/server/apps/CMakeLists.txt', 'src/tools/CMakeLists.txt',
        'src/cmake/macros/ConfigureApplications.cmake', 'src/cmake/macros/ConfigureTools.cmake']
    contract = {name: identity(server / name) for name in source_contract}
    for parent, names in (('src/server/apps', REQUIRED_APPS), ('src/tools', REQUIRED_TOOLS)):
        actual = {p.name for p in (server / parent).iterdir() if p.is_dir()}
        require(actual == set(names), f'source-target-list-changed: {parent}')
    paths = installed_files(install)
    names = {path.relative_to(install).as_posix() for path in paths}
    require(expected <= names, 'required-server-app-or-extractor-missing')
    require('server-build.json' not in names, 'manifest-already-exists')
    require(identity(install / 'sources.lock.json') == identity(lock_path), 'installed-source-lock-mismatch')
    options = cmake_options(cache)
    entries = []
    for path in paths:
        name = path.relative_to(install).as_posix()
        entry = {'path': name, **identity(path)}
        with plain_file(path) as stream:
            is_elf = stream.read(4) == b'\x7fELF'
        if is_elf or name in expected:
            entry['elf'] = elf_header(path, executable=name in expected)
            metadata = bounded_command([readelf, '--wide', '--dynamic', '--version-info', str(path)])
            entry['elf'].update(dynamic_metadata(metadata))
        entries.append(entry)
    proof = {'cmakeCache': identity(cache), 'packages': identity(packages), 'host': identity(host),
             'readelf': bounded_command([readelf, '--version'], limit=64 * 1024).splitlines()[0]}
    result = {'schemaVersion': 1, 'evidence': 'build-only', 'architecture': 'Linux-ARM64',
        'integrationRevision': revision, 'buildId': build_id, 'sourcesLock': identity(lock_path),
        'serverSource': source, 'sourceContract': contract, 'cmakeOptions': options,
        'buildEnvironment': proof, 'requiredExecutables': sorted(expected), 'files': entries,
        'sourceCheckoutAndPatchesVerified': True, 'runtimeDependencyClosureQualified': False,
        'mysqlPackaged': False, 'gameSchemasLoaded': False, 'gameDataLoaded': False,
        'androidRuntimeQualified': False, 'serverStarted': False, 'gameplayQualified': False,
        'hostLoaderSmoke': {'requested': loader_smoke, 'qualified': False}}
    if loader_smoke:
        require(platform.system() == 'Linux' and platform.machine().lower() in ('aarch64', 'arm64'),
                'loader-smoke-needs-native-linux-arm64')
        outputs = {}
        with tempfile.TemporaryDirectory(prefix='esteria-version-') as empty_cwd:
            for name in REQUIRED_APPS:
                # Both pinned Main.cpp files return immediately after printing
                # --version, before configuration, DB pools or listeners.
                text = bounded_command([str(install / 'bin' / name), '--version'],
                                       cwd=empty_cwd, timeout=20, limit=64 * 1024)
                require(source['commit'][:7] in text and 'Unix' in text, 'server-version-output-mismatch')
                outputs[name] = text.strip()
        result['hostLoaderSmoke'] = {'requested': True, 'qualified': True,
            'scope': 'auth-world-version-on-build-host-only', 'outputs': outputs}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--server', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=ROOT / 'sources.lock.json')
    parser.add_argument('--cmake-cache', type=Path, required=True)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--build-id', required=True)
    parser.add_argument('--readelf', default='readelf')
    parser.add_argument('--loader-smoke', action='store_true')
    args = parser.parse_args()
    install = args.install.absolute()
    result = verify(install, args.server.absolute(), args.lock.absolute(), args.cmake_cache.absolute(),
        args.packages.absolute(), args.host.absolute(), args.revision, args.build_id,
        readelf=args.readelf, loader_smoke=args.loader_smoke)
    with (install / 'server-build.json').open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    print(json.dumps({'verifiedExecutables': len(result['requiredExecutables']),
                      'files': len(result['files']), 'evidence': result['evidence'],
                      'hostLoaderSmoke': result['hostLoaderSmoke']['qualified']}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit('server artifact verification failed: ' + str(error)) from error
