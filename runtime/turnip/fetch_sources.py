#!/usr/bin/env python3
"""Fetch exact original archives and safely unpack only locked upstream tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import ssl
import tarfile
import urllib.request


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def fetch(pin, output, context):
    require('/' not in pin['file'] and pin['file'] not in ('.', '..') and
            0 < pin['bytes'] <= 256 * 1024**2, 'source-bound')
    url = pin['url']
    require(url.startswith(('https://snapshot.debian.org/archive/', 'https://archive.mesa3d.org/',
                            'https://codeload.github.com/mesonbuild/meson/tar.gz/',
                            'https://codeload.github.com/KhronosGroup/glslang/tar.gz/',
                            'https://codeload.github.com/KhronosGroup/SPIRV-Tools/tar.gz/',
                            'https://codeload.github.com/KhronosGroup/SPIRV-Headers/tar.gz/')), 'source-origin')
    target = output / pin['file']; digest = hashlib.sha256(); count = 0
    with urllib.request.urlopen(url, timeout=120, context=context) as source, target.open('xb') as destination:
        while chunk := source.read(1024 * 1024):
            count += len(chunk); require(count <= pin['bytes'], 'source-size-limit')
            destination.write(chunk); digest.update(chunk)
    require(count == pin['bytes'] and digest.hexdigest() == pin['sha256'], 'source-identity-mismatch')
    return target


def unpack(archive, pin, target):
    # Authenticated upstream sources contain a few internal relative links.
    # Extract regular members first and create confined links only afterward.
    target.mkdir(); seen = set(); total = 0; links = []
    with tarfile.open(archive, 'r:*') as source:
        for entry in source:
            path = PurePosixPath(entry.name)
            require(path.parts and path.parts[0] == pin['prefix'] and not path.is_absolute() and
                    '..' not in path.parts and '\\' not in entry.name and not entry.islnk() and
                    (entry.isfile() or entry.isdir() or entry.issym()), 'unsafe-source-member')
            relative = PurePosixPath(*path.parts[1:])
            if str(relative) == '.':
                require(entry.isdir(), 'source-root-not-directory'); continue
            require(str(relative) not in seen, 'duplicate-source-member'); seen.add(str(relative))
            total += entry.size; require(total <= 1024**3 and len(seen) <= 100000, 'expanded-source-bound')
            destination = target.joinpath(*relative.parts)
            if entry.issym():
                link = PurePosixPath(entry.linkname)
                resolved = posixpath.normpath(str(relative.parent / link))
                require(not link.is_absolute() and '\\' not in entry.linkname and
                        resolved != '..' and not resolved.startswith('../'), 'source-link-escape')
                links.append((destination, entry.linkname)); continue
            if entry.isdir():
                destination.mkdir(parents=True, exist_ok=True); continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(entry) as content, destination.open('xb') as output:
                remaining = entry.size
                while remaining:
                    data = content.read(min(1024 * 1024, remaining)); require(data, 'truncated-source')
                    output.write(data); remaining -= len(data)
            destination.chmod(0o755 if entry.mode & 0o111 else 0o644)
    for destination, link in links:
        require(not os.path.lexists(destination), 'source-link-collision')
        destination.parent.mkdir(parents=True, exist_ok=True); destination.symlink_to(link)
    for destination, _ in links:
        require(destination.resolve().is_relative_to(target.resolve()), 'source-link-chain-escape')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', required=True); args = parser.parse_args()
    lock = json.loads(Path('/inputs/sources.lock.json').read_text())
    output = Path('/out/corresponding-source/original-archives'); output.mkdir(parents=True)
    context = ssl.create_default_context(cafile=args.ca)
    for name, pin in lock['upstream'].items():
        archive = fetch(pin, output, context); unpack(archive, pin, Path('/src') / name)
    known = json.loads(Path('/src/glslang/known_good.json').read_text())['commits']
    for name, subrepo in (('spirv-tools','KhronosGroup/SPIRV-Tools'),('spirv-headers','KhronosGroup/SPIRV-Headers')):
        require([p['commit'] for p in known if p['subrepo'] == subrepo] == [lock['upstream'][name]['revision']],
                'glslang-corresponding-source-revision-mismatch')
    for source in lock['sources']:
        for pin in source['archives']:
            fetch(pin, output, context)
    files = {}
    for path in sorted(output.iterdir()):
        with path.open('rb') as source:
            files[path.name] = dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(source, 'sha256').hexdigest())
    manifest = dict(formatVersion=1, scope='exact-upstream-and-direct-build-input-sources',
                    completeGuestRootfsSourceClosure=False, files=files)
    (output / 'SOURCE-MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')


if __name__ == '__main__':
    main()
