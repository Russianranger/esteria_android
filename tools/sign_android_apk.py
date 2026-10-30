#!/usr/bin/env python3
"""Sign a fresh APK using an owner-provisioned external key; never create a key.

Linux, Python 3.11+, Android SDK build-tools 35.0.0 and JDK 17. The public pin is
reviewed separately. A signing receipt does not qualify installation/gameplay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import tempfile
import time
import zipfile

try:
    from .package_server_content import publish_directory
    from .owned_process_group import OwnedGroup
except ImportError:
    from package_server_content import publish_directory
    from owned_process_group import OwnedGroup

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'io.github.russianranger.esteria'
LOCK = ROOT / 'app/development-signing.lock.json'
MAX_VERSION = 2_100_000_000
HEX = re.compile(r'[0-9a-f]{64}')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        while block := source.read(256 * 1024):
            result.update(block)
    return result.hexdigest()


def plain(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        require(not part.is_symlink(), 'symlink-path-rejected')
    require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'regular-file-required')
    return path


def private_file(path, password=False):
    path = plain(path)
    require(not path.is_relative_to(ROOT), 'private-input-must-be-outside-repository')
    info = path.stat()
    require(info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
            'private-input-owner-or-permissions')
    require(0 < info.st_size <= (4096 if password else 16 * 1024 * 1024),
            'private-input-size')
    if password:
        value = path.read_bytes()
        line = value.removesuffix(b'\n').removesuffix(b'\r')
        require(line and b'\n' not in line and b'\r' not in line and b'\0' not in line,
                'password-must-be-one-nonempty-line')
    return path


def load_lock(path, qualification=False):
    path = plain(path)
    require(path.stat().st_size <= 16384, 'signing-lock-too-large')
    lock = json.loads(path.read_text())
    require(set(lock) == {'formatVersion', 'purpose', 'packageId', 'certificateSha256', 'lastPublished'},
            'signing-lock-fields')
    require(lock['formatVersion'] == 1 and lock['packageId'] == PACKAGE, 'signing-lock-identity')
    require(lock['purpose'] == ('qualification-only' if qualification else 'persistent-development'),
            'signing-lock-purpose')
    require(isinstance(lock['certificateSha256'], str) and HEX.fullmatch(lock['certificateSha256']),
            'certificate-not-pinned')
    baseline = lock['lastPublished']
    if baseline is not None:
        require(isinstance(baseline, dict) and set(baseline) == {'versionCode', 'apkSha256'},
                'published-baseline-fields')
        version(baseline['versionCode'])
        require(isinstance(baseline['apkSha256'], str) and HEX.fullmatch(baseline['apkSha256']),
                'published-baseline-hash')
    return lock


def version(value):
    require(type(value) is int and 0 < value <= MAX_VERSION, 'invalid-version-code')
    return value


def sdk_tools(build_tools):
    directory = Path(build_tools).resolve(strict=True)
    props = (directory / 'source.properties').read_text()
    require(re.search(r'^Pkg.Revision\s*=\s*35\.0\.0\s*$', props, re.M), 'sdk-build-tools-version')
    return {name: plain(directory / name) for name in ('apksigner', 'aapt')}


def command(arguments, operation):
    # No shell, no stdin password fallback, no password values in argv. Never
    # export arbitrary SDK diagnostics: malformed input/aliases may contain data.
    environment = dict(os.environ, LC_ALL='C', LANG='C')
    for name in ('JAVA_TOOL_OPTIONS', '_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS'):
        environment.pop(name, None)
    process = None
    group = None
    output = bytearray()
    try:
        process = subprocess.Popen([str(x) for x in arguments], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True, env=environment)
        group = OwnedGroup(process)
        counts = {'stdout': 0, 'stderr': 0}
        deadline = time.monotonic() + 180
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 'stdout')
            selector.register(process.stderr, selectors.EVENT_READ, 'stderr')
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(arguments, 180)
                for key, _ in selector.select(min(remaining, .1)):
                    block = os.read(key.fd, 65536)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    counts[key.data] += len(block)
                    require(counts[key.data] <= 1024 * 1024, operation + '-output-limit')
                    if key.data == 'stdout':
                        output.extend(block)
                group.observe()  # Keep the leader reserved until group cleanup.
        status = group.wait(max(.01, deadline - time.monotonic()))
        require(status == 0, operation + '-failed')
        return output.decode('utf-8', errors='strict')
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(operation + '-execution-failed') from None
    finally:
        try:
            if group is not None:
                group.stop(graceful_timeout=0)
        finally:
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()


def manifest(apk, tools, expected_version):
    apk = plain(apk)
    require(0 < apk.stat().st_size <= 2 * 1024**3, 'apk-size-limit')
    output = command([tools['aapt'], 'dump', 'badging', apk], 'manifest-inspection')
    matches = re.findall(r"^package: name='([^']+)' versionCode='([0-9]+)' versionName='([^']*)'.*$", output, re.M)
    require(len(matches) == 1, 'apk-package-metadata')
    package, code, name = matches[0]
    require(package == PACKAGE and version(int(code)) == version(expected_version), 'apk-package-or-version-mismatch')
    require(re.findall(r"^sdkVersion:'(\d+)'$", output, re.M) == ['26']
            and re.findall(r"^targetSdkVersion:'(\d+)'$", output, re.M) == ['35'], 'apk-sdk-levels')
    require(not re.search(r'\bsplit=', output.splitlines()[0]), 'split-apk-unsupported')
    return {'packageId': package, 'versionCode': int(code), 'versionName': name,
            'debuggable': 'application-debuggable' in output.splitlines(), 'minSdk': 26, 'targetSdk': 35}


def verify(apk, tools, lock, expected_version, qualification=False):
    result = manifest(apk, tools, expected_version)
    require(qualification or not result['debuggable'], 'debuggable-apk-not-distributable')
    output = command([tools['apksigner'], 'verify', '--verbose', '--print-certs', apk], 'signature-verification')
    certificates = re.findall(r'^Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-f]{64})$', output, re.M)
    require(certificates == [lock['certificateSha256']]
            and re.findall(r'^Number of signers: (\d+)$', output, re.M) == ['1'], 'certificate-mismatch')
    require('Verified using v2 scheme (APK Signature Scheme v2): true' in output.splitlines(),
            'apk-v2-signature-required')
    require('Verified using v3 scheme (APK Signature Scheme v3): true' in output.splitlines(),
            'apk-v3-signature-required')
    require(qualification or not re.search(r'^Signer #[0-9]+ certificate DN:.*CN=Android Debug', output, re.M),
            'debug-certificate-not-persistent-identity')
    return dict(result, certificateSha256=certificates[0], apkSha256=digest(Path(apk)),
                apkBytes=Path(apk).stat().st_size)


def payload(apk):
    """Resigning may alter signature records, never application ZIP contents."""
    result = {}
    with zipfile.ZipFile(apk) as archive:
        entries = archive.infolist()
        require(len(entries) <= 100000 and sum(x.file_size for x in entries) <= 4 * 1024**3,
                'apk-expanded-size-limit')
        seen = set()
        for entry in entries:
            require(entry.filename not in seen and not (entry.flag_bits & 1), 'apk-duplicate-or-encrypted-entry')
            seen.add(entry.filename)
            if re.fullmatch(r'META-INF/(?:MANIFEST\.MF|[^/]+\.(?:SF|RSA|DSA|EC))', entry.filename, re.I):
                continue
            hash_value = hashlib.sha256()
            with archive.open(entry) as source:
                while block := source.read(256 * 1024):
                    hash_value.update(block)
            result[entry.filename] = {'bytes': entry.file_size, 'sha256': hash_value.hexdigest(),
                                      'compression': entry.compress_type}
    return result


def continuity(lock, previous, tools, new_version, initial, qualification):
    version(new_version)
    baseline = lock['lastPublished']
    if initial:
        require(previous is None and baseline is None, 'initial-baseline-already-established')
        return None
    require(previous is not None and baseline is not None, 'previous-published-apk-required')
    old = verify(previous, tools, lock, baseline['versionCode'], qualification)
    require(old['apkSha256'] == baseline['apkSha256'], 'previous-apk-not-published-baseline')
    require(new_version > old['versionCode'], 'version-code-must-increase')
    return {'versionCode': old['versionCode'], 'apkSha256': old['apkSha256']}


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sign(args):
    output = Path(os.path.abspath(args.output))
    require(not output.exists() and not output.is_symlink(), 'output-already-exists')
    require(output.parent.is_dir(), 'output-parent-required')
    for part in (output.parent, *output.parent.parents):
        require(not part.is_symlink(), 'symlink-output-parent')
    lock = load_lock(args.lock, args.qualification_only)
    lock_hash = digest(Path(args.lock))
    tools = sdk_tools(args.build_tools)
    source = plain(args.apk)
    identity = manifest(source, tools, args.version_code)
    require(args.qualification_only or not identity['debuggable'], 'debuggable-apk-not-distributable')
    prior = continuity(lock, args.previous_apk, tools, args.version_code,
                       args.initial_baseline, args.qualification_only)
    key = private_file(args.keystore)
    store_pass = private_file(args.store_password_file, password=True)
    key_pass = private_file(args.key_password_file, password=True)
    require(not os.path.samefile(store_pass, key_pass), 'password-files-must-be-distinct')
    require(re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', args.alias), 'invalid-key-alias')
    source_hash = digest(source)
    original = payload(source)
    stage = Path(tempfile.mkdtemp(prefix='.esteria-signing-', dir=output.parent))
    try:
        signed = stage / 'esteria-development.apk'
        command([tools['apksigner'], 'sign', '--ks', key, '--ks-key-alias', args.alias,
                 '--ks-pass', 'file:' + str(store_pass), '--key-pass', 'file:' + str(key_pass),
                 '--v1-signing-enabled', 'false', '--v2-signing-enabled', 'true',
                 '--v3-signing-enabled', 'true', '--v4-signing-enabled', 'false',
                 '--debuggable-apk-permitted', str(args.qualification_only).lower(),
                 '--in', source, '--out', signed], 'apk-signing')
        checked = verify(signed, tools, lock, args.version_code, args.qualification_only)
        require(payload(signed) == original and digest(source) == source_hash, 'apk-payload-changed')
        require(digest(Path(args.lock)) == lock_hash, 'public-signing-lock-changed')
        receipt = {'formatVersion': 1, 'scope': 'apk-signature-and-update-identity',
                   'qualificationOnly': args.qualification_only,
                   'persistentSigningIdentityVerified': not args.qualification_only,
                   'inputApkSha256': source_hash, 'publicSigningLockSha256': lock_hash,
                   'previousPublished': prior, 'signedApk': checked, 'payloadPreserved': True,
                   'sdkBuildToolsVersion': '35.0.0', 'actualInstallOverQualified': False,
                   'gameplayQualified': False, 'deviceCandidateQualified': False}
        (stage / 'signing-receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
        for item in stage.iterdir():
            with item.open('rb') as file:
                os.fsync(file.fileno())
        sync_directory(stage)
        publish_directory(stage, output)
        sync_directory(output.parent)
        return receipt
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('sign', 'verify'))
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--build-tools', type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=LOCK)
    parser.add_argument('--version-code', type=int, required=True)
    parser.add_argument('--qualification-only', action='store_true', help='requires a separate test-only public lock')
    parser.add_argument('--previous-apk', type=Path)
    parser.add_argument('--initial-baseline', action='store_true')
    parser.add_argument('--keystore', type=Path)
    parser.add_argument('--store-password-file', type=Path)
    parser.add_argument('--key-password-file', type=Path)
    parser.add_argument('--alias', default='esteria')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'sign':
            require(all((args.keystore, args.store_password_file, args.key_password_file, args.output)), 'signing-inputs-required')
            result = sign(args)
        else:
            result = verify(args.apk, sdk_tools(args.build_tools), load_lock(args.lock, args.qualification_only),
                            args.version_code, args.qualification_only)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError, zipfile.BadZipFile) as error:
        # OSError may contain private paths. Only controlled ValueError messages
        # are printable; SDK/parser exceptions never expose captured diagnostics.
        message = str(error) if type(error) is ValueError and re.fullmatch(r'[a-z0-9-]+', str(error)) else 'signing-validation-failed'
        parser.exit(1, message + '\n')


if __name__ == '__main__':
    main()
