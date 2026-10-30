# Pinned server adaptations

The server repository remains at `f35f04d01689f034778e3474b3c820092f51e461`.
Patches are stored here, SHA-256 pinned in `sources.lock.json`, and applied to the
exact source or named pinned submodule by `tools/fetch_sources.py`. The script
verifies indexed patch bytes and rejects unrelated local changes on repeated runs.

`0001-eluna-declare-area-trigger.patch` applies inside Eluna gitlink
`src/server/game/LuaEngine` at `58d7652138887783228b9727bd1fa4e08f00342b`.
Its `LuaEngine.h` aliases `AreaTrigger` without declaring it when AzerothCore is
selected. Server `Globals/ObjectMgr.h:422` defines `struct AreaTrigger`; a matching
forward declaration makes pointer-only hook signatures valid without a transitive
include or precompiled header. No behavior, ABI, Lua hooks or content are removed.

Evidence: native ARM64 CI run `40979894616`, job `123817047329`, failed compiling
`ElunaEventMgr.cpp` and `ElunaInstanceAI.cpp` at `LuaEngine.h:80/566` with the missing
type. The patch applies cleanly to the exact pinned Eluna commit. A subsequent full
server build is still required to establish compilation beyond this failure.

`0004-attunement-stat-api.patch` applies at the server root to
`modules/mod-attunement-plus/src/mod_attunement_plus.cpp`. It preserves the removed
primary-stat display-field operation through a local compatibility helper and maps
flat armor/AP modifiers to the current `HandleStatFlatModifier` API. This is not a
claim that primary-stat gameplay bonuses worked before or are now qualified: the
old API was display-only, contrary to the module's original comments. The comments
are corrected. SQL/Lua/configuration/module discovery remain unchanged. See
[ATTUNEMENT-API-AUDIT.md](ATTUNEMENT-API-AUDIT.md) for pinned upstream/current source
comparison, known gameplay limitations and targeted compilation evidence.

`0005-script-grid-templates.patch` includes the existing `CellImpl.h` and
`GridNotifiersImpl.h` template definitions in the three scripts whose player-grid
visitors failed at final linking. It changes no visitor logic or protocol fields.

`0006-empty-script-modules.patch` prevents generated `Add<Directory>Scripts` calls
for directories containing no inputs accepted by the real recursive
`CollectSourceFiles` helper. The pinned `Custom` directory contains only README.md;
the patch does not add an empty registration function or suppress populated custom
scripts. [LINKAGE-AUDIT.md](LINKAGE-AUDIT.md) records the source evidence and actual
CMake fixture. Both patches remain unqualified at full server linking until CI.
