"""Private file contract for the reconstructed executable's real Grunt check.

This module contains no SRP or replacement client implementation. The C++ client
performs authentication; the outer owner compares its private key with MySQL.
"""
import hashlib
import json
import os
import re

try:
    from . import prepare_runtime as files
except ImportError:
    import prepare_runtime as files

INPUT = 'Esteria-auth-input.bin'
RECEIPT = 'Esteria-auth-check.json'
KEY = 'Esteria-auth-session.key'
CHECKS = {'actualCommandParser','localOfflineEnabled','twoWorkerThreads','gruntTimerThread','connectedCallback',
          'newSessionRequest','versionChallengeObserved','serverProofVerified','realmListCallback','controlledDisconnect',
          'connectionRefsReleased','gruntTimerJoined','networkThreadsJoined'}
require = files.require


def write_input(path, intent, nonce):
    require(re.fullmatch('EST[0-9A-F]{14}', intent.get('username','')) and
            re.fullmatch('[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{16}', intent.get('password','')) and
            type(nonce) is bytes and len(nonce)==16, 'invalid-private-client-auth-input')
    raw=b'ESTAUTH1'+nonce+intent['username'].encode('ascii')+intent['password'].encode('ascii')
    descriptor=os.open(path, os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor,'wb') as output:
        output.write(raw);output.flush();os.fsync(output.fileno())


def bounded_private(path, maximum):
    with files.plain_file(path) as source:
        info=os.fstat(source.fileno())
        require(info.st_nlink==1 and 0<info.st_size<=maximum, 'private-client-output-shape')
        raw=source.read(maximum+1)
    require(len(raw)<=maximum, 'private-client-output-limit')
    return raw


def read_receipt(path, nonce):
    raw=bounded_private(path,4096);value=json.loads(raw)
    expected=dict(schemaVersion=1,scope='executable-grunt-authentication-only',architecture='ARM64',protocolBuild=12340,
        fixtureId=nonce.hex(),checks={name:True for name in CHECKS},authentications=1,realms=1,realmId=1,
        worldEndpoint='127.0.0.1:8085',privateSessionKeyBytes=40,versionChecksumQualified=False,commonMainStarted=False,
        assetsLoaded=False,compiledServerQualified=False,worldEntryQualified=False,gameplayQualified=False)
    require(type(value) is dict and set(value)==set(expected)|{'realmFlags','realmBuildPresent'} and
            all(type(value[name]) is type(item) and value[name]==item for name,item in expected.items()) and
            all(value['checks'][name] is True for name in CHECKS), 'client-auth-receipt-scope-or-checks')
    require(type(value['realmFlags']) is int and 0<=value['realmFlags']<=255 and
            type(value['realmBuildPresent']) is bool and value['realmBuildPresent']==bool(value['realmFlags']&4),
            'client-auth-realm-flags')
    return value,hashlib.sha256(raw).hexdigest()


def read_key(path):
    raw=bounded_private(path,40);require(len(raw)==40,'client-session-key-length');return raw


def export_status(source, destination):
    # Arbitrary Wine/crash output can include register or memory contents. Only
    # controlled client diagnostic status lines are public; raw logs stay private.
    allowed={b'PASS: Esteria actual Grunt/SRP callbacks, local realm and joined teardown (no game initialization)',
             b'ESTERIA_LOCAL_OFFLINE enabled; classic loopback login; remote downloads disabled'}
    with files.plain_file(source) as stream:
        raw=stream.read(16*1024**2+1)
    require(len(raw)<=16*1024**2,'client-private-log-limit')
    lines=[]
    for line in raw.splitlines():
        if line in allowed:lines.append(line)
        elif line.startswith(b'FAIL: Esteria Grunt authentication check:'):
            lines.append(b'FAIL: Esteria Grunt authentication check (private detail withheld)')
    with destination.open('xb') as out:out.write(b'\n'.join(lines)+b'\n')
