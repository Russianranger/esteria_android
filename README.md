# Esteria Stock Android

Esteria runs the reconstructed Wrath 3.3.5a build 12340 ARM64 client, world server and MySQL locally on the AYN Thor Max. The owner has created a character, accepted a quest, fought an enemy and logged out on the handheld.

[Signed stock v25 release](https://github.com/Russianranger/esteria_android/releases/tag/non-custom-v0.1.0-non-custom.25) · [Device testing and support export](NON-CUSTOM-TESTING.md).

Install over Esteria Stock, then open **Play → Start local game** and select the existing character. V25 reuses the prepared client, world, shaders and local database. [Startup and update evidence](STATUS.md).

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset requirements](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Developer handoff](HANDOFF.md)
- [Runtime packaging](runtime/PACKAGING.md)

This branch is `non-custom`; original custom branches/releases remain preserved. `sources.lock.json` pins client/server inputs; branch labels never select binaries. Extra Esteria/HD assets, custom races and bot AI qualification are deferred.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported assets, databases, credentials, private signing material and generated binaries do not belong in Git.
