#!/usr/bin/env python3
"""Stage one additive stock release from a verified persistent signing receipt."""
import argparse
import json
from pathlib import Path
import re
import shutil

try:
    from . import sign_android_apk as signing
except ImportError:
    import sign_android_apk as signing


def stage(args):
    signing.require(re.fullmatch('[0-9a-f]{40}', args.app_revision), 'exact-app-revision-required')
    signing.require(re.fullmatch('[1-9][0-9]*', args.run_id), 'run-id-required')
    signing.require(not args.output.exists(), 'release-output-already-exists')
    receipt = json.loads((args.signed / 'signing-receipt.json').read_bytes())
    proof = json.loads(args.cohort_proof.read_bytes())
    apk = args.signed / 'esteria-development.apk'
    signed = receipt['signedApk']
    signing.require(receipt['persistentSigningIdentityVerified'] is True
                    and receipt['qualificationOnly'] is False and receipt['payloadPreserved'] is True,
                    'persistent-signing-and-preserved-payload-required')
    signing.require(signed['packageId'] == signing.STOCK_PACKAGE and signed['debuggable'] is False,
                    'stock-nondebuggable-package-required')
    signing.require(signed['apkSha256'] == signing.digest(apk) and signed['apkBytes'] == apk.stat().st_size,
                    'signed-apk-identity-mismatch')
    signing.require(proof['apk']['sha256'] == receipt['inputApkSha256']
                    and proof['completeAssetInventoryVerified'] is True
                    and proof['exactCurrentHelperClosureVerified'] is True,
                    'complete-provider-proof-required')
    lock = json.loads((signing.ROOT / 'sources.lock.json').read_bytes())
    signing.require(re.fullmatch('[0-9a-f]{40}', lock['sources']['client']['commit'])
                    and re.fullmatch('[0-9a-f]{40}', lock['sources']['server']['commit']),
                    'exact-engine-revisions-required')
    instructions = signing.ROOT / 'NON-CUSTOM-TESTING.md'
    signing.require(instructions.is_file() and instructions.stat().st_size > 0, 'consolidated-instructions-required')
    tag = 'non-custom-v' + signed['versionName']
    signing.require(re.fullmatch(r'non-custom-v[0-9A-Za-z._-]+', tag), 'release-tag-format')
    result = dict(formatVersion=1, tag=tag, branch='non-custom', contentProfile='stock-3.3.5a',
        appRevision=args.app_revision, clientRevision=lock['sources']['client']['commit'],
        serverRevision=lock['sources']['server']['commit'], buildRunId=int(args.run_id),
        sourceLockSha256=signing.digest(signing.ROOT / 'sources.lock.json'),
        serverAdaptations=lock['sources']['server'].get('patches', []),
        serverSubmodules=lock['sources']['server'].get('submodules', {}),
        signedApk=signed, completeProviderBytesVerified=True, sourceReviewedStockSupport=True,
        actualUserClientValidated=False, graphicalClientStartupQualified=False,
        characterCreationQualified=False, worldEntryQualified=False, thorQualified=False)
    if 'rendererSelection' in proof:
        contract = signing.ROOT / 'runtime/client/renderer-compatibility.json'
        renderer = json.loads(contract.read_bytes())
        signing.require(proof['rendererSelection'] == renderer and
                       proof.get('rendererContract') == {'bytes': contract.stat().st_size, 'sha256': signing.digest(contract)} and
                       renderer['preparedClientRevision'] == result['clientRevision'] and
                       renderer['preparedSourceLockSha256'] == result['sourceLockSha256'],
                       'release-renderer-recipe-selection-differs')
        result.update(preparedClientRevision=renderer['preparedClientRevision'],
                      clientRevision=renderer['executableRevision'],
                      clientExecutableSha256=renderer['executableSha256'],
                      clientRuntimeArchiveSha256=renderer['clientArchiveSha256'],
                      rendererCompatibilitySha256=proof['rendererContract']['sha256'])
    args.output.mkdir(parents=True)
    name = 'Esteria-Stock-3.3.5a-arm64.apk'
    shutil.copyfile(apk, args.output / name)
    (args.output / 'release.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    (args.output / 'SHA256SUMS').write_text(signed['apkSha256'] + '  ' + name + '\n')
    setup = ('Keep the completed client import and retry Prepare local runtime / world, then\n'
             'start the local game. Follow the attached NON-CUSTOM-TESTING.md procedure, including\n'
             'the offline repeat and support bundle export if a stage fails.' if signed['versionCode'] in (5, 6, 7, 8, 9, 10, 11) else
             'Import your complete ChromieCraft client, prepare the local runtime/world, then\n'
             'start the local game. Follow the attached NON-CUSTOM-TESTING.md procedure, including\n'
             'the offline repeat and support bundle export if a stage fails.')
    if signed['versionCode'] == 12:
        setup = ('Install over the existing Esteria Stock app and keep its completed import, prepared\n'
                 'world data, configuration, databases and saves. With the same locale selected,\n'
                 'choose Start local game if preparation already completed. If stock shaders or\n'
                 'database preparation are still missing, use Prepare / fully verify local runtime\n'
                 'and world to finish that preparation, then Start local game.\n'
                 'Do not uninstall, clear storage,\n'
                 'reimport or delete completed navigation output. Follow NON-CUSTOM-TESTING.md;\n'
                 'export support before another attempt after a failure.')
    if signed['versionCode'] in (13, 14):
        prior = signed['versionCode'] - 1
        setup = ('Install over the existing Esteria Stock app. Keep the completed import, world data,\n'
                 'databases, configuration and saves. Select the same locale used for preparation.\n'
                 f'After the v{prior} shader failure, choose **Repair local component → Shaders**. Once it\n'
                 'finishes, choose **Start local game**. If it reports a missing database, use\n'
                 '**Repair local component → Database setup**, then start the local game again.\n'
                 'If a stage fails, wait for cleanup, tap **Export support bundle**, choose a\n'
                 'destination and tap **Save**. Send the whole ZIP before retrying.')
    if signed['versionCode'] == 24:
        setup = ('Install over the existing signed Esteria Stock app. Choose **Play → Start local game** '
                 'and select your existing character. Keep the same enUS, Balanced and display settings. '
                 'After normal logout and a clean session stop, use **Tools → Export support bundle**.')
    elif signed['versionCode'] == 23:
        setup = ('Install over your existing signed Esteria Stock app, then choose **Start local game**. '
                 'Tap the movable gear for the keyboard, display settings and session controls. '
                 'The default client cap is 30 FPS. Choose **Tools → Export support bundle** after logout.')
    elif signed['versionCode'] == 22:
        setup = ('Install over the signed Esteria Stock v21 app. Keep the ChromieCraft import, enUS, Balanced '
                 'and both retained database attempts. Choose **Repair local component → Database setup** once. '
                 'Wait for four-schema completion and a clean stop, then choose **Start local game**. '
                 'If it stops, export the complete support ZIP after cleanup.')
    elif signed['versionCode'] == 21:
        setup = ('Install over Esteria Stock. On the retained v19 Thor installation, keep enUS and Balanced. '
                 'Choose **Repair local component → Database setup**, wait for completion, then **Start local game**. '
                 'If a phase fails, wait for cleanup and export the complete support ZIP before retrying.')
    elif signed['versionCode'] == 20:
        setup = ('Install over Esteria Stock and keep your import, selected locale, databases and saves. '
                 'From a prepared v19 installation, tap **Start local game**. '
                 'When updating from before v19, use **Repair local component → Client runtime** once. '
                 'For a previous shader failure, use **Repair local component → Shaders** once, then start. '
                 'If startup fails, wait for cleanup, tap **Export support bundle**, choose Downloads '
                 'and tap **Save**. Send the complete ZIP.')
    elif signed['versionCode'] == 19:
        setup = ('Install over Esteria Stock. Keep the existing import, selected locale, prepared world and saves. '
                 'Tap **Repair local component → Client runtime** once to select the updated executable. '
                 'If shader preparation previously failed, tap **Repair local component → Shaders** once. '
                 'Once shaders are ready, tap **Start local game**. '
                 'If either repair fails, use **Export support bundle**, choose Downloads and tap **Save** '
                 'before retrying.')
    elif signed['versionCode'] == 18:
        setup = ('Install over Esteria Stock. Keep the existing import, configuration, databases and saves. '
                 'With the client and shaders prepared, tap **Start local game**. '
                 'If the previous failure was at shaders, choose **Repair local component → Shaders** once, then start. '
                 'After a new failure, wait for cleanup, tap **Export support bundle**, choose a destination '
                 'and tap **Save**. Send the complete ZIP.')
    elif signed['versionCode'] == 17:
        setup = ('Install over Esteria Stock and keep the existing import and saves. '
                 'From v16 with the client and shaders prepared, tap **Start local game**. '
                 'For a previous shader failure, choose **Repair local component → Shaders** once, then start. '
                 'If upgrading from before v16 and you still need the corrected client, or Start names it, '
                 'choose **Repair local component → Client runtime**. '
                 'For a new failure, export the complete support ZIP before retrying.')
    elif 'rendererSelection' in proof:
        setup = ('Install over the existing Esteria Stock app. Keep enUS and Balanced. Select '
                 '**Repair local component → Client runtime** to install the corrected executable. '
                 'If shaders previously failed, choose **Repair local component → Shaders** once. '
                 'A completed compatible shader generation can be reused. Choose **Start local game**. '
                 'Use **Repair local component → Database setup** if the launcher names it. '
                 'For a new failure, tap **Export support bundle**, choose a destination and tap **Save**.')
    notes = f'''Esteria Stock 3.3.5a / non-custom {signed['versionName']}

Separate Android package `{signing.STOCK_PACKAGE}`; installs beside the custom app.
The source path targets genuine stock build 12340 client data and keeps original
signed UI checks. Client files and Thor gameplay are not verified by this build.

{setup}

App `{args.app_revision}`; reconstructed ARM64 client `{result['clientRevision']}`;
server `{result['serverRevision']}`. Build run `{args.run_id}`.
APK SHA-256: `{signed['apkSha256']}`.

Custom MPQs/races/appearances/HD/Retail/Forever content and bot AI qualification
are deferred. Generated stock world data and Vulkan shaders remain required.
'''
    if signed['versionCode'] == 3:
        notes += '''
Version 3 reduces import allocation and retained source metadata, preserves
version-2 import resume, and stores stock-inspection MPQ tables compactly.
Android 13 component stress tests imported 1 GiB by folder and ZIP and checked
3,210 files. These fixtures do not reproduce the owner's Thor low-memory kill.

Install over the existing stock app without uninstalling or clearing data.
Retry the same client source with its normal Data layout. If Android kills the
app again, reopen it and export support before another import; the bundle now
contains sampled import heap values and bounded Android process-exit history.
'''
    if signed['versionCode'] == 4:
        notes += '''
Version 4 deliberately slows both folder and ZIP imports to 8 MiB/s, flushes
2 MiB write batches and asks Android to release their clean file-cache pages.
Low-memory observations reduce copying to 2 MiB/s or wait for recovery.
Sustained severe pressure pauses safely with completed work retained for retry.
The ZIP staging pass and nonseekable resume reads use the same policy.

Install over the existing stock app without uninstalling or clearing data.
Retry the same complete client source with its normal Data layout. Each 1 GiB
copy takes at least 128 seconds; ZIPs require staging and extraction passes.
If Android closes the app again, reopen and export the whole support bundle
before another import. Actual Thor import/gameplay still need device confirmation.
'''
    if signed['versionCode'] == 5:
        notes += '''
Version 5 extends memory controls to local-world preparation after the owner's
v4 folder import completed successfully. Keep that completed import and app data;
install over the existing stock app and retry Prepare local runtime / world.
No client reimport, uninstall or data clearing is required.

Java/Python preparation verification is limited to 8 MiB/s, dropping to 2 MiB/s
under pressure or pausing. One full hash pass over the reported 15.6 GiB archive
set takes roughly 34 minutes at the normal rate; later phases add time. Native
extractors retain their own speed. Their children receive a 4 GiB virtual-address
limit per process, clean-input cache advice and supervised cleanup. This is not
a native I/O cap, an RSS measurement or a total app-plus-children RAM guarantee.

The shader adapter uses packed archive tables and bounded shader records while
retaining the verified original decoder/emitter/compiler path. Memory pauses use
a distinct outcome, retain completed phases and do not cache failed stock reports.
Durable phase receipts and independently validated partial logs improve support
exports. If Android closes the app, reopen and export support before another
preparation attempt. Do not reimport the already completed client.

Two v4 owner bundles recorded successful folder import and three unique Android
LOW_MEMORY exits during later preparation. Missing helper logs did not identify
the exact child or allocation. Host/synthetic checks do not establish that the
Thor failure is eliminated; actual v5 preparation and gameplay remain unqualified.
'''
    if signed['versionCode'] == 6:
        notes += '''
Version 6 fixes the Turnip graphics readiness timeout seen during v5 preparation.
Paced provider and launch-specification validation now completes before the
five-second native probe execution budget begins. Native process startup remains
inside that budget. The probe still requires the original GPU pixel-readback
receipt and retains cancellation, provider identity and owned cleanup checks.

The reported v5 failure was a graphics timeout with about 9 GB of memory
available, not a newly recorded low-memory kill. Existing preparation memory
controls remain active: paced verification, bounded shader retention and native
child memory guards. No graphics check is skipped and no source pin is changed.

Install over the existing stock app, keep app data and the completed client
import, and retry Prepare local runtime / world with the same locale. No reimport
or data clearing is needed. A full verification pass over 15.6 GiB still takes
roughly 34 minutes at the normal 8 MiB/s rate; later phases add time. If a stage
fails, export the complete support bundle before another preparation attempt.
Actual Thor world preparation, rendering and gameplay remain unqualified.
'''
    if signed['versionCode'] == 7:
        notes += '''
Version 7 corrects ordered map/DBC extractor file enumeration. Archive listfiles
are bounded and checked while only the requested DBC names are retained, so
unrelated texture, audio and world filenames do not exhaust the effective DBC
inventory. Provider order, path validation and deletion markers remain enforced.
The native extractor pair is rebuilt from the pinned server and adapted sources.

The v6 support report confirms the graphics probe passed in 243 ms, followed by
map_extractor exit 2 at the ordered effective file count bound. It records no
new low-memory kill. Existing preparation memory controls remain active.

Install over the existing stock app. Keep the completed import and app data,
select the same locale, and retry Prepare local runtime / world. Do not reimport,
uninstall or clear data. Completed compatible phases remain reusable; the new
extractor identity requires affected data phases to run again. Export support
before another retry after any failure. Actual Thor world preparation and
gameplay remain unqualified until the device retry.
'''
    if signed['versionCode'] == 8:
        notes += '''
Version 8 fixes map/DBC output creation when the private staging path is long.
The extractor's legacy 128-byte output buffer truncated the absolute path and
reported a directory permissions error. The adapter now uses a short relative
output path inside the same verified private phase working directory.

The existing v7 ordered readers and their source/debug-qualified runtime remain
unchanged. File selection bounds, provider order, source pins and preparation
memory controls remain active. The v7 report records no new low-memory kill.

Install over the existing stock app. Keep the completed client import, app data,
databases and saves, then retry Prepare local runtime / world with the same
locale. Do not reimport, uninstall or clear storage. Completed compatible phases
are reused; changed helper identities require affected data phases to run again.
Export support before another retry after failure. Actual Thor world preparation
and gameplay remain unqualified until the device retry.
'''
    if signed['versionCode'] == 9:
        notes += '''
Version 9 adds selectable preparation verification speeds: Gentle 8 MiB/s,
Balanced 32 MiB/s (default) and Fast 64 MiB/s. Choose a level while idle; changing
it does not require a client reimport. Import copying retains its 8 MiB/s policy.
Pressure still slows reads to 2 MiB/s or pauses them. Native conversion remains
one worker with the existing memory guard; these rates are not total-world ETAs.

Compatible completed phases and valid partial navigation-mesh tiles can be reused
on retry, including strictly checked v8 staging. Abandoned duplicate phase copies
are reclaimed after migration. Idle storage maintenance reports and removes only
recognized obsolete runtime generations and redundant archive caches, preserving
the current runtime, imported client, usable world work, databases and saves.

Transient Android trim signals with verified healthy headroom back off rather
than immediately discarding a long native phase. Actual low-memory conditions
retain the safe pause behavior. Native clean-cache advice is bounded and cycled
instead of repeatedly advising every complete archive in each short interval.

Install over the existing stock app and keep all app data. Select the same locale,
start with Balanced, and retry Prepare local runtime / world. If comparing speeds,
Stop and wait for cleanup before changing the setting. Export the support bundle
before another attempt after a failure. Full Thor preparation, rendering and
local/offline gameplay still need device confirmation.
'''
    if signed['versionCode'] == 10:
        notes += '''
Version 10 corrects the data-format preflight reached after navigation-mesh
preparation in the v9 report. Matching completed v9 extraction/navigation work
is retained and revalidated for reuse, so the preflight retry does not require
a new client import or deliberately discard completed world output. Malformed
or incompatible data still fails validation; no essential format check is skipped.

Preparation controls are unchanged: Gentle 8 MiB/s, Balanced 32 MiB/s (default)
and Fast 64 MiB/s govern Java/Python verification and copying. Native conversion
remains one worker with the existing memory guard. Memory-pressure backoff/pause,
bounded cache advice, safe idle storage trim and resumable phases remain active.
These I/O levels are not total-world completion estimates.

Install over the existing stock app, retain the completed import, generated world
work, databases and saves, select the same locale and retry Prepare local runtime
/ world. Keep the chosen speed unless comparing it deliberately while idle.
Do not reimport, uninstall, clear storage or delete completed navigation files.
Export support before another attempt after a failure. Actual Thor preparation,
rendering, persistence and offline gameplay still need device confirmation.
'''
    if signed['versionCode'] == 11:
        notes += '''
Version 11 addresses the completed-world-data handoff reached after v10 finished
its format checks. The v10 report records successful world-data preparation,
followed by the Android receipt inspector rejecting the completed selection.
Matching completed v10 world data is retained and checked before reuse; no new
client import or deliberate deletion of navigation output is required.

Preparation speeds and memory controls are unchanged. Keep the completed import,
generated data, databases and saves. Install over the existing stock app, select
the same locale and retry Prepare local runtime / world. Hash verification still
takes time. Native extraction remains necessary for missing or incompatible data.
Do not uninstall, clear storage, reimport or delete completed world files.

Export support before another attempt after a failure. Actual Thor completion,
rendering, persistence and offline gameplay still need device confirmation.
'''
    if signed['versionCode'] == 12:
        notes += '''
Version 12 separates normal startup from preparation. Start local game selects
source-bound existing runtime, world data and shader generations, with explicit
repair guidance for missing or invalid components. It does not rerun extraction,
download runtime packages or recopy a valid imported client on that startup path.
Full payload verification remains required; the prepared-data fast cache is
still disabled. Reuse must not be read as a claim that all hashing is eliminated.

Server admission and native auth/world startup now have separate bounded clocks,
with the failing phase, process, readiness condition and elapsed time retained in
support diagnostics. Admission verification observes the selected preparation
speed and cancellation. A full verification that exceeds its admission budget
still reports a failure; this update does not establish faster Thor loading.

The v11 receipt compatibility fix, all generation-bound preparation helper bytes,
client/server pins, native providers and stock SQL selection are unchanged.
Compatible completed v10/v11 data remains eligible for checked reuse. Missing or
incompatible components still need preparation; existing databases are not reset.

This candidate is not Thor gameplay-qualified. A genuine graphical client frame,
normal local login, Human Warrior world entry, saving and three cold offline
relaunches still require execution with the owner's retained client and device.
Host fixtures, component tests and a successful package build do not prove those
stages. Custom content and MPQ authoring remain deferred until stock acceptance.
'''
    if signed['versionCode'] == 13:
        notes += '''
V12 accepted the retained Thor world generation and reached shader translation.
Both initial setup and named shader repair stopped in the reader for Data/patch.MPQ
with “MPQ delete markers are unsupported”. V13 handles MPQ deletion markers
during shader selection. The completed world generation remains selectable.

Confirmation on the imported Thor MPQs, a graphical login frame, world entry,
saving and offline relaunches still require device execution.
'''
    if signed['versionCode'] == 14:
        notes += '''
The v13 Thor run reused the prepared world and then refused ten legacy terrain
pixel shaders, including Terrain1w:0. The stock Vulkan client selects all 32
Terrain1 ps_3_0 permutations. V14 verifies this selection and checks the winning
effects for legacy terrain references before excluding the five exact PS1-only
containers. Other unsupported shader records still fail strict preparation.

Named shader repair keeps the selected import, completed world generation,
configuration and saves. Full shader preparation on the retained Thor import,
graphical login, world entry and saved-character relaunch require device verification.
'''
    if signed['versionCode'] == 17:
        notes += '''
On offline Android ARM64, the original first launch of the reconstructed client
spent about five minutes waiting for Wine's optional Mono installer. The native
stock client and codec have no managed-code dependency. Disabling that installer
reduced the first authenticated client run from 311.7 to 30.8 seconds in a
disposable database test. This measures the client's authentication diagnostic.

V17 uses this Wine setting for ordinary stock client launches. Client runtime
repair can also finish the recognized interrupted Wine installation in place.
The APK uses the same client, Wine package, shaders, world-data recipe and SQL
profile as v16. Physical Thor shader completion and gameplay remain open.
'''
    if signed['versionCode'] == 19:
        notes += '''
The reconstructed client now completes short positional reads of stock MPQs.
On a full 3.3.5a import under ARM64 Wine, a successful read returned 507,904
of 1,048,576 requested bytes. The previous executable treated the archive as
empty, lost the front-end particle effects and crashed when drawing them.
The corrected read stops at the first true EOF or I/O error.

The APK pairs the new executable with the existing prepared-data revision.
Completed import, shader and world generations keep their original identities.
The signed update uses the existing database and stock SQL profile.
'''
    if signed['versionCode'] == 20:
        notes += '''
After an interrupted world load, the next session checks the owned stock realm
before starting authserver. If that realm still has the interrupted startup
flags, it restores its offline status. The real worldserver handles its normal
transition to online. The client, server binaries, prepared assets and stock SQL
profile match v19.
'''
    (args.output / 'RELEASE-NOTES.md').write_text(notes)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('signed', 'cohort-proof', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--app-revision', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(stage(args), sort_keys=True))


if __name__ == '__main__':
    main()
