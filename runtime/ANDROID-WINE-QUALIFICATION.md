# Android x86_64 reconstructed-client Wine diagnostic

This is an isolated, debug-only Android13 emulator fixture. It runs the actual
reconstructed Windows x64 client, not an imported stock executable. It establishes
no ARM64, Thor, graphics, audio, authentication, world-entry or gameplay result.
The normal application and production ARM64 runtime selection remain separate.

The input client is `97b347ee034551ea78dc905c3e209667534e6283`, measured from
successful upstream run41007244092. Its Windows entry, offline-policy and loopback
diagnostics passed before selection. The Wine source is the ARM64 candidate's
exact `a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29`, built separately for x64 against
the signed frozen Debian12 package snapshot. The source-only Wine workflow first
builds, normalizes and independently reads back a fresh rootfs without a prefix.
The runtime input lock selects only a successfully completed build and its exact
binary/source archive bytes; a floating branch never selects a payload.

`fetch_android_wine_probe.py` requires successful source-bound runs and matching
artifact metadata before downloading, then checks the complete archive hashes.
The provider builder reconstructs the expected client manifest from the actual
PE files using the selected client's committed parser, verifies x64 imports and
layout, and selects only the reconstructed EXE, its Xvid DLL, manifest/limits,
committed validators and original notices. The provider verifier reconstructs the
whole provider from those original inputs and checks exact final APK members.
The runtime archive must be stored uncompressed inside the APK. Production,
MySQL, shader and presentation providers cannot be combined with this profile.

`wineProbeProviderDir` enables only `app/src/wineProbeAndroidTest`, requires the
explicit x64 native-owner and PRoot probe profiles, and disables release variants.
The instrumentation requires the actual installed tracer/loader's pinned bytes,
API33/targetSdk35 and debug flags. The host harness additionally requires a fresh
emulator installation; it refuses physical devices and existing application data.
No Android policy, target SDK, executable-file permission or production ABI is
relaxed to run the fixture.

The real production archive cache and installer stream/read back the Wine rootfs
into an immutable private generation. Client binaries and diagnostic output use
a separate private work directory. Each of four bounded owned PRoot invocations
runs one fixed Python phase: create a Wine prefix, execute entry diagnostics,
execute offline-policy diagnostics, then execute loopback transport diagnostics.
The latter invokes the actual `--loopback-check --local-offline` client path.
Normal zero exits and `wineserver -w` completion are mandatory for every phase;
forced termination cannot become a successful result. Failures attempt bounded
cleanup of only the fixture prefix and owned processes. Logs remain bounded and
must not have lost bytes for a passing phase.

The guest and host both validate original C++ receipts against the exact client's
committed validators. The host reads the original files independently, binds all
three to the installed provider/runtime/client/build identities and the emulator
fingerprint, and requires all diagnostic checks. It does not infer game startup
from a clean Wine exit. `CommonMain`, asset loading, authentication and gameplay
flags remain false. No game assets or user accounts are needed for these checks.

Before execution, `package_android_wine_sources.py` retains:

- The exact complete Wine/Debian source artifact, including Wine's original
  archive/license/configuration, every installed runtime **and build** package's
  original Debian sources and descriptors, and the runtime-build integration tree.
- The complete selected client Git tree and exact upstream Xvid archive; its
  original build recipes, bundled dependencies and license notices remain intact.
- PRoot's originals, patches and tracked recipes, glibc originals, and every
  actual x64 talloc relinkable object. Object bytes must match the inventory bound
  into the same provider build receipt; matching an ELF header alone is insufficient.
- The complete current integration Git tree containing all Android/native source,
  launch helpers, validators, build scripts and licenses.

Source ZIP/ZIP64 central directories are bounded before allocation. Every original
Debian archive is read and hashed; descriptors must cover the exact runtime/build
source-package union. Extra files, missing sources, changed object bodies and
overwrites fail. Source output is a separate companion, never application assets.
The workflow retains this companion even when subsequent Android execution fails.

The fixture and source guards pass on the development host using the actual
selected client artifact and real x64 PRoot source objects. These are source,
packaging and receipt checks. A completed Android execution receipt is required
before claiming the named Wine/client diagnostic behavior; the first actual run
failed before client execution, as detailed below.

The measured runtime from successful source build41011458046 passed another
complete local archive readback: 10,191 entries, 673,993,620 regular-file bytes and
964 links. All 24 focused runtime/provider/source/receipt groups pass, including
the real selected client payload and relinkable-object mutation controls.
The opt-in native x64 APK, instrumentation APK and Android lint build passed in
30 seconds, and the final APK's exact provider/native bytes passed verification.
This local test APK is 204,295,879 bytes, SHA-256
`de01a7befee0aa58833acae5803787267f404ea572b91d648d530b661ab88218`;
it has not been executed on Android and is not a Thor candidate.

Actual emulator run41015479987 at integration
`386b537723f4cf8f60920b7e92ff02959246f484` passed original artifact recovery,
complete Wine/Debian source validation, source sealing, APK build and byte checks.
Its prefix phase exited 1: Wine could not change `ntdll.dll`'s `.text` section
protection and then reported exception-stack overflow. No reconstructed-client
phase ran and all execution qualification flags remain false. Evidence artifact
12960040385 is 53,716 bytes, SHA-256
`1a2bfc95c1408dc970f819adda13bd85e25ce2af34ae18b8b42cea58a9d6865b`.
The complete retained corresponding-source artifact12959298932 is 929,858,045
bytes, SHA-256 `d1f70a1a25117aa50c0bb2dfe93294d8ff1883206b46d2f86c2b0f90e5253095`.

The next diagnostic compares anonymous, direct file-backed RX/RWX, and clean or
modified private file-backed RW-to-RX mappings inside the same guest/private
filesystem. It reports exact syscall success and numeric errno, verifies its
fixed fixture bytes remain unchanged, and never executes mapped bytes. Wine's
existing prefix/client failure gate is unchanged. Whether Android rejects a
particular transition remains a hypothesis until this comparison runs; no
target-SDK, permission, SELinux or device policy changes are made.
