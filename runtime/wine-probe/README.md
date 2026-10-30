# Android x86_64 Wine qualification fixture

This separate test fixture builds Wine from the exact source archive used by the
ARM64 candidate (`a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`) for GNU/Linux x86_64.
The Debian12 amd64 OCI manifest, signed frozen repositories, Wine archive and
license bytes are pinned. FEX is unnecessary on an x86_64 emulator. No production
runtime lock, ARM64 provider, application target SDK or Android policy changes.

The source-build workflow initially records only build and archive-readback
evidence. It does not initialize a prefix or start the client. It retains the
original Wine source, build configuration, all installed Debian runtime and build
package sources, and the exact integration Git tree. The rootfs package retains
installed copyright notices and records exact critical ELF/PE bytes and hardlink
copy space. These archives are intermediate qualification inputs, not a user APK.

An isolated debug APK will subsequently use the already qualified x64 Bionic
PRoot/loader and real native process owner to execute the actual reconstructed
Windows x64 client's entry/offline diagnostics, followed by its bounded transport
diagnostic after upstream qualification. This is pending: no Android Wine,
ARM64, graphics, audio, authentication, world-entry or gameplay pass is claimed.

Build on an x86_64 Docker host with `runtime/wine-probe/Dockerfile` and target
`runtime`, mounting a trusted HTTPS CA bundle as BuildKit secret `build_ca`.
Export a newly created, never-started container, copy its
`/etc/esteria-wine-probe.json`, then use
`tools/package_android_wine_runtime.py --docker-export EXPORT --runtime-metadata
METADATA --output NEW_DIRECTORY`. The `source-export` build target retains the
complete source companion. `.github/workflows/android-wine-runtime.yml` is the
reproducible invocation. `tests.test_android_wine_runtime` checks bounded staging,
actual ELF/PE architecture rejection, exact scope/source pins, hardlink budget,
escaping links and no-overwrite behavior with synthetic archives.

The initial source build in run41008440024 compiled Wine successfully but failed
at installation because this pinned Wine revision has no `install-strip` target.
The recipe uses its actual `install` target with `INSTALL_PROGRAM_FLAGS=-s`;
the pinned `tools/makedep.c` supplies the correct native/PE `STRIPPROG` for each
installed program. Silent make mode avoids clipping compiler diagnostics behind
BuildKit's command-output limit. The corrected source/runtime build and complete
source export passed in run41011458046 at
`f963225d900961c3696880bc6c0c537aa741577f`; exact runtime and source artifact bytes
are now pinned in `runtime-input.lock.json`. The normalized runtime is 193,915,664
compressed bytes and 673,993,620 regular-file bytes; hardlink-copy fallback can
require 313,010,682 additional bytes. It contains no initialized Wine prefix.
The source manifest records 158 source packages and 505 original Debian files.

The Android fixture is documented in `runtime/ANDROID-WINE-QUALIFICATION.md`.
The source ZIP exceeds the connector's 512 MiB local download limit. The separate
execution workflow therefore uses the ordinary authorized Actions read API,
streams its exact 876,847,394-byte archive, and requires full source/descriptor
validation before building/executing the fixture. Local ZIP/manifest checks do
not claim that larger source-content validation or an Android execution result.

The actual Android mapping comparison in run41017052972 found `EACCES` only
when adding executable permission to a modified private file-backed page.
Anonymous modified pages and direct/clean file mappings succeeded. The next
source build applies the exact locked `android-private-pe-copy.patch`; only
`WINE_ANDROID_PRIVATE_PE_COPY=1` selects anonymous private PE image copies.
The default desktop path and real shared-section mappings remain unchanged.
Checked reads, bounded zero tails and failed final protections cannot silently
report a loaded image. The Android helper explicitly selects this profile.

The `private-image-test-export` Docker target executes the same source-built PE
EXE/DLL pair under default and opt-in modes on Linux x64. It checks image data,
BSS, relocation with an occupied preferred base, actual page protections, and
shared writes across a live child, while retaining bounded public evidence.
Test prefixes and test executables are never exported into the runtime rootfs.
This host gate must pass before binary artifacts are published; it does not
qualify Android or ARM64. Patch, test sources and process-owner helper bytes are
hashed in `sources.lock.json` and retained with the complete corresponding sources.
The measured `runtime-input.lock.json` must be replaced only after the new source
build, host gate, archive readback and source export succeed; its previous
unadapted runtime is intentionally incompatible with the new source lock.
The exact mapping evidence, source rationale, shared-section bounds and helper
validation are recorded in [PRIVATE-PE-COPY.md](PRIVATE-PE-COPY.md).
