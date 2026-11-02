These are source-backed synthetic format tests, not game data.

`source-manifest.json` pins the unchanged server declarations/Detour implementation
at `Russianranger/EsteriaWoW` revision `f35f04d01689f034778e3474b3c820092f51e461`
and client row readers at `Russianranger/wowdecomp_esteria` revision
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`. Original source notices are retained.
The map declaration excerpt records its exact range and full original source
identity. These sources came from exact-revision GitHub readback and the verified
public complete native extractor source companion; no game assets are included.

`native_format_writer.cpp` compiles the pinned 44-byte map, 56-byte mmap tile,
28-byte Detour index and camera model header declarations. The exact pinned Detour
code builds and loads one synthetic navigation triangle. Twelve unchanged client
row readers consume generated rows and reject truncated rows through the clearly
labelled, bounded in-memory SFile fixture. This separately demonstrates ten GT
generated-ID float rows, the explicit-ID GT scalar and packed PowerDisplay rows.
The server's original full-width formats remain independently generated inputs.

The unchanged pinned `DBCFileLoader.cpp/.h` additionally loads two packed
PowerDisplay rows with distinct IDs/types and nonzero RGB bytes through its real
`Load` and `AutoProduceData` functions, retaining both ID/type pairs with a
15-byte row stride. The same loader reads a one-field GT header but refuses its
`df` projection, while its indexed two-field GT counterpart projects correctly.
Only the assertion/logging bridge is substituted; no loader or field-offset
function is mocked. These checks do not execute the SQL fallback or its database.

VMAP outputs exercise native magic/classification only; map, model, camera,
shader, SQL and geographical coverage remain native runtime/owner-data gates.
No output from this fixture qualifies Android, Thor world preparation or gameplay.
Generated binaries and data stay in temporary test directories and are not shipped
in the APK. A C++17 compiler is needed to execute the native reference tests.
