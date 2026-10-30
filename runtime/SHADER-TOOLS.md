# Offline shader tool bundle

`tools/package_shader_tools.py` packages the seven committed Python translator
files from an explicitly selected reconstructed-client commit with one real
Linux ARM64 `glslangValidator`. It never copies the client engine or imports game
assets. The application client source pin is independent and is not changed by
this operation. The selected shader revision must support the strict translator
contract; the first such reviewed revision is
`926a6f73253720283ead9d7621ffd6d7d9c040cd`.

Supply clean, exact checkouts for both source revisions and a fully extracted,
verified Turnip build artifact. The compiler receipt SHA must come from the
downloaded artifact's independently checked identity, not an untrusted directory.
`readelf`, Python 3.11+ and Git are required on the Linux packaging host.

```sh
python3 tools/package_shader_tools.py \
  --client /absolute/exact-client-checkout \
  --client-revision 926a6f73253720283ead9d7621ffd6d7d9c040cd \
  --integration /absolute/exact-compiler-build-checkout \
  --integration-revision FULL_COMPILER_BUILD_COMMIT \
  --turnip-payload /absolute/verified-turnip-export \
  --build-sha256 MEASURED_TURNIP_BUILD_JSON_SHA256 \
  --output /absolute/new-shader-bundle
```

`tools/` contains exactly the runtime helper's eight-file closure plus
`shader-tools.json`. The manifest records source revision and every file's byte
count and SHA-256. Use this directory as `runtime/shader_generation.py`'s tool
root. Preserve the sibling `provenance/`, `corresponding-source/`, `notices/` and
`NOTICE.txt` when distributing it. They are deliberately outside the executable
closure so unexpected executable files remain rejected.

Packaging checks committed Git blobs against the selected working-tree files,
compiler ELF architecture/interpreter/dependencies/GLIBC limits, its exact build
receipt, and successful native compiler/validator/disassembler fixtures. It
retains the original glslang, SPIRV-Tools and SPIRV-Headers archives, compares
their original license bytes, and binds package copyright notices to the build
receipt. Compiler recipe files and input locks are independently compared with
the exact integration Git revision. Output is staged, reread and published
without replacing an existing directory. No source or executable input is run
during packaging except the host Git/readelf tools.

Native compiler evidence does not establish Android execution or successful
translation of the user's imported shaders. Full Wine rootfs source closure is
also outside this bundle. The original client checkout has no top-level license;
the bundle preserves its source and notices without assigning a different
license. The full compiler-build source companion remains separately identified
by the retained build recipe and lock.

`python3 -m unittest tests.test_shader_tools_package` exercises real temporary
Git commits, exact closure/readback, interrupted publication refusal and mutated
sources/compiler/notices. Its compiler is explicitly synthetic and never
executes; real ARM64 compiler packaging still requires the measured CI artifact.

## Measured compiler bundle

The first real package was built from client
`926a6f73253720283ead9d7621ffd6d7d9c040cd` and integration
`8a42261db0413ce10ce9a01cd669264a5d5b90fc`. Its 69 files total 16,602,254 bytes,
including the three original compiler source archives and notices. The runtime
generation helper independently accepted its exact executable-file closure.

| Measured item | SHA-256 |
| --- | --- |
| Turnip build receipt | `52f4214ce6af27985fe80a9e0aec55e6bd2c5f0c867b6ded0987bf9aa4ea9ef0` |
| `glslangValidator`, 8,234,112 bytes | `279cb8d922fa71319e12eb63b46a1c6f80938d07747cec73326ec64928a044fc` |
| `shader-tools.json` | `45ca24037e24fcd7eddf2cc70c5dffaa57de7386ef96f24801d6eb91e7086767` |
| Bundle provenance receipt | `6106d53fd5a63438606743f1b9dff142e9dbb19131b10b65b75adf79c5bab48e` |

The real ELF requires `libc.so.6`, `libm.so.6`, `libstdc++.so.6`, GLIBC through
2.34 and GLIBCXX through 3.4.29. Native ARM64 valid compilation, SPIR-V validation
and disassembly, invalid GLSL rejection and invalid SPIR-V rejection passed in
[run 41008439895](https://github.com/Russianranger/esteria_android/actions/runs/41008439895).
The run's separate Turnip driver test on a host without a GPU failed; that result
does not change the compiler fixture's narrower evidence. Android shader setup
and shaders from imported MPQs remain unqualified. The application client pin
remains independent and unchanged.

The complete original artifact is 267,867,656 bytes, SHA-256
`43867f8121d34a8140e9b30757d667bf58ef58e8b8e2b613092786c28f637271`,
[artifact 12956644900](https://github.com/Russianranger/esteria_android/actions/runs/41008439895/artifacts/12956644900).
Actions retention is temporary. The exact Docker recipe and source originals
remain the rebuild path; distribute the source companion with any future durable
tool release.

## Optional Android provider and setup API

`runtime/shaders/android-provider.lock.json` binds every measured bundle file,
the original artifact and the exact committed generation helper. Build and verify
an optional APK provider from that package:

```sh
python3 tools/provider_shader_tools.py build --bundle /absolute/new-shader-bundle --output /absolute/new-shader-provider
python3 tools/provider_shader_tools.py verify --provider /absolute/new-shader-provider
./gradlew :app:clean :app:assembleDebug -PnativeRuntimeBridge=true -PnativeBridgeAbi=arm64-v8a -PshaderToolsProviderDir=/absolute/new-shader-provider
python3 tools/provider_shader_tools.py verify --provider /absolute/new-shader-provider --apk app/build/outputs/apk/debug/app-debug.apk
```

The provider includes the 69 bundle files and the exact source-backed generation
helper. Its deterministic regular-file GNU tar archive is 10,635,594 bytes,
SHA-256 `7937274c8379882a045fb93c50ea9bb8575e25d5f769f7d8a3077d1518522c57`.
The production Java installer read back all70 files (16,621,607 bytes), checked
the ARM64 ELF, and reused the completed generation without opening an archive,
under a32MiB host heap. This is host installation evidence, not Android execution.
The archive stays uncompressed inside the APK. Builds without the optional
provider compile with `SHADER_TOOLS_PACKAGED=false`; missing tools fail explicitly.

`ShaderToolsSetup.prepare()` streams the bundled archive into its owned cache and
installs a separate `runtimes/shader-tools-arm64` generation. It never writes into
Wine, imported assets, saves or databases. Both provider installation and the
exact Wine archive ABI are checked before `ShaderSetup.prepare()` starts its
owned guest process. The provider is mounted at `/esteria-shader-tools`; the
complete import store is mounted at `/esteria-data` so the helper can bind its
completed overlay ancestry. Persistent generated outputs live in
`state/shader-work/shaders`. Each operation has separate bounded process logs.
Neither helper nor application performs a background download.

The API requires an explicit supported locale and caller serialization against
import activation and client execution. A local operation lock separately
excludes duplicate shader jobs. Cancellation, timeout or interruption stops the
whole owned guest tree and retains prior generations and staged outputs. A fully
completed atomic promotion can win a cancellation race; cancellation never rolls
back or deletes an already completed generation. The helper independently checks
its tool closure, completed import metadata, strict translator output and every
shader hash before activation. The Android adapter checks the typed receipt,
input-generation hash, current import and journal identities, and canonical
output paths/sizes. It does not rehash entire MPQs or assert GPU correctness.

`ShaderSetup` is deliberately not invoked by a launcher action yet. Actual ARM64
Android compiler execution and strict translation from an available imported
build12340 MPQ set remain required. The prepared translator revision is separate
from the application's current client PE pin; neither gameplay nor shader/render
qualification is inferred from installing this component. The core command/path
checks and synthetic Android receipt test exercise guards only. No replacement
game shaders or assets are included.

The optional provider was also included in an internal ARM64 build together with
PRoot, server dependencies, guest bridges and reconstructed client. Core checks,
APK and instrumentation compilation, and Android lint passed. All five independent
provider verifiers matched the final APK's bytes; the shader archive was
`ZIP_STORED`. The synthetic receipt instrumentation test compiled but has not
been executed. This internal package is not the requested device-test candidate.
