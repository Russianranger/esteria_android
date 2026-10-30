# Retained local world setup

`LocalWorldSetup.begin` accepts installed typed providers and checks the measured
playerbots helper and semantic existing database before extraction or SQL. Only
absence returns null; changed/incompatible active proofs and legacy server work
are refused. Errors never select fresh initialization. Fresh allocation rechecks
absence under the transactional installation lock.

The owner is registered before any child. It prepares server data through
`ServerDataSetup` and retains that owner's actual `game/import.lock` while
preparing shaders and the database. New SQL executes the real baseline/updater,
realm/account and playerbots phases, followed by four-schema verification and
owned clean database shutdown. Only the resulting bound proof promotes a slot.
Existing completed installations are verified and reused; they are not reset.
The returned result has a private constructor and retains its exact provider,
import, shader and installation context for the game-session owner.

Close runs installation, shader and data cleanup in that order, retaining later
dependencies and the outer file lock while any child remains owned. The service
keeps its foreground operation busy and retries the same owner until CLOSED;
first cleanup errors remain diagnostic. Import/preparation cannot overlap the
retained data lease. The four GiB fresh-database storage budget is a conservative
policy, not a measured database footprint. It excludes runtime and extracted data.

The launcher exposes Prepare local world only with the complete source-qualified
provider profile, with an explicit imported-client language and one worker.
Graphics setup also installs the selected Turnip provider. Local compute/setup
uses the already declared specialUse foreground type on API34+, separate from
network/import dataSync work. No normal Start action is enabled by this slice.

Validation: APK/AndroidTest compilation and lint passed in35s (83tasks); two real
Java fixtures passed in20s (28tasks) with a32MiB heap. The fixtures use production
close methods, actual file locks, a real importer and a controlled delayed Java
process backend. They establish dependency/import exclusion through known reap,
prelaunch stop intent, retry release and preserved output, including retained
unclean-shutdown diagnostics. They execute no guest, SQL, extractor, GPU or
Android framework service. Independent ownership and Service/Main review found
no remaining blockers. See runtime/evidence/local-world-setup-host.json.

Actual Android pipeline/slot promotion, real MPQ conversion, shader output,
CommonMain, world entry and saving remain unqualified. The source-qualified
ordered tools and helper-augmented server providers are still being composed.
