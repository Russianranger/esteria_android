# Optional embedded server dependency provider

The provider installs the measured Ubuntu 24.04 ARM64 dependency rootfs from an
uncompressed APK asset. It starts no executable or service and initializes no
database. Authserver/worldserver, SQL content, private accounts, saves and game
data are separate components. A normal app build without this provider remains
valid; requesting server preparation reports that the provider is absent.

## Exact inputs and reproduction

`android-provider.lock.json` pins the measured runtime archive, package receipt,
runtime metadata, source lock and corresponding-source companion from integration
`b06de55f5b17f27ae9659abcfdaf93a61b749a9e`, Actions run `40993458111`.
No binary payload is committed. Build the dependency image and package a fresh
container using [README.md](README.md), or recover that exact runtime artifact.
The provider's inputs are the four package files:

- `server-runtime-arm64.tar.gz`
- `package-receipt.json`
- `server-runtime.json`
- `sources.lock.json`

On Linux with Python 3.11+, use a new output directory:

```sh
python3 tools/provider_server_runtime.py build \
  --package /private/measured-server-package \
  --output /private/server-runtime-provider
python3 tools/provider_server_runtime.py verify --provider /private/server-runtime-provider
./gradlew :app:assembleDebug :app:lintDebug \
  -PserverRuntimeProviderDir=/private/server-runtime-provider
python3 tools/provider_server_runtime.py verify \
  --provider /private/server-runtime-provider \
  --apk app/build/outputs/apk/debug/app-debug.apk
```

The optional Gradle hook verifies provider inputs before compilation, includes its
`assets` directory and stores the `.archive` asset without ZIP compression. The provider uses an
`.archive` suffix because AAPT automatically expands and renames a `.gz` asset
even when `noCompress` includes `gz`; the asset retains the original gzip bytes. The final APK
verifier checks every server asset's bytes and insists on `ZIP_STORED` for the
archive. `ServerRuntimeSetup` also uses `AssetManager.openFd`, which rejects a
compressed asset. This avoids repeated decompression while resuming asset copies.
The provider can coexist with `prootProviderDir`; neither enables launch.

The input receipt is **not its own trust authority**: all four files must match
independent repository pins. The tool checks the source lock, exact MySQL/Python
ARM64 ELF header identities, complete archive/link graph and distro metadata.
It emits a bounded descriptor containing only installation evidence. It does not
claim complete ELF dependency closure, Android guest execution or gameplay.

A rebuilt rootfs with different bytes is rejected even if it names the same
source snapshot. Record and review the new package's identity, re-run runtime
qualification, then update the provider pin deliberately. Source selection is
reproducible; bit-identical rebuilding of the dependency image is not assumed.
The recorded Actions artifacts expire after 14 days. A distributed application
and long-term clean build must retain exact pinned runtime bytes plus the
corresponding source/recipe companion at durable release URLs. The app itself
needs no Actions authentication or Internet to install its embedded component.

## Storage, interruption and updates

Provider assets live under `assets/server-runtime/`. The Java adapter uses:

- `runtime-embedded-cache/server-arm64/` for the owned, resumable archive cache.
- `runtimes/server-arm64/` for immutable staged/generation directories and the
  current-generation pointer managed by the existing `RuntimeInstaller`.

It does not use the Wine generation store or private game/database directories.
Archive copying holds a file lock, verifies its ownership pin, hashes retained
partial bytes before resuming and checks the complete SHA-256 before publishing.
Cancellation and truncated reads retain only owned partial work. Failed updates
never activate a new runtime. A cached generation revalidates its completion and
required files without recopied assets or an unnecessary full archive scan.

The measured archive has 6,263 entries and 385,051,708 regular-file bytes. Two
hardlinks may require **3,944,586 extra bytes** where Android denies hardlinks.
The maximum physical payload is therefore 388,996,294 bytes. The descriptor
reserves 585,256,470 bytes for a fresh setup, including archive cache, metadata
allowance and 64 MiB margin. After caching, the adapter subtracts the already
occupied archive bytes from its free-space requirement. Resumed extraction uses
the installer's verified journal and per-copy capacity checks, preserving its
existing hardlink-copy recovery behavior.

Private APK/runtime metadata is bounded at 64 KiB per descriptor/input. Tar paths,
members, total file bytes and installer metadata memory have independent bounds.
Required files include mysqld, mysql, Python3.12, the runtime receipt and os-release.
The expected database version remains the raw measured
`8.0.46-0ubuntu0.24.04.4`; installation is not SQL-version verification.

## Evidence and outstanding validation

Host guards cover modified receipts/source locks/descriptors, exact APK asset
sets, compressed-asset rejection and the physical hardlink budget. The embedded
cache test exercises cancellation/resume, reuse without reopening its source,
corruption preservation, short-source recovery, invalid-hash rejection and a
64 MiB file under a 32 MiB Java heap. The adapter compiles against Android API 35.

Actual Android provider installation, interruption/update behavior and PRoot
execution of this rootfs are separate upcoming gates. No UI control or launch
button is activated by these files. Keep original runtime copyright notices
inside the rootfs and distribute the identified 89-package corresponding-source
companion and exact recipes alongside a release containing this payload.
