# Persisted owned support-log selection

`SupportLogSelection` stores only versioned, sorted ASCII metadata identifying
fixed application-owned diagnostic log roles. It does not open or read log
contents, enumerate directories, copy credentials or create missing logs.

The selector accepts exactly20 roles. Database and server-helper stdout/stderr,
auth/world logs and four presentation components account for14 game roles.
Data, shader and installation stdout/stderr account for six setup roles. Each
role is bound to its exact private operation/session path shape. It cannot be
used to select arbitrary app-relative paths.

`encode(canonicalAppRoot, fixedOwnedLogPaths)` returns the bounded metadata value;
`decode(canonicalAppRoot, encoded)` returns an immutable sorted map. Empty stored
text means no selection. Both operations require a canonical existing app root
and reject unknown roles, traversal, absolute/foreign paths, control characters,
links, unexpected file types and private configuration/account paths. Missing or
rotated log files are allowed so a saved selection can survive an interrupted
startup or update. The limits are32 entries,64KiB encoded ASCII and1024 relative
path characters. The fixed role bindings are stricter than those size limits.

The service must decode again immediately before support export. A previously
validated selection is a metadata snapshot, not authority to follow a later
symlink or open an arbitrary replacement. The exporter remains responsible for
its bounded log tail, redaction and open-time filesystem safeguards. Log byte
privacy is outside this metadata utility's scope.

Host validation on2026-10-30: `:core:supportLogSelectionTest` passed with JDK17,
Gradle8.9 and a32MiB heap. Three actual temporary-filesystem groups cover all20
roles, deterministic missing/rotated roundtrips, immutability, format bounds,
private/foreign/traversal paths, symlink ancestors/targets and unexpected file
types. Independent source review found no blocking issue. This establishes no
Android, guest, game-session or world execution result.
