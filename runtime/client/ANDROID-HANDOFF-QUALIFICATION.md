# Android private handoff recovery fixture

`android-handoff-recovery.yml` qualifies only the source-owned local-login file
owner on a fresh Android13 x86_64 emulator. It is not a game APK or a Thor test.
No reconstructed client, Wine, PRoot, native library, SQL engine or imported game
data is packaged or executed by this fixture.

The explicit debug profile uses `-PhandoffEmulatorTest=true`,
`-PnativeBridgeAbi=x86_64` and `-PnativeRuntimeBridge=false`. Runtime providers and
release variants are refused. Its unexported service runs in `:handoffProbe`;
it can kill only its own process. Ordinary APKs contain no fixture service,
class or build-evidence asset. The workflow builds an ordinary APK first and
independently checks those exclusions before building the fixture.

The host qualifier reads the actual compiled binary manifest, including framework
attribute resource IDs, to verify the private process, explicit unexported flag,
debug build and targetSDK35. It rejects native/runtime payloads and requires the
exact fourteen source input identities in `handoff-probe/build-evidence.json`.
The declared exact-source Boolean is insufficient: committed Git blobs, current
working files and the clean source checkout are independently checked. A local
uncommitted SDK build can establish compilation/structural behavior, but cannot
pass execution admission.

The single instrumentation method kills/recreates a remote owner after each
of `created`, `written`, `proof-synced`, `synced` and `consumed`. Binder death and
changed owner instances must be observed. Recovery must preserve unknown stages
and account/database/config siblings while cleaning only recognized unchanged
records. Before-state pairs for the published record/owner receipt are exactly
`false/false`, `false/false`, `false/true`, `true/true`, `false/true`.
The active-owner case additionally verifies same-JVM and cross-process duplicate
refusal, unchanged live data, released ownership and successful later relaunch.

Only a serial matching `emulator-<number>`, qemu=1, API33 and x86_64 is admitted.
Both the application and instrumentation package must be absent; instrumentation
also refuses preexisting private files. Physical devices, previous installs and
existing data are preserved. The qualifier runs one test and validates every
phase/Boolean/count against the exact APK source evidence. It force-stops only
the fresh fixture package it installed, and cleanup acknowledgment is mandatory
before issuing a positive result.

The app exports no account/password, record/proof bytes, nonce, owner UUID or PID.
The host retrieves a bounded receipt into private temporary storage, validates
its exact field set, then exports only the approved JSON. Malformed or extra-field
receipts never enter retained raw logs. Fixed instrumentation/build diagnostics,
filtered bounded logcat, APK/source identities and a complete canonical Git
source companion are retained separately from private app storage.

Run the host guards with:

```sh
python3 -m unittest tests.test_android_handoff -v
```

Ten host groups cover real binary-XML chunks in both encodings, framework-ID
spoof refusal, native/runtime exclusions, exact-source checks, every receipt
phase, fresh-emulator admission, mandatory cleanup and private malformed-receipt
handling. Synthetic APK/transport cases are host guards, not Android evidence.
The binary-manifest reader and ordinary-profile exclusion also pass against an
existing actual SDK-built ordinary APK. Actual remote Binder-death execution
still requires the separate completed emulator job.

Even a positive emulator result leaves production application-process restart,
real client consumption/login, ARM64, physical Thor, SQL and gameplay unqualified.
The selected client471 and its57-byte handoff format remain unchanged.
