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
