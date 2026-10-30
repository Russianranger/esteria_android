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
