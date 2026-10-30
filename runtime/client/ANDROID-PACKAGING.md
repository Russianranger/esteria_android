# Reconstructed client binary provider

`tools/provider_client_runtime.py` builds a host-verified APK asset provider from
the actual reconstructed Windows ARM64 client artifact. The selected input is
client `0f931bbade36a4b197725d691b8eff7caea7b3be`, build `41012726334.1`,
[artifact 12958691770](https://github.com/Russianranger/wowdecomp_esteria/actions/runs/41012726334/artifacts/12958691770).
`android-provider.lock.json` pins its 45,848,368-byte ZIP and SHA-256
`1fd6176727065f50a926b45a3d81df1bfd0ea33c330e9fb9131ff30ad170b94e`, measured
against GitHub's artifact digest. The tool requires the same clean source revision
as application `sources.lock.json`; a changed source pin requires a newly measured
artifact pin. It never chooses a floating branch or accepts a stock `Wow.exe`.

That client revision passed all five CI jobs, including native Windows x64/ARM64
and native Linux ARM64 Wine execution. The latter exercised real executable entry,
offline network policy, loopback transport and synthetic Grunt authentication,
codec, software Vulkan graphics and captured FMOD output. These asset-free fixture
results are separate from Android execution or matched world gameplay. The new
provider binds the exact seven-patch server source lock; the earlier 69cc provider
and its already-published source release remain preserved as historical inputs.

Only `WowClient64.exe` and matching `XvidDecoder.dll` enter the binary directory.
The tool reuses the exact committed client's PE parser, validates actual AA64
images/direct imports against the build manifest, and verifies generated descriptor
bytes for build12340, 254 container slots, 25 quests and class capacity32. Nonzero
PE delay-import directories are rejected until explicitly supported. The two
images currently have 35 unique direct imports: the packaged codec plus 22 Windows
modules and 12 CRT API sets supplied by the separately pinned Wine runtime.
The immutable package records those imports and the required Wine archive and
manifest hashes. Optional dynamically loaded libraries are not a proven complete
closure; Vulkan/audio/movie selections need their own runtime checks.

The ZIP is hash-checked on the same open file used for bounded selective reads.
Its central directory/member count are bounded before allocation. Links, duplicate
or unsafe names and oversized selected members are rejected; PDBs, test fixtures
and build logs are not copied. A deterministic GNU tar/gzip contains only regular
files, including original build metadata, all selected original component notices,
the source lock and Xvid adapter/source recipes. Every archive member is read back
and hashed before atomic no-replace publication. Repeating verification rebuilds
the expected provider from the pinned artifact/source and requires identical bytes.
Output failure leaves an existing provider unchanged. Optional `verify --apk` bounds
the APK directory before allocation, requires exactly the three client asset
entries with identical bytes, and requires the runtime archive to be ZIP_STORED.

The output is `assets/client-runtime/{client-arm64.archive,provider.json,NOTICE.txt}`.
The archive installs into a separate `client-arm64` generation with these paths:

| Path | Purpose |
| --- | --- |
| `bin/WowClient64.exe`, `bin/XvidDecoder.dll` | Matching reconstructed client binaries |
| `metadata/client-build.json`, `metadata/limits.json` | Original build and generated descriptor evidence |
| `metadata/sources.lock.json`, `client-runtime.json` | Exact source/protocol/runtime set and limited package scope |
| `notices/`, `source-recipes/`, `NOTICE.txt` | Preserved notices, FMOD credit and pinned Xvid build/source information |

`provider.json` supplies the archive hash/size, exact required-file hashes and PE
machine values, extraction bounds, physical/free-space budgets and source/build
identity. No hard or symbolic links are needed. No Gradle integration or game
launch is enabled by this tool. All Android/game-initialization/login flags remain
false. Previous Linux ARM64 Wine codec, executable-entry and software-renderer
fixtures are separate evidence; a package digest is not world-entry evidence.

Use Python3.11+ and Git on Linux. Acquire the exact ZIP through the authenticated
GitHub Actions artifact API (not an extracted/repacked download). Actions artifacts
expire; retain the original ZIP and matching checkout with a release. The current
tool intentionally rejects a rebuilt ZIP with a new digest until its exact build
has been measured and the pin reviewed. Source builds remain documented in the
client repository; generated binaries are never committed to either repository.

```sh
python3 tools/fetch_sources.py client --output sources
python3 tools/provider_client_runtime.py build --artifact /cache/arm64-auth-0f.zip \
  --client-source sources/client --provider /tmp/new-client-provider
python3 tools/provider_client_runtime.py verify --artifact /cache/arm64-auth-0f.zip \
  --client-source sources/client --provider /tmp/new-client-provider
python3 tools/package_client_sources.py --client-source sources/client \
  --xvid-source /cache/xvidcore-1.3.7.tar.gz --output /tmp/new-client-sources
ESTERIA_CLIENT_ARTIFACT=/cache/arm64-auth-0f.zip ESTERIA_CLIENT_SOURCE="$PWD/sources/client" \
  python3 -m unittest tests.test_client_runtime_provider -v
```

`package_client_sources.py` creates a separate `client-corresponding-source.tar.gz`
and source receipt. It retains the full pinned client Git tree, the unchanged
Xvid1.3.7 archive verified against the committed CMake hash, every adaptation/build
recipe and the integration packaging helpers/locks. Each outer archive member is
hashed and read back. This source companion belongs beside distributed binary
packages/APKs, not inside the application asset directory. Preserve it with the
original build artifact so source delivery does not depend on expiring CI URLs.

The measured-artifact test actually reproduces the package, rejects corrupted
output and a wrong input digest, and verifies no-overwrite behavior. Small guard
tests also exercise ZIP-directory allocation bounds, compressed member bounds,
links/traversal/duplicates and unsupported delay imports. Without the original
artifact/source, that integration test explicitly skips; this is not execution
qualification. The pinned client has no top-level LICENSE. Component notices are
retained without assigning the integration repository's license to client code;
the FMOD notice and required Firelight Technologies credit are preserved.

## Launch view and writable state

Source audit at the exact pin establishes `-datadir` followed by one Windows path
argument, for example `-datadir Z:\work\launch\<generation>`, plus `-vulkan`. `CmdLine.cpp`
registers `datadir` as a string; `SCmd.cpp` accepts the next token. `SetPaths()`
sets both the process working directory and SFile base path to that directory,
then reads the `Data\` subtree. The launcher uses `/work/launch/<generation>` as
the writable view, `/esteria-data` as the separately bound imported generation,
and a real `Data` overlay directory containing validated per-file guest links
plus private root/locale realmlist overrides for loopback routing.
`WTF`, `Cache`, `Logs`, and `Screenshots` link to persistent `/work/client-state`
paths. Binding an immutable imported root directly as the working directory
would mix mutable settings into imported assets.

The same writable launch directory contains verified copies of only the EXE/DLL. Never launch it directly from the immutable provider:
the early crash logger deletes/recreates `WowClient_crash.log` beside the EXE;
Esteria appearance tracing appends `EsteriaDecomp.log` there. Loose `Esteria*.bin`
catalog/texture-bank fallback reads directly beside the EXE, even with `-datadir`;
the packed `Esteria\<name>` path takes precedence. Bind later verified catalogs
at their exact names without copying large content. The optional `EsteriaOff.txt`
sentinel beside the EXE disables extensions and must not be created by default.

Vulkan shader lookup uses explicit `GX_VULKAN_SHADERS` or defaults to
`VulkanShaders`/`VulkanShadersRetail` beside the executable. Bind a separately
generated, effective-data-matched shader generation at `/esteria-shaders` and set
`GX_VULKAN_SHADERS=Z:\esteria-shaders` explicitly.
Retail/Forever preparation remains separate; this binary has that optional path
disabled. SFile MPQ ordering and locale-specific `Data/<locale>/realmlist.wtf`
remain relevant: loopback settings need a session overlay at the effective locale
path, without editing imported MPQs or relying on the root realmlist fallback.
Keep the Wine prefix/home and persistent state outside updateable providers.
These are source-audited integration requirements, not yet a tested full launch.
