#!/usr/bin/env python3
"""Stopped-session, resumable preparation of source-matched server data.

Raw extractors run in fresh phase directories. Completed, byte-verified phases
are reused; navigation additionally retains length-checked finished tile files.
Interrupted raw vmap output is never passed to the assembler.
The final pointer describes format-checked output, not coverage or gameplay.
No network acquisition or modification of imported client files occurs here.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import time
import uuid

try:
    from . import shader_generation as storage, extractor_order as order, server_data_preflight as formats, world_io
    from .owned_process_group import OwnedGroup
except ImportError:
    import shader_generation as storage
    import extractor_order as order
    import server_data_preflight as formats
    import world_io
    from owned_process_group import OwnedGroup

SCOPE = 'local-server-data-format-checked-not-world-qualified'
PROGRAMS = ('map_extractor', 'vmap4_extractor', 'vmap4_assembler', 'mmaps_generator')
CLIENT_REVISION = '471ee42faadf4a97a1d0a86989cf1452621f2dc5'
MMAP_CONFIG = {'bytes': 7888, 'sha256': '324479ef3821a0f9ef0c3f2d6b42c011eba1c31148eeaccd6bed3250c3d9c306'}
PROFILE = dict(classical=True, trial=False, streaming=False, directAccess=False,
               retailVirtualProviders=False, parentDataVisible=False, installDataVisible=False)
MAX_FILES, MAX_FILE, MAX_TOTAL, MAX_METADATA = 300000, 16 << 30, 96 << 30, 64 << 20
CONTENT_PROFILES = ('stock-3.3.5a', 'esteria-custom')
DEFAULT_CONTENT_PROFILE = CONTENT_PROFILES[0]
CAPABILITY = b'esteria-classical-ordered-providers-v1; archive/folder/prefix; no conversion qualification'
PREPARATION_HELPERS = ('server_data_generation.py', 'server_data_preflight.py', 'shader_generation.py',
                       'extractor_order.py', 'owned_process_group.py', 'world_io.py')
# Only this reviewed v8 six-file APK helper manifest may donate compatible work.
V8_HELPER_GENERATION = '8b50b139c4b3ee78406da672cc267eb88baef0fb508ed5e6d2d3213bb545376c'
PHASES = ('maps-dbc-cameras', 'raw-vmaps', 'assembled-vmaps', 'navigation')
MAX_ATTEMPTS = 1024


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def walk_error(error):
    raise error


def document(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate server data metadata key')
            result[key] = value
        return result
    return json.loads(_metadata_bytes(path, MAX_METADATA), object_pairs_hook=unique)


def _metadata_bytes(path, maximum):
    """Allocate the actual metadata size, never the entire configured ceiling."""
    path=storage.canonical(path,False)
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as incoming:
        before=os.fstat(incoming.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size<=maximum,'bounded regular data metadata required')
        raw=incoming.read(before.st_size+1)
        after=os.fstat(incoming.fileno())
    fields=lambda info:(info.st_dev,info.st_ino,info.st_mode,info.st_size,info.st_mtime_ns,info.st_ctime_ns)
    require(len(raw)==before.st_size and fields(before)==fields(after)==fields(path.lstat()),
            'data metadata changed during read')
    return raw


def pin(value):
    require(type(value) is dict and set(value) == {'bytes', 'sha256'} and
            type(value['bytes']) is int and 0 < value['bytes'] <= MAX_FILE and
            type(value['sha256']) is str and storage.HASH.fullmatch(value['sha256']), 'invalid data tool pin')
    return value


def preparation_helper_generation():
    """Match the APK's exact compact, ordered helper manifest generation."""
    files = {name: storage.identity(Path(__file__).resolve().parent / name, 131072)
             for name in sorted(PREPARATION_HELPERS)}
    raw = (json.dumps({'formatVersion': 1, 'files': files}, separators=(',', ':')) + '\n').encode()
    return hashlib.sha256(raw).hexdigest()


def package_selection(source, *, validate=False):
    namespace = source / formats.SERVER_NAMESPACE
    for name in source.iterdir():
        require(name.name.lower() != formats.SERVER_NAMESPACE.lower() or name.name == formats.SERVER_NAMESPACE,
                'matched server namespace capitalization differs')
    if not namespace.exists() and not namespace.is_symlink(): return None
    storage.canonical(namespace)
    require({path.name for path in namespace.iterdir()} == {formats.SERVER_MANIFEST, 'data'},
            'matched server package requires only its manifest and data directory')
    raw = storage.read(namespace / formats.SERVER_MANIFEST, 2048)
    selected = formats.parse_server_manifest(raw)
    data = storage.canonical(namespace / 'data')
    if validate: formats.check_server_package(data, selected)
    return dict(formatVersion=1, scope='user-supplied-format-checked', namespace=formats.SERVER_NAMESPACE,
        mode=selected['mode'], clientProviderOrderSha256=selected['clientProviderOrderSha256'],
        manifest=dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))


def validate_package_selection(value):
    require(type(value) is dict and set(value) == {'formatVersion', 'scope', 'namespace', 'mode',
            'clientProviderOrderSha256', 'manifest'} and type(value['formatVersion']) is int and
            value['formatVersion'] == 1 and value['scope'] == 'user-supplied-format-checked' and
            value['namespace'] == formats.SERVER_NAMESPACE and value['mode'] in ('complete', 'overlay') and
            (value['clientProviderOrderSha256'] == 'none' or
             type(value['clientProviderOrderSha256']) is str and storage.HASH.fullmatch(value['clientProviderOrderSha256'])),
            'invalid supplied server package selection')
    pin(value['manifest'])
    require(value['manifest']['bytes'] <= 2048, 'supplied server manifest size differs')
    return value


def merge_supplied(source, destination, *, cancelled=lambda: False):
    """Replace each supplied file by rename, never mutate a phase's hard link."""
    for parent, dirs, files in os.walk(source, followlinks=False, onerror=walk_error):
        require(not cancelled(), 'supplied server copy cancelled; active data preserved')
        at = Path(parent); target = destination / at.relative_to(source)
        storage.canonical(target, create=True)
        for name in dirs: storage.canonical(at / name)
        for name in files:
            require(not cancelled(), 'supplied server copy cancelled; active data preserved')
            original = storage.canonical(at / name, False)
            output = target / name; temporary = target / ('.server-input-' + uuid.uuid4().hex)
            try:
                try: os.link(original, temporary, follow_symlinks=False)
                except OSError as error:
                    if error.errno not in (errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP, errno.ENOSYS): raise
                    with original.open('rb') as incoming, temporary.open('xb') as outgoing:
                        world_io.copy_stream(incoming, outgoing, cancelled=cancelled)
                        outgoing.flush(); os.fsync(outgoing.fileno())
                    os.chmod(temporary, 0o600)
                require(not output.is_symlink() and (not output.exists() or output.is_file()),
                        'supplied server file conflicts with a non-regular destination')
                os.replace(temporary, output)
            finally:
                if temporary.exists(): temporary.unlink()


def tools_verified(root, selection):
    """Selection comes from the app's verified provider, never user game content."""
    root = storage.canonical(root)
    require(type(selection) is dict and set(selection) == {'formatVersion', 'serverRevision', 'clientRevision',
            'orderedSourceReceipt', 'files'} and type(selection['formatVersion']) is int and
            selection['formatVersion'] == 1 and selection['serverRevision'] == formats.SERVER_REVISION and
            selection['clientRevision'] == CLIENT_REVISION,
            'unsupported server data tool selection')
    pin(selection['orderedSourceReceipt'])
    expected = {'bin/' + name for name in PROGRAMS} | {'etc/mmaps-config.yaml', 'provenance/ordered-source-receipt.json'}
    require(type(selection['files']) is dict and set(selection['files']) == expected,
            'complete fixed extraction tool closure required')
    # The exact source config uses dataDir="./" and debugOutput=false. Do not
    # accept a custom absolute destination merely because it has a valid hash.
    require(selection['files']['etc/mmaps-config.yaml'] == MMAP_CONFIG,
            'source-matched relative navigation configuration required')
    require(selection['files']['provenance/ordered-source-receipt.json'] == selection['orderedSourceReceipt'],
            'ordered source receipt differs from selected tool closure')
    for name, identity in selection['files'].items():
        require(storage.identity(root / name, MAX_FILE) == pin(identity), 'selected extraction tool bytes changed')
        if name.startswith('bin/'):
            require(os.access(root / name, os.X_OK), 'extraction tool is not executable')
            with (root / name).open('rb') as source:
                header = source.read(64)
            require(len(header) == 64 and header[:7] == b'\x7fELF\x02\x01\x01' and
                    header[16:18] in (b'\x02\x00', b'\x03\x00') and header[18:20] == b'\xb7\x00' and
                    header[20:24] == b'\x01\x00\x00\x00', 'ARM64 ELF header required')
    return hashlib.sha256(storage.encoded(selection)).hexdigest()


def inventory(root):
    """Hash a completed phase once, bounded and without following links."""
    storage.canonical(root)
    rows, total, entries = {}, 0, 0
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        require(len(Path(parent).relative_to(root).parts) <= 16, 'data output depth bound')
        folded = set()
        for name in dirs + files:
            entries += 1
            require(entries <= MAX_FILES, 'data output entry bound')
            relative = (Path(parent) / name).relative_to(root).as_posix()
            order.safe(relative, 1024)
            require(name.casefold() not in folded, 'case-colliding data output')
            folded.add(name.casefold())
            storage.canonical(Path(parent) / name, directory=name in dirs)
        for name in files:
            path = Path(parent) / name
            relative = path.relative_to(root).as_posix()
            rows[relative] = storage.identity(path, MAX_FILE)
            total += rows[relative]['bytes']
            require(len(rows) <= MAX_FILES and total <= MAX_TOTAL, 'data output inventory bound')
    require(rows, 'extractor produced no data files')
    require(len(storage.encoded(rows)) <= MAX_METADATA, 'data output metadata bound')
    return rows


def clone(source, destination):
    """Private output only: prefer hard links; bounded fallback handles Android denial."""
    storage.canonical(source)
    destination.mkdir(mode=0o700)
    for parent, dirs, files in os.walk(source, followlinks=False, onerror=walk_error):
        at = Path(parent)
        target = destination / at.relative_to(source)
        for name in dirs:
            storage.canonical(at / name)
            (target / name).mkdir(mode=0o700)
        for name in files:
            original = storage.canonical(at / name, False)
            output = target / name
            try:
                os.link(original, output, follow_symlinks=False)
            except OSError as error:
                if error.errno not in (errno.EPERM, errno.EXDEV, errno.EOPNOTSUPP, errno.ENOSYS):
                    raise
                with original.open('rb') as incoming, output.open('xb') as outgoing:
                    world_io.copy_stream(incoming, outgoing)
                os.chmod(output, 0o600)


class NavigationProgress:
    """Relay only a fixed numeric native status line, never paths/child text."""
    PATTERN = re.compile(rb'([0-9]{1,3})% \[Map ([0-9]{4,5})\] Building tile \[([0-9]{2}),([0-9]{2})\]')
    def __init__(self, *, emit=lambda row: print('NAVIGATION_PROGRESS ' + json.dumps(row, separators=(',', ':')), flush=True),
                 clock=time.monotonic):
        self.pending = bytearray(); self.overflow = False
        self.emit, self.clock, self.next_report, self.reports = emit, clock, 0, 0

    def feed(self, block):
        for value in block:
            if value in (10, 13):
                if not self.overflow:
                    matched = self.PATTERN.fullmatch(self.pending)
                    if matched is not None:
                        percent, map_id, x, y = map(int, matched.groups())
                        now = self.clock()
                        if percent <= 100 and map_id <= 65535 and x <= 63 and y <= 63 and \
                                now >= self.next_report and self.reports < 8192:
                            self.emit(dict(percent=percent, map=map_id, tileX=x, tileY=y))
                            self.reports += 1; self.next_report = now + 2
                self.pending.clear(); self.overflow = False
            elif not self.overflow:
                if len(self.pending) < 256: self.pending.append(value)
                else: self.pending.clear(); self.overflow = True


def execute(command, cwd, log_path, timeout, *, cancelled=lambda: False, cache_inputs=()):
    """Actual serial child, reserved process-group identity and bounded private logs."""
    require(type(timeout) is int and 0 < timeout <= 48 * 3600, 'invalid extraction deadline')
    require(not cancelled(), 'data preparation cancelled')
    with log_path.open('x+b') as log, world_io.native_inputs(cache_inputs) as cache:
        os.chmod(log_path, 0o600)
        child = subprocess.Popen(world_io.guarded_command(command), cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1'})
        owner = OwnedGroup(child)
        navigation_progress = NavigationProgress() if Path(command[0]).name == 'mmaps_generator' else None
        os.set_blocking(child.stdout.fileno(), False)
        deadline, written, observed, tail = time.monotonic() + timeout, 0, 0, b''
        try:
            while True:
                cache.tick()
                require(not cancelled(), 'data preparation cancelled')
                require(time.monotonic() < deadline, 'data preparation deadline exceeded')
                while True:
                    try:
                        block = os.read(child.stdout.fileno(), 65536)
                    except BlockingIOError:
                        break
                    if not block:
                        break
                    if navigation_progress is not None: navigation_progress.feed(block)
                    observed += len(block)
                    keep = min(len(block), max(0, (4 << 20) - written))
                    log.write(block[:keep]); written += keep
                    tail = (tail + block[keep:])[-(256 << 10):]
                    require(not cancelled() and time.monotonic() < deadline, 'data preparation interrupted')
                status = owner.observe()
                if status is not None:
                    # Exit observed before reaping; drain the remaining bounded pipe.
                    while True:
                        try:
                            block = os.read(child.stdout.fileno(), 65536)
                        except BlockingIOError:
                            break
                        if not block:
                            break
                        if navigation_progress is not None: navigation_progress.feed(block)
                        observed += len(block)
                        keep = min(len(block), max(0, (4 << 20) - written))
                        log.write(block[:keep]); written += keep
                        tail = (tail + block[keep:])[-(256 << 10):]
                        require(not cancelled() and time.monotonic() < deadline, 'data preparation interrupted')
                    break
                time.sleep(.1)
        finally:
            try:
                owner.stop(graceful_timeout=2, reap_timeout=5)
            finally:
                child.stdout.close()
                if tail:
                    log.write(b'\n[bounded log tail]\n' + tail)
                log.flush(); os.fsync(log.fileno())
        if status == world_io.PAUSED_EXIT_CODE:
            raise world_io.PreparationPaused('Native preparation paused; completed phases retained')
        if status != 0:
            raise ValueError('extractor failed; active server data preserved; ' +
                world_io.child_failure(Path(command[0]).name, status, log))
        return {'exitStatus': status, 'logBytesObserved': observed, 'logBytesRetained': log.tell()}


def _attempts(root, name):
    """Only exact source-owned attempt names qualify for reclamation."""
    result = []
    with os.scandir(storage.canonical(root)) as entries:
        for index, entry in enumerate(entries):
            require(index < MAX_ATTEMPTS, 'extraction attempt count bound')
            suffix = entry.name.removeprefix(name + '-')
            if entry.name.startswith(name + '-') and re.fullmatch('[0-9a-f]{32}', suffix):
                result.append(storage.canonical(root / entry.name))
    return result


def _discard(path):
    """Delete a stopped private attempt, refusing links and unbounded trees."""
    storage.canonical(path)
    count = 0
    for parent, dirs, files in os.walk(path, followlinks=False, onerror=walk_error):
        require(len(Path(parent).relative_to(path).parts) <= 20, 'obsolete extraction depth bound')
        for name in dirs + files:
            count += 1
            require(count <= MAX_FILES + 32, 'obsolete extraction entry bound')
            order.safe((Path(parent) / name).relative_to(path).as_posix(), 1024)
            storage.canonical(Path(parent) / name, directory=name in dirs)
    shutil.rmtree(path)


def _phase_verified(completed, name):
    saved = document(completed / 'phase.json')
    require(type(saved) is dict and set(saved) == {'phase', 'files'} and saved['phase'] == name and
            storage.encoded(saved['files']) == storage.encoded(inventory(completed / 'data')),
            'completed extraction phase changed')
    return saved['files']


def _navigation_tiles(data, *, prune=False):
    """Native skip checks only a header; reject truncated payloads on retry.
    These files remain unqualified until the complete child exits successfully.
    """
    root = data / 'mmaps'
    if not root.exists() and not root.is_symlink(): return 0
    storage.canonical(root)
    tiles = total = 0
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            require(index < MAX_FILES, 'navigation checkpoint file bound')
            path = storage.canonical(root / entry.name, False)
            require(re.fullmatch(r'[0-9]{3,10}\.mmap|[0-9]{7,14}\.mmtile', entry.name),
                    'unexpected navigation checkpoint output')
            size = path.stat().st_size
            require(size <= MAX_FILE, 'navigation checkpoint size bound')
            total += size
            require(total <= MAX_TOTAL, 'navigation checkpoint total bound')
            try:
                if path.suffix == '.mmtile': formats.check_mmtile(path)
                else: formats.check_mmap(path)
            except ValueError:
                if prune: path.unlink()
                continue
            if path.suffix == '.mmtile': tiles += 1
    if prune: storage.sync(root)
    return tiles


def _navigation_inputs(data, maps, vmaps):
    """Compare retained inputs with byte-verified completed source phases."""
    with os.scandir(data) as entries:
        for index, entry in enumerate(entries):
            require(index < 3 and entry.name in ('maps', 'vmaps', 'mmaps'),
                    'unexpected navigation attempt content')
    for name, source in (('maps', maps / 'maps'), ('vmaps', vmaps / 'vmaps')):
        target = data / name
        if not target.exists() and not target.is_symlink(): return False
        try: actual = inventory(target)
        except ValueError as error:
            if str(error) == 'extractor produced no data files': return False
            raise
        if storage.encoded(actual) != storage.encoded(inventory(source)): return False
    return True


def _navigation_work(root, maps, vmaps):
    selected = root / 'navigation-in-progress'
    candidates = _attempts(root, 'navigation')
    if selected.exists() or selected.is_symlink(): candidates.append(storage.canonical(selected))
    usable = []
    for path in candidates:
        if not (path / 'data').exists() and not (path / 'data').is_symlink(): continue
        data = storage.canonical(path / 'data')
        if _navigation_inputs(data, maps, vmaps):
            usable.append((_navigation_tiles(data), path.stat().st_mtime_ns, path))
    chosen = max(usable, key=lambda row: (row[0], row[1]))[2] if usable else None
    # All candidates are stopped under the same exact generation/setup lock.
    for path in candidates:
        if path != chosen: _discard(path)
    if chosen is not None and chosen != selected:
        os.rename(chosen, selected); storage.sync(root)
    if chosen is None:
        selected.mkdir(mode=0o700)
        data = selected / 'data'; data.mkdir(mode=0o700)
        clone(maps / 'maps', data / 'maps')
        clone(vmaps / 'vmaps', data / 'vmaps')
    _navigation_tiles(selected / 'data', prune=True)
    return selected


def phase(root, name, action, *, progress=lambda value: None, navigation_inputs=None):
    require(name in PHASES, 'unknown extraction phase')
    completed = root / (name + '-complete')
    if completed.exists() or completed.is_symlink():
        _phase_verified(completed, name)
        progress('extraction-reused-' + name)
        world_io.phase('reused-' + name)
        return completed / 'data'
    if name == 'navigation':
        require(navigation_inputs is not None, 'verified navigation inputs required')
        working = _navigation_work(root, *navigation_inputs)
        tiles = _navigation_tiles(working / 'data')
        progress('extraction-navigation-resume-' + str(tiles) + '-tiles')
        world_io.phase('navigation-resume-' + str(tiles) + '-tiles')
    else:
        for abandoned in _attempts(root, name): _discard(abandoned)
        working = root / (name + '-' + uuid.uuid4().hex)
        working.mkdir(mode=0o700)
        (working / 'data').mkdir(mode=0o700)
    data = working / 'data'
    action(data, working)
    rows = inventory(data)
    for relative in rows:
        with (data / relative).open('rb') as source:
            os.fsync(source.fileno())
    for parent, _, _ in os.walk(data, topdown=False, onerror=walk_error):
        storage.sync(Path(parent))
    storage.atomic(working / 'phase.json', storage.encoded({'phase': name, 'files': rows}))
    os.rename(working, completed); storage.sync(root)
    return completed / 'data'


def _v8_inputs(inputs):
    return dict(inputs, preparationHelperGeneration=V8_HELPER_GENERATION)


def _v8_work(staging, work, inputs, progress):
    """Move verified phases only from the explicitly reviewed old APK key."""
    old_key = hashlib.sha256(storage.encoded(_v8_inputs(inputs))).hexdigest()
    old = staging / old_key
    if old == work or not old.exists() and not old.is_symlink(): return
    storage.canonical(old)
    marker = work / 'migrated-v8.json'
    if marker.exists() or marker.is_symlink():
        saved = document(marker)
        require(type(saved) is dict and set(saved) == {'scope', 'oldGeneration', 'newGeneration', 'orderManifest', 'orderWire'} and
                saved['scope'] == 'reviewed-v8-work-transferred' and saved['oldGeneration'] == old_key and
                saved['newGeneration'] == work.name and
                storage.identity(work / 'order.json', order.MAX_MANIFEST) == pin(saved['orderManifest']) and
                storage.identity(work / 'order.tsv', order.MAX_MANIFEST) == pin(saved['orderWire']),
                'reviewed v8 migration completion binding differs')
        # Old cleanup may stop after unlinking order metadata, or may preserve
        # unknown owner entries. The transferred validated work remains usable.
        _trim_work(old)
        return
    plan = document(old / 'order.json'); wire = order.wire(plan)
    require(plan['configuredLocale'] == inputs['locale'] and plan['profile'] == PROFILE and
            storage.read(old / 'order.tsv', order.MAX_MANIFEST) == wire,
            'reviewed v8 provider projection differs')
    if (work / 'order.json').exists() or (work / 'order.json').is_symlink():
        require(storage.encoded(document(work / 'order.json')) == storage.encoded(plan) and
                storage.read(work / 'order.tsv', order.MAX_MANIFEST) == wire,
                'reviewed v8 provider selection changed')
    else:
        storage.atomic(work / 'order.tsv', wire)
        storage.atomic(work / 'order.json', order.canonical(plan))
    for name in PHASES:
        previous, target = old / (name + '-complete'), work / (name + '-complete')
        if previous.exists() or previous.is_symlink():
            rows = _phase_verified(previous, name)
            if target.exists() or target.is_symlink():
                require(storage.encoded(_phase_verified(target, name)) == storage.encoded(rows),
                        'reviewed v8 completed phase conflicts with current work')
                _discard(previous)
            else: os.rename(previous, target)
    for candidate in _attempts(old, 'navigation'):
        target = work / candidate.name
        require(not target.exists() and not target.is_symlink(), 'reviewed v8 navigation attempt conflicts')
        os.rename(candidate, target)
    storage.sync(old); storage.sync(work)
    storage.atomic(marker, storage.encoded(dict(scope='reviewed-v8-work-transferred', oldGeneration=old_key,
        newGeneration=work.name, orderManifest=storage.identity(work / 'order.json', order.MAX_MANIFEST),
        orderWire=storage.identity(work / 'order.tsv', order.MAX_MANIFEST))))
    progress('extraction-resumed-reviewed-v8-work')
    world_io.phase('resumed-reviewed-v8-work')
    _trim_work(old)


def _trim_work(root):
    """Reclaim recognized obsolete work; preserve unrecognized entries."""
    for name in PHASES:
        for path in _attempts(root, name): _discard(path)
        for suffix in ('-complete', '-in-progress'):
            path = root / (name + suffix)
            if path.exists() or path.is_symlink(): _discard(path)
    for path in _attempts(root, 'final'): _discard(path)
    names = []
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            require(index < MAX_ATTEMPTS, 'extraction metadata entry bound')
            names.append(entry.name)
    for name in names:
        if name in ('order.json', 'order.tsv', 'migrated-v8.json') or re.fullmatch(r'capability-(map_extractor|vmap4_extractor)-[0-9a-f]{32}\.log', name):
            storage.canonical(root / name, False).unlink()
    if not any(root.iterdir()): root.rmdir()


def _remove_empty(path):
    try: path.rmdir()
    except OSError as error:
        if error.errno not in (errno.ENOTEMPTY, errno.EEXIST): raise


def _retire_v8_generation(previous, receipt):
    """Reclaim only the promoted generation's known old data/metadata paths.

    Unknown root entries or newly added nested files are preserved. Cached v9
    retries can finish known-path cleanup even after the old receipt was removed.
    """
    previous = storage.canonical(previous)
    expected = receipt['files']; names = sorted(expected)
    require(len(names) <= MAX_FILES, 'obsolete generation file bound')
    root = previous / 'data'
    if root.exists() and stat.S_ISDIR(root.lstat().st_mode):
        storage.canonical(root)
        directories = []; count = 0
        for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            at = Path(parent); directories.append(at)
            require(len(at.relative_to(root).parts) <= 16, 'obsolete generation depth bound')
            count += len(dirs) + len(files)
            require(count <= MAX_FILES + 32, 'obsolete generation entry bound')
            for name in list(dirs):
                path = at / name; prefix = path.relative_to(root).as_posix() + '/'
                index = bisect_left(names, prefix)
                if path.is_symlink() or index == len(names) or not names[index].startswith(prefix): dirs.remove(name)
            for name in files:
                path = at / name
                if path.relative_to(root).as_posix() in expected and stat.S_ISREG(path.lstat().st_mode): path.unlink()
        for path in reversed(directories): _remove_empty(path)
    for name in ('order.json', 'order.tsv', 'receipt.json'):
        path = previous / name
        if path.exists() and stat.S_ISREG(path.lstat().st_mode): path.unlink()
    _remove_empty(previous)


def _completed_metadata(destination, expected_inputs=None, *, expected_generation=None, _reviewed_v8=False):
    """Metadata only. Its caller must independently verify the data payload.

    Kept private so a metadata receipt is never confused with verify_completed's
    actual payload hashing and preflight. The optional, separately gated cache
    sealer uses this same unchanged source/input/provider contract.
    """
    destination = storage.canonical(destination)
    selected_generation = destination.name if expected_generation is None else expected_generation
    require(type(selected_generation) is str and storage.HASH.fullmatch(selected_generation),
            'full prepared data generation identity required')
    receipt = document(destination / 'receipt.json')
    require(type(receipt) is dict and set(receipt) == {'formatVersion', 'scope', 'generation', 'inputs',
            'files', 'providerOrder', 'preflight', 'worldQualified', 'androidQualified', 'gameplayQualified'} and
            type(receipt['formatVersion']) is int and receipt['formatVersion'] == 1 and receipt['scope'] == SCOPE and
            all(receipt[name] is False for name in ('worldQualified', 'androidQualified', 'gameplayQualified')),
            'invalid prepared server data receipt')
    inputs = receipt['inputs']
    base_fields = {'formatVersion', 'importGeneration', 'clientRevision', 'serverRevision', 'locale',
                   'threads', 'importMetadata', 'toolSelectionSha256'}
    version = inputs.get('formatVersion') if type(inputs) is dict else None
    fields = base_fields if version == 1 else base_fields | {'serverDataPackage', 'preparationHelperGeneration'}
    # Historical receipts remain readable only as the custom profile. Every new
    # generation binds an explicit profile; stock callers require that identity.
    if type(inputs) is dict and 'contentProfile' in inputs: fields |= {'contentProfile'}
    if type(inputs) is dict and 'preparationHelperGeneration' in inputs: fields |= {'preparationHelperGeneration'}
    require(type(inputs) is dict and set(inputs) == fields and type(version) is int and version in (1, 2) and
            inputs.get('contentProfile', 'esteria-custom') in CONTENT_PROFILES and
            inputs['clientRevision'] == CLIENT_REVISION and inputs['serverRevision'] == formats.SERVER_REVISION and
            inputs['locale'] in order.LOCALES and type(inputs['threads']) is int and inputs['threads'] in (1, 2) and
            type(inputs['importGeneration']) is str and storage.HASH.fullmatch(inputs['importGeneration']) and
            type(inputs['toolSelectionSha256']) is str and storage.HASH.fullmatch(inputs['toolSelectionSha256']) and
            type(inputs['importMetadata']) is dict and 0 < len(inputs['importMetadata']) <= 96,
            'prepared data input selection differs')
    if version == 2:
        validate_package_selection(inputs['serverDataPackage'])
    if 'preparationHelperGeneration' in inputs:
        require(inputs['preparationHelperGeneration'] ==
                (V8_HELPER_GENERATION if _reviewed_v8 else preparation_helper_generation()),
                'prepared server package helper source changed; prepare a new generation')
    for name, identity in inputs['importMetadata'].items():
        order.safe(name, 1024); pin(identity)
    key = hashlib.sha256(storage.encoded(inputs)).hexdigest()
    require(receipt['generation'] == key == selected_generation and
            (expected_inputs is None or storage.encoded(inputs) == storage.encoded(expected_inputs)),
            'prepared data generation/source selection differs')
    provider = receipt['providerOrder']
    require(type(provider) is dict and set(provider) == {'effectiveLocale', 'manifest', 'wire'} and
            provider['effectiveLocale'] in order.LOCALES, 'prepared provider order metadata differs')
    for name, identity in (('order.json', provider['manifest']), ('order.tsv', provider['wire'])):
        require(storage.identity(destination / name, order.MAX_MANIFEST) == pin(identity),
                'prepared provider order bytes changed')
    plan = document(destination / 'order.json')
    require(plan['configuredLocale'] == inputs['locale'] and plan['effectiveLocale'] == provider['effectiveLocale'] and
            plan['profile'] == PROFILE and _metadata_bytes(destination / 'order.tsv', order.MAX_MANIFEST) == order.wire(plan),
            'prepared provider projection differs')
    return receipt


def verify_completed(destination, expected_inputs=None, *, expected_generation=None):
    """Full byte/header verification. This remains the production default."""
    destination = storage.canonical(destination)
    receipt = _completed_metadata(destination, expected_inputs, expected_generation=expected_generation)
    require(storage.encoded(receipt['files']) == storage.encoded(inventory(destination / 'data')),
            'prepared server data changed')
    preflight = formats.check_server_data(destination / 'data')
    require(preflight['checks_passed'] and storage.encoded(receipt['preflight']) == storage.encoded(preflight),
            'prepared server data preflight changed')
    return receipt


def _v8_completed(generations, inputs):
    previous_inputs = _v8_inputs(inputs)
    key = hashlib.sha256(storage.encoded(previous_inputs)).hexdigest()
    previous = generations / key
    if inputs == previous_inputs or not previous.exists() and not previous.is_symlink(): return None
    receipt = _completed_metadata(previous, previous_inputs, _reviewed_v8=True)
    require(storage.encoded(receipt['files']) == storage.encoded(inventory(previous / 'data')),
            'reviewed v8 prepared data changed')
    checked = formats.check_server_data(previous / 'data')
    require(checked['checks_passed'] and storage.encoded(checked) == storage.encoded(receipt['preflight']),
            'reviewed v8 prepared data preflight changed')
    return previous


def generate(store, game, generation, tools, selection, locale, *, threads=1, timeout=24 * 3600,
             cancelled=lambda: False, progress=lambda phase: None, content_profile=DEFAULT_CONTENT_PROFILE):
    with world_io.adapt_helpers(cancelled=cancelled):
        return _generate(store, game, generation, tools, selection, locale, threads=threads, timeout=timeout,
            cancelled=cancelled, progress=progress, content_profile=content_profile)


def _generate(store, game, generation, tools, selection, locale, *, threads=1, timeout=24 * 3600,
             cancelled=lambda: False, progress=lambda phase: None, content_profile=DEFAULT_CONTENT_PROFILE):
    require(content_profile in CONTENT_PROFILES, 'unsupported content profile')
    require(type(threads) is int and threads in (1, 2), 'one or two extraction workers required')
    require(type(timeout) is int and 0 < timeout <= 48 * 3600, 'invalid extraction deadline')
    require(locale in order.LOCALES, 'explicit extraction locale required')
    store, game, tools = storage.canonical(store, create=True), storage.canonical(game), storage.canonical(tools)
    require(not any(a == b or a in b.parents or b in a.parents for a, b in
                    ((store, game), (store, tools), (game, tools))), 'extraction roots must be separate')
    lock = os.open(store / '.setup.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = {'formatVersion': 1, 'contentProfile': content_profile, 'importGeneration': generation, 'locale': locale, 'threads': threads,
                  'clientRevision': CLIENT_REVISION, 'serverRevision': formats.SERVER_REVISION,
                  'importMetadata': storage.imported(game, generation),
                  'toolSelectionSha256': tools_verified(tools, selection),
                  'preparationHelperGeneration': preparation_helper_generation()}
        source = game / 'generations' / generation / 'data'
        external = package_selection(source)
        require(content_profile != 'stock-3.3.5a' or external is None,
                'Stock 3.3.5a generates matching data from stock client archives; custom server-data overlays require the Esteria profile')
        if external is not None:
            inputs.update(formatVersion=2, serverDataPackage=external,
                          preparationHelperGeneration=preparation_helper_generation())
        key = hashlib.sha256(storage.encoded(inputs)).hexdigest()
        staging = storage.canonical(store / 'staging', create=True)
        generations = storage.canonical(store / 'generations', create=True)
        destination = generations / key
        if destination.exists() or destination.is_symlink():
            receipt = verify_completed(destination, inputs)
            previous = None
        else:
            work = storage.canonical(staging / key, create=True)
            previous = _v8_completed(generations, inputs)
            if previous is not None and not (work / 'order.json').exists() and not (work / 'order.json').is_symlink():
                storage.atomic(work / 'order.tsv', storage.read(previous / 'order.tsv', order.MAX_MANIFEST))
                storage.atomic(work / 'order.json', storage.read(previous / 'order.json', order.MAX_MANIFEST))
                progress('extraction-migrated-reviewed-v8-generation')
                world_io.phase('migrated-reviewed-v8-generation')
            _v8_work(staging, work, inputs, progress)
            plan_path = work / 'order.json'
            if plan_path.exists() or plan_path.is_symlink():
                plan = document(plan_path)
                wire = order.wire(plan)
                require(storage.read(work / 'order.tsv', order.MAX_MANIFEST) == wire,
                        'cached extraction provider projection changed')
            else:
                progress('extraction-provider-order')
                plan = order.plan(source, locale, profile=PROFILE)
                wire = order.wire(plan)
                storage.atomic(work / 'order.tsv', wire)
                storage.atomic(plan_path, order.canonical(plan))
            require(plan['configuredLocale'] == locale and plan['profile'] == PROFILE, 'extraction provider profile changed')
            if external is not None:
                require(package_selection(source, validate=True) == external, 'matched server package selection changed')
                selected_order = external['clientProviderOrderSha256']
                require(selected_order == 'none' or selected_order == hashlib.sha256(order.canonical(plan)).hexdigest(),
                        'supplied server package is bound to a different effective client provider order')
            ordered = ['--esteria-order', str(work / 'order.tsv'), '--esteria-order-sha256', hashlib.sha256(wire).hexdigest(),
                       '--esteria-input-root', str(source)]
            deadline = time.monotonic() + timeout
            def run(name, args, cwd, log):
                progress('extraction-' + name)
                world_io.phase('extraction-' + name)
                remaining = int(deadline - time.monotonic())
                require(remaining > 0, 'data preparation deadline exceeded')
                # Assembly/navigation consume generated maps/models, not MPQs.
                # Advising every archive throughout those hours of CPU work
                # repeatedly evicts unrelated data without protecting the child.
                cache_inputs = tuple(source / row['path'] for row in plan['providers'] if row['kind'] == 'mpq') \
                    if name in PROGRAMS[:2] and args != ['--esteria-order-capabilities'] else ()
                return execute([str(tools / 'bin' / name), *args], cwd, log, remaining, cancelled=cancelled, cache_inputs=cache_inputs)
            complete_external = external is not None and external['mode'] == 'complete'
            if previous is None and not complete_external:
                for name in PROGRAMS[:2]:
                    capability_log = work / ('capability-' + name + '-' + uuid.uuid4().hex + '.log')
                    run(name, ['--esteria-order-capabilities'], work, capability_log)
                    require(storage.read(capability_log, 4096).rstrip(b'\n') == CAPABILITY,
                            'ordered extractor capability differs; no stock fallback')
                    capability_log.unlink()
                # The original extractor truncates -o to 127 bytes. Its private
                # phase data directory is already the child cwd; use that short
                # relative destination while keeping full paths for ownership.
                maps = phase(work, 'maps-dbc-cameras', lambda data, at:
                    run('map_extractor', [*ordered, '-o', '.', '-e', '7'], data, at / 'extract.log'), progress=progress)
                raw = phase(work, 'raw-vmaps', lambda data, at:
                    run('vmap4_extractor', ordered, data, at / 'extract.log'), progress=progress)
                def assemble(data, at):
                    (data / 'vmaps').mkdir(mode=0o700)
                    run('vmap4_assembler', [str(raw / 'Buildings'), str(data / 'vmaps')], data, at / 'extract.log')
                vmaps = phase(work, 'assembled-vmaps', assemble, progress=progress)
                def navigation(data, at):
                    # The reusable attempt already owns verified input clones.
                    # Old logs are dispensable after their causal tail has been
                    # exported by the owned child; avoid one log per retry.
                    for path in at.iterdir():
                        if path.name == 'extract.log' or re.fullmatch(r'extract-[0-9a-f]{32}\.log', path.name):
                            storage.canonical(path, False).unlink()
                    run('mmaps_generator', ['--config', str(tools / 'etc/mmaps-config.yaml'), '--threads', str(threads), '--silent'],
                        data, at / 'extract.log')
                nav = phase(work, 'navigation', navigation, progress=progress, navigation_inputs=(maps, vmaps))
            final = work / ('final-' + uuid.uuid4().hex); final.mkdir(mode=0o700)
            data = final / 'data'
            if previous is not None: clone(previous / 'data', data)
            else: data.mkdir(mode=0o700)
            if previous is None and not complete_external:
                for base, names in ((maps, ('maps', 'dbc', 'Cameras')), (vmaps, ('vmaps',)), (nav, ('mmaps',))):
                    for name in names:
                        clone(base / name, data / name)
            if previous is None and external is not None:
                progress('extraction-supplied-server-data')
                merge_supplied(source / formats.SERVER_NAMESPACE / 'data', data, cancelled=cancelled)
            preflight = formats.check_server_data(data)
            require(preflight['checks_passed'], 'generated server data failed format preflight')
            require(not cancelled() and storage.imported(game, generation) == inputs['importMetadata'] and
                    tools_verified(tools, selection) == inputs['toolSelectionSha256'] and package_selection(source) == external and
                    preparation_helper_generation() == inputs['preparationHelperGeneration'],
                    'extraction inputs changed before completion')
            receipt = {'formatVersion': 1, 'scope': SCOPE, 'generation': key, 'inputs': inputs,
                       'files': inventory(data), 'preflight': preflight,
                       'providerOrder': {'effectiveLocale': plan['effectiveLocale'],
                           'manifest': storage.identity(plan_path, order.MAX_MANIFEST),
                           'wire': storage.identity(work / 'order.tsv', order.MAX_MANIFEST)},
                       'worldQualified': False, 'androidQualified': False, 'gameplayQualified': False}
            for relative in receipt['files']:
                with (data / relative).open('rb') as source_file:
                    os.fsync(source_file.fileno())
            for parent, _, _ in os.walk(data, topdown=False, onerror=walk_error):
                storage.sync(Path(parent))
            storage.atomic(final / 'order.json', storage.read(plan_path, order.MAX_MANIFEST))
            storage.atomic(final / 'order.tsv', wire)
            storage.atomic(final / 'receipt.json', storage.encoded(receipt))
            os.rename(final, destination); storage.sync(generations)
        require(not cancelled() and storage.imported(game, generation) == inputs['importMetadata'] and
                package_selection(source) == external and
                preparation_helper_generation() == inputs['preparationHelperGeneration'],
                'import changed before server data activation')
        storage.atomic(store / 'current', (key + '\n').encode())
        previous_key = hashlib.sha256(storage.encoded(_v8_inputs(inputs))).hexdigest()
        previous_generation = generations / previous_key
        if previous_generation != destination and (previous_generation.exists() or previous_generation.is_symlink()):
            # Equivalent, fully reverified v9 data is now active. Old receipt and
            # clones can be reclaimed without touching the promoted generation.
            # Retrying also finishes an interrupted old-generation reclamation.
            _retire_v8_generation(previous_generation, receipt)
        if (staging / key).exists():
            _trim_work(staging / key)
        progress('extraction-format-checked')
        return receipt
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('store', 'game', 'tools', 'selection'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--generation', required=True)
    parser.add_argument('--locale', required=True)
    parser.add_argument('--content-profile', choices=CONTENT_PROFILES, default=DEFAULT_CONTENT_PROFILE)
    parser.add_argument('--threads', type=int, default=1, choices=(1, 2))
    parser.add_argument('--android-low-memory', action='store_true', help='Use the fixed Android preparation I/O policy')
    args = parser.parse_args()
    try:
        def run():
            return generate(args.store, args.game, args.generation, args.tools, document(args.selection), args.locale,
                threads=args.threads, content_profile=args.content_profile, progress=lambda value: print(value, flush=True))
        if args.android_low_memory:
            with world_io.android_policy(progress=lambda value: print(value, flush=True)):
                receipt = run()
        else:
            receipt = run()
        print('Server data format checked: ' + receipt['generation'] + '; world coverage remains unqualified')
        return 0
    except world_io.PreparationPaused:
        world_io.print_pause()
        return world_io.PAUSED_EXIT_CODE
    except (OSError, ValueError) as error:
        print('Server data preparation failed (' + type(error).__name__ + '): ' + str(error) + '; active output preserved', flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
