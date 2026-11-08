"""Fetch only the three selected public assets, then run the original package and PE consumers."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

from tools import acquire_stock_renderer, qualify_packaged_grunt as grunt


def fetch(cache, pin):
    url = urlsplit(pin['url'])
    parts = url.path.strip('/').split('/')
    if not (url.scheme == 'https' and url.netloc == 'github.com' and len(parts) == 6 and
            parts[0] == 'Russianranger' and parts[2:4] == ['releases', 'download'] and
            parts[5] == pin['file'] and Path(pin['file']).name == pin['file']):
        raise ValueError('unexpected selected release route')
    owner, repo, _, _, tag, name = parts
    partial = cache / (name + '.partial')
    final = cache / name
    def matches():
        if partial.stat().st_size != pin['bytes']:
            return False
        with partial.open('rb') as handle:
            return hashlib.file_digest(handle, 'sha256').hexdigest() == pin['sha256']
    curl = ['curl', '--proto', '=https', '--fail', '--silent', '--show-error', '--location',
            '--retry', '3', '--retry-all-errors', '--connect-timeout', '20', '--max-time', '180']
    downloaded = subprocess.run([*curl, pin['url'], '-o', str(partial)]).returncode == 0
    if not downloaded or not matches():
        release = json.loads(subprocess.check_output(['gh', 'api', f'repos/{owner}/{repo}/releases/tags/{tag}']))
        assets = [a for a in release['assets'] if a['name'] == name and a['size'] == pin['bytes']]
        if len(assets) != 1 or release['tag_name'] != tag:
            raise ValueError('public release member selection differs')
        with partial.open('wb') as stream:
            subprocess.run(['gh', 'api', '-H', 'Accept: application/octet-stream',
                            f"repos/{owner}/{repo}/releases/assets/{int(assets[0]['id'])}"], stdout=stream, check=True)
        if not matches():
            raise ValueError('pinned public provider size or digest mismatch')
    partial.rename(final)


def main(cache, target):
    os.umask(0o077)
    cache.mkdir(mode=0o700)
    selected, pair, build = grunt.selection()
    revision = pair['executableRevision']
    name = f'client-ARM64-{revision}.zip'
    archive = dict(build['artifact'], file=name,
                   url=f'{acquire_stock_renderer.REPOSITORY}/releases/download/stock-client-arm64-{revision}/{name}')
    for pin in (selected['archive'], selected['manifest'], archive):
        fetch(cache, pin)
    grunt.stage(target, input_cache=cache)


if __name__ == '__main__':
    main(Path(sys.argv[1]), Path(sys.argv[2]))
