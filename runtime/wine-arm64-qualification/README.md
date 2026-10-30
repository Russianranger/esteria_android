# Measured source-owned ARM64 Wine and separate client qualification

Run41057900330 at `681b2e9f30b19e94bf8e8de44f67fedba5033c8a` passed the full
native Linux ARM64 build, original/selected PE reference, runtime readback,
complete original-source closure and reconstructed client `0f931bba…` component
gates. Its runtime/source identities are fixed in `runtime-input.lock.json`.
This selects inputs for qualification; production still selects the old immutable
`f036c00a…` runtime and its existing providers.

The measured runtime archive is 282,628,308 bytes, SHA-256
`c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46`.
Independent local streaming readback checked all 14,180 entries, 1,325,744,204
file bytes, 1,029 links and required ELF/PE/notice identities. The measured
hardlink-copy fallback is 45 files and 2,333,910,717 maximum physical bytes.
Both real ARM64 PE modes passed, with zero/two adaptation markers and normal
teardown.

Actual codec, CRT/FP/allocator/C++ unwind/fiber entry, both offline spellings,
real loopback transport, controlled Grunt/SRP positive/negative peer, software
Vulkan presentation/frame readback/texture lifecycle and both captured
WinMM/DirectSound PCM gates passed on this runtime with the exact `0f` client.
Independent receipt checks and retained PCM-byte/signal analysis passed again.
These remain named host component results: CommonMain, real assets, Android
ARM64, Adreno, audible hardware, world entry and gameplay did not run.

The complete source companion is 1,681,474,721 bytes, SHA-256
`38e16617545abb16f995ba75a8b52b8ca2bacad5d2688adf3646911f16c8fb06`.
The successful producer read back all 183 Debian runtime/build source packages /
583 originals, original Wine/FEX/toolchain archives, four exact toolchain Git
trees, 47 toolchain source notices, 22 FEX notices, five adaptation/test inputs
and the complete integration tree. The large companion was not downloaded
locally; its full original-byte validation was executed in CI before client tests.
The public receipts and artifact identities are retained in
[`../evidence/wine-arm64-qualified-41057900330.json`](../evidence/wine-arm64-qualified-41057900330.json).

`client-input.lock.json` separately selects the newer measured client
`471ee42faadf4a97a1d0a86989cf1452621f2dc5`. That client's successful five-job
run41061576677 used the previous runtime. Its pairing with this new runtime must
pass a qualification-only job using the retained runtime and complete sources;
the `0f` result is not relabeled as a `471` result and Wine is not recompiled.

Before production transition, publish a new exact runtime/source release and
rebuild/reverify the client, guest bridge, shader-tool and Turnip descriptors and
source companions against the new archive. Re-audit X11/loader identities and
build a coherent all-provider APK. Existing consumers continue rejecting old
archive bindings. Historical releases and runtime generations stay intact.
