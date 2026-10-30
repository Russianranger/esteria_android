#!/usr/bin/env python3
"""Transactional generation of local Vulkan shaders from completed client imports.

This Linux guest helper consumes a separately verified, source-matched tool bundle.
It never downloads content or writes into imported data. A receipt records generation,
not rendering qualification. Normal gameplay resolves a prepared generation separately.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import time
import uuid

HASH = re.compile(r'[0-9a-f]{64}\Z')
MD5 = re.compile(r'[0-9a-f]{32}\Z')
REVISION = re.compile(r'[0-9a-f]{40}\Z')
LOCALES = {'enUS', 'enGB', 'koKR', 'frFR', 'deDE', 'zhCN', 'zhTW', 'esES', 'esMX', 'ruRU'}
TOOL_FILES = {'translate_shaders.py', 'bls/__init__.py', 'bls/archive.py',
              'bls/dx9ir.py', 'bls/emitter.py', 'bls/mpq_extract.py', 'bls/translate.py',
              'bin/glslangValidator'}
MAX_MODULES = 32768
MAX_MODULE = 16 << 20
MAX_OUTPUT = 2 << 30
MAX_TEXT = 16 << 20


class ShaderError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ShaderError(message)


def canonical(path: Path, directory=True, create=False):
    path = Path(os.path.abspath(path))
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if create and not cursor.exists() and not cursor.is_symlink():
            cursor.mkdir(mode=0o700)
        info = cursor.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'symlink in shader setup path')
        require(stat.S_ISDIR(info.st_mode) if cursor != path or directory else stat.S_ISREG(info.st_mode),
                'non-regular shader setup path')
    return path


def read(path, maximum):
    canonical(path, False)
    with path.open('rb') as source:
        require(os.fstat(source.fileno()).st_size <= maximum, 'metadata size bound exceeded')
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, 'metadata grew beyond bound')
    return raw


def identity(path, maximum):
    canonical(path, False)
    with path.open('rb') as source:
        before = os.fstat(source.fileno())
        require(0 <= before.st_size <= maximum, 'file size bound exceeded')
        digest = hashlib.sha256()
        count = 0
        while block := source.read(128 << 10):
            count += len(block)
            require(count <= maximum, 'file grew beyond bound')
            digest.update(block)
        after = os.fstat(source.fileno())
    require(count == before.st_size and (before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
            (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'input changed during read')
    return {'bytes': count, 'sha256': digest.hexdigest()}


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


def atomic(path, raw):
    temp = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    with temp.open('xb') as out:
        os.chmod(temp, 0o600)
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    sync(path.parent)


def sync(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def imported(game, generation):
    """Bind private completion/overlay journals; never rehash whole MPQs here.

    These are trusted importer records, not signatures or content qualification.
    The caller must keep import activation and client execution stopped throughout.
    """
    require(bool(HASH.fullmatch(generation)), 'invalid import generation')
    game = canonical(game)
    require(read(game / 'current', 66) == (generation + '\n').encode(), 'import is no longer current')
    rows, seen, total = {}, set(), 0
    at = generation
    while at is not None:
        require(at not in seen and len(seen) < 32, 'import ancestry cycle or depth bound')
        seen.add(at)
        root = canonical(game / 'generations' / at)
        canonical(root / 'data')
        complete = read(root / 'complete', 2048)
        require(complete.endswith(b'\n'), 'incomplete import receipt')
        values = {}
        for line in complete.decode('utf-8').splitlines():
            key, separator, value = line.partition('=')
            require(separator and key not in values, 'invalid import receipt')
            values[key] = value
        require(values.get('format') == '1' and values.get('clientBuild') == '12340' and
                values.get('request') == at and bool(HASH.fullmatch(values.get('source', ''))),
                'import receipt does not bind build12340 and generation')
        rows[at + '/complete'] = identity(root / 'complete', 2048)
        journal = identity(root / 'journal.tsv', 32 << 20)
        total += journal['bytes']
        require(total <= 64 << 20, 'import metadata exceeds64MiB')
        rows[at + '/journal.tsv'] = journal
        parent = root / 'base-ready'
        if parent.exists() or parent.is_symlink():
            raw = read(parent, 66)
            next_id = raw.decode('ascii').removesuffix('\n')
            require(bool(HASH.fullmatch(next_id)) and raw == (next_id + '\n').encode(), 'invalid import parent')
            rows[at + '/base-ready'] = identity(parent, 66)
            at = next_id
        else:
            at = None
    return rows


def tool_identity(root, revision):
    root = canonical(root)
    require(bool(REVISION.fullmatch(revision)), 'full client revision required')
    raw = read(root / 'shader-tools.json', 65536)
    manifest = json.loads(raw)
    require(manifest.get('formatVersion') == 1 and manifest.get('clientRevision') == revision and
            set(manifest.get('files', {})) == TOOL_FILES, 'shader tool source/closure mismatch')
    found = set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        at = Path(directory).relative_to(root)
        for name in dirs:
            require(at == Path('.') and name in ('bls', 'bin'), 'unexpected shader tool directory')
            canonical(Path(directory) / name)
        for name in files:
            path = Path(directory) / name
            canonical(path, False)
            found.add(path.relative_to(root).as_posix())
    require(found == TOOL_FILES | {'shader-tools.json'}, 'unexpected shader tool file or bytecode cache')
    for name, pin in manifest['files'].items():
        require(type(pin) is dict and set(pin) == {'bytes', 'sha256'} and
                type(pin['bytes']) is int and 0 < pin['bytes'] <= 64 << 20 and
                bool(HASH.fullmatch(pin['sha256'])), 'invalid shader tool pin')
        require(identity(root / name, 64 << 20) == pin, 'shader tool bytes differ from package')
    require(os.access(root / 'bin/glslangValidator', os.X_OK), 'shader compiler is not executable')
    return hashlib.sha256(raw).hexdigest()


def spirv(path, kind):
    raw = read(path, MAX_MODULE)
    require(len(raw) >= 20 and len(raw) % 4 == 0, 'invalid SPIR-V length')
    magic, version, generator, bound, schema = struct.unpack_from('<5I', raw)
    require(magic == 0x07230203 and version == 0x00010000 and 0 < bound <= 1 << 24 and schema == 0,
            'invalid Vulkan1.0 SPIR-V header')
    offset, entry = 20, False
    while offset < len(raw):
        instruction, = struct.unpack_from('<I', raw, offset)
        words, opcode = instruction >> 16, instruction & 0xffff
        require(words > 0 and offset + words * 4 <= len(raw), 'invalid SPIR-V instruction bounds')
        if opcode == 15:  # OpEntryPoint: execution model, ID and null-terminated name.
            require(words >= 4, 'invalid SPIR-V entry point')
            model, = struct.unpack_from('<I', raw, offset + 4)
            require(model == (0 if kind == 'vertex' else 4), 'SPIR-V stage mismatch')
            entry = True
        offset += words * 4
    require(entry, 'SPIR-V entry point missing')
    # Structural validation only; real --spirv-val is performed by the compiler.


def validate_output(root):
    canonical(root)
    manifest = read(root / 'manifest.txt', MAX_TEXT).decode('utf-8')
    index = read(root / 'index.txt', MAX_TEXT).decode('utf-8')
    require('Refused (not translated):' not in manifest and 'REFUSED:' not in index,
            'partial/refused shader generation cannot be activated')
    records, current, companions = {}, None, []
    for line in manifest.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith('#'):
            continue
        if fields[0] == 'record':
            require(len(fields) in (7, 8), 'invalid shader manifest record')
            _, digest, kind, profile, relative, vconst, pconst, *extra = fields
            require(bool(MD5.fullmatch(digest)) and digest not in records and kind in ('vertex', 'pixel') and
                    relative == kind + '/' + digest + '.spv' and
                    profile in ({'vs_3_0', 'vs_2_0', 'vs_1_1'} if kind == 'vertex' else
                                {'ps_3_0', 'ps_2_0', 'ps_1_4', 'ps_1_1', 'ff'}) and
                    vconst in ('vconst=64', 'vconst=512', 'vconst=1024') and pconst == 'pconst=20' and
                    (not extra or extra == ['pext=96']), 'invalid shader manifest contract')
            records[digest] = (kind, profile, relative)
            require(len(records) <= MAX_MODULES, 'shader count bound exceeded')
            current = digest
        else:
            require(current is not None and fields[0] in ('name', 'sampler', 'input', 'output', 'reads', 'flag', 'companion'),
                    'unknown shader manifest line')
            if fields[0] == 'companion':
                require(len(fields) == 2 and bool(MD5.fullmatch(fields[1])) and records[current][0] == 'vertex',
                        'invalid shader companion')
                companions.append(fields[1])
    require({record[0] for record in records.values()} == {'vertex', 'pixel'}, 'both shader stages required')
    for digest in companions:
        require(digest in records and records[digest][:2] == ('pixel', 'ff'), 'missing fixed-function companion')
    expected = {record[2] for record in records.values()}
    inventory, total = {}, 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        relative = Path(directory).relative_to(root)
        require(relative == Path('.') or str(relative) in ('vertex', 'pixel'), 'unexpected shader output directory')
        for name in dirs:
            require(relative == Path('.') and name in ('vertex', 'pixel'), 'unexpected shader output subtree')
            canonical(Path(directory) / name)
        for name in files:
            path = Path(directory) / name
            name = path.relative_to(root).as_posix()
            require(name in ('manifest.txt', 'index.txt') or
                    bool(re.fullmatch(r'(?:vertex|pixel)/[0-9a-f]{32}\.(?:spv|glsl|spvasm)', name)),
                    'unexpected shader output file')
            pin = identity(path, MAX_TEXT if name.endswith('.txt') else MAX_MODULE)
            total += pin['bytes']
            require(total <= MAX_OUTPUT and len(inventory) < MAX_MODULES * 3 + 2, 'shader output bound exceeded')
            inventory[name] = pin
    require({name for name in inventory if name.endswith('.spv')} == expected, 'shader module set differs from manifest')
    for kind, profile, relative in records.values():
        spirv(root / relative, kind)
    return inventory


def execute(command, output, timeout):
    """Serial translator; bounded log and duration, no shell or network setup."""
    require(0 < timeout <= 14400, 'invalid shader setup deadline')
    # Compiler execution has its own per-record bounds in the pinned translator.
    # On abort the Android owner must stop the complete PRoot process tree.
    with output.open('xb') as log:
        os.chmod(output, 0o600)
        child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
                                 env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'})
        deadline = time.monotonic() + timeout
        os.set_blocking(child.stdout.fileno(), False)
        written = 0
        try:
            while True:
                while True:
                    require(time.monotonic() < deadline, 'shader generation deadline exceeded')
                    try:
                        chunk = os.read(child.stdout.fileno(), 65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    remaining = (8 << 20) - written
                    log.write(chunk[:remaining])
                    written += min(remaining, len(chunk))
                    require(len(chunk) <= remaining, 'shader setup log exceeded8MiB')
                require(time.monotonic() < deadline, 'shader generation deadline exceeded')
                # Leave the leader unreaped until group cleanup. Its reserved PID
                # prevents signalling a recycled process-group identifier.
                if os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                    # Capture the final pipe bytes after observing exit. The
                    # retained zombie still reserves the process group identity.
                    while True:
                        try:
                            tail = os.read(child.stdout.fileno(), 65536)
                        except BlockingIOError:
                            break
                        if not tail:
                            break
                        remaining = (8 << 20) - written
                        log.write(tail[:remaining])
                        written += min(remaining, len(tail))
                        require(len(tail) <= remaining, 'shader setup log exceeded8MiB')
                    break
                time.sleep(0.1)
        finally:
            # The group is created exclusively for this process. Kill remaining
            # compiler children even if the translator exited unexpectedly.
            try:
                os.killpg(child.pid, 9)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired as error:
                raise ShaderError('shader process did not reap within cleanup deadline') from error
            finally:
                child.stdout.close()
        require(child.returncode == 0, 'shader translator failed; previous generation retained')


def generate(store, game, generation, tools, revision, locale, timeout=7200):
    require(locale in LOCALES, 'explicit supported locale required')
    store, game, tools = canonical(store, create=True), canonical(game), canonical(tools)
    require(not any(a == b or a in b.parents or b in a.parents for a, b in
                    ((store, game), (store, tools), (game, tools))), 'shader/input/tool roots must be separate')
    lock = os.open(store / '.setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = {'formatVersion': 1, 'importGeneration': generation, 'clientRevision': revision,
                  'locale': locale, 'importMetadata': imported(game, generation),
                  'toolManifestSha256': tool_identity(tools, revision)}
        key = hashlib.sha256(encoded(inputs)).hexdigest()
        generations = canonical(store / 'generations', create=True)
        destination = generations / key
        if destination.exists() or destination.is_symlink():
            canonical(destination)
            receipt = json.loads(read(destination / 'receipt.json', MAX_TEXT))
            require(type(receipt) is dict and set(receipt) == {'formatVersion', 'scope', 'generation', 'inputs',
                    'outputs', 'graphicsQualified', 'androidQualified', 'gameplayQualified'} and
                    type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1 and
                    receipt['scope'] == 'local-generated-shaders-not-render-qualified' and
                    all(receipt[name] is False for name in ('graphicsQualified', 'androidQualified', 'gameplayQualified')) and
                    receipt.get('inputs') == inputs and receipt.get('generation') == key and
                    receipt.get('outputs') == validate_output(destination / 'shaders'), 'prepared shader generation changed')
        else:
            staging = canonical(store / 'staging', create=True) / (key + '-' + uuid.uuid4().hex)
            staging.mkdir(mode=0o700)
            shaders = staging / 'shaders'
            shaders.mkdir(mode=0o700)
            execute([sys.executable, '-B', '-s', '-E', str(tools / 'translate_shaders.py'),
                     '--strict', '--client', str(game / 'generations' / generation / 'data'),
                     '--locale', locale, '--glslang', str(tools / 'bin/glslangValidator'),
                     '--out', str(shaders)], staging / 'setup.log', timeout)
            outputs = validate_output(shaders)
            require(imported(game, generation) == inputs['importMetadata'] and
                    tool_identity(tools, revision) == inputs['toolManifestSha256'], 'inputs changed during shader setup')
            receipt = {'formatVersion': 1, 'scope': 'local-generated-shaders-not-render-qualified',
                       'generation': key, 'inputs': inputs, 'outputs': outputs,
                       'graphicsQualified': False, 'androidQualified': False, 'gameplayQualified': False}
            # Ensure every generated file reaches storage before the completion/pointer commit.
            for name in outputs:
                with (shaders / name).open('rb') as source:
                    os.fsync(source.fileno())
            for folder in ('vertex', 'pixel'):
                sync(shaders / folder)
            sync(shaders)
            atomic(staging / 'receipt.json', encoded(receipt))
            os.rename(staging, destination)
            sync(generations)
        require(imported(game, generation) == inputs['importMetadata'], 'import changed before shader activation')
        atomic(store / 'current', (key + '\n').encode())
        return receipt
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store', 'game', 'tools'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--client-revision', required=True)
    parser.add_argument('--locale', required=True)
    args = parser.parse_args()
    try:
        receipt = generate(args.store, args.game, args.generation, args.tools, args.client_revision, args.locale)
        print('Shader generation prepared: ' + receipt['generation'] + '; rendering remains unqualified')
        return 0
    except (OSError, ValueError) as error:
        print('Shader generation failed (' + type(error).__name__ + '); previous output preserved', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
