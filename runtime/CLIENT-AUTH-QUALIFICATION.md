# Reconstructed client and compiled authserver gate

`tools/qualify_client_auth.py` pairs the actual source-built Windows ARM64 client
with the exact compiled Esteria authserver and local MySQL. It reuses the existing
updater, configuration, account, realm and owned-process helpers without changing
`qualify_authserver.py` or adopting its previous state.

Actual paired execution passed in
[run `41060555263`](https://github.com/Russianranger/esteria_android/actions/runs/41060555263)
at integration revision `ad5785ff1f3242453a9fe72a5b2efb200ac47129`.
[The compact proof](evidence/client-auth-41060555263.json) binds the exact
47,747-byte artifact and public receipts. Client revision `0f931bba…b3be`, build
`41012726334.1`, authenticated against retained six-patch server build
`41005048019.1` under its original `dbbf8983…41b0` lock. This qualifies their
named authentication exchange; the current seven-patch client/server pair,
normal game initialization, imported assets and Android execution remain
separate gates.

The normal untraced invocation passed the owned listener, actual Grunt/SRP
callbacks, persisted 40-byte session key, local realm and joined worker/timer
teardown checks. Credentials, trackers and updater ledgers remained unchanged;
all services stopped cleanly and the private key file was removed. No diagnostic
fallback was used. Realm 1 retained its world-offline flag and advertised
`127.0.0.1:8085`; `CommonMain` and game assets were not started.

The client `--auth-check --local-offline` path uses its real Grunt timer, SRP
exchange, stream parser, realm callback and network workers before `CommonMain`.
The initial Windows CI check uses an owned synthetic peer, including bad-proof
and nonlocal-realm negative cases. This separate integration gate replaces that
peer with the compiled server; it contains no alternative SRP client/server.

## Development prerequisites

Run on native Linux ARM64, as root, inside the pinned Ubuntu ARM64 server
dependency environment or an equivalent explicitly verified native reference
environment. The host needs Python3, `unshare`, `mount`, `ip`, and `chroot`.
A container must permit a new mount/PID/network namespace; Docker is a CI tool,
not an Android runtime requirement. The prepared Debian Wine filesystem is a
separate dependency closure. It is never overlaid onto the Ubuntu server files.

Inputs are the exact installed server tree plus matching immutable content
package/receipt, matching original server-build source lock, native MySQL programs/version, a fresh
`prepare_runtime.py` Wine result, and the original ARM64 client Actions ZIP with
its measured SHA256/size and clean matching source checkout. The committed
client parser verifies both PE images and generated build12340/254/25/32
descriptors. The source must contain the real opt-in Grunt diagnostic. The tool
retains the original artifact/build/source identities and rechecks copied images
immediately before supplying credentials.

The invocation shape is:

```sh
python3 tools/qualify_client_auth.py \
  --runtime /private/fresh-prepared-wine \
  --install /qualification/out/server-install \
  --content /qualification/out/server-content \
  --content-receipt-sha256 EXACT_CONTENT_RECEIPT_SHA256 \
  --lock /qualification/sources.lock.json \
  --mysql /usr/bin/mysql --mysqld /usr/sbin/mysqld \
  --expected-version EXACT_PINNED_MYSQL_VERSION \
  --client-artifact /private/exact-client-arm64.zip \
  --client-artifact-sha256 EXACT_CLIENT_ZIP_SHA256 \
  --client-artifact-bytes EXACT_CLIENT_ZIP_BYTES \
  --client-source /private/clean-pinned-client \
  --client-revision EXACT_CLIENT_COMMIT \
  --output /private/new-client-auth-run
```

These placeholders must be replaced by the actual measured artifacts; the
composer does not download or select a latest client/server. This command is
not a device installation procedure.

`.github/workflows/client-auth.yml` now prepares the exact six-patch server
reference through `prepare_server_requalification.py`. Its original build
`41005048019.1` linked and passed loader/module/artifact checks, but its first
runtime gate stopped at a content-consumer comparison before MySQL initialization.
The separate server reference retains that failed-run scope and its original
source lock. The new gate reruns the actual updater on fresh private state.

`runtime/client/auth-reference.lock.json` independently pins client
`0f931bbade36a4b197725d691b8eff7caea7b3be`, build `41012726334.1`, original ARM64
artifact `12958691770` and Wine evidence `12958019059`. The original ZIP hashes,
full passing workflow, matching manifest and exact combined receipt are checked
before use. That measured receipt passed nine Linux ARM64 component scopes,
including real Grunt against the controlled peer; it did not qualify a compiled
server. The application production source lock is not substituted for either
reference.

The first compiled-pair run `41018243765` verified the exact client/server inputs,
prepared Wine and built the dependency image. It then failed on Ubuntu snapshot
HTTP503 responses while fetching test tools, before SQL or Grunt execution.
Artifact12960742516 (SHA256
`1ae48c1980bf0cbf6a9fe69e23ab3050ad0a4ca96ba1d784849e2bbd26cac3f0`)
retains that actual APT solver log. This is an infrastructure failure, not an
authentication result.

The qualification-only extension now uses the exact published dependency rootfs
and a separate offline tool bundle. `runtime/client-auth/tool-inputs.lock.json`
pins the original 32 solver packages plus one separately recorded signed-index
`strace` addition: 33 packages and 21 corresponding source packages/67 original
files. The addition uses the exact base's existing libc6 dependency, replacing
no base package. Both verified InReleases, four index hashes and the original
solver-log identity remain bound. `prepare_client_auth_tools.py` accepts only those exact
bytes from the official Ubuntu pool or the original snapshot; it performs no new
resolution or version substitution. Source files stay outside the image context
and are retained in a separate test-input artifact. The Android runtime recipe
and dependency payload do not gain these tools.

Both images build with networking disabled. Before installation, the actual
dependency metadata and complete dpkg-status file must match the measured
published rootfs. After offline `dpkg -i`, its package inventory must equal the
unchanged original set plus exactly the 33 selected packages; missing dependencies,
upgrades and extra packages fail. Actual native Git/readelf/ip/unshare version
commands must execute, then the original MySQL/Python ELF identities and fresh
state are rechecked. Actual run `41060555263` passed these image gates and
prepared all 33 exact binary packages and 67 source files before its successful
compiled-pair exchange. Source files remain in their separate input artifact.

During execution the
disposable container is read-only and has no network interface beyond loopback;
namespace privileges allow the composer to create its own owned PID, mount and
network namespaces. The same new private host directory is mounted at `/state`
for Wine and `/var/lib/mysql/esteria-client-auth` for the owned SQL fixture;
the temporary filesystem is also writable. The image preflight requires an
unused destination with plain directory parents. An earlier separate diagnostic
[recorded `openat`/`EACCES` on its owned staging directory](evidence/client-auth-initialization-41058676745.json),
before the fallback directory creation returned `EEXIST`; the security mechanism
was not established. The successful retry uses MySQL's intended data tree,
without changing its binary or the container's isolation policy.
Credentials are generated inside this fresh state and never become
Docker arguments, environment variables, or artifacts. Both source checkouts
avoid persisted GitHub credentials, and the execution step receives no token.

## Ownership, private state and evidence

The outer owner creates a new output directory and refuses an already-used Wine
fixture. Its child is PID1 of new private mount/PID/network namespaces. It raises
only loopback and verifies that no other interface exists. MySQL and authserver
remain direct owned native processes; readiness checks require the authserver's
own listener inode at `127.0.0.1:3724`, including immediately before credentials
are supplied. No existing port, account directory or database may be adopted.

The compiled updater is the sole creator of a fresh nested server fixture.
Normal configuration rendering and account/realm provisioning follow. The gate
requires the source-default `StrictVersionCheck=0` instead of changing it; game
asset version-checksum validation remains false. Realm1 must advertise
`127.0.0.1:8085` for build12340. Its offline flag is allowed because the world
server is not part of this gate.

The generated private account is serialized to the client's exclusive 57-byte
`Esteria-auth-input.bin`; no credentials are passed through arguments. The
exclusive public client receipt must contain every actual callback, SRP-proof
and joined-thread check with this run's nonce. The raw 40-byte private session
key must equal the actual account's database `session_key`, with platform/locale
`Win`/`enUS`. The gate also compares unchanged schema/update-ledger, character
trackers, account salt/verifier, private journal and realm configuration.

Qualification requires normal client exit, Wine stop/wait, authserver/MySQL
shutdown, complete bounded log draining and final namespace exit0. Private input
and key files are removed during cleanup. A killed namespace, incomplete worker
receipt or failed shutdown cannot qualify an earlier successful authentication.

Only `OUTPUT/evidence/` is suitable for a public CI artifact. It contains typed
phase/error-class and qualification receipts plus fixed client diagnostic status
lines. Never publish `OUTPUT/private/`, the prepared Wine filesystem, raw Wine or
server crash logs, generated credential files, session keys or initialized MySQL
files. Server logs remain private even if ordinary account redaction would be
possible, because a crash may expose session material before it is returned to
the harness.

The executable receipt deliberately describes only its own authentication
checks and keeps `compiledServerQualified=false`; the outer gate establishes the
additional compiled-server relationship after the owned listener, matching key,
persistence and cleanup checks all pass. Neither receipt qualifies world entry,
characters, gameplay, bots, imported assets or Android execution.
