#!/usr/bin/env python3
"""Export/apply a public APK v2/v3 block, zero alignment and EOCD offset.

No key is read and no APK is signed here. Transport preserves ZIP payload and
metadata bytes except canonical SDK 0xd935/alignment4 local fields, their derived
central-directory offsets, up to4095 zero alignment bytes, the public signing
block and the EOCD offset. Recipes cannot supply arbitrary ZIP replacement data.
Apply reconstructs the exact already-signed SHA-256; callers independently use
apksigner and the pinned certificate before publication. ZIP64 and v1 signing
are outside this deliberately narrow transport format.
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
import zipfile

try:
    from . import sign_android_apk as signing
except ImportError:
    import sign_android_apk as signing

require = signing.require
SCOPE = 'public-apk-v2-v3-signature-block-only'
ALIGNMENT_SCOPE = 'public-apk-v2-v3-signature-and-zip-alignment-only'
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


def _local_header(stream, info):
    stream.seek(info.header_offset)
    header = stream.read(30)
    require(len(header) == 30 and header[:4] == b'PK\x03\x04', 'alignment-local-header')
    names, extras = struct.unpack_from('<HH', header, 26)
    name, extra = stream.read(names), stream.read(extras)
    require(len(name) == names and len(extra) == extras, 'alignment-local-header-bound')
    return header, name, extra


def alignment_entries(unsigned, signed):
    """Identify only local extra fields rewritten by the Android SDK signer."""
    with zipfile.ZipFile(unsigned) as old, zipfile.ZipFile(signed) as new, unsigned.open('rb') as source, signed.open('rb') as target:
        before, after = old.infolist(), new.infolist()
        require(0 < len(before) <= 8192 and [row.filename for row in before] == [row.filename for row in after],
                'signed-zip-entry-order-changed')
        names = []
        for left, right in zip(before, after):
            _, _, original = _local_header(source, left)
            _, _, completed = _local_header(target, right)
            if original != completed:
                names.append(left.filename)
        return names


def alignment_plan(unsigned, original, names):
    """Derive canonical 0xd935/alignment4 fields and CD offsets from the input.

    A recipe supplies entry names only. It cannot supply arbitrary replacement
    bytes, sizes, offsets or payload data. Existing zero padding (0--3 bytes) may
    become the SDK's canonical alignment field. Every other source prefix byte
    and every other central-directory byte is preserved exactly.
    """
    require(type(names) is list and 0 < len(names) <= 1024 and
            all(type(name) is str and 0 < len(name) <= 1024 for name in names) and len(set(names)) == len(names), 'zip-alignment-entry-selection')
    wanted = set(names)
    patches, observed, delta = [], [], 0
    with zipfile.ZipFile(unsigned) as archive, unsigned.open('rb') as source:
        rows = archive.infolist()
        require(len(rows) == original.entries and len(rows) <= 8192 and
                len({row.filename for row in rows}) == len(rows), 'zip-alignment-input-entry-set')
        source.seek(original.directory_offset)
        directory = bytearray(source.read(original.directory_bytes))
        position = 0
        previous_end = 0
        for info in rows:
            header, name, extra = _local_header(source, info)
            require(info.header_offset >= previous_end and info.header_offset < original.directory_offset and
                    position + 46 <= len(directory) and directory[position:position + 4] == b'PK\x01\x02',
                    'zip-alignment-entry-order')
            name_bytes, extra_bytes, comment_bytes = struct.unpack_from('<HHH', directory, position + 28)
            end = position + 46 + name_bytes + extra_bytes + comment_bytes
            require(end <= len(directory) and directory[position + 46:position + 46 + name_bytes] == name and
                    struct.unpack_from('<I', directory, position + 42)[0] == info.header_offset,
                    'zip-alignment-central-directory')
            new_offset = info.header_offset + delta
            struct.pack_into('<I', directory, position + 42, new_offset)
            if info.filename in wanted:
                require(info.compress_type == 0 and len(extra) <= 3 and not any(extra),
                        'zip-alignment-only-stored-zero-padding')
                # Android's 0xd935 extra record: tag, record length, alignment=4,
                # then only enough zero bytes to align the following data.
                extra_count = 6 + (-(new_offset + 30 + len(name) + 6) % 4)
                replacement = struct.pack('<HHH', 0xd935, extra_count - 4, 4) + b'\0' * (extra_count - 6)
                patches.extend(((info.header_offset + 28, 2, struct.pack('<H', extra_count)),
                                (info.header_offset + 30 + len(name), len(extra), replacement)))
                delta += extra_count - len(extra)
                observed.append(info.filename)
            previous_end = info.header_offset + 30 + len(name) + len(extra) + info.compress_size
            require(previous_end <= original.directory_offset, 'zip-alignment-payload-bounds')
            position = end
        require(position == len(directory) and observed == names, 'zip-alignment-unknown-or-reordered-entry')
    return patches, bytes(directory), delta


def transfer_prefix(source, target, patches, end, *, compare=False):
    source.seek(0)
    position = 0
    for offset, old_count, replacement in (*patches, (end, 0, b'')):
        require(position <= offset <= end and offset + old_count <= end, 'zip-alignment-patch-bounds')
        remaining = offset - position
        while remaining:
            chunk = source.read(min(remaining, 256 << 10))
            require(chunk, 'unsigned-apk-truncated-during-copy')
            if compare:
                require(target.read(len(chunk)) == chunk, 'signed-prefix-bytes-changed')
            else:
                target.write(chunk)
            remaining -= len(chunk)
        source.seek(old_count, 1)
        if compare:
            require(target.read(len(replacement)) == replacement, 'signed-zip-alignment-field-changed')
        else:
            target.write(replacement)
        position = offset + old_count


def export(unsigned, signed, output):
    output = checked_output(output)
    unsigned, signed = signing.plain(unsigned), signing.plain(signed)
    original, completed = layout(unsigned), layout(signed)
    require(original.block is None, 'input-apk-must-be-unsigned')
    require(completed.block is not None, 'signed-apk-v2-v3-block-required')
    names = alignment_entries(unsigned, signed)
    if names:
        patches, directory, delta = alignment_plan(unsigned, original, names)
    else:
        patches, delta = [], 0
        with unsigned.open('rb') as stream:
            stream.seek(original.directory_offset)
            directory = stream.read(original.directory_bytes)
    padding = completed.block_offset - original.directory_offset - delta
    require(0 <= padding < 4096 and (padding == 0 or completed.block_offset % 4096 == 0),
            'signed-prefix-alignment-changed')
    with signed.open('rb') as stream:
        stream.seek(original.directory_offset + delta)
        require(stream.read(padding) == b'\0' * padding, 'signed-alignment-padding-not-zero')
    require(completed.directory_bytes == original.directory_bytes and completed.entries == original.entries,
            'signed-central-directory-layout-changed')
    with unsigned.open('rb') as source, signed.open('rb') as target:
        transfer_prefix(source, target, patches, original.directory_offset, compare=True)
        target.seek(completed.directory_offset)
        require(target.read(completed.directory_bytes) == directory, 'signed-central-directory-bytes-changed')
    eocd = original.eocd[:16] + struct.pack('<I', completed.directory_offset) + original.eocd[20:]
    require(completed.eocd == eocd and completed.size == original.size + delta + padding + len(completed.block),
            'only-eocd-directory-offset-may-change')
    first, final = identity(unsigned), identity(signed)
    recipe = dict(formatVersion=1, scope=SCOPE, unsigned=first, signed=final,
        signingBlockBase64=base64.b64encode(completed.block).decode('ascii'),
        signingBlockIds=block_ids(completed.block), alignmentPaddingBytes=padding,
        unsignedCentralDirectoryOffset=original.directory_offset,
        centralDirectoryBytes=original.directory_bytes,
        eocdPatch=dict(relativeOffset=16, unsignedCentralDirectoryOffset=original.directory_offset,
                       signedCentralDirectoryOffset=completed.directory_offset))
    if names:
        recipe.update(formatVersion=2, scope=ALIGNMENT_SCOPE, zipAlignmentEntries=names)
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
    require(type(value) is dict and type(value.get('formatVersion')) is int and
            ((value['formatVersion'] == 1 and value.get('scope') == SCOPE and set(value) == fields) or
             (value['formatVersion'] == 2 and value.get('scope') == ALIGNMENT_SCOPE and
              set(value) == fields | {'zipAlignmentEntries'})), 'public-recipe-schema')
    if value['formatVersion'] == 2:
        names = value['zipAlignmentEntries']
        require(type(names) is list and 0 < len(names) <= 1024 and
                all(type(name) is str and 0 < len(name) <= 1024 for name in names) and
                len(set(names)) == len(names), 'zip-alignment-entry-selection')
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
    require(type(padding) is int and 0 <= padding < 4096, 'public-recipe-alignment-padding')
    delta = value['signed']['bytes'] - value['unsigned']['bytes'] - padding - len(block)
    require((delta == 0 if value['formatVersion'] == 1 else 0 < delta <= 9 * len(value['zipAlignmentEntries'])),
            'public-recipe-zip-alignment-delta')
    require(padding == 0 or (value['unsignedCentralDirectoryOffset'] + delta + padding) % 4096 == 0,
            'public-recipe-alignment-padding')
    patch = value['eocdPatch']
    require(type(patch) is dict and set(patch) == {'relativeOffset', 'unsignedCentralDirectoryOffset', 'signedCentralDirectoryOffset'} and
            all(type(item) is int for item in patch.values()) and patch['relativeOffset'] == 16 and
            patch['unsignedCentralDirectoryOffset'] == value['unsignedCentralDirectoryOffset'] and
            patch['signedCentralDirectoryOffset'] == value['unsignedCentralDirectoryOffset'] + delta + padding + len(block),
            'public-recipe-eocd-patch')
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
    if recipe['formatVersion'] == 2:
        patches, directory, delta = alignment_plan(unsigned, original, recipe['zipAlignmentEntries'])
    else:
        patches, delta = [], 0
        with unsigned.open('rb') as source:
            source.seek(original.directory_offset)
            directory = source.read(original.directory_bytes)
    require(delta == recipe['signed']['bytes'] - recipe['unsigned']['bytes'] -
            recipe['alignmentPaddingBytes'] - len(block), 'public-recipe-zip-alignment-delta')
    eocd = original.eocd[:16] + struct.pack('<I', recipe['eocdPatch']['signedCentralDirectoryOffset']) + original.eocd[20:]
    with tempfile.NamedTemporaryFile(prefix='.public-apk-signature-', dir=output.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            with unsigned.open('rb') as source:
                transfer_prefix(source, stream, patches, original.directory_offset)
                stream.write(b'\0' * recipe['alignmentPaddingBytes'])
                stream.write(block)
                stream.write(directory)
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
                zipAlignmentEntries=recipe.get('zipAlignmentEntries', []),
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
    except (ValueError, OSError, struct.error, zipfile.BadZipFile) as error:
        reason = str(error) if type(error) is ValueError and re.fullmatch('[a-z0-9-]+', str(error)) else 'public-apk-signature-validation-failed'
        parser.exit(1, reason + '\n')


if __name__ == '__main__':
    main()
