# Owned compiled updater

`runtime.server_update_setup` consumes real verified packaged content and an
already authenticated, owned MySQL service. It requires no Git or Docker and
does not start or stop MySQL, authserver or worldserver. The caller retains its
exclusive service lease throughout the operation.

`prepare(content, executable, selected_program_identity, template,
template_identity, mysql, original_build_identity=...)` binds the original build
to the complete compiled-module object. Selected executable and template pins
come from the caller's verified program generation. Derived executable hashes
remain separate from original binary provenance. Metadata and every selected
SQL file are checked against their immutable SHA-256 identities; SHA-1 updater
expectations retain the selected source's ledger semantics.

`apply(plan, connection, state, version, ...)` requires the real completed source
baseline journal on the same UUID, datadir and credentials. First execution
refuses existing account intent, account rows or character rows. A private
journal records and fsyncs execution intent before the updater can start. The
shared process owner retains the whole child group and a bounded private log.
Completion requires exact live source ledgers, unchanged credentials/account
intent and the same owned service. No updater ledger rows are synthesized.

Cancellation is honored before durable intent. Once committed, the updater
finishes its bounded unit; cancellation does not imply SQL rollback. Failed or
interrupted intent is preserved and refused on reentry. A completed repeat
verifies current bindings and ledgers without executing the updater again.

`verify_completed_update(content, connection, state, version,
expected_uuid=..., verify_service=...)` supports subsequent realm/account setup.
The caller holds its state/config/service lease and the bootstrap SQL lock; the
verifier independently checks SQL lock ownership and acquires or releases none.
It performs no mutation, binary access, journal rewrite or replay. Later owned
account intent is permitted and must remain unchanged during verification.

An optional `state_lease` on initialization/updater operations reuses only the
opaque, active capability yielded by `mysql_bootstrap.state_lock`. The registry
binds its process, thread, exact state path, live descriptor and lock inode.
Default callers acquire the ordinary lock. The baseline completion observer
receives the actual underlying proof only after its durable completed journal;
historical verification does not emit another import proof.

The native qualifier now exercises these real product journals, their completed
verifiers, the complete runtime renderer and the portable realm/account APIs
before adding qualification-only probe tables. Its original second actual
updater, marker and restart checks remain, with owned-account preservation
checks added. Focused host tests cover these guards; actual native execution of
this new composition remains pending its workflow result.

These receipts qualify only their named components. The separately identified
fresh appearance adaptation remains source-derived, not recovered original DDL.
Playerbots' unregistered database must remain empty during this phase. World
entry, bots, saved-state upgrades and Android gameplay remain separate gates.
