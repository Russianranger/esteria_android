# Measured optional playerbots helper candidate

The original programs provider still selects exactly `authserver`, `worldserver`
and `dbimport`. The playerbots database helper is a separately built executable,
with a separate build and native SQL proof. Its candidate never rewrites the
original build/module/program receipts or asserts a complete game installation.

[Run `41076505231`](../evidence/server-playerbots-schema-41076505231.json) measured
the 25,188,512-byte AArch64 helper, SHA-256
`b7d9b72c17f32294915f0a474283c543057ffb7de7b3f93015c2e7e179bfcf25`.
The build and real source-schema/reentry/restart evidence bind the original
seven-patch build `41019374697.1` and archived `5f72e02c…be80c1` source lock.
Actual native SQL success includes 29 original base files, 31 original updates,
52 prepared statements and final verification after removing the fixture table.

The original 150,197,120-byte helper ZIP has 39 members; the declared payload and
receipt require 40. GitHub's default hidden-file exclusion omitted only
`recipes/.github/workflows/playerbots-schema.yml`. Its actual producer Git blob
`07932bf7acd594e660adde05b0576587cd97b0da` at `6ce7a9f154b11f5e24ce2d228e613f06001b979f`
supplies the exact 14,368 bytes/SHA-256 already declared by the build receipt.
The original ZIP stays unchanged and explicitly incomplete. Recovery provenance
identifies this separate canonical source; it does not claim those bytes were
present in the upload. Future helper uploads include the selected hidden recipe.

`runtime/server/playerbots-helper-candidate.lock.json` records measured producer,
artifact, executable, build/native proof and exact 40-file identities. It is a
candidate pin; it does not enable a production provider. Source-only preparation
and registration must preserve the original ZIP and explicit recovery record.

`tools/package_playerbots_helper.py build` requires explicit build/native receipt
digests, reads every retained payload byte, checks the real ARM64 ELF, validates
the successful same-UUID native phases, and compares the original three programs
against the current immutable provider selection. It creates an atomic candidate
directory with three runtime delta files: `helpers/playerbots-schema` and its
two public provenance receipts. The full source/build payload and native proof
remain alongside them in `companion/`.

`verify --candidate … --candidate-pin-sha256 …` rechecks the externally pinned
candidate, exact runtime/companion file sets, all bytes, normalized modes and
original source/program bindings. Neither command executes a helper/server/SQL,
creates an Android provider, promotes a slot or modifies a checked-in pin.

The source-only registration workflow retains a deterministic mode-preserving
`candidate.tar.gz`, its pinned candidate JSON and explicit acquisition/preparation
receipts. It excludes duplicate input downloads from the upload. Authenticated
444/555 file modes remain inside the tar despite Actions ZIP mode normalization.

Host fixtures cover validation and refusal paths only. A local full readback of
the actual recovered 40-file payload, candidate and 45-member archive passed.
The local archive contains 175,514,426 expanded bytes; its compressed identity is
recorded separately from the original producer artifacts.
[Source-only run `41081216973`](../evidence/server-playerbots-helper-candidate-41081216973.json)
registered the complete 45-member mode-preserving archive and explicit recovery
provenance. Its typed receipt pins match the local full readback; the large outer
artifact was identified through GitHub metadata and was not downloaded again.
Source-sealed helper/provider integration and native qualification of the new
phone finish path remain required before production adoption. `sourceCompanionComplete`,
`androidProviderCreated`, `productionActivated`, complete setup, Android runtime,
world, playerbot AI and gameplay flags remain false.
