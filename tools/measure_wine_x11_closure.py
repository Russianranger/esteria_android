#!/usr/bin/env python3
"""Measure the reviewed X11 loader roster in an exact retained runtime archive.

Only the small ELF closure is materialized temporarily. A changed path roster,
alias policy, loader configuration set or dependency requires explicit review.
No guest executes and no production lock is replaced.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

try:
    from . import prepare_runtime as archives, wine_arm64_requalification as retained
    from .package_server_content import publish_directory
except ImportError:
    import prepare_runtime as archives, wine_arm64_requalification as retained
    from package_server_content import publish_directory

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / 'runtime/bridges/x11-runtime.lock.json'
# The source-built XTest input helper links libXext directly. Xtigervnc/xkbcomp
# alone do not reach it; keep this named helper dependency as an explicit root.
HELPER_LIBRARIES = ('usr/lib/aarch64-linux-gnu/libXext.so.6.4.0',)
require = archives.require


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def resolve(name, links, *, parent_only=False):
    require(archives.member_path(name) == name, 'x11-closure-unsafe-path')
    for _ in range(64):
        parts = name.split('/')
        for count in range(1, len(parts) + (0 if parent_only else 1)):
            prefix = '/'.join(parts[:count])
            if prefix in links:
                name = '/'.join([archives.link_target(prefix, links[prefix], False, 4096), *parts[count:]])
                break
        else:
            return name
    raise ValueError('x11-closure-link-cycle')


def elf_dependencies(path):
    with archives.plain_file(path) as stream:
        archives.inspect_component(stream.read(4096), dict(elfMachine=183, elfClass=2))
    result = subprocess.run(['readelf', '--wide', '--program-headers', '--dynamic', str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
    require(result.returncode == 0 and len(result.stdout) <= 2*1024**2 and not result.stderr,
            'x11-closure-readelf-failed')
    text = result.stdout.decode('ascii')
    require(not re.search(r'\((?:RPATH|RUNPATH)\)', text), 'x11-closure-unreviewed-search-path')
    needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', text)
    require(len(needed) == len(set(needed)) and all(re.fullmatch('[A-Za-z0-9_.+-]+', n) for n in needed),
            'x11-closure-needed-name')
    interpreter = re.findall(r'Requesting program interpreter: ([^\]]+)', text)
    require(interpreter in ([], ['/lib/ld-linux-aarch64.so.1']), 'x11-closure-interpreter')
    require(not re.search(r'GNU_STACK[^\n]*\bRWE\b', text), 'x11-closure-executable-stack')
    return dict(needed=sorted(needed), interpreter=interpreter)


def dependency_closure(images, links, entrypoints):
    pending = list(entrypoints); reached = set(); bindings = {}
    while pending:
        name = resolve(pending.pop(), links)
        require(name in images, 'x11-closure-missing-image:' + name)
        if name in reached: continue
        reached.add(name); row = images[name]; selected = {}
        for soname in row['needed']:
            target = resolve('usr/lib/aarch64-linux-gnu/' + soname, links)
            require(target in images, 'x11-closure-unreviewed-dependency:' + soname)
            selected[soname] = target; pending.append(target)
        for loader in row['interpreter']:
            target = resolve(loader.lstrip('/'), links)
            require(target in images, 'x11-closure-loader-not-pinned'); pending.append(target)
        bindings[name] = selected
    require(reached == set(images), 'x11-closure-roster-not-exactly-transitive:' + ','.join(sorted(set(images)-reached)))
    return bindings


def measure(package_directory, output):
    output = Path(os.path.abspath(output))
    require(not os.path.lexists(output), 'x11-closure-output-exists')
    archives.directory(output.parent)
    pin, _ = retained.pins()
    _, candidate = retained.runtime_package(archives.directory(package_directory), pin)
    selected = candidate['packages']['wine-arm64']
    reference = json.loads(retained.client.small(REFERENCE))
    old = json.loads(retained.runtime.LOCK.read_bytes())['oldProviderArchiveSha256']
    require(reference.get('formatVersion') == 1 and reference.get('scope') == 'pinned-wine-rootfs-x11-static-library-closure' and
            reference.get('runtimeArchiveSha256') == old and reference.get('inputQualified') is False and
            reference.get('androidQualified') is False and reference.get('preloadFileAbsent') is True,
            'x11-closure-reference-profile')
    required = set(reference['components']) | set(reference['loaderConfiguration'])
    require(len(reference['components']) == 49 and len(reference['symlinks']) == 44 and
            len(reference['loaderConfiguration']) == 4 and set(reference['entrypoints']) == {'usr/bin/Xtigervnc', 'usr/bin/xkbcomp'},
            'x11-closure-reviewed-roster-changed')
    with tempfile.TemporaryDirectory(prefix='.wine-x11-measure-', dir=output.parent) as temporary:
        temporary = Path(temporary); images_root = temporary/'images'; images_root.mkdir()
        links = {}; measured = {}; count = total = captured = 0; seen = set()
        with archives.plain_file(package_directory/'wine-arm64.tar.gz') as raw, archives.bounded_tar(raw, selected['limits']) as tar:
            for member in tar:
                count += 1
                if member.name in ('.', './'):
                    require(member.isdir(), 'x11-closure-archive-root'); tar.members.clear(); continue
                name = archives.member_path(member.name); require(name not in seen, 'x11-closure-duplicate-member'); seen.add(name)
                require(name != 'etc/ld.so.preload', 'x11-closure-unexpected-preload')
                total += member.size
                require(count <= selected['limits']['entries'] and 0 <= member.size <= selected['limits']['memberBytes'] and
                        total <= selected['limits']['fileBytes'], 'x11-closure-archive-bound')
                if member.issym(): links[name] = member.linkname
                if name in required:
                    require(member.isfile() and 0 < member.size <= 32*1024**2, 'x11-closure-required-image-not-regular')
                    captured += member.size; require(captured <= 128*1024**2, 'x11-closure-temporary-byte-bound')
                    target = images_root/name; target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, target.open('xb') as destination:
                        digest = archives.hash_stream(source, member.size, destination)
                    measured[name] = dict(bytes=member.size, sha256=digest)
                tar.members.clear()
        require(count == selected['archiveEntries'] and total == selected['archiveFileBytes'] and set(measured) == required,
                'x11-closure-measured-roster-missing')
        aliases = {}
        for logical, previous_target in reference['symlinks'].items():
            actual = resolve(logical, links, parent_only=True)
            require(actual in links and links[actual] == previous_target, 'x11-closure-alias-policy-changed:' + logical)
            aliases[logical] = links[actual]
        images = {name: elf_dependencies(images_root/name) for name in reference['components']}
        bindings = dependency_closure(images, links, [*reference['entrypoints'], *HELPER_LIBRARIES])
        closure = dict(formatVersion=1, scope=reference['scope'], runtimeArchiveSha256=selected['archive']['sha256'],
            entrypoints=reference['entrypoints'],
            components={name: dict(measured[name], elfMachine=183, elfClass=2) for name in sorted(images)},
            symlinks=dict(sorted(aliases.items())),
            loaderConfiguration={name: measured[name] for name in sorted(reference['loaderConfiguration'])},
            preloadFileAbsent=True, inputQualified=False, androidQualified=False)
        changed = [name for name in required if measured[name] !=
                   {k: v for k, v in (reference['components'] if name in reference['components'] else reference['loaderConfiguration'])[name].items()
                    if k in ('bytes', 'sha256')}]
        report = dict(formatVersion=1, scope='measured-static-x11-closure-only',
            runtimeArchive=pin['files']['wine-arm64.tar.gz'], referenceLock=retained.client.identity(REFERENCE),
            actualElfImages=len(images), aliasesReadBack=len(aliases), loaderConfigurationFiles=4,
            sourceBuiltXTestHelperDependencyRoots=list(HELPER_LIBRARIES),
            temporaryMaterializedBytes=captured, dependencyClosure=bindings, elfMetadata=images,
            changedIdentityPaths=sorted(changed), allNeededLibrariesAndInterpretersPinned=True,
            runtimeExpanded=False, guestExecuted=False, inputQualified=False, androidQualified=False, gameplayQualified=False)
        stage = temporary/'output'; stage.mkdir()
        (stage/'x11-runtime.proposed.lock.json').write_bytes(encoded(closure))
        report['proposedLock'] = retained.client.identity(stage/'x11-runtime.proposed.lock.json')
        (stage/'x11-closure-measurement.json').write_bytes(encoded(report))
        publish_directory(stage, output); archives.sync_directory(output.parent)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(measure(args.runtime_package, args.output), indent=2))


if __name__ == '__main__': main()
