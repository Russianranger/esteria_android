# Optional Android guest bridge provider

This provider installs the measured ARM64 glibc frame, XTest input, and ALSA PCM
helpers into a separate immutable generation. It does not start Wine, modify the
Wine rootfs, start an Android presentation/audio session, or qualify gameplay.
The three executables remain Linux guest binaries, not Android/Bionic libraries.

## Inputs and reproduction

`android-provider.lock.json` pins the successful native ARM64 build at integration
`61bf8a134845276cb78430884d557e477ff286aa`, workflow run `40995565147`, artifact
[`12951430269`](https://github.com/Russianranger/esteria_android/actions/runs/40995565147/artifacts/12951430269).
The original ZIP is 142,339,282 bytes, SHA-256
`f3365863da63074fb18bf9809cb7df38c161d47e5efe40f2f32c1fe5f6847e3b`.
Each selected file has an independent size/hash pin, including the build receipt,
original build recipe, notices, project sources, and statically linked Xtst
original source archives and Debian changes. Current project source hashes,
bridge reference and build dependency lock must still match these inputs.

On a Linux build host with Python 3.11+ and binutils `readelf`:

```sh
python3 tools/provider_guest_bridges.py build \
  --artifact /absolute/path/to/downloaded-12951430269.zip \
  --output /absolute/path/to/new-guest-bridge-provider
python3 tools/provider_guest_bridges.py verify \
  --provider /absolute/path/to/new-guest-bridge-provider
```

The original artifact is convenient, not required. A clean source checkout can
rebuild the exact pinned native Debian image and helper source via
`.github/workflows/guest-bridges.yml`. Use source revision `61bf8a1...`, the exact
`runtime/bridges` recipe/lock at that revision, native ARM64 Docker with its CA
secret, `INTEGRATION_REVISION` set to the full revision above, and the workflow's
`guest-export` target. Retain its `notices/ESTERIA-GPL-3.0` and
`corresponding-source/bridge-reference.json` copy steps. Pass the resulting
payload directory instead of a ZIP:

```sh
python3 tools/provider_guest_bridges.py build \
  --payload /absolute/path/to/rebuilt/payload \
  --output /absolute/path/to/new-guest-bridge-provider
```

Rebuilt inputs must match every measured byte pin. A different binary or receipt
is rejected and needs an explicit new build review/pin update. The provider never
fetches code or accepts a receipt as its own authority. Docker is a build host
tool; the Android app does not use Docker. The original recipe is also retained
inside the installed source tree so later test-only recipe changes do not erase
its provenance.

The small installed archive retains complete project sources, MIT/GPL notices,
and all three pinned libXtst source originals. The remaining original direct
build inputs (compiler, glibc and other library sources) are identified by the
included `SOURCE-MANIFEST.json` and snapshot URLs/hashes in the included build
lock. The complete original artifact contains them. Preserve that source
companion with any release; Actions artifacts expire. This package does not
establish source closure for the separate Wine rootfs.

## APK and installer

The optional Gradle property adds verified assets and a build flag. Ordinary
source builds continue to work without a provider; the adapter reports its
absence rather than pretending the helpers are installed.

```sh
./gradlew :app:assembleDebug \
  -PguestBridgeProviderDir=/absolute/path/to/new-guest-bridge-provider
python3 tools/provider_guest_bridges.py verify \
  --provider /absolute/path/to/new-guest-bridge-provider \
  --apk app/build/outputs/apk/debug/app-debug.apk
```

The original gzip bytes use the APK asset suffix `.archive` and must be
`ZIP_STORED`. Android's asset packaging can decompress `.gz` input implicitly;
the verifier checks the final APK bytes and compression, not only build settings.
No generated provider or binary is committed to the application repository.

`GuestBridgeSetup(Context, privateRoot)` parses the bounded asset descriptor;
`prepare(progress, cancellation)` uses `EmbeddedArchiveCache` and
`RuntimeInstaller`. It retains owned partial copies, rechecks source hashes,
validates all installed files and ARM64 ELF headers, publishes a complete
generation atomically, and reuses a verified completed generation without
recopying the archive. All archive entries are regular files, with no hardlinks,
symlinks, or mutable guest state. App updates retain old generations and saves.

The private stores are `runtimes/guest-bridges-arm64` and
`runtime-embedded-cache/guest-bridges-arm64`. The 64MiB setup safety margin matches
the shared installer. The current provider archive is 469,031 bytes, SHA-256
`a91e2e7cf74957c7caf2c7e85de2a6ee8952d273b3f5e3f18cecb06127791c39`;
its 30 files total 745,949 bytes. Every file, including notices and sources, is a
required hash-pinned component.

## Session integration contract

Call `requireWineArchive(actualWineArchiveSha256)` before using the generation.
The required Wine archive SHA-256 is
`f036c00a290abb953bec26be80c4d8fe492fd986e7a589c51008124432c8641e`.
This check binds the measured Debian ABI; it does not establish runtime success.
Use an owned PRoot bind from `current()` to `/esteria-bridges`, leaving the Wine
rootfs unchanged. Keep writable session sockets, Wine prefixes and logs outside
that immutable generation.

| Purpose | Guest path / setting |
| --- | --- |
| Frame helper | `/esteria-bridges/bin/esteria-x11-frame /session/frame.sock 30` |
| Input helper | `/esteria-bridges/bin/esteria-x11-input /session/input.sock` |
| ALSA configuration | `ALSA_CONFIG_PATH=/esteria-bridges/etc/alsa-esteria.conf` |
| PCM receiver socket | `ESTERIA_AUDIO_SOCKET=/session/audio.sock` |
| Plugin | `/esteria-bridges/lib/alsa-lib/libasound_module_pcm_esteria.so` |

The included ALSA configuration includes the guest's default `alsa.conf` and
names this plugin through an explicit absolute `pcm_type.esteria` library path.
It selects signed 16-bit stereo 48kHz through ALSA's `plug` converter. Preserve
the runtime's `LD_LIBRARY_PATH` and existing/default `ALSA_PLUGIN_DIR`; neither
needs replacement. In the private Wine prefix, select ALSA audio and disable
Pulse for that session while retaining any other DLL overrides. Start the owned
Android PCM/frame receivers before their producers and provide the owned X11
`DISPLAY`; socket readiness and cleanup belong to the session supervisor.

## Evidence and limits

The builder rechecks all three actual ELF files with `readelf`: AArch64,
expected interpreter, bounded glibc symbol requirement, allowed `DT_NEEDED`
imports, and no RPATH/RUNPATH. The measured maximum glibc versions are 2.34 for
the helpers and 2.17 for the plugin, compatible with the pinned guest's 2.36
version ceiling. This is static inspection, not an ELF dependency-closure or
execution result.

Five provider tests cover exact input/source identity, synthetic wrong-ABI
rejection, deterministic ZIP/rebuilt-directory equivalence, mutation rejection,
unsafe archive entries, publication refusal, and stored APK asset policy. The
real archive also passed the actual Java installer under a 32MiB host heap,
including all 30 file hashes, ARM64 header checks and completed-generation reuse.
Android presentation/audio and Wine-to-ALSA tests have their own receipts; none
of their outcomes is inferred from this package or converted into a gameplay
qualification flag.
