# Esteria Android non-custom implementation plan

## Current objective

One local stock Wrath 3.3.5a build 12340 session on AYN Thor Max (Android 13, Snapdragon 8 Gen 2, Adreno 740, 16 GB). Import the owner's ChromieCraft client data, prepare matching world data/shaders/MySQL automatically, start the reconstructed ARM64 client with local auth/world, create a Human Warrior, enter its ordinary starting area, stop cleanly and relaunch offline with the character retained.

The branch is `non-custom`, created from coherent integration `0319cc00f77c97c17f01592af3fac2bff555f362`. The original integration and complete custom project remain unchanged and recoverable. The app uses a separate `.stock` package and private storage. There is no migration or reseeding of the custom app's saves.

## Architecture and source selection

Keep the reconstructed Windows ARM64 client under ARM64 Wine in a Debian 12 PRoot, with Linux ARM64 server/MySQL in the separate Ubuntu 24 PRoot. This is the existing compatibility architecture, with no original x86 client substitution and no device Docker requirement.

- Client: `471ee42faadf4a97a1d0a86989cf1452621f2dc5`.
- Server: `f35f04d01689f034778e3474b3c820092f51e461`, seven digest-pinned integration adaptations.
- Eluna source: `58d7652138887783228b9727bd1fa4e08f00342b`; Lua disabled in stock configuration.
- Protocol remains 254 containers / 25 quest slots / 32 client class capacity, paired to the selected server.
- `sources.lock.json` and provider locks remain authoritative. Branch names never select binaries.

## Implementation sequence and acceptance

1. Verify actual client input: VERSIONINFO 3.3.5.12340, complete base/locale/speech archives, effective archive order, stock protected UI/signatures, required DBC layouts and shader inputs. Names alone are not proof. Keep Blizzard root and locale patch archives. Diagnose exact missing/corrupt inputs.
2. Select stock content in app-owned state. Preserve source installation, realmlist and accounts. Remove only content-confirmed optional archive overlays from the stock selection; unknown overlays require a useful report. Exclude loose custom UI/addons/Retail/Forever inputs from stock launch. Missing Esteria catalogues are not fatal.
3. Prepare matching dbc/maps/vmaps/mmaps/Cameras and Vulkan shaders from that same selection through the existing ordered no-external-overlay extraction path. Bind `stock-3.3.5a` into reuse identities and retain completed work on failure.
4. Initialize a fresh private local database using genuine source SQL with stock selection of updater inputs/configuration. Do not run incompatible custom race/map/classless overlays. Retain required schema adaptations and real source checks. Validate DBC/SQL combined references through actual world startup when content is available.
5. Start DB, authenticate readiness, then auth/world, presentation and reconstructed client with app-owned loopback account. Use normal signed stock UI. Stop client, world/auth and DB in ownership order; forced stop never counts as a successful save.
6. Build and verify full provider APK, sign with a persistent key and publish an additive non-custom prerelease. Run available host/emulator checks, then one consolidated real-data/Thor procedure.

## Evidence rules

Record source-reviewed support, structural/content validation and actual execution separately. Compilation, synthetic files, SQL receipts, mock owners and listening ports do not demonstrate gameplay. No complete ChromieCraft client or Thor is presently accessible in this checkout; continue all independent implementation and package diagnosis for the first consolidated test.

## Deferred beyond this milestone

Full Esteria MPQ catalogues, custom races/appearance, HD art, custom maps, Retail/Forever assets, AIO/Lua extensions, custom gameplay and bot AI qualification. These do not block stock completion. Asset-independent code can remain compiled where its supported disabled configuration is safe.
