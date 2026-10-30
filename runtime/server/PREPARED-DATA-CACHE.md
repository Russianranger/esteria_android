# Prepared-data cache qualification

The production world-data verifier still hashes every prepared payload and checks
its headers. `PRODUCTION_FAST_PATH_ENABLED` is `false` in both
`runtime/prepared_data_cache.py` and Core `PreparedDataCachePin`. No application
call site uses the optional cache. Android/PRoot stat qualification and a
source-owned capability check remain activation gates.

The proposed optimization covers only immutable, already prepared server data.
The current setup and session paths each fully verify that data, so a hypothetical
60 GiB prepared set can require about 120 GiB of payload reads across those two
boundaries. That is an estimate from the call paths, not a Thor measurement.
Imported-source, runtime-provider, source-selection and SQL verification remain
unchanged; this cache does not remove their cost or establish world coverage.

## Candidate and authority

The Python sealer first checks the exact generation, receipt, helper identity,
provider projection, every payload SHA-256 through a stable open descriptor, and
the retained header-preflight result. It writes a bounded canonical JSON-lines
candidate containing every file and directory's device, inode, mode, UID, GID,
link count, size, nanosecond mtime and nanosecond ctime. An exclusive publication
step preserves any candidate another operation has already published. Cancelled
or failed seals leave no new completed candidate.

Core's package-private publisher copies the exact size/SHA-bound candidate from
its fixed owned-operation path to `state/prepared-data-cache`, outside guest
mounts. A typed selection binds the current generation, receipt bytes/SHA, helper
generation and cache implementation SHA. The private index supplies the cache's
trusted SHA; a caller boolean, imported cache file, self-declared hash or Intent
path cannot provide authority. Files are private, single-link regular files under
private canonical directories. Missing index state requires full verification;
malformed state, aliases, hard links or unsupported hard-link checks fail visibly.
Explicit replacement proofs preserve previous generations.

A warm comparison hashes the bounded receipt/cache metadata and freshly compares
every captured file/directory stat tuple. It reads no data payload and performs no
directory enumeration. Directory tuples detect added or removed entries, including
mutations followed by restoration of mtime. Every lease acquisition needs a fresh
complete comparison: setup releasing its lease before gameplay acquires another
does not confer continuous ownership or permission to reuse a previous comparison.
A mismatch requires full verification/recovery; it never rewrites the old receipt
or treats the cache's own contents as a new trusted pin.

Metadata can detect only changes exposed by the filesystem. Byte corruption that
preserves every captured field is outside this mechanism's guarantee. Linux host
results do not qualify Android ARM64, Android's Java filesystem provider, PRoot
aliases or the Thor. Production remains on full byte verification until the
platform and owner integration gates are met.

## Host evidence

`runtime/evidence/prepared-data-cache-host.json` records the exact modified source
identities and focused results. Actual Linux tests cover restored-mtime writes,
ctime/inode/directory mutations, links, modes, source/helper/receipt substitution,
malformed/truncated caches, cancellation, explicit resealing and competing
publication. The warm-cache test forbids payload inventory/hash and header-reader
calls. A 64 MiB payload's full seal peaks below 8 MiB of traced Python allocation.

The prepared-data metadata reader also now allocates the stable descriptor's
actual size plus one byte, rather than its configured 64 MiB ceiling. A direct
tiny-receipt allocation regression and the streamed-payload regression pass.
Bounds, type checks and full production verification remain in place.

The Core private-index test runs actual filesystem operations at a 32 MiB heap,
including a 48 MiB streamed candidate. It qualifies index isolation and bounded
copy/hash behavior only. Synthetic header fixtures execute no real MPQ conversion,
Android guest, worldserver, gameplay or character persistence.

Run the focused checks with:

```sh
python3 -m unittest tests.test_prepared_data_cache tests.test_server_data_generation tests.test_server_data_packages
./gradlew :core:preparedDataCachePinTest :core:serverDataRunPlanTest :core:serverDataToolSelectionTest
```
