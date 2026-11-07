"""Run inside the immutable-payload, offline Linux chroot. No external package dependencies."""
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

RESULT = Path('/work/result.json')
ENV = dict(PATH='/opt/wine/bin:/usr/bin:/bin', HOME='/work/home', WINEPREFIX='/work/wine',
           XDG_RUNTIME_DIR='/work/xdg', DISPLAY=':100', XAUTHORITY='/session/Xauthority',
           WINEESYNC='0', WINEFSYNC='0', WINE_ANDROID_PRIVATE_PE_COPY='1', WINEDLLOVERRIDES='winepulse.drv=',
           ESTERIA_AUDIO_SOCKET='/session/audio.sock', ALSA_CONFIG_PATH='/esteria-bridges/etc/alsa-esteria.conf',
           VK_ICD_FILENAMES='/usr/share/vulkan/icd.d/lvp_icd.aarch64.json',
           VK_DRIVER_FILES='/usr/share/vulkan/icd.d/lvp_icd.aarch64.json', GX_VULKAN_SHADERS=r'Z:\esteria-shaders',
           WINEDEBUG='-all', FEX_DISABLETELEMETRY='1', WINEARCH='win64', LP_NUM_THREADS='2')
PROCS = []


def launch(*args, env=ENV):
    child = subprocess.Popen(args, cwd='/work/client', env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    PROCS.append(child)
    return child


def frame():
    def receive(sock, size):
        data = bytearray()
        while len(data) < size:
            part = sock.recv(size - len(data))
            if not part:
                raise OSError('truncated')
            data.extend(part)
        return data
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        sock.connect('/session/frame.sock')
        sock.sendall(b'\x01')
        magic, w, h, stride, _, _, length, flags = struct.unpack('>8I', receive(sock, 32))
        if (magic, w, h, stride, length, flags) != (0x54524631, 1280, 720, 5120, 3686400, 0):
            raise ValueError('frame-format')
        pixels = receive(sock, length)
    return {'sha256': hashlib.sha256(pixels).hexdigest(),
            'sampleColors': len({bytes(pixels[i:i+3]) for i in range(0, length, 127*4)})}


def run():
    report = {'phase': 'x11', 'frameSamples': [], 'titleQualified': False}
    try:
        def field(value):
            return struct.pack('>H', len(value)) + value
        Path('/session/Xauthority').write_bytes(b'\xff\xff' + field(b'') + field(b'100')
                                       + field(b'MIT-MAGIC-COOKIE-1') + field(os.urandom(16)))
        launch('/usr/bin/Xtigervnc', ':100', '-geometry', '1280x720', '-depth', '24',
               '-nolisten', 'tcp', '-rfbport', '-1', '-auth', '/session/Xauthority', '-noreset')
        for path, cmd in [('/tmp/.X11-unix/X100', ('/esteria-bridges/bin/esteria-x11-frame', '/session/frame.sock', '30')),
                          ('/session/frame.sock', ('/esteria-bridges/bin/esteria-x11-input', '/session/input.sock'))]:
            for _ in range(100):
                if Path(path).is_socket():
                    break
                time.sleep(0.1)
            launch(*cmd)
        report['phase'] = 'prefix'
        report['background'] = frame()
        boot = launch('/opt/wine/bin/wine', 'wineboot.exe', '-u',
                      env=dict(ENV, WINEDLLOVERRIDES='winemenubuilder,mshtml,mscoree=;winepulse.drv='))
        if boot.wait(timeout=180) != 0 or not Path('/work/wine/system.reg').is_file():
            raise RuntimeError('prefix')
        report['phase'] = 'client'
        started = time.monotonic()
        client = launch('/opt/wine/bin/wine', r'Z:\work\client\WowClient64.exe',
                       '-datadir', r'Z:\work\client', '-vulkan', '--local-offline')
        for after in (5, 15, 30, 60):
            time.sleep(max(0, started + after - time.monotonic()))
            if client.poll() is not None:
                break
            sample = frame()
            sample['afterSeconds'] = round(time.monotonic() - started, 1)
            report['frameSamples'].append(sample)
        report['clientExitBeforeCleanup'] = client.poll()
        report['phase'] = 'observed'
    except Exception as err:
        report['failure'] = type(err).__name__
    finally:
        # The input view is disposable, with no account credentials or database. Forced termination is not a save.
        for proc in reversed(PROCS):
            if proc.poll() is None:
                proc.terminate()
        for proc in PROCS:
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        report['wrappersReaped'] = all(child.poll() is not None for child in PROCS)
        RESULT.write_text(json.dumps(report))


if __name__ == '__main__':
    run()
