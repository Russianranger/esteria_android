#!/usr/bin/env python3
"""Export/apply a public APK v2/v3 block, zero alignment and EOCD offset.

No key is read and no APK is signed here. The only non-block insertion is up to
4095 verified zero alignment bytes emitted by apksigner. Export requires byte-identical ZIP
prefixes and central directories. Apply reconstructs the exact already-signed
SHA-256 using a bounded public recipe; callers must independently use apksigner
and the pinned certificate before publication. ZIP64 and v1 signing are outside
this deliberately narrow transport format.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import struct
import tempfile

try:
    from . import sign_android_apk as signing
except ImportError:
    import sign_android_apk as signing

require = signing.require
SCOPE = 'public-apk-v2-v3-signature-block-only'
MAGIC = b'APK Sig Block 42'
MAX_APK = 2 << 30
MAX_BLOCK = 4 << 20
MAX_RECIPE = 6 << 20
MAX_DIRECTORY = 32 << 20
V2 = 0x7109871a
V3 = 0xf05368c0
V31 = 0x1b93ad61
PADDING = 0x42726577
ALLOWED_IDS = frozenset((V2, V3, V31, PADDING))


@dataclass(frozen=True)
class Layout:
    size: int
    directory_offset: int
    directory_bytes: int
    entries: int
    eocd: bytes
    block_offset: int | None
    block: bytes | None


def identity(path):
    path = signing.plain(path)
    size = path.stat().st_size
    require(22 <= size <= MAX_APK, 'apk-size-limit')
    return dict(bytes=size, sha256=signing.digest(path))


def block_ids(block):
    require(type(block) is bytes and 32 <= len(block) <= MAX_BLOCK, 'signature-block-size')
    require(block[-16:] == MAGIC, 'signature-block-magic')
    size = struct.unpack_from('<Q', block)[0]
    require(size == len(block) - 8 and struct.unpack_from('<Q', block, len(block) - 24)[0] == size,
            'signature-block-size-pair')
    end = len(block) - 24
    position = 8
    ids = []
    while position < end:
        require(position + 12 <= end, 'signature-block-record-header')
        length, identifier = struct.unpack_from('<QI', block, position)
        require(4 <= length <= MAX_BLOCK and position + 8 + length <= end, 'signature-block-record-size')
        require(identifier in ALLOWED_IDS and identifier not in ids, 'signature-block-record-id')
        ids.append(identifier)
        position += 8 + length
    require(position == end and V2 in ids and V3 in ids, 'both-v2-v3-blocks-required')
    return ['0x%08x' % item for item in ids]


def layout(path):
    path = signing.plain(path)
    size = path.stat().st_size
    require(22 <= size <= MAX_APK, 'apk-size-limit')
    with path.open('rb') as stream:
        count = min(size, 65557)
        stream.seek(size - count)
        tail = stream.read(count)
        positions = []
        start = 0
        while True:
            at = tail.find(b'PK\x05\x06', start)
            if at < 0:
                break
            if at + 22 <= len(tail) and at + 22 + struct.unpack_from('<H', tail, at + 20)[0] == len(tail):
                positions.append(at)
            start = at + 1
        require(len(positions) == 1, 'one-terminal-eocd-required')
        at = positions[0]
        eocd = tail[at:]
        _, disk, directory_disk, disk_entries, entries, directory_bytes, directory_offset, _ = struct.unpack_from('<4s4H2IH', eocd)
        require(disk == directory_disk == 0 and disk_entries == entries and 0 < entries < 65535,
                'single-disk-nonzip64-apk-required')
        require(0 < directory_bytes <= MAX_DIRECTORY and directory_offset > 0 and
                directory_offset + directory_bytes == size - count + at,
                'central-directory-bounds')
        stream.seek(directory_offset)
        require(stream.read(4) == b'PK\x01\x02', 'central-directory-header')
        block = None
        block_offset = None
        if directory_offset >= 24:
            stream.seek(directory_offset - 24)
            footer = stream.read(24)
            if footer[-16:] == MAGIC:
                block_bytes = struct.unpack_from('<Q', footer)[0] + 8
                require(32 <= block_bytes <= MAX_BLOCK and block_bytes <= directory_offset,
                        'signature-block-bounds')
                block_offset = directory_offset - block_bytes
                stream.seek(block_offset)
                block = stream.read(block_bytes)
                block_ids(block)
        return Layout(size, directory_offset, directory_bytes, entries, eocd, block_offset, block)


def compare_region(left, left_offset, right, right_offset, count, reason):
    with left.open('rb') as source, right.open('rb') as other:
        source.seek(left_offset)
        other.seek(right_offset)
        while count:
            length = min(count, 256 << 10)
            chunk = source.read(length)
            require(len(chunk) == length and other.read(length) == chunk, reason)
            count -= length


def checked_output(path):
    path = Path(os.path.abspath(path))
    require(not os.path.lexists(path), 'output-already-exists')
    require(path.parent.is_dir(), 'output-parent-required')
    for part in (path.parent, *path.parent.parents):
        require(not part.is_symlink(), 'symlink-output-parent')
    return path


def publish_temporary(temporary, output):
    # The final exclusive hardlink is an atomic no-replace operation. Only the
    # private temporary name is removed on failure, never a competing output.
    os.link(temporary, output)
    descriptor = os.open(output.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_new(output, data):
    output = checked_output(output)
    with tempfile.NamedTemporaryFile(prefix='.public-apk-signature-', dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            publish_temporary(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)


def export(unsigned, signed, output):
    output = checked_output(output)
    unsigned, signed = signing.plain(unsigned), signing.plain(signed)
    original, completed = layout(unsigned), layout(signed)
    require(original.block is None, 'input-apk-must-be-unsigned')
    require(completed.block is not None, 'signed-apk-v2-v3-block-required')
    padding = completed.block_offset - original.directory_offset
    require(0 <= padding < 4096 and (padding == 0 or completed.block_offset % 4096 == 0),
            'signed-prefix-alignment-changed')
    with signed.open('rb') as stream:
        stream.seek(original.directory_offset)
        require(stream.read(padding) == b'\0' * padding, 'signed-alignment-padding-not-zero')
    require(completed.directory_bytes == original.directory_bytes and completed.entries == original.entries,
            'signed-central-directory-layout-changed')
    compare_region(unsigned, 0, signed, 0, original.directory_offset, 'signed-prefix-bytes-changed')
    compare_region(unsigned, original.directory_offset, signed, completed.directory_offset,
                   original.directory_bytes, 'signed-central-directory-bytes-changed')
    eocd = original.eocd[:16] + struct.pack('<I', completed.directory_offset) + original.eocd[20:]
    require(completed.eocd == eocd and completed.size == original.size + padding + len(completed.block),
            'only-eocd-directory-offset-may-change')
    first, final = identity(unsigned), identity(signed)
    recipe = dict(formatVersion=1, scope=SCOPE, unsigned=first, signed=final,
        signingBlockBase64=base64.b64encode(completed.block).decode('ascii'),
        signingBlockIds=block_ids(completed.block), alignmentPaddingBytes=padding,
        unsignedCentralDirectoryOffset=original.directory_offset,
        centralDirectoryBytes=original.directory_bytes,
        eocdPatch=dict(relativeOffset=16, unsignedCentralDirectoryOffset=original.directory_offset,
                       signedCentralDirectoryOffset=completed.directory_offset))
    # Refuse an input modified during the comparison/hashing window.
    require(identity(unsigned) == first and identity(signed) == final, 'apk-changed-during-export')
    write_new(output, (json.dumps(recipe, sort_keys=True, indent=2) + '\n').encode())
    return recipe


def _unique(rows):
    result = {}
    for key, value in rows:
        require(key not in result, 'duplicate-recipe-field')
        result[key] = value
    return result


def read_recipe(path):
    path = signing.plain(path)
    require(path.stat().st_size <= MAX_RECIPE, 'public-recipe-size-limit')
    value = json.loads(path.read_bytes(), object_pairs_hook=_unique)
    fields = {'formatVersion', 'scope', 'unsigned', 'signed', 'signingBlockBase64', 'signingBlockIds',
              'unsignedCentralDirectoryOffset', 'centralDirectoryBytes', 'alignmentPaddingBytes', 'eocdPatch'}
    require(type(value) is dict and set(value) == fields and type(value['formatVersion']) is int and
            value['formatVersion'] == 1 and value['scope'] == SCOPE, 'public-recipe-schema')
    for name in ('unsigned', 'signed'):
        pin = value[name]
        require(type(pin) is dict and set(pin) == {'bytes', 'sha256'} and type(pin['bytes']) is int and
                22 <= pin['bytes'] <= MAX_APK and type(pin['sha256']) is str and
                re.fullmatch('[0-9a-f]{64}', pin['sha256']), 'public-recipe-apk-pin')
    require(type(value['signingBlockBase64']) is str and len(value['signingBlockBase64']) <= (MAX_BLOCK * 4 // 3 + 4),
            'public-recipe-block-bound')
    try:
        block = base64.b64decode(value['signingBlockBase64'], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('public-recipe-block-encoding') from None
    require(base64.b64encode(block).decode('ascii') == value['signingBlockBase64'] and
            value['signingBlockIds'] == block_ids(block), 'public-recipe-block-identity')
    for name in ('unsignedCentralDirectoryOffset', 'centralDirectoryBytes'):
        require(type(value[name]) is int and 0 < value[name] < MAX_APK, 'public-recipe-directory-field')
    padding = value['alignmentPaddingBytes']
    require(type(padding) is int and 0 <= padding < 4096 and
            (padding == 0 or (value['unsignedCentralDirectoryOffset'] + padding) % 4096 == 0),
            'public-recipe-alignment-padding')
    patch = value['eocdPatch']
    require(type(patch) is dict and set(patch) == {'relativeOffset', 'unsignedCentralDirectoryOffset', 'signedCentralDirectoryOffset'} and
            all(type(item) is int for item in patch.values()) and patch['relativeOffset'] == 16 and
            patch['unsignedCentralDirectoryOffset'] == value['unsignedCentralDirectoryOffset'] and
            patch['signedCentralDirectoryOffset'] == value['unsignedCentralDirectoryOffset'] + padding + len(block) and
            value['signed']['bytes'] == value['unsigned']['bytes'] + padding + len(block), 'public-recipe-eocd-patch')
    return value, block


def _copy(source, destination, count):
    while count:
        chunk = source.read(min(count, 256 << 10))
        require(chunk, 'unsigned-apk-truncated-during-copy')
        destination.write(chunk)
        count -= len(chunk)


def apply(unsigned, recipe_path, output):
    output = checked_output(output)
    unsigned = signing.plain(unsigned)
    recipe, block = read_recipe(recipe_path)
    require(identity(unsigned) == recipe['unsigned'], 'unsigned-apk-identity-mismatch')
    original = layout(unsigned)
    require(original.block is None and original.directory_offset == recipe['unsignedCentralDirectoryOffset'] and
            original.directory_bytes == recipe['centralDirectoryBytes'], 'unsigned-apk-layout-mismatch')
    eocd = original.eocd[:16] + struct.pack('<I', recipe['eocdPatch']['signedCentralDirectoryOffset']) + original.eocd[20:]
    with tempfile.NamedTemporaryFile(prefix='.public-apk-signature-', dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with unsigned.open('rb') as source:
                _copy(source, stream, original.directory_offset)
                stream.write(b'\0' * recipe['alignmentPaddingBytes'])
                stream.write(block)
                _copy(source, stream, original.directory_bytes)
                stream.write(eocd)
            stream.flush()
            os.fsync(stream.fileno())
            require(identity(temporary) == recipe['signed'], 'reconstructed-signed-apk-identity-mismatch')
            require(identity(unsigned) == recipe['unsigned'], 'unsigned-apk-changed-during-copy')
            publish_temporary(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return dict(unsigned=recipe['unsigned'], signed=recipe['signed'], publicSignatureBlockBytes=len(block),
                alignmentPaddingBytes=recipe['alignmentPaddingBytes'],
                exactPreviouslySignedBytesReconstructed=True, cryptographicSignatureVerifiedHere=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('export', 'apply'))
    parser.add_argument('--unsigned', type=Path, required=True)
    parser.add_argument('--signed', type=Path)
    parser.add_argument('--recipe', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == 'export':
            require(args.signed is not None and args.recipe is None, 'signed-apk-required-for-export')
            result = export(args.unsigned, args.signed, args.output)
            result = dict(unsigned=result['unsigned'], signed=result['signed'], publicRecipeBytes=args.output.stat().st_size,
                          publicRecipeSha256=signing.digest(args.output))
        else:
            require(args.recipe is not None and args.signed is None, 'public-recipe-required-for-apply')
            result = apply(args.unsigned, args.recipe, args.output)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, struct.error) as error:
        reason = str(error) if type(error) is ValueError and re.fullmatch('[a-z0-9-]+', str(error)) else 'public-apk-signature-validation-failed'
        parser.exit(1, reason + '\n')


if __name__ == '__main__':
    main()
