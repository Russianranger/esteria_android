#!/usr/bin/env python3
"""Fresh compiled updater + owned loopback authserver SRP/realm qualification.

No existing state can be supplied. The updater creates this invocation's private
fixture; only then does this wrapper start its exact verified authserver. This is
a protocol probe, not reconstructed-client, world, bot, or Android qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import auth_protocol as protocol
from tools import qualify_dbimport as importer
from tools import qualify_base_sql as base
from tools import render_server_config as config
from tools import verify_server_build as files
from tools import manifest_server_modules as modules
from tools.owned_process_group import OwnedGroup
from runtime import mysql_bootstrap as db
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm

require = base.content.require
LOG_LIMIT = 256 * 1024


class OwnedAuthserver:
    """Bounded private output and process-group ownership, including updater children."""
    def __init__(self, executable, configuration, log):
        self.error = None
        descriptor = os.open(db.private_path(log), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        self.output = os.fdopen(descriptor, 'wb', buffering=0)
        environment = {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
                       'AC_DISABLE_INTERACTIVE': '1', 'MYSQL_TEST_LOGIN_FILE': os.devnull}
        try:
            self.process = subprocess.Popen([str(executable), '--config', str(configuration)],
                cwd=configuration.parent, env=environment, umask=0o077, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, bufsize=0)
            self.group = OwnedGroup(self.process)
        except BaseException:
            self.output.close()
            raise
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()

    def _drain(self):
        tail = bytearray()
        try:
            while True:
                block = self.process.stdout.read(8192)
                if not block:
                    break
                tail.extend(block)
                if len(tail) > LOG_LIMIT:
                    del tail[:-LOG_LIMIT]
                if self.error is None:
                    try:
                        self.output.seek(0); self.output.write(tail); self.output.truncate()
                    except OSError as error:
                        self.error = error
        except OSError as error:
            self.error = error
        finally:
            try:
                self.output.flush(); os.fsync(self.output.fileno())
            except OSError as error:
                self.error = error
            self.output.close(); self.process.stdout.close()

    def stop(self):
        try:
            status, forced = self.group.stop(graceful_timeout=30)
            require(not forced, 'owned authserver did not stop cleanly')
            require(status == 0, 'owned authserver failed startup/shutdown')
        finally:
            self.reader.join(timeout=5)
            require(not self.reader.is_alive() and self.error is None, 'owned authserver diagnostic drain failed')


def owns_listener(pid, *, proc=Path('/proc')):
    """Confirm this child owns the IPv4 loopback listener, not merely an open port."""
    sockets = set()
    try:
        for path in (proc / str(pid) / 'fd').iterdir():
            try:
                target = os.readlink(path)
            except FileNotFoundError:
                continue
            match = re.fullmatch(r'socket:\[([0-9]+)\]', target)
            if match:
                sockets.add(match[1])
        rows = (proc / str(pid) / 'net/tcp').read_text().splitlines()[1:]
        ipv6 = (proc / str(pid) / 'net/tcp6').read_text().splitlines()[1:]
    except FileNotFoundError:
        return False
    found = []
    for row in ipv6:
        fields = row.split()
        require(len(fields) >= 10, 'unexpected owned Linux TCP6 metadata')
        require(not (fields[3] == '0A' and fields[9] in sockets), 'owned authserver opened an unexpected IPv6 listener')
    for row in rows:
        fields = row.split()
        require(len(fields) >= 10, 'unexpected owned Linux TCP metadata')
        if fields[3] == '0A' and fields[9] in sockets:
            found.append(fields[1])
    require(all(endpoint == '0100007F:0E8C' for endpoint in found), 'owned authserver opened an unexpected IPv4 listener')
    return found == ['0100007F:0E8C']


def wait_authserver(capture):
    deadline = time.monotonic() + 120
    while True:
        require(capture.group.observe() is None, 'owned authserver exited before readiness')
        if owns_listener(capture.process.pid):
            return
        require(time.monotonic() < deadline, 'owned authserver listener readiness timed out')
        time.sleep(.1)


def templates(install, output, content_source, build):
    """Bind both immutable main templates to the build and packaged source.

    The verified content tree also holds the exact compiled module selection;
    returning it permits the shared renderer to materialize every module.
    """
    listed = {row['path']: row for row in build['files']}
    for app in ('authserver', 'worldserver'):
        paths = [path for path in listed if Path(path).name == app + '.conf.dist']
        require(len(paths) == 1, 'matching installed server configuration template missing')
        row = listed[paths[0]]
        source = install / paths[0]
        expected = {key: row[key] for key in ('bytes', 'sha256')}
        require(files.identity(source) == expected and row['bytes'] <= 2 * 1024**2,
                'installed server template differs from exact build receipt')
        packaged = content_source / ('src/server/apps/' + app + '/' + app + '.conf.dist')
        require(files.identity(packaged) == expected, 'source and installed main configuration templates differ')
    return content_source


def render_runtime_config(install, output, source, build, state, mysql):
    result = config.render(templates(install, output, source, build), state,
        output / 'unavailable-game-data', source, mysql,
        module_inventory=output / 'content/metadata/content-manifest.json',
        compiled_modules=output / 'content/metadata/compiled-modules.json')
    require(result['module_configurations_complete'] is True, 'complete compiled module configurations required')
    return result


def export_auth_log(state, output, extra_secrets=()):
    source = state / 'logs/authserver-private.log'
    if not source.is_file():
        return
    with source.open('rb') as stream:
        text = stream.read(LOG_LIMIT).decode('utf-8', errors='replace')
    for secret in extra_secrets:
        for value in (secret, secret.lower(), secret.upper()):
            if value:
                text = text.replace(value, '[redacted]')
    for name in ('database-secret', 'database-root-secret'):
        path = state / 'accounts' / name
        if path.is_file():
            text = text.replace(path.read_text().strip(), '[redacted]')
    path = state / account.JOURNAL
    if path.is_file():
        intent = json.loads(path.read_text())
        for key in ('username', 'password', 'saltHex', 'verifierHex'):
            for value in (intent[key], intent[key].upper(), intent[key].lower()):
                text = text.replace(value, '[redacted]')
    config.write_private(output / 'authserver-redacted.log', text)


def run(install, content_directory, receipt_sha256, lock_path, mysql, mysqld, version, output,
        *, engine_derivative_receipt=None):
    # This call is the sole creator of output and its MySQL state. There is no
    # mode that adopts a previous updater fixture or a user-owned save path.
    output = db.private_path(output)
    selection_args = {} if engine_derivative_receipt is None else {'engine_derivative_receipt': engine_derivative_receipt}
    updated = importer.run(install, content_directory, receipt_sha256, lock_path, mysql, mysqld, version, output,
                           **selection_args)
    require(updated['qualificationSucceeded'], 'compiled updater did not qualify')
    state = output / 'private-state'
    evidence = dict(formatVersion=1, scope='disposable-native-ARM64-authserver-protocol-probe', mysqlVersion=version,
        compiledUpdaterReceiptSha256=files.identity(output / 'qualification.json')['sha256'],
        qualificationSucceeded=False, ownedLoopbackListenerVerified=False, srpProofVerified=False,
        persistedSessionKeyVerified=False, advertisedLoopbackRealmVerified=False, credentialsAndTrackersPreserved=False,
        schemaLedgerPreserved=False, cleanShutdownVerified=False, reconstructedClientExecuted=False,
        playerbotsRuntimeQualified=False, worldEntryQualified=False, androidRuntimeQualified=False, gameplayQualified=False)
    mysql_capture = auth_capture = key = None
    try:
        manifest, _ = modules.read_json(output / 'content/metadata/content-manifest.json')
        compiled, _ = modules.read_json(output / 'content/metadata/compiled-modules.json')
        build, _, programs, derivative = importer.select_install(install, compiled, lock_path, engine_derivative_receipt)
        if derivative is not None:
            evidence['engineDerivative'] = derivative
        auth = [row for row in build['files'] if row['path'] == 'bin/authserver']
        require(len(auth) == 1 and auth[0].get('elf', {}).get('machine') == 'AArch64', 'verified ARM64 authserver missing')
        require(files.identity(install / 'bin/authserver') == programs['authserver'],
                'authserver identity changed before execution')
        evidence.update(serverBuildId=build['buildId'], authserver=programs['authserver'],
                        source=updated['source'], sourceLockSha256=updated['sourceLockSha256'])
        source = output / 'content/source'
        rendered = render_runtime_config(install, output, source, build, state, mysql)
        evidence['moduleConfigurationsPrepared'] = rendered['module_configurations_complete']
        evidence['worldModuleConfigsLoadedByAuthserver'] = False
        password = db.read_secret(state / 'accounts/database-secret')
        generation = realm.active_config(state, password)
        configuration = state / 'config/generations' / generation / 'authserver.conf'
        require(realm.settings(realm.read_text(configuration), ('StrictVersionCheck',)) == {'StrictVersionCheck': '0'},
                'source auth version-proof policy differs; protocol probe needs review')
        evidence['phase'] = 'start-owned-mysql'
        mysql_capture = db.EngineCapture(base.engine_command(mysqld, state), state / 'logs/mysql-auth-engine.log')
        base.wait_owned(mysql, state, version, mysql_capture)
        realm.provision(mysql, state, version)
        account.provision(mysql, state, version)
        journal_path = state / account.JOURNAL
        journal_bytes = journal_path.read_bytes()
        intent = account.read_intent(journal_path, db.read_receipt(state / 'database-bootstrap.json', version))
        expected = {name: importer.expected_updates(source, manifest, name) for name in importer.DATABASES}
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            before = importer.schema_snapshot(connection, expected)
            trackers = connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
        evidence['phase'] = 'start-owned-authserver'
        require(files.identity(install / 'bin/authserver') == programs['authserver'],
                'selected authserver identity changed before owned startup')
        auth_capture = OwnedAuthserver(install / 'bin/authserver', configuration, state / 'logs/authserver-private.log')
        wait_authserver(auth_capture)
        evidence['ownedLoopbackListenerVerified'] = True
        evidence['phase'] = 'authenticate-build-12340-and-read-realms'
        with socket.create_connection(('127.0.0.1', 3724), timeout=5) as connection:
            realms, key = protocol.login(connection, intent)
        evidence['srpProofVerified'] = True
        require(len(realms) == 1 and realms[0]['id'] == 1 and realms[0]['address'] == '127.0.0.1:8085' and
                realms[0]['locked'] == 0 and (realms[0]['build'] is None or realms[0]['build'] == (3,3,5,12340)),
                'authserver advertised a nonlocal or incompatible realm')
        evidence.update(advertisedLoopbackRealmVerified=True, advertisedRealm=realms[0], clientBuild=12340)
        with db.option_file(state, 'esteria', password) as options, db.Mysql(mysql, options) as connection:
            session = connection.query('SELECT LOWER(HEX(session_key)),os,locale FROM acore_auth.account WHERE id=' + str(intent['accountId']))
            require(len(session) == 1 and hmac.compare_digest(session[0], key.hex() + '\tWin\t0'),
                    'authenticated session key or protocol platform/locale was not persisted')
            evidence['persistedSessionKeyVerified'] = True
            require(importer.schema_snapshot(connection, expected) == before, 'authserver startup changed the qualified schema/ledger')
            evidence['schemaLedgerPreserved'] = True
            require(connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid') == trackers,
                    'authentication changed character tracker state')
            account.match_account(account.selected_account(connection, intent['username']), intent)
            require(connection.query(realm.ROW_SQL) == [realm.EXPECTED_ROW], 'realm endpoint changed after authentication')
        require(journal_path.read_bytes() == journal_bytes, 'authentication changed private credentials')
        evidence['credentialsAndTrackersPreserved'] = True
        auth_capture.stop(); auth_capture = None
        account.provision(mysql, state, version, verify_only=True)
        base.stop_owned(mysql_capture); mysql_capture = None
        evidence.update(cleanShutdownVerified=True, qualificationSucceeded=True, phase='complete')
        return evidence
    finally:
        for capture in (auth_capture, mysql_capture):
            if capture is not None:
                try:
                    capture.stop() if isinstance(capture, OwnedAuthserver) else base.stop_owned(capture)
                except BaseException:
                    evidence['qualificationSucceeded'] = False
        export_auth_log(state, output, (key.hex(),) if key is not None else ())
        db.atomic_json(output / 'auth-qualification.json', evidence)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('install', 'content', 'mysql', 'mysqld', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--lock', type=Path, default=base.content.ROOT / 'sources.lock.json')
    parser.add_argument('--content-receipt-sha256', required=True)
    parser.add_argument('--expected-version', required=True)
    parser.add_argument('--engine-derivative-receipt', type=Path)
    args = parser.parse_args()
    try:
        result = run(args.install, args.content, args.content_receipt_sha256, args.lock,
                     args.mysql, args.mysqld, args.expected_version, args.output,
                     engine_derivative_receipt=args.engine_derivative_receipt)
        print(json.dumps(result, indent=2)); return 0
    except BaseException:
        print('Owned authserver qualification failed; private fixture retained and credentials withheld', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
