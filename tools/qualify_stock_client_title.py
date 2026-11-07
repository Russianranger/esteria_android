"""Bounded, offline native Linux ARM64 client capture after complete stock shader validation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

from runtime import shader_generation, stock_shader_generation
from tools import acquire_stock_renderer, prepare_runtime, provider_client_runtime

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


def renderer_pair(prepared_revision, wine_digest):
    provider = ROOT/'runtime/client'
    selected = provider/'stock-renderer-sources.lock.json'
    if not selected.exists():
        return None
    revision = read(selected)['sources']['client']['commit']
    pairing = read(provider/'renderer-compatibility.json')
    build = read(provider/'stock-renderer-build.lock.json')
    shader = read(ROOT/'runtime/shaders/android-provider.lock.json')
    if (pairing['formatVersion'] != 1 or pairing['scope'] != 'stock-renderer-only' or
            not re.fullmatch('[0-9a-f]{40}', revision) or
            revision != pairing['executableRevision'] or revision != build['sourceRevision'] or
            prepared_revision != pairing['preparedClientRevision'] or prepared_revision != shader['clientRevision'] or
            pairing['preparedSourceLockSha256'] != hashlib.sha256((ROOT/'sources.lock.json').read_bytes()).hexdigest() or
            pairing['executableSourceLockSha256'] != hashlib.sha256(selected.read_bytes()).hexdigest() or
            pairing['shaderToolManifestSha256'] != shader['toolManifestSha256'] or
            pairing['requiredWineArchiveSha256'] != wine_digest):
        raise ValueError('renderer-preparation-pair')
    return pairing, build


def stage_renderer(view, cache, pairing, build, artifact):
    revision = pairing['executableRevision']
    name = 'client-ARM64-' + revision + '.zip'
    url = f'{acquire_stock_renderer.REPOSITORY}/releases/download/stock-client-arm64-{revision}/{name}'
    pin = dict(build['artifact'], file=name, url=url)
    if artifact is None:
        artifact = prepare_runtime.fetch(pin, cache)
    # Verify the exact measured Windows ZIP even when passed directly by a pre-publication job.
    with prepare_runtime.plain_file(artifact.resolve(strict=True)) as source:
        before = os.fstat(source.fileno())
        prepare_runtime.verify_stream(source, pin)
        with provider_client_runtime.checked_zip(source) as archive:
            for name in ('WowClient64.exe', 'XvidDecoder.dll', 'client-build.json'):
                with archive.open('bin/Win/ARM64/'+name) as member, (view/name).open('wb') as target:
                    shutil.copyfileobj(member, target)
        after = os.fstat(source.fileno())
        if (before.st_size,before.st_ctime_ns) != (after.st_size,after.st_ctime_ns):
            raise ValueError('candidate-changed')
    if hashlib.sha256((view/PE).read_bytes()).hexdigest() != pairing['executableSha256']:
        raise ValueError('candidate-executable')
    return pin['sha256']


def capture(work, client, shaders, revision, *, candidate_artifact=None):
    report = dict(environment='linux-arm64-software-vulkan', titleQualified=False, gameplayQualified=False,
                  phase='reference-inputs', preparedClientRevision=revision, externalNetwork=False)
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
        report['phase'] = 'renderer-selection'
        selected = renderer_pair(revision, wine['archive']['sha256'])
        if candidate_artifact is not None and selected is None:
            raise ValueError('unbound-candidate')
        prepare_runtime.fetch(wine['archive'], cache)
        prepare_runtime.fetch(wine['manifest'], cache)
        prepare_runtime.prepare(wine, cache, stage/'wine')
        root = stage/'wine/rootfs'
        for name in ('work/client','work/home','work/wine','work/xdg','session','esteria-bridges'):
            (root/name).mkdir(mode=0o700, parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as signed:
            if selected is not None:
                pair, _ = selected
                for member, field in [('assets/shader-tools/shader-tools-arm64.archive', 'shaderToolsArchiveSha256'),
                                      ('assets/client-runtime/client-arm64.archive', 'previousClientArchiveSha256')]:
                    with signed.open(member) as stream:
                        if hashlib.file_digest(stream, 'sha256').hexdigest() != pair[field]:
                            raise ValueError('donor-provider-pair')
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
        executable_revision = revision
        if selected is not None:
            pair, build = selected
            if hashlib.sha256((view/PE).read_bytes()).hexdigest() != pair['previousExecutableSha256']:
                raise ValueError('donor-executable')
            report['originalArtifactSha256'] = stage_renderer(view, cache, pair, build, candidate_artifact)
            executable_revision = pair['executableRevision']
            report['clientProviderArchiveSha256'] = pair['clientArchiveSha256']
        report['clientRevision'] = executable_revision
        built = read(view/'client-build.json')
        if built['source_revision'] != executable_revision or built['architecture'] != 'ARM64':
            raise ValueError('executable-source')
        for entry in built['files']:
            name = entry['name']
            with (view/name).open('rb') as stream:
                prepare_runtime.verify_stream(stream,dict(file=name,bytes=entry['size'],sha256=entry['sha256']))
        report['clientExecutableSha256']=next(e['sha256'] for e in built['files'] if e['name']==PE)
        report['wineArchiveSha256']=wine['archive']['sha256']
        report['donorApkSha256']=apk['sha256']
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

def replay_existing(work, game, *, store=None, candidate_artifact=None, locale='enUS'):
    """Use a stopped private Java import without making a second acquisition of stock assets."""
    game = shader_generation.canonical(game)
    if store is None:
        from tools.qualify_stock_shader_corpus import prepare_tools

        source = shader_generation.read(game/'current', 65).decode('ascii').rstrip('\n')
        shader_generation.imported(game, source)
        tools, pin = prepare_tools(work/'compiler-provider')
        store = work/'prepared-shaders'
        stock_shader_generation.generate(store, game, source, tools, pin['clientRevision'], locale)
    store = shader_generation.canonical(store)
    key = shader_generation.read(store/'current', 65).decode('ascii').rstrip('\n')
    if not re.fullmatch('[a-f0-9]{64}', key):
        raise ValueError('shader-pointer')
    generation = shader_generation.canonical(store/'generations'/key)
    receipt = json.loads(shader_generation.read(generation/'receipt.json', shader_generation.MAX_TEXT))
    inputs = receipt['inputs']
    client_id = inputs['importGeneration']
    if (receipt.get('formatVersion') != 1 or receipt.get('scope') != 'local-generated-shaders-not-render-qualified' or
            inputs.get('contentProfile') != stock_shader_generation.DEFAULT_CONTENT_PROFILE or
            inputs.get('preparationHelperFiles') != stock_shader_generation.helper_files() or
            receipt.get('generation') != key or hashlib.sha256(shader_generation.encoded(inputs)).hexdigest() != key or
            inputs['toolManifestSha256'] != read(ROOT/'runtime/shaders/android-provider.lock.json')['toolManifestSha256'] or
            shader_generation.imported(game,client_id) != inputs['importMetadata'] or
            shader_generation.validate_output(generation/'shaders') != receipt['outputs']):
        raise ValueError('prepared-selection')
    result = capture(work, game/'generations'/client_id/'data', generation/'shaders',
                     inputs['clientRevision'], candidate_artifact=candidate_artifact)
    if (shader_generation.read(store/'current', 65) != (key+'\n').encode('ascii') or
            shader_generation.imported(game,client_id) != inputs['importMetadata']):
        raise ValueError('prepared-selection-changed')
    result.update(importGeneration=client_id,shaderGeneration=key)
    return result


def main():
    parser = argparse.ArgumentParser(description='Replay one stopped private Java import with the selected stock renderer.')
    parser.add_argument('--game', required=True, type=Path)
    parser.add_argument('--shader-store', type=Path, help='reuse selected complete shaders; otherwise generate privately from this import')
    parser.add_argument('--locale', default='enUS', help='shader locale when compiling privately (default enUS)')
    parser.add_argument('--candidate-artifact', type=Path, help='original Windows ARM64 build ZIP matching the selected build lock')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as tmp:
        result = replay_existing(Path(tmp), args.game, store=args.shader_store,
                                 candidate_artifact=args.candidate_artifact, locale=args.locale)
    with args.report.open('x') as out:
        json.dump(result,out,sort_keys=True,indent=2)
        out.write('\n')
    return 0 if result.get('namespaceExit') == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
