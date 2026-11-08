"""Serve immutable, hash-checked stock MPQ intervals; attempts to read holes fail with EIO."""
import argparse
from bisect import bisect_right
import errno
import hashlib
import json
import mmap
import os
from pathlib import Path
import stat
import struct

HERE = Path(__file__).resolve().parent


class VerifiedRanges:
    def __init__(self, source):
        self.files = {}
        self.directories = {'/': set()}
        locked = json.loads((HERE / 'buffered-ranges.json').read_bytes())['providers']
        rows = json.loads((HERE.parents[1] / 'tests/fixtures/chromiecraft-enUS-12340-zip.json').read_bytes())
        ledger = json.loads((source / 'valid-mpq-extents.json').read_bytes())
        if len(rows) != 16 or set(ledger) != set(locked):
            raise ValueError('source extent provider set differs')
        for row in rows:
            relative = row['path'].removeprefix('ChromieCraft_3.3.5a/')
            name = '/' + relative
            pins = locked[relative]
            bounds = [[p['offset'], p['offset'] + p['bytes']] for p in pins]
            if ledger[relative] != bounds:
                raise ValueError('FUSE extent bounds differ from decoder lock')
            path = source / relative
            if path != path.resolve():
                raise ValueError('linked backing path refused')
            # Preserve proof past the preparation owner: read and recheck each selected byte on
            # this mount. All later FUSE reads slice immutable Python bytes, never the sparse file.
            content = []
            with path.open('rb') as reader:
                if os.fstat(reader.fileno()).st_size != row['bytes']:
                    raise ValueError('logical stock provider length changed')
                for pin in pins:
                    reader.seek(pin['offset'])
                    data = reader.read(pin['bytes'])
                    if len(data) != pin['bytes'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
                        raise ValueError('stock shader interval changed before mount')
                    content.append(data)
            self.files[name] = (row['bytes'], [pair[0] for pair in bounds], content)
            item = Path(name)
            while item != item.parent:
                self.directories.setdefault(str(item.parent), set()).add(item.name)
                item = item.parent

    def read(self, path, size, offset):
        if path not in self.files:
            raise OSError(errno.ENOENT, 'unknown provider')
        length, starts, content = self.files[path]
        if size < 0 or offset < 0:
            raise OSError(errno.EINVAL, 'invalid read')
        end = min(length, offset + size)
        if offset >= end:
            return b''
        i = bisect_right(starts, offset) - 1
        if i < 0 or end > starts[i] + len(content[i]):
            raise OSError(errno.EIO, 'outside authenticated shader extent')
        return content[i][offset - starts[i]:end - starts[i]]


def serve(source, mount, stats=None):
    try:
        from fusepy import FUSE, FuseOSError, Operations
    except ImportError:
        from fuse import FUSE, FuseOSError, Operations

    view = VerifiedRanges(source.resolve())
    # Only the runner owns this optional file. Expose no additional path through FUSE.
    counters = [0, 0, 0]  # granted calls, granted bytes, denied EIO calls
    shared = None
    if stats is not None:
        with stats.open('r+b') as backing:
            if os.fstat(backing.fileno()).st_size != 24:
                raise ValueError('invalid initial read telemetry')
            shared = mmap.mmap(backing.fileno(), 24)
        struct.pack_into('<QQQ', shared, 0, *counters)

    def update(granted, returned, denied):
        if shared is not None:
            counters[0] += granted
            counters[1] += returned
            counters[2] += denied
            struct.pack_into('<QQQ', shared, 0, *counters)


    class Projection(Operations):
        def getattr(self, path, fh=None):
            if path in view.files:
                mode, length = stat.S_IFREG | 0o444, view.files[path][0]
            elif path in view.directories:
                mode, length = stat.S_IFDIR | 0o555, 0
            else:
                raise FuseOSError(errno.ENOENT)
            return dict(st_mode=mode, st_size=length, st_uid=0, st_gid=0, st_nlink=1)

        def readdir(self, path, fh):
            if path not in view.directories:
                raise FuseOSError(errno.ENOTDIR)
            return ['.', '..', *sorted(view.directories[path])]

        def open(self, path, flags):
            if flags & (os.O_ACCMODE | os.O_TRUNC | os.O_CREAT):
                raise FuseOSError(errno.EROFS)
            if path not in view.files:
                raise FuseOSError(errno.ENOENT)
            return 0

        def read(self, path, size, offset, fh):
            try:
                data = view.read(path, size, offset)
                update(1, len(data), 0)
                return data
            except OSError as error:
                if error.errno == errno.EIO:
                    update(0, 0, 1)
                    print('Denied unauthenticated shader read', path, offset, size, flush=True)
                raise FuseOSError(error.errno)

    try:
        FUSE(Projection(), str(mount), foreground=True, allow_other=True, ro=True, default_permissions=True,
             direct_io=True, max_readahead=0, nothreads=True)
    finally:
        if shared is not None:
            shared.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('mount', type=Path)
    parser.add_argument('--stats', type=Path)
    args = parser.parse_args()
    serve(args.source, args.mount, args.stats)
