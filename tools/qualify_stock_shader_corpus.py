"""Native CI qualification using the English providers from ChromieCraft's stock ZIP."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import builtins
import hashlib
import http.client
import importlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import sys
import tarfile
import tempfile
from threading import Lock
import time
import urllib.error
import urllib.request
from unittest.mock import patch
import zlib

from runtime import shader_generation, stock_shader_translate as adapter
from tools import prepare_runtime, provider_shader_tools, qualify_stock_client_title

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / 'tests/fixtures/chromiecraft-enUS-12340-zip.json'
PREFIX = 'ChromieCraft_3.3.5a/'
URL = 'https://chmi.btground.dedyn.io/ChromieCraft_3.3.5a.zip'
ETAG = '"41d7f4760-5ed279fed4970"'
TOTAL = 17674749792
TORRENT = 'https://usefulness.altervista.org/WoW/ChromieCraft_3.3.5a.zip.torrent'
TORRENT_HASH = '58731d43da3e615fbeb489ebd7a9401a8b56eeed8b7baf72f6b57646c574f62e'
PIECE = 2 << 20
WINDOW = 16 * PIECE
DEADLINE = 90 * 60


class Invalid(Exception):
    """Only messages authored here may be copied to the public report."""


def require(condition, message):
    if not condition:
        raise Invalid(message)


def torrent_pieces():
    with urllib.request.urlopen(TORRENT, timeout=60) as response:
        raw = response.read(256 << 10)
    require(hashlib.sha256(raw).hexdigest() == TORRENT_HASH, 'official torrent digest changed')
    field = re.search(rb'6:pieces([0-9]+):', raw)
    length = int(field[1])
    require(length == ((TOTAL + PIECE - 1) // PIECE) * 20, 'torrent piece count changed')
    return raw[field.end():field.end() + length]


def range_bytes(first, end, deadline, opener=urllib.request.urlopen):
    # The stock origin sometimes closes a valid 206 body early. Retain only bytes
    # from responses with the exact If-Match/Content-Range and authenticate whole
    # torrent pieces in verified_slices before the inflater sees any of them.
    data = bytearray()
    stalled = 0
    for _ in range(64):
        cursor = first + len(data)
        require(time.monotonic() < deadline, 'stock ZIP transfer exceeded deadline')
        request = urllib.request.Request(URL, headers={
            'Range': 'bytes=%d-%d' % (cursor, end - 1), 'If-Match': ETAG, 'Accept-Encoding': 'identity'})
        try:
            with opener(request, timeout=75) as response:
                require(response.geturl() == URL and response.status == 206 and
                        response.headers.get('ETag') == ETAG and
                        response.headers.get('Content-Range') == 'bytes %d-%d/%d' % (cursor, end - 1, TOTAL),
                        'ZIP origin, ETag or byte range changed')
                while first + len(data) < end:
                    require(time.monotonic() < deadline, 'stock ZIP transfer exceeded deadline')
                    try:
                        part = response.read(min(65536, end - first - len(data)))
                    except http.client.IncompleteRead as error:
                        data.extend(error.partial)
                        break
                    if not part:
                        break
                    data.extend(part)
                require(first + len(data) <= end, 'ZIP range returned excess bytes')
                if first + len(data) == end:
                    require(not response.read(1), 'ZIP range returned excess bytes')
                    return data
        except (OSError, EOFError, http.client.HTTPException):
            pass
        stalled = stalled + 1 if cursor == first + len(data) else 0
        require(stalled < 3, 'stock ZIP range unavailable after three attempts without progress')
        if stalled:
            time.sleep(stalled)
    raise Invalid('stock ZIP exceeded partial-response limit')


def verified_slices(start, length, hashes, fetch, total=TOTAL, piece=PIECE):
    """Yield only authenticated intersecting bytes. The complete ZIP is never stored."""
    end = start + length
    require(0 <= start < end <= total, 'invalid ZIP member range')
    first = start // piece * piece
    limit = min(((end + piece - 1) // piece) * piece, total)
    for offset in range(first, limit, WINDOW):
        stop = min(limit, offset + WINDOW)
        block = fetch(offset, stop)
        require(len(block) == stop - offset, 'incomplete ZIP range')
        for pos in range(offset, stop, piece):
            buf = memoryview(block)[pos - offset:pos - offset + piece]
            index = pos // piece * 20
            require(hashlib.sha1(buf).digest() == hashes[index:index + 20], 'ZIP torrent piece hash mismatch')
            yield buf[max(0, start - pos):min(len(buf), end - pos)]


def extract(row, root, hashes, fetch, total=TOTAL, piece=PIECE):
    name = row['path']
    require(re.fullmatch(r'ChromieCraft_3\.3\.5a/Data/(enUS/)?[A-Za-z0-9-]+\.MPQ', name)
            and row['method'] == 8, 'unexpected selected ZIP member')
    encoded = name.encode('ascii')
    head = b''.join(verified_slices(row['local'], 30 + len(encoded), hashes, fetch, total, piece))
    flags, method = struct.unpack_from('<HH', head, 6)
    namesize, extra = struct.unpack_from('<HH', head, 26)
    require(head[:4] == b'PK\x03\x04' and not flags & 1 and method == 8 and
            namesize == len(encoded) and head[30:] == encoded, 'ZIP local header differs from lock')
    target = root / name.removeprefix(PREFIX)
    target.parent.mkdir(parents=True, exist_ok=True)
    decoder, size, crc = zlib.decompressobj(-15), 0, 0
    with target.open('xb') as output:
        for chunk in verified_slices(row['local'] + len(head) + extra, row['compressed'], hashes,
                                     fetch, total, piece):
            while chunk:
                plain = decoder.decompress(chunk, 4 << 20)
                chunk = decoder.unconsumed_tail
                size += len(plain)
                require(size <= row['bytes'], 'ZIP member exceeded expected size')
                crc = zlib.crc32(plain, crc)
                output.write(plain)
    require(decoder.eof and not decoder.unused_data and size == row['bytes'] and crc == row['crc'],
            'ZIP member CRC, size or DEFLATE termination mismatch')
    return target


def prepare_tools(work):
    public = json.loads((ROOT / 'runtime/wine-cohort-publication/published-release.json').read_bytes())
    name = 'provider-assets.tar.gz'
    cohort = prepare_runtime.fetch(dict(public['assets'][name], file=name), work)
    with tarfile.open(cohort, 'r:gz') as outer:
        archive = outer.extractfile(provider_shader_tools.ASSETS + '/' + provider_shader_tools.ARCHIVE).read()
    tools = work / 'tools'
    pin = provider_shader_tools.load_pin()
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as inner:
        for name in pin['files']:
            if name.startswith('tools/'):
                target = tools / name.removeprefix('tools/')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(inner.extractfile(name).read())
                target.chmod(0o700 if name == provider_shader_tools.COMPILER else 0o600)
    require(shader_generation.tool_identity(tools, pin['clientRevision']) == pin['toolManifestSha256'],
            'packaged shader reader/compiler identity mismatch')
    return tools, pin


def model_requirement(code, ir):
    """Report the model and opcode vocabulary only; never emit operands, comments or bytecode."""
    if len(code) < 8 or len(code) % 4:
        return {'model': 'unaligned'}
    tokens = struct.unpack('<%dI' % (len(code) // 4), code)
    version = tokens[0]
    major, minor = (version >> 8) & 255, version & 255
    stage = {0xfffe: 'vs', 0xffff: 'ps'}.get(version >> 16, 'unknown')
    seen, pos = set(), 1
    while pos < len(tokens):
        word = tokens[pos]
        op = word & 0xffff
        pos += 1
        if op == ir.OP_END:
            break
        if op == ir.OP_COMMENT:
            pos += (word >> 16) & 0x7fff
            continue
        if major == 1 and word >> 31:
            continue  # SM1 operand, no instruction length field
        seen.add(ir.OPS.get(op, 'phase' if op == 0xfffd else 'unknown'))
        if major >= 2:
            pos += (word >> 24) & 15
        elif op == ir.OP_DEF:
            pos += 5  # Immediate constants are payload, not instructions.
    return {'model': '%s_%d_%d' % (stage, major, minor), 'instructionSet': sorted(seen)}


def input_failure(reader, data, error):
    # Production strict input errors now give the rejected provider, path and permutation.
    # Re-read that exact winner for the public instruction vocabulary, without raw tokens.
    pattern = (r'(Shaders[\\/](Vertex|Pixel)[\\/]([a-z0-9_]+)[\\/][A-Za-z0-9_-]+\.bls) in '
               r'([A-Za-z0-9_./-]+), permutation ([0-9]+), token 0x[0-9a-f]{8}: ([A-Za-z0-9 ._-]{1,100})')
    match = re.fullmatch(pattern, str(error))
    if not match:
        if str(error).startswith('stock Vulkan requires all 32'):
            return [dict(reason='required 32 Terrain1 ps_3_0 permutations were not selected')]
        if str(error).startswith('stock Vulkan effect requests legacy terrain'):
            return [dict(reason='a selected effect references legacy terrain')]
        return [dict(reason='stock provider input rejected')]
    path, kind, profile, provider, permutation, reason = match.groups()
    opened = reader.archives(data, 'enUS')
    try:
        actual, body = reader.grab(opened, path)
        require(actual == provider, 'shader winner changed during diagnosis')
        code = next(code for index, _, code in adapter.container_records(body, True) if index == int(permutation))
        return [dict(path=path.replace(chr(92), '/'), kind=kind.lower(), profile=profile, provider=provider,
                     permutation=int(permutation), reason=reason, **model_requirement(code, reader.ir))]
    finally:
        for _, archive in opened:
            archive.close()


def diagnose(tools, revision, data, capture):
    reader, _ = adapter.stock.load_reader(tools, revision)
    translate = importlib.import_module(reader.__package__ + '.translate')
    failures = []
    with adapter.bounded_adapter(reader, translate, stock_vulkan=True):
        try:
            records = reader.enumerate_records(data, 'enUS', strict=True)
        except ValueError as exc:
            return input_failure(reader, data, exc)
        opened = reader.archives(data, 'enUS')
        try:
            for rec in records:
                if len(failures) == 32:
                    break
                error = None
                if rec.sh is None:
                    try:
                        reader.ir.decode_strict(rec.code)
                    except ValueError as exc:
                        error = re.sub(r'[^a-zA-Z0-9 ._-]', '', str(exc))[:100]
                elif rec.sh.kind != {'vertex': 'vs', 'pixel': 'ps'}[rec.kind]:
                    error = 'shader stage differs from container'
                elif 'FAILED ' + rec.key + ':' in capture or 'FAILED ' + rec.key + ' = ' in capture:
                    error = 'packaged glslang rejected emitted module'
                elif 'refused x' in capture:
                    try:
                        translate.Emitter(rec).run()
                    except translate.Refused as exc:
                        error = re.sub(r'[^a-zA-Z0-9 ._-]', '', str(exc))[:100]
                if error:
                    path = '/'.join(('Shaders', rec.kind.capitalize(), rec.profile, rec.name + '.bls'))
                    require(re.fullmatch(r'[A-Za-z0-9_./-]{1,180}', path), 'invalid shader path for report')
                    provider = next(name for name, archive in reversed(opened)
                                    if archive.find(path.replace('/', chr(92))) is not None)
                    failures.append(dict(provider=provider, path=path, profile=rec.profile, kind=rec.kind,
                                         permutation=rec.perm, reason=error, **model_requirement(rec.code, reader.ir)))
        finally:
            for _, provider in opened:
                provider.close()
    return failures


@contextmanager
def verified_reads(extents, stats):
    """Reject any read of an MPQ byte absent from the authenticated projection."""
    if extents is None:
        yield
        return
    spans = {}
    for path, ranges in extents.items():
        merged = []
        for lo, hi in sorted(ranges):
            require(0 <= lo < hi <= path.stat().st_size, 'invalid authenticated MPQ extent')
            if merged and lo <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
            else:
                merged.append((lo, hi))
        spans[path.resolve()] = merged

    class CoveredArchive:
        def __init__(self, stream, bounds):
            self.stream = stream
            self.bounds = bounds

        def check(self, size):
            start = self.stream.tell()
            require(size >= 0 and any(lo <= start and start + size <= hi for lo, hi in self.bounds),
                    'production reader accessed unverified MPQ extent')
            stats['mpqReadCalls'] += 1
            stats['mpqReadBytes'] += size

        def read(self, size=-1):
            self.check(size)
            return self.stream.read(size)

        def readinto(self, buffer):
            self.check(len(buffer))
            return self.stream.readinto(buffer)

        def seek(self, *args):
            return self.stream.seek(*args)

        def close(self):
            self.stream.close()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def guarded(opener):
        def opened(file, mode='r', *args, **kwargs):
            if isinstance(file, (str, os.PathLike)) and Path(file).suffix.lower() == '.mpq':
                path = Path(file).resolve()
                require(mode == 'rb' and path in spans, 'production reader selected unexpected MPQ')
                return CoveredArchive(opener(file, mode, *args, **kwargs), spans[path])
            return opener(file, mode, *args, **kwargs)
        return opened

    with ExitStack() as stack:
        for module in (builtins, io):
            stack.enter_context(patch.object(module, 'open', guarded(module.open)))
        yield


def qualify(work, report, *, complete_client=False):
    rows = json.loads(LOCK.read_bytes())
    required = (sum(row['bytes'] for row in rows) if complete_client else 512 << 20) + (3 << 30)
    require(shutil.disk_usage(work).free >= required, 'insufficient scratch for requested corpus and compiler')
    require(platform.machine() == 'aarch64', 'native Linux ARM64 runner required')
    report['phase'] = 'packaged-tools'
    tools, pin = prepare_tools(work)
    report.update(clientRevision=pin['clientRevision'], toolManifestSha256=pin['toolManifestSha256'],
                  adapterSha256=hashlib.sha256(Path(adapter.__file__).read_bytes()).hexdigest())
    report['phase'] = 'verified-stock-zip'
    report['inputScope'] = 'complete-effective-providers' if complete_client else 'verified-shader-extents'
    hashes = torrent_pieces()
    deadline = time.monotonic() + DEADLINE
    client = work / 'client'
    started = time.monotonic()
    transfer = dict(rangeRequestsCompleted=0, zipRangeBytes=0)
    transfer_lock = Lock()
    report['transfer'] = transfer
    def fetch(start, end):
        data = range_bytes(start, end, deadline)
        with transfer_lock:
            transfer['rangeRequestsCompleted'] += 1
            transfer['zipRangeBytes'] += len(data)
        return data
    extents = None
    if complete_client:
        def materialize(row):
            path = extract(row, client, hashes, fetch)
            print('Verified', str(path.relative_to(client)), row['bytes'], flush=True)
            return str(path.relative_to(client))
        with ThreadPoolExecutor(max_workers=4) as pool:
            report['verifiedProviders'] = sorted(pool.map(materialize, rows))
    else:
        from tools import stock_shader_ranges
        extents = stock_shader_ranges.materialize(client, rows, fetch, hashes)
        report['verifiedProviders'] = sorted(str(path.relative_to(client)) for path in extents)
    report['inputSeconds'] = round(time.monotonic() - started, 2)
    reader, _ = adapter.stock.load_reader(tools, pin['clientRevision'])
    effective = reader.provider_paths(client / 'Data', 'enUS')
    require(set(effective) == {client / name for name in report['verifiedProviders']},
            'verified ZIP members differ from effective provider stack')
    report['phase'] = 'strict-translation'
    started = time.monotonic()
    output = work / 'compiled'
    # Raw diagnostics can include disassembly or compiler input. Keep them private.
    read_stats = dict(mpqReadCalls=0, mpqReadBytes=0)
    if extents is not None:
        report['authenticatedReads'] = read_stats
    with verified_reads(extents, read_stats), tempfile.TemporaryFile(mode='w+t', encoding='utf8') as private:
        args = ['--strict', '--client', str(client), '--locale', 'enUS', '--glslang',
                str(tools / 'bin/glslangValidator'), '--out', str(output)]
        with redirect_stdout(private), redirect_stderr(private):
            code = adapter.run(tools, pin['clientRevision'], args, stock_vulkan=True)
        report.update(strictExit=code, strictSeconds=round(time.monotonic() - started, 2))
        private.seek(0)
        capture = private.read(1 << 20)
        if code:
            report['failures'] = diagnose(tools, pin['clientRevision'], client / 'Data', capture)
            raise Invalid('strict translation rejected the selected stock corpus')
    report['phase'] = 'validate-production-output'
    inventory = shader_generation.validate_output(output)
    report.update(files=len(inventory), modules=sum(name.endswith('.spv') for name in inventory),
                  outputBytes=sum(item['bytes'] for item in inventory.values()), phase='qualified', passed=True)
    summary = re.search(r'^records: (\d+) total, (\d+) decodable, (\d+) distinct; (\d+) selected:',
                        capture, re.MULTILINE)
    if summary:
        report.update(zip(('records', 'decodable', 'distinct', 'selected'), map(int, summary.groups())))
    if not complete_client:
        report['clientCapture'] = dict(phase='shader-extents-only', titleQualified=False)
    elif shutil.disk_usage(work).free < (3 << 30):
        report['clientCapture'] = dict(phase='insufficient-title-scratch', titleQualified=False)
    else:
        report['clientCapture'] = qualify_stock_client_title.capture(work, client, output, pin['clientRevision'])



def main():
    os.umask(0o077)
    sys.dont_write_bytecode = True
    report = dict(environment='native-linux-arm64', source=os.environ.get('GITHUB_SHA'),
                  officialTorrentSha256=TORRENT_HASH, passed=False, phase='disk-admission')
    try:
        with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as tmp:
            qualify(Path(tmp), report, complete_client=os.environ.get('COMPLETE_CLIENT') == 'true')
    except Exception as error:
        report['error'] = str(error) if isinstance(error, Invalid) else type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            report['httpStatus'] = error.code
    encoded = json.dumps(report, indent=2, sort_keys=True) + '\n'
    (ROOT / 'stock-shader-qualification.json').write_text(encoded)
    print(encoded)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
