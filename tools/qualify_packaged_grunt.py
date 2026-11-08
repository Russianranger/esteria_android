"""Pair the shipped stock schema/account owner and the actual ARM64 client in one loopback namespace."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import socket
import stat
import time

from runtime import mysql_bootstrap as db, provision_local_account as account, provision_local_realm as realm
from tools import client_auth_contract as contract, prepare_runtime, qualify_authserver, qualify_client_auth
from tools import qualify_stock_client_title as title, qualify_wine_arm64 as wine

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(wine.GUEST)
require = prepare_runtime.require


def selection():
    selected = json.loads((ROOT / 'runtime/runtime-sources.lock.json').read_bytes())['packages']['wine-arm64']
    prepared = json.loads((ROOT / 'sources.lock.json').read_bytes())['sources']['client']['commit']
    pair, build = title.renderer_pair(prepared, selected['archive']['sha256'])
    require(selected['wineEnvironment'] == wine.PRIVATE_PE_ENVIRONMENT, 'Wine private executable environment differs')
    return selected, pair, build


def stage(destination, *, input_cache=None):
    selected, pair, build = selection()
    destination.mkdir(mode=0o700)
    cache = input_cache if input_cache is not None else destination / 'cache'
    fixture = destination / 'fixture'
    fixture.mkdir(mode=0o700)
    for pin in (selected['archive'], selected['manifest']):
        prepare_runtime.fetch(pin, cache)
    prepare_runtime.prepare(selected, cache)
    title.stage_renderer(fixture, cache, pair, build, None)
    manifest = fixture / 'client-build.json'
    require(hashlib.sha256(manifest.read_bytes()).hexdigest() == build['buildManifestSha256'], 'client manifest differs')
    built = json.loads(manifest.read_bytes())
    require(built['source_revision'] == pair['executableRevision'] and built['architecture'] == 'ARM64' and
            built['protocol'] == dict(build=12340, container_slots=254, quest_slots=25, max_class_id=32),
            'client protocol/source selection differs')
    verify_images(fixture)


def verify_images(fixture):
    _, pair, build = selection()
    raw = (fixture / 'client-build.json').read_bytes()
    require(hashlib.sha256(raw).hexdigest() == build['buildManifestSha256'], 'executable manifest changed')
    images = json.loads(raw)['files']
    require({image['name'] for image in images} == {'WowClient64.exe', 'XvidDecoder.dll'}, 'unexpected client members')
    for image in images:
        name = image['name']
        actual = wine.pe_identity(fixture / name, name.endswith('.dll'))
        require((actual['bytes'], actual['sha256']) == (image['size'], image['sha256']) and
                (name != 'WowClient64.exe' or actual['sha256'] == pair['executableSha256']), 'selected executable changed')


def wait_for(name, timeout):
    end = time.monotonic() + timeout
    while not (FIXTURE / name).is_file():
        require(not (FIXTURE / 'client-failed').exists(), 'reconstructed client worker failed')
        require(time.monotonic() < end, 'reconstructed client handoff deadline')
        time.sleep(.15)


def server_probe(state, connection, intent, child, attempt):
    require([name for _, name in socket.if_nameindex()] == ['lo'], 'external network interface present')
    journal = state / account.JOURNAL
    journal_before = journal.read_bytes()
    trackers = 'SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid'
    before = connection.query(trackers)
    key_query = 'SELECT LOWER(HEX(session_key)) FROM acore_auth.account WHERE id=' + str(intent['accountId'])
    previous_key = connection.query(key_query)
    def ledger_rows():
        # Both source-owned setup gates have already verified these four ledgers.
        return tuple(connection.query('SELECT name,hash,state FROM acore_' + schema + '.updates ORDER BY name')
                     for schema in ('auth', 'characters', 'world', 'playerbots'))
    ledgers = ledger_rows()
    nonce = secrets.token_bytes(16)
    paths = [FIXTURE / name for name in (contract.INPUT, contract.KEY, contract.RECEIPT)]
    require(not any(os.path.lexists(path) for path in paths), 'previous private authentication material exists')
    contract.write_input(paths[0], intent, nonce)
    try:
        (FIXTURE / f'request-{attempt}').touch(mode=0o600, exist_ok=False)
        wait_for(f'response-{attempt}', 300)
        receipt, digest = contract.read_receipt(paths[2], nonce)
        key = contract.read_key(paths[1])
        qualify_client_auth.verify_persisted_session(connection, intent, key)
        require(connection.query(key_query) != previous_key and ledger_rows() == ledgers, 'fresh key or four-ledger continuity failed')
        require(qualify_authserver.owns_listener(child.process.pid) and child.group.observe() is None,
                'authserver ownership changed during PE login')
        require(journal.read_bytes() == journal_before and connection.query(trackers) == before and
                connection.query(realm.ROW_SQL) == [realm.EXPECTED_ROW], 'account, character tracker or realm changed')
        account.match_account(account.selected_account(connection, intent['username']), intent)
        if attempt == 2:
            wait_for('client-clean', 95)
        selected, pair, _ = selection()
        return dict(executableRevision=pair['executableRevision'], executableSha256=pair['executableSha256'],
                    wineArchiveSha256=selected['archive']['sha256'], authReceiptSha256=digest,
                    clientServerSessionKeyMatched=True, nonceMatched=True, callbacks=sorted(receipt['checks']),
                    worldEndpoint=receipt['worldEndpoint'], realmId=receipt['realmId'], realmCount=receipt['realms'],
                    freshClientProcess=True, loopbackOnly=True, fourLedgersPreserved=True,
                    graphicalLoginQualified=False, characterPersistenceQualified=False)
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


def client():
    require(platform.machine() == 'aarch64' and [name for _, name in socket.if_nameindex()] == ['lo'], 'native private Linux ARM64 required')
    def progress(phase):
        db.atomic_json(FIXTURE / 'client-phase.json', dict(phase=phase))
    progress('verify-client-images')
    verify_images(FIXTURE)
    private = FIXTURE / 'private'
    for path in (private, FIXTURE / 'home', FIXTURE / 'prefix'):
        path.mkdir(mode=0o700)
    captures = []
    # This process already runs inside the verified Wine image; use the existing guest command's environment verbatim.
    def cmd(*args):
        return wine.guest_command(Path('/'), *args, private_pe_copy=True)[2:]
    def run(name, *args, timeout):
        if name not in ('stop', 'wait'):
            progress(name)
        result = wine.run_logged(cmd(*args), private / (name + '.log'), timeout, captures)
        require(result.exit_code == 0, 'reconstructed client process failed')
    progress('start-private-display')
    display = wine.Capture(cmd('/usr/bin/Xtigervnc', ':8', '-geometry', '1920x1080', '-depth', '24',
                               '-rfbport', '-1', '-SecurityTypes', 'None', '-nolisten', 'tcp', '-ac'), private / 'x11.log')
    captures.append(display)
    try:
        deadline = time.monotonic() + 30
        target = Path('/tmp/.X11-unix/X8')
        while not target.exists():
            require(display.process.poll() is None and time.monotonic() < deadline, 'private display failed')
            time.sleep(.1)
        require(stat.S_ISSOCK(target.lstat().st_mode), 'private display socket differs')
        run('boot', '/opt/wine/bin/wine', 'wineboot.exe', '-u', timeout=180)
        for attempt in (1, 2):
            progress(f'wait-for-authserver-{attempt}')
            wait_for(f'request-{attempt}', 900)
            verify_images(FIXTURE)
            run(f'client-{attempt}', '/opt/wine/bin/wine', wine.GUEST + '/WowClient64.exe', '--auth-check', '--local-offline', timeout=120)
            (FIXTURE / f'response-{attempt}').touch(mode=0o600, exist_ok=False)
    finally:
        try:
            run('stop', '/opt/wine/bin/wineserver', '-k', timeout=30)
            run('wait', '/opt/wine/bin/wineserver', '-w', timeout=30)
        finally:
            if display.process.poll() is None:
                display.process.terminate()
            require(display.wait(10).exit_code in (0, -signal.SIGTERM), 'display did not stop')
    require(all(c.finish(10) and not c.truncated and c.error is None for c in captures), 'incomplete private process logs')
    require(wine.private_pe_marker_observed(private,captures), 'private Wine mapping marker missing')
    progress('two-clients-and-wine-cleanly-stopped')
    (FIXTURE / 'client-clean').touch(mode=0o600, exist_ok=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['stage', 'client'])
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.mode == 'stage':
        stage(args.output)
    else:
        try:
            client()
        except BaseException:
            (FIXTURE / 'client-failed').touch(mode=0o600)
            raise
