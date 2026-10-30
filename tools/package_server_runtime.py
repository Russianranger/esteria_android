#!/usr/bin/env python3
"""Normalize a fresh Docker export into a verified, unqualified server guest archive.

No container, executable, database or downloaded code is run by this tool. Input
must be the dependency image, never a container that has initialized player data.
"""
import argparse
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

try:
    from . import prepare_runtime as runtime
except ImportError:
    import prepare_runtime as runtime

require = runtime.require
LIMITS = dict(entries=50000, memberBytes=512 * 1024**2, fileBytes=4 * 1024**3, pathBytes=4096)
MAX_INPUT = 6 * 1024**3
MAX_PAX = 16384
MARKER = 'etc/esteria-server-runtime.json'
# These contain container-host identities, not game configuration. An empty
# resolver deliberately requires an explicit setup/update network configuration.
PORTABLE = {'etc/hostname': b'esteria-local\n',
            'etc/hosts': b'127.0.0.1 localhost esteria-local\n::1 localhost ip6-localhost\n',
            'etc/resolv.conf': b'# Offline gameplay; setup may configure a resolver explicitly.\n',
            'etc/machine-id': b''}
EMPTY_TREES = ('dev', 'proc', 'sys', 'run', 'tmp', 'var/tmp', 'var/log', 'var/cache/apt/archives')
PRIVATE_TREES = ('var/lib/mysql', 'esteria-state', 'esteria-content', 'esteria-server')
SKIP_FILES = {'.dockerenv', 'var/lib/dbus/machine-id'}


def below(name, roots):
    return any(name.startswith(root + '/') for root in roots)


def read_json(path):
    with runtime.plain_file(path) as stream:
        raw = stream.read(runtime.MAX_METADATA + 1)
    require(len(raw) <= runtime.MAX_METADATA, 'metadata-size-limit')
    return raw, json.loads(raw)


def validate_metadata(raw, document, lock_raw, lock):
    require(document.get('formatVersion') == 1 and document.get('scope') == 'built-linux-arm64-server-dependencies'
            and document.get('architecture') == 'arm64', 'invalid-runtime-metadata')
    require(document.get('sourceLockSha256') == hashlib.sha256(lock_raw).hexdigest(), 'source-lock-mismatch')
    require(document.get('baseImage') == lock['baseImage']['reference'] and
            document.get('snapshot') == lock['snapshot']['id'] and
            document.get('expectedMysqlSqlVersion') == lock['mysql']['expectedRuntimeVersion'], 'runtime-selection-mismatch')
    for key in ('databaseInitialized', 'serverIncluded', 'serverExecuted', 'androidRuntimeQualified', 'gameLoginQualified'):
        require(document.get(key) is False, 'input-is-not-a-fresh-dependency-image:' + key)
    images = document.get('images', {})
    require(set(images) == {'mysql', 'mysqld', 'python3'}, 'missing-runtime-executables')
    components = {}
    for entry in images.values():
        require(entry['path'].startswith('/'), 'invalid-runtime-executable-path')
        path = runtime.member_path(entry['path'][1:])
        require(path not in components and type(entry['bytes']) is int and 64 <= entry['bytes'] <= LIMITS['memberBytes']
                and re.fullmatch('[0-9a-f]{64}', entry['sha256']) and entry['elfMachine'] == 183,
                'invalid-runtime-executable-identity')
        components[path] = dict(bytes=entry['bytes'], sha256=entry['sha256'], elfMachine=183, elfClass=2)
    # Bind the exact receipt bytes as well as its interpreted object.
    components[MARKER] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    return components


@contextmanager
def docker_tar(stream):
    """Accept bounded Docker PAX metadata, emit no PAX in the output archive."""
    headers = 0
    class Info(tarfile.TarInfo):
        def _proc_member(self, archive):
            nonlocal headers
            headers += 1
            require(sum(len(k) + len(v) for k, v in archive.pax_headers.items()) <= MAX_PAX, 'input-global-pax-limit')
            require(headers <= LIMITS['entries'] * 3, 'input-header-limit')
            require(self.type in (tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE, tarfile.SYMTYPE,
                                 tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE,
                                 tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME,
                                 tarfile.GNUTYPE_LONGLINK), 'unsupported-input-tar-encoding')
            if self.type in (tarfile.XHDTYPE, tarfile.XGLTYPE):
                require(0 < self.size <= MAX_PAX, 'input-pax-size-limit')
            elif self.type in (tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK):
                require(0 < self.size <= LIMITS['pathBytes'] + 1, 'input-extended-header-limit')
            return super()._proc_member(archive)

        def _proc_gnusparse_00(self, *args):
            raise ValueError('sparse-input-unsupported')

        _proc_gnusparse_01 = _proc_gnusparse_00
        _proc_gnusparse_10 = _proc_gnusparse_00

    with tarfile.open(fileobj=stream, mode='r|', tarinfo=Info) as archive:
        yield archive


def repack(source, destination):
    """Copy with bounded buffers; output graph receives a full independent audit."""
    seen, parents = {}, set()
    counts = dict(inputEntries=0, omittedEntries=0, entries=0, fileBytes=0)
    input_bytes = 0
    with docker_tar(source) as incoming, gzip.GzipFile(filename='', fileobj=destination, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as outgoing:
            for item in incoming:
                counts['inputEntries'] += 1
                require(counts['inputEntries'] <= LIMITS['entries'], 'input-entry-limit')
                if item.name in ('.', './'):
                    require(item.isdir() and '' not in seen, 'invalid-input-root')
                    seen[''] = 'directory'
                    incoming.members.clear()
                    continue
                name = runtime.member_path(item.name)
                require(name not in seen and not item.issparse() and
                        not any(key.startswith('GNU.sparse') for key in item.pax_headers), 'duplicate-or-sparse-input')
                require(0 <= item.size <= LIMITS['memberBytes'] and (item.isfile() or item.size == 0), 'input-member-size-limit')
                input_bytes += item.size
                require(input_bytes <= LIMITS['fileBytes'], 'input-file-byte-limit')
                kind = 'directory' if item.isdir() else 'file' if item.isfile() else 'link' if item.issym() or item.islnk() else 'special'
                ancestors = tuple(str(p) for p in PurePosixPath(name).parents)
                require(all(seen.get(parent) in (None, 'directory') for parent in ancestors), 'input-beneath-nondirectory')
                require(kind == 'directory' or name not in parents, 'input-nondirectory-over-parent')
                seen[name] = kind
                parents.update(ancestors)
                require(not below(name, PRIVATE_TREES), 'nonempty-private-runtime-tree:' + name)
                require(name not in PRIVATE_TREES or item.isdir(), 'private-runtime-root-is-not-directory')
                require(not name.endswith(('/.my.cnf', '/.mylogin.cnf', '/.bash_history', '/.mysql_history')),
                        'private-credential-or-history-file')
                omit = name in SKIP_FILES or below(name, EMPTY_TREES)
                if omit:
                    counts['omittedEntries'] += 1
                    incoming.members.clear()
                    continue
                require(kind != 'special', 'special-file-outside-ephemeral-tree')
                require(name not in EMPTY_TREES or item.isdir(), 'ephemeral-root-is-not-directory')
                clean = tarfile.TarInfo(name)
                clean.uid = clean.gid = clean.mtime = 0
                clean.uname = clean.gname = ''
                clean.type = item.type
                clean.mode = 0o755 if item.isdir() or item.mode & 0o111 else 0o644
                payload = None
                if name in PORTABLE:
                    require(item.isfile() or item.issym(), 'invalid-host-identity-file')
                    clean.type = tarfile.REGTYPE
                    clean.mode = 0o644
                    clean.size = len(PORTABLE[name])
                    payload = io.BytesIO(PORTABLE[name])
                elif item.issym() or item.islnk():
                    runtime.link_target(name, item.linkname, item.islnk(), LIMITS['pathBytes'])
                    clean.linkname = item.linkname
                elif item.isfile():
                    clean.size = item.size
                    payload = incoming.extractfile(item)
                try:
                    outgoing.addfile(clean, payload)
                finally:
                    if payload is not None:
                        payload.close()
                counts['entries'] += 1
                counts['fileBytes'] += clean.size
                incoming.members.clear()
            # Docker can omit mounted identity files. Always supply their stable
            # replacements so no host resolver/hostname is inherited at launch.
            for name, content in PORTABLE.items():
                if name not in seen:
                    clean = tarfile.TarInfo(name)
                    clean.mode, clean.size = 0o644, len(content)
                    outgoing.addfile(clean, io.BytesIO(content))
                    counts['entries'] += 1
                    counts['fileBytes'] += len(content)
    return counts


def package(export_path, metadata_path, lock_path, output):
    raw, document = read_json(metadata_path)
    lock_raw, lock = read_json(lock_path)
    components = validate_metadata(raw, document, lock_raw, lock)
    output = Path(os.path.abspath(output))
    runtime.directory(output.parent, create=True)
    require(not os.path.lexists(output), 'destination-exists')
    temporary = Path(tempfile.mkdtemp(prefix='.' + output.name + '.stage-', dir=output.parent))
    try:
        target = temporary / 'server-runtime-arm64.tar.gz'
        with runtime.plain_file(export_path) as source, target.open('xb') as destination:
            require(os.fstat(source.fileno()).st_size <= MAX_INPUT, 'input-export-size-limit')
            counts = repack(source, destination)
            destination.flush()
            os.fsync(destination.fileno())
        pin = dict(file=target.name, bytes=target.stat().st_size)
        with runtime.plain_file(target) as stream:
            pin['sha256'] = runtime.hash_stream(stream, pin['bytes'])
        contract = dict(markerPath=MARKER, marker=document, metadataFiles=['usr/lib/os-release'],
                        components=components, archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'], limits=LIMITS)
        with runtime.plain_file(target) as stream:
            audit = runtime.inspect_archive(stream, contract)
        require('ID=ubuntu' in audit['metadata']['usr/lib/os-release'] and
                'VERSION_ID="24.04"' in audit['metadata']['usr/lib/os-release'], 'wrong-runtime-distribution')
        receipt = dict(formatVersion=1, scope='packaged-linux-arm64-server-dependencies', archive=pin,
                       sourceLockSha256=document['sourceLockSha256'], runtimeManifestSha256=hashlib.sha256(raw).hexdigest(),
                       packagerSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                       architecture='arm64', expectedMysqlSqlVersion=document['expectedMysqlSqlVersion'],
                       archiveReadBack=True, archiveEntries=counts['entries'], archiveFileBytes=counts['fileBytes'],
                       inputEntries=counts['inputEntries'], omittedEntries=counts['omittedEntries'],
                       linkCount=audit['linkCount'], portableIdentityFiles=list(PORTABLE),
                       components=components, limits=LIMITS, sourceArchivesIncluded=False,
                       databaseInitialized=False, serverIncluded=False, serverExecuted=False,
                       androidRuntimeQualified=False, gameLoginQualified=False)
        for name, data in [('package-receipt.json', (json.dumps(receipt, indent=2) + '\n').encode()),
                           ('server-runtime.json', raw), ('sources.lock.json', lock_raw)]:
            with (temporary / name).open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        runtime.sync_directory(temporary)
        # No replacing an existing installation, even if another process wins.
        # Linux renameat2 is already required elsewhere by the package tooling.
        try:
            from .package_server_content import publish_directory
        except ImportError:
            from package_server_content import publish_directory
        publish_directory(temporary, output)
        runtime.sync_directory(output.parent)
        return receipt
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--docker-export', required=True, type=Path)
    parser.add_argument('--runtime-metadata', required=True, type=Path)
    parser.add_argument('--source-lock', type=Path, default=Path(__file__).resolve().parents[1] / 'runtime/server/sources.lock.json')
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.docker_export, args.runtime_metadata, args.source_lock, args.output), indent=2))


if __name__ == '__main__':
    main()
