# Retained Android server-data preparation

`ServerDataSetup.begin(...)` accepts only the prepared, source-qualified
`ServerDataToolsSetup` and its matching Ubuntu `ServerRuntimeSetup`. It is not a
public entry point for a caller-pinned executable or self-hashed tool plan. The
current pending composed-provider pin still prevents actual production creation;
no Main or UI action invokes this owner.

The owner uses top-level private `server-data-work` for derived assets, separate
from reserved state/database/runtime roots, so its completed generation can pass
the fresh SQL owner's existing path guards directly. It validates canonical paths
and captures the exact immutable runtime/tool generations. It acquires two actual FileLocks before reading the
active import: the data operation's `.android-server-data-setup.lock` and the
importer's exact `game/import.lock`. A live import, another preparation or the
future playing-session owner excludes it. The actual `GameDataImporter` uses
that same file. The application must retain the data handle until close
completes; a subsequent job cannot steal an allocated or failed live owner.

`prepare(...)` is single-use. It installs the existing five APK source helpers,
atomically writes the typed provider's canonical `ServerDataToolSelection` bytes,
and constructs the fixed `ServerDataRunPlan`. Only the pinned Ubuntu process
adapter and composed source-matched tools are used. No additional helper asset,
archive flag, shell, Git or device-side build dependency is introduced.

The process has a24-hour deadline, a final prelaunch cancellation/deadline check,
and bounded native cleanup. Phase reporting consumes only new bounded log bytes;
a whitelist translates the actual helper's stage lines into provider order,
maps/DBC/cameras, raw/assembled collision and navigation progress. Elapsed seconds
are explicit. Arbitrary log text never reaches progress callbacks. Complete and
failed private logs remain available for diagnostics.

The helper owns the existing resumable immutable-generation protocol. Cancelled
or interrupted phases are retained, rather than mixed into later phase inputs.
Only a normal zero process exit without forced cleanup, unchanged provider and
import selection, and completed metadata readback can return `ServerDataBinding`.
The binding and underlying receipt remain format-only: no world coverage,
character persistence, Android execution or gameplay qualification is inferred.
Atomic promotion may win a cancellation race; a cancelled caller receives no
binding, and the next owned helper invocation validates any completed output.

Close requests cancellation before waiting for the operation's safe boundary.
A timeout/interruption keeps the actual process, provider identities, setup lock
and import lock retained. Cleanup retries target only the known child. Both locks
are released only after the native owner confirms reaping; earlier cleanup
failures remain diagnostic. Closing never deletes imported data, staged output
or completed generations. Immutable runtime/provider generations are retained
by their installers, which do not prune them during this operation.

`serverDataSetupOwnerTest` runs four32MiB host fixture groups with real Java
FileLocks/operation guards and a controlled delayed process backend. The actual
importer refuses before its source snapshot while cleanup remains active; it is
admitted after confirmed reaping. The suite also covers prelaunch cancellation,
secondary-lock failure unwind, canonical atomic metadata/symlink refusal, and
bounded incremental progress parsing. It executes no native process, extractor,
source-qualified provider or game input. APK/AndroidTest compilation, lint and
helper-source byte readback are separate checks; actual Android data conversion
and matched proprietary inputs remain required.
