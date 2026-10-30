# Local login handoff recovery

An app-process interruption before the client consumed its login handoff used
to leave `Esteria-local-login.bin` in the stable launch view. Exclusive creation
then refused every subsequent launch. The selected client remains471ee42f: its
fixed filename,57-byte `ESTLOGN1` record and consume-before-submit behavior are
unchanged. Accounts, credentials and database storage are not reset or rotated.

`LocalAccountHandoff` now retains a dedicated kernel file lock and a canonical
directory reservation within the JVM. The reservation precedes every lock-file
open. This matters on Linux: closing a second descriptor after a failed local
lock attempt can release another descriptor's POSIX record lock. An actual
second-JVM fixture checks that a refused same-JVM attempt cannot weaken the
active owner's cross-process lock. Reservations are removed by their own token
only after the descriptor closes.

The live `GameSession` already holds `ClientLaunchSetup.Lease` from allocation
through client reap and cleanup. Its existing `prepareLocalLogin` call remains
the production writer. The additional handoff lock is retained until that
caller's stopped-client cleanup; it is never inherited as cleanup authority by
the client or a caller-selected PID.

## Publication and restart

1. Write and sync a unique mode0600 record stage within the canonical launch
   view. The existing random nonce remains part of the client record.
2. Write and sync a bounded metadata stage, then publish a private ownership
   receipt. It binds the exact view generation, generated stage name, device,
   inode, modification time,57-byte length and SHA256. It contains no username,
   password, PID or arbitrary path.
3. After the receipt and directory are durable, move the verified record into
   the fixed client filename. Both moves use the same private parent and reject
   existing destinations; no replacement option is supplied. Inode readback
   confirms that the private Unix provider preserved the same file.
4. After process death, a new exclusive owner can recognize either the recorded
   stage or final file. It checks the private single-link inode and opaque
   record hash twice before removal. A consumed record permits removal of only
   its unchanged receipt. The next launch writes a fresh handoff.

Unrecognized legacy files, changed or replaced records, malformed or changed
receipts, links and escaping names are preserved and refused. Fixed failure
tokens direct the user to support export; the application never asks them to
inspect secret-file contents. A unique stage interrupted before its receipt
was published is preserved and ignored, rather than adopted or broadly cleaned.
Such stages are private, at most57 bytes for data or bounded metadata, and are
outside support-log selection. Unrelated settings, imported data and saves are
untouched.

Normal close still requires the retained client to have stopped. A failed
cleanup releases its kernel descriptor while preserving the invalid record.
An explicit cleanup retry must reacquire ownership and match the original
receipt identity; it cannot clean a newer session's receipt.

## Actual evidence boundary

`:core:localAccountHandoffRecoveryTest` runs only on a Linux host. It launches
real JVM children and kills/reaps their exact `Process` handles at five
boundaries: record creation, completed write, durable proof, published handoff
and client consumption. Every case must relaunch successfully. Other fixtures
check cross-JVM exclusion, refused local reentry, unchanged57-byte compatibility,
unknown legacy/stage preservation, replacement, restored-mtime mutation,
hardlinks, record/proof/lock symlinks, proof path escape, missing proof, publication
collision and unrelated account/save/settings siblings.

These are actual host filesystem/process checks. They do not qualify Android
process restart, Android ARM64, normal client login, world entry or saved-game
shutdown. Existing PDEATHSIG/PRoot EXITKILL containment and Android x64 owner-death
evidence remain separate from this persistent-handoff recovery check.
