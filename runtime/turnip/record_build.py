#!/usr/bin/env python3
"""Build and no-GPU loader evidence; hardware is never qualified by CI."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import struct
import subprocess

ALLOWED_NEEDED = {'libz.so.1', 'libzstd.so.1', 'libexpat.so.1', 'libstdc++.so.6', 'libgcc_s.so.1',
    'libm.so.6', 'libc.so.6', 'ld-linux-aarch64.so.1', 'libX11.so.6', 'libX11-xcb.so.1',
    'libxcb.so.1', 'libxcb-dri3.so.0', 'libxcb-present.so.0', 'libxcb-randr.so.0', 'libxcb-shm.so.0',
    'libxcb-xfixes.so.0', 'libxcb-sync.so.1', 'libxshmfence.so.1', 'libvulkan.so.1'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def identity(path):
    require(path.is_file() and not path.is_symlink(), 'plain-file-required')
    with path.open('rb') as source:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(source, 'sha256').hexdigest())


def notices(root):
    """Bind source-build license bytes, excluding the later integration LICENSE copy."""
    selected = root / 'notices'
    require(selected.is_dir() and not selected.is_symlink(), 'plain-notice-directory-required')
    inventory = {}; total = 0; pending = [selected]
    entries = 0
    while pending:
        for path in sorted(pending.pop().iterdir()):
            entries += 1
            require(entries <= 256 and not path.is_symlink(), 'notice-inventory-bound-or-link')
            if path.is_dir():
                pending.append(path); continue
            require(path.is_file() and 0 < path.stat().st_size <= 4 * 1024**2, 'notice-file-bound')
            pin = identity(path); total += pin['bytes']
            require(total <= 16 * 1024**2, 'notice-total-bound')
            inventory[path.relative_to(root).as_posix()] = pin
    require(inventory, 'notice-inventory-empty')
    return dict(sorted(inventory.items()))


def elf(path, shared):
    with path.open('rb') as source: head = source.read(64)
    require(len(head) == 64 and head[:6] == b'\x7fELF\x02\x01' and struct.unpack_from('<H',head,18)[0] == 183, 'not-arm64-elf')
    dynamic = subprocess.check_output(['readelf','-dW',str(path)], text=True)
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', dynamic)
    require(needed and len(needed) == len(set(needed)) and set(needed) <= ALLOWED_NEEDED, 'unexpected-needed-library')
    require(not re.search(r'\((?:RPATH|RUNPATH)\)',dynamic), 'unexpected-search-path')
    headers = subprocess.check_output(['readelf','-lW',str(path)],text=True)
    interpreter = re.findall(r'Requesting program interpreter: ([^\]]+)',headers)
    require(interpreter == ([] if shared else ['/lib/ld-linux-aarch64.so.1']), 'unexpected-interpreter')
    require(not re.search(r'GNU_STACK.*\bRWE\b',headers), 'executable-stack')
    versions = subprocess.check_output(['readelf','-VW',str(path)],text=True)
    glibc = sorted({tuple(map(int,x.split('.'))) for x in re.findall(r'Name: GLIBC_([0-9.]+)',versions)})
    cpp = sorted({tuple(map(int,x.split('.'))) for x in re.findall(r'Name: GLIBCXX_([0-9.]+)',versions)})
    require(glibc and glibc[-1] <= (2,36) and (not cpp or cpp[-1] <= (3,4,30)), 'newer-than-pinned-wine-runtime')
    return dict(**identity(path), architecture='arm64', needed=sorted(needed),
                interpreter=interpreter, maxGlibc='.'.join(map(str,glibc[-1])),
                maxGlibcxx='.'.join(map(str,cpp[-1])) if cpp else None)


def validate_no_gpu(value):
    expected = dict(formatVersion=1, scope='linux-arm64-turnip-kgsl-component-probe', icdLoaded=True,
        noKgslHostVerified=True, turnip740ShaderReadbackQualified=False, pixelsVerified=0,
        vendorId=0, deviceId=0, deviceName='', x11PresentationQualified=False, androidQualified=False, gameplayQualified=False)
    require(type(value) is dict and set(value) == set(expected) and
            all(type(value[k]) is type(v) and value[k] == v for k,v in expected.items()), 'no-gpu-receipt-overclaims-or-incomplete')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-inputs',action='store_true');parser.add_argument('--shader-header',action='store_true')
    parser.add_argument('--check-no-gpu',action='store_true');parser.add_argument('--revision');args=parser.parse_args()
    require(platform.machine() in ('aarch64','arm64'), 'native-arm64-builder-required')
    if args.shader_header:
        output = '#include <stdint.h>\n'
        for stage in ('vert','frag'):
            raw=Path('/build/probe.'+stage+'.spv').read_bytes()
            require(20 <= len(raw) <= 65536 and len(raw)%4 == 0 and raw[:4] == b'\x03\x02\x23\x07','invalid-generated-spirv')
            words=struct.unpack('<'+'I'*(len(raw)//4),raw)
            output += 'static const uint32_t probe_'+stage+'[] = {'+','.join(hex(w) for w in words)+'};\n'
        Path('/build/probe_shaders.h').write_text(output);return
    if args.check_no_gpu:
        validate_no_gpu(json.loads(Path('/out/no-gpu-check/probe.json').read_text()))
        print('TURNIP_ICD_LOAD_WITHOUT_GPU_PASS; hardware/Android/presentation false');return
    raw=Path('/inputs/sources.lock.json').read_bytes();lock=json.loads(raw)
    measured=[identity(p) for p in Path('/package-pins').iterdir()]
    installed={}
    for pin in lock['packages']:
        require(dict(bytes=pin['bytes'],sha256=pin['sha256']) in measured, 'package-hash-mismatch')
        version=subprocess.check_output(['dpkg-query','-W','-f=${Version}',pin['package']],text=True)
        require(version == pin['version'],'installed-package-version-mismatch');installed[pin['package']]=version
    if args.verify_inputs:
        print('TURNIP_PINNED_DEBIAN_INPUTS_PASS');return
    require(args.revision and re.fullmatch('[0-9a-f]{40}',args.revision),'exact-source-revision-required')
    options={p['name']:p['value'] for p in json.loads(Path('/build/mesa/meson-info/intro-buildoptions.json').read_text())}
    for name,value in {'vulkan-drivers':['freedreno'],'freedreno-kmds':['kgsl'],'platforms':['x11'],
                       'gallium-drivers':[],'llvm':'disabled','glx':'disabled','egl':'disabled'}.items():
        require(options.get(name) == value, 'unexpected-mesa-option:'+name)
    icd=Path('/out/lib/libvulkan_freedreno.so');probe=Path('/out/bin/esteria-turnip-probe')
    binaries={'lib/libvulkan_freedreno.so':elf(icd,True),'bin/esteria-turnip-probe':elf(probe,False)}
    for name in ('glslangValidator','spirv-val'):
        binaries['bin/'+name]=elf(Path('/out/bin')/name,False)
    require('libdrm.so.2' not in binaries['lib/libvulkan_freedreno.so']['needed'],'DRM-is-not-KGSL')
    Path('/out/turnip-icd.json').write_text(json.dumps(dict(file_format_version='1.0.0',ICD=dict(
        library_path=str(icd),api_version='1.3.0')),indent=2)+'\n')
    Path('/out/installed-build-packages.txt').write_text(subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\n'],text=True))
    for pin in lock['packages']:
        source=Path('/usr/share/doc')/pin['package']/'copyright'
        require(source.is_file(),'missing-package-license:'+pin['package'])
        (Path('/out/notices')/(pin['package']+'-copyright')).write_bytes(source.read_bytes())
    report=dict(formatVersion=1,scope='linux-arm64-turnip-kgsl-build-only',integrationRevision=args.revision,
        inputLockSha256=hashlib.sha256(raw).hexdigest(),runtimeArchiveSha256=lock['runtimeArchiveSha256'],
        upstream=lock['upstream'],binaries=binaries,selectedPackages=installed,mesonOptions=options,
        compiled=True,hardwareQualified=False,androidQualified=False,x11PresentationQualified=False,gameplayQualified=False,
        recipeSources={p.name:identity(p) for p in sorted(Path('/inputs').iterdir()) if p.is_file()},
        probeShaders={stage:identity(Path('/build/probe.'+stage+'.spv')) for stage in ('vert','frag')},
        notices=notices(Path('/out')), noticeInventoryScope='source-build-notices-before-integration-license')
    shader_path=Path('/out/shader-tool-check/qualification.json')
    shader_check=json.loads(shader_path.read_text())
    require(shader_check.get('scope') == 'native-linux-arm64-shader-tools-only' and shader_check.get('qualified') is True and
            all(shader_check.get(key) is True for key in ('validGlslCompiled','spirvValidated','spirvDisassembled','invalidGlslRejected','invalidSpirvRejected')) and
            all(shader_check.get(key) is False for key in ('androidQualified','gameAssetShadersQualified','gameplayQualified')), 'shader-tool-probe-required')
    report['shaderToolEvidence']=dict(**identity(shader_path), result=shader_check)
    Path('/out/turnip-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('TURNIP_ARM64_KGSL_BUILD_ONLY_PASS')


if __name__=='__main__':main()
