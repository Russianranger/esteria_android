#!/usr/bin/env python3
"""Run the shipped ARM64 map extractor on tiny synthetic MPQs in a long cwd.

This deliberately converts no map tiles, camera models or owner assets. It
exercises the real DBC copy/output-creation path and the production owned-child
executor, including the legacy absolute-output failure and repaired relative
contract. The immutable native provider is never rebuilt or changed.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import struct
import sys

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime import server_data_generation as data, world_io
from tools import provider_server_data_tools as provider, qualify_server_data_tools as native

ROOT = Path(__file__).resolve().parents[1]
SCOPE = 'native-arm64-shipped-map-extractor-long-output-and-synthetic-dbc'
SOURCES = ('runtime/server_data_generation.py', 'runtime/world_io.py',
    'tools/qualify_extractor_output.py', '.github/workflows/native-extractor-output.yml')
FALSE_FLAGS = ('ownerGameDataSupplied', 'mapTilesConverted', 'cameraModelsConverted',
    'androidRuntimeQualified', 'thorQualified', 'gameplayQualified')
require = provider.require
identity = provider.files.identity
MASK = 0xffffffff


def byte_pin(raw):
    return dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


def crypt_table():
    seed = 0x100001
    result = [0] * 0x500
    for index in range(0x100):
        for group in range(5):
            seed = (seed * 125 + 3) % 0x2aaaab
            high = (seed & 0xffff) << 16
            seed = (seed * 125 + 3) % 0x2aaaab
            result[group * 0x100 + index] = high | (seed & 0xffff)
    return result


CRYPT = crypt_table()


def mpq_hash(name, kind):
    seed1, seed2 = 0x7fed7fed, 0xeeeeeeee
    for char in name.replace('/', '\\').upper().encode('ascii'):
        seed1 = (CRYPT[(kind << 8) + char] ^ ((seed1 + seed2) & MASK)) & MASK
        seed2 = (char + seed1 + seed2 + (seed2 << 5) + 3) & MASK
    return seed1


def encrypt_table(raw, key):
    require(len(raw) % 4 == 0, 'fixture-table-word-alignment')
    seed, result = 0xeeeeeeee, bytearray()
    for (plain,) in struct.iter_unpack('<I', raw):
        seed = (seed + CRYPT[0x400 + (key & 0xff)]) & MASK
        result += struct.pack('<I', plain ^ ((key + seed) & MASK))
        key = (((((~key) & MASK) << 21) + 0x11111111) | (key >> 11)) & MASK
        seed = (plain + seed + (seed << 5) + 3) & MASK
    return bytes(result)


def synthetic_mpq(members):
    """Small uncompressed classic MPQ with real encrypted hash/block tables."""
    require(type(members) is dict and len(members) <= 8 and
        all(type(k) is str and type(v) is bytes and len(v) <= 4096 for k, v in members.items()),
        'bounded-synthetic-mpq-members-required')
    entries = dict(members)
    entries['(listfile)'] = ''.join(name + '\r\n' for name in members).encode('ascii')
    slots = 2
    while slots < len(entries) * 2:
        slots *= 2
    hashes = [(MASK, MASK, 0xffff, 0xffff, MASK)] * slots
    blocks, payload = [], bytearray()
    for index, (name, raw) in enumerate(entries.items()):
        location = mpq_hash(name, 0) & (slots - 1)
        while hashes[location][4] != MASK:
            location = (location + 1) & (slots - 1)
        hashes[location] = (mpq_hash(name, 1), mpq_hash(name, 2), 0, 0, index)
        blocks.append((32 + len(payload), len(raw), len(raw), 0x81000000))
        payload += raw
    hash_raw = b''.join(struct.pack('<IIHHI', *row) for row in hashes)
    block_raw = b''.join(struct.pack('<4I', *row) for row in blocks)
    hash_at, block_at = 32 + len(payload), 32 + len(payload) + len(hash_raw)
    header = struct.pack('<8I', 0x1a51504d, 32, block_at + len(block_raw),
        3 << 16, hash_at, block_at, slots, len(blocks))
    return header + payload + encrypt_table(hash_raw, mpq_hash('(hash table)', 3)) + \
        encrypt_table(block_raw, mpq_hash('(block table)', 3))


def fixture_members():
    # Empty geographical tables exercise output directories without inventing a
    # map/camera or claiming coverage. One ordinary WDBC row is copied as well.
    def empty(fields):
        return struct.pack('<4s4I', b'WDBC', 0, fields, fields * 4, 1) + b'\0'
    return {
        'component.wow-enUS.txt': b'<component version="12340"/>\n',
        'DBFilesClient/Map.dbc': empty(2),
        'DBFilesClient/LiquidType.dbc': empty(4),
        'DBFilesClient/CinematicCamera.dbc': empty(2),
        'DBFilesClient/FixtureTable.dbc': struct.pack('<4s5I', b'WDBC', 1, 1, 4, 1, 12340) + b'\0',
    }


def expected_outputs(members=None):
    members = fixture_members() if members is None else members
    return {'dbc/' + name.rsplit('/', 1)[-1]: byte_pin(raw) for name, raw in members.items()}


def expected_inputs():
    return {name: byte_pin(synthetic_mpq(members)) for name, members in (
        ('Data/common.MPQ', fixture_members()), ('Data/enUS/locale-enUS.MPQ', {}),
        ('Data/enUS/speech-enUS.MPQ', {}))}


def output_inventory(path):
    rows = {}
    for p in sorted(path.rglob('*')):
        require(not p.is_symlink(), 'fixture-output-symlink-refused')
        if p.is_file():
            require(p.stat().st_size <= 4096, 'fixture-output-byte-bound')
            rows[p.relative_to(path).as_posix()] = identity(p)
    return rows


def verify_receipt(value, revision):
    pin = provider.load_pin(sealed=True)
    required = {'formatVersion', 'scope', 'appRevision', 'providerInputLock', 'runtimeArchive',
        'shippedMapExtractor', 'sourceIdentities', 'referenceImageReadback', 'fixtureInputs',
        'expectedOutputs', 'cases', 'productionExecuteAndMemoryPolicyUsed', *FALSE_FLAGS}
    require(type(revision) is str and type(value) is dict and set(value) == required and
        type(value['formatVersion']) is int and value['formatVersion'] == 1 and
        value['scope'] == SCOPE and value['appRevision'] == revision and
        re.fullmatch('[0-9a-f]{40}', revision or '') and
        value['providerInputLock'] == identity(provider.LOCK) and
        value['runtimeArchive'] == provider.identity(pin['archive']) and
        value['shippedMapExtractor'] == provider.identity(pin['files']['bin/map_extractor']) and
        value['sourceIdentities'] == {name: identity(ROOT / name) for name in SOURCES} and
        value['productionExecuteAndMemoryPolicyUsed'] is True and
        all(value[k] is False for k in FALSE_FLAGS), 'native-output-exact-source-and-boundary-required')
    native.verify_image_binding(value['referenceImageReadback'], pin)
    require(value['expectedOutputs'] == expected_outputs() and value['fixtureInputs'] == expected_inputs(),
        'native-output-exact-synthetic-inputs-required')
    cases = value['cases']
    require(type(cases) is dict and set(cases) == {'legacyAbsolute', 'relativeFresh', 'relativeExisting'},
        'native-output-three-actual-cases-required')
    old = cases['legacyAbsolute']
    require(type(old) is dict and set(old) == {'exitStatus', 'outputArgumentBytes', 'truncatedArgumentBytes',
        'equivalentMkdirErrno', 'nativeTruncatedPathErrorMatched', 'intendedOutputAbsent', 'log'} and
        type(old.get('exitStatus')) is int and old['exitStatus'] == 1 and
        type(old.get('outputArgumentBytes')) is int and old['outputArgumentBytes'] > 127 and
        old.get('truncatedArgumentBytes') == 127 and old.get('equivalentMkdirErrno') == errno.ENOENT and
        old.get('nativeTruncatedPathErrorMatched') is True and old.get('intendedOutputAbsent') is True,
        'native-output-legacy-truncation-and-missing-parent-required')
    for key in ('relativeFresh', 'relativeExisting'):
        case = cases[key]
        require(type(case) is dict and set(case) == {'exitStatus', 'outputOperand', 'cwdBytes', 'outputs',
            'outputDirectories', 'inputBytesUnchanged', 'misdirectedDirectoryAbsent', 'log'} and
            type(case.get('exitStatus')) is int and case['exitStatus'] == 0 and
            case.get('outputOperand') == '.' and type(case.get('cwdBytes')) is int and case['cwdBytes'] > 127 and
            case.get('outputs') == expected_outputs() and
            case.get('outputDirectories') == ['Cameras', 'dbc', 'maps'] and
            case.get('inputBytesUnchanged') is True and case.get('misdirectedDirectoryAbsent') is True,
            'native-output-genuine-dbc-and-owned-directories-required')
    return value


def verify_result(directory, revision):
    directory = provider.archives.directory(Path(os.path.abspath(directory)))
    require({p.name for p in directory.iterdir()} == {'native-output.json', 'dependency-image-check.json',
        'legacyAbsolute.log', 'relativeFresh.log', 'relativeExisting.log'}, 'native-output-artifact-roster')
    value, _ = provider.engine.modules.read_json(directory / 'native-output.json')
    verify_receipt(value, revision)
    image = native.accept_image_readback(directory / 'dependency-image-check.json',
        value['referenceImageReadback']['identity']['sha256'], provider.load_pin(sealed=True))
    require(image == value['referenceImageReadback'], 'native-output-image-artifact-differs')
    for name, case in value['cases'].items():
        path = directory / (name + '.log')
        require(path.stat().st_size <= 64 << 10 and identity(path) == case['log'],
            'native-output-retained-log-bytes-differ')
        with provider.files.plain_file(path) as incoming:
            raw = incoming.read((64 << 10) + 1)
        if name == 'legacyAbsolute':
            match = re.search(rb'Fatal Error: Could not create directory (.+)/dbc/ check your permissions', raw)
            require(match is not None and len(match.group(1)) == 127 and b'Extracting dbc files...' in raw,
                'native-output-legacy-log-does-not-show-truncated-path')
        else:
            expected_count = b'Extracted 4 DBC files' if name == 'relativeFresh' else b'Extracted 1 DBC files'
            require(expected_count in raw and b'Extracting maps...' in raw and
                b'Fatal' not in raw and b"Can't create" not in raw, 'native-output-conversion-log-differs')
    return value


def qualify(provider_directory, output, revision, reference_check, reference_sha):
    native.native()
    require(re.fullmatch('[0-9a-f]{40}', revision or ''), 'exact-application-source-required')
    provider_directory = provider.archives.directory(Path(os.path.abspath(provider_directory)))
    pin = provider.load_pin(sealed=True)
    provider.verify(provider_directory)
    accepted_image = native.accept_image_readback(reference_check, reference_sha, pin)
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output) and len(str(output)) < 100 and
        all(output != p and output not in p.parents and p not in output.parents for p in
            (provider_directory, ROOT)), 'fresh-separate-short-owned-fixture-root-required')
    provider.archives.directory(output.parent)
    output.mkdir(mode=0o700)
    binary = output / 'bin/map_extractor'; binary.parent.mkdir(mode=0o700)
    archive = provider_directory / 'assets' / provider.ASSETS / provider.ARCHIVE
    with provider.files.plain_file(archive) as incoming, provider.archives.bounded_tar(incoming,
            dict(entries=128, pathBytes=4096, fileBytes=128 << 20)) as stream:
        copied = False
        for member in stream:
            if member.name == 'bin/map_extractor':
                require(member.isfile() and not copied, 'one-regular-shipped-map-extractor-required')
                with stream.extractfile(member) as src, binary.open('xb') as dst:
                    actual = provider.archives.hash_stream(src, member.size, dst)
                require(dict(bytes=member.size, sha256=actual) ==
                    provider.identity(pin['files']['bin/map_extractor']), 'shipped-map-elf-bytes-differ')
                binary.chmod(0o500); copied = True
            stream.members.clear()
        require(copied, 'shipped-map-extractor-missing')
    game = output / 'inputs'; (game / 'Data/enUS').mkdir(mode=0o700, parents=True)
    members = fixture_members()
    for name, values in (('Data/common.MPQ', members), ('Data/enUS/locale-enUS.MPQ', {}),
                         ('Data/enUS/speech-enUS.MPQ', {})):
        p = game / name; p.write_bytes(synthetic_mpq(values)); p.chmod(0o400)
    fixture_inputs = {p.relative_to(game).as_posix(): identity(p) for p in game.rglob('*') if p.is_file()}
    plan = data.order.plan(game, 'enUS', profile=data.PROFILE)
    wire = data.order.wire(plan); manifest = output / 'order.tsv'; manifest.write_bytes(wire)
    cwd = output / 'server-data/staging' / ('8' * 64) / ('maps-dbc-cameras-' + 'a' * 32) / 'data'
    cwd.mkdir(mode=0o700, parents=True)
    legacy = str(cwd); truncated = legacy.encode('ascii')[:127].decode('ascii')
    require(len(legacy) > 127 and not Path(truncated).exists() and str(Path(truncated)).startswith(str(output) + '/'),
        'fixture-must-reproduce-nonexistent-truncated-parent')
    try:
        os.mkdir(truncated + '/dbc/')
    except OSError as error:
        require(error.errno == errno.ENOENT, 'legacy-equivalent-mkdir-errno-differs')
        mkdir_errno = error.errno
    else:
        raise ValueError('legacy-truncated-parent-unexpectedly-exists')
    ordered = ['--esteria-order', str(manifest), '--esteria-input-root', str(game),
        '--esteria-order-sha256', hashlib.sha256(wire).hexdigest()]
    cases = {}
    for key, operand in (('legacyAbsolute', legacy), ('relativeFresh', '.'), ('relativeExisting', '.')):
        if key == 'relativeExisting':
            (cwd / 'dbc/component.wow-enUS.txt').unlink()
            (cwd / 'dbc/FixtureTable.dbc').unlink()
        log = output / (key + '.log')
        with world_io.android_policy(progress=lambda _: None):
            require(world_io.enabled(), 'production-memory-policy-required')
            try:
                result = data.execute([str(binary), *ordered, '-o', operand, '-e', '7'], cwd, log, 60,
                    cache_inputs=tuple(game / name for name in fixture_inputs))
                status = result['exitStatus']
            except ValueError as error:
                require(key == 'legacyAbsolute' and 'exitStatus=1' in str(error),
                    'unexpected-native-output-failure')
                status = 1
        require(log.stat().st_size <= 64 << 10, 'native-output-log-byte-bound')
        with provider.files.plain_file(log) as incoming:
            raw = incoming.read((64 << 10) + 1)
        if key == 'legacyAbsolute':
            expected_error = ('Fatal Error: Could not create directory ' + truncated + '/dbc/ check your permissions').encode()
            require(status == 1 and expected_error in raw and not (cwd / 'dbc').exists(),
                'actual-native-truncated-output-failure-not-reproduced')
            cases[key] = dict(exitStatus=status, outputArgumentBytes=len(legacy),
                truncatedArgumentBytes=len(truncated), equivalentMkdirErrno=mkdir_errno,
                nativeTruncatedPathErrorMatched=True, intendedOutputAbsent=True, log=identity(log))
        else:
            require(status == 0 and b'Extracting dbc files...' in raw and b'Extracting maps...' in raw and
                b'Fatal' not in raw and b"Can't create" not in raw and output_inventory(cwd) == expected_outputs(),
                'actual-native-dbc-output-conversion-failed')
            unchanged = {p.relative_to(game).as_posix(): identity(p) for p in game.rglob('*') if p.is_file()}
            require(unchanged == fixture_inputs and not Path(truncated).exists(), 'fixture-input-or-owned-output-changed')
            cases[key] = dict(exitStatus=status, outputOperand=operand, cwdBytes=len(str(cwd)),
                outputs=output_inventory(cwd), outputDirectories=sorted(p.name for p in cwd.iterdir() if p.is_dir()),
                inputBytesUnchanged=True, misdirectedDirectoryAbsent=True, log=identity(log))
    value = dict(formatVersion=1, scope=SCOPE, appRevision=revision,
        providerInputLock=identity(provider.LOCK), runtimeArchive=provider.identity(pin['archive']),
        shippedMapExtractor=identity(binary), sourceIdentities={name: identity(ROOT / name) for name in SOURCES},
        referenceImageReadback=accepted_image, fixtureInputs=fixture_inputs, expectedOutputs=expected_outputs(),
        cases=cases, productionExecuteAndMemoryPolicyUsed=True, **{name: False for name in FALSE_FLAGS})
    verify_receipt(value, revision)
    provider.engine.put_metadata(output / 'native-output.json', value)
    return value


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('provider', 'output', 'reference-image-check'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--reference-image-check-sha256', required=True)
    args = p.parse_args()
    result = qualify(args.provider, args.output, args.source_revision,
        args.reference_image_check, args.reference_image_check_sha256)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
