#!/usr/bin/env python3
"""Retain exact toolchain Git trees, original notices and measured source archives.

This never executes fetched source or follows .gitmodules URLs. Every gitlink
must have an explicit repository/full-revision entry in its parent's submodules
mapping. Source bytes come directly from cat-file, without Git archive or any
attribute-driven worktree conversion. Every emitted blob is checked against its
original Git object. No binary-rebuild equivalence is claimed.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import resource
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from urllib.parse import urlsplit

try:
    from owned_process_group import OwnedGroup
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.owned_process_group import OwnedGroup


MAX_SOURCES = 64
MAX_FILES = 500000
MAX_MEMBER = 512 * 1024**2
MAX_TREE = 4 * 1024**3
MAX_TOTAL_TREE = 8 * 1024**3
MAX_ARCHIVES = 4 * 1024**3
MAX_LIST = 128 * 1024**2
MAX_NOTICE = 2 * 1024**2
MAX_NOTICES = 4096
MAX_NOTICE_BYTES = 64 * 1024**2
NOTICE = re.compile(r'(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?', re.I)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def identity(path):
    with path.open('rb') as stream:
        return dict(bytes=path.stat().st_size, sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def small(path, maximum):
    require(path.stat().st_size <= maximum, 'toolchain-retained-metadata-limit')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    require(len(raw) <= maximum, 'toolchain-retained-metadata-limit')
    return raw


def relative(value):
    require(isinstance(value, str) and 0 < len(value.encode()) <= 4096 and
            str(PurePosixPath(value)) == value and not value.startswith('/') and
            '\\' not in value and all(part not in ('', '.', '..') for part in value.split('/')) and
            len(value.split('/')) <= 128 and
            all(ord(char) >= 32 and ord(char) != 127 for char in value), 'unsafe-source-path')
    return value


def selector(value, depth=0):
    require(type(value) is dict and depth <= 4, 'toolchain-source-selector')
    repository = value.get('repository', '')
    require(isinstance(repository, str) and re.fullmatch(
        r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', repository),
        'toolchain-source-repository')
    revision = value.get('revision', '')
    require(isinstance(revision, str) and re.fullmatch('[a-f0-9]{40}', revision),
            'toolchain-full-source-revision-required')
    name = value.get('name', repository.rsplit('/', 1)[1].removesuffix('.git'))
    require(isinstance(name, str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', name),
            'toolchain-source-name')
    submodules = value.get('submodules', {})
    require(type(submodules) is dict and len(submodules) <= 128, 'toolchain-submodule-map')
    children = {relative(path): selector(child, depth + 1) for path, child in submodules.items()}
    return dict(repository=repository.removesuffix('.git'), revision=revision, name=name,
                submodules=children)


def child_limit():
    # Bound any individual Git pack/temporary file without changing proxy/auth.
    _, hard = resource.getrlimit(resource.RLIMIT_FSIZE)
    limit = 3 * 1024**3 if hard == resource.RLIM_INFINITY else min(hard, 3 * 1024**3)
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def git(repository, arguments, ca, output=None, limit=1024**2, timeout=900, input_file=None):
    """Drain bounded output and reserve the leader identity through group cleanup."""
    command = ['git', '-c', 'http.sslCAInfo=' + str(ca), '-c', 'http.sslVerify=true',
               '-c', 'core.hooksPath=/dev/null', '-c', 'core.attributesFile=/dev/null',
               '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never',
               '-c', 'fetch.recurseSubmodules=false', '-c', 'submodule.recurse=false',
               '-c', 'transfer.fsckObjects=true', '-c', 'fetch.fsckObjects=true']
    if repository is not None:
        command += ['--git-dir=' + str(repository)]
    command += list(arguments)
    environment = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0',
                       GIT_TRACE='0', GIT_TRACE_CURL='0', GIT_CURL_VERBOSE='0')
    process = subprocess.Popen(command, env=environment,
                               stdin=subprocess.DEVNULL if input_file is None else input_file,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               start_new_session=True, preexec_fn=child_limit)
    owner = OwnedGroup(process)
    result = io.BytesIO() if output is None else output
    errors = []

    def drain(stream, sink, maximum):
        count = 0
        try:
            while chunk := stream.read(65536):
                count += len(chunk)
                if count > maximum:
                    if 'git-output-limit' not in errors:
                        errors.append('git-output-limit')
                    continue
                if sink is not None:
                    sink.write(chunk)
        except BaseException as error:
            errors.append(type(error).__name__)
        finally:
            stream.close()

    readers = [threading.Thread(target=drain, args=(process.stdout, result, limit), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, None, 1024**2), daemon=True)]
    for reader in readers:
        reader.start()
    code = None
    try:
        deadline = time.monotonic() + timeout
        while (code := owner.observe()) is None:
            require(not errors, 'git-command-output-failed')
            require(time.monotonic() < deadline, 'git-command-timeout')
            time.sleep(.02)
    finally:
        owner.stop(graceful_timeout=2, reap_timeout=5)
        for reader in readers:
            reader.join(5)
    require(not any(reader.is_alive() for reader in readers) and not errors,
            'git-command-output-failed')
    require(code == 0, 'git-command-failed:' + str(arguments[0]))
    return result.getvalue() if output is None else None


def fetch(source, directory, ca):
    require(not directory.exists(), 'toolchain-git-output-exists')
    template = directory.parent / 'empty-template'
    template.mkdir(exist_ok=True)
    git(None, ['init', '--quiet', '--bare', '--object-format=sha1',
               '--template=' + str(template), str(directory)], ca)
    git(directory, ['fetch', '--quiet', '--no-tags', '--depth=1', source['repository'], source['revision']], ca)
    actual = git(directory, ['rev-parse', '--verify', 'FETCH_HEAD^{commit}'], ca).decode().strip()
    require(actual == source['revision'], 'toolchain-fetched-revision-differs')


def records(stream):
    pending = bytearray()
    while chunk := stream.read(65536):
        pending.extend(chunk)
        while (end := pending.find(0)) >= 0:
            yield bytes(pending[:end])
            del pending[:end + 1]
        require(len(pending) <= 8192, 'git-tree-record-limit')
    require(not pending, 'git-tree-record-truncated')


def tree(repository, source, ca, work):
    listing = work / 'tree-list'
    with listing.open('xb') as stream:
        git(repository, ['ls-tree', '-r', '-z', '--long', source['revision']], ca,
            output=stream, limit=MAX_LIST)
    blobs = {}
    links = {}
    total = 0
    with listing.open('rb') as stream:
        for record in records(stream):
            fields, separator, raw_path = record.partition(b'\t')
            require(separator, 'git-tree-record')
            mode, kind, oid, size = fields.split()
            path = relative(raw_path.decode('utf-8'))
            require(path not in blobs and path not in links and re.fullmatch(b'[a-f0-9]{40}', oid),
                    'git-tree-duplicate-or-object')
            if mode == b'160000' and kind == b'commit':
                links[path] = oid.decode()
            else:
                require(kind == b'blob' and mode in (b'100644', b'100755', b'120000') and size.isdigit(),
                        'git-tree-entry-type')
                length = int(size)
                total += length
                require(length <= MAX_MEMBER and total <= MAX_TREE and len(blobs) < MAX_FILES,
                        'toolchain-source-tree-limit')
                blobs[path] = (mode.decode(), oid.decode(), length)
    require(blobs and set(links) == set(source['submodules']), 'unpinned-or-extra-source-gitlinks')
    require(all(links[path] == child['revision'] for path, child in source['submodules'].items()),
            'toolchain-submodule-revision-differs')
    return blobs, total


class BlobReader:
    def __init__(self, stream, size, retain=False):
        self.stream = stream
        self.remaining = size
        self.git_sha = hashlib.sha1(b'blob ' + str(size).encode() + b'\0')
        self.sha = hashlib.sha256()
        self.saved = bytearray() if retain else None

    def read(self, count=-1):
        count = self.remaining if count < 0 else min(count, self.remaining)
        data = self.stream.read(count)
        require(len(data) == count, 'toolchain-source-blob-truncated')
        self.remaining -= len(data)
        self.git_sha.update(data)
        self.sha.update(data)
        if self.saved is not None:
            self.saved.extend(data)
        return data


def snapshot(repository, source, ca, work, output, budget):
    blobs, byte_count = tree(repository, source, ca, work)
    budget['treeBytes'] += byte_count
    require(budget['treeBytes'] <= MAX_TOTAL_TREE, 'toolchain-all-source-byte-limit')
    # cat-file without --filters/--textconv returns the original Git blobs.
    # git archive also applies text/eol/ident/working-tree-encoding attributes,
    # so disabling only export-ignore/export-subst does not preserve raw bytes.
    raw_blobs = work / 'original.blobs'
    requests = work / 'blob-requests'
    ordered = sorted(blobs)
    with requests.open('xb') as stream:
        for path in ordered:
            stream.write(blobs[path][1].encode() + b'\n')
    with requests.open('rb') as incoming, raw_blobs.open('xb') as stream:
        git(repository, ['cat-file', '--batch'], ca, input_file=incoming,
            output=stream, limit=MAX_TREE + MAX_FILES * 128)
    prefix = source['name'] + '/'
    target = output / (source['name'] + '.tar.gz')
    commit = git(repository, ['cat-file', 'commit', source['revision']], ca)
    require(hashlib.sha1(b'commit ' + str(len(commit)).encode() + b'\0' + commit).hexdigest() ==
            source['revision'], 'toolchain-source-commit-object')
    root_tree = commit.split(b'\n', 1)[0]
    require(re.fullmatch(b'tree [a-f0-9]{40}', root_tree), 'toolchain-source-commit-tree')
    commit_file = output / (source['name'] + '.commit')
    commit_file.write_bytes(commit)
    retained = {}
    with raw_blobs.open('rb') as incoming, target.open('xb') as compressed:
        with gzip.GzipFile(filename='', fileobj=compressed, mode='wb', mtime=0) as zipped:
            with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                for path in ordered:
                    mode, oid, size = blobs[path]
                    require(incoming.readline(128) == f'{oid} blob {size}\n'.encode(),
                            'toolchain-source-blob-header')
                    notice = NOTICE.fullmatch(PurePosixPath(path).name) is not None
                    require(not notice or size <= MAX_NOTICE, 'toolchain-notice-size-limit')
                    info = tarfile.TarInfo(prefix + path)
                    info.mode = 0o755 if mode == '100755' else 0o644
                    info.uid = info.gid = info.mtime = 0
                    info.uname = info.gname = ''
                    if mode == '120000':
                        require(0 < size <= 4096, 'toolchain-source-symlink-target')
                        data = incoming.read(size)
                        # This is source data in a tar stream, never a host
                        # symlink. Preserve its original target bytes without
                        # resolving or extracting them.
                        require(len(data) == size and b'\0' not in data,
                                'toolchain-source-symlink-target')
                        require(hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + data).hexdigest() == oid,
                                'toolchain-source-symlink-object')
                        info.type = tarfile.SYMTYPE
                        info.linkname = data.decode('utf-8')
                        archive.addfile(info)
                    else:
                        info.size = size
                        reader = BlobReader(incoming, size, retain=notice)
                        archive.addfile(info, reader)
                        require(reader.remaining == 0 and reader.git_sha.hexdigest() == oid,
                                'toolchain-source-blob-object')
                        if notice:
                            budget['notices'] += 1
                            budget['noticeBytes'] += size
                            require(budget['notices'] <= MAX_NOTICES and budget['noticeBytes'] <= MAX_NOTICE_BYTES,
                                    'toolchain-notice-total-limit')
                            path_out = output / 'notices' / source['name'] / path
                            path_out.parent.mkdir(parents=True, exist_ok=True)
                            path_out.write_bytes(reader.saved)
                            retained[path] = dict(bytes=size, sha256=reader.sha.hexdigest())
                    require(incoming.read(1) == b'\n', 'toolchain-source-blob-terminator')
                require(incoming.read(1) == b'', 'toolchain-source-blob-trailing-data')
        compressed.flush()
        os.fsync(compressed.fileno())
    require(retained, 'toolchain-source-notices-missing')
    measured = identity(target)
    budget['archiveBytes'] += measured['bytes']
    require(budget['archiveBytes'] <= MAX_ARCHIVES, 'toolchain-source-archive-total-limit')
    return dict(repository=source['repository'], revision=source['revision'], file=target.name,
                prefix=prefix, **measured, gitBlobs=len(blobs), gitBlobBytes=byte_count,
                gitTree=root_tree[5:].decode(), commitObject=dict(file=commit_file.name, **identity(commit_file)),
                gitObjectsReadBack=True, notices=retained,
                submodules={path: dict(repository=child['repository'], revision=child['revision'],
                                      archive=child['name'] + '.tar.gz')
                            for path, child in source['submodules'].items()})


def license_pins(lock, captured):
    licenses = lock.get('licenses', {})
    require(type(licenses) is dict and len(licenses) <= 128, 'toolchain-license-pin-count')
    verified = {}
    external = []
    for name, pin in licenses.items():
        require(type(pin) is dict and type(pin.get('bytes')) is int and 0 < pin['bytes'] <= MAX_NOTICE and
                isinstance(pin.get('sha256'), str) and re.fullmatch('[a-f0-9]{64}', pin['sha256']),
                'toolchain-license-pin')
        url = urlsplit(pin.get('url', ''))
        require(url.scheme == 'https' and url.netloc == 'raw.githubusercontent.com' and
                not url.query and not url.fragment, 'toolchain-license-url')
        parts = url.path.lstrip('/').split('/', 3)
        require(len(parts) == 4 and re.fullmatch('[a-f0-9]{40}', parts[2]), 'toolchain-license-revision')
        repository = 'https://github.com/' + '/'.join(parts[:2])
        selected = next((item for item in captured if item['repository'] == repository and
                         item['revision'] == parts[2]), None)
        if selected is None:
            external_sources = [lock.get(key, {}) for key in ('fex', 'wine')]
            require(any(item.get('repository', '').removesuffix('.git') == repository and
                        item.get('revision') == parts[2] for item in external_sources),
                    'toolchain-unmatched-license-pin')
            external.append(name)
            continue
        expected = dict(bytes=pin['bytes'], sha256=pin['sha256'])
        require(selected['notices'].get(relative(parts[3])) == expected, 'toolchain-pinned-license-differs')
        verified[name] = dict(repository=repository, revision=parts[2], path=parts[3], **expected)
    return verified, external


def selected_sources(lock):
    profile = lock['toolchain']
    refs = profile.get('sourceRefs', [])
    require(type(refs) is list and 0 < len(refs) <= 16, 'toolchain-source-ref-count')
    pending = [selector(profile['recipe']), *[selector(item) for item in refs]]
    selected = []
    names = set()
    identities = set()
    while pending:
        source = pending.pop(0)
        key = (source['repository'], source['revision'])
        require(source['name'] not in names and key not in identities and len(selected) < MAX_SOURCES,
                'duplicate-or-excess-toolchain-source')
        names.add(source['name'])
        identities.add(key)
        selected.append(source)
        pending.extend(source['submodules'].values())
    return selected


def git_tree(entries):
    """Reconstruct canonical Git tree objects from archived paths/modes/blobs."""
    root = {}
    for path, value in entries.items():
        parts = relative(path).split('/')
        current = root
        for component in parts[:-1]:
            prior = current.setdefault(component, {})
            require(type(prior) is dict, 'toolchain-tree-parent-is-file')
            current = prior
        require(parts[-1] not in current, 'toolchain-tree-duplicate')
        current[parts[-1]] = value

    def digest(directory):
        ordered = sorted(directory.items(), key=lambda item: item[0].encode() +
                         (b'/' if type(item[1]) is dict else b''))
        payload = bytearray()
        for name, value in ordered:
            mode, oid = ('40000', digest(value)) if type(value) is dict else value
            payload.extend(mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(oid))
        return hashlib.sha1(b'tree ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
    return digest(root)


def verified_snapshot(source, item, output, budget):
    expected_links = {path: dict(repository=child['repository'], revision=child['revision'],
                                 archive=child['name'] + '.tar.gz')
                      for path, child in source['submodules'].items()}
    require(item.get('repository') == source['repository'] and item.get('revision') == source['revision'] and
            item.get('file') == source['name'] + '.tar.gz' and item.get('prefix') == source['name'] + '/' and
            item.get('submodules') == expected_links, 'toolchain-retained-source-selection')
    archive_pin = {key: item.get(key) for key in ('bytes', 'sha256')}
    require(type(archive_pin['bytes']) is int and 0 < archive_pin['bytes'] <= MAX_ARCHIVES and
            isinstance(archive_pin['sha256'], str) and re.fullmatch('[a-f0-9]{64}', archive_pin['sha256']),
            'toolchain-retained-archive-pin')
    archive_path = output / item['file']
    require(identity(archive_path) == archive_pin, 'toolchain-retained-archive-identity')
    commit_pin = item.get('commitObject', {})
    require(commit_pin.get('file') == source['name'] + '.commit', 'toolchain-retained-commit-file')
    commit_path = output / commit_pin['file']
    require(commit_path.stat().st_size <= 1024**2 and identity(commit_path) ==
            {key: commit_pin.get(key) for key in ('bytes', 'sha256')}, 'toolchain-retained-commit-identity')
    commit = small(commit_path, 1024**2)
    require(hashlib.sha1(b'commit ' + str(len(commit)).encode() + b'\0' + commit).hexdigest() == source['revision'],
            'toolchain-retained-commit-object')
    root_tree = commit.split(b'\n', 1)[0]
    require(re.fullmatch(b'tree [a-f0-9]{40}', root_tree) and
            root_tree[5:].decode() == item.get('gitTree'), 'toolchain-retained-root-tree')
    entries = {}
    notices = {}
    total = 0
    with archive_path.open('rb') as compressed, \
            gzip.GzipFile(fileobj=compressed, mode='rb') as uncompressed, \
            tarfile.open(fileobj=uncompressed, mode='r|', bufsize=512) as archive:
        for member in archive:
            require(member.name.startswith(item['prefix']) and not member.isdir() and not member.pax_headers and
                    member.uid == member.gid == member.mtime == 0 and member.uname == member.gname == '',
                    'toolchain-retained-tar-header')
            path = relative(member.name[len(item['prefix']):])
            require(path not in entries and path not in expected_links and len(entries) < MAX_FILES,
                    'toolchain-retained-tar-inventory')
            if member.issym():
                data = member.linkname.encode()
                require(member.size == 0 and member.mode == 0o644 and 0 < len(data) <= 4096 and
                        '\0' not in member.linkname,
                        'toolchain-retained-symlink')
                total += len(data)
                oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                entries[path] = ('120000', oid)
            else:
                require(member.isfile() and member.mode in (0o644, 0o755) and
                        0 <= member.size <= MAX_MEMBER, 'toolchain-retained-blob')
                is_notice = NOTICE.fullmatch(PurePosixPath(path).name) is not None
                require(not is_notice or member.size <= MAX_NOTICE, 'toolchain-retained-notice-limit')
                reader = BlobReader(archive.extractfile(member), member.size)
                while reader.remaining:
                    reader.read(min(reader.remaining, 131072))
                entries[path] = ('100755' if member.mode == 0o755 else '100644', reader.git_sha.hexdigest())
                total += member.size
                if is_notice:
                    notices[path] = dict(bytes=member.size, sha256=reader.sha.hexdigest())
            require(total <= MAX_TREE, 'toolchain-retained-tree-limit')
            archive.members.clear()
        padding = uncompressed.read(10241)
        require(len(padding) <= 10240 and not padding.strip(b'\0') and not uncompressed.read(1),
                'toolchain-retained-trailing-archive-content')
    require(len(entries) == item.get('gitBlobs') and total == item.get('gitBlobBytes') and
            notices and notices == item.get('notices') and item.get('gitObjectsReadBack') is True,
            'toolchain-retained-tree-inventory')
    entries.update({path: ('160000', child['revision']) for path, child in source['submodules'].items()})
    require(git_tree(entries) == item['gitTree'], 'toolchain-retained-git-tree-differs')
    budget['treeBytes'] += total
    budget['archiveBytes'] += archive_pin['bytes']
    budget['notices'] += len(notices)
    budget['noticeBytes'] += sum(pin['bytes'] for pin in notices.values())
    require(budget['treeBytes'] <= MAX_TOTAL_TREE and budget['archiveBytes'] <= MAX_ARCHIVES and
            budget['notices'] <= MAX_NOTICES and budget['noticeBytes'] <= MAX_NOTICE_BYTES,
            'toolchain-retained-total-limit')
    return {item['file'], commit_pin['file']} | {'notices/' + source['name'] + '/' + path for path in notices}


def verify_output(lock, output):
    """Read every exported source blob and bind its reconstructed tree to the lock."""
    if isinstance(lock, Path):
        lock_raw = small(lock, 1024**2)
        lock = json.loads(lock_raw)
    else:
        lock_raw = None
    require(type(lock) is dict and output.is_dir() and not output.is_symlink(), 'toolchain-retained-root')
    files = set()
    directories = set()
    physical_bytes = 0
    for path in output.rglob('*'):
        info = path.lstat()
        name = path.relative_to(output).as_posix()
        relative(name)
        if stat.S_ISDIR(info.st_mode):
            directories.add(name)
        else:
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'toolchain-retained-filesystem-type')
            physical_bytes += info.st_size
            require(info.st_size <= MAX_ARCHIVES and physical_bytes <= MAX_ARCHIVES + MAX_NOTICE_BYTES + 16 * 1024**2,
                    'toolchain-retained-filesystem-size')
            files.add(name)
        require(len(files) + len(directories) <= MAX_NOTICES * 130 + MAX_SOURCES * 2 + 2,
                'toolchain-retained-filesystem-count')
    raw = small(output / 'SOURCE-MANIFEST.json', 8 * 1024**2)
    require(0 < len(raw) <= 8 * 1024**2, 'toolchain-retained-manifest-limit')
    manifest = json.loads(raw)
    saved_lock = small(output / 'sources.lock.json', 1024**2)
    require(len(saved_lock) <= 1024**2 and json.loads(saved_lock) == lock and
            (lock_raw is None or saved_lock == lock_raw) and
            manifest.get('sourceLockSha256') == hashlib.sha256(saved_lock).hexdigest(),
            'toolchain-retained-source-lock')
    require(manifest.get('formatVersion') == 1 and
            manifest.get('scope') == 'retained-fixed-toolchain-git-trees-and-original-notices' and
            manifest.get('binaryToolchainInput') == lock['toolchain']['archive'] and
            manifest.get('allSelectedGitBlobsReadBack') is True and
            all(manifest.get(key) is False for key in ('binaryRebuildEquivalent', 'androidRuntimeQualified',
                                                      'gameplayQualified')), 'toolchain-retained-manifest-scope')
    selected = selected_sources(lock)
    sources = manifest.get('sources', [])
    require(type(sources) is list and len(sources) == len(selected), 'toolchain-retained-source-count')
    budget = dict(treeBytes=0, archiveBytes=0, notices=0, noticeBytes=0)
    expected = {'SOURCE-MANIFEST.json', 'sources.lock.json'}
    for source, item in zip(selected, sources):
        require(type(item) is dict, 'toolchain-retained-source-record')
        expected.update(verified_snapshot(source, item, output, budget))
        for path, pin in item['notices'].items():
            require(identity(output / 'notices' / source['name'] / path) == pin,
                    'toolchain-retained-notice-identity')
    verified, external = license_pins(lock, sources)
    require(manifest.get('verifiedLicensePins') == verified and
            manifest.get('externalLicensePinsNotVerifiedHere') == external and
            all(manifest.get(key) == value for key, value in budget.items()),
            'toolchain-retained-license-or-byte-inventory')
    expected_directories = {parent.as_posix() for name in expected for parent in PurePosixPath(name).parents
                            if str(parent) != '.'}
    require(files == expected and directories == expected_directories, 'toolchain-retained-extra-or-missing-file')
    return dict(sourceTrees=len(sources), originalNotices=budget['notices'], archiveBytes=budget['archiveBytes'],
                manifest=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()),
                allSelectedGitBlobsReadBack=True, binaryRebuildEquivalent=False, androidRuntimeQualified=False)


def capture(lock_path, output, ca):
    require(ca.is_file() and not ca.is_symlink(), 'toolchain-source-ca-file')
    lock_raw = lock_path.read_bytes()
    require(0 < len(lock_raw) <= 1024**2, 'toolchain-source-lock-limit')
    lock = json.loads(lock_raw)
    profile = lock['toolchain']
    selected = selected_sources(lock)
    output = output.absolute()
    require(not os.path.lexists(output), 'toolchain-source-output-exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.' + output.name + '-', dir=output.parent))
    budget = dict(treeBytes=0, archiveBytes=0, notices=0, noticeBytes=0)
    captured = []
    try:
        with tempfile.TemporaryDirectory(prefix='esteria-toolchain-git-') as raw_work:
            root = Path(raw_work)
            for index, source in enumerate(selected):
                work = root / str(index)
                work.mkdir()
                repository = work / 'source.git'
                fetch(source, repository, ca)
                captured.append(snapshot(repository, source, ca, work, stage, budget))
                shutil.rmtree(work)
        verified, external = license_pins(lock, captured)
        (stage / 'sources.lock.json').write_bytes(lock_raw)
        manifest = dict(formatVersion=1, scope='retained-fixed-toolchain-git-trees-and-original-notices',
                        sourceLockSha256=hashlib.sha256(lock_raw).hexdigest(),
                        binaryToolchainInput=profile['archive'], sources=captured,
                        verifiedLicensePins=verified, externalLicensePinsNotVerifiedHere=external,
                        limits=dict(sourceCount=MAX_SOURCES, blobsPerTree=MAX_FILES, memberBytes=MAX_MEMBER,
                                    treeBytes=MAX_TREE, allTreeBytes=MAX_TOTAL_TREE, archiveBytes=MAX_ARCHIVES),
                        **budget, allSelectedGitBlobsReadBack=True,
                        binaryRebuildEquivalent=False, androidRuntimeQualified=False, gameplayQualified=False)
        manifest_raw = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
        with (stage / 'SOURCE-MANIFEST.json').open('xb') as stream:
            stream.write(manifest_raw)
            stream.flush()
            os.fsync(stream.fileno())
        verification = verify_output(lock_path, stage)
        # The namespace reservation avoids replacing a file or empty directory
        # that another invocation created after the initial check.
        output.mkdir(mode=0o755)
        try:
            for path in stage.iterdir():
                os.rename(path, output / path.name)
        except BaseException:
            shutil.rmtree(output)
            raise
        return verification
    finally:
        shutil.rmtree(stage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lock', 'output', 'ca'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.lock, args.output, args.ca), indent=2))


if __name__ == '__main__':
    main()
