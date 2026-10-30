#!/usr/bin/env python3
"""Bounded ELF64 validation for Android ARM64 process payloads, not JNI libraries."""
import struct


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def inspect(data, *, loader=False):
    require(64 <= len(data) <= 16 * 1024 * 1024 and data[:7] == b'\x7fELF\x02\x01\x01', 'invalid-elf64')
    kind, machine, version, entry, phoff = struct.unpack_from('<HHIQQ', data, 16)
    ehsize, phsize, count = struct.unpack_from('<HHH', data, 52)
    require((kind, machine, version, ehsize, phsize) == (2 if loader else 3, 183, 1, 64, 56), 'wrong-elf-target-type')
    require(1 <= count <= 32 and 64 <= phoff and phoff + count * phsize <= len(data), 'invalid-elf-program-headers')
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize) for i in range(count)]
    loads = []; executable = False; stacks = []; dynamic = []; interpreters = []
    for typ, flags, offset, virtual, physical, filesz, memsz, alignment in segments:
        require(offset <= len(data) and filesz <= len(data) - offset, 'elf-segment-outside-file')
        if typ == 1:
            require(filesz <= memsz and alignment >= 16384 and alignment & (alignment - 1) == 0 and
                    virtual % alignment == offset % alignment, 'invalid-load-alignment')
            require(flags & 3 != 3, 'writable-executable-segment')
            loads.append((offset, virtual, filesz, alignment))
            executable |= bool(flags & 1 and virtual <= entry < virtual + filesz)
        elif typ == 2:
            require(filesz <= 65536 and filesz % 16 == 0, 'invalid-dynamic-table')
            dynamic.append((offset, filesz))
        elif typ == 3:
            require(1 <= filesz <= 256 and data[offset + filesz - 1] == 0, 'invalid-interpreter')
            interpreters.append(data[offset:offset + filesz - 1].decode('ascii'))
        elif typ == 0x6474e551:
            stacks.append(flags)
    require(loads and executable and len(stacks) == 1 and not stacks[0] & 1, 'invalid-entry-or-stack')
    needed = []
    if loader:
        require(not interpreters and not dynamic, 'loader-has-dynamic-linkage')
    else:
        require(interpreters == ['/system/bin/linker64'] and len(dynamic) == 1, 'not-android-pie')
        offset, size = dynamic[0]
        tags = {}
        ended = False
        for pos in range(offset, offset + size, 16):
            tag, value = struct.unpack_from('<qQ', data, pos)
            if tag == 0:
                ended = True
                break
            tags.setdefault(tag, []).append(value)
        require(ended and not any(t in tags for t in (14, 15, 29)), 'dynamic-soname-or-search-path')
        require(len(tags.get(5, [])) == 1 and len(tags.get(10, [])) == 1, 'missing-dynamic-strings')
        addr, length = tags[5][0], tags[10][0]
        require(0 < length <= 1024 * 1024, 'dynamic-strings-limit')
        mapping = [(off + addr - virt) for off, virt, fsize, align in loads if virt <= addr and addr + length <= virt + fsize]
        require(len(mapping) == 1, 'dynamic-strings-not-file-backed')
        strings = data[mapping[0]:mapping[0] + length]
        for index in tags.get(1, []):
            require(index < length, 'invalid-needed-index')
            end = strings.find(b'\0', index)
            require(end > index, 'invalid-needed-string')
            needed.append(strings[index:end].decode('ascii'))
        require(sorted(needed) == ['libc.so', 'libdl.so'], 'unexpected-android-dependency')
    return dict(type='EXEC' if loader else 'DYN', machine='AArch64',
                interpreter=None if loader else interpreters[0], needed=needed,
                minimumLoadAlignment=min(x[3] for x in loads), executableStack=False)
