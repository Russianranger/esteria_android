# Separate source-owned ARM64 Wine candidate

This recipe prepares a new Debian12 ARM64 candidate and runs native host gates.
It does not select a replacement in the APK. The existing `f036c00a…` archive,
`runtime/runtime-sources.lock.json` and every installed/provider binding stay
unchanged. No native ARM64 build or execution success is claimed by these sources.

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
Each toolchain source archive is read back into Git blob/tree identities and
bound to the pinned raw commit object. Unlisted submodules, missing notices,
changed archives and extra source files fail validation. The FEX version argument
is `2510`; FEX's CMake code supplies its own `FEX-` prefix.

`wine-arm64-candidate.yml` runs on a real `ubuntu-24.04-arm` worker. It requires:

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
sources/evidence are retained separately on failures when available. No initialized
prefix, client fixture or private session is exported in the runtime package.

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
