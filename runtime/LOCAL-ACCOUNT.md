# Owned local player account

`runtime/provision_local_account.py` creates one ordinary local player account
after the caller has loaded all matching schemas/module updates and reasserted
realm 1. It is isolated from the Android UI for now. It does not start a server,
create a character, populate bots, grant permissions, or establish network login.

The reviewed server is `f35f04d01689f034778e3474b3c820092f51e461`.
`AccountMgr::CreateAccount` allows 17 username and 16 password characters,
uppercases ASCII a–z only, and stores a random 32-byte salt with a 32-byte SRP6
verifier. The exact calculation is
`v = 7 ^ LE(SHA1(salt || SHA1(UPPER_ASCII(user) || ':' || UPPER_ASCII(password)))) mod N`,
where `N=894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7`.
The verifier is padded to 32 bytes, little-endian. Python's general Unicode
`upper()` would be incompatible. Generated usernames are 17 ASCII characters;
passwords are 16 uniformly selected characters from a 32-character alphabet.

The source `account` and `realmcharacters` SQL SHA256 values are respectively
`0d4e185018ab52b6cbb87ef6f2554e4bc1ae2a8394f0d219ba37631e1661f35a` and
`ce6b1c44b436373414ed816ee2f14bf2cbf8736d6dd13da8831fea0c10c043e8`.
Checked-in test fixtures preserve their exact CREATE fragments and source
provenance; they are not runtime migrations. Original SQL licensing remains the
server's GPL-2.0-or-later; retain the source package's LICENSE/AUTHORS notices.

The helper authenticates the bootstrap-owned MySQL UUID/version and loopback
listener, locks the state/config generation and MySQL setup operations, verifies
the real realm endpoint, requires expansion 2, and checks the actual account and
tracker types/defaults/column collations/keys (including full-length unique keys),
InnoDB engines, and absence of triggers or outgoing foreign keys on those two
tables. The pinned realm schema is checked independently.

`state/accounts/local-player.json` is a private mode-0600 credential and ownership
journal, not a support artifact. Intent is flushed before account SQL. The helper
inserts the source AccountMgr fields and only that account's realm-1 tracker in
one transaction. It deliberately narrows AccountMgr's global tracker-initializer
SQL, which would inspect unrelated accounts. Before committing a newly allocated
ID, the helper rejects orphaned auth permissions/bans/mute/tracker rows and, when
the character schema exists, core character/account data belonging to that ID.
Missing required auth tables and partially loaded character schemas fail closed.
This check does not qualify arbitrary module-specific account tables.

Completed setup only verifies the exact account ID/name/salt/verifier. It does
not rewrite the journal, update the password, reset character counts, repair
missing tracker rows, or recreate a deleted account. An interruption after COMMIT
but before the completion receipt is recoverable only when the pending journal's
random salt and verifier exactly match the row. Other name collisions and changed
credentials are preserved and reported as failures. No automatic reset path is
provided. Existing permissions on an already-owned account are also preserved.

```sh
python3 runtime/provision_local_account.py provision \
  --state-root /state --mysql /usr/bin/mysql \
  --expected-version 8.0.46-0ubuntu0.24.04.4
python3 runtime/provision_local_account.py verify \
  --state-root /state --mysql /usr/bin/mysql \
  --expected-version 8.0.46-0ubuntu0.24.04.4
```

No username/password CLI parameters exist. Passwords and verifier material never
appear in argv, standard output, or the public `state/local-account.json` receipt.
The eventual launcher must read the private journal through its owned runtime
path and must exclude accounts/config/database files from support bundles. The
public receipt explicitly leaves auth-protocol and gameplay qualification false.

## Qualification

`tools/qualify_local_account.py prepare` stages the exact 22 auth base SQL files
and three real configuration templates from the pinned Git tree. `qualify` first
verifies their externally supplied manifest digest, source lock, SHA256 and Git
blob identities, then copies them privately before starting a new owned engine.
Every output directory is exclusive: it never adopts, clears, retries, or upgrades
an existing database. The current source fixture has 25 files / 386,271 bytes.

The added `base-sql.yml` phase runs a separate fresh instance in the same exact
ARM64 MySQL dependency image with external networking disabled. It loads the
auth bases only and checks create/repeat, private-credential preservation,
interrupted-commit recovery, name/credential collision rejection, orphan-admin
rejection, schema/collation/prefix-index drift rejection, and persistence after
clean restart. Other accounts and tracker counts are compared, while world,
character, and playerbot schemas remain empty. SQL-client error output stays
private; only receipts and bounded engine diagnostics are uploaded.

`tests/srp6_reference.cmake` adds an isolated, non-installed target to the actual
server CMake graph. `tests/srp6_reference.cpp` calls the real `common` library's
SRP6 and normalization functions against the pinned source vector, rejects a
wrong password/salt and reversed verifier, and emits only public test evidence.
It does not implement substitute crypto. The server workflow builds and executes
this target before continuing the full server build.

Current local evidence: 17 focused Python guard/fixture tests pass; exact source
staging, full readback, and rendering the actual source templates with verified
loopback endpoints/expansion 2 pass. The C++ reference also compiled and exited 0
on the x86_64 GNU++20/OpenSSL host using the actual pinned `SRP6.cpp`,
`BigNumber.cpp`, `CryptoRandom.cpp`, `Util.cpp`, `Errors.cpp` and vendored fmt,
with no stubs or substitute crypto. Boost 1.83 headers were obtained from the
pinned Ubuntu package SHA256
`1412e461d573f66c9d5c7af63696a1d01e11a4724215299a3cf6afd1bcdd3d7f`;
unrelated unused utility sections were eliminated at link time. This is isolated
host crypto evidence; the ARM64 common-target C++ workflow remains pending.
No auth challenge, world entry,
existing-save upgrade, module account behavior, or Android gameplay is qualified.

The actual ARM64 MySQL phase passed in [run 40998008509](https://github.com/Russianranger/esteria_android/actions/runs/40998008509),
job `123875576596`, integration revision
`69b6b9e46ae91dac012dfb55463b81d0652191b8`. MySQL
`8.0.46-0ubuntu0.24.04.4` ran with external networking disabled. The exact 22 auth
bases loaded; owned-account creation, unchanged repeat credentials, interrupted
commit recovery, collision/schema-drift rejection, and clean-restart persistence
all passed. The full 468-file base fixture also passed in that job.

The account evidence artifact is `12951864061` (8,842 bytes), ZIP SHA256
`f034ce232eac6d10355bcda2eef866d9bda5f4d39dd63067bbe43ffb40516d4f`;
download and receipt readback were independently verified. Its qualification
receipt SHA256 is
`6c67ff662a12c1165bdad9b6b3330feeb5452af0f99c9365776d52e25c9bc0fa`,
and the runtime manifest SHA256 is
`3aa480f48fd36cea1253557976163dc2da0707eef72dbef18d028196888b05b1`.
The source fixture manifest is
`54cccae6362ed4cad7d656b3bf12e9da4333c08297af2bb282190f53660eff33`.
This qualifies the disposable account/bootstrap behavior, not a running
authserver, client login, world gameplay, or upgrades of existing saves.
