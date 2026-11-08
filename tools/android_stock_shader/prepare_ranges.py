"""Materialize only the authenticated stock shader extents consumed by the Android qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Lock
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from tools import qualify_stock_shader_corpus as corpus, stock_shader_ranges

BUFFERED = HERE / 'buffered-ranges.json'


def prepare(output, fetch, hashes):
    start = time.monotonic()
    output = output.absolute()
    output.mkdir(mode=0o700, exist_ok=True)
    corpus.require(not any(output.iterdir()), 'fresh private shader-range fixture required')
    source = output / 'source'
    rows = json.loads(corpus.LOCK.read_bytes())
    index = json.loads(BUFFERED.read_bytes())['providers']
    counters = {'zipRangeRequests': 0, 'zipRangeBytes': 0, 'windowRetriesAfterStall': 0}
    counter_lock = Lock()

    def observed_fetch(first, end):
        # A transient failure of one official range must not discard already authenticated
        # siblings. Keep the original per-window response checks, whole-piece digest and
        # acquisition deadline; refuse identity or integrity failures immediately.
        for attempt in range(4):
            try:
                result = fetch(first, end)
                break
            except corpus.Invalid as failure:
                if str(failure) != 'stock ZIP range unavailable after three attempts without progress' or attempt == 3:
                    raise
                with counter_lock:
                    counters['windowRetriesAfterStall'] += 1
                time.sleep(8 * 2**attempt)
        with counter_lock:
            counters['zipRangeRequests'] += 1
            counters['zipRangeBytes'] += len(result)
        return result

    allowed = stock_shader_ranges.materialize(source, rows, observed_fetch, hashes, index_path=BUFFERED)
    ledger = {path.relative_to(source).as_posix(): spans for path, spans in allowed.items()}
    assert len(ledger) == 16 and sum(map(len, ledger.values())) == 40
    (source / 'valid-mpq-extents.json').write_text(json.dumps(ledger, sort_keys=True) + '\n')

    # The complete MPQs were never read. Bind paths, logical lengths and each verified interval's
    # exact content pin in a dedicated QA journal, with no claimed whole-file digest or ZIP import.
    journal = ['qa-verified-shader-extents-v1']
    for name in sorted(ledger):
        path = source / name
        journal.append(f'provider\t{name}\t{path.stat().st_size}')
        for span, pinned in zip(ledger[name], index[name], strict=True):
            assert tuple(span) == (pinned['offset'], pinned['offset'] + pinned['bytes'])
            journal.append(f'extent\t{span[0]}\t{span[1]}\t{pinned["sha256"]}')
        path.chmod(0o400)
    raw = ('\n'.join(journal) + '\n').encode('ascii')
    key = hashlib.sha256(raw).hexdigest()
    store = output / 'import-metadata'
    selected = store / 'generations' / key
    (selected / 'data').mkdir(parents=True)
    (selected / 'journal.tsv').write_bytes(raw)
    (selected / 'complete').write_text(f'format=1\nclientBuild=12340\nrequest={key}\nsource={key}\n')
    (store / 'current').write_text(key + '\n')
    report = dict(scope='official-stock-shader-windows-with-private-qa-journal', providers=len(ledger),
                  intervals=sum(map(len, ledger.values())), verifiedBytes=sum(b - a for v in ledger.values() for a, b in v),
                  importFixture=key, rangeLockSha256=hashlib.sha256(BUFFERED.read_bytes()).hexdigest(),
                  torrentSha256=corpus.TORRENT_HASH, elapsedSeconds=round(time.monotonic() - start, 3), **counters)
    (output / 'source-metrics.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    deadline = time.monotonic() + corpus.DEADLINE
    print(json.dumps(prepare(args.output, lambda a, b: corpus.range_bytes(a, b, deadline), corpus.torrent_pieces())),
          flush=True)
