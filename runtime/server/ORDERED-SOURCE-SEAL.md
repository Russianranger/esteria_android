# Ordered extractor source companion

`tools/seal_ordered_extractor_sources.py` composes a separate corresponding-source
companion for the two measured ordered extractors. It accepts local inputs only:

Native run `41095126683` at `9d20c3bea4f9f2ea7cdfb0915cef1b7ed23faab6`
passed its 104.694-second two-target compile, metadata stabilization, actual
210-object/two-link observation and synthetic lookup checks. The bounded proof
is `runtime/evidence/server-ordered-source-observation-41095126683.json`.
Its measured input lock now identifies the exact 105,175,041-byte payload ZIP.
The full payload readback and this separate source composition remain the x64
workflow's responsibility; the native receipt still has
`sourceCompanionComplete=false`.

Source-only run `41097592284` at `2ca73e3f07b515549c170a6fb0978fb091909ab5`
subsequently passed composition and retention. The exact 64,983,534-byte artifact
ZIP and all 5,675 source archive members (240,249,815 expanded bytes) received
independent full readback. The archive is 63,802,409 bytes with SHA-256
`5fb68b3d204a50c6573857a63192aeff3c92733def9ec69348998624b5571786`;
its separate 1,180,783-byte receipt has SHA-256
`1cbf3a0d25980a3a4785ce7ee50a6de061b6d20875d364a4ae3c8d3c43656149`.
`runtime/evidence/server-ordered-sources-retained-41097592284.json` records this
readback. The measured native input lock remains unchanged. The existing data
tools provider lock now carries these source-output identities in the
`source-sealed-pending-derived-native-cli` state; unmeasured runtime and pair
fields remain null, and production provider creation is still refused.

```sh
python3 tools/seal_ordered_extractor_sources.py \
  --ordered-payload out/ordered-inputs/payload \
  --original-sealed out/ordered-inputs/original-sealed \
  --integration-git-root . \
  --client-readme out/ordered-inputs/client-reference/README.md \
  --output "$RUNNER_TEMP/ordered-complete-sources"
```

The parent acquisition step verifies the whole published payload ZIP against its
artifact ID, byte count, digest, run and integration revision. The sealer requires
the measured `runtime/server/ordered-tools-inputs.lock.json`; a pending native
dependency gate is refused before any output is created. The extracted payload
must contain exactly every `payloadFiles` entry and the original
`ordered-build.json`. Its raw receipt and dependency observation must match the
input lock. Each of the two original executable identities is checked, but the
executables are excluded from this source archive.

`tools/prepare_ordered_extractor_sources.py` acquires that exact payload, the
original 24.7 MB source artifact and the client README. It reuses the existing
stock source-transfer verifier, checks the successful native run and selected
job, and reads back every native payload member. The original installed server
and large paired debug archives are not downloaded for composition. The bounded
native evidence artifact's remote identity is checked without downloading it;
the full dependency logs already reside in the authenticated native payload.
The x64 `server-ordered-sources.yml` job performs acquisition and composition,
with a 3 GiB free-space preflight. It does not execute native programs or compile.

The original seven-patch source archive, qualification and sealed receipt remain
separate immutable inputs. The original archive's complete member set is read
back, including all 266 original files. The sealer extracts its inner source
inputs and the recorded supplement, replays the original seven patches and the
archival revision metadata adaptation, then reproduces the exact original
preparation receipt. It applies only the separately reviewed four extractor
translation-unit changes and the new order header. Full before/after inventories
prove that the rest of the prepared tree is unchanged. The resulting adaptation
receipt must equal the native build's retained receipt.

The native gate performs a fresh two-target build and a second build of those
same targets to settle generated revision metadata. Its observation records 210
actual AArch64 relocatable objects, their compiler commands and Ninja dependency
records, and requires every dependency to be no newer than its referencing
object. The two final linker dependency records are retained separately, bound
to their exact selected link commands and measured executable identities. Local
objects and archives and system linker scripts/libraries have separate hash
inventories; their bytes are not copied into the source archive. Link inputs
must be no newer than the linked output. Unknown or missing dependency records
are refused. The shared retained-graph verifier checks those records against the exact compile
database and raw Ninja logs. Every observed project source/header must be in the
reconstructed full tree with the same identity, and all four adapted translation
units must have actual object records. Every observed generated header is
retained with its recorded identity. System header identities are kept separately;
their sources are not copied, and no comparison with unknown original system
hashes is claimed. The sealer does not read back object bytes from the native
runner; the immutable native observation binds that measurement.

Build recipe closure is exported from the native integration commit's Git
objects, with network fetching disabled. It includes committed Python under
`tools`, `runtime` and `tests`; C/C++/CMake test references; runtime JSON outside
public evidence; config JSON; server documentation; the source lock and license;
and the ordered workflow, header and patch. Every recipe supplied in the native
payload must also equal its committed blob. Working-tree edits, untracked files,
Git configuration and credentials are not imported.

The native integration commit predates the source sealer. Its exported recipes
remain unchanged. A separate `sealing-recipes/` inventory retains the current
sealer, its tests, the shared graph verifier and its tests, acquisition helper,
source workflow, this document, the measured input lock and the raw repository
license. Their exact identities are checked again before publication. An actual
`GITHUB_SHA`, when supplied, is recorded as `creationIntegrationRevision`; these
creation files are not described as blobs from the older native build commit.

The exact ten client policy reference files and their original policy receipt
remain in the curated native payload. The separately pinned client README is
retained with its SHA-256 and Git blob identity. The audit records
`rootLicenseFound=false`, `applicablePolicyNoticeFiles=[]` and
`licenseGrantVerified=false`: the selected client policy files have no identified
applicable notice or root license. Their license is not inferred from the server
license. Server, dependency, Lua and integration notices remain in the original
source inputs and full prepared trees.

The output contains `ordered-extractor-complete-sources.tar.gz` and a new
`ordered-source-receipt.json`. The archive carries the original source archive
and its raw receipts, the source-only native payload, full prepared source tree,
native Git recipe closure, client attribution audit, source inventories and an
offline replay plan and standalone staging helper. Executables, objects, libraries, debug symbols, Git metadata
and client assets are refused. All archive members are read back before the new
positive receipt is published atomically into a fresh directory. Existing output
directories are preserved.

Archive files use a uniform read-only mode. The retained prepared tree is a
readback reference; the replay plan regenerates the original preparation before
building, restoring recorded executable Git/Lua source modes. It then uses the
native integration's two-target driver, which applies the ordered adaptation and
repeats its native environment, compile, dependency and lookup gates. The
matching native ABI/toolchain must be supplied; no package installation or
network fetch is hidden in the replay plan.

After separately verifying and extracting the companion archive, stage its
replay inputs into a fresh directory:

```sh
python3 "$BUNDLE/prepare-replay.py" --bundle "$BUNDLE" --output "$REPLAY"
```

`prepare-replay.py` uses only the Python standard library. It fully verifies and
extracts the original source archive, then follows the plan's complete copy
inventory. It stages `acquired/{source-inputs,environment,supplements}` and the
exact original `acquisition.json`, copies the original build lock, all policy
source files and their receipt, the input environment receipt, and the native
integration's recipe closure. Every source identity, destination, file mode and
directory mode is explicit. Directories use mode 0700; native Git executable
recipe files recover mode 0755. Changed inputs, path escapes, symlinks and an
existing output are refused. Staging does not run the source preparer, compiler
or native programs.

The resulting `commands.json` records a working directory and two exact argument
arrays: original source preparation, then the captured native two-target
builder. Execute those arrays sequentially in their recorded working directory
only in the required native offline build environment. The first command
creates `base`; the second consumes that base and `acquired`, the original lock,
staged environment receipt and `policy_sources`, and creates `native`. No folder
rename or implicit acquisition step is left to the reader. These commands are
retained instructions; sealing and staging do not execute them.

Only this new receipt can assert `orderedSourceCompanionComplete=true`. The raw
native `ordered-build.json` retains `sourceCompanionComplete=false`, and the
original global source archive and receipts are unchanged. Composition performs
no new native compilation. It does not change the global patch selection or
replace server programs, and it does not qualify proprietary client conversion,
custom content load order, world startup, Android execution or gameplay. Runtime
stripping and the paired debug companion are separate gates outside the APK.

Focused host checks use the existing GCC/Ninja fixture. Their machine is x86-64;
they exercise source/dependency record consistency without making an ARM64 claim:

```sh
python3 -m unittest tests.test_ordered_extractor_sources -v
python3 -m py_compile tools/seal_ordered_extractor_sources.py
```
