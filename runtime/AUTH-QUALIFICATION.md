# Owned authserver protocol qualification

`tools/qualify_authserver.py` wraps the existing **fresh, disposable** compiled
updater qualification. There is no argument to adopt a previous save or database:
the same invocation must create the fixture and pass both actual updater runs,
ledger/table checks and MySQL restart before authentication can start.

The wrapper re-verifies every installed ELF against the source/module-bound build
receipt, checks the exact ARM64 authserver and installed auth/world templates,
renders the local configuration, and provisions the owned ordinary player.
Selected source updater behavior remains enabled. Its core/module ledger is
compared before and after authserver startup; the source updater explicitly
excludes `MODULE` entries from orphan cleanup. All module updates precede the
local realm reassertion, and the endpoint is checked again after authentication.

The child must own exactly the `127.0.0.1:3724` listener, verified through its
Linux socket file descriptors and TCP tables. Unexpected IPv4 or IPv6 listeners
fail qualification. It receives a private config filename, never a password in
argv; its environment is explicit, descendants share an owned process group,
and drained output is limited to a private 256-KiB tail. Graceful shutdown is
required. Export redacts database/account credentials, salt/verifier and the
authenticated session key. Private SQL output, configurations and state are not
uploaded.

`tools/auth_protocol.py` implements only the selected source's bounded
build-12340 auth packet layout. It sends the packed 3.3.5 challenge, checks the
fixed generator/modulus/version challenge and the owned account salt, computes
the client SRP6 proof with a random private exponent, verifies the server's M2,
and parses the realm list. It requires exactly realm 1 advertising
`127.0.0.1:8085`. The received session key, `Win` platform and `enUS` locale must
be persisted by the actual authserver. The helper's private credentials and
character tracker rows must remain unchanged. A world-offline realm flag is
preserved and reported; this does not pretend a worldserver is running.

The selected source defaults to `StrictVersionCheck=0`. The probe verifies that
setting rather than changing it, and supplies the unused version-proof field as
zero bytes. Build 12340 is still checked by the server against `build_info`.
Imported game-data build validation is separate and remains mandatory.

The protocol was audited against these files at server revision
`f35f04d01689f034778e3474b3c820092f51e461`:

| Source | SHA256 |
| --- | --- |
| `AuthSession.cpp` | `58e8fe542a3918cbb674e60ba117e25e1cdbaa9841efd96c2a44d4672e261bb9` |
| `AuthCodes.cpp` | `ae792ce6b40f3989564aaaaba23a10c85290dd7ce78a819a9aae36bbe31249d3` |
| `Realm.h` | `ad9fd9abedd93074b5103ec5a46508ef8fabb32d04b143b29f6f217c67c8ad7c` |
| `SRP6.cpp` | `c45100b3148435ec0f66bb8d69363f6d02378dd3114771fd6bad7a255a182b9c` |

`tests/auth_srp_reference.cpp` uses the actual server's `SRP6` constructor,
`VerifyChallengeResponse` and `GetSessionVerifier` with fixed test-only
credentials. The Python probe's proof was accepted by this independently
compiled x86_64 GNU++20/OpenSSL reference, and both returned M2 and session key
matched; a changed proof was rejected. There are no crypto stubs. This reuses the
exact pinned source/dependency setup described in [LOCAL-ACCOUNT.md](LOCAL-ACCOUNT.md).
Twelve focused codec/ownership/diagnostic tests passed, including those two real
C++ exchanges. The server workflow also builds the reference through the actual
ARM64 `common` target and requires those exchanges before its full build.

Actual native ARM64 execution passed in runtime-only run
[`41050050193`](https://github.com/Russianranger/esteria_android/actions/runs/41050050193)
at integration revision `870034ae997bbdba778770f0b1072821678cbf43`.
[The compact evidence](evidence/server-auth-41050050193.json) binds the retained
709,363-byte artifact ZIP, its public receipts, and the original six-patch server
build `41005048019.1` under source lock `dbbf8983…41b0`. This reuses the exact
linked binary; it does not qualify the current seven-patch binary.

The actual compiled updater passed its first run, same-revision repeat, ledger
checks and restart before the authserver passed the owned listener, SRP6 proof,
persisted session key, local realm, credential/tracker preservation and clean
shutdown checks. The same invocation also passed the no-Git packaged-content
consumer and the separately identified source-derived appearance storage gate.
The original source SQL and the fresh appearance adaptation remain distinct;
the latter is not recovered original DDL.

The client side of this exchange is the bounded Python protocol probe described
above. Execution of the reconstructed client remains a separate failing gate.
World entry, character creation, bots, existing-save upgrades and Android
gameplay remain unqualified. The reported realm retains its world-offline flag.
