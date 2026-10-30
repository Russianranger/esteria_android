# Owned local auth/world session

`LocalServerSession` is an internal process adapter. Main START and
`SessionService` do not invoke it. It executes neither a game client nor a schema
initializer, and its readiness receipt does not qualify world entry, saving,
bot AI, Android execution or gameplay.

## Inputs and closed production gates

`begin(...)` returns a retained handle before native launch. It requires an
already live `ServerDatabaseService.Handle`, the exact promoted
`FreshServerInstallations.Active`, prepared source-sealed runtime/program/content
providers and a typed `ServerDataBinding`. It re-runs
`ServerInstallationSetup.completed(...)`, then compares the promoted proof,
work directory, runtime archive and live MySQL UUID. The complete setup receipt
hash comes from the validated promotion proof, rather than a current self-hash.

`ServerDataBinding` streams the potentially large receipt inventory; it retains
only bounded metadata, not300,000 file objects. It checks the selected import's
actual build12340 completion/ancestry journals, canonical tool-selection identity,
current client/server revisions, order metadata pins and exact data-generation
identity. It compares those inputs again before launch. Its factory is deliberately
package-private: the future source-qualified composed ordered-extractor provider
and data setup owner must supply it. A caller-pinned `ServerDataRunPlan` is not
public source qualification authority. Metadata inspection does not verify usable
maps or source binaries. The guest separately hashes the actual completed data
inventory and reruns the format/projection preflight.

The complete prepared generation is mounted at `/esteria-data`; its actual
`DataDir` is `/esteria-data/data`. Under the same owned state/database lease,
`server_session.prepare` requires the real completed playerbots loader and core
updater/source ledgers before rendering a new verified configuration generation.
It then runs the existing local realm/account APIs in verify-only mode. It never
replays baseline SQL, migrates schemas, adopts another database, resets accounts
or rewrites historical setup/PB journals. Current verified runtime configuration
and public realm/account receipts may refresh independently of the original
complete setup receipt. A real four-schema installation and full module
configuration remain mandatory.

## Process ownership and readiness

One retained Java worker holds `database.withReadyLease(...)` for the whole guest
session. A database shutdown request asks that worker to stop; it cannot pass its
guard and stop the engine while the auth/world helper remains owned. The worker
continues known-child cleanup on failure. A timed-out `close(Duration)` keeps the
worker, native owner, actual session FileLock, providers and database dependency
retained for retry. Closing this component never stops or deletes the caller's
database. No registry lookup discovers or signals another PID.

The fixed interactive guest supervisor retains each `ServerChild` before Popen,
uses reserved unreaped process-group identities, bounded8MiB private logs and
explicit same-instance SQL checks. It holds the real state/configuration leases
through child and diagnostic-worker cleanup. Source-selected programs/configs
are fixed; no caller executable, shell command, password or SQL text is accepted
on its control channel.

Readiness requires all of these:

1. The same authenticated owned MySQL instance and intact credential/account/PB
   journal identities, together with the exact local realm endpoint.
2. The retained auth child's socket inode joined against its own `/proc/<pid>/fd`
   and TCP tables. Only its fixed IPv4 loopback3724 listener is accepted; extra,
   nonloopback or IPv6 listeners are refused. Permission failure never falls back
   to an open-port check.
3. A source Grunt build12340 challenge with a fresh random16-character unknown
   probe name. Exact `00 00 04` confirms the source's asynchronous unknown-account
   callback runs. No password, SRP proof or session key is sent; a name collision
   fails closed. Owned socket identity is checked on both sides of this probe.
4. Equivalent owned world loopback8085 socket identity, the actual40-byte
   `SMSG_AUTH_CHALLENGE`, and a fresh source `server info` console response.
   Fixed `Connected players:` and `Update time diff:` output confirms that the
   world loop processed its queue. The source's earlier ready log alone is
   insufficient. The realm's startup OFFLINE/VERSION_MISMATCH transition is
   tolerated; exact flag0 is required at completed world readiness.

The supervisor monitors children, log workers, SQL ownership, private journals
and listener identities. Credentials and arbitrary guest log text are absent
from public receipts/failure events. Logs remain private for support redaction.

## Shutdown

The only control line is `server shutdown 1\n`. EOF and signals are distinct stop
reasons; neither becomes an explicit command acknowledgment. The supervisor sends
the exact source command to world, keeps stdin open, and waits for actual zero
exit. It then signals its directly created auth child with SIGTERM and waits for
zero exit without forced termination. An auth child already exited before a stop
request cannot count as a source-signal acknowledgment, including status0.

If cleanup cannot confirm reaping, it keeps its live execution mechanism and
all dependencies rather than writing `stopped.json`. Confirmed forced cleanup,
nonzero status, missing command delivery or diagnostic failure remains an error.
Retries preserve the earlier failure. The Java owner also requires the bound
clean stop receipt and actual normal outer-process exit. These checks establish
source shutdown mechanics, not character/inventory/bot persistence; relog and
actual world testing remain separate gates.

The exact source is server `f35f04d01689f034778e3474b3c820092f51e461`:
`apps/authserver/Main.cpp` registers SIGTERM/SIGINT and returns0 after its IO loop;
`apps/authserver/Server/AuthSession.cpp` defines the packed challenge and unknown
account callback; `apps/authserver/Authentication/AuthCodes.h` defines error4.
`apps/worldserver/Main.cpp` emits its ready marker before CLI/world-loop startup.
`game/Server/WorldSocket.cpp` sends the40-byte challenge;
`scripts/Commands/cs_server.cpp` implements console info/shutdown; and
`apps/worldserver/CommandLine/CliRunnable.cpp` queues commands and treats EOF as a
separate StopNow request. See [world shutdown](../WORLD-SHUTDOWN.md).

## Evidence and remaining boundary

`tests/test_server_session_process.py` executes actual Linux host Python child
fixtures for console bytes/processing, the two protocol probes, bounded logging,
post-Popen/reap-failure retention and unexpected exit0. These are not real server
binaries. This managed host denies or does not expose the own-child socket inode
projection, so its actual inode proof is explicitly skipped; the parser receives
separately labeled synthetic proc metadata. Production remains fail-closed.

`tests/test_server_session.py` mocks source/SQL phases while exercising the real
state lease, gate ordering, verify-only calls, single-use/control contracts and
world-before-auth cleanup dependency. The Java32MiB owner fixtures exercise real
FileLocks/guards with controlled backends, including database shutdown exclusion,
prelaunch cancellation and a finished flag racing a live native child.

APK/AndroidTest compilation and lint are recorded separately. The actual23-file
APK helper closure and local import dependencies are read back byte for byte.
Two emulator tests install/reuse those exact helpers and check private synthetic
metadata bindings. They execute no helper, extractor, SQL or server. Their
execution is pending the installer workflow; compilation is not an Android run.

Actual native source-matched auth/world composition, prepared proprietary
maps/DBC/vmaps/mmaps/Cameras, Android ARM64/Thor startup, world loading, client
entry and character/bot saving remain unqualified. Missing data or unavailable
provider gates refuse execution. No preliminary Thor package is requested.
