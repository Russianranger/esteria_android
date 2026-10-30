# Android client-runtime installation

The launcher offers explicit preparation of the pinned Wine archive. Setup runs as
foreground work with progress, cancellation and a persisted interruption marker.
It downloads approximately 585 MiB and expands about 2.46 GiB; initial setup needs
roughly 3.2 GiB of free storage before game assets. It does not launch Wine or
claim gameplay readiness. Runtime startup remains gated.

## Storage and recovery

`runtime/runtime-sources.lock.json` supplies the exact HTTPS archive length/hash,
entry and byte limits, required binary identities and installation metadata. The
selected package plus installation profile determine a canonical source identity;
unrelated server or graphics lock changes do not invalidate the Wine generation.
The APK embeds the lock. Imported game data, mutable databases and saves remain
outside these replaceable runtime directories:

- `runtime-downloads/`: owned partial downloads and verified cached archive.
- `runtimes/wine-arm64/staging/`: resumable private extraction generations.
- `runtimes/wine-arm64/generations/`: verified complete generations.
- `runtimes/wine-arm64/current`: small atomic active-generation pointer.

The downloader uses bounded buffers and authenticated HTTPS, checks pinned length
and SHA-256, supports validated range continuation, and refuses an unowned partial
file. A verified private cache avoids repeated network access and whole-archive
hashing when its recorded file identity is unchanged. Preparation first recognizes
a valid current generation and therefore needs no network on a normal retry.

The installer streams gzip/GNU tar; PAX metadata is not supported. It bounds paths,
member sizes, total bytes, entry count and in-memory metadata. Regular files are
written and read back before journaling. Resume compares the journal with actual
private file identity and archive bytes; it does not blindly trust a receipt.
Contained symbolic/hard links are created after payload verification. Inventory
closure rejects unexpected retained files, including remnants of a rejected
archive. Required files are rehashed and architecture-checked on cached activation.
Directory fsync support is recorded; completed generations promote atomically and
the current pointer changes last. Failure preserves the previous active runtime.

## Actual evidence and limits

Seventeen focused Java test groups pass with a 64 MiB heap, and independently
with 32 MiB. They cover traversal/link safety, malformed tar metadata, bounded
payloads, cancellation, torn journals, stale files, download/cache behavior,
required-file tampering and activation preservation.

The actual pinned 612,917,105-byte archive passed extraction and readback on Linux
with `-Xmx64m`: 14,092 paths, including 11,844 regular source files, 45 hard links,
988 symbolic links and 1,215 directories. A retry reused all 11,844 regular files
and copied zero payload bytes; completed-generation reuse also copied zero.
Recorded evidence SHA-256:
`e27689b59820054ac9c20670d68edd7d785e3182d0cb9e611977d40a5cdfddda`.

The Android adapter compiles, clean assemble/lint pass, and the APK's bundled
PRoot/loader bytes match the verified provider. Android filesystem execution,
PRoot guest launch, display/audio/input and gameplay remain separate unpassed
gates. This installer currently covers the client Wine candidate; a compatible
server rootfs/content installation adapter is still required. Retention/cleanup
of superseded generations must be implemented before storage-managed releases.

Run the bounded behavior checks with:

```sh
./gradlew --no-daemon :core:runtimeInstallerTest
```

Changing `-PprootProviderDir` should be followed by `:app:clean` before rebuilding,
so previously merged assets cannot contaminate verification.
