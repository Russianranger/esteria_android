# Shared Android / host behavior

This module uses Java 17 source compilation with Android API 26-compatible library
calls and no external dependencies. `:core:check` runs executable behavior tests.

`SessionSupervisor` starts dependency components in order. Each component supplies
a real readiness predicate. A watchdog continues checking earlier processes while
a later readiness probe is pending, enforces the deadline, and cancels the probe
on stop or failure. Probe implementations must respond to cancellation/interruption.
Any start/readiness/exit failure stops the chain in reverse order. A shutdown timeout
is a failed session, never a successful save. One instance owns one session.

`LoggedProcess` is a real `ProcessBuilder` child with bounded rotating stdout/stderr
logs and graceful SIGTERM before a reported forced stop. It supervises the direct
child only. The runtime entrypoint must `exec` the final service or provide a
qualified process-group implementation; no process-tree guarantee is inferred.

The Android service currently integrates the transactional importer and support
export. The supervisor is host-tested but is not yet wired to a packaged game
runtime. Runtime launch fails explicitly until the client/server session adapter,
database bootstrap, protocol-aware readiness, and persistent shutdown are qualified.

Support bundles include only public version/status facts and explicitly allowlisted
log tails (32 files maximum, 64 KiB each). Common credentials and AzerothCore
DatabaseInfo strings are redacted. This is best-effort log redaction; never add
database files, account stores, secret files or whole runtime configs to the export.
