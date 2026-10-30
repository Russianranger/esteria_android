#!/usr/bin/env python3
"""Retain exact Debian runtime AND Wine build-package sources from signed APT."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from record_runtime import package_inventory, source_inventory, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('runtime', 'build-packages', 'lock', 'ca', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    runtime_raw = args.runtime.read_bytes(); runtime = json.loads(runtime_raw)
    require(runtime['sourceLockSha256'] == hashlib.sha256(args.lock.read_bytes()).hexdigest(), 'source-lock-changed')
    packages = package_inventory(args.build_packages.read_text()) + runtime['packages']
    selected = source_inventory(packages)
    require(0 < len(selected) <= 512, 'source-package-count-limit')
    args.output.mkdir(mode=0o755)
    for item in selected:
        name, version = item['package'], item['version']
        require(re.fullmatch('[a-z0-9][a-z0-9+.-]*', name) and
                re.fullmatch('[0-9][a-zA-Z0-9.+:~_-]*', version), 'unsafe-source-selector')
        subprocess.run(['apt-get', '-y', '-o', 'Acquire::https::CaInfo=' + str(args.ca), '--download-only',
                        '--only-source', 'source', name + '=' + version], cwd=args.output, check=True, timeout=900)
    files = []; total = 0
    for path in sorted(args.output.iterdir()):
        require(path.is_file() and not path.is_symlink(), 'unexpected-source-entry')
        size = path.stat().st_size; total += size
        require(0 < size <= 2 * 1024**3 and total <= 8 * 1024**3, 'source-byte-limit')
        with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        files.append(dict(file=path.name, bytes=size, sha256=digest))
    result = dict(formatVersion=1, scope='installed-debian-runtime-and-wine-build-corresponding-sources',
                  sourceLockSha256=runtime['sourceLockSha256'], runtimeManifestSha256=hashlib.sha256(runtime_raw).hexdigest(),
                  sourcePackages=selected, files=files, fileBytes=total,
                  note='All installed runtime and build package source versions retained through authenticated APT; no rebuild-equivalence claim.')
    (args.output / 'SOURCE-MANIFEST.json').write_text(json.dumps(result, indent=2) + '\n')
    (args.output / 'runtime.json').write_bytes(runtime_raw)
    (args.output / 'sources.lock.json').write_bytes(args.lock.read_bytes())
    print(json.dumps(dict(sourcePackages=len(selected), archives=len(files), bytes=total)))


if __name__ == '__main__': main()
