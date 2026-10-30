# Status

Updated2026-10-29 (America/Chicago). This is an implementation checkpoint, **not a device-test candidate**.

## Current pins
`sources.lock.json` is authoritative. Starting integration main 6309c8f, client 800cdd2, server f35f04d. Both requested development branches exist remotely. No default merge or server push has occurred.

## Implemented
- Pinned source preparation preserving local changes, including rejecting hidden Git index flags; ordered digest-checked server patch support and pinned Eluna.
- Protocol generator/verifier: all 215 player descriptors, 254-slot container, 25 quests and 42 mask DWORDs match actual pinned source. Optional enlarged wire formats rejected.
- Local MySQL 8/server configuration generations, private persistent secret, loopback binds, separate auth/world temporary directories, zero automatic random-bot population and four controlled account-bot ceiling.
- Client ARM64 CPU/math/crash paths, real portable LZNT1 catalog decoder, source-built Xvid movie codec and native component tests. Corrected Vulkan shader input archive order and bounded archive extraction.
- Android launcher stable package identity, foreground ZIP import/cancel, resumable staged immutable generations, touchscreen/controller launcher navigation, support ZIP export with redaction, runtime supervisor with readiness/dependency monitoring/reverse shutdown. Gameplay startup remains explicitly gated until real runtime packaging exists.
- Source-lock provenance embedded in APK/support exports; persistent signing-key strategy documented. No signed user update baseline yet.

## Actual evidence
- Actual user-supplied Wow.exe (7,702,016 bytes) passes structural PE VERSIONINFO verification for 3.3.5.12340. SHA256 `c4ea8503112878fa47d06580de9d936b184f9bb6b452f6931dfe793fe2f0a47e`. This is executable evidence, not verification of the complete client dataset; the file remains outside Git.
-21 Python integration tests passed at first app checkpoint (source pins/config/layout/assets).
-16 Java importer behavior groups passed with a 32MiB heap, including 64MiB streaming input; 7 supervisor tests and bounded/redacted diagnostics tests passed. Synthetic inputs validate behavior, not real gameplay assets.
-12 shader MPQ tests passed; five host client platform CTests passed (vector math, CPU selection, LZNT1, movie encode/decode).
-Client CI 40980276079: native Linux x64 and ARM64 component tests pass. Windows paths failed before full client build; codec assembly guard and VS2026 ARM runner selection corrected in next revision. Full Windows executable build is not yet proven.
-Server CI 40979894616: pinned checkout, protocol verification and native Linux ARM64 configuration pass; compile running when this checkpoint was written.
-Android launcher debug compile and lint pass locally; final clean rerun/remote CI pending for complete checkpoint.

## Remaining gates
Complete reconstructed Windows ARM64 client build/link and desktop reference; real Wine/PRoot/display/audio runtime pins/package; MySQL bootstrap and guarded compatible schema update; server SQL/module/Lua/data packaging; authentic full client/custom assets and Vulkan shader outputs; matched login/world entry; game controller/touch/keyboard/audio; save/relog/bots/offline and Android lifecycle qualification. Rootfs/runtime is not packaged, and launcher controls are not in-game controls.

Committed historical server patch MPQs have inconsistent declared extents, confirmed on raw Git bytes. Treat them as unqualified artifacts, not a complete current content pack. Catalog packers require unavailable original developer inputs. See ASSET-REQUIREMENTS.md for exact scope. These content gaps do not halt platform, builds, diagnostics or importer work.
