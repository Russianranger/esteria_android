# Exact compiled server runtime qualification

Run `41005048019` at integration `ae5534d0a9d7fb72c8e5a03dcfc65420c354e7bb`
completed the real native ARM64 build, all application/extractor links,
installation, ELF/source verification, auth/world `--version` loader smoke,
compiled module/config binding and deterministic source packaging. This proves
the six reviewed server patches build together. It does not prove world entry.

Its first runtime qualification stopped before initializing MySQL or executing
the updater: the consumer compared a full archive identity record against only
its byte length and SHA-256 fields. The producer also records origin, source
path and Git blob identity. The corrected consumer requires all five exact
fields. A real Git-backed producer-to-consumer test and five provenance mutation
cases cover that boundary; no verification was weakened.

`compiled-reference.lock.json` preserves the original run, job, exact artifact
IDs, archive lengths/hashes, six-patch application lock hash and runtime source
lock. The original overall workflow result is explicitly **failure**, while
the required build/verification/package steps must all be successful. The
runtime-only workflow checks those facts through the read-only GitHub API before
downloading. The 1.168 GB install archive is streamed on the native ARM64 runner;
it is not downloaded into the constrained interactive workspace.

`tools/prepare_server_requalification.py` then:

1. Hashes each exact ZIP, bounds its central directory and expanded members, and
   rejects links, special files, duplicate paths and unlisted installed files.
2. Restores every installed byte against `server-build.json`. Only executable
   permissions are reconstructed for its verified ELF entries; binaries are
   neither stripped nor rebuilt.
3. Preserves the original installed source lock and its exact patch bytes,
   independently of the current application's client/server selection. The
   original compile commands are re-read and their generated module/config
   literals rechecked against the installed binaries.
4. Verifies and retains the original content package metadata and archive hash.
   The earlier package predates inclusion of main auth/world templates in its
   payload. A separate package is therefore generated from the same pinned
   source Git objects and compiled module selection using the current reviewed
   packager. Original and repacked receipts remain distinct in the evidence.
5. Writes a preparation receipt only after all checks and repackaging succeed.
   It never starts MySQL, runs server binaries, imports SQL, or changes an
   existing output directory. Failed new staging remains visible for diagnosis.

The workflow builds the exact pinned MySQL dependency environment and invokes
the existing fresh-state `qualify_authserver.py` pipeline with external networking
disabled. That pipeline owns initialization, actual compiled dbimport execution,
same-revision updater reentry, restart persistence, account provisioning, SRP
proof and the loopback realm list. The preserved six-patch lock is passed
explicitly; a later application lock does not silently reinterpret old binaries.

Only public receipts, version/source identities and already bounded/redacted
component logs are uploaded. SQL dumps, configuration credentials, account rows,
session keys and private database trees remain outside artifact paths. Input
staging tests use synthetic byte fixtures and are not native execution evidence.
Actual runtime results must be read from the new workflow receipt before any
SQL/authentication success is claimed. Playerbots' fourth-schema loader, real
world data, gameplay and Android execution remain separate gates.

The installed archive and its source-content artifact are temporary Actions
inputs. Their exact source revisions and adaptations remain reproducible; a
future runtime release still needs appropriate durable artifact/source retention.
