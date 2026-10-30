#!/usr/bin/env python3
"""Qualify exact ARM64 input-helper events in a disposable pinned X11 namespace."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import time

try:
    from . import prepare_runtime as packages
    from .qualify_wine_arm64 import Capture, GUEST, guest_command, namespace_command, read_json, run_logged
except ImportError:
    import prepare_runtime as packages
    from qualify_wine_arm64 import Capture, GUEST, guest_command, namespace_command, read_json, run_logged

ROOT = Path(__file__).resolve().parents[1]
SCOPE = 'native-linux-arm64-x11-input-fixture'
HELPER = 'esteria-x11-input'
OBSERVER = 'esteria-x11-input-observer'
CHECKS = ('absoluteMotion', 'relativeMotion', 'buttons', 'keyboardAndShift', 'releaseOnEof',
          'unsupportedKeyRejected', 'reconnectNeutral')
UNQUALIFIED = ('androidQualified', 'controllerQualified', 'gameplayQualified')
DISPLAY = 64
READY = b'ESTERIA_X11_INPUT_READY protocol=1'
FORMATTER_SOURCES = ('core/src/main/java/io/github/russianranger/esteria/core/presentation/X11SessionPlan.java',
                     'tests/fixtures/X11AuthorityFixture.java')


def authority_cookie(path):
    """Check one bounded actual formatter record; cookie bytes are never evidence."""
    with packages.plain_file(path) as stream:
        info = os.fstat(stream.fileno())
        packages.require(info.st_mode & 0o777 == 0o600 and info.st_size <= 256, 'authority-not-private-or-bounded')
        data = stream.read(257)
    packages.require(len(data) >= 2 and data[:2] == b'\xff\xff', 'authority-family')
    fields = []; offset = 2
    for _ in range(4):
        packages.require(offset + 2 <= len(data), 'authority-truncated-length')
        length = struct.unpack_from('!H', data, offset)[0]; offset += 2
        packages.require(offset + length <= len(data), 'authority-truncated-field')
        fields.append(data[offset:offset + length]); offset += length
    packages.require(offset == len(data) and fields[:3] == [b'', str(DISPLAY).encode(), b'MIT-MAGIC-COOKIE-1']
                     and len(fields[3]) == 16, 'authority-record-contract')
    return fields[3]


def server_command(path):
    with packages.plain_file(path) as stream:
        data = stream.read(4097)
    packages.require(len(data) <= 4096, 'formatter-command-too-large')
    command = data.decode('ascii').splitlines()
    packages.require(command == ['/usr/bin/Xtigervnc', ':' + str(DISPLAY), '-geometry', '1280x720', '-depth', '24',
                     '-nolisten', 'tcp', '-rfbport', '-1', '-auth', '/session/Xauthority', '-noreset'],
                     'application-x11-command-contract-changed')
    return command


def prepare_authority(root, fixture, output):
    # The measured archive already carries an empty /session mountpoint. Keep
    # it intact; the worker binds this fresh fixture there in its own namespace.
    target = packages.directory(root / 'session', create=True)
    packages.require(not any(target.iterdir()), 'x11-session-mountpoint-not-empty')
    session = fixture / 'auth-session'
    packages.require(not os.path.lexists(session), 'fresh-authentication-session-required')
    session.mkdir(mode=0o700)
    classes = fixture / 'formatter-classes'; classes.mkdir(mode=0o700)
    sources = {name: identity(ROOT / name) for name in FORMATTER_SOURCES}
    executables = {name: Path(shutil.which(name) or '/missing-java-tool').resolve() for name in ('javac', 'java')}
    tools = {name: identity(path) for name, path in executables.items()}
    captures = []
    clean = ['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'LANG=C.UTF-8', 'HOME=' + str(fixture)]
    try:
        compile_result = run_logged([*clean, str(executables['javac']), '--release', '17', '-d', str(classes),
                                    *[str(ROOT / name) for name in FORMATTER_SOURCES]],
                                   output / 'formatter-compile.log', 30, captures)
        packages.require(compile_result.exit_code == 0, 'application-formatter-compilation-failed')
        run = run_logged([*clean, str(executables['java']), '-cp', str(classes), 'X11AuthorityFixture',
                          str(session), str(fixture / 'server-argv.txt'), str(DISPLAY)],
                         output / 'formatter-run.log', 15, captures, needle=b'ESTERIA_X11_AUTHORITY_FORMATTED')
        packages.require(run.exit_code == 0 and run.finish(5) and run.matched.is_set(), 'application-formatter-failed')
        packages.require(authority_cookie(session / 'Xauthority') != authority_cookie(session / 'Xauthority-wrong'),
                         'negative-cookie-not-distinct')
        server_command(fixture / 'server-argv.txt')
        packages.require(sources == {name: identity(ROOT / name) for name in FORMATTER_SOURCES}, 'formatter-source-changed')
        return dict(actualApplicationFormatterExecuted=True, sources=sources, hostJavaExecutables=tools,
                    display=DISPLAY, privateCookiesExported=False)
    finally:
        deadline = time.monotonic() + 5
        packages.require(all([capture.finish(deadline - time.monotonic()) for capture in captures]) and
                         all(not capture.truncated and capture.error is None for capture in captures),
                         'formatter-capture-failed')


def x11_command(root, authority, *command):
    return guest_command(root, '/usr/bin/env', 'DISPLAY=:' + str(DISPLAY), 'XAUTHORITY=' + authority, *command)


def rejected_helper(command, endpoint, log, captures):
    packages.require(not os.path.lexists(endpoint), 'negative-input-endpoint-already-exists')
    capture = Capture(command, log, needle=READY); captures.append(capture)
    deadline = time.monotonic() + 10; listener = False
    try:
        while capture.process.poll() is None and time.monotonic() < deadline:
            listener |= os.path.lexists(endpoint)
            time.sleep(.01)
        if capture.process.poll() is None:
            raise ValueError('unauthenticated-helper-did-not-reject')
        listener |= os.path.lexists(endpoint)
        drained = capture.finish(5)
        result = dict(exitCode=capture.process.returncode, listenerCreated=listener,
                      readyMarker=capture.matched.is_set(), logDrained=drained)
        packages.require(rejection_passed(result) and not capture.truncated and capture.error is None,
                         'unauthenticated-helper-not-rejected-before-listener')
        return result
    finally:
        if capture.process.poll() is None:
            capture.process.kill(); capture.process.wait(timeout=5)


def rejection_passed(value):
    return (type(value) is dict and type(value.get('exitCode')) is int and value['exitCode'] == 3 and
            value.get('listenerCreated') is False and value.get('readyMarker') is False and value.get('logDrained') is True)


def identity(path):
    with packages.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        return dict(bytes=size, sha256=packages.hash_stream(stream, size))


def fixture_receipt(value):
    expected = dict(formatVersion=1, scope=SCOPE, groupsPassed=7, observedEvents=16, acknowledgments=15,
                    **{key: True for key in CHECKS}, **{key: False for key in UNQUALIFIED})
    packages.require(type(value) is dict and set(value) == set(expected) and
                     all(type(value[key]) is type(item) and value[key] == item for key, item in expected.items()),
                     'x11-observer-receipt-incomplete-or-overclaims')
    return value


def build_identity(payload, revision, package, bridge_input_lock=None):
    packages.require(re.fullmatch('[0-9a-f]{40}', revision or '') is not None, 'full-bridge-revision-required')
    payload = packages.directory(payload)
    receipt, receipt_sha = read_json(payload / 'bridge-build.json')
    packages.require(receipt.get('formatVersion') == 1 and receipt.get('compiled') is True and
                     receipt.get('scope') == 'linux-arm64-guest-bridge-build-only' and
                     receipt.get('integrationRevision') == revision and
                     receipt.get('runtimeArchiveSha256') == package['archive']['sha256'], 'bridge-build-identity')
    source_paths = list((ROOT / 'native/guest-bridges').glob('*')) + [ROOT / 'native/presentation' / name
                   for name in ('frame_protocol.h', 'frame_transport.h')]
    expected = {str(path.relative_to(ROOT / 'native')): identity(path) for path in source_paths if not path.is_dir()}
    packages.require(receipt.get('sources') == expected, 'bridge-source-identity')
    input_lock, input_sha = read_json(bridge_input_lock if bridge_input_lock is not None else
                                      ROOT / 'runtime/bridges/sources.lock.json')
    packages.require(receipt.get('inputLockSha256') == input_sha, 'bridge-build-input-lock')
    packages.require(type(input_lock) is dict and type(input_lock.get('formatVersion')) is int and
                     input_lock['formatVersion'] == 1 and input_lock.get('scope') == 'guest-bridge-build-inputs-only' and
                     input_lock.get('architecture') == 'arm64' and
                     input_lock.get('runtimeArchiveSha256') == package['archive']['sha256'],
                     'bridge-input-runtime-pin-mismatch')
    spec = importlib.util.spec_from_file_location('esteria_x11_build', ROOT / 'runtime/bridges/record_build.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    with packages.plain_file(payload / 'bin' / HELPER):
        helper = module.elf(payload / 'bin' / HELPER)
    packages.require(helper == receipt.get('binaries', {}).get(HELPER), 'production-helper-binary-identity')
    test, test_sha = read_json(payload / 'x11-test/observer-build.json')
    packages.require(test.get('formatVersion') == 1 and test.get('scope') == 'linux-arm64-x11-observer-build-only' and
                     test.get('integrationRevision') == revision and test.get('inputLockSha256') == input_sha and
                     test.get('bridgeReceipt') == identity(payload / 'bridge-build.json') and
                     test.get('source') == identity(ROOT / 'native/guest-tests/x11_input_observer.c') and
                     all(test.get(key) is False for key in ('executionQualified', 'androidQualified', 'gameplayQualified')),
                     'observer-build-provenance')
    with packages.plain_file(payload / 'x11-test' / OBSERVER):
        observer = module.elf(payload / 'x11-test' / OBSERVER)
    packages.require(observer == test.get('binary'), 'observer-binary-identity')
    return dict(integrationRevision=revision, bridgeReceiptSha256=receipt_sha, observerReceiptSha256=test_sha,
                inputLockSha256=input_sha, helper=helper, observer=observer)


def validate_runtime(runtime, runtime_lock=None, x11_runtime_lock=None):
    lock, lock_sha = read_json(runtime_lock if runtime_lock is not None else packages.DEFAULT_LOCK)
    packages.require(type(lock) is dict and type(lock.get('formatVersion')) is int and lock['formatVersion'] == 1,
                     'unsupported-runtime-lock-version')
    package = lock['packages']['wine-arm64']
    prepared, prepared_sha = read_json(runtime / 'package-receipt.json')
    pin_sha = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    packages.require(prepared.get('archiveSha256') == package['archive']['sha256'] and
                     prepared.get('manifestSha256') == package['manifest']['sha256'] and
                     prepared.get('packagePinSha256') == pin_sha and
                     prepared.get('preparerSha256') == identity(Path(packages.__file__))['sha256'] and
                     prepared.get('archiveExtracted') is True and prepared.get('stagedFilesReadBack') is True,
                     'fresh-runtime-preparation-required')
    x11, x11_sha = read_json(x11_runtime_lock if x11_runtime_lock is not None else
                           ROOT / 'runtime/bridges/x11-runtime.lock.json')
    packages.require(type(x11) is dict and type(x11.get('formatVersion')) is int and x11['formatVersion'] == 1 and
                     x11.get('scope') == 'pinned-wine-rootfs-x11-static-library-closure' and
                     x11.get('androidQualified') is False and x11.get('inputQualified') is False,
                     'x11-runtime-lock-scope')
    packages.require(x11.get('runtimeArchiveSha256') == package['archive']['sha256'], 'x11-runtime-pin-mismatch')
    for name, expected in {**x11['components'], **x11['loaderConfiguration']}.items():
        packages.member_path(name)
        with packages.plain_file(runtime / 'rootfs' / name) as stream:
            packages.verify_stream(stream, dict(file=Path(name).name, **expected))
            stream.seek(0); packages.inspect_component(stream.read(4096), expected)
    for name, target in x11['symlinks'].items():
        packages.member_path(name)
        packages.require(os.readlink(runtime / 'rootfs' / name) == target, 'x11-loader-library-alias-mismatch')
    packages.require(x11.get('preloadFileAbsent') is True and not os.path.lexists(runtime / 'rootfs/etc/ld.so.preload'),
                     'x11-unexpected-global-preload')
    return package, dict(runtimeArchiveSha256=package['archive']['sha256'], runtimeLockSha256=lock_sha,
                         runtimeReceiptSha256=prepared_sha,
                         x11RuntimeLockSha256=x11_sha, x11ElfImagesVerified=len(x11['components']))


def passed(result, namespace_exit):
    return (type(namespace_exit) is int and namespace_exit == 0 and type(result.get('expectedExit')) is int and
            result['expectedExit'] == 0 and
            result.get('workerCompleted') is True and result.get('networkIsolated') is True and
            result.get('displayReady') is True and result.get('helperReady') is True and
            result.get('authenticatedServerCommand') is True and result.get('positiveHelperReadyMarker') is True and
            rejection_passed(result.get('missingCookie')) and rejection_passed(result.get('wrongCookie')) and
            type(result.get('observerExit')) is int and result['observerExit'] == 0 and result.get('receiptValidated') is True and
            type(result.get('helperExit')) is int and result['helperExit'] == 0 and result.get('helperForced') is False and
            result.get('socketRemoved') is True and result.get('displayStopped') is True and
            result.get('logStreamsDrained') is True and result.get('logsWithinLimit') is True and
            result.get('logWritesSucceeded') is True)


def worker(runtime, output):
    packages.require(os.getpid() == 1 and os.geteuid() == 0 and os.environ.get('ESTERIA_NAMESPACE_CHILD') == '1',
                     'owned-pid-and-network-namespace-required')
    root = runtime / 'rootfs'; fixture = root / GUEST.lstrip('/')
    result = dict(workerCompleted=False, expectedExit=1, networkIsolated=False, displayReady=False,
                  helperReady=False, observerExit=None, receiptValidated=False)
    captures = []; display = None; helper = None; code = 1
    try:
        for source in ('/dev', '/proc', '/sys'):
            target = packages.directory(root / source.lstrip('/'), create=True)
            subprocess.run(['mount', '--bind', source, str(target)], check=True, timeout=15)
            if source == '/sys': subprocess.run(['mount', '-o', 'remount,bind,ro', str(target)], check=True, timeout=15)
        subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True, timeout=15)
        interfaces = json.loads(subprocess.check_output(['ip', '-j', 'link', 'show'], timeout=15))
        packages.require({item['ifname'] for item in interfaces} == {'lo'}, 'unexpected-network-interface')
        result['networkIsolated'] = True
        target = packages.directory(root / 'session')
        packages.require(not any(target.iterdir()), 'x11-session-mountpoint-not-empty')
        session = packages.directory(fixture / 'auth-session')
        subprocess.run(['mount', '--bind', str(session), str(target)], check=True, timeout=15)
        packages.require(authority_cookie(root / 'session/Xauthority') != authority_cookie(root / 'session/Xauthority-wrong'),
                         'negative-cookie-not-distinct')
        packages.require(not os.path.lexists(root / 'session/Xauthority-missing'), 'missing-cookie-file-present')
        display_capture = Capture(guest_command(root, *server_command(fixture / 'server-argv.txt')), output / 'display.log')
        result['authenticatedServerCommand'] = True
        captures.append(display_capture); display = display_capture.process
        endpoint = root / ('tmp/.X11-unix/X' + str(DISPLAY))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and display.poll() is None:
            if endpoint.exists() and stat.S_ISSOCK(endpoint.lstat().st_mode): result['displayReady'] = True; break
            time.sleep(.05)
        packages.require(result['displayReady'], 'x11-display-not-ready')
        for label, filename in (('missingCookie', 'Xauthority-missing'), ('wrongCookie', 'Xauthority-wrong')):
            socket_name = label + '.sock'
            result[label] = rejected_helper(x11_command(root, '/session/' + filename,
                GUEST + '/' + HELPER, GUEST + '/' + socket_name), fixture / socket_name,
                output / (label + '.log'), captures)
            packages.require(display.poll() is None, 'display-exited-during-authentication-check')
        helper_capture = Capture(x11_command(root, '/session/Xauthority', GUEST + '/' + HELPER, GUEST + '/input.sock'),
                                 output / 'input-helper.log', needle=READY)
        captures.append(helper_capture); helper = helper_capture.process
        endpoint = fixture / 'input.sock'; deadline = time.monotonic() + 10
        while time.monotonic() < deadline and helper.poll() is None:
            if endpoint.exists():
                mode = endpoint.lstat().st_mode
                packages.require(stat.S_ISSOCK(mode) and mode & 0o077 == 0, 'input-endpoint-not-private')
                if helper_capture.matched.is_set(): result['helperReady'] = True; break
            time.sleep(.05)
        packages.require(result['helperReady'], 'production-input-helper-not-ready')
        result['positiveHelperReadyMarker'] = helper_capture.matched.is_set()
        receipt_path = fixture / 'x11-input-receipt.json'
        packages.require(not os.path.lexists(receipt_path), 'observer-receipt-already-exists')
        observed = run_logged(x11_command(root, '/session/Xauthority', GUEST + '/' + OBSERVER, GUEST + '/input.sock',
                              GUEST + '/x11-input-receipt.json'), output / 'observer.log', 60, captures)
        result['observerExit'] = observed.exit_code
        packages.require(observed.exit_code == 0, 'actual-x11-observer-failed')
        packages.require(receipt_path.stat().st_size <= 4096, 'observer-receipt-size-limit')
        value, digest = read_json(receipt_path)
        result['observerReceipt'] = fixture_receipt(value); result['observerReceiptSha256'] = digest
        result['receiptValidated'] = True
        packages.write_json(output / 'observer-receipt.json', value)
        code = 0
    except Exception as error:
        result['failure'] = str(error)
    finally:
        for name, process in (('helper', helper), ('display', display)):
            try:
                if process is None: continue
                forced = False
                if process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        forced = True; process.kill(); process.wait(timeout=5)
                result[name + 'Exit'] = process.returncode
                result[name + 'Forced'] = forced
                if name == 'display': result['displayStopped'] = process.poll() is not None and not forced
            except Exception as error:
                result[name + 'CleanupFailure'] = str(error); code = 1
        result['socketRemoved'] = not os.path.lexists(fixture / 'input.sock')
        deadline = time.monotonic() + 5
        result['logStreamsDrained'] = all([capture.finish(deadline - time.monotonic()) for capture in captures])
        result['logsWithinLimit'] = all(not capture.truncated for capture in captures)
        result['logWritesSucceeded'] = all(capture.error is None for capture in captures)
        result['workerCompleted'] = True; result['expectedExit'] = code
        if not passed(result, code): code = 1; result['expectedExit'] = 1
        packages.write_json(output / 'worker-result.json', result)
    return code


def qualify(runtime, payload, revision, output, runtime_lock=None, x11_runtime_lock=None, bridge_input_lock=None):
    packages.require(platform.machine().lower() in ('aarch64', 'arm64') and os.geteuid() == 0,
                     'native-arm64-root-host-required')
    runtime = packages.directory(runtime); payload = packages.directory(payload)
    package, runtime_identity = validate_runtime(runtime, runtime_lock, x11_runtime_lock)
    binaries = build_identity(payload, revision, package, bridge_input_lock)
    packages.directory(output.parent, create=True); output.mkdir(mode=0o700)
    fixture = runtime / 'rootfs' / GUEST.lstrip('/')
    packages.require(not os.path.lexists(fixture), 'runtime-already-used-for-qualification')
    fixture.mkdir(mode=0o700)
    for source, name, expected in ((payload / 'bin' / HELPER, HELPER, binaries['helper']),
                                  (payload / 'x11-test' / OBSERVER, OBSERVER, binaries['observer'])):
        with packages.plain_file(source) as src, (fixture / name).open('xb') as dst:
            packages.require(packages.hash_stream(src, expected['bytes'], dst) == expected['sha256'], 'binary-changed-during-copy')
            dst.flush(); os.fsync(dst.fileno())
        (fixture / name).chmod(0o755)
    report = dict(formatVersion=1, scope=SCOPE, **runtime_identity, binaries=binaries,
                  linuxArm64X11InputQualified=False, processNamespaceExited=False, wineClientExecuted=False,
                  linuxArm64AuthenticatedX11InputQualified=False,
                  **{key: False for key in UNQUALIFIED})
    child = None; capture = None
    try:
        report['authentication'] = prepare_authority(runtime / 'rootfs', fixture, output)
        # env execs unshare; --kill-child binds its PID-namespace init's lifetime
        # to this owned process, including when the outer timeout kills it.
        command = ['/usr/bin/env', '-i', 'PATH=/usr/sbin:/usr/bin:/sbin:/bin', 'LANG=C.UTF-8',
                   'ESTERIA_NAMESPACE_CHILD=1', *namespace_command(Path(__file__).resolve(), runtime, output, True)]
        capture = Capture(command, output / 'namespace.log')
        child = capture.process
        try: code = child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            child.kill(); child.wait(timeout=15); raise ValueError('x11-namespace-timeout')
        result, _ = read_json(output / 'worker-result.json')
        report.update(namespaceExit=code, processNamespaceExited=True, worker=result)
        report['linuxArm64X11InputQualified'] = (passed(result, code) and capture.finish(5) and
                                                not capture.truncated and capture.error is None)
        report['linuxArm64AuthenticatedX11InputQualified'] = report['linuxArm64X11InputQualified']
        packages.require(report['linuxArm64X11InputQualified'], 'actual-x11-input-not-qualified')
        return report
    except Exception as error:
        report['failure'] = str(error); raise
    finally:
        if child is not None and child.poll() is None: child.kill(); child.wait(timeout=15)
        if child is not None and child.poll() is not None: report['processNamespaceExited'] = True
        if capture is not None and (not capture.finish(5) or capture.truncated or capture.error is not None):
            report['linuxArm64X11InputQualified'] = False
            report['linuxArm64AuthenticatedX11InputQualified'] = False
            report['namespaceCaptureFailed'] = True
        packages.write_json(output / 'qualification.json', report)
        if os.environ.get('SUDO_UID', '').isdigit() and os.environ.get('SUDO_GID', '').isdigit():
            uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
            for path in output.iterdir():
                packages.require(stat.S_ISREG(path.lstat().st_mode), 'unexpected-evidence-file-type')
                os.chown(path, uid, gid, follow_symlinks=False)
            os.chown(output, uid, gid, follow_symlinks=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--bridge-dir', type=Path)
    parser.add_argument('--bridge-revision')
    parser.add_argument('--runtime-lock', type=Path, help='separate exact runtime input lock; default production pins')
    parser.add_argument('--x11-runtime-lock', type=Path, help='exact X11/loader closure bound to the selected runtime')
    parser.add_argument('--bridge-input-lock', type=Path, help='exact build-input lock for the rebuilt guest bridges')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--namespace-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.namespace_worker: return worker(args.runtime, args.output)
    packages.require(args.bridge_dir is not None, 'source-built-bridge-payload-required')
    qualify(args.runtime.absolute(), args.bridge_dir.absolute(), args.bridge_revision, args.output.absolute(),
            args.runtime_lock, args.x11_runtime_lock, args.bridge_input_lock)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
