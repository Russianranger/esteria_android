"""Optional actual Grunt/SRP execution under ARM64 Wine with a pinned test peer.

The synthetic peer stays in the client repository. This module copies its exact
committed bytes for the matching reconstructed executable and never implements
an alternative game client, actual authserver or SRP algorithm.
"""
import hashlib
import hmac
import os
import types

try:
    from . import client_auth_contract as contract, provider_client_runtime as client
except ImportError:
    import client_auth_contract as contract
    import provider_client_runtime as client

PEER='client-auth-peer.py'
MODES=('valid','bad-server-proof','remote-realm')
require=client.require


def prepare(source, revision, fixture):
    client.fetch_sources.verify_checkout(source,dict(commit=revision,submodules={}),[])
    raw=client.source_blob(source,revision,'Tools/PlatformTests/auth_peer.py')
    require(0<len(raw)<=256*1024,'client-auth-peer-source-size')
    with (fixture/PEER).open('xb') as target:target.write(raw)
    return dict(sourceRevision=revision,path='Tools/PlatformTests/auth_peer.py',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())


def load_peer(fixture, identity):
    raw=client.small(fixture/PEER,256*1024)
    require(len(raw)==identity['bytes'] and hashlib.sha256(raw).hexdigest()==identity['sha256'],'client-auth-peer-source-changed')
    peer=types.ModuleType('esteria_committed_client_auth_peer');peer.__file__=str(fixture/PEER)
    exec(compile(raw,'committed-client/Tools/PlatformTests/auth_peer.py','exec'),peer.__dict__)
    return peer


def execute(root, fixture, guest, identity, observed, run_logged, guest_command, captures):
    peer_module=load_peer(fixture,identity)
    logs=fixture/'auth-private';logs.mkdir(mode=0o700)
    observed.update(scope='linux-arm64-wine-grunt-synthetic-peer-only',cases=[],qualified=False,
        privateOutputsRemoved=False,existingOutputsPreserved=False,receiptValidated=False,compiledServerQualified=False,
        gameInitializationStarted=False,worldEntryQualified=False,gameplayQualified=False)
    for name in (contract.INPUT,contract.KEY,contract.RECEIPT):
        require(not os.path.lexists(fixture/name),'client-auth-output-already-exists')
    command=guest_command(root,'/opt/wine/bin/wine',guest+'/WowClient64.exe','--auth-check','--local-offline')
    try:
        for index,mode in enumerate(MODES):
            value=peer_module.credentials();nonce=bytes.fromhex(value['fixtureId'])
            case=dict(mode=mode,exitCode=None,peerVerifiedClientProof=False,peerObservedClose=False)
            observed['cases'].append(case);contract.write_input(fixture/contract.INPUT,value,nonce)
            try:
                with peer_module.Peer(value,mode) as peer:
                    capture=run_logged(command,logs/(str(index)+'.log'),120,captures)
                    case['exitCode']=capture.exit_code;peer.finish()
                    case.update(peerVerifiedClientProof=peer.proofVerified,peerObservedClose=peer.peerClosed)
                    if mode=='valid':
                        require(capture.exit_code==0,'actual-wine-grunt-auth-failed')
                        receipt,digest=contract.read_receipt(fixture/contract.RECEIPT,nonce)
                        require(receipt['realmFlags']==6 and receipt['realmBuildPresent'] is True and peer.realmRequested,
                                'synthetic-local-realm-callback-mismatch')
                        key=contract.read_key(fixture/contract.KEY)
                        require(hmac.compare_digest(key,peer.key),'synthetic-client-server-private-key-mismatch')
                        observed.update(receipt=receipt,receiptSha256=digest,privateSessionKeyMatched=True,receiptValidated=True)
                    else:
                        require(capture.exit_code==65 and not os.path.lexists(fixture/contract.RECEIPT) and
                                not os.path.lexists(fixture/contract.KEY),'invalid-peer-or-remote-realm-accepted')
                if mode=='valid':
                    capture=run_logged(command,logs/'existing.log',120,captures)
                    require(capture.exit_code==66 and contract.read_receipt(fixture/contract.RECEIPT,nonce)[1]==digest and
                            hmac.compare_digest(contract.read_key(fixture/contract.KEY),key),'existing-auth-output-changed')
                    observed['existingOutputsPreserved']=True
                    (fixture/contract.RECEIPT).unlink();(fixture/contract.KEY).unlink()
            finally:
                (fixture/contract.INPUT).unlink(missing_ok=True);(fixture/contract.KEY).unlink(missing_ok=True)
        observed['qualified']=True
    except BaseException:
        # No exception text from dynamic peer code, OS/codec or private input is
        # eligible for the outer public worker receipt.
        raise ValueError('actual-wine-grunt-synthetic-exchange-failed') from None
    finally:
        (fixture/contract.INPUT).unlink(missing_ok=True);(fixture/contract.KEY).unlink(missing_ok=True)
        observed['privateOutputsRemoved']=True


def export_logs(fixture, output):
    logs=fixture/'auth-private'
    if logs.exists():
        for name in ('0','1','2','existing'):
            source=logs/(name+'.log')
            if source.exists():contract.export_status(source,output/('client-auth-'+name+'.log'))


def passed(value):
    return (value.get('scope')=='linux-arm64-wine-grunt-synthetic-peer-only' and
        all(value.get(name) is True for name in ('qualified','privateOutputsRemoved','existingOutputsPreserved','privateSessionKeyMatched','receiptValidated')) and
        all(value.get(name) is False for name in ('compiledServerQualified','gameInitializationStarted','worldEntryQualified','gameplayQualified')) and
        type(value.get('cases')) is list and len(value['cases'])==len(MODES) and
        all(type(case) is dict and case.get('mode')==mode and type(case.get('exitCode')) is int and case['exitCode']==(0 if mode=='valid' else 65) and
            case.get('peerVerifiedClientProof') is True and case.get('peerObservedClose') is True
            for case,mode in zip(value['cases'],MODES)))
