# Validation gates

## Host tooling
```
python3 -m unittest discover -s tests -v
python3 tools/verify_protocol.py --client ../client-src --server ../server-src
```
The actual-source protocol verifier generates the selected 25/254/32 descriptors and compares every player field to pinned server offsets and sizes. It also checks mask counts, container slots and server size-comment consistency. This verifies layout, not login, appearance transport or world behavior.

Java core tests use synthetic files and child processes, with no game data or database required. Android CI also compiles and lints the application. Client portable tests exercise algorithms; the Windows matrix must separately build real executables.

## Not yet qualified
MySQL initialization/migration, server data loading, Wine client launch, Vulkan world rendering, full audio/input, character login/create/world entry, combat/loot/quests, save/relog, bots, offline play, update-signature continuity and Android low-memory recovery have not passed end-to-end validation.

Do not ask the owner to install a foundation APK. The main Thor test comes after one coherent candidate is expected to cover all requested gameplay. A narrow device-only diagnostic is allowed only when evidence shows useful independent work cannot continue.

## Future consolidated Thor test
Install/update with the stable signing identity; import verified data; start local play; create/select a character; move/look with controller; fight/loot/equip/quest; summon a small supported bot group; verify audio; exit/relaunch and confirm saves; repeat with networking disabled. Export one support bundle. Exact instructions and artifact identification must accompany the qualified candidate, not this preliminary gate description.
