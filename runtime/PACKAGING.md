# Runtime packaging foundation

The candidate in `runtime-sources.lock.json` is a **Linux ARM64 Wine guest** for
the reconstructed **Windows ARM64** client. This is not a native Android client.
The preparer acquires and stages files; it never starts Wine, PRoot, a database
or game code. It is not wired to the Android launch button.

## Exact inputs and practical compatibility

The public [UO v0.2.0 release](https://github.com/Russianranger/uo-android-launcher/releases/tag/v0.2.0)
provides `client-runtime-arm64.tar.gz`: 612,917,105 compressed bytes, SHA256
`f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`.
The lock also pins its 450-byte manifest, three corresponding-source archives,
fifteen core binary identities, and the expected 14,092 entries / 2,637,799,241
file bytes. The manifest was fetched independently and its identity checked.
The original inventory came from the pinned FtA launcher reference; an Esteria
audit receipt must be generated before using the archive here.

The 2026-10-30 Esteria host audit acquired the complete archive and passed those
identities and counts. Full staging and file readback also passed. The measured
package inventory is now pinned: libc6 `2.36-9+deb12u14`, libstdc++6
`12.2.0-14+deb12u1`, libssl3 `3.0.20-1~deb12u2`, Python 3 `3.11.2-1+b1`
and Vulkan loader `1.3.239.0-1`. All four requested CRT/Vulkan DLL files were
found; their exact hashes and actual PE machine values are now in the lock.
**VCRUNTIME140_1 has machine `0x8664` even though it resides under
`aarch64-windows`**. Pure ARM64 import resolution is therefore an explicit
execution-test requirement. Directory names alone are not ABI evidence. This
host evidence includes no Wine execution. Compare the actual ARM64 build's
imports; the x64 build requiring this DLL does not prove the ARM64 build needs it.

The exact [runtime recipe](https://github.com/Russianranger/uo-android-launcher/blob/0fca7bdc7045c2a1b70ce9f0bef6d31e968b42de/client-runtime/Dockerfile)
uses Debian Bookworm and Wine commit
`a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`, configured for
`arm64ec,aarch64,i386`. It contains ARM64 ELF Wine/wineserver and ARM64 PE
kernel32/ntdll. FEX commit `320c5f18475b0c8a7e99c51a5fdc5b5e35b147ab`
supplies the x86/x64 translators. Pure ARM64 client code should not require CPU
translation, but that is an architecture assessment, not an observed execution
result. The earlier FtA tests exercise x86/x64 fixtures, not this client.

The recipe includes Python 3, TigerVNC, X11, ALSA, PulseAudio and Vulkan libraries.
It disables Wayland and GStreamer. These are useful Linux dependencies, but do
not connect Android surfaces, Adreno graphics, AudioTrack, controllers or touch.
The pinned binary is reproducibly obtainable; its original Docker recipe has
floating base-image/package inputs, so a byte-identical source rebuild is not
claimed.

**Keep the server runtime separate.** Current server CI targets Ubuntu 24.04,
while this client rootfs was built from Debian 12. Its libc, Boost, OpenSSL and
C++ library closure has not been matched to the server executable. Do not copy
Ubuntu-built `worldserver` into this rootfs and assume it runs. No MySQL server
is provided by this package. The future server package needs its own exact
libraries, Python standard library, MySQL 8 server/client, package inventory and
raw `SELECT VERSION()` value, including any distribution suffix. See
[LOCAL-SERVER.md](LOCAL-SERVER.md) for the database bootstrap contract.

## Use on a Linux build host

Python 3.11 or newer is required. Keep caches and prepared trees outside Git.
Only `--download` enables network access. A matching offline copy with the
locked filenames works without that flag.

```sh
# Setup acquisition + static audit, without extracting or executing anything.
python3 tools/prepare_runtime.py --cache /private/esteria-runtime-cache \
  --download --report /private/wine-audit.json

# Offline preparation in a NEW directory; existing directories are refused.
python3 tools/prepare_runtime.py --cache /private/esteria-runtime-cache \
  --stage /private/wine-candidate

# Optionally compare direct imports from the reconstructed ARM64 build.
python3 tools/prepare_runtime.py --cache /private/esteria-runtime-cache \
  --client-manifest /private/arm64-client/client-build.json \
  --report /private/wine-client-imports.json

python3 -m unittest tests.test_runtime_packages -v
```

Output is `wine-candidate/rootfs/` plus `package-receipt.json`. Static reports
include the full pinned Debian package inventory, `os-release`, ARM64 Windows
module identities, and presence/absence of MSVCP140, VCRUNTIME140,
VCRUNTIME140_1 and Vulkan loader DLL files. Optional client import comparison
lists missing files. Wine can resolve API sets through forwarding rather than
individual DLL files; file presence alone also cannot prove export coverage.
Neither case establishes successful loading or gameplay. Delay-loaded and
`LoadLibrary` dependencies are not covered by the client's direct import list.

Download writes use a 256 KiB buffer, exact byte count and SHA256, then publish
without replacing an existing cache file. Redirects must remain HTTPS. A
failed download removes only its own temporary file; retry restarts that
download. Already valid cached archives are reused. A mismatching existing
cache entry is refused, not silently overwritten.

Preparation checks the exact compressed identity before parsing, bounds gzip
output and GNU extended headers, and streams each file. It refuses traversal,
duplicates, special/sparse files, PAX metadata, non-directory parents and unsafe
hard links. The locked upstream packer uses GNU tar. Link creation is delayed
until the complete member graph has passed; absolute guest symlinks become
equivalent relative links inside the prepared root. Files are private to the
owner, retaining executable permission where required. Every staged file is
read back and hashed before a flushed receipt and the whole directory are
published under an exclusive preparation lock. No existing runtime, import,
database or Wine prefix is replaced. These are owned build directories, not a
sandbox against another process concurrently modifying the same filesystem.

A caught failure removes the owned staging tree. A killed process may leave a
hidden staging directory; it is never considered installed and is not merged
or promoted automatically. The next attempt uses a fresh staging directory.
Interrupted updates therefore cannot turn an incomplete tree into a ready one.
The Android installer, incremental update strategy and retained runtime lease
still need implementation. Reserve the compressed archive plus the expanded
tree and room for the prior runtime before an eventual application update.

## Android execution boundary

The read-only [FtA bridge reference](https://github.com/Russianranger/fta-launcher/blob/7a9ce45988f295824d20c9ff7436a77a0baa4f07/tools/build_client_bridge.py)
uses Termux PRoot commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`,
talloc 2.4.3, the existing SysV memfd/seccomp patches, and a separate
`PTRACE_O_EXITKILL` ownership patch. Its evidence establishes these interfaces:

| Component | Required form |
| --- | --- |
| Android tracer | AArch64 PIE; `/system/bin/linker64`; `libc.so`/`libdl.so` only |
| PRoot loader | AArch64 ET_EXEC; no ELF interpreter or dynamic dependencies |
| Segment alignment | At least 16 KiB in tracer and loader |
| APK location | Extracted `nativeLibraryDir`, `extractNativeLibs=true` |
| Guest libraries | glibc binaries inside the private rootfs, entered through PRoot |
| Ownership | Owned native process handle; EXITKILL; stop/reap before releasing data |

The reference launches its packaged tracer with `PROOT_LOADER`, a short private
`PROOT_TMP_DIR`, `PROOT_NO_SECCOMP=1` and `PROOT_DONT_POLLUTE_ROOTFS=1`, and exposes
real `/proc` and `/sys` CPU topology. It found Unix-socket path length and
leftover mode-zero bind placeholders to be real failure cases. Copying only
`libproot.so` omits its loader, ownership and cleanup requirements. Downloaded
guest ELF files must remain data; `chmod +x` and direct execution from Android
`filesDir` is not this architecture. PRoot is a compatibility mechanism, not a
security boundary.

No PRoot binary is currently included in Esteria. The exact original bridge
source archive is pinned for rebuilding. Before enabling the Android launch
button, build and package the bionic tracer/loader and prove normal, Stop,
backgrounding and tracer-death behavior on our own process bridge. Linux
chroot/PRoot qualification may advance independently of Android. Xvid decoding
and a synthetic ARM64 PE import test can run without game assets; actual
Vulkan presentation, audio and controller integration remain separate gates.

## Notices and source availability

The lock records Wine LGPL-2.1-or-later, FEX's MIT license and dependency notices,
PRoot GPL-2.0-or-later and talloc LGPL-3.0-or-later source locations. Preserve
the runtime's `usr/share/doc/*/copyright` files and exact
`etc/memento-client-packages.txt`; do not strip them during packaging. The
Wine, FEX and bridge corresponding-source archives have exact size/hash/URL
pins. Debian package source closure is not yet staged, and reference notices
contain older Box64/Wine sections that do not describe this candidate.

This foundation downloads upstream files for development and does not publish
a combined runtime binary. Before redistribution, assemble and verify the
complete corresponding source/notices for the actual shipped packages,
including our patches and build recipes. Source links alone are not recorded
as completion of that work. No proprietary client data is included.

## Remaining qualification

Synthetic package tests cover bounded downloads, identity mismatch, cache
preservation, archive traversal and link attacks, component architecture,
interruption, atomic staging and static import diagnostics. A successful audit
is evidence of bytes and structure only. All receipts explicitly leave Wine
execution, Android runtime, server inclusion, rendering, audio and login false.
Do not use this output as the user's main device-test candidate.
