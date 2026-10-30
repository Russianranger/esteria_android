# Esteria Android development

Read STATUS.md, HANDOFF.md, ANDROID-PORT-PLAN.md, BUILDING.md and ASSET-REQUIREMENTS.md before changing implementation. This repository owns Android/integration only; reusable reconstructed-client changes belong on Russianranger/wowdecomp_esteria `android/arm64-port`. Server adaptations are reproducible patches here against sources.lock.json, never server-repository commits.

- Work on `android/client-server`; do not merge defaults or force-push. Preserve unrelated work.
- User authorizes autonomous branch pushes, workflows, builds and routine implementation. Do not ask again for these. PR creation is not a stopping gate.
- Keep private keys, runtime credentials, game assets, databases and generated APK/EXE binaries out of Git. Preserve original licenses and dependency notices.
- Exact source revisions must be recorded in every application build. Never use a floating branch to select an engine or server build input.
- Keep imported immutable assets, replaceable runtime generations and mutable saves/configuration separate. Never initialize or reseed over live saves. Shutdown failure must remain visible; forced termination is not a successful save.
- Preserve 25 quest slots / 254 containers /32 client class capacity. Validate generated layouts against pinned server; compile success does not qualify protocol/gameplay.
- Use real functionality, bounded memory, interruptible/resumable imports, and actual readiness checks. No silent essential-feature stubs. Disabled optional graphics vendors must have explicit platform reasons.
- Run focused host tests plus relevant build/lint jobs. Record host vs native ARM64 vs Android emulator vs Thor evidence separately. Do not claim runtime success from mocks/fixtures/headers or an APK that only opens the launcher.
- Do not ask user to install preliminary startup probes. Main Thor candidate must coherently support local login/world/gameplay/persistence/bots/audio/controllers/offline use. Continue independent work when assets are missing.
- Update records and push meaningful checkpoints before ending. State truthfully whether any real execution mechanism remains running.
