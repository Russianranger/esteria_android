#!/usr/bin/env python3
"""Capture checksum-pinned original build/static-library sources, without executing them."""
import argparse
import hashlib
import json
from pathlib import Path
import ssl
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', required=True)
    args = parser.parse_args()
    lock = json.loads(Path('/inputs/sources.lock.json').read_text())
    output = Path('/out/corresponding-source/original-archives')
    output.mkdir()
    context = ssl.create_default_context(cafile=args.ca)
    captured = []
    for source in lock['sources']:
        for archive in source['archives']:
            name = archive['file']
            if '/' in name or '\\' in name or name in ('.', '..') or archive['bytes'] > 256 * 1024**2:
                raise ValueError('unsafe-source-archive')
            url = archive['url']
            if not url.startswith('https://snapshot.debian.org/archive/'):
                raise ValueError('unexpected-source-url')
            digest = hashlib.sha256(); count = 0
            with urllib.request.urlopen(url, timeout=120, context=context) as response, (output / name).open('xb') as target:
                while chunk := response.read(1024 * 1024):
                    count += len(chunk)
                    if count > archive['bytes']:
                        raise ValueError('oversized-source-archive')
                    target.write(chunk); digest.update(chunk)
            if count != archive['bytes'] or digest.hexdigest() != archive['sha256']:
                raise ValueError('source-archive-hash-mismatch')
            captured.append(dict(package=source['package'], version=source['version'], file=name,
                                 bytes=count, sha256=digest.hexdigest()))
    (output / 'SOURCE-MANIFEST.json').write_text(json.dumps(dict(formatVersion=1, files=captured,
        scope='original-archives-for-locked-direct-build-and-static-link-inputs',
        completeGuestRootfsSourceClosure=False), indent=2) + '\n')
    print('GUEST_BRIDGE_SOURCE_ARCHIVES_OK', len(captured))


if __name__ == '__main__':
    main()
