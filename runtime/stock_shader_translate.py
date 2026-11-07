#!/usr/bin/env python3
"""Bounded-memory adapter over the unchanged, verified shader translator.

The original MPQ member decoder, DX9 decoder, emitter, compiler and manifest
formatter still execute. Packed tables and short-lived decoded IR replace the
upstream reader's simultaneously retained Python table/IR objects.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import importlib
import importlib.util
import io
import re
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

try:
    from . import stock_content_inspection as stock, world_io
except ImportError:
    import stock_content_inspection as stock
    import world_io

MAX_LISTFILE = 16 << 20
MAX_RECORD_BYTES = 1 << 20
MAX_CODE_BYTES = 64 << 20
MAX_RECORD_METADATA = 64 << 20
MAX_RECORDS = 262144
MPQ_FILE_PATCH_FILE = 0x00100000
MPQ_FILE_DELETE_MARKER = 0x02000000


# CMap::Initialize on the stock Vulkan PS3 tier loads Terrain1[0..31].
# These exact stock containers serve its separate PS1.1/1.4 branches. A single
# legacy bytecode digest is shared between flat and cube-map draws, so compiling
# it with an assumed sampler type would produce an incorrect manifest.
LEGACY_TERRAIN_CONTAINERS = {
    ('ps_1_1', 'terrain1w'): '0137d20560289c42d2c316359cf72ab5bf467f298efbc846d0e1175afc323220',
    ('ps_1_4', 'terrain1w_1'): '09f8aa83145a186a86e3c63d36894bdc634e52f14bf51e877faed51d1c3026a9',
    ('ps_1_4', 'terrain1w_2'): '023b4ff2350a86281908f65e35bde51e5c15ea5832843449ddbe5532c3e55272',
    ('ps_1_4', 'terrain1w_3'): '64ab82e635c09c16657135076e9f1e7f7721e69ab14bd08d08362c90551b0d92',
    ('ps_1_4', 'terrain1w_4'): 'd9c6ed0e373ee312d5a0997fdd6ee1e652237fee46998b7086ca59fbc317f41c',
}
STOCK_EFFECT_FILES = ('MapObj.wfx', 'MapObjU.wfx', 'Model2.wfx', 'Particle.wfx', 'ShadowMap.wfx')


class DeletedMember(ValueError):
    """The winning provider explicitly removed this virtual path."""


class CompactRecord:
    __slots__ = ('kind', 'profile', 'name', 'perm', 'code', 'md5', 'names', 'hdr',
                 '_summary', '_active_shader', '_strict')

    @property
    def key(self):
        return '%s:%d' % (self.name, self.perm)

    @property
    def sh(self):
        return self._active_shader if self._active_shader is not None else self._summary


def container_records(data, strict):
    """The pinned split() wire rules, yielding one bounded record at a time."""
    magic, version, count = struct.unpack_from('<III', data, 0)
    if strict and (magic != 0x47585348 or version != 0x10003 or not 0 < count <= (len(data) - 12) // 16):
        raise ValueError('invalid or empty shader container header')
    offset = 12
    for index in range(count):
        a, b, c, d, size = struct.unpack_from('<IIHHI', data, offset)
        offset += 16
        if strict and (size < 8 or size % 4 or size > len(data) - offset):
            raise ValueError('invalid shader record size')
        stock.require(size <= MAX_RECORD_BYTES, 'shader record exceeds bounded 1 MiB bytecode limit')
        code = data[offset:offset + size]
        offset = (offset + size + 3) & ~3
        yield index, (a, b, c, d), code
    if strict and offset != len(data):
        raise ValueError('shader container has unaccounted bytes')


@contextmanager
def bounded_adapter(reader, translate, *, stock_vulkan=False):
    """Install only in this fresh helper process; never rewrite provider files."""
    original = (reader.archives, reader.entries, reader.enumerate_records, translate.Emitter)
    packed = stock.compact_mpq_class(reader)
    last_emitter = [None]
    effect_paths = set()

    class BoundedMPQ(packed):
        def read_file(self, name):
            index = self.find(name)
            if index is not None:
                _, _, size, flags = self.block_table[index]
                if flags & MPQ_FILE_DELETE_MARKER:
                    member = '%s in %s' % (name, self.path)
                    stock.require(flags & reader.mq.FLAG_EXISTS, 'MPQ hash references an absent block: ' + member)
                    stock.require(not flags & MPQ_FILE_PATCH_FILE, 'ambiguous MPQ delete marker and delta-patch: ' + member)
                    raise DeletedMember('MPQ delete marker for ' + member)
                maximum = MAX_LISTFILE if name.lower() == '(listfile)' else reader.mq.MAX_FILE_SIZE
                stock.require(size <= maximum,
                              'shader/listfile member exceeds bound before allocation: ' + str(self.path))
            return super().read_file(name)

    class BoundedFolder(reader.FolderArchive):
        def read_file(self, name):
            if name.lower() == '(listfile)':
                stock.require(len(self.files) <= MAX_RECORDS and
                    sum(len(item[0].encode('utf-8')) + 1 for item in self.files.values()) <= MAX_LISTFILE,
                    'folder shader inventory exceeds memory bound')
            return super().read_file(name)

    def archives(datadir, locale=None):
        selected = reader.select_locale(datadir, locale)
        paths = reader.provider_paths(datadir, selected)
        stock.require(len(paths) <= stock.order.MAX_PROVIDERS, 'shader provider inventory bound')
        regular = [path for path in paths if path.is_file()]
        # Header discovery does not consult locale members. A root-only reader
        # can therefore use the enUS numeric header probe without fabricating data.
        counts = stock.preflight_tables(regular, reader, selected or 'enUS')
        opened, retained = [], 0
        try:
            for path in paths:
                if path.is_dir():
                    provider = BoundedFolder(path)
                else:
                    retained += counts[path]
                    stock.require(retained <= stock.MAX_TABLE_ENTRIES,
                                  'combined retained shader MPQ table memory bound before allocation: ' + str(path))
                    provider = BoundedMPQ(path, reader.LOCALES.get(selected, 0))
                opened.append((str(path.relative_to(datadir)), provider))
                if provider.find('(listfile)') is None:
                    raise ValueError('shader inventory requires (listfile) in %s' % path)
            return opened
        except Exception:
            for _, provider in opened:
                provider.close()
            raise

    def entries(archives_, prefix='shaders'):
        result, total = set(), 0
        for _, provider in archives_:
            if provider.find('(listfile)') is None:
                continue
            raw, _ = provider.read_file('(listfile)')
            stock.require(len(raw) <= MAX_LISTFILE, 'shader listfile exceeds memory bound')
            # Avoid retaining the split-lines list in addition to the decoded
            # text and the filtered shader inventory.
            for line in io.StringIO(raw.decode('ascii', 'replace')):
                line = line.strip()
                if line.lower().startswith(prefix.lower()) and line not in result:
                    total += len(line.encode('utf-8')) + 64
                    stock.require(len(result) < MAX_RECORDS and total <= MAX_RECORD_METADATA,
                                  'combined shader inventory memory bound')
                    result.add(line)
                    if stock_vulkan and line.lower().endswith('.wfx'):
                        effect_paths.add(line.lower())
        return sorted(result)

    def enumerate_records(datadir, locale=None, strict=False):
        effect_paths.clear()
        opened = archives(datadir, locale)
        legacy_paths = []
        result, code_pool, code_bytes, metadata_bytes = [], {}, 0, 0
        decode = reader.ir.decode_strict if strict else reader.ir.decode
        try:
            inventory = reader.inventory(opened)
            for kind, profile, name in reader.resolve(inventory):
                chain = reader.VS_FALLBACK if kind == 'vertex' else reader.PS_FALLBACK
                for candidate in chain[chain.index(profile):]:
                    low = name.lower()
                    if low not in inventory.get((kind, candidate), {}):
                        continue
                    candidate_name = inventory[(kind, candidate)][low]
                    path = reader.BS.join(['Shaders', kind.capitalize(), candidate,
                                          candidate_name + '.bls'])
                    try:
                        provider, data = reader.grab(opened, path)
                    except DeletedMember:
                        # grab() already chose the winning provider. A marker removes
                        # only this profile path, even when a lower MPQ lists its bytes.
                        continue
                    if data is None or len(data) < 12:
                        if strict:
                            raise ValueError('selected shader container is missing or truncated: %s (%s)' %
                                             (path, provider or 'no provider'))
                        continue
                    profile, name = candidate, candidate_name
                    break
                else:
                    # No surviving profile. Strict translation still checks that both
                    # required stages have live records before publishing anything.
                    continue
                if strict and stock_vulkan and kind == 'pixel':
                    known = LEGACY_TERRAIN_CONTAINERS.get((profile, name.lower()))
                    if known and hashlib.sha256(data).hexdigest() == known:
                        legacy_paths.append(path)
                        continue
                for permutation, header, code in container_records(data, strict):
                    stock.require(len(result) < MAX_RECORDS, 'shader record count exceeds memory bound')
                    metadata_bytes += 256 + len(name.encode('utf-8')) * 4
                    stock.require(metadata_bytes <= MAX_RECORD_METADATA, 'shader record metadata exceeds memory bound')
                    digest = hashlib.sha256(code).digest()
                    pooled = code_pool.get(digest)
                    if pooled is None or pooled != code:
                        code_bytes += len(code)
                        stock.require(code_bytes <= MAX_CODE_BYTES, 'distinct shader bytecode exceeds memory bound')
                        code_pool.setdefault(digest, code)
                    else:
                        code = pooled
                    record = CompactRecord()
                    record.kind, record.profile, record.name, record.perm = kind, profile, name, permutation
                    record.code, record.md5, record.hdr = code, hashlib.md5(code).hexdigest(), header
                    record.names, record._active_shader = [], None
                    record._strict = strict
                    try:
                        shader = decode(code)
                        if strict and shader.kind != ('ps' if kind == 'pixel' else 'vs'):
                            raise ValueError('stage mismatch: ' + shader.profile)
                        record._summary = SimpleNamespace(kind=shader.kind, major=shader.major,
                            minor=shader.minor, profile=shader.profile)
                        shader = None
                    except ValueError as error:
                        if strict:
                            version, = struct.unpack_from('<I', code)
                            raise ValueError('%s in %s, permutation %d, token 0x%08x: %s' %
                                             (path, provider, permutation, version, error)) from error
                        record._summary = None
                    result.append(record)
            if legacy_paths:
                active = [r for r in result if r.kind == 'pixel' and r.name.lower() == 'terrain1']
                stock.require(len(active) == 32 and all(r.perm == i and r.profile == 'ps_3_0' and
                              r.sh.profile == 'ps_3_0' for i, r in enumerate(active)),
                              'stock Vulkan requires all 32 selected ps_3_0 Terrain1 permutations')
                # Stock names are probed directly even if a provider omitted them from
                # its listfile. The native effect parser accepts literal shader names.
                effect_paths.update(reader.BS.join(('Shaders', 'Effects', name)).lower()
                                    for name in STOCK_EFFECT_FILES)
                for effect in sorted(effect_paths):
                    try:
                        provider, body = reader.grab(opened, effect)
                    except DeletedMember:
                        continue
                    if body is not None and re.search(b'terrain1w', body, re.IGNORECASE):
                        raise ValueError('stock Vulkan effect requests legacy terrain: %s in %s' %
                                         (effect, provider))
                print('Stock Vulkan vs_3_0/ps_3_0: selected 32 Terrain1 permutations; '
                      'excluded reviewed PS1-only containers: ' + ', '.join(legacy_paths), flush=True)
            return result
        finally:
            for _, provider in opened:
                provider.close()

    class BoundedEmitter(original[3]):
        def __init__(self, record):
            if last_emitter[0] is not None:
                # The pinned main loop has formatted the previous manifest
                # and index before it constructs another emitter. Its results
                # summary reads no previous emitter-state fields.
                last_emitter[0].release_metadata()
            if isinstance(record, CompactRecord):
                # The complete record already passed the pinned decoder. Only
                # the current byte-distinct emitter needs its expanded IR.
                decode = reader.ir.decode_strict if record._strict else reader.ir.decode
                record._active_shader = decode(record.code)
                try:
                    super().__init__(record)
                finally:
                    record._active_shader = None
            else:
                super().__init__(record)
            last_emitter[0] = self

        def release_metadata(self):
            for name in ('inputs', 'samplers', 'flags', 'reads', 'outputs'):
                value = getattr(self, name, None)
                if value is not None:
                    value.clear()

        def run(self):
            try:
                return super().run()
            finally:
                if isinstance(self.rec, CompactRecord):
                    # Later original manifest formatting uses only profile;
                    # companion/index formatting uses the retained small metadata.
                    self.sh = self.rec._summary
                    for name in ('body', 'defs', 'defi', 'temps', 'helpers', 'ops_used', 'outregs', 'in_masks', 'out_sems'):
                        getattr(self, name).clear()

    reader.archives, reader.entries, reader.enumerate_records = archives, entries, enumerate_records
    translate.Emitter = BoundedEmitter
    try:
        yield
    finally:
        if last_emitter[0] is not None:
            last_emitter[0].release_metadata()
            last_emitter[0] = None
        reader.archives, reader.entries, reader.enumerate_records, translate.Emitter = original


def run(tools, revision, arguments, *, stock_vulkan=False):
    previous_bytecode = sys.dont_write_bytecode
    previous_bls = sys.modules.get('bls')
    previous_path = list(sys.path)
    try:
        sys.dont_write_bytecode = True
        reader, manifest = stock.load_reader(Path(tools), revision)
        package = sys.modules[reader.__package__]
        translate = importlib.import_module(reader.__package__ + '.translate')
        spec = importlib.util.spec_from_file_location('_esteria_verified_shader_entry', Path(tools) / 'translate_shaders.py')
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        sys.modules['bls'] = package
        with bounded_adapter(reader, translate, stock_vulkan=stock_vulkan):
            result = entry.main(arguments)
        stock.require(stock.storage.tool_identity(Path(tools), revision) == manifest,
                      'immutable shader provider changed during translation')
        return result
    finally:
        if previous_bls is None:
            sys.modules.pop('bls', None)
        else:
            sys.modules['bls'] = previous_bls
        sys.path[:] = previous_path
        sys.dont_write_bytecode = previous_bytecode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tools', 'client', 'out', 'glslang'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--client-revision', required=True)
    parser.add_argument('--locale', required=True)
    parser.add_argument('--strict', action='store_true', required=True)
    parser.add_argument('--stock-vulkan', action='store_true')
    parser.add_argument('--android-low-memory', action='store_true')
    args = parser.parse_args()
    stock.require(args.glslang == args.tools / 'bin/glslangValidator', 'verified shader compiler path required')
    arguments = ['--strict', '--client', str(args.client), '--locale', args.locale,
                 '--glslang', str(args.glslang), '--out', str(args.out)]
    try:
        if args.android_low_memory:
            with world_io.android_policy():
                return run(args.tools, args.client_revision, arguments, stock_vulkan=args.stock_vulkan)
        return run(args.tools, args.client_revision, arguments, stock_vulkan=args.stock_vulkan)
    except world_io.PreparationPaused:
        world_io.print_pause()
        return world_io.PAUSED_EXIT_CODE


if __name__ == '__main__':
    raise SystemExit(main())
