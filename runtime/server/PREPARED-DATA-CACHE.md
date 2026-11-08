# Prepared world data admission

The stock Android session checks source identities and the active receipt under its retained import lease. An eligible private generation can reuse a SHA-anchored stat inventory. Each session runs a new filesystem trial with the packaged PRoot and compares every captured file and directory. The full byte/header verification remains available to normal startup and the explicit world-data integrity check.

A warm admission requires an independently approved installed data reader, compatible output recipe, matching cache implementation, generation and receipt. The filesystem trial checks that the selected root and scratch share a device, the Android owner excludes a second writer and same-size writes with restored mtime, replacement and directory entry changes update captured metadata. Nodes with external hard links, multiple filesystem devices or timestamps too recent for the trial use full verification. Corruption that preserves every captured stat field requires a full audit.

## Candidate and authority

The Python sealer first checks the exact generation, receipt, helper identity,
provider projection, every payload SHA-256 through a stable open descriptor, and
the retained header-preflight result. It writes a bounded canonical JSON-lines
candidate containing every file and directory's device, inode, mode, UID, GID,
link count, size, nanosecond mtime and nanosecond ctime. An exclusive publication
step preserves any candidate another operation has already published. Cancelled
or failed seals leave no new completed candidate.

The Android owner checks the successful dedicated verifier's bounded private stdout and copies the exact size/SHA-bound candidate from
its fixed owned-operation path to `state/prepared-data-cache`, outside guest
mounts. A typed selection binds the current generation, receipt bytes/SHA, output
recipe, installed data reader and cache implementation SHA. An index publication
failure leaves the verified operation-local candidate available for the same owner. The private index supplies the cache's
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
preserves every captured field is outside this mechanism's guarantee. Each later owner must acquire new locks and complete a new comparison. A stale
private index requests a full audit, then retires the matching pointer. The next
owner can seal the verified output again. Historical proof directories remain intact.

## Android 13 ARM64 measurements

The signed app’s Java publisher passed seven groups and the packaged PRoot passed 15 Python cache tests on disposable Redroid ext4. Three fresh ART processes independently verified the complete shader output. Killing a publisher during a 96 MiB replacement preserved the prior anchor and a fresh process successfully published the replacement. The interrupted process left an unselected pending directory.

Java and PRoot observed the same inode through both guest aliases. Android’s Java filesystem view reported the app UID and whole-second timestamps. PRoot’s root mapping reported UID 0 and nanosecond timestamps. The PRoot verifier compares its own tuples under an Android-held lease. Android anchors the exact cache digest privately. A separate app-UID owner reused all 10 nodes of a five-file disposable generation without reading any payload, and a same-size edit with restored mtime failed admission. A Thor session must independently qualify its volume and selection. [Measured Android and PRoot results](../evidence/prepared-data-cache-android13.json).

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
