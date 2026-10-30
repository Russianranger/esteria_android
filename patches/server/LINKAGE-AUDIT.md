# Final ARM64 worldserver link adaptations

Native ARM64 run `40994809596`, job `123865355694`, at integration
`1f19c3abe5722ac06ab58f9af4e54b2f27f54ec8` completed compilation and archive
generation. Authserver, dbimport and extractor executables linked. Worldserver's
final link, step 2,257 of 2,257, failed at 2026-10-30 04:38:04 UTC.
No installed/qualified server package was produced. The partial compiler cache
was saved for the next build.

## Existing player-visitor template definitions

Three call sites lacked the template implementation headers:

- `scripts/Kalimdor/zone_moonglade.cpp:284` selects quest players near Clintar.
- `scripts/Northrend/zone_zuldrak.cpp:498` checks players during Drakuru's encounter.
- `scripts/OutdoorPvP/OutdoorPvPNA.cpp:619` finds players near the Halaa objective.

Each instantiates `Cell::VisitObjects<PlayerListSearcher<AnyPlayerInObjectRangeCheck>>`.
`Cell.h` only declares that function; `Grids/Cells/CellImpl.h:165` defines it.
`GridNotifiers.h` declares the player visitor; `GridNotifiersImpl.h:475` implements
the phase-filtered iteration. Patch 0005 includes these existing definitions at
the callers. It neither substitutes a visitor nor changes radius, alive/GM,
phase, quest or PvP checks. The same explicit header pattern already appears in
`scripts/Events/hallows_end.cpp`.

The patch applied with both `git apply --check --index` and `git apply --index`
to a disposable fixture containing the three exact pinned Git blobs. The server
checkout remained unchanged. CI now compiles these actual three objects before
the full link; their successful full linkage remains a subsequent gate.

## README-only Custom directory

The pinned tree contains exactly `src/server/scripts/Custom/README.md` (Git blob
`5eee67576bb979f8826f957dd95d61914a26e765`), with no C++ definition of
`AddCustomScripts`. Its README explains optional git-ignored private scripts.
`GetScriptModuleList` in `ConfigureScripts.cmake` previously selected every
directory, and the script-loader generator emitted an unresolved call for Custom.

Patch 0006 checks the same recursive inputs as `AutoCollect.cmake`:
`c`, `cc`, `cpp`, `inl`, `def`, `h`, `hh`, `hpp`, including its symlink-following
selection policy. Only a directory with zero such inputs is omitted, with an
explicit configure message. A populated Custom directory still requires and
invokes its real loader; no empty function or unconditional disable is added.
Committed Esteria modules remain selected separately through `AC_MODULES_LIST`.
This does not invent or qualify private custom scripts absent from the repository.

`tests/test_empty_script_modules.py` reads the actual pinned CMake helpers using
Git, applies the patch in scratch, and runs CMake against README-only and nested
source/header fixtures. It checks enumeration against the real `CollectSourceFiles`
result and requires populated Custom with a missing loader to remain selected.
That actual CMake fixture passed independently with CMake 3.22.1 and the available
host CMake. Source-absent tooling jobs explicitly skip this test; server CI has
the required exact checkout and executes it before configuration.

Neither patch changes SQL/Lua/configuration data, update ordering, network layouts,
or module SQL discovery. The content manifest separately records the sixth
patch's script-registration policy effect instead of calling it an Eluna patch
or hiding that generator change.
