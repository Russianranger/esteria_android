#!/usr/bin/env python3
"""Create separately identified server ELF derivatives without changing loaded bytes.

This layer does not package or execute a server. Its caller must verify the original
build/source inventory before selecting inputs. Debug files remain paired outputs.
"""
from __future__ import annotations

import hashlib
import json
import mmap
import os
from pathlib import Path
import selectors
import struct
import subprocess
import time
import zlib
import zipfile

from tools import owned_process_group, verify_server_build as files

require = files.require
BLOCK = 128 * 1024
MAX_SECTIONS = 65535
MAX_STRINGS = 16 * 1024**2
MAX_SYMBOL_NAME = 64 * 1024
DEBUG_COMPANION_SECTIONS = {'.note.gnu.build-id', '.gdb_index', '.gnu_debugaltlink'}
NDK_TOOL = 'android-ndk-r28c/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-objcopy'
TOOL_LOCK = Path(__file__).resolve().parents[1] / 'runtime/server/engine-strip.lock.json'


def command(arguments, timeout=300):
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
        env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C', 'LANG': 'C'})
    owner = owned_process_group.OwnedGroup(process)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    deadline, output = time.monotonic() + timeout, bytearray()
    try:
        while selector.get_map():
            require(time.monotonic() < deadline, 'objcopy-timeout')
            for key, _ in selector.select(.1):
                chunk = os.read(key.fd, BLOCK)
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                require(len(output) + len(chunk) <= 64 * 1024, 'objcopy-output-limit')
                output.extend(chunk)
        require(owner.wait(max(.01, deadline - time.monotonic())) == 0, 'objcopy-failed')
        return output.decode('utf-8', errors='strict')
    finally:
        selector.close()
        process.stdout.close()
        owner.stop(graceful_timeout=0)


def verify_tool(archive, executable, ndk_pin):
    """Bind the exact executable to the previously pinned, independently hashed ZIP."""
    with files.plain_file(TOOL_LOCK) as source:
        raw = source.read(16385)
    require(len(raw) <= 16384, 'server-strip-tool-lock-size')
    locked = json.loads(raw)
    require(type(locked.get('formatVersion')) is int and locked['formatVersion'] == 1 and
            locked.get('scope') == 'server-engine-debug-separation-tool-only' and
            locked.get('host') == 'linux-x86_64' and locked.get('target') == 'linux-aarch64' and
            locked.get('executable', {}).get('archivePath') == NDK_TOOL and
            all(ndk_pin.get(key) == locked['ndkArchive'].get(key) for key in ('bytes', 'sha256')),
            'server-strip-tool-lock-mismatch')
    require(files.identity(archive) == {key: ndk_pin[key] for key in ('bytes', 'sha256')},
            'server-strip-ndk-archive-mismatch')
    # This exact, fully hashed upstream NDK ZIP contains legitimate tool symlinks.
    # Read only the single original regular tool; never extract archive paths.
    with files.plain_file(archive) as stream, zipfile.ZipFile(stream) as package:
        require(len(package.infolist()) <= 100000 and
                sum(item.filename == NDK_TOOL for item in package.infolist()) == 1,
                'server-strip-tool-archive-inventory')
        item = package.getinfo(NDK_TOOL)
        require(0 < item.file_size <= 32 * 1024**2, 'server-strip-tool-size-limit')
        with package.open(item) as source:
            pin = dict(bytes=item.file_size, sha256=hashlib.file_digest(source, 'sha256').hexdigest())
    require(files.identity(executable) == pin, 'server-strip-tool-bytes-mismatch')
    require(pin == {key: locked['executable'][key] for key in ('bytes', 'sha256')},
            'server-strip-executable-lock-mismatch')
    version = command([str(executable), '--version'], timeout=10)
    require('LLVM version 19.0.1' in version and 'llvm-objcopy' in version, 'server-strip-tool-version-mismatch')
    return dict(ndkArchive={key: ndk_pin[key] for key in ('bytes', 'sha256')},
                executable=pin, version=version.strip(),
                toolLockSha256=hashlib.sha256(raw).hexdigest())


def region(stream, offset, size, *, normalize_header=False):
    stream.seek(offset)
    result = hashlib.sha256()
    remaining = size
    position = offset
    while remaining:
        block = bytearray(stream.read(min(BLOCK, remaining)))
        require(block, 'elf-region-short-read')
        if normalize_header:
            # objcopy may move the section table. These fields are not consumed
            # by the ELF loader. All entry, machine and program-table fields stay.
            for first, last in ((40, 48), (58, 64)):
                a, b = max(first, position), min(last, position + len(block))
                if a < b:
                    block[a-position:b-position] = bytes(b-a)
        result.update(block)
        position += len(block)
        remaining -= len(block)
    return result.hexdigest()


def inspect(path, *, debug=False):
    with files.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        require(64 <= size <= files.MAX_FILE, 'server-elf-size-limit')
        header = stream.read(64)
        require(header[:7] == b'\x7fELF\x02\x01\x01', 'server-elf64-le-required')
        kind, machine, version = struct.unpack_from('<HHI', header, 16)
        require(kind in (2, 3) and machine == 183 and version == 1, 'server-aarch64-executable-required')
        phoff, shoff = struct.unpack_from('<QQ', header, 32)
        ehsize, phsize, phcount, shsize, shcount, shstrings = struct.unpack_from('<HHHHHH', header, 52)
        require(ehsize == 64 and phsize == 56 and 0 < phcount <= 8192 and
                64 <= phoff <= size and phcount * phsize <= size - phoff, 'server-program-table-invalid')
        require(shsize == 64 and 0 < shcount <= MAX_SECTIONS and shstrings < shcount and
                64 <= shoff <= size and shcount * shsize <= size - shoff, 'server-section-table-invalid')
        stream.seek(phoff)
        program = stream.read(phcount * phsize)
        segments, interpreter = [], None
        for offset in range(0, len(program), phsize):
            typ, flags, start, va, pa, count, memory, alignment = struct.unpack_from('<IIQQQQQQ', program, offset)
            require(start <= size and count <= size-start, 'server-segment-bounds')
            if typ == 1:
                require(count <= memory, 'server-load-size-invalid')
            if typ == 3 and not debug:
                require(interpreter is None and count <= 4096, 'server-interpreter-invalid')
                stream.seek(start); interpreter = stream.read(count)
                require(interpreter == b'/lib/ld-linux-aarch64.so.1\0', 'server-interpreter-mismatch')
            segments.append(dict(type=typ, flags=flags, offset=start, virtualAddress=va,
                physicalAddress=pa, bytes=count, memoryBytes=memory, alignment=alignment,
                sha256=region(stream, start, count, normalize_header=True)))
        require(any(row['type'] == 1 for row in segments), 'server-load-segment-missing')
        require(debug or interpreter is not None, 'server-interpreter-missing')
        stream.seek(shoff)
        entries = [struct.unpack('<IIQQQQIIQQ', stream.read(64)) for _ in range(shcount)]
        names = entries[shstrings]
        require(names[1] == 3 and names[5] <= MAX_STRINGS and names[4] <= size and
                names[5] <= size-names[4], 'server-section-names-invalid')
        stream.seek(names[4]); strings = stream.read(names[5])
        sections, section_names = {}, []
        for entry in entries:
            name, typ, flags, address, start, count, link, info, alignment, width = entry
            require(name < len(strings), 'server-section-name-offset')
            end = strings.find(b'\0', name)
            require(end >= name and end-name <= 4096, 'server-section-name-invalid')
            label = strings[name:end].decode('ascii', errors='strict')
            section_names.append(label)
            require(label not in sections, 'server-section-name-duplicate')
            require(typ == 8 or (start <= size and count <= size-start), 'server-section-bounds')
            sections[label] = dict(type=typ, flags=flags, address=address, bytes=count,
                sha256=None if typ == 8 else region(stream, start, count), offset=start)
        symbol_hash = None
        if '.symtab' in sections:
            sym = entries[section_names.index('.symtab')]
            require(sym[9] == 24 and sym[5] % 24 == 0 and sym[5] <= 512 * 1024**2 and
                    sym[6] < len(entries), 'server-symbol-table-invalid')
            strings_row = entries[sym[6]]
            require(strings_row[1] == 3 and strings_row[5] <= 128 * 1024**2,
                    'server-symbol-strings-invalid')
            symbols = hashlib.sha256()
            with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                for offset in range(sym[4], sym[4] + sym[5], 24):
                    name, info, other, index, value, count = struct.unpack_from('<IBBHQQ', mapped, offset)
                    require(name < strings_row[5], 'server-symbol-name-offset')
                    start = strings_row[4] + name
                    end = mapped.find(b'\0', start, min(start + MAX_SYMBOL_NAME + 1, strings_row[4] + strings_row[5]))
                    require(end >= start, 'server-symbol-name-invalid')
                    label = ('special:' + str(index)) if index >= 0xff00 else section_names[index] if index < len(section_names) else None
                    require(label is not None, 'server-symbol-section-invalid')
                    # String-table offsets and section indices may be rewritten;
                    # names, target section, binding/type, visibility and values
                    # must remain identical for every symbol in original order.
                    symbols.update(mapped[start:end] + b'\0' + label.encode('ascii') + b'\0')
                    symbols.update(struct.pack('<BBQQ', info, other, value, count))
            symbol_hash = symbols.hexdigest()
        normalized = bytearray(header)
        normalized[40:48] = bytes(8); normalized[58:64] = bytes(6)
        return dict(headerSha256=hashlib.sha256(normalized).hexdigest(),
                    programTableSha256=hashlib.sha256(program).hexdigest(),
                    segments=segments, sections=sections, symbolTableSha256=symbol_hash)


def verify_pair(original, stripped, debug_file):
    before, after, debug = inspect(original), inspect(stripped), inspect(debug_file, debug=True)
    for key in ('headerSha256', 'programTableSha256', 'segments'):
        require(before[key] == after[key], 'server-loaded-bytes-changed:' + key)
    for name, row in before['sections'].items():
        if row['flags'] & 2:  # SHF_ALLOC: preserve every runtime section as well.
            actual = after['sections'].get(name)
            require(actual is not None and row == actual, 'server-allocated-section-changed')
    required = {name for name in before['sections'] if name.startswith(('.debug', '.zdebug'))}
    require(required and '.symtab' in before['sections'], 'original-server-debug-information-missing')
    for name in required | (DEBUG_COMPANION_SECTIONS & set(before['sections'])):
        row, actual = before['sections'].get(name), debug['sections'].get(name)
        require(row is not None and actual is not None and all(row[key] == actual[key]
                for key in ('type', 'flags', 'bytes', 'sha256')), 'server-debug-section-changed')
    require(before['symbolTableSha256'] == debug['symbolTableSha256'], 'server-debug-symbols-changed')
    require(not any(name.startswith(('.debug', '.zdebug')) for name in after['sections']),
            'server-debug-sections-not-stripped')
    link = after['sections'].get('.gnu_debuglink')
    require(link is not None and link['bytes'] <= 512, 'server-debuglink-missing')
    with files.plain_file(debug_file) as source:
        checksum = 0
        while block := source.read(BLOCK):
            checksum = zlib.crc32(block, checksum)
    name = debug_file.name.encode('ascii') + b'\0'
    expected = name + bytes((-len(name)) % 4) + struct.pack('<I', checksum)
    require(link['bytes'] == len(expected) and link['sha256'] == hashlib.sha256(expected).hexdigest(),
            'server-debuglink-identity-mismatch')
    return dict(original=files.identity(original), stripped=files.identity(stripped),
                debug=files.identity(debug_file), loadedSegments=after['segments'],
                runtimeBytesPreserved=True, debugSectionsPreserved=sorted(required),
                debugLinkVerified=True, serverExecuted=False)


def derive(original, stripped, debug_file, objcopy, tool_proof):
    require(not os.path.lexists(stripped) and not os.path.lexists(debug_file), 'existing-derivative-preserved')
    require(stripped.parent.resolve() == stripped.parent.absolute() and
            debug_file.parent.resolve() == debug_file.parent.absolute(), 'derivative-parent-is-not-canonical')
    require(files.identity(objcopy) == tool_proof['executable'], 'server-strip-tool-changed')
    expected = files.identity(original)
    inspect(original)
    command([str(objcopy), '--only-keep-debug', str(original), str(debug_file)])
    command([str(objcopy), '--strip-unneeded', '--add-gnu-debuglink=' + str(debug_file), str(original), str(stripped)])
    require(files.identity(original) == expected, 'original-server-changed-during-strip')
    result = verify_pair(original, stripped, debug_file)
    require(result['stripped']['bytes'] < result['original']['bytes'], 'server-strip-did-not-reduce-size')
    stripped.chmod(0o555); debug_file.chmod(0o444)
    for path in (stripped, debug_file):
        with files.plain_file(path) as stream:
            os.fsync(stream.fileno())
    return result
