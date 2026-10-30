#!/usr/bin/env python3
"""Run only fixed diagnostics in an owned, fresh Android x64 Wine fixture.

The source-pinned client validators accompany this script. No game initialization,
display, audio, account, server, content download or desktop shell is requested.
"""
import argparse
import ctypes
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


def mapping_diagnostics(work):
    """Measure ordinary mapping permissions without executing mapped bytes.

    This is an emulator fixture, not a workaround or a qualification. In
    particular an allowed anonymous mapping cannot explain a rejected PE map.
    """
    page = os.sysconf('SC_PAGE_SIZE')
    require(4096 <= page <= 65536, 'unexpected-mapping-page-size')
    path = work / 'mapping-diagnostic.bin'
    payload = bytes((index * 17 + 23) % 256 for index in range(page))
    libc = ctypes.CDLL(None, use_errno=True)
    libc.mmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long)
    libc.mmap.restype = ctypes.c_void_p
    libc.mprotect.argtypes = (ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int)
    libc.mprotect.restype = ctypes.c_int
    libc.munmap.argtypes = (ctypes.c_void_p, ctypes.c_size_t)
    libc.munmap.restype = ctypes.c_int
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    cases = (('anonymous-dirty-rw-to-rx', -1, 0x22, 3, 5, True),
             ('file-direct-rx', descriptor, 2, 5, None, False),
             ('file-direct-rwx', descriptor, 2, 7, None, False),
             ('file-clean-rw-to-rx', descriptor, 2, 3, 5, False),
             ('file-dirty-rw-to-rx', descriptor, 2, 3, 5, True))
    results = []
    try:
        with os.fdopen(os.dup(descriptor), 'wb') as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        require(os.fstat(descriptor).st_size == page and os.pread(descriptor, page, 0) == payload,
                'mapping-fixture-write-readback')
        for name, fd, flags, initial, final, dirty in cases:
            ctypes.set_errno(0)
            address = libc.mmap(None, page, initial, flags, fd, 0)
            row = dict(case=name, initialProtection=initial, finalProtection=final,
                       mmapSucceeded=address != ctypes.c_void_p(-1).value,
                       mmapErrno=ctypes.get_errno() if address == ctypes.c_void_p(-1).value else 0,
                       mprotectSucceeded=None, mprotectErrno=None, modified=False)
            if address != ctypes.c_void_p(-1).value:
                require(address is not None, 'mapping-unexpected-zero-address')
                try:
                    if dirty:
                        ctypes.memmove(address, b'fixed-fixture-bytes', 19)
                        row['modified'] = True
                    if final is not None:
                        ctypes.set_errno(0)
                        result = libc.mprotect(address, page, final)
                        row['mprotectSucceeded'] = result == 0
                        row['mprotectErrno'] = ctypes.get_errno() if result else 0
                finally:
                    require(libc.munmap(address, page) == 0, 'mapping-fixture-unmap-failed')
            results.append(row)
        require(os.pread(descriptor, page, 0) == payload, 'private-mapping-modified-backing-file')
    finally:
        os.close(descriptor)
    report = dict(formatVersion=1, scope='mapping-permission-diagnostic-only', pageBytes=page,
                  fixtureSha256=hashlib.sha256(payload).hexdigest(), privateFileUnchanged=True,
                  mappedBytesExecuted=False, wineQualified=False, cases=results)
    print('ESTERIA_WINE_MAPPING_DIAGNOSTIC ' + json.dumps(report, sort_keys=True), file=sys.stderr, flush=True)
    return report


def require(value, message):
    if not value:
        raise ValueError(message)


def environment():
    # No host proxy, online update channel or arbitrary command is inherited.
    return dict(HOME='/work/home', PATH='/opt/wine/bin:/usr/bin:/bin', LANG='C.UTF-8',
                TMPDIR='/tmp', WINEPREFIX=str(PREFIX), WINEARCH='win64', WINEDEBUG='-all,err+all',
                WINEESYNC='0', WINEFSYNC='0', WINE_ANDROID_PRIVATE_PE_COPY='1',
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
            mapping_diagnostics(WORK)
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
