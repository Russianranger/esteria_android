"""Disposable native stock world qualification using a genuine Java import and complete selected data."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import subprocess
import tarfile
import time
import zipfile

from runtime import mysql_bootstrap as db, server_content, server_data_generation as data, server_session
from tools import qualify_packaged_server_auth as auth, qualify_stock_shader_corpus as corpus

PROFILE = 'stock-3.3.5a'
# The Android caller passes one worker. This value is part of the generation identity.
STOCK_THREADS = 1
ROOT = auth.ROOT
PACKAGE = Path('/package')
GAME = Path('/game')
OUTPUT = Path('/derived')
EVIDENCE = Path('/evidence')


def download(destination, progress, deadline):
    """Only the workflow's new staging ZIP is written; every completed piece is torrent-authenticated."""
    hashes = corpus.torrent_pieces()
    with destination.open('xb') as outfile:
        def window(offset):
            length = min(corpus.WINDOW, corpus.TOTAL - offset)
            cursor = offset
            for block in corpus.verified_slices(offset, length, hashes,
                    lambda start, end: corpus.range_bytes(start, end, deadline)):
                while block:
                    count = os.pwrite(outfile.fileno(), block, cursor)
                    if count <= 0:
                        raise IOError('short ZIP write')
                    cursor += count
                    block = block[count:]
            return length
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        try:
            futures = [pool.submit(window, offset) for offset in range(0, corpus.TOTAL, corpus.WINDOW)]
            complete = 0
            for finished in concurrent.futures.as_completed(futures):
                previous = complete
                complete += finished.result()
                if complete == corpus.TOTAL or complete // (128 << 20) != previous // (128 << 20):
                    progress('official-zip-transfer', verifiedBytes=complete,
                             acquisitionSecondsLeft=max(0, round(deadline - time.monotonic())))
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        os.fsync(outfile.fileno())
    auth.require(destination.stat().st_size == corpus.TOTAL, 'incomplete official ZIP')


def archive_identity(source):
    stat = source.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def verify_archive(source, hashes, total=corpus.TOTAL, piece=corpus.PIECE):
    corpus.require(source.is_file() and not source.is_symlink(), 'stock ZIP must be a regular file')
    identity = archive_identity(source)
    corpus.require(identity[2] == total, 'incomplete official ZIP')
    with source.open('rb') as archive:
        fetch = lambda start, end: os.pread(archive.fileno(), end - start, start)
        for _ in corpus.verified_slices(0, total, hashes, fetch, total, piece):
            pass
    corpus.require(archive_identity(source) == identity, 'stock ZIP changed during verification')
    return identity


def collector_archive(spool, progress):
    # Read-only handoff from the existing collector. The journal can reject an incomplete
    # transfer cheaply. Its counts alone never authenticate ZIP bytes across ownership.
    corpus.require(spool.is_dir() and not spool.is_symlink(), 'invalid private collector directory')
    metadata, journal = spool / 'official.torrent', spool / 'verified-pieces'
    for path in (metadata, journal):
        corpus.require(path.is_file() and not path.is_symlink(), 'missing or indirect private collector input')
    corpus.require(metadata.stat().st_size < 256 << 10, 'oversized torrent metadata')
    hashes = corpus.checked_torrent_pieces(metadata.read_bytes())
    count = len(hashes) // 20
    corpus.require(journal.stat().st_size <= count * (len(str(count)) + 1), 'oversized verified piece journal')
    lines = journal.read_bytes().splitlines(keepends=True)
    done = set()
    for line in lines:
        corpus.require(re.fullmatch(rb'(?:0|[1-9][0-9]*)\n', line) is not None, 'malformed verified piece journal')
        index = int(line)
        corpus.require(index < count and index not in done, 'invalid or duplicate verified piece index')
        done.add(index)
    complete = len(done) == count
    progress('verified-collector-ready' if complete else 'verified-collector-pending',
             verifiedPieces=len(done), requiredPieces=count)
    corpus.require(complete, 'existing collector has incomplete stock ZIP')
    return spool / 'client-texture-input.zip', hashes


def validate_fixture_directory(path):
    info = path.lstat()
    corpus.require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid() and info.st_mode & 0o077 == 0,
                   'retained import must be a private owned directory')


def private_import(scratch, source, progress):
    # Match the production ZipSource identity (canonical path, bytes and millisecond mtime),
    # then bind it to the independently authenticated original publisher bytes.
    info = source.stat()
    binding = dict(formatVersion=1, scope='verified-official-zip-import', torrentSha256=corpus.TORRENT_HASH,
                   source=str(source.resolve(strict=True)), bytes=info.st_size, modifiedMs=info.st_mtime_ns // 1_000_000)
    marker = scratch / 'qualification-source.json'
    if os.path.lexists(scratch):
        validate_fixture_directory(scratch)
        corpus.require(marker.is_file() and not marker.is_symlink() and marker.stat().st_size < 8192 and
                       auth.document(marker) == binding, 'retained import belongs to a different or unknown source')
        validate_fixture_directory(scratch / 'game')
        # GameDataImporter computes its exact remaining copy using its own authenticated source identity,
        # entry journal and current filesystem metadata under its import lock, including its 64 MiB reserve.
        progress('resume-source-bound-java-import')
        return
    unit = os.statvfs(scratch.parent).f_frsize
    with zipfile.ZipFile(source) as archive:
        files = [member.file_size for member in archive.infolist() if not member.is_dir()]
    allocated = sum((size + unit - 1) // unit * unit for size in files)
    required = allocated + (64 << 20)
    free = shutil.disk_usage(scratch.parent).free
    progress('private-import-capacity', regularEntries=len(files), unpackedBytes=sum(files),
             allocatedFileBytes=allocated, allocationUnitBytes=unit, requiredBytes=required, availableBytes=free)
    corpus.require(free >= required, 'insufficient private disk for the complete official import')
    # Publish the marker and private game store together. No interrupted Java output exists before this point.
    with tempfile.TemporaryDirectory(dir=scratch.parent) as staging:
        prepared = Path(staging) / 'fixture'
        prepared.mkdir(mode=0o700)
        (prepared / 'game').mkdir(mode=0o700)
        db.atomic_json(prepared / marker.name, binding)
        prepared.rename(scratch)
        db.sync_directory(scratch.parent)


def import_source(scratch, source, progress, spool=None, deadline=None):
    owned_download = source is None and spool is None
    identity = None
    if spool is not None:
        source, hashes = collector_archive(spool, progress)
        progress('verify-existing-collector-zip')
        identity = verify_archive(source, hashes)
        private_import(scratch, source, progress)
    else:
        scratch.mkdir(mode=0o700)
        (scratch / 'game').mkdir(mode=0o700)
    game = scratch / 'game'
    if owned_download:
        # Direct import from the complete ZIP avoids a second loose copy of every archive.
        auth.require(shutil.disk_usage(scratch).free >= corpus.TOTAL + 18000000000 + (1 << 30),
                     'insufficient disk for authentic ZIP and production import')
        source = scratch / 'official.zip'
        progress('official-zip-transfer', verifiedBytes=0)
        download(source, progress, deadline)
    progress('production-java-import')
    # Class output is operation-private. Only the source-bound production game store is reopened.
    with tempfile.TemporaryDirectory(dir=scratch) as classes:
        subprocess.run(['javac', '-d', classes, '-sourcepath', ROOT / 'core/src/main/java',
                        ROOT / 'tools/stock_world/StockWorldImport.java'], check=True)
        result = subprocess.run(['java', '-cp', classes, 'StockWorldImport', source, game],
                                check=True, stdout=subprocess.PIPE, text=True)
    if identity is not None:
        corpus.require(archive_identity(source) == identity, 'stock ZIP changed during Java import')
    current = (game / 'current').read_text().strip()
    completed = re.fullmatch(r'Imported build 12340; generation=([a-f0-9]{64}) copiedBytes=([0-9]+) reusedFiles=([0-9]+)\n', result.stdout)
    corpus.require(completed and current == completed[1], 'source-bound Java import receipt differs')
    progress('source-import-complete', generation=current, copiedBytes=int(completed[2]), reusedFiles=int(completed[3]))
    if owned_download:
        source.unlink()


def last_published_readback(root):
    signing = auth.document(root / 'app/stock-signing.lock.json')
    published = signing['lastPublished']
    version = published['versionCode']
    auth.require(type(version) is int and version > 0, 'invalid published version code')
    path = root / f'runtime/evidence/non-custom-v{version}-public-apk-readback.json'
    measured = auth.document(path)
    apks = [item for item in measured['assets'] if item['name'].endswith('.apk')]
    auth.require(len(apks) == 1 and apks[0]['sha256'] == published['apkSha256']
                 and apks[0]['completeAnonymousReadback'] is True
                 and measured['persistentCertificateSha256'] == signing['certificateSha256']
                 and measured['sdkV2AndV3SignatureVerified'] is True,
                 'published world qualification APK differs from signing ledger')
    return path


def stage(destination, readback, apk):
    archive = auth.stage(destination, apk, readback)
    provider = 'server-data-tools'
    pin = auth.document(ROOT / 'runtime/server/data-tools-provider.lock.json')['archive']
    with zipfile.ZipFile(archive) as signed:
        with signed.open('assets/server-data-tools/server-data-tools.archive') as source:
            tarball = destination / 'server-data-tools.tar.gz'
            with tarball.open('xb') as output:
                digest = auth.prepare_runtime.hash_stream(source, pin['bytes'], output)
            auth.require(digest == pin['sha256'], 'stock data tool archive differs')
        proof = json.loads(signed.read('assets/server-data-tools/provider.json'))
        auth.require(proof['requiredServerRuntimeArchiveSha256'] ==
                     auth.document(destination / 'bindings.json')['archives']['server-runtime'], 'data tool dependency differs')
        helpers = json.loads(signed.read('assets/server-data/manifest.json'))
        for name, identity in helpers['files'].items():
            auth.require(auth.identity(ROOT / 'runtime' / name) == identity and
                         signed.read('assets/server-data/' + name) == (ROOT / 'runtime' / name).read_bytes(),
                         'preparation helper differs from APK')
        with tarfile.open(tarball, 'r:gz') as tar:
            tar.extractall(destination / provider, filter='data')
        (destination / 'data-tool-selection.json').write_bytes(data.storage.encoded(proof['toolSelection']))
    stage_reader(destination.parent / 'prepared-work', archive)


def stage_reader(work, archive):
    """Stage just the checked APK reader and its exact provider selection. All paths are QA-owned."""
    work.mkdir(mode=0o700, exist_ok=True)
    approved = auth.document(ROOT / 'config/stock-prepared-data-reader.json')
    manifest_name = 'assets/server-data/manifest.json'
    with zipfile.ZipFile(archive) as signed:
        raw = signed.read(manifest_name)
        installed = hashlib.sha256(raw).hexdigest()
        auth.require(installed == approved['installedReader'] == data.installed_helper_generation() and
                     approved['outputRecipe'] == data.preparation_helper_generation(), 'APK data reader or recipe differs')
        helpers = work / 'data-helpers' / installed
        helpers.mkdir(mode=0o700, parents=True, exist_ok=True)
        def immutable(path, expected):
            if path.exists():
                auth.require(not path.is_symlink() and path.read_bytes() == expected, 'QA reader selection changed')
            else:
                with path.open('xb') as target:
                    target.write(expected)
        files = json.loads(raw)['files']
        auth.require(set(files) == set(data.PREPARATION_HELPERS) | {data.READER_LOCK}, 'incomplete signed data reader')
        for name, pin in files.items():
            payload = signed.read('assets/server-data/' + name)
            auth.require(dict(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest()) == pin and
                         (ROOT / 'runtime' / name).read_bytes() == payload, 'checkout differs from signed data reader')
            immutable(helpers / name, payload)
        proof = json.loads(signed.read('assets/server-data-tools/provider.json'))
        immutable(work / 'data-tools-selection.json', data.storage.encoded(proof['toolSelection']))


def bind_receipt(game, tools, work, evidence):
    """Independent host JVM using the pinned Android 13 JSON classes and unchanged production consumer."""
    approved = auth.document(ROOT / 'config/stock-prepared-data-reader.json')
    pins = auth.document(work / 'data-tools-selection.json')
    tool_digest = data.tools_verified(tools, pins)
    generation = (work / 'server-data/current').read_text('ascii').strip()
    auth.require(re.fullmatch(r'[a-f0-9]{64}', generation), 'invalid selected data generation')
    runtime = ROOT / 'app/src/main/java/io/github/russianranger/esteria/runtime'
    fixtures = ROOT / 'tests/fixtures/android13-json'
    lock = auth.document(ROOT / 'sources.lock.json')['sources']
    started = time.monotonic()
    with tempfile.TemporaryDirectory() as directory:
        classes = Path(directory)
        build = classes / 'BuildConfig.java'
        build.write_text('package io.github.russianranger.esteria; public final class BuildConfig {'
                         'public static final String CLIENT_REVISION="' + lock['client']['commit'] + '";}')
        subprocess.run(['javac', '-d', classes, '-sourcepath', ROOT / 'core/src/main/java',
                        *sorted((fixtures / 'aosp').glob('*.java')), *sorted((fixtures / 'support').glob('*.java')),
                        build, runtime / 'PythonReceiptJson.java', runtime / 'ServerDataBinding.java',
                        ROOT / 'tools/stock_world/StockWorldBinding.java'], check=True)
        call = subprocess.run(['java', '-cp', classes, 'io.github.russianranger.esteria.runtime.StockWorldBinding',
                               game, tools, work, approved['installedReader'], tool_digest, lock['server']['commit'],
                               approved['outputRecipe'], generation], text=True, capture_output=True)
        auth.require(call.returncode == 0, 'production ServerDataBinding rejected the staged receipt')
        result = json.loads(call.stdout)
    db.atomic_json(evidence, dict(phase='production-java-data-binding', environment='host JVM; Android 13 AOSP JSON',
                                  elapsedSeconds=round(time.monotonic()-started, 3), **result))


def selection():
    generation = data.storage.read(GAME / 'current', 66).decode().strip()
    tools = PACKAGE / 'server-data-tools'
    pins = auth.document(PACKAGE / 'data-tool-selection.json')
    inputs = dict(formatVersion=1, contentProfile=PROFILE, importGeneration=generation, locale='enUS', threads=STOCK_THREADS,
                  clientRevision=data.CLIENT_REVISION, serverRevision=data.formats.SERVER_REVISION,
                  importMetadata=data.storage.imported(GAME, generation), toolSelectionSha256=data.tools_verified(tools, pins),
                  preparationHelperGeneration=data.preparation_helper_generation())
    return generation, tools, pins, inputs


def generate():
    generation, tools, pins, inputs = selection()
    root = GAME / 'generations' / generation / 'data'
    # Require the full effective build-12340 stock MPQ set before invoking any tool.
    for member in auth.document(corpus.LOCK):
        archive = root / member['path'].removeprefix(corpus.PREFIX)
        auth.require(archive.is_file() and archive.stat().st_size == member['bytes'], 'incomplete effective stock archive set')
    started = time.monotonic()
    stages = []
    def progress(phase):
        # All stage names originate in the selected helper. Filenames, private logs and raw receipt
        # inventories stay in the disposable working directory.
        if isinstance(phase, str) and phase.startswith('extraction-') and phase not in stages:
            stages.append(phase)
            db.atomic_json(EVIDENCE / 'generation.json', dict(phase=phase, stages=stages,
                freeBytes=shutil.disk_usage(OUTPUT).free, elapsedSeconds=round(time.monotonic()-started, 2)))
    result = data.generate(OUTPUT, GAME, generation, tools, pins, 'enUS', threads=STOCK_THREADS,
                           content_profile=PROFILE, progress=progress)
    members = {row['path'].removeprefix(corpus.PREFIX) for row in auth.document(corpus.LOCK)}
    final = OUTPUT / 'generations' / result['generation']
    providers = auth.document(final / 'order.json')['providers']
    auth.require(all(row['kind'] == 'mpq' for row in providers) and {row['path'] for row in providers} == members,
                 'generated data includes an unexpected archive or loose provider')
    auth.require(result['inputs'] == inputs and result['preflight']['checks_passed'], 'qualified generated data required')
    db.atomic_json(EVIDENCE / 'generation.json', dict(phase='generated', stages=stages, generation=result['generation'],
        files=len(result['files']), bytes=sum(f['bytes'] for f in result['files'].values()),
        elapsedSeconds=round(time.monotonic()-started, 2), freeBytes=shutil.disk_usage(OUTPUT).free))


def world(package, state, database, version, uuid, record):
    _, _, _, expected_inputs = selection()
    expected_generation = hashlib.sha256(data.storage.encoded(expected_inputs)).hexdigest()
    data_root = Path('/esteria-data')
    auth.require(auth.document(data_root / 'receipt.json')['generation'] == expected_generation,
                 'mounted data generation differs from live import/tools/profile')
    binding = auth.document(EVIDENCE / 'data-binding.json')
    auth.require(binding['phase'] == 'production-java-data-binding' and binding['generation'] == expected_generation and
                 binding['outputRecipe'] == expected_inputs['preparationHelperGeneration'] and
                 binding['threads'] == expected_inputs['threads'], 'matching production Java receipt admission required')
    phases, _ = auth.selections(package)
    selected = phases[0][1]
    verified = server_content.verify(package / 'server-content', package / 'content-receipt.json',
        selected['contentReceipt']['sha256'], selected['source'], selected['sourceLockSha256'],
        auth.document(package / 'server-programs/provenance/server-modules.json'))
    programs = {}
    proof = auth.document(package / 'server-programs.json')
    for name in ('authserver', 'worldserver'):
        member = 'bin/' + name
        pin = {key: proof['requiredFiles'][member][key] for key in ('bytes', 'sha256')}
        programs[name] = dict(path=package / 'server-programs' / member, identity=pin)
    mysql = Path('/usr/bin/mysql')
    op = state.parent / 'world-operation'
    op.mkdir(mode=0o700)
    with db.option_file(state, 'esteria', db.read_secret(state / 'accounts/database-secret')) as options:
        with db.Mysql(mysql, options) as connection, db.state_lock(state) as lease:
            verify = lambda: database.verify(connection, uuid)
            prepared = server_session.prepare(verified, connection, state, version, programs=programs,
                data_generation=data_root, expected_data_inputs=expected_inputs, profile=auth.document(package / 'local-server.json'),
                mysql=mysql, expected_uuid=uuid, verify_service=verify, state_lease=lease, progress=record)
            owner = server_session.Session(prepared, connection, op, verify)
            try:
                receipt = owner.start(progress=lambda phase, process, **timing: record(phase, process=process, **timing))
                auth.require(all(receipt[k] for k in ('ownedAuthListenerVerified', 'ownedWorldListenerVerified',
                    'authChallengeProcessed', 'worldChallengeVerified', 'worldConsoleLoopVerified')),
                    'actual owned world and console readiness required')
                owner.monitor()
            finally:
                owner.close()
            record('real-worldserver-ready-and-cleanly-stopped', worldserverExecuted=True,
                   worldserverSha256=programs['worldserver']['identity']['sha256'], generation=expected_generation)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    prepare = modes.add_parser('package')
    prepare.add_argument('--output', required=True, type=Path)
    prepare.add_argument('--readback', type=Path, help='verified APK readback (defaults to the published stock signing ledger)')
    prepare.add_argument('--apk', type=Path)
    importing = modes.add_parser('import')
    importing.add_argument('--work', type=Path, required=True)
    importing.add_argument('--evidence', type=Path)
    sources = importing.add_mutually_exclusive_group(required=True)
    sources.add_argument('--source', type=Path, help='existing owner-supplied private client folder or ZIP')
    sources.add_argument('--verified-spool', type=Path, help='read the existing official ZIP, torrent and verified piece journal offline')
    sources.add_argument('--acquire-until', type=int, help='fetch a fresh official ZIP until this Unix epoch time')
    binding = modes.add_parser('bind-receipt')
    for name in ('game', 'tools', 'work', 'evidence'):
        binding.add_argument('--' + name, required=True, type=Path)
    modes.add_parser('generate')
    modes.add_parser('world')
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == 'package':
        stage(args.output, args.readback or last_published_readback(ROOT), args.apk)
    elif args.mode == 'bind-receipt':
        bind_receipt(args.game.resolve(), args.tools.resolve(), args.work.resolve(), args.evidence)
    elif args.mode == 'import':
        started = time.monotonic()
        state = {}
        def progress(phase, **details):
            state.update(phase=phase, elapsedSeconds=round(time.monotonic()-started, 2),
                         freeBytes=shutil.disk_usage(args.work.parent).free, **details)
            print(json.dumps(state, sort_keys=True), flush=True)
            if args.evidence:
                db.atomic_json(args.evidence, state)
        try:
            progress('source-disk-admission')
            deadline = None
            if args.acquire_until is not None:
                seconds = args.acquire_until - time.time()
                corpus.require(seconds > 0, 'stock ZIP acquisition budget expired')
                deadline = time.monotonic() + seconds
            import_source(args.work, args.source, progress, spool=args.verified_spool, deadline=deadline)
        except Exception as error:
            state.update(failureClass=type(error).__name__, **auth.sql.safe_failure_context(error, args.work))
            if isinstance(error, corpus.Invalid):
                state['sourceReason'] = str(error)
            if args.evidence:
                db.atomic_json(args.evidence, state)
            raise
    else:
        evidence = EVIDENCE / ('generation.json' if args.mode == 'generate' else 'world.json')
        try:
            if args.mode == 'generate':
                generate()
            else:
                auth.run(PACKAGE, Path('/work'), evidence, world_probe=world)
        except Exception as error:
            report = auth.document(evidence) if evidence.is_file() else dict(phase=args.mode)
            report.update(failureClass=type(error).__name__, **auth.sql.safe_failure_context(error, Path('/work/state')))
            db.atomic_json(evidence, report)
            raise


if __name__ == '__main__':
    main()
