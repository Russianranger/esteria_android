# Separate source-owned ARM64 Wine candidate

This recipe prepares a new Debian12 ARM64 candidate and runs native host gates.
It does not select a replacement in the APK. The existing `f036c00a…` archive,
`runtime/runtime-sources.lock.json` and every installed/provider binding stay
unchanged. Native build/PE evidence is recorded below; full source closure and
current-client qualification remain separate gates.

The reviewed Wine adaptation already passed default/selected Linux x64 PE tests
and actual Android13 x64 prefix, reconstructed entry, offline and loopback tests
in run41046942035. This recipe applies the same exact patch to the same
`a6844d10622fc1a973ec1f22fc4f78a0fcd6cb29` Wine source. It preserves the existing
`arm64ec,aarch64,i386` Wine surface and both ARM64EC/AArch64 FEX translators.
`WINE_ANDROID_PRIVATE_PE_COPY=1` remains an explicit selection; the default
mapping path stays unchanged.

The ARM64 OCI manifest, signed frozen Debian12 repositories, original Wine/FEX
archives, original native LLVM-MinGW toolchain and all fixed Git source refs are
recorded in `sources.lock.json`. The exact 75,125,388-byte toolchain was independently
downloaded and hashed. Its native ELF/embedded LLVM version corroborates LLVM
commit `c5668510b7c8a1881d5764d6a67ff253523d21e9`. MinGW and LLDB-MI source refs
come from the exact retained release recipe; independently proven binary/source
equivalence for those two components is not claimed.

Original Wine, FEX and bundled toolchain notices stay in the runtime. Complete
original Wine/FEX/toolchain archives, the toolchain's recipe/LLVM/MinGW/LLDB-MI
Git trees and original notices, all Debian runtime **and build** package sources,
build logs and the complete integration tree form the separate source export.
Raw Git objects supply each source byte; Git archive/worktree text conversions
cannot change the retained originals. Each source archive is read back into Git blob/tree identities and
bound to the pinned raw commit object. Unlisted submodules, missing notices,
changed archives and extra source files fail validation. The FEX version argument
is `2510`; FEX's CMake code supplies its own `FEX-` prefix.

`wine-arm64-candidate.yml` first captures and verifies all fixed toolchain Git
trees on a host worker. Only a successful preflight enables the real
`ubuntu-24.04-arm` build. The same-run source artifact is independently checked
again after download and supplied directly to the Docker source export. It requires:

1. A source-built runtime and real original/selected ARM64 PE pair: relocation,
   image protections, code execution/cache flush, data/BSS, private isolation and
   writable shared-section communication between live processes.
2. Full normalized runtime/archive readback, exact notice identities and an
   independently verified complete source export.
3. The exact existing `0f931bbade36a4b197725d691b8eff7caea7b3be` client original
   and complete source companion. Its PE fixtures are extracted from that measured
   artifact; the client is not rebuilt from a floating branch.
4. A separately built guest bridge whose input-lock hash and runtime archive
   binding name this candidate. A bridge bound to the old archive is rejected.
5. Current codec, entry, both offline spellings, loopback transport, controlled
   Grunt/SRP peer, software Vulkan presentation/frame readback/texture lifecycle
   and both captured WinMM/DirectSound PCM gates, with bounded namespace cleanup.

The measured candidate lock is an output of the build. The unchanged preparer
accepts it only through `--lock`; the qualifier requires explicit `--runtime-lock`,
`--bridge-input-lock` and `--private-pe-copy`. Selected execution must emit the
real mapping marker. Runtime upload requires the entire host job to succeed;
sources/evidence are retained separately on failures when available. A packaged
runtime from a later failed job is retained under an explicit `unqualified` name,
independently of source closure; it cannot qualify a provider. No initialized
prefix, client fixture or private session is exported in the runtime package.

## First actual native result

Run41051386531 at `b1d96ed0788e0e0d052db0dffe89f7d6c517d0c6` built the exact
Wine/FEX runtime and passed both real native ARM64 PE modes: zero default and
two selected adaptation markers, forced relocation, executable pages, data/BSS,
private isolation, shared writes and normal cleanup. Its fresh archive readback
passed 14,180 entries / 1,325,744,204 file bytes and 52 original runtime notices.
The 282,627,881-byte archive had SHA-256
`cf2e2bfa690d5883924f3b78c216c8b27e61045c13c4d85bf1b1ca75150266eb`.

The strict source gate then stopped at `toolchain-source-blob-size`; current
client fixtures did not run. It had downloaded 183 Debian source packages /
583 originals before failing to retain the toolchain Git tree. Reproduction
showed that `git archive` can apply CRLF, ident or encoding conversions despite
disabling export-ignore/substitution. The exact original offending pathname was
not recorded. Capture now reads raw `git cat-file --batch` objects and retains
the same blob/tree/commit checks, with conversion and large-batch regressions.
Actual complete LLVM capture must pass the new source preflight before rebuilding.

Verified public receipts are in
[`../evidence/wine-arm64-candidate-41051386531.json`](../evidence/wine-arm64-candidate-41051386531.json).
That failed run retained only bounded logs/receipts, not the measured archive;
the new failure-only upload prevents losing that output on later gate failures.

## Later provider transition

Passing these native host gates would still leave Android ARM64 and Thor open.
Before any APK transition, publish the exact new runtime plus full sources and
rebuild/reverify each archive-bound dependency coherently:

| Binding | Required follow-up |
| --- | --- |
| Runtime setup | New measured runtime/archive/marker/component/installer identities; preserve the old immutable generation. |
| Reconstructed client | Rebuild its provider descriptor and source companion against the new Wine archive. |
| Guest bridges | New source-verified provider/receipt bound to the new archive; rerun presentation/input/PCM gates. |
| X11 closure | Re-audit actual loader/library/alias bytes and rerun authenticated input. |
| Shader tools | Rebuild its provider/source descriptor against the new Wine archive and rerun real tool gates. |
| Turnip | New exact provider/source binding and actual loader/ICD gate; Adreno remains separate. |

Existing Java and host consumers keep rejecting mismatched old bindings. The
Ubuntu24 server guest remains separate. No Android policy, target SDK or imported
asset requirement is relaxed, and no gameplay or persistent world-save result is
inferred from these component tests.
