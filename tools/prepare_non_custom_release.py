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
    args.output.mkdir(parents=True)
    name = 'Esteria-Stock-3.3.5a-arm64.apk'
    shutil.copyfile(apk, args.output / name)
    (args.output / 'release.json').write_text(json.dumps(result, sort_keys=True, indent=2) + '\n')
    (args.output / 'SHA256SUMS').write_text(signed['apkSha256'] + '  ' + name + '\n')
    setup = ('Keep the completed client import and retry Prepare local runtime / world, then\n'
             'start the local game. Follow the attached NON-CUSTOM-TESTING.md procedure, including\n'
             'the offline repeat and support bundle export if a stage fails.' if signed['versionCode'] in (5, 6, 7, 8) else
             'Import your complete ChromieCraft client, prepare the local runtime/world, then\n'
             'start the local game. Follow the attached NON-CUSTOM-TESTING.md procedure, including\n'
             'the offline repeat and support bundle export if a stage fails.')
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
