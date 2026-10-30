"""Source/ABI verification and actual FMOD-to-ALSA PCM capture for Wine qualification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

try:
    from . import pcm_capture, prepare_runtime as packages
except ImportError:
    import pcm_capture
    import prepare_runtime as packages

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = 'libasound_module_pcm_esteria.so'
BACKENDS = {'winmm': 'WinMM', 'dsound': 'DirectSound'}


def bridge_identity(root, payload, revision, lock, bridge_input_lock=None):
    packages.require(re.fullmatch('[0-9a-f]{40}', revision or '') is not None, 'exact-audio-bridge-revision-required')
    payload = packages.directory(payload)
    with packages.plain_file(payload / 'bridge-build.json') as stream:
        raw = stream.read(packages.MAX_METADATA + 1)
    packages.require(len(raw) <= packages.MAX_METADATA, 'audio-bridge-receipt-size-limit')
    receipt = json.loads(raw)
    packages.require(type(receipt.get('formatVersion')) is int and receipt.get('formatVersion') == 1 and receipt.get('compiled') is True and
                     receipt.get('scope') == 'linux-arm64-guest-bridge-build-only' and
                     receipt.get('integrationRevision') == revision, 'audio-bridge-receipt-identity-mismatch')
    sources = list((ROOT / 'native/guest-bridges').glob('*')) + [ROOT / 'native/presentation' / name
              for name in ('frame_protocol.h', 'frame_transport.h')]
    expected = {}
    for path in sources:
        if path.is_dir():
            continue
        with packages.plain_file(path) as stream:
            size = path.stat().st_size
            expected[str(path.relative_to(ROOT / 'native'))] = dict(bytes=size, sha256=packages.hash_stream(stream, size))
    packages.require(receipt.get('sources') == expected, 'audio-bridge-source-mismatch')
    selected_lock = bridge_input_lock if bridge_input_lock is not None else ROOT / 'runtime/bridges/sources.lock.json'
    with packages.plain_file(selected_lock) as stream:
        lock_raw = stream.read(packages.MAX_METADATA + 1)
    packages.require(len(lock_raw) <= packages.MAX_METADATA, 'audio-bridge-input-lock-size-limit')
    bridge_lock = json.loads(lock_raw)
    packages.require(receipt.get('inputLockSha256') == hashlib.sha256(lock_raw).hexdigest(),
                     'audio-bridge-input-lock-mismatch')
    archive = lock['packages']['wine-arm64']['archive']['sha256']
    packages.require(type(bridge_lock) is dict and bridge_lock.get('runtimeArchiveSha256') == archive and
                     receipt.get('runtimeArchiveSha256') == archive and
                     lock['softwareAudio']['runtimeArchiveSha256'] == archive, 'audio-runtime-identity-mismatch')
    for name, expected in lock['softwareAudio']['components'].items():
        with packages.plain_file(root / name) as stream:
            packages.verify_stream(stream, dict(file=Path(name).name, **expected))
            stream.seek(0)
            packages.inspect_component(stream.read(4096), expected)
    # Reuse the exact source-build ELF checker, including readelf dependencies,
    # forbidden loader/search paths and glibc <=2.36; receipt assertions alone
    # do not establish what the supplied plugin bytes require.
    spec = importlib.util.spec_from_file_location('esteria_bridge_build', ROOT / 'runtime/bridges/record_build.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    plugin = packages.directory(payload / 'bin') / PLUGIN
    with packages.plain_file(plugin):
        actual = module.elf(plugin)
    needed = set(actual['needed'])
    required = {'libasound.so.2', 'libc.so.6'}
    # AArch64 glibc can import __stack_chk_guard from this exact pinned loader.
    # Keep that one legitimate direct dependency distinct from arbitrary libs.
    packages.require(actual == receipt.get('binaries', {}).get(PLUGIN) and len(needed) == len(actual['needed']) and
                     required <= needed <= required | {'ld-linux-aarch64.so.1'}, 'audio-plugin-binary-contract-mismatch')
    return dict(integrationRevision=revision, buildReceiptSha256=hashlib.sha256(raw).hexdigest(),
                inputLockSha256=receipt['inputLockSha256'], plugin=actual, softwareAudio=lock['softwareAudio'])


def configure(fixture, guest):
    # ALSA's system definitions supply conversion machinery; the only default
    # playback endpoint is the explicit source-built private PCM plugin.
    config = ('</usr/share/alsa/alsa.conf>\n'
              'pcm_type.esteria { lib "' + guest + '/' + PLUGIN + '" }\n'
              'pcm.esteria { type esteria }\n'
              'pcm.!default { type plug slave { pcm "esteria" format S16_LE rate 48000 channels 2 } }\n')
    with (fixture / 'alsa-qualification.conf').open('x') as stream:
        stream.write(config)


def execute(root, fixture, output, guest, backend, observed, run_logged, guest_command, captures):
    packages.require(backend in BACKENDS, 'unknown-audio-backend')
    receiver = pcm_capture.PcmCapture(fixture / 'audio.sock')
    failure = None
    try:
        registration = run_logged(guest_command(root, '/opt/wine/bin/wine', 'reg.exe', 'add',
            r'HKCU\Software\Wine\Drivers', '/v', 'Audio', '/d', 'alsa', '/f', audio=True),
            output / ('audio-' + backend + '-registry.log'), 120, captures)
        observed['driverSelectionExit'] = registration.exit_code
        packages.require(registration.exit_code == 0, 'wine-alsa-driver-selection-failed')
        marker = 'PASS: Reconstructed FMOD ' + BACKENDS[backend] + ' stereo playback lifecycle (PCM capture required)'
        capture = run_logged(guest_command(root, '/opt/wine/bin/wine', guest + '/fmod_output_device.exe',
            '--' + backend, audio=True), output / ('audio-' + backend + '.log'), 120, captures, needle=marker.encode(),
            line_prefixes=(marker.encode(), b'FMOD output:'))
        capture.matched.wait(timeout=5)
        observed.update(fixtureExit=capture.exit_code, messageMatched=capture.lines.get(marker) == marker,
                        outputDevice=capture.lines.get('FMOD output:', ''))
    except Exception as error:
        failure = error
        observed['failure'] = str(error)
    finally:
        # Stop the owned Wine server and observe its exit before interpreting
        # EOF. Detached guest processes must not leave capture workers waiting.
        for label, argument in (('wineStopExit', '-k'), ('wineWaitExit', '-w')):
            try:
                stopped = run_logged(guest_command(root, '/opt/wine/bin/wineserver', argument),
                    output / ('audio-' + backend + '-' + label + '.log'), 30, captures)
                observed[label] = stopped.exit_code
                packages.require(stopped.exit_code == 0, 'audio-wineserver-cleanup-failed')
            except Exception as error:
                failure = failure or error
                observed[label + 'Failure'] = str(error)
        try:
            observed['pcmEofDrained'] = receiver.wait_eof(3)
            receiver.close()
            observed['pcm'] = receiver.report(output, 'audio-' + backend + '-captured')
        except Exception as error:
            failure = failure or error
            observed['captureFailure'] = str(error)
    if failure:
        raise failure
    packages.require(passed(observed), 'fmod-' + backend + '-pcm-transport-failed')


def passed(observed):
    return (observed.get('driverSelectionExit') == 0 and observed.get('fixtureExit') == 0 and
            observed.get('messageMatched') is True and observed.get('wineStopExit') == 0 and
            observed.get('wineWaitExit') == 0 and observed.get('pcmEofDrained') is True and
            observed.get('pcm', {}).get('pcmSignalQualified') is True)
