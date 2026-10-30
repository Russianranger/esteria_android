# Server executable packaging

The installed reference server uses `RelWithDebInfo`. Its six-patch installed
receipt records a 2,646,600,344-byte worldserver, a 34,991,328-byte authserver and a
26,569,848-byte dbimport. These are original build inputs, not APK-ready runtime
payloads. The current application selects seven patches; a six-patch binary must
not be relabelled as that selection.

`tools/server_engine_elf.py` implements the first derivative layer. The exact
LLVM objcopy executable is bound to the fully hashed NDK28.2.13676358 archive in
`engine-strip.lock.json`. Its Linux x64 host tools can process AArch64 ELF files
without executing them. This is a packaging tool choice, not a change from the
server's GNU/Linux ABI to Android Bionic.

The tool creates a separate `.debug` file and a stripped executable with a
CRC-bound GNU debug link. It checks the original file again after processing.
Every program header and all file-backed program segment bytes must remain
identical, except the ELF header's section-table location/count fields. Every
allocated section remains byte-identical. Debug sections retain their original
bytes; each symbol retains its name, target section, binding, visibility, value
and size even when objcopy rearranges string-table offsets. Existing output
files are refused. The enclosing packager must use a fresh private staging
directory, preserve partial failures and publish only a fully verified package.

Twelve ELF test groups pass, including ten cases using a real NDK-compiled
AArch64 ELF fixture with separate debug data. The fixture is never executed.
Checks cover deterministic repeated output, loaded-code corruption, changed debug
data/symbols, incorrect debug links, tool identity, malformed section bounds and
existing-output preservation. The executable was independently compared against
its entry in the full hash-verified NDK ZIP. **No actual authserver, worldserver or
dbimport derivative has been produced or qualified yet.**

Run the actual ELF tests with the resolved NDK toolchain directory:

```sh
ESTERIA_NDK_TOOLCHAIN=/absolute/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin \
  python3 -m unittest tests.test_server_engine_elf -v
```

`tools/package_server_engine.py` now implements the preparatory package layer.
It rechecks the exact selected source checkout/patches, current source lock,
original `server-build.json`, actual compiled module literals and compile commands
before selecting the three executables and the complete installed configuration
selection (53 templates in the measured build). Old six-patch inputs are refused
under the current seven-patch source lock. Unknown ELF files, including a future
private shared library in `bin/`, require explicit packaging review.

The immutable mount contract is `/esteria-server-programs`, retaining `bin/` and
`etc/` hierarchies. Original manifests stay byte-identical in `provenance/`; a
separate derivative manifest identifies the new binary/debug hashes. The original
module receipt's binary hashes are never rewritten to disguise stripping.

On a Linux **x64** packaging runner, after fetching the exact original installed
artifact, its compiled-module receipt and its diagnostic compile commands:

```sh
python3 tools/package_server_engine.py \
  --install out/server-install --compiled-modules out/server-modules.json \
  --compile-commands out/server/compile_commands.json \
  --lock sources.lock.json --server sources/server \
  --ndk-archive out/android-ndk-r28c-linux.zip \
  --objcopy out/ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-objcopy \
  --output out/server-engine-package
```

The pinned objcopy is an x64 host executable and must not be run in the native
ARM64 build job. The AArch64 inputs are processed as data, never executed. Budget
at least 8 GiB of working space for the original ZIP, original install, NDK and
debug outputs; compressed output archives need additional room. CI should reuse
the retained exact artifact rather than downloading it into a limited local
workspace or recompiling the server solely for stripping.

The output contains deterministic GNU `server-engine-runtime-arm64.tar.gz`,
`server-engine-debug-arm64.tar.gz` and `package-receipt.json`. Runtime includes
only the three stripped programs, selected immutable templates and provenance.
Debug includes the paired symbols, original receipts, compile commands and strip
recipes. Both archives receive complete member/hash/mode readback before atomic
publication. Existing output and output inside either source/install tree are
refused; failures retain a private unpublished stage for diagnostics.

Eleven packaging test groups cover source-selection refusal, configuration and
receipt mutation, unknown ELF rejection, archive metadata/bounds, existing output
and failed-stage preservation. One uses actual AArch64 derivatives from a synthetic
fixture and checks both final archives; it does not execute the fixture or attest
a server source companion. These package outputs are explicitly **unsealed**:
`sourceCompanionComplete`, `androidProviderCreated` and runtime/gameplay flags
remain false. No actual authserver/worldserver/dbimport package has been produced
by this tool yet.

Runtime packaging must omit extractors, installed static libraries, developer
headers and all database/private state. A matching separate debug/source
companion must retain original source archives, all selected source/module/static
dependency notices, Eluna, exact adaptations, build/strip recipes and both
original/derivative receipts. Lua5.2.4 is fetched by CMake rather than committed:
its exact original archive must be included. The repository also contains game
assets and unrelated binary tools, so blindly exporting its entire Git tree is
not an acceptable source companion. The source-root/notice audit, actual
seven-patch input verification and isolated-source rebuild remain prerequisites
for sealing that companion. Keep the original preparatory receipts; a later
sealing receipt must bind both archives and complete source/debug companions by
exact identities.

These operations do not initialize SQL, launch a server, qualify Android, or
establish gameplay. Complete loaded-byte comparison is required even after an
actual native loader smoke test succeeds; neither replaces matched schemas,
content, local authentication and world-entry qualification.
