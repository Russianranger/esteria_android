#!/usr/bin/env python3
"""Download exact installed Ubuntu package sources using authenticated APT indexes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

try:
    from .record_runtime import require
except ImportError:
    from record_runtime import require


def source_selector(item):
    name, version = item['package'], item['version']
    require(re.fullmatch('[a-z0-9][a-z0-9+.-]*', name) and
            re.fullmatch('[0-9][a-zA-Z0-9.+:~_-]*', version), 'unsafe-source-selector')
    return name + '=' + version


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime', 'lock', 'ca', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    runtime = json.loads(args.runtime.read_text())
    lock = json.loads(args.lock.read_text())
    require(runtime['sourceLockSha256'] == hashlib.sha256(args.lock.read_bytes()).hexdigest(), 'source-lock-mismatch')
    selectors = sorted({source_selector(item) for item in runtime['sourcePackages']})
    require(0 < len(selectors) <= 512, 'source-package-count-limit')
    args.output.mkdir(mode=0o755)
    for selected in selectors:
        subprocess.run(['apt-get', '-y', '-o', 'Acquire::https::CaInfo=' + str(args.ca), '--download-only',
                        '--only-source', 'source', selected], cwd=args.output, check=True, timeout=900)
    files = []
    total = 0
    for path in sorted(args.output.iterdir()):
        require(path.is_file() and not path.is_symlink(), 'unexpected-source-download-entry')
        size = path.stat().st_size
        total += size
        require(0 < size <= 2 * 1024**3 and total <= 8 * 1024**3, 'source-download-size-limit')
        with path.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files.append(dict(file=path.name, bytes=size, sha256=digest))
    by_name = {item['file']: item for item in files}
    for expected in lock['mysql']['sourceArchives']:
        require(by_name.get(expected['file']) == {key: expected[key] for key in ('file', 'bytes', 'sha256')},
                'mysql-source-archive-mismatch')
    result = dict(formatVersion=1, scope='installed-ubuntu-package-corresponding-sources',
                  runtimeManifestSha256=hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
                  sourceLockSha256=runtime['sourceLockSha256'], sourcePackages=runtime['sourcePackages'],
                  files=files, fileBytes=total,
                  note='APT authenticated download selection; archive identities recorded. No source rebuild equivalence claim.')
    with (args.output / 'SOURCE-MANIFEST.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    # Retain the exact selector/recipe inputs beside the original archives.
    for source, name in ((args.runtime, 'server-runtime.json'), (args.lock, 'sources.lock.json')):
        (args.output / name).write_bytes(source.read_bytes())
    print(json.dumps(dict(sourcePackages=len(selectors), archives=len(files), bytes=total)))


if __name__ == '__main__':
    main()
