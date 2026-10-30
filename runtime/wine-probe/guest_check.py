#!/usr/bin/env python3
"""Run only fixed diagnostics in an owned, fresh Android x64 Wine fixture.

The source-pinned client validators accompany this script. No game initialization,
display, audio, account, server, content download or desktop shell is requested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

WINE = '/opt/wine/bin/wine'
SERVER = '/opt/wine/bin/wineserver'
WORK = Path('/work')
CLIENT = WORK / 'client'
PREFIX = WORK / 'prefix'


def require(value, message):
    if not value:
        raise ValueError(message)


def environment():
    # No host proxy, online update channel or arbitrary command is inherited.
    return dict(HOME='/work/home', PATH='/opt/wine/bin:/usr/bin:/bin', LANG='C.UTF-8',
                TMPDIR='/tmp', WINEPREFIX=str(PREFIX), WINEARCH='win64', WINEDEBUG='-all,err+all',
                WINEESYNC='0', WINEFSYNC='0',
                WINEDLLOVERRIDES='winemenubuilder.exe=d;mscoree,mshtml=')


def command(words, seconds):
    result = subprocess.run(words, cwd=CLIENT, env=environment(), timeout=seconds, check=False)
    require(result.returncode == 0, 'fixed-wine-command-exit:' + str(result.returncode))


def run(phase):
    require(WORK.is_dir() and CLIENT.is_dir() and (WORK / '.wine-probe-owner').is_file(), 'missing-owned-fixture')
    require(not PREFIX.is_symlink(), 'prefix-is-symlink')
    receipt = WORK / 'results' / (phase + '.json')
    require(not receipt.exists(), 'existing-phase-receipt')
    success = False
    try:
        if phase == 'prefix':
            require(not PREFIX.exists(), 'prefix-is-not-fresh')
            command([WINE, 'wineboot.exe', '-u'], 180)
            command([SERVER, '-w'], 60)
            require((PREFIX / 'system.reg').is_file() and (PREFIX / 'drive_c/windows/system32/ntdll.dll').is_file(),
                    'prefix-not-created')
            result = dict(formatVersion=1, scope='wine-prefix-initialized-only', prefixInitialized=True,
                          reconstructedClientExecuted=False, commonMainStarted=False, gameplayQualified=False)
        else:
            require((PREFIX / 'system.reg').is_file(), 'prefix-not-initialized')
            import verify_client_entry as entry
            import verify_client_offline as offline
            import verify_client_loopback as loopback
            module, arguments = {
                'entry': (entry, [entry.FLAG]),
                'offline': (offline, [offline.FLAG, '--local-offline']),
                'loopback': (loopback, [loopback.FLAG, '--local-offline']),
            }[phase]
            target = CLIENT / module.RECEIPT
            require(not target.exists(), 'existing-client-receipt')
            command([WINE, str(CLIENT / 'WowClient64.exe'), *arguments], 120)
            command([SERVER, '-w'], 60)
            checked, digest = module.read_receipt(target, 'x64')
            result = dict(formatVersion=1, scope='owned-reconstructed-client-diagnostic-only', phase=phase,
                          clientReceipt=checked, clientReceiptSha256=digest, wineserverStoppedNormally=True,
                          commonMainStarted=False, assetsLoaded=False, arm64Qualified=False, gameplayQualified=False)
        with receipt.open('x') as output:
            json.dump(result, output, sort_keys=True)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        success = True
    finally:
        if not success:
            # This exact fresh prefix is the only server selected. PRoot/native
            # ownership still bounds every descendant if these commands fail.
            for words in ([SERVER, '-k'], [SERVER, '-w']):
                try: subprocess.run(words, cwd=CLIENT, env=environment(), timeout=15, check=False)
                except (OSError, subprocess.TimeoutExpired): pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prefix', 'entry', 'offline', 'loopback'), required=True)
    args = parser.parse_args()
    try:
        run(args.phase)
    except Exception as error:
        # This fixture has no account or database credentials; paths remain
        # private. A concise type/errno distinguishes Android filesystem failures.
        print(json.dumps(dict(scope='wine-probe-failure', phase=args.phase, type=type(error).__name__,
                              errno=getattr(error, 'errno', None))), file=sys.stderr)
        raise


if __name__ == '__main__': main()
