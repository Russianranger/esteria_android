# Building Esteria Android

Build from `android/client-server`. `sources.lock.json` is authoritative; its branch labels never choose build inputs. Existing GPL-3.0 LICENSE is unchanged.

## Pinned sources
```
python3 tools/fetch_sources.py all
python3 tools/verify_protocol.py --client sources/client --server sources/server
```
Source preparation requires Git and Python 3.10+. It verifies full commit IDs and Eluna's gitlink, rejects modified or differently pinned checkouts, and never resets developer changes. Use `--offline` once all sources are prepared. To change a pin, review the source change, update the lock and use a fresh output directory. Server patches must be listed in order with SHA-256 in the lock.

## Windows reconstructed client
The passing reference matrix uses Visual Studio 2026 on Windows ARM64 and Visual
Studio 2022 on Windows x64, with matching C++ desktop tools, Windows SDK, CMake
3.24+ and Python. The ARM64 job runs natively on `windows-11-arm` with the
`Visual Studio 18 2026` generator. See client platform instructions for the pinned
source-built movie codec and architecture-specific optional integrations.

```sh
cmake -S sources/client/Tools/PlatformTests -B out/platform-arm64 -G "Visual Studio 18 2026" -A ARM64
cmake --build out/platform-arm64 --config Release --parallel 2
ctest --test-dir out/platform-arm64 -C Release --output-on-failure
```

```sh
cmake -S sources/client -B out/client-arm64 -G "Visual Studio 18 2026" -A ARM64 -DWOWDECOMP_EXTENDED_LIMITS=ON -DWOWDECOMP_CONTAINER_SLOTS=254 -DWOWDECOMP_QUEST_LOG_SLOTS=25 -DWOWDECOMP_MAX_CLASSES=32 -DWOWCLIENT_CRASH_LOG=ON
cmake --build out/client-arm64 --config RelWithDebInfo --target WowClient --parallel 2
```

ARM64 outputs are under `sources/client/bin/Win/ARM64`. For x64 use the VS 2022
generator, `-A x64` and separate build directories; outputs are `bin/Win`. Both
complete executables now compile/link in CI. Run `Tools/RuntimeManifest/generate.py`
with the exact source SHA, CI build identifier, binary directory, architecture and
generated `limits.json` before packaging. The client workflow contains the exact
invocation and packaged-DLL test. Shaders require matching imported data; see
[ASSET-REQUIREMENTS.md](ASSET-REQUIREMENTS.md).

## Linux ARM64 server
First build environment: Ubuntu 24.04 ARM64 with GCC, CMake, Ninja, Boost development packages, OpenSSL, MySQL 8 client development package, readline, bzip2 and zlib. Eluna uses the source revision in the lock and Lua 5.2.4. `.github/workflows/server.yml` provides the concrete build. It retains static scripts/modules and builds extraction tools. Two compiler jobs bound peak build memory.

MySQL 8 is required by the selected source. MariaDB is not a drop-in qualified substitution: both compile-time and runtime version checks reject it. Server artifacts do not include a seeded database, extracted game data or an Android runtime.

The three locked Eluna patches supply the missing `AreaTrigger` declaration,
`MapMgr.h` include and standalone integer/size type includes exposed by clean builds; `fetch_sources.py` verifies and applies it inside the exact
submodule. Compiler caches include actual compiler/package and source/patch
fingerprints and use two jobs/2 GiB. The cache can accelerate a failed build but
does not replace the source checks.

The separate dependency-image recipe in [runtime/server/README.md](runtime/server/README.md)
pins Ubuntu snapshot packages, MySQL and corresponding sources. Docker is used for
development builds and offline native ARM64 database qualification, not on-device execution.

## Android toolchain
JDK 17, Android SDK platform 35 / build-tools 35.0.0, Gradle 8.9 / AGP 8.7.3. The app and core are Java; host core tests require no game data. The Gradle wrapper pins its distribution hash. APK compilation initially validates the launcher and core only. The runtime and gameplay gates must pass before calling it a device candidate.

```sh
sha256sum --check gradle/wrapper/SHA256SUMS
./gradlew --no-daemon :core:check :app:assembleDebug :app:lintDebug
```

Set `ANDROID_HOME` and `JAVA_HOME` to installed toolchains. CI explicitly downloads
Android command-line tools 12.0 with a checked SHA-256 rather than assuming
`sdkmanager` exists on the runner. Use `-PsourceRevision=<full-application-commit>`
for recorded build provenance. Gradle embeds the complete source lock as well.

## Android native process bridge

[runtime/proot/README.md](runtime/proot/README.md) provides the exact source/NDK
inputs, one-job Bionic ARM64 build, corresponding-source companion, provider
validation and APK byte check. Pass `-PprootProviderDir=<verified-provider>` to
include the real PRoot/loader executables. Run `:app:clean` when changing provider
inputs to discard previously merged native/compressed assets. Plain launcher builds remain valid
without that provider. Build success does not qualify Android guest execution.

## Runtime staging and database qualification

[runtime/PACKAGING.md](runtime/PACKAGING.md) describes the pinned Wine candidate
and streaming, verified, offline-capable staging tool. A prepared rootfs is a host
artifact, not an Android runtime installation. Do not execute Ubuntu 24.04 server
binaries in that Debian 12 rootfs without a compatible dependency environment.

[runtime/WINE-QUALIFICATION.md](runtime/WINE-QUALIFICATION.md) describes the isolated
native ARM64 Linux codec, Vulkan and optional actual-EXE entry fixtures. It needs a real Windows ARM64 build artifact and
does not require proprietary game data. [runtime/LOCAL-SERVER.md](runtime/LOCAL-SERVER.md)
documents guarded MySQL initialization and authenticated readiness. Dedicated
database CI tests real engines; ordinary Python discovery skips those fixtures.

[runtime/ANDROID-INSTALLATION.md](runtime/ANDROID-INSTALLATION.md) documents the
app setup adapter and bounded Java installer. [runtime/SQL-PACKAGING.md](runtime/SQL-PACKAGING.md)
documents the source-backed module selection and reproducible GNU content archive.

## Android instrumentation builds

`./gradlew :app:assembleDebugAndroidTest` builds the pinned AndroidX runner and
reuses the core installer test source directly. `-PbuildVersionCode=<positive-integer>`
selects an increasing application version for update qualification. The emulator
workflow tests versions 1 and 2 with the same job-local debug key; these are internal
checks, not user-deliverable update candidates.

## Signing and reproducibility
Keep `*.jks`, `*.keystore`, private runtime configurations and game assets out of Git. A user-deliverable development APK must use one persistent privately stored key and carry the application/client/server source revisions and runtime hashes. This is not yet a bit-identical reproducible APK promise: SDK/compiler/runtime package locks and release signing qualification remain to be completed.

## Optional native application bridges

`-PnativeRuntimeBridge=true` builds process ownership and ARM64 presentation JNI
with NDK `28.2.13676358`, CMake `3.22.1`, static libc++ and 16 KiB ELF alignment.
Combine it with the verified PRoot provider for internal ARM64 build checks.
`-PnativeBridgeAbi=x86_64` builds only the process JNI for emulator qualification
and rejects the ARM64 PRoot provider. Neither build property enables gameplay.
See `runtime/ANDROID-EXECUTION.md`, `runtime/ANDROID-OWNER-QUALIFICATION.md` and
`runtime/PRESENTATION-AUDIO.md` for exact scope and source provenance.

The reviewed server dependency provider is optional:
`-PserverRuntimeProviderDir=<verified-provider>` bundles the exact normalized
Ubuntu/MySQL archive as an uncompressed `.archive` APK asset and enables its
resumable setup action. The suffix matters: AAPT transforms `.gz` assets even
when compression is disabled. `tools/provider_server_runtime.py` verifies both
provider and final APK bytes; use `runtime/server/ANDROID-PACKAGING.md` to build
it from pinned inputs. This packages database/server dependencies, not the
authserver/worldserver binaries or a gameplay-ready database.

For actual Android execution qualification use the dedicated workflows and their
documented explicit emulator-only properties. The production ABI stays ARM64.
`presentationEmulatorTest=true` requires an x86_64 debug/test native build;
`prootProbeProviderDir` selects a separate source-verified emulator fixture.
Neither may substitute emulator binaries for the ARM64 production provider.

`-PguestBridgeProviderDir=<verified-provider>` additionally bundles the pinned
ARM64 X11 frame/input helpers and ALSA output plugin. See
`runtime/bridges/ANDROID-PACKAGING.md` for source rebuild and verification. The
existing client setup action installs these into a separate generation after
checking the exact Wine archive identity. Repeating setup of a verified Wine
generation does not reopen or download its archive. Final APK validation must
check each selected provider, not only successful assembly.

To include the reconstructed Windows ARM64 client, build its measured provider
with `tools/provider_client_runtime.py` and pass all three properties:
`-PclientRuntimeProviderDir=<provider>`, `-PclientRuntimeArtifact=<original-zip>`
and `-PclientRuntimeSource=<exact-client-checkout>`. Pre-build verification checks
the original artifact and exact source; APK verification additionally uses
`verify --apk <apk>`. Client setup checks the embedded source-lock digest,
12340/254/25/32 protocol and pinned Wine identity before installing separate
immutable client files. See `runtime/client/ANDROID-PACKAGING.md` and retain its
corresponding-source companion beside any distributed APK.

`runtime/server/DEPENDENCY-RELEASE.md` describes the dependency-only preservation
workflow. It validates original runtime and complete corresponding sources before
publishing a write-once, hash-pinned prerelease. Until the workflow succeeds and
its actual publication receipt is committed, durable release availability is
not established. It publishes no application APK or game data.

Native builds also copy the exact installed NDK root, LLVM and sysroot notices
into APK assets, covering the linked static C++/compiler runtime notices. Missing
notice inputs fail the build. The mutable client view is exercised by
`:core:clientLaunchViewTest`; see `runtime/client/LAUNCH-VIEW.md` for its stopped
client requirement, loopback configuration and explicit loose-Interface gate.


`app/database-setup.gradle` packages the original Python bootstrap and its fixed
Android entry point, with a generated file-size/SHA-256 inventory. No separate
source copy or Python dependency download is needed. The optional server runtime
already contains the measured Python/MySQL binaries. This adapter is compiled but
not invoked by launcher setup until actual Android MySQL qualification succeeds;
see `runtime/ANDROID-DATABASE-SETUP.md` for the persistent guest-path contract.

The dependency-preservation workflow supports an already-owned exact-commit UI
draft. Its upload job only attaches verified missing assets, then a separate
read-only job verifies actual publication. It does not expand Actions permissions,
change default branches or substitute another tag target. See
`runtime/server/DEPENDENCY-RELEASE.md` for the concrete authentication boundary.


The server and guest-helper dependency releases have actual publication and
independent public-fetch receipts. The current client0f/seven-patch packaging
checkpoint replaces the application pin; its new dependency release is published
and independently fetched/verified without credentials. The historical69 release
remains available and unchanged. Scoped `dependency-release.lock.json`
files retain exact URLs/hashes and refuse stale mismatched provider inputs.

The optional `-PshaderToolsProviderDir=<verified-provider>` packages the exact
source-backed ARM64 compiler/translator. Client runtime preparation installs its
immutable files after verifying Wine compatibility. Generate the provider using
the durable, anonymously verified archive described in `runtime/shaders/RELEASE.md`.
This source bundle is 10,635,594 bytes; it contains no game data or generated game
shaders. Actual game shader generation remains a separate gated operation in
`runtime/SHADER-GENERATION.md` and is not run by ordinary launcher setup.

The optional `-PturnipProviderDir=<verified-provider>` installs the measured ARM64
glibc driver separately. Its original build ZIP/source companion must remain beside
the provider and accompany distribution, outside APK assets. See
`runtime/turnip/ANDROID-PACKAGING.md`; no driver is selected by the launcher and
Android/Adreno execution remains unqualified.

`server-requalification.yml` and `client-auth.yml` reuse the exact measured linked
six-patch binaries and artifact-contained lock, independent of the newer application
lock. Docker is only their native reference environment. Android execution uses
PRoot and the application-owned process bridge, never device Docker.


## Server programs, SQL sources and Android setup

`-PserverProgramsProviderDir=<verified-provider>` selects the optional stripped
ARM64 programs installer. `runtime/server/PROGRAMS-ANDROID-PACKAGING.md` records
its original binaries, paired debug archive and source gate. The current lock
remains pending: an actual complete isolated source rebuild receipt is required
before Gradle/provider tools permit packaging. Never flip only its boolean.

The original seven-patch SQL/configuration package can be prepared without Git:

```sh
python3 tools/provider_server_content.py build --artifact <exact-12965377058.zip> --output <new-provider>
python3 tools/provider_server_content.py verify --provider <new-provider>
```

Pass `-PserverContentProviderDir=<new-provider>` together with the separately
verified `-PserverRuntimeProviderDir=<dependencies>`. The source archive remains
unaltered and is stored uncompressed in APK assets as `.archive`; the external
receipt and four metadata markers bind its4,063-file source-selected inventory.
`verify --apk <apk>` must pass for every selected provider after assembly. See
`runtime/server/content-provider.lock.json` for exact input bytes/hashes. This
bundles source SQL/configuration and notices, not initialized saves or server data.

`app/server-schema.gradle` packages the original standard-library helper sources
and nested appearance adaptation inputs. `ServerSchemaSetup` requires a retained
live owned MySQL handle, verified programs/content generations and matching UUID.
It does not enable Main START. `runtime/server/ANDROID-SCHEMA-SETUP.md` documents
the current baseline-only and partial-journal boundaries.

`.github/workflows/server-isolated-build.yml` replays all seven server patches
against exported inputs with no source Git repository, compiler cache or external
network. It captures relevant original compiler/ABI inputs and seals corresponding
sources only after the complete native ARM64 rebuild passes. The one original
module-loader header supplement is separately hash-pinned and retained.

`.github/workflows/wine-arm64-candidate.yml` builds the source-owned private-PE
adaptation for the production architecture. Its generated candidate locks remain
separate from the old production runtime and archive-bound client/bridge/graphics
providers until the actual new runtime is measured and requalified.


`-PserverExtractorsProviderDir=<verified-provider>` selects the four source-matched
ARM64 extraction tools, exact mmaps YAML and original notices. Its pin is pending
the same actual complete-source rebuild as server programs; default builds leave
it disabled. See `runtime/server/EXTRACTOR-PROVIDER.md`. Native CLI success does
not authorize custom Esteria MPQ conversion: current extractor archive ordering
and loose providers differ from the reconstructed reader and need adaptation.

The staged phone setup helper is packaged from18 exact source/profile inputs by
`app/server-installation.gradle`; the final APK sealer checks every nested byte
and refuses missing, changed or extra helpers. Run
`./gradlew :app:serverInstallationOwnerTest` for its three32MiB Java cleanup
timeout/retry cases (bootstrap, installation guest and legacy bootstrap). These
are owner/lease fault tests with Java backend fixtures, not native SQL execution.
The staged coordinator deliberately cannot promote a playerbots-incomplete slot.

Source-matched server data preparation now lives in
`runtime/server_data_generation.py`; its fixed tool selection must be generated
from verified ordered-reader and original assembler/navigation providers. See
`runtime/server/DATA-PREPARATION.md`. This helper is not yet a launcher action,
and the stock four-tool provider does not imply ordered-reader support.

`app/server-data.gradle` packages exactly five helpers. The combined APK sealer
checks that same closure. `:core:serverDataRunPlanTest` verifies fixed commands,
private separate paths and source/import changes without running an extractor.

`app/server-session.gradle` packages23 exact server-session helper/profile files.
The composed data-tools profile uses `app/server-data-tools.gradle`, remains
default false while its source/native pin is pending, and is mutually exclusive
with the stock extractors property. The standalone new-cohort packaging workflow
is separate from the historical two-key client release/combined sealer.

The complete local setup profile adds `app/world-setup.gradle` and
`:app:localWorldSetupOwnerTest`. Its launcher action requires the composed tools,
measured helper-augmented programs, content and shader profiles; a stock server
profile fails before SQL allocation. Prepare client/server runtimes first, then
select the imported client language for Prepare local world. Data/setup children
remain owned through cancellation and cleanup; the4GiB fresh SQL reserve is a
conservative policy separate from imported/extracted assets.

The actual public Wine cohort passes anonymous/full-source consumption and all
seven consumer pins are adopted together. The standalone android-wine-cohort
workflow builds/checks that selected profile, separate from the old combined
release schema. `app/game-session.gradle` supplies gameSessionOwnerTest; regular
Android CI runs it with data/world/presentation owners. Complete gameplay still
requires the composed data tools and helper-augmented programs profiles.

## Complete local-game provider profile

The separate `.github/workflows/android-local-game-profile.yml` composes the
selected public Wine/client/bridge/Turnip/shader cohort, source-built Bionic
ARM64 PRoot, Ubuntu/MySQL dependencies, original server content, the measured
helper-augmented program profile and composed data4. It excludes the stock
extractor provider. Its APK is an internal packaging result until actual
import, SQL/services, client/world and gameplay gates pass.

Reproduce the server portion after the documented Python/JDK/SDK setup:

```sh
python3 tools/qualify_server_providers.py acquire --output out/stock-inputs
python3 tools/qualify_server_providers.py build --inputs out/stock-inputs --output out/stock-providers
python3 tools/qualify_playerbots_programs.py acquire --output out/helper-inputs
python3 tools/qualify_playerbots_programs.py build --stock-providers out/stock-providers --inputs out/helper-inputs --output out/helper-providers
python3 tools/prepare_data_tools_provider.py acquire --output out/data-inputs
python3 tools/prepare_data_tools_provider.py build --inputs out/data-inputs --output out/data-providers
```

These exact artifact acquisitions require GitHub Actions access (`GITHUB_TOKEN`
in CI); tokens are never build inputs or stored in providers. They verify full
source/debug/runtime identities and preserve existing outputs rather than
overwriting them. The stock acquisition requires at least16GiB free before
starting; allow additional space for independent helper/source copies and the
Wine/NDK toolchain. Durable preservation of the new server components is the
next packaging task; current source identities are pinned, while Actions
retention is finite.

Use all the Wine/PRoot/runtime/content properties in the workflow, adding:

```sh
-PserverProgramsProfile=playerbots-schema-helper \
-PserverProgramsProviderDir="$PWD/out/helper-providers/programs" \
-PserverDataToolsProviderDir="$PWD/out/data-providers/provider"
```

Omit `serverExtractorsProviderDir` for this profile. Explicit
`verify_wine_cohort_apk.py --server-profile local-game` additionally requires
`--playerbots-programs-provider` and `--data-tools-provider`; it rechecks every
selected source/debug companion and the complete actual APK inventory. The
historical stock profile keeps its original default checker and workflow.

The complete-profile workflow also runs `assembleRelease` and `lintRelease` with
the same verified providers after retaining the debug APK, AndroidTest, reference
receipts and complete source/debug companions. It rechecks the unsigned release
with the unchanged full cohort verifier and signing tool's manifest reader,
including package/version, minSdk26, targetSdk35 and `debuggable=false`. Its
separate `unsigned-local-game-profile-release-arm64-<revision>` artifact contains
one unsigned APK and three bounded JSON proofs, with combined input bytes below
500,000,000. Actual8c run41149985842 passes this full release path. Signed0.1.0-dev.1
is published with the persistent certificate and baseline1; content/device
installation and gameplay qualification remain separate.

`workflow_dispatch` accepts `build_version_code` (default1; positive and at most
2,100,000,000); increase it before publishing a signed update. Push builds use1.
The release build explicitly clears signing environment variables and performs
no private-key operation. Sign the reviewed `app-release-unsigned.apk` separately
with `tools/sign_android_apk.py` and the owner-provisioned persistent development
key. The signer continues to reject debuggable APKs; this path uses no
`--qualification-only` exception and does not establish an update baseline.

## Supplied server-data preparation

Client generation imports can include the reserved matched server-data namespace
described in `runtime/server/IMPORTED-SERVER-DATA.md`. Generation input format2
binds that manifest and exact APK helper generation; ordinary generated data
keeps format1. Do not alter the helper byte manifest independently of
ServerDataRunPlan: the actual five-file manifest hash is checked against the
preparer and APK. Source-side tests use explicitly synthetic tiny headers and
do not qualify actual maps, DBC rows or world entry.

## Durable complete local-server profile

The helper/data4/content/original-extractor profile now has an actual public
release and complete anonymous source/debug readback. The complete-game workflow
selects it through `tools/fetch_local_server_profile.py` after verifying the bound
lock and both raw publication receipts. It executes the separately checked-out
exact7e498c recipe; it does not acquire those providers from Actions retention.
The existing separate Ubuntu/MySQL dependency release is still required.

```sh
git fetch --no-tags origin 7e498c50cdf55027e679d63e31f0a5e4b117f934
git worktree add --detach out/local-server-recipe 7e498c50cdf55027e679d63e31f0a5e4b117f934
env -u GITHUB_TOKEN -u GH_TOKEN python3 tools/fetch_local_server_profile.py acquire \
  --packaging-source out/local-server-recipe --output out/server-public-inputs \
  --providers out/server-public-providers
```

The result contains programs, data-tools, extractors and content. Keep all source
and paired debug companions outside the APK and retain them with distribution.
Only programs/data-tools/content are selected for the complete application; the
original extractors remain preserved comparison inputs. This gate qualifies
source/package reproduction, not world entry or a Thor test candidate.

## Preparing the first game-content import

Use MPQs plus a small matched DBC overlay for the initial package. The app's
**Import client folder/ZIP** checks the complete build 12340 base. **Add custom
content folder/ZIP** installs client patches at their effective `Data/` or
`Data/<locale>/` locations and an optional whole replacement server namespace.
After runtime/dependency setup, **Prepare local world** performs extraction,
shader preparation and local database setup. Choose the imported client language.
A missing requested locale uses the client reader's effective fallback; both
choices remain visible during shader preparation and must match server data.

To prepare only the reserved overlay from authentic matching server files on a
build host, this example refuses an existing output and leaves source files
unchanged. It creates no maps, rows or replacement assets:

```sh
ESTERIA_MATCHED_DATA=/path/to/matched/server-data python3 - <<'PY'
from pathlib import Path
import os, shutil
from runtime.server_data_preflight import parse_server_manifest, check_server_package
source = Path(os.environ['ESTERIA_MATCHED_DATA'])
package = Path('out/matched-server-overlay')
package.mkdir(parents=True, exist_ok=False)
namespace = package / 'EsteriaServerData'
payload = namespace / 'data'
payload.mkdir(parents=True)
shutil.copy2('config/server-data-inputs.example.properties', namespace / 'manifest.properties')
for name in ('dbc', 'dbc-continuations'):
    if (source / name).is_dir():
        shutil.copytree(source / name, payload / name, symlinks=True)
selected = parse_server_manifest((namespace / 'manifest.properties').read_bytes())
print(check_server_package(payload, selected))
print('Import the folder:', package)
PY
```

The example preserves exactly seven manifest fields and `mode=overlay`.
`clientProviderOrderSha256=none` leaves client matching unverified; only a hash
of the actual canonical `order.json` for that same effective import can supply
an exact provider-order binding. Include every continuation that should remain:
a subsequent server namespace replaces the previous namespace atomically.
Client MPQs can be added separately through the same custom-content import route.

Do not unpack a complete precomputed world set into this overlay. The existing
16 MiB metadata budget applies to source enumeration, path validation and
resume bookkeeping, even when individual files are small. Generated MPQ-based
world preparation avoids that loose-file import ceiling. Large `mode=complete`
packages and large folder MPQs remain bounded and may be refused. No Android
heap limit was raised and no new packed server-data format was introduced.

Client471 uses its original enabled signature checks. A custom package which
changes protected GlueXML/FrameXML content still needs actual signed-content
and normal UI initialization qualification with that selected binary. Import
verification, SRP authentication and successful shader compilation do not
establish that gate or authorize a silent signature-policy change.
