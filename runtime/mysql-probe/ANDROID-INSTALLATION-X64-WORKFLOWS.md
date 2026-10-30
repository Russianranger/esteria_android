# Source-bound x64 installation qualification workflows

These are internal Android13 x64 SQL/coordinator checks. They do not qualify
production ARM64, Thor, game data, auth/world execution, character persistence or
bot AI. The committed Android provider and artifact selections remain disabled.

| State | Allowed work | Required evidence |
| --- | --- | --- |
| Native SQL/provider pending | Host refusal and source tests | No downloads, provider generation, SDK or emulator execution |
| Actual native SQL qualified; provider pending | Provider measurement workflow | Separately admitted actual x64 build, complete source/debug/library readback and successful four-schema native SQL |
| Provider artifacts measured and selected | Exact artifact acquisition and Android workflow | Actual descriptor/readback plus successful producer run/job and complete/evidence artifact byte identities |
| Android execution complete | Report only the specific new coordinator result | Current APK/source checks, actual instrumentation, live four-schema SQL, promotion, reseeding refusal, same UUID restart and two clean stops |

`android-installation-x64-provider.yml` first admits the actual native SQL
selection. It reads original tool/debug/library sources, the original x64 MySQL
provider and original public SQL content. All outputs and the exact frozen817
Git worktree stay outside the clean current source checkout. The builder and
independent reader generate a closed provider/source product; the seal retains a
canonical full measurement-source archive and streams every product identity.
Two artifacts preserve the complete product and six bounded JSON receipts. No
job edits a selection lock, executes SQL, builds an APK or enables Android.

The root must independently read the small artifact and actual producer
metadata before selecting its exact measured fields in
`android-installation-x64-provider-artifacts.lock.json` and
`android-installation-x64-inputs.lock.json`. No generated placeholder can enable
either lock. The full product still must be downloaded and read by its consumer;
small metadata is not a substitute for original sources and paired debug.

`android_installation_x64_provider_artifacts.py acquire --output <new-directory>
--frozen-source <exact817-worktree>` checks both measured gates before creating
output or contacting GitHub. It verifies the exact completed producer run/job,
artifact digests, closed ZIP inventory, bounded six-member evidence and full
original source/debug readback. It recomputes canonical producer P Git bytes,
rejecting local Git replacement objects, and separately checks current Q source
bytes. It restores exact old MySQL inputs and PRoot payloads, then invokes only
the whole-checkout-admitted original817 verifier. Current code never inherits
that runtime's historical Java result.

The output contains `provider/`, `corresponding-source/`, `mysql-provider/`,
`proot-provider/` and a source-bound `acquisition.json`. Existing output is
preserved and refused. Interrupted/private staging is never a completed receipt.
Downloads, database state, journals, account options and private logs are not
included in the APK. All original source archives remain outside it.

`android-server-installation-x64.yml` requires both selected provider and artifact
locks before downloads, SDK setup or emulator creation. Full Git history supplies
producer P objects while compiling activation Q. Only selected source bytes must
remain equal; Q's newly committed selection metadata may differ. The workflow
exports the entire canonical Q source archive separately and builds the explicit
debug x64 profile, retaining the unchanged standalone MySQL current-source guard.

`qualify_android_installation_x64.py` admits exact APK/provider/MySQL/PRoot bytes,
the current database helpers, compiled manifests, fixed instrumentation class and
full Q Git/blob/mode/source archive. A declared `gradlew.bat` CRLF checkout is
recorded separately from canonical Git bytes; other conversions, tracked source
symlinks and hidden foreign source changes refuse. It accepts only a fresh
Android13 x64 emulator without the fixed application/test packages already
installed. Its fixed test executes the actual retained Java coordinator.

Only an exact positive app receipt can report Android x64 coordinator success.
The reader checks all thirteen lifecycle/SQL flags, original content/runtime/
program hashes, a new instance UUID, and the actual schema counts against native
SQL. A failure or failed owned-fixture cleanup stays unqualified. Raw ADB output,
private malformed receipts, SQL rows, journals, credentials and logcat are never
published. APKs remain labeled unqualified until the actual execution succeeds.

Host checks cover real closed ZIP reads, unsafe/changed/oversized members,
producer/source mutations, real Git P/Q distinctions and CRLF conversions,
strict receipt rejection, default refusal before ADB/output and fixed cleanup.
They do not replace the future full provider measurement or actual emulator run.
