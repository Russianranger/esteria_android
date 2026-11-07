"""Bounded, offline native Linux ARM64 client capture after complete stock shader validation."""
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import zipfile

from tools import prepare_runtime

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT/'tools/stock_client_capture'
V13 = ROOT/'runtime/evidence/non-custom-v13-public-apk-readback.json'
SOURCE = ROOT/'runtime/releases/non-custom-v0.1.0-non-custom.13.json'
PE = 'WowClient64.exe'


def read(path):
    return json.loads(path.read_bytes())


def public_result(path):
    """Only a closed schema of counts, digests, phases and flags leaves the scratch directory."""
    if path.stat().st_size > 4096:
        raise ValueError('capture-size')
    raw = read(path)
    if raw['phase'] not in ('x11', 'prefix', 'client', 'observed'):
        raise ValueError('capture-phase')
    public = {'phase': raw['phase'], 'wrappersReaped': raw.get('wrappersReaped') is True,
              'commonMainLocaleRead': raw.get('commonMainLocaleRead') is True}
    if raw.get('failure') in ('OSError', 'ValueError', 'RuntimeError', 'TimeoutExpired', 'TimeoutError',
                              'ConnectionRefusedError', 'PermissionError', 'FileNotFoundError'):
        public['failure'] = raw['failure']
    public['rendererStages'] = {k: raw.get('rendererStages', {}).get(k) is True for k in
        ('device', 'swapchain', 'pipelines', 'presentation', 'extensionsStarted', 'worldModelRequested',
         'stockUiVertex', 'stockUiPixel', 'clientDatabasesInitialized', 'clientInitialized')}
    counts = raw['successfulClientAccesses']
    public['successfulClientAccesses'] = {
        k: v for k in ('locale','mpq','spirv') if type(v := counts[k]) is int and 0 <= v <= 65536}
    exit_code = raw.get('clientExitBeforeCleanup')
    if type(exit_code) is int and -128 <= exit_code <= 255:
        public['clientExitBeforeCleanup'] = exit_code
    def safe_frame(frame):
        if not re.fullmatch('[a-f0-9]{64}',frame['sha256']) or type(frame['sampleColors']) is not int or not 1 <= frame['sampleColors'] <= 10000:
            raise ValueError('invalid-frame-result')
        return {'sha256':frame['sha256'], 'sampleColors':frame['sampleColors']}
    public['frameSamples'] = [safe_frame(frame) for frame in raw['frameSamples'][:4]]
    if 'background' in raw:
        public['background'] = safe_frame(raw['background'])
    return public


def capture(work, client, shaders, revision):
    report = dict(environment='linux-arm64-software-vulkan', titleQualified=False, gameplayQualified=False,
                  phase='reference-inputs', clientRevision=revision, externalNetwork=False)
    try:
        if platform.machine() != 'aarch64' or os.getuid() == 0:
            raise ValueError('host')
        if Path(os.environ['RUNNER_TEMP']).resolve() not in work.resolve().parents:
            raise ValueError('scratch')
        if read(SOURCE)['clientRevision'] != revision:
            raise ValueError('client-pin')
        stage = work/'title'
        stage.mkdir(mode=0o700)
        evidence = read(V13)
        apk = next(asset for asset in evidence['assets'] if asset['name'].endswith('.apk'))
        url = evidence['releaseUrl'].replace('/tag/', '/download/') + '/' + apk['name']
        cache = stage/'cache'
        archive = prepare_runtime.fetch(dict(file=apk['name'],bytes=apk['bytes'],sha256=apk['sha256'],url=url),cache)
        wine = read(ROOT/'runtime/runtime-sources.lock.json')['packages']['wine-arm64']
        prepare_runtime.fetch(wine['archive'], cache)
        prepare_runtime.fetch(wine['manifest'], cache)
        prepare_runtime.prepare(wine, cache, stage/'wine')
        root = stage/'wine/rootfs'
        for name in ('work/client','work/home','work/wine','work/xdg','session','esteria-bridges'):
            (root/name).mkdir(mode=0o700, parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as signed:
            for prefix,member,target in [('guest-bridges','guest-bridges-arm64','esteria-bridges'),
                                         ('client-runtime','client-arm64','work/client')]:
                with signed.open(f'assets/{prefix}/{member}.archive') as stream, \
                        tarfile.open(fileobj=stream, mode='r|gz') as tar:
                    for entry in tar:
                        name=entry.name.removeprefix('./')
                        if prefix == 'client-runtime':
                            if name not in ('bin/'+PE, 'bin/XvidDecoder.dll','metadata/client-build.json'):
                                continue
                            destination=root/target/Path(name).name
                        else:
                            if name not in ('bin/esteria-x11-frame','bin/esteria-x11-input','etc/alsa-esteria.conf'):
                                continue
                            destination=root/target/name
                        if not entry.isreg():
                            raise ValueError('invalid-provider-member')
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        with tar.extractfile(entry) as source, destination.open('xb') as output:
                            shutil.copyfileobj(source,output)
                        destination.chmod(0o755)
        view = root/'work/client'
        built = read(view/'client-build.json')
        if built['source_revision'] != revision or built['architecture'] != 'ARM64':
            raise ValueError('executable-source')
        for entry in built['files']:
            name = entry['name']
            with (view/name).open('rb') as stream:
                prepare_runtime.verify_stream(stream,dict(file=name,bytes=entry['size'],sha256=entry['sha256']))
        report['clientExecutableSha256']=next(e['sha256'] for e in built['files'] if e['name']==PE)
        report['wineArchiveSha256']=wine['archive']['sha256']
        report['apkSha256']=apk['sha256']
        for src in sorted((client/'Data').rglob('*')):
            if src.is_file() and src.suffix.lower()=='.mpq':
                dest = view/src.relative_to(client)
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.symlink_to(Path('/esteria-data')/src.relative_to(client))
        (view/'Data/enUS/realmlist.wtf').write_text('set realmlist 127.0.0.1\n')
        for name in ('WTF','Cache','Logs','Screenshots'):
            state = root/'work/client-state'/name
            state.mkdir(parents=True)
            (view/name).symlink_to(Path('/work/client-state')/name)
        (root/'work/client-state/WTF/RunOnce~EsteriaLocale.wtf').write_text('SET locale "enUS"\n')
        shutil.copyfile(HELPERS/'guest.py',root/'work/guest.py')
        # Running Wine is confined to a new mount/PID/network namespace; it uses the unprivileged runner UID.
        report['phase']='launch-namespace'
        args = ['sudo','-n','timeout','--kill-after=10','305','unshare','--mount','--net','--pid',
                '--fork','--kill-child','--propagation','private','/usr/bin/python3',str(HELPERS/'namespace.py'),
                str(root),str(client),str(shaders),str(os.getuid()),str(os.getgid())]
        result=subprocess.run(args, stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              timeout=325,check=False)
        report['namespaceExit']=result.returncode
        if result.returncode == 0:
            report.update(public_result(root/'work/result.json'))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, KeyError) as exc:
        report['failure']=type(exc).__name__
    return report
