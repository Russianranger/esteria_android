#!/usr/bin/env python3
"""Run the reconstructed ARM64 Xvid DLL fixture in a disposable Linux namespace.

Requires a native ARM64 Linux host, unshare/mount/ip/chroot, and root.
No Android, graphics, audio or gameplay qualification is implied.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import signal
import stat
import struct
import subprocess
import sys
import threading
import time

try:
    from . import prepare_runtime as packages
    from . import wine_audio
except ImportError:
    import prepare_runtime as packages
    import wine_audio


GUEST = '/esteria-qualification'
SUCCESS = 'Movie adapter (DLL): BGRA/VFLIP, output bounds, skipped frames and slot lifecycle passed'
ENTRY_SUCCESS = 'PASS: Esteria executable entry/CRT/allocator/exception/fiber roundtrip (entry-check only)'
ENTRY_RECEIPT = 'Esteria-entry-check.json'
OFFLINE_RECEIPT = 'Esteria-local-offline-check.json'
OFFLINE_CHECKS = {'actualCommandParser', 'osUrlRejected', 'blizzardUrlRejected', 'initiationFailureCallbacksPreserved',
                  'trackerReturned', 'hostConnectionRejected', 'numericConnectionRejected', 'invalidPortRejected',
                  'connectFailureCallbacks', 'connectionRefsReleased'}
ENGINE_FRAME_SUCCESS = 'PASS: Engine Vulkan frame BGRA readback, partial clears and embedded-shader presentation'
LOG_LIMIT = 16 * 1024 * 1024
VULKAN_FIXTURES = {
    'presentation': ('presentation_device.exe',
                     'PASS: Vulkan Win32 clear/submit/present completed 16 frames across swapchain resize'),
    'texture': ('texture_device.exe',
                'PASS: Vulkan driver created 20000 simultaneous images; all 30000 create/destroy operations accounted for'),
}


def read_json(path):
    with packages.plain_file(path) as stream:
        data = stream.read(packages.MAX_METADATA + 1)
    packages.require(len(data) <= packages.MAX_METADATA, 'qualification-json-limit')
    return json.loads(data), hashlib.sha256(data).hexdigest()


def read_entry_receipt(path):
    with packages.plain_file(path) as stream:
        data = stream.read(4097)
    packages.require(len(data) <= 4096, 'client-entry-receipt-size-limit')
    result = json.loads(data)
    expected = dict(schemaVersion=1, scope='executable-entry-only', architecture='ARM64',
                    protocolBuild=12340, extensionVersion=4, commonMainStarted=False, assetsLoaded=False)
    checks = {'imageEntryReached', 'crtInitialized', 'stormAllocator', 'cppUnwind', 'mainFiber', 'fiberReturn',
              'fpControlRead'}
    packages.require(type(result) is dict and set(result) == set(expected) | {'checks'}, 'client-entry-receipt-fields')
    packages.require(all(type(result[key]) is type(value) and result[key] == value for key, value in expected.items()),
                     'client-entry-receipt-scope-mismatch')
    packages.require(type(result['checks']) is dict and set(result['checks']) == checks and
                     all(value is True for value in result['checks'].values()), 'client-entry-checks-incomplete')
    return result, hashlib.sha256(data).hexdigest()


def pe_identity(path, dll):
    with packages.plain_file(path) as stream:
        size = os.fstat(stream.fileno()).st_size
        packages.require(64 <= size <= 128 * 1024 * 1024, 'fixture-pe-size-limit')
        head = stream.read(min(4096, size))
        packages.require(head[:2] == b'MZ', 'fixture-not-pe')
        offset = struct.unpack_from('<I', head, 60)[0]
        packages.require(64 <= offset <= len(head) - 26 and head[offset:offset + 4] == b'PE\0\0', 'fixture-pe-header')
        machine = struct.unpack_from('<H', head, offset + 4)[0]
        characteristics = struct.unpack_from('<H', head, offset + 22)[0]
        magic = struct.unpack_from('<H', head, offset + 24)[0]
        packages.require(machine == 0xaa64 and magic == 0x20b and characteristics & 2 and
                         bool(characteristics & 0x2000) == dll, 'fixture-is-not-native-arm64-image')
        stream.seek(0)
        digest = packages.hash_stream(stream, size)
    return {'bytes': size, 'sha256': digest, 'peMachine': '0xaa64', 'dll': dll}


def read_offline_receipt(path):
    with packages.plain_file(path) as stream:data = stream.read(4097)
    packages.require(len(data) <= 4096, 'client-offline-receipt-size-limit')
    result = json.loads(data)
    expected = dict(schemaVersion=1, scope='executable-local-offline-boundaries-only', architecture='ARM64',
                    protocolBuild=12340, remoteAttemptsRejected=3, failureCallbacks=3,
                    commonMainStarted=False, assetsLoaded=False, loopbackGameplayQualified=False)
    packages.require(type(result) is dict and set(result) == set(expected) | {'checks'} and
                     all(type(result[key]) is type(value) and result[key] == value for key, value in expected.items()),
                     'client-offline-receipt-scope-mismatch')
    packages.require(type(result['checks']) is dict and set(result['checks']) == OFFLINE_CHECKS and
                     all(value is True for value in result['checks'].values()), 'client-offline-checks-incomplete')
    return result, hashlib.sha256(data).hexdigest()


def client_inputs(client_dir, driver):
    client_dir = packages.directory(client_dir)
    manifest, digest = read_json(client_dir / 'client-build.json')
    packages.require(manifest.get('schema_version') == 1 and manifest.get('architecture') == 'ARM64' and
                     manifest.get('evidence') == 'build-only' and
                     re.fullmatch('[0-9a-f]{40}', manifest.get('source_revision', '')), 'invalid-arm64-build-manifest')
    packages.require(manifest.get('protocol') == dict(build=12340, container_slots=254, quest_slots=25,
                                                    max_class_id=32), 'client-protocol-mismatch')
    expected = manifest['files']
    packages.require(len(expected) == 2 and {item['name'] for item in expected} ==
                     {'WowClient64.exe', 'XvidDecoder.dll'}, 'client-artifact-members-mismatch')
    files = {}
    for item in expected:
        identity = pe_identity(client_dir / item['name'], item['name'].endswith('.dll'))
        packages.require((identity['bytes'], identity['sha256']) == (item['size'], item['sha256']),
                         'client-artifact-identity-mismatch')
        files[item['name']] = identity
    files['test_xvid_adapter.exe'] = pe_identity(driver, False)
    return manifest, dict(sourceRevision=manifest['source_revision'], buildId=manifest['build_id'],
                          clientManifestSha256=digest, files=files)


def imports_report(manifest, runtime_report):
    modules = runtime_report['windowsArm64Modules']
    local = {item['name'].lower(): item['pe']['machine'] for item in manifest['files']}
    result = {}
    for name in sorted({name.lower() for item in manifest['files'] for name in item['imports']}):
        if name in local:
            result[name] = {'provider': 'client-build', 'peMachine': local[name]}
        elif name in modules:
            result[name] = {'provider': 'wine-file', 'peMachine': modules[name].get('peMachine')}
        else:
            result[name] = {'provider': 'not-a-file', 'apiSetName': name.startswith(('api-', 'ext-')),
                            'resolutionQualified': False}
    return result


def namespace_command(script, runtime, output, privileged):
    packages.require(privileged, 'invoke-qualification-with-sudo')
    return [
        'unshare', '--mount', '--propagation', 'private', '--pid', '--fork',
        '--kill-child=SIGKILL', '--mount-proc', '--net', sys.executable, str(script),
        '--namespace-worker', '--runtime', str(runtime), '--output', str(output)]


def guest_command(root, *command, graphics=None, audio=False):
    environment = []
    if graphics:
        environment = ['VK_ICD_FILENAMES=/' + graphics['icdPath'], 'LIBGL_ALWAYS_SOFTWARE=1']
    overrides = 'winemenubuilder,mshtml,mscoree='
    if audio:
        environment += [f'ALSA_CONFIG_PATH={GUEST}/alsa-qualification.conf', f'ESTERIA_AUDIO_SOCKET={GUEST}/audio.sock']
        overrides += ';winepulse.drv='
    return ['chroot', str(root), '/usr/bin/env', '-i',
            'PATH=/opt/wine/bin:/usr/bin:/bin', 'LANG=C.UTF-8', f'HOME={GUEST}/home',
            f'WINEPREFIX={GUEST}/prefix', 'WINEARCH=win64', 'DISPLAY=:8',
            'WINEDEBUG=-all,err+all', 'WINEDLLOVERRIDES=' + overrides,
            'WINEESYNC=0', 'WINEFSYNC=0', 'FEX_DISABLETELEMETRY=1', *environment, *command]


class Capture:
    """Drain output for the whole session without limiting guest file creation.

    Wine services may inherit the pipe after the launcher exits. Their readers
    stay alive until cleanup, with a separately bounded final join. Reaching the
    cap discards further bytes rather than blocking the guest on a full pipe.
    """
    def __init__(self, command, path, *, limit=LOG_LIMIT, needle=None, line_prefixes=()):
        self.limit = limit
        self.truncated = False
        self.error = None
        self.matched = threading.Event()
        self.needle = needle
        self.line_prefixes = line_prefixes
        self.lines = {}
        self.exit_code = None
        self.log = path.open('xb', buffering=0)
        try:
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except BaseException:
            self.log.close()
            raise
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self):
        retained = 0
        suffix = b''
        line_tail = b''
        try:
            while True:
                block = os.read(self.process.stdout.fileno(), packages.BUFFER)
                if not block:
                    break
                if self.line_prefixes:
                    lines = (line_tail + block).split(b'\n')
                    line_tail = lines.pop()[-4096:]
                    for line in lines:
                        for prefix in self.line_prefixes:
                            if line.startswith(prefix) and len(line) <= 1024:
                                self.lines[prefix.decode()] = line.rstrip(b'\r').decode('utf-8', errors='replace')
                if self.needle:
                    combined = suffix + block
                    if self.needle in combined:
                        self.matched.set()
                    keep = len(self.needle) - 1
                    suffix = combined[-keep:] if keep else b''
                available = max(0, self.limit - retained)
                self.truncated |= len(block) > available
                if available and self.error is None:
                    try:
                        selected = memoryview(block)[:available]
                        while selected:
                            count = self.log.write(selected)
                            if not count:
                                raise OSError('short-log-write')
                            retained += count
                            selected = selected[count:]
                    except OSError as error:
                        self.error = str(error)
                        # Keep draining if storage fails; the owner will fail
                        # qualification instead of deadlocking its descendants.
            if self.error is None:
                os.fsync(self.log.fileno())
        except (OSError, ValueError) as error:
            self.error = str(error)
        finally:
            self.process.stdout.close()
            self.log.close()

    def wait(self, timeout):
        try:
            self.exit_code = self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
            raise
        return self

    def finish(self, timeout):
        self.reader.join(timeout=max(0, timeout))
        return not self.reader.is_alive()


def run_logged(command, path, timeout, captures, needle=None, line_prefixes=()):
    capture = Capture(command, path, needle=needle, line_prefixes=line_prefixes)
    captures.append(capture)
    return capture.wait(timeout)


def worker(runtime, output):
    # A direct accidental --namespace-worker invocation must never mount on the
    # caller's host. PID 1 is the init created by the outer unshare command.
    packages.require(os.getpid() == 1 and os.geteuid() == 0, 'worker-requires-owned-pid-namespace')
    packages.require(os.environ.get('ESTERIA_NAMESPACE_CHILD') == '1', 'worker-not-owned')
    root = runtime / 'rootfs'
    fixture = root / GUEST.lstrip('/')
    plan, _ = read_json(fixture / 'qualification-plan.json')
    result = {'displayReady': False, 'prefixExit': None, 'fixtureExit': None,
              'codecMessageMatched': False, 'networkIsolated': False,
              'expectedExit': None, 'workerCompleted': False}
    display = None
    captures = []
    try:
        # Mounts live only in this disposable mount namespace; /proc exposes
        # only this PID namespace. No mounts are installed on the CI host.
        for source in ('/dev', '/proc', '/sys'):
            target = packages.directory(root / source.lstrip('/'), create=True)
            subprocess.run(['mount', '--bind', source, str(target)], check=True, timeout=15)
            if source == '/sys':
                subprocess.run(['mount', '-o', 'remount,bind,ro', str(target)], check=True, timeout=15)
        subprocess.run(['ip', 'link', 'set', 'lo', 'up'], check=True, timeout=15)
        interfaces = json.loads(subprocess.check_output(['ip', '-j', 'link', 'show'], timeout=15))
        packages.require({item['ifname'] for item in interfaces} == {'lo'}, 'unexpected-network-interface')
        result['networkIsolated'] = True
        for name in ('home', 'prefix'):
            (fixture / name).mkdir(mode=0o700)
        display_capture = Capture(guest_command(root, '/usr/bin/Xtigervnc', ':8', '-geometry', '640x480',
                                  '-depth', '24', '-rfbport', '-1', '-SecurityTypes', 'None',
                                  '-nolisten', 'tcp', '-ac'), output / 'display.log')
        captures.append(display_capture)
        display = display_capture.process
        deadline = time.monotonic() + 20
        socket = root / 'tmp/.X11-unix/X8'
        while time.monotonic() < deadline and display.poll() is None:
            if socket.exists() and stat.S_ISSOCK(socket.lstat().st_mode):
                result['displayReady'] = True
                break
            time.sleep(0.1)
        packages.require(result['displayReady'], 'headless-display-not-ready')
        result['prefixExit'] = run_logged(guest_command(root, '/opt/wine/bin/wine', 'wineboot.exe', '-u'),
                                         output / 'wineboot.log', 180, captures).exit_code
        packages.require(result['prefixExit'] == 0, 'wine-prefix-failed')
        codec = run_logged(guest_command(root, '/opt/wine/bin/wine',
            GUEST + '/test_xvid_adapter.exe', r'Z:\esteria-qualification\XvidDecoder.dll'),
            output / 'codec.log', 120, captures, needle=SUCCESS.encode())
        result['fixtureExit'] = codec.exit_code
        result['codecMessageMatched'] = codec.matched.wait(timeout=5)
        packages.require(result['fixtureExit'] == 0 and result['codecMessageMatched'], 'codec-fixture-failed')
        if plan['clientEntryRequested']:
            receipt_path = fixture / ENTRY_RECEIPT
            packages.require(not os.path.lexists(receipt_path), 'client-entry-receipt-already-exists')
            entry = dict(launchAttempted=True, exitCode=None, messageObserved=False, receiptValidated=False)
            result['clientEntry'] = entry
            capture = run_logged(guest_command(root, '/opt/wine/bin/wine', GUEST + '/WowClient64.exe',
                                               '--esteria-entry-check'),
                                 output / 'client-entry.log', 120, captures, needle=ENTRY_SUCCESS.encode())
            entry['exitCode'] = capture.exit_code
            # AllocConsole may move stdout to Wine's console; the exclusive
            # receipt and process exit are authoritative for this narrow gate.
            entry['messageObserved'] = capture.matched.is_set()
            packages.require(capture.exit_code == 0, 'client-entry-process-failed')
            value, digest = read_entry_receipt(receipt_path)
            entry.update(receipt=value, receiptSha256=digest, receiptValidated=True)
            packages.write_json(output / 'client-entry-check.json', value)
        if plan.get('clientOfflineRequested'):
            result['clientOffline'] = {}
            receipt_path = fixture / OFFLINE_RECEIPT
            packages.require(not os.path.lexists(receipt_path), 'client-offline-receipt-already-exists')
            for spelling in ('-local-offline', '--local-offline'):
                label = 'short' if spelling == '-local-offline' else 'long'
                observed = dict(exitCode=None, receiptValidated=False)
                result['clientOffline'][spelling] = observed
                capture = run_logged(guest_command(root, '/opt/wine/bin/wine', GUEST + '/WowClient64.exe',
                                     '--offline-check', spelling), output / ('client-offline-' + label + '.log'), 120, captures)
                observed['exitCode'] = capture.exit_code
                packages.require(capture.exit_code == 0, 'client-offline-process-failed')
                value, digest = read_offline_receipt(receipt_path)
                observed.update(receipt=value, receiptSha256=digest, receiptValidated=True)
                packages.write_json(output / ('client-offline-' + label + '.json'), value)
                if label == 'short':receipt_path.unlink() # Only this validated, private fixture receipt.
        result['graphics'] = {}
        for name in plan['graphicsRequested']:
            filename, message = VULKAN_FIXTURES[name]
            capture = run_logged(guest_command(root, '/opt/wine/bin/wine', GUEST + '/' + filename,
                                               graphics=plan['softwareGraphics']),
                output / (name + '.log'), 180, captures, needle=message.encode(),
                line_prefixes=(b'Vulkan adapter:', b'Vulkan validation callback:', ENGINE_FRAME_SUCCESS.encode()))
            matched = capture.matched.wait(timeout=5)
            adapter = capture.lines.get('Vulkan adapter:', '')
            observed = dict(exitCode=capture.exit_code, messageMatched=matched, adapter=adapter,
                            softwareAdapterMatched=adapter.startswith(plan['softwareGraphics']['expectedAdapterPrefix']),
                            validationCallbackActive=capture.lines.get('Vulkan validation callback:') ==
                            'Vulkan validation callback: active')
            result['graphics'][name] = observed
            if name == 'presentation':
                observed['engineFrameMessageMatched'] = capture.lines.get(ENGINE_FRAME_SUCCESS) == ENGINE_FRAME_SUCCESS
            packages.require(capture.exit_code == 0 and matched and observed['softwareAdapterMatched'],
                             name + '-vulkan-fixture-failed')
            if name == 'presentation' and plan.get('engineFrameReadbackRequired'):
                packages.require(observed['engineFrameMessageMatched'], 'engine-frame-readback-marker-missing')
        if plan.get('audioRequested'):
            wine_audio.configure(fixture, GUEST)
            result['audio'] = {}
            for backend in wine_audio.BACKENDS:
                observed = {}
                result['audio'][backend] = observed
                wine_audio.execute(root, fixture, output, GUEST, backend, observed, run_logged, guest_command, captures)
        result['expectedExit'] = 0
        return 0
    except Exception as error:
        result['failure'] = str(error)
        result['expectedExit'] = 1
        return 1
    finally:
        finish_wine(root, output, result, captures)
        if display is not None:
            display.terminate()
            try:
                display.wait(timeout=5)
            except subprocess.TimeoutExpired:
                display.kill()
                display.wait(timeout=5)
        drain_deadline = time.monotonic() + 5
        result['logStreamsDrained'] = all([capture.finish(drain_deadline - time.monotonic()) for capture in captures])
        result['logsWithinLimit'] = all(not capture.truncated for capture in captures)
        result['logWritesSucceeded'] = all(capture.error is None for capture in captures)
        result['workerCompleted'] = True
        packages.write_json(output / 'worker-result.json', result)
        # Exiting PID 1 tears down every descendant, including detached Wine
        # services. The outer owner observes namespace process exit before pass.


def finish_wine(root, output, result, captures):
    # Each audio case stops and waits for this same private prefix before PCM
    # EOF is inspected. A second -k returns 1 when that server is already gone.
    # Reuse only the latest case's observed successful stop+wait, then require a
    # fresh final wait. An earlier case cannot excuse incomplete later cleanup.
    audio = result.get('audio', {})
    latest = next((name for name in reversed(tuple(wine_audio.BACKENDS)) if name in audio), None)
    previous = audio.get(latest, {})
    if previous.get('wineStopExit') == 0 and previous.get('wineWaitExit') == 0:
        result['wineStopExit'] = previous['wineStopExit']
        result['wineStopSource'] = 'audio-' + latest
    else:
        try:
            result['wineStopExit'] = run_logged(guest_command(root, '/opt/wine/bin/wineserver', '-k'),
                                               output / 'wine-stop.log', 15, captures).exit_code
            result['wineStopSource'] = 'final-cleanup'
        except Exception as error:
            result['wineStopFailure'] = str(error)
    try:
        result['wineWaitExit'] = run_logged(guest_command(root, '/opt/wine/bin/wineserver', '-w'),
                                           output / 'wine-wait.log', 15, captures).exit_code
    except Exception as error:
        result['wineWaitFailure'] = str(error)


def graphics_identity(root, lock):
    candidate = lock['softwareGraphics']
    packages.require(candidate['runtimeArchiveSha256'] == lock['packages']['wine-arm64']['archive']['sha256'],
                     'graphics-runtime-identity-mismatch')
    for name, expected in candidate['components'].items():
        with packages.plain_file(root / name) as stream:
            packages.verify_stream(stream, dict(file=Path(name).name, **expected))
            stream.seek(0)
            packages.inspect_component(stream.read(4096), expected)
    icd, _ = read_json(root / candidate['icdPath'])
    packages.require(icd.get('file_format_version') == '1.0.0' and
                     icd.get('ICD') == dict(api_version=candidate['icdApiVersion'], library_path=candidate['icdLibrary']),
                     'lavapipe-icd-contract-mismatch')
    return candidate


def qualification_flags(result, requested, namespace_exit=0, client_entry=False, audio=False, client_offline=False):
    # A deliberate handled fixture failure may preserve earlier passing scopes.
    # An abnormal namespace exit may not qualify anything, even if a receipt was
    # flushed just before the worker was killed.
    completed = (result.get('workerCompleted') is True and type(result.get('expectedExit')) is int and
                 result['expectedExit'] in (0, 1) and type(namespace_exit) is int and
                 namespace_exit == result['expectedExit'])
    common = (completed and result.get('displayReady') is True and result.get('networkIsolated') is True and
              result.get('prefixExit') == 0 and result.get('wineStopExit') == 0 and result.get('wineWaitExit') == 0 and
              result.get('logStreamsDrained') is True and result.get('logsWithinLimit') is True and
              result.get('logWritesSucceeded') is True)
    flags = {'linuxArm64CodecQualified': bool(common and result.get('fixtureExit') == 0 and
                                              result.get('codecMessageMatched') is True),
             'linuxArm64VulkanPresentationQualified': False, 'linuxArm64VulkanTextureLifecycleQualified': False,
             'linuxArm64ClientEntryQualified': False, 'linuxArm64VulkanEngineFrameReadbackQualified': False,
             'linuxArm64FmodPcmTransportQualified': False, 'linuxArm64ClientOfflineBoundariesQualified': False}
    if client_offline:
        observed = result.get('clientOffline', {})
        flags['linuxArm64ClientOfflineBoundariesQualified'] = bool(common and
            set(observed) == {'-local-offline', '--local-offline'} and
            all(case.get('exitCode') == 0 and case.get('receiptValidated') is True for case in observed.values()))
    if audio:
        flags['linuxArm64FmodPcmTransportQualified'] = bool(common and
            all(wine_audio.passed(result.get('audio', {}).get(name, {})) for name in wine_audio.BACKENDS))
    if client_entry:
        entry = result.get('clientEntry', {})
        flags['linuxArm64ClientEntryQualified'] = bool(common and entry.get('launchAttempted') is True and
            entry.get('exitCode') == 0 and entry.get('receiptValidated') is True)
    for name in requested:
        observed = result.get('graphics', {}).get(name, {})
        passed = bool(common and observed.get('exitCode') == 0 and observed.get('messageMatched') is True and
                      observed.get('softwareAdapterMatched') is True)
        flags['linuxArm64VulkanPresentationQualified' if name == 'presentation' else
              'linuxArm64VulkanTextureLifecycleQualified'] = passed
        if name == 'presentation':
            flags['linuxArm64VulkanEngineFrameReadbackQualified'] = bool(
                passed and observed.get('engineFrameMessageMatched') is True)
    return flags


def qualify(runtime, client_dir, driver, output, graphics=None, client_entry=False, require_engine_frame=False,
            audio_driver=None, bridge_dir=None, bridge_revision=None, client_offline=False):
    packages.require(not client_offline or client_entry, 'offline-check-requires-client-entry-check')
    packages.require(not require_engine_frame or 'presentation' in (graphics or {}),
                     'engine-frame-readback-requires-presentation-driver')
    packages.require(bool(audio_driver) == bool(bridge_dir) == bool(bridge_revision), 'audio-driver-and-pinned-bridge-required-together')
    packages.require(platform.machine().lower() in ('aarch64', 'arm64'), 'native-arm64-host-required')
    packages.require(os.geteuid() == 0, 'invoke-qualification-with-sudo')
    runtime = packages.directory(runtime)
    manifest, client = client_inputs(client_dir, driver)
    lock, _ = read_json(packages.DEFAULT_LOCK)
    package = lock['packages']['wine-arm64']
    prepared, prepared_sha = read_json(runtime / 'package-receipt.json')
    pin_sha = hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    packages.require(prepared.get('archiveSha256') == package['archive']['sha256'] and
                     prepared.get('manifestSha256') == package['manifest']['sha256'] and
                     prepared.get('packagePinSha256') == pin_sha and
                     prepared.get('preparerSha256') == hashlib.sha256(Path(packages.__file__).read_bytes()).hexdigest() and
                     prepared.get('archiveExtracted') is True and prepared.get('stagedFilesReadBack') is True,
                     'runtime-not-prepared-by-this-revision')
    for name, expected in package['components'].items():
        with packages.plain_file(runtime / 'rootfs' / name) as stream:
            packages.verify_stream(stream, dict(file=Path(name).name, **expected))
    packages.directory(output.parent, create=True)
    output.mkdir(mode=0o700)
    root = runtime / 'rootfs'
    audio_identity = wine_audio.bridge_identity(root, bridge_dir, bridge_revision, lock) if audio_driver else None
    if audio_driver:
        client['files']['fmod_output_device.exe'] = pe_identity(audio_driver, False)
    graphics = graphics or {}
    packages.require(set(graphics) <= set(VULKAN_FIXTURES), 'unknown-graphics-fixture')
    software_graphics = graphics_identity(root, lock) if graphics else None
    for name, path in graphics.items():
        client['files'][VULKAN_FIXTURES[name][0]] = pe_identity(path, False)
    fixture = root / GUEST.lstrip('/')
    packages.require(not os.path.lexists(fixture), 'runtime-already-used-for-qualification')
    fixture.mkdir(mode=0o700)
    inputs = [(driver, 'test_xvid_adapter.exe'), (client_dir / 'XvidDecoder.dll', 'XvidDecoder.dll')]
    if client_entry:
        inputs.append((client_dir / 'WowClient64.exe', 'WowClient64.exe'))
    inputs += [(path, VULKAN_FIXTURES[name][0]) for name, path in graphics.items()]
    if audio_driver:
        inputs.append((audio_driver, 'fmod_output_device.exe'))
    for source, name in inputs:
        with packages.plain_file(source) as src, (fixture / name).open('xb') as dst:
            digest = packages.hash_stream(src, client['files'][name]['bytes'], dst)
            packages.require(digest == client['files'][name]['sha256'], 'fixture-changed-during-copy')
            dst.flush()
            os.fsync(dst.fileno())
    if audio_driver:
        with packages.plain_file(bridge_dir / 'bin' / wine_audio.PLUGIN) as src, (fixture / wine_audio.PLUGIN).open('xb') as dst:
            expected = audio_identity['plugin']
            packages.require(packages.hash_stream(src, expected['bytes'], dst) == expected['sha256'], 'audio-plugin-changed-during-copy')
            dst.flush()
            os.fsync(dst.fileno())
    packages.write_json(fixture / 'qualification-plan.json',
                        dict(graphicsRequested=list(graphics), softwareGraphics=software_graphics,
                             clientEntryRequested=client_entry, engineFrameReadbackRequired=require_engine_frame,
                             clientOfflineRequested=client_offline,
                             audioRequested=bool(audio_driver)))
    report = dict(formatVersion=1, scope='native-linux-arm64-wine-component-fixtures',
                  runtimeArchiveSha256=package['archive']['sha256'], runtimeReceiptSha256=prepared_sha,
                  client=client, directImports=imports_report(manifest, prepared),
                  androidRuntimeQualified=False, clientExecutableLaunchAttempted=False,
                  clientExecutableEntryReached=False, gameInitializationStarted=False, renderingQualified=False,
                  audioQualified=False, gameLoginQualified=False, serverRuntimeIncluded=False,
                  linuxArm64CodecQualified=False, processNamespaceExited=False,
                  linuxArm64VulkanPresentationQualified=False, linuxArm64VulkanTextureLifecycleQualified=False,
                  linuxArm64ClientEntryQualified=False, clientEntryRequested=client_entry,
                  linuxArm64ClientOfflineBoundariesQualified=False, clientOfflineRequested=client_offline,
                  linuxArm64VulkanEngineFrameReadbackQualified=False, engineFrameReadbackRequired=require_engine_frame,
                  linuxArm64FmodPcmTransportQualified=False, audioRequested=bool(audio_driver), audioBridge=audio_identity,
                  softwareGraphics=software_graphics, graphicsRequested=list(graphics))
    command = namespace_command(Path(__file__).resolve(), runtime, output, os.geteuid() == 0)
    child = None
    try:
        with (output / 'namespace.log').open('xb') as log:
            child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8',
                     'ESTERIA_NAMESPACE_CHILD': '1'})
            try:
                report['namespaceExit'] = child.wait(timeout=420 + 185 * len(graphics) + (125 if client_entry else 0) +
                                                    (620 if audio_driver else 0) + (250 if client_offline else 0))
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=15)
                raise ValueError('wine-qualification-timeout')
        report['processNamespaceExited'] = True
        result, _ = read_json(output / 'worker-result.json')
        report['worker'] = result
        report.update(qualification_flags(result, graphics, report['namespaceExit'], client_entry, bool(audio_driver), client_offline))
        report['clientExecutableLaunchAttempted'] = result.get('clientEntry', {}).get('launchAttempted') is True
        report['clientExecutableEntryReached'] = report['linuxArm64ClientEntryQualified']
        packages.require(report['linuxArm64CodecQualified'], 'wine-codec-qualification-failed')
        if client_entry:
            packages.require(report['linuxArm64ClientEntryQualified'], 'client-entry-not-qualified')
        if client_offline:
            packages.require(report['linuxArm64ClientOfflineBoundariesQualified'], 'client-offline-boundaries-not-qualified')
        for name in graphics:
            key = ('linuxArm64VulkanPresentationQualified' if name == 'presentation' else
                   'linuxArm64VulkanTextureLifecycleQualified')
            packages.require(report[key], name + '-vulkan-not-qualified')
        if require_engine_frame:
            packages.require(report['linuxArm64VulkanEngineFrameReadbackQualified'], 'engine-frame-readback-not-qualified')
        if audio_driver:
            packages.require(report['linuxArm64FmodPcmTransportQualified'], 'fmod-pcm-transport-not-qualified')
        packages.require(report['namespaceExit'] == 0, 'wine-worker-exit-failed')
        return report
    except Exception as error:
        report['failure'] = str(error)
        raise
    finally:
        if child is not None and child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=15)
        if child is not None and child.poll() is not None:
            report['processNamespaceExited'] = True
        packages.write_json(output / 'qualification.json', report)
        # A sudo invocation must leave its bounded evidence readable by the CI
        # account. Only this newly-created output directory is transferred.
        if os.environ.get('SUDO_UID', '').isdigit() and os.environ.get('SUDO_GID', '').isdigit():
            uid, gid = int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID'])
            for path in output.iterdir():
                packages.require(stat.S_ISREG(path.lstat().st_mode), 'unexpected-evidence-file-type')
                os.chown(path, uid, gid, follow_symlinks=False)
            os.chown(output, uid, gid, follow_symlinks=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True, help='New prepared bundle containing rootfs/ and receipt')
    parser.add_argument('--client-dir', type=Path)
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--presentation-driver', type=Path)
    parser.add_argument('--texture-driver', type=Path)
    parser.add_argument('--audio-driver', type=Path, help='Actual source-built ARM64 FMOD Windows output fixture')
    parser.add_argument('--bridge-dir', type=Path, help='Matching source-built native guest bridge payload')
    parser.add_argument('--bridge-revision', help='Exact integration revision used to build the guest bridge')
    parser.add_argument('--client-entry-check', action='store_true', help='Launch the verified full PE in its explicit entry-only mode')
    parser.add_argument('--client-offline-check', action='store_true', help='Exercise both real offline command spellings and refused remote paths')
    parser.add_argument('--require-engine-frame-readback', action='store_true',
                        help='Require the presentation driver to pass real engine scene readback and embedded shaders')
    parser.add_argument('--output', type=Path, required=True, help='New evidence directory')
    parser.add_argument('--namespace-worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.runtime = args.runtime.absolute()
    args.output = args.output.absolute()
    if args.namespace_worker:
        return worker(args.runtime, args.output)
    packages.require(args.client_dir is not None and args.driver is not None, 'client-dir-and-driver-required')
    graphics = {name: path.absolute() for name, path in
                (('presentation', args.presentation_driver), ('texture', args.texture_driver)) if path is not None}
    result = qualify(args.runtime, args.client_dir.absolute(), args.driver.absolute(), args.output, graphics,
                     args.client_entry_check, args.require_engine_frame_readback,
                     args.audio_driver.absolute() if args.audio_driver else None,
                     args.bridge_dir.absolute() if args.bridge_dir else None, args.bridge_revision, args.client_offline_check)
    print(json.dumps({key: result[key] for key in ('linuxArm64CodecQualified', 'linuxArm64VulkanPresentationQualified',
                                                 'linuxArm64VulkanTextureLifecycleQualified', 'linuxArm64ClientEntryQualified',
                                                 'linuxArm64VulkanEngineFrameReadbackQualified',
                                                 'linuxArm64FmodPcmTransportQualified',
                                                 'linuxArm64ClientOfflineBoundariesQualified',
                                                 'androidRuntimeQualified')}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error)) from error
