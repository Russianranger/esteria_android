#!/usr/bin/env python3
"""Acquire, audit and optionally stage a pinned candidate; never execute it.

Python 3.11+ on Linux. Network is used only with --download. The output is a
host-prepared guest tree, not an Android installer or a qualified game runtime.
"""
import argparse
from contextlib import contextmanager
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import stat
import struct
import tarfile
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


DEFAULT_LOCK = Path(__file__).resolve().parents[1] / 'runtime/runtime-sources.lock.json'
BUFFER = 256 * 1024
MAX_METADATA = 2 * 1024 * 1024
CRT_MODULES = ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll', 'vulkan-1.dll')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def directory(path, create=False):
    """Reject symlinks in every host parent; only create missing directories."""
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if create:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
        require(stat.S_ISDIR(current.lstat().st_mode), 'host-directory-is-not-plain')
    return path


@contextmanager
def plain_file(path):
    path = Path(path)
    directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        require(stat.S_ISREG(os.fstat(fd).st_mode), 'input-is-not-regular')
        with os.fdopen(fd, 'rb') as stream:
            fd = None
            yield stream
    finally:
        if fd is not None:
            os.close(fd)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def pin_identity(pin):
    require(type(pin.get('bytes')) is int and 0 < pin['bytes'] <= 8 * 1024**3,
            'invalid-package-size-pin')
    require(re.fullmatch('[0-9a-f]{64}', pin.get('sha256', '')), 'invalid-package-hash-pin')
    name = pin.get('file', '')
    require(name and name not in ('.', '..') and '/' not in name and '\\' not in name and
            all(ord(c) >= 32 for c in name), 'invalid-package-filename')


def hash_stream(stream, size, output=None):
    digest = hashlib.sha256()
    total = 0
    while True:
        data = stream.read(min(BUFFER, size - total + 1))
        if not data:
            break
        total += len(data)
        require(total <= size, 'package-larger-than-pin')
        digest.update(data)
        if output is not None:
            output.write(data)
    require(total == size, 'package-shorter-than-pin')
    return digest.hexdigest()


def verify_stream(stream, pin):
    pin_identity(pin)
    require(os.fstat(stream.fileno()).st_size == pin['bytes'], 'package-size-mismatch')
    require(hash_stream(stream, pin['bytes']) == pin['sha256'], 'package-hash-mismatch')


def fetch(pin, cache, *, opener=urlopen):
    """Publish only a complete exact-hash file. Existing cache data is never replaced."""
    pin_identity(pin)
    cache = directory(cache, create=True)
    target = cache / pin['file']
    if os.path.lexists(target):
        with plain_file(target) as stream:
            verify_stream(stream, pin)
        return target
    parsed = urlsplit(pin['url'])
    require(parsed.scheme == 'https' and parsed.hostname and not parsed.username and
            not parsed.password and not parsed.fragment, 'package-url-requires-https')
    fd, temporary = tempfile.mkstemp(prefix='.' + pin['file'] + '.part-', dir=cache)
    try:
        with os.fdopen(fd, 'wb') as output, opener(pin['url'], timeout=30) as response:
            require(urlsplit(response.geturl()).scheme == 'https', 'insecure-package-redirect')
            length = response.headers.get('Content-Length')
            require(length is None or int(length) == pin['bytes'], 'http-size-mismatch')
            require(hash_stream(response, pin['bytes'], output) == pin['sha256'], 'package-hash-mismatch')
            output.flush()
            os.fsync(output.fileno())
        # A concurrent winner is refused; no last-writer-wins cache replacement.
        os.link(temporary, target, follow_symlinks=False)
        sync_directory(cache)
        return target
    finally:
        os.unlink(temporary)


def member_path(value, maximum=4096):
    value = value.removeprefix('./').rstrip('/')
    require(0 < len(value.encode('utf-8')) <= maximum and not value.startswith('/') and
            all(p not in ('', '.', '..') for p in value.split('/')) and
            all(ord(c) >= 32 and c != '\\' for c in value), 'unsafe-archive-path')
    return value


def link_target(name, raw, hard, maximum):
    require(raw and len(raw.encode('utf-8')) <= maximum and
            all(ord(c) >= 32 and c != '\\' for c in raw), 'unsafe-archive-link')
    if hard:
        return member_path(raw, maximum)
    # Lexical normalization through a/../ can disagree with filesystem lookup
    # when a is itself a symlink. Leading ../ is safe because member parents
    # are proven real directories; reject the ambiguous interior form.
    seen_name = False
    for part in raw.split('/'):
        if part not in ('', '.', '..'):
            seen_name = True
        require(part != '..' or not seen_name, 'ambiguous-parent-in-link')
    target = posixpath.normpath(raw.lstrip('/') if raw.startswith('/') else
                               posixpath.join(posixpath.dirname(name), raw))
    require(target != '..' and not target.startswith('../'), 'escaping-archive-link')
    return target


def inspect_component(head, expected):
    if 'elfMachine' in expected:
        require(len(head) >= 64 and head[:6] == b'\x7fELF\x02\x01' and
                struct.unpack_from('<H', head, 18)[0] == expected['elfMachine'], 'component-elf-mismatch')
    if 'peMachine' in expected:
        require(len(head) >= 64 and head[:2] == b'MZ', 'component-pe-mismatch')
        offset = struct.unpack_from('<I', head, 60)[0]
        require(64 <= offset <= len(head) - 26 and head[offset:offset + 4] == b'PE\0\0' and
                struct.unpack_from('<H', head, offset + 4)[0] == int(expected['peMachine'], 16),
                'component-pe-mismatch')


def read_member(archive, item, output=None, capture=False):
    source = archive.extractfile(item)
    require(source is not None, 'missing-member-stream')
    digest = hashlib.sha256()
    head = bytearray()
    content = bytearray()
    total = 0
    with source:
        while True:
            block = source.read(BUFFER)
            if not block:
                break
            total += len(block)
            require(total <= item.size, 'archive-member-overrun')
            digest.update(block)
            if len(head) < 4096:
                head.extend(block[:4096 - len(head)])
            if capture:
                require(total <= MAX_METADATA, 'metadata-size-limit')
                content.extend(block)
            if output is not None:
                output.write(block)
    require(total == item.size, 'truncated-archive-member')
    return digest.hexdigest(), bytes(head), bytes(content)


@contextmanager
def bounded_tar(stream, limits):
    """Bound gzip output and GNU extended headers before tarfile allocates them.

    The pinned packer emits GNU tar. PAX and sparse encodings are unnecessary
    here and are rejected instead of allowing their metadata to override limits.
    """
    header_count = 0

    class Info(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal header_count
            header_count += 1
            require(header_count <= limits['entries'] * 3, 'archive-header-limit')
            require(self.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE,
                                  tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.GNUTYPE_LONGNAME,
                                  tarfile.GNUTYPE_LONGLINK), 'unsupported-tar-encoding')
            if self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                require(0 < self.size <= limits['pathBytes'] + 1, 'extended-header-limit')
            return super()._proc_member(archive)

    with gzip.GzipFile(fileobj=stream) as compressed:
        class Reader:
            total = 0

            def read(self, size):
                require(0 <= size <= BUFFER, 'unbounded-tar-read')
                data = compressed.read(size)
                self.total += len(data)
                require(self.total <= limits['fileBytes'] + limits['entries'] *
                        (2 * limits['pathBytes'] + 4096) + 10240, 'archive-expanded-limit')
                return data

        reader = Reader()
        with tarfile.open(fileobj=reader, mode='r|', tarinfo=Info) as archive:
            yield archive
        # Reach the gzip trailer even when tar ends before gzip's EOF. This
        # checks CRC/truncation; the compressed byte identity is checked first.
        while reader.read(BUFFER):
            pass


def inspect_archive(stream, package, root=None):
    """Stream contents; create no links until every path has been checked.

    Absolute guest symlinks are converted to equivalent relative links so the
    staged tree cannot accidentally resolve them against the host root.
    """
    limits = package['limits']
    entries = {}
    parents = set()
    links = {}
    files = {}
    selected = {}
    metadata = {}
    modules = {}
    marker = None
    count = total = 0
    capture_names = set(package.get('metadataFiles', [])) | {package['markerPath']}
    with bounded_tar(stream, limits) as archive:
        for item in archive:
            count += 1
            require(count <= limits['entries'], 'archive-entry-limit')
            if item.name in ('.', './'):
                require(item.isdir() and '' not in entries, 'invalid-archive-root')
                entries[''] = 'directory'
                archive.members.clear()
                continue
            name = member_path(item.name, limits['pathBytes'])
            require(name not in entries and not item.issparse(), 'duplicate-or-sparse-member')
            require(item.isfile() or item.isdir() or item.issym() or item.islnk(), 'special-archive-member')
            require(0 <= item.size <= limits['memberBytes'], 'archive-member-size-limit')
            require(item.isfile() or item.size == 0, 'nonfile-payload')
            total += item.size
            require(total <= limits['fileBytes'], 'archive-byte-limit')
            kind = 'file' if item.isfile() else 'directory' if item.isdir() else 'link'
            ancestors = tuple(PurePosixPath(name).parents)
            for ancestor in ancestors:
                require(entries.get(str(ancestor)) in (None, 'directory'), 'member-beneath-nondirectory')
            # Also rejects a late file/link replacing an earlier implicit directory.
            if kind != 'directory':
                require(name not in parents, 'nondirectory-over-parent')
            entries[name] = kind
            parents.update(str(parent) for parent in ancestors)
            if kind == 'link':
                links[name] = (link_target(name, item.linkname, item.islnk(), limits['pathBytes']), item.islnk())
                require(name not in capture_names and name not in package['components'], 'required-member-not-regular')
            elif item.isdir():
                require(name not in capture_names and name not in package['components'], 'required-member-not-regular')
                if root:
                    directory(root / name, create=True)
            else:
                require(name not in capture_names or item.size <= MAX_METADATA, 'metadata-size-limit')
                if root:
                    output_path = root / name
                    directory(output_path.parent, create=True)
                    with output_path.open('xb') as output:
                        digest, head, content = read_member(archive, item, output, name in capture_names)
                        output.flush()
                        os.fsync(output.fileno())
                    os.chmod(output_path, 0o700 if item.mode & 0o111 else 0o600)
                else:
                    digest, head, content = read_member(archive, item, capture=name in capture_names)
                files[name] = (item.size, digest)
                if name in package['components']:
                    expected = package['components'][name]
                    require(item.size == expected['bytes'] and digest == expected['sha256'], 'component-identity-mismatch')
                    inspect_component(head, expected)
                    selected[name] = expected
                if name == package['markerPath']:
                    marker = json.loads(content)
                elif name in capture_names:
                    metadata[name] = content.decode('utf-8')
                    if name in package.get('metadataSha256', {}):
                        require(digest == package['metadataSha256'][name], 'runtime-metadata-hash-mismatch')
                if posixpath.dirname(name) == 'opt/wine/lib/wine/aarch64-windows':
                    module = PurePosixPath(name).name.lower()
                    require(module not in modules, 'case-colliding-windows-module')
                    machine = None
                    if len(head) >= 64 and head[:2] == b'MZ':
                        offset = struct.unpack_from('<I', head, 60)[0]
                        if 64 <= offset <= len(head) - 26 and head[offset:offset + 4] == b'PE\0\0':
                            machine = hex(struct.unpack_from('<H', head, offset + 4)[0])
                    modules[module] = {'path': name, 'bytes': item.size, 'sha256': digest, 'peMachine': machine}
            # Do not retain tarfile's second unbounded copy of the member catalog.
            archive.members.clear()
    require(count == package['archiveEntries'] and total == package['archiveFileBytes'], 'archive-inventory-mismatch')
    require(marker == package['marker'], 'runtime-marker-mismatch')
    require(set(selected) == set(package['components']), 'missing-runtime-components')
    require(set(metadata) == set(package.get('metadataFiles', [])), 'missing-runtime-metadata')
    for name, (target, hard) in links.items():
        require(not hard or entries.get(target) == 'file', 'hardlink-target-not-regular')
        if root:
            output = root / name
            directory(output.parent, create=True)
            if hard:
                os.link(root / target, output, follow_symlinks=False)
            else:
                os.symlink(posixpath.relpath(target, posixpath.dirname(name) or '.'), output)
    if root:
        # Detect storage/copy failure without buffering a large file. Paths cannot
        # have link ancestors; that was checked for every member above.
        for name, (size, digest) in files.items():
            with plain_file(root / name) as source:
                require(os.fstat(source.fileno()).st_size == size and hash_stream(source, size) == digest,
                        'staged-file-verification-failed')
        for path, _, _ in os.walk(root, followlinks=False):
            sync_directory(Path(path))
    return {'entries': count, 'fileBytes': total, 'linkCount': len(links),
            'componentIdentitiesValidated': True, 'metadata': metadata,
            'windowsArm64Modules': modules,
            'runtimeDependencies': {name: modules.get(name) for name in CRT_MODULES}}


def client_imports(path, modules):
    with plain_file(path) as stream:
        value = stream.read(MAX_METADATA + 1)
    require(len(value) <= MAX_METADATA, 'client-manifest-too-large')
    manifest = json.loads(value)
    require(manifest.get('schema_version') == 1 and manifest.get('architecture') == 'ARM64' and
            manifest.get('evidence') == 'build-only', 'client-manifest-is-not-arm64-build-evidence')
    imports = sorted({name.lower() for item in manifest['files'] for name in item['imports']})
    require(len(imports) <= 1024 and all(re.fullmatch(r'[a-z0-9_.-]+\.dll', name) for name in imports),
            'invalid-client-import-name')
    return {'manifestSha256': hashlib.sha256(value).hexdigest(), 'sourceRevision': manifest['source_revision'],
            'directImportsPresentAsFiles': [name for name in imports if name in modules],
            'directImportsWithoutFiles': [name for name in imports if name not in modules],
            'note': 'File presence does not prove export compatibility. Wine API-set forwarding and delayed/dynamic imports require execution tests.'}


def receipt(package, result):
    return dict(formatVersion=1, scope='host-prepared-runtime-candidate',
                archiveSha256=package['archive']['sha256'], manifestSha256=package['manifest']['sha256'],
                packagePinSha256=hashlib.sha256(json.dumps(package, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                preparerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                sourceArchives=package['sourceArchives'],
                archiveIdentityValidated=True, **result,
                wineExecuted=False, androidRuntimeQualified=False, serverRuntimeIncluded=False,
                renderingQualified=False, audioQualified=False, gameLoginQualified=False)


def write_json(path, value):
    with path.open('x', encoding='utf-8') as output:
        json.dump(value, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())


def prepare(package, cache, stage=None, imports=None):
    cache = directory(cache)
    with plain_file(cache / package['manifest']['file']) as stream:
        verify_stream(stream, package['manifest'])
        require(package['manifest']['bytes'] <= MAX_METADATA, 'manifest-size-limit')
        stream.seek(0)
        manifest = json.load(stream)
    expected = dict(package['marker'], **{k: package['archive'][k] for k in ('file', 'bytes', 'sha256')},
                    **package.get('manifestExtra', {}))
    require(manifest == expected, 'download-manifest-mismatch')
    temporary = None
    lock_fd = None
    try:
        if stage is not None:
            stage = Path(os.path.abspath(stage))
            parent = directory(stage.parent, create=True)
            lock_fd = os.open(parent / ('.' + stage.name + '.prepare.lock'),
                              os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            require(stat.S_ISREG(os.fstat(lock_fd).st_mode), 'invalid-package-lock')
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            require(not os.path.lexists(stage), 'stage-destination-exists')
            temporary = Path(tempfile.mkdtemp(prefix='.' + stage.name + '.stage-', dir=parent))
            root = temporary / 'rootfs'
            root.mkdir(mode=0o700)
        else:
            root = None
        with plain_file(cache / package['archive']['file']) as stream:
            verify_stream(stream, package['archive'])
            before = os.fstat(stream.fileno())
            stream.seek(0)
            result = inspect_archive(stream, package, root)
            after = os.fstat(stream.fileno())
            require((before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'archive-changed-during-read')
        if imports:
            result['clientImports'] = client_imports(imports, result['windowsArm64Modules'])
        result.update(archiveExtracted=bool(root), stagedFilesReadBack=bool(root),
                      guestAbsoluteLinksRelativized=bool(root))
        report = receipt(package, result)
        if temporary:
            write_json(temporary / 'package-receipt.json', report)
            sync_directory(temporary)
            require(not os.path.lexists(stage), 'stage-destination-exists')
            os.rename(temporary, stage)
            temporary = None
            sync_directory(stage.parent)
        return report
    finally:
        if temporary is not None:
            shutil.rmtree(temporary)
        if lock_fd is not None:
            os.close(lock_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=DEFAULT_LOCK)
    parser.add_argument('--package', default='wine-arm64')
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--download', action='store_true', help='Explicitly allow setup downloads')
    parser.add_argument('--stage', type=Path, help='Publish rootfs/ and receipt in a NEW directory')
    parser.add_argument('--client-manifest', type=Path, help='Compare direct imports from an ARM64 client-build.json')
    parser.add_argument('--report', type=Path, help='Write an audit JSON to a NEW file')
    args = parser.parse_args()
    with plain_file(args.lock) as stream:
        data = stream.read(MAX_METADATA + 1)
    require(len(data) <= MAX_METADATA, 'lock-file-too-large')
    lock = json.loads(data)
    require(lock.get('formatVersion') == 1, 'unsupported-lock-version')
    package = lock['packages'][args.package]
    if args.download:
        for key in ('manifest', 'archive'):
            fetch(package[key], args.cache)
    result = prepare(package, args.cache, args.stage, args.client_manifest)
    if args.report:
        directory(args.report.parent, create=True)
        write_json(args.report, result)
    print(json.dumps({'archiveIdentityValidated': True, 'entries': result['entries'],
                      'archiveExtracted': result['archiveExtracted'], 'androidRuntimeQualified': False,
                      'runtimeDependencies': {k: bool(v) for k, v in result['runtimeDependencies'].items()}}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, EOFError, KeyError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from error
