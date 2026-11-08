"""Verified shader input windows of the fixed English 12340 ZIP. CI use only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib


LOCK = Path(__file__).resolve().parents[1] / 'tests/fixtures/chromiecraft-enUS-12340-shader-ranges.json'


def materialize(client, rows, fetch, hashes, *, index_path=None):
    """Return allowed half-open read extents keyed by each absolute sparse MPQ path.

    The lock locates independently decodable ZIP stored blocks or entry starts.
    Both the source torrent pieces and the exact output SHA-256 bind each extent.
    Callers must enforce this read set throughout every consuming operation.
    """
    from tools.qualify_stock_shader_corpus import PIECE, PREFIX, TOTAL, require, verified_slices

    index = json.loads((index_path or LOCK).read_bytes())
    providers = index['providers']
    require(index['version'] == 1 and len(rows) == len(providers) and
            {row['path'] for row in rows} == {PREFIX + name for name in providers},
            'shader range provider set differs from ZIP lock')
    pieces = set()

    def add(start, size):
        require(0 < size <= 32 << 20 and 0 <= start <= TOTAL - size, 'invalid shader ZIP window')
        pieces.update(range(start // PIECE, (start + size - 1) // PIECE + 1))

    for row in rows:
        name = row['path'].removeprefix(PREFIX)
        require(re.fullmatch(r'Data/(enUS/)?[A-Za-z0-9-]+\.MPQ', name) and row['method'] == 8,
                'unexpected shader ZIP member')
        add(row['local'], 30 + len(row['path']))
        for span in providers[name]:
            add(span['start'], span['compressedBytes'])
    require(0 < len(pieces) <= 128, 'shader torrent piece budget exceeded')

    def load(piece):
        start = piece * PIECE
        size = min(PIECE, TOTAL - start)
        return piece, b''.join(verified_slices(start, size, hashes, fetch))

    with ThreadPoolExecutor(max_workers=8) as pool:
        authenticated = dict(pool.map(load, sorted(pieces)))

    def read(start, size):
        end = start + size
        return b''.join(authenticated[i][max(0, start - i * PIECE):min(PIECE, end - i * PIECE)]
                        for i in range(start // PIECE, (end - 1) // PIECE + 1))

    allowed = {}
    for row in rows:
        name = row['path'].removeprefix(PREFIX)
        header = read(row['local'], 30 + len(row['path']))
        flags, method = struct.unpack_from('<HH', header, 6)
        namesize, extra = struct.unpack_from('<HH', header, 26)
        require(header[:4] == b'PK\x03\x04' and not flags & 1 and method == 8 and
                namesize == len(row['path']) and header[30:] == row['path'].encode('ascii'),
                'shader ZIP header differs from lock')
        start = row['local'] + len(header) + extra
        target = (client / name).absolute()
        target.parent.mkdir(parents=True, exist_ok=True)
        extents = []
        with target.open('xb') as output:
            output.truncate(row['bytes'])
            for span in providers[name]:
                position, length = span['start'], span['compressedBytes']
                offset, size, skip = span['offset'], span['bytes'], span['skip']
                require(start <= position and position + length <= start + row['compressed'] and
                        0 <= offset <= row['bytes'] - size and size > 0 and
                        0 <= skip and skip + size <= 32 << 20 and
                        (not extents or extents[-1][1] <= offset), 'invalid shader extent')
                data = read(position, length)
                if span['restart'] == 'stored':
                    block, inverse = struct.unpack_from('<HH', data)
                    require(block ^ inverse == 0xffff, 'invalid ZIP stored-block restart')
                    # Raw DEFLATE at a byte-aligned LEN/NLEN pair, with BFINAL/BTYPE=000.
                    data = b'\0' + data
                else:
                    require(span['restart'] == 'entry' and position == start and offset == skip == 0,
                            'invalid ZIP entry restart')
                decoder = zlib.decompressobj(-15)
                payload = decoder.decompress(data, skip + size)[skip:]
                require(len(payload) == size and hashlib.sha256(payload).hexdigest() == span['sha256'],
                        'decoded shader extent digest mismatch')
                output.seek(offset)
                output.write(payload)
                extents.append((offset, offset + size))
        allowed[target] = extents
    return allowed
