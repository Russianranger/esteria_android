# Non-custom stock bring-up status

Updated 2026-10-31 America/Chicago. Active branch: `non-custom`; profile: `stock-3.3.5a`; separate package: `io.github.russianranger.esteria.stock`.

## Goal and boundaries

Ordinary Wrath 3.3.5a build 12340 local login, Human Warrior creation and stock starting-area entry, followed by clean stop/persistent/offline relaunch. Full custom assets, races, appearance catalogues, HD content, custom maps, Retail/Forever and bot AI are deferred and are not acceptance prerequisites.

The branch starts at integration `0319cc00f77c97c17f01592af3fac2bff555f362`. `main`, `android/client-server`, the custom client branches and published `android-v0.1.0-dev.1` assets remain unchanged. The custom app's database/state is isolated by the separate package.

## Exact retained engine selection

- Reconstructed Windows ARM64 client: `471ee42faadf4a97a1d0a86989cf1452621f2dc5`; Retail disabled, signatures enabled.
- Linux ARM64 server: `f35f04d01689f034778e3474b3c820092f51e461`, with the same seven digest-pinned integration adaptations.
- Eluna source: `58d7652138887783228b9727bd1fa4e08f00342b`; disabled in stock runtime configuration.
- `sources.lock.json` and all native provider/source/debug identities remain authoritative. No x86 client or alternate server substituted.

## Implementation

- Import report checks actual PE VERSIONINFO, essential archive headers, locale selection and speech. It preserves Blizzard root/locale patches and reports unclassified overlays. Structural checks do not claim MPQ content/signature/runtime proof.
- Stock content inspection and app-owned selection feed the same client/extraction/shader stack, preserving original input. Confirmed optional overlays can be omitted; unknown overlays require precise diagnosis. Genuine signed stock UI remains mandatory.
- Content profile enters generated world/shader reuse identities. The new shader wrapper is app-owned; original compiler/provider helper bytes remain unchanged and source-verifiable.
- Stock SQL projection uses exact authenticated source files and source-supported dbimport discovery. It excludes incompatible custom race/map/classless data, retains required schema, and prevents world startup from reapplying the full custom updater tree. No fabricated rows or success stubs.
- One preparation action installs dependencies/tools and prepares stock client/world/shaders/local database. Existing process ownership, streamed/resumable import, private loopback login, save-preserving shutdown and bounded support export remain.
- Full provider ARM64 packaging, persistent signing and additive non-custom prerelease are wired to the branch. A package is distributable only after actual signing/payload checks succeed.

## Evidence and open gates

No complete ChromieCraft client folder/archive or Thor was found in this session. The official download documentation describes clean stock data with separate optional HD/challenge additions; this is expected support, not validation of the owner's bytes.

The inherited integration proved actual Android 13 x64 four-schema installation/restart in run `41148736592`, and release packaging in `41149985842`. Those historical results do not transfer as proof of changed stock SQL, actual ARM64 Android, normal graphical initialization, world entry, character persistence or gameplay.

Current host and build results are recorded by the non-custom workflow and evidence checkpoint. Until those results are added, worktree checks are implementation evidence only. Actual stock extraction/shaders/world startup and graphical login/creation/entry remain unexecuted without genuine data. See `NON-CUSTOM-TESTING.md` for one consolidated real-data/Thor procedure and support export.

## Real remaining inputs

The smallest missing content input is the owner's complete build 12340 `Wow.exe` plus `Data` and one complete locale/speech set. No custom MPQ bundle or pre-extracted world package is requested. Actual Thor graphics/controller/audio/offline persistence require hardware. Signing publication additionally requires the persistent project key to be available to the release job.
