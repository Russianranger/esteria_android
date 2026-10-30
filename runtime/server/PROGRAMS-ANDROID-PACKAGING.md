# Optional server programs provider

`tools/provider_server_programs.py` and `ServerProgramsSetup` implement the
install-only boundary for the actual stripped seven-patch ARM64 programs. The
optional `serverProgramsProviderDir` profile remains disabled by default. The
checked-in `programs-provider.lock.json` now binds the actual complete source
rebuild and byte-identical retained archive from run `41078079045`, separately
from its original native loader evidence. Provider creation still performs full
paired-debug and source readback. The four-component CI profile is described in
`PROVIDER-QUALIFICATION.md`; Android runtime and gameplay remain unqualified.

The actual runtime archive is 21,996,594 bytes, SHA-256
`df7e0b33e4048daf780ebf31c0a7f9a10b1f74ea42f4de100ca18ed1a65b673e`.
It contains exactly 126 regular files / 66,025,007 expanded bytes: three ARM64 ELF
programs, 53 configuration templates, four original provenance files, and 66
original notice files. Every member's bytes, size and mode is pinned. Original
module/build receipts retain original binary identities; separate derivative
pairs bind each original, stripped program and debug file. No receipt is rewritten
by the Android provider to relabel the original executables.

The immutable mount is `/esteria-server-programs`, with only the validated
`bin/authserver`, `bin/worldserver` and `bin/dbimport` executable paths. Android
callers choose a `ServerProgramsSetup.Program` enum value. There is no arbitrary
executable argument. The separately installed Ubuntu ARM64 dependency generation
must match archive SHA-256
`21a9e8020aac3c780114e2b3e368a643a6e830d35b6406ed99135dec9ba03ce5`.
The provider is incompatible with the Debian Wine rootfs and Android x64 probe
profiles. It does not create configuration, SQL tables, users, credentials, or
mutable state and is not connected to Main START or a foreground server service.

## Evidence required before enabling

A deliberate lock update may select `state: sealed-source-and-native-loader` only
after actual qualification and review of the exact files below. Setting a boolean
alone is refused. `sourceQualification` must independently pin all three sealed
outputs by byte count and SHA-256:

- `server-engine-complete-sources.tar.gz`
- `sealed-source-receipt.json`
- `qualification.json`

The provider verifies the sealed receipt's original build, compiled module,
source lock and source-input identities. The actual native isolated-build receipt
must report a complete clean build, reference programs, observed source/include
closure, preserved module selection and auth/world version execution. The source
archive receives complete regular-member/hash/mode readback, including its
embedded exact qualification and original source-input archive/receipt.

It also independently verifies the real native derived auth/world loader receipt,
the original paired engine-package receipt, and the complete paired debug archive
(1,082,880,246 bytes, SHA-256
`facc75680f3fb1b205a98960d6ea5a0d565cb2a2b4bd56303dd6625fd4854a24`).
Debug member hashes must match the original↔stripped↔debug identities. Native
version execution establishes a loader component only; dbimport execution, SQL,
Android, game login and gameplay qualification remain separate.

The measured payload can be audited without creating a provider:

```sh
python3 tools/provider_server_programs.py audit \
  --package /private/notice-augmented-package \
  --original-receipt /private/original-engine-package/package-receipt.json \
  --native-loader /private/native/loader-smoke.json
```

After the real sealed gate and its exact lock update, use fresh output storage:

```sh
python3 tools/provider_server_programs.py build \
  --package /private/notice-augmented-package \
  --original-receipt /private/original-engine-package/package-receipt.json \
  --native-loader /private/native/loader-smoke.json \
  --sealed /private/isolated-build/sealed \
  --debug-archive /private/original-engine-package/server-engine-debug-arm64.tar.gz \
  --output /private/server-programs-provider
python3 tools/provider_server_programs.py verify \
  --provider /private/server-programs-provider
./gradlew :app:assembleDebug :app:lintDebug \
  -PserverProgramsProviderDir=/private/server-programs-provider \
  -PserverRuntimeProviderDir=/private/server-runtime-provider
python3 tools/provider_server_programs.py verify \
  --provider /private/server-programs-provider \
  --apk app/build/outputs/apk/debug/app-debug.apk
```

## Installation and distribution contract

Only `assets/server-programs/{provider.json,server-programs.archive}` enter the
APK. The `.archive` suffix preserves the original gzip bytes through AAPT. Gradle
verifies the source-sealed provider before build; final APK verification requires
exact asset closure, matching bytes, and ZIP_STORED for the archive. Android
`AssetManager.openFd` enforces the stored-asset path. All original notices remain
inside the pinned runtime archive.

The adjacent `sources` directory contains the original notice-package receipt,
original paired-package receipt, real native-loader receipt, sealed source archive,
sealing and build receipts, and paired debug archive. It must accompany any
distributed provider/APK and is checked on each provider verification. Original
preparatory receipts retain their historical false qualification flags; later
sealing receipts establish separate evidence. Do not drop or silently replace the
companions merely because the APK can install.

`ServerProgramsSetup` accepts only canonical app-private storage and verifies the
embedded application source lock, provider lock, three selected programs, ELF183,
paired identities, original provenance, notices and dependency archive identity.
It streams through `EmbeddedArchiveCache` and `RuntimeInstaller`, with resumable
copy/extraction, cancellation, bounded storage reserve and verified generation
reuse. Repeating setup of a completed generation avoids reopening the archive.
Its separate `runtimes/server-programs-arm64` generation and
`runtime-embedded-cache/server-programs-arm64` cache do not touch `/work/state`,
saves, imported content, existing runtime generations, application ID or signing.

Current tests cover refusal of a pending or boolean-only source seal, source and
dependency drift, unknown executables, omitted notices, path/size/mode/symlink
bounds, existing-output preservation, and exact stored APK assets. Synthetic asset
checks do not qualify server execution or a production provider. The actual
archive audit and native loader receipt are separate measured component evidence.
The first fully sealed provider still requires its own APK build/readback and
actual Android ARM64 installation/execution gates before any launcher activation.
