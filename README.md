# Esteria Android

A local client/server application for AYN Thor Max, in active bring-up. Target: Android 13 ARM64 / Snapdragon 8 Gen 2 / Adreno 740. Gameplay will use the reconstructed Esteria client, local server and MySQL 8, with no network dependency after setup.

**No playable Android package is qualified yet.** Internal launcher APKs test import/UI/lifecycle only. Current source pins and validation evidence are in [STATUS.md](STATUS.md).

- [Implementation plan](ANDROID-PORT-PLAN.md)
- [Build instructions](BUILDING.md)
- [Asset inventory](ASSET-REQUIREMENTS.md)
- [Validation gates](TESTING.md)
- [Next-session handoff](HANDOFF.md)
- [Local server requirements](runtime/LOCAL-SERVER.md)
- [Pinned runtime preparation](runtime/PACKAGING.md)
- [Native ARM64 Wine qualification](runtime/WINE-QUALIFICATION.md)

Development branches: `Russianranger/wowdecomp_esteria:android/arm64-port` and this repository's `android/client-server`. The server is consumed at a fixed revision without modifying its repository. `sources.lock.json` selects exact source inputs; do not vendor a divergent client engine here.

Original GPL-3.0 [LICENSE](LICENSE) is preserved. Imported client/content and private databases/signing keys are not source files and must never be committed.
