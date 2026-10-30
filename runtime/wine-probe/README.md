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
BuildKit's command-output limit. The corrected runtime build remains pending.
