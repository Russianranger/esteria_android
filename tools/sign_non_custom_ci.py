#!/usr/bin/env python3
"""Use already provisioned CI secrets for the separate stock package identity.

Private inputs exist only in an exclusive external directory and are removed on
every exit. This never generates a key or substitutes a debug certificate.
"""
import argparse
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

try:
    from . import sign_android_apk as signing
except ImportError:
    import sign_android_apk as signing


MAX_PREVIOUS_APK_BYTES = 500_000_000


def fetch_previous_apk(lock, destination):
    """Fetch only the fixed official stock asset and require its complete hash.

    No key, account token or authorization header is used for this public
    download. The existing SDK continuity verifier still checks the previous
    APK's certificate, package and version before any update can be signed.
    """
    baseline = lock['lastPublished']
    if baseline is None:
        return None
    signing.require(lock['packageId'] == signing.STOCK_PACKAGE, 'stock-package-required')
    code = signing.version(baseline['versionCode'])
    destination = Path(destination)
    signing.require(not destination.exists() and not destination.is_symlink(), 'previous-apk-output-exists')
    url = ('https://github.com/Russianranger/esteria_android/releases/download/'
        f'non-custom-v0.1.0-non-custom.{code}/Esteria-Stock-3.3.5a-arm64.apk')
    request = Request(url, headers={'User-Agent': 'Esteria-stock-update-signer', 'Accept': 'application/octet-stream'})
    started = time.monotonic()
    created = False
    try:
        with urlopen(request, timeout=60) as response:
            length = response.headers.get('Content-Length', '')
            signing.require(response.getcode() == 200 and length.isascii() and length.isdecimal(),
                'previous-apk-download-response')
            expected = int(length)
            signing.require(0 < expected <= MAX_PREVIOUS_APK_BYTES, 'previous-apk-download-bound')
            digest = hashlib.sha256()
            total = 0
            with destination.open('xb') as output:
                created = True
                while block := response.read(256 * 1024):
                    total += len(block)
                    signing.require(total <= expected and time.monotonic() - started <= 600,
                        'previous-apk-download-bound')
                    output.write(block)
                    digest.update(block)
            signing.require(total == expected and digest.hexdigest() == baseline['apkSha256'],
                'previous-apk-download-identity')
        return destination
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise


def execute(args):
    required = ('ESTERIA_KEYSTORE_BASE64', 'ESTERIA_KEYSTORE_PASSWORD', 'ESTERIA_KEY_PASSWORD')
    signing.require(all(os.environ.get(name) for name in required), 'persistent-signing-secrets-not-configured')
    private = Path(os.path.abspath(args.private_directory))
    signing.require(not private.is_relative_to(signing.ROOT), 'private-input-must-be-outside-repository')
    signing.require(private.parent.is_dir() and not private.exists(), 'exclusive-private-directory-required')
    for part in (private.parent, *private.parent.parents):
        signing.require(not part.is_symlink(), 'symlink-private-parent')
    # Validate bounded secret encodings without printing their values or SDK output.
    encoded = os.environ['ESTERIA_KEYSTORE_BASE64']
    signing.require(len(encoded) <= 24 * 1024 * 1024, 'private-input-size')
    try:
        # Existing GitHub key secrets may use the original decoder's line wrapping.
        # Only ASCII base64 whitespace is ignored; all other invalid bytes fail.
        normalized = encoded.translate(str.maketrans('', '', ' \t\r\n'))
        key = base64.b64decode(normalized, validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('invalid-keystore-encoding') from None
    signing.require(0 < len(key) <= 16 * 1024 * 1024, 'private-input-size')
    lock = signing.load_lock(signing.ROOT / 'app/stock-signing.lock.json')
    signing.require(lock['packageId'] == signing.STOCK_PACKAGE, 'stock-package-required')
    private.mkdir(mode=0o700)
    try:
        previous_apk = args.previous_apk
        if previous_apk is None:
            previous_apk = fetch_previous_apk(lock, private / 'previous-stock.apk')
        paths = {name: private / name for name in ('key.jks', 'store-password', 'key-password')}
        for name, value in (('key.jks', key), ('store-password', os.environ['ESTERIA_KEYSTORE_PASSWORD'].encode()),
                            ('key-password', os.environ['ESTERIA_KEY_PASSWORD'].encode())):
            with paths[name].open('xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(value)
        return signing.sign(SimpleNamespace(apk=args.apk, output=args.output,
            build_tools=args.build_tools, lock=signing.ROOT / 'app/stock-signing.lock.json',
            version_code=args.version_code, qualification_only=False,
            previous_apk=previous_apk, initial_baseline=lock['lastPublished'] is None,
            keystore=paths['key.jks'], store_password_file=paths['store-password'],
            key_password_file=paths['key-password'], alias=os.environ.get('ESTERIA_KEY_ALIAS') or 'esteria'))
    finally:
        shutil.rmtree(private)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('apk', 'build-tools', 'private-directory', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version-code', type=int, required=True)
    parser.add_argument('--previous-apk', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), sort_keys=True))
    except (OSError, ValueError) as error:
        import re
        message = str(error) if type(error) is ValueError and re.fullmatch(r'[a-z0-9-]+', str(error)) else 'persistent-signing-failed'
        parser.exit(1, message + '\n')


if __name__ == '__main__':
    main()
