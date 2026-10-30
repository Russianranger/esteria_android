# Launcher UI import review

`ClientLaunchSetup` now connects the persistent UI store to the app's explicit
runtime-preparation operation. It resolves the selected completed import,
prepares its writable Interface candidate, and obtains a typed active selection
for `ClientLaunchView.Plan`. Imported assets and per-account WTF settings are
never changed by the review flow.

The first UI inventory and an update with no local mutations activate
without a prompt. Preparing the currently selected inventory reuses its writable
tree without hashing all its live files again. A new import with the same UI
inventory retains addon changes; only its new source provenance needs binding.
Other inventory changes require a bounded assessment of the old and candidate
UI trees. No MPQs or other large game-data files are rehashed for that assessment.

If either tree has local changes, the launcher shows counts of modified, added,
deleted and renamed files plus conflicting paths. Each section displays at most
four relative filenames and the remaining count, never file contents. The
concrete actions are:

- **Use imported UI version:** select the separately prepared imported tree.
  The button sends the exact digest of the report displayed. The service checks
  that it is still the pending report, then the store recomputes the live
  assessment under its lock before any pointer change. A stale or replayed
  decision is refused. The new report must be reviewed again.
- **Keep current UI:** dismiss the report without changing the pointer. The
  newly imported content remains incompatible with the old selected UI until
  reviewed, or until a later import selects the matching inventory again.

Both choices retain all prior UI generations. There is no automatic merge,
replacement of modified addons, transfer of previous-tree mutations, or cleanup.
An imported candidate that was used previously can itself contain mutations;
the report calls those out and selection preserves them. Settings in WTF survive
independently. Old and new addon versions may interpret saved variables
differently; this file-preservation policy does not claim semantic compatibility.

Review decisions are held only in memory. Recreating the service never restores
an approval. Choose Prepare client runtime again to recompute a report after
interruption. Acceptance uses already installed client binaries and never starts
another Wine download. Support bundles include the pending digest and counts;
launcher logs do not include addon contents or the review's paths.

## Session and validation limits

Preparation has a private operation lock, and the service serializes import,
prepare, review and start actions on one worker. All actual gameplay starts are
still gated, so the client is stopped during this flow. A future session adapter
must keep the client stopped for the whole operation, including assessment and
activation; the UI file lock cannot prevent a running game from writing files.
No review choice enables gameplay or changes the offline-network qualification.

`tests/test_client_launch_setup.py` compiles the actual app adapter with the real
core classes and narrow Android signature stubs. Its 32MiB Java fixture checks
initial/clean activation, mutation-preserving same-inventory reuse without an
assessment, a concrete conflicting update, stale/replayed decision rejection,
retained previous UI/import/WTF bytes, typed launch views and cancellation. The
stubbed signatures are not evidence of Android execution. App compilation/lint
cover the activity/service bindings; device UI interaction remains unqualified.
