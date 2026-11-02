# Esteria Stock Android

Local Wrath 3.3.5a build 12340 client/server bring-up for AYN Thor Max: Android 13 ARM64, Snapdragon 8 Gen 2, Adreno 740. The reconstructed ARM64 client uses pinned Wine/PRoot with local server/MySQL; gameplay is intended to remain offline after setup.

**V9 preparation speed, resume and storage controls:** [signed ARM64 APK](https://github.com/Russianranger/esteria_android/releases/download/non-custom-v0.1.0-non-custom.9/Esteria-Stock-3.3.5a-arm64.apk) · [testing procedure](NON-CUSTOM-TESTING.md).

Install over the existing stock app and preserve the completed import and all data. Start with **Balanced 32 MiB/s**, select the same locale and retry **Prepare local runtime / world**. Gentle 8 and Fast 64 MiB/s are also available while idle. Compatible completed work and valid partial navigation tiles resume; idle storage controls trim recognized obsolete files. Do not reimport. Native conversion stays at one worker with the existing memory guard.

All six exact-producer source gates passed, covering ARM64 packaging, native SQL, Android tests and native extractor fixtures. Public APK/signature readback also passed. The selected rate governs verification/copy I/O, not total navigation CPU time. Physical Thor preparation/world entry and gameplay remain unqualified; export support before another retry after failure. [STATUS.md](STATUS.md) records exact identities and limits.

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
