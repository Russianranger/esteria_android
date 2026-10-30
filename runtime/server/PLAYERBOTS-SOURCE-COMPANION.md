# Separate Playerbots helper source companion

The helper source seal is pending. Actual native source observation run
`41095126547` passed with 201 compiler objects and one ARM64 final link.
The helper schema and installation finish gates passed separately; these
results do not activate a helper provider. The
[`playerbots-sources-inputs.lock.json`](playerbots-sources-inputs.lock.json)
now pins the actual capture, registered helper candidate and original
three-program source triple. Missing, pending or mismatched measurements refuse
sealing before any output directory is created.

The runtime helper remains the original 25,188,512-byte executable, SHA256
`b7d9b72c17f32294915f0a474283c543057ffb7de7b3f93015c2e7e179bfcf25`,
with its unchanged build and actual native SQL receipts. The registered
[helper candidate](PLAYERBOTS-HELPER-CANDIDATE.md) and
[native finish proof](NATIVE-INSTALLATION-FINISH.md) identify those measured
inputs. The three original server programs retain their own complete source
archive, qualification and sealing receipt. A new helper source receipt cannot
replace or relabel that original three-program qualification.

## Native observation and source-only composition

`tools/qualify_playerbots_helper_sources.py` acquires no game assets and requests
only `esteria_playerbots_database_reference` from the exact archived seven-patch
source selection. Its fresh native ARM64 build uses the measured compiler and
relevant package environment, with compiler launchers disabled and external
networking unavailable. A second identical target build stabilizes generated
revision metadata before dependency capture.

The capture requires the actual DatabaseLoader, DBUpdater, PlayerbotsDatabase
and reference compilation units, their `MOD_PLAYERBOTS` definitions and the
52-statement header. It records the compiler objects separately from the final
linker record. The latter must identify exactly one ARM64 helper executable and
its actual object, archive and system linker inputs. Raw Ninja records, compiler
commands, source/header hashes and dependency timestamps must agree. Source
files and final outputs are rehashed after observation. This new executable is
recorded separately, and receives no transferred SQL qualification from the
original measured helper.

After actual native measurements are pinned, the source-only input acquirer
downloads only the measured capture payload, registered helper candidate and
original source triple. It checks successful exact producer/job identities,
outer artifact hashes, member hashes and complete selected file inventories.
It downloads no paired-debug package or dependency image and executes no helper.
The composer can then consume those verified local inputs:

```sh
python3 tools/prepare_playerbots_source_companion.py --output source-inputs
python3 tools/seal_playerbots_helper_sources.py \
  --payload source-inputs/native \
  --candidate source-inputs/candidate \
  --original-sealed source-inputs/original/sealed \
  --integration-git-root . \
  --output ../playerbots-helper-sources
```

The new output must be outside the read-only integration checkout and every
input tree. CI uses a fresh directory below the runner's separate temporary root.

The host integration repository must already contain the exact initial-helper
and native-observation recipe commits, plus the current sealing commit. A CI
workflow fetches those specific integration commits before network isolation;
the composer refuses missing objects and enables no lazy Git fetch. It fetches
neither an original server source repository nor an asset tree.

It verifies the exact registered helper candidate and original three-program
source triple, fully reads the latter archive, reconstructs the original helper
source preparation and compares the original and observed source/reference,
compiler and CMake bindings. It then reads back the complete retained compiler
and linker dependency graph, including the final selected executable identity.
The original native object and archive bytes are not independently present in
this source-only readback; their producer-observed identities remain explicit.

The new archive retains reconstructable source inputs, the prepared source
tree, generated headers, original and new unmodified receipts, source coverage,
notices, and separate committed integration recipes for the initial helper,
native observation and later sealing operation. Genuine empty source files are
retained. Runtime programs and object/archive files are excluded from source
members and listed separately by identity. Original three-program source
archive bytes and receipts remain unchanged inside their own namespace.

The composer publishes its positive helper-source receipt only after full
normalized archive readback and a final recheck of every selected input.
It executes no compiler, helper, SQL engine or Android provider. Its receipt
does not claim bit-identical original binaries, original native object readback,
copied system header/library sources, world execution or gameplay.

## Offline replay

The archive's `replay-plan.json` contains exact argument arrays. Preparation uses
the retained original source archive, supplemental header and archived build
lock. Replay then invokes the archived `build_playerbots_component.py` driver
and the same explicit helper-only stabilization target. Those replay operations
need no Git metadata or asset tree; they require a matching native ARM64
toolchain and an isolated loopback-only network namespace. Recorded preparation
restores the original source modes before compilation.

The native observation driver is retained as producer evidence. Its original
committed-recipe Git guard remains intact and is not advertised as a Git-free
archive replay command. A replay build creates new output; it cannot rewrite
the original helper's build or SQL receipt.

Runtime dependency sources remain part of the separately verified dependency
component. A sealed helper source companion still needs exact provider/archive
binding and install-package verification before the optional helper namespace
can be enabled. Phone execution, Java promotion, imported data, world behavior,
Playerbots AI and device gameplay remain separate gates.
