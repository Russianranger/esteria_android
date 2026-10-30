#!/usr/bin/env python3
"""Pair the reconstructed ARM64 Grunt client with the compiled local authserver.

Run in the pinned native Ubuntu ARM64 server dependency environment, as root,
with a separately prepared Debian Wine runtime. The sole external network
namespace contains loopback. This is disposable authentication qualification,
never Android/game/world qualification or a way to adopt existing player state.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import re
import secrets
import signal
import stat
import subprocess
import sys
import time
import types

if not __package__:sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import client_auth_contract as contract
from tools import provider_client_runtime as client
from tools import qualify_wine_arm64 as wine
from tools import qualify_authserver as server
from tools import qualify_dbimport as importer
from tools import qualify_base_sql as base
from tools import render_server_config as config
from tools import manifest_server_modules as modules
from tools import verify_server_build as identities
from runtime import mysql_bootstrap as db
from runtime import provision_local_account as account
from runtime import provision_local_realm as realm

require=client.require
SCOPE='disposable-linux-arm64-reconstructed-client-compiled-authserver'
SELECTED={'bin/Win/ARM64/'+name:name for name in client.BINARIES}
SELECTED.update({'bin/Win/ARM64/client-build.json':'client-build.json',
                 'build/client/generated/limits/limits.json':'limits.json'})


def prepare_client(artifact, source, revision, expected_sha, expected_bytes, fixture):
    require(re.fullmatch('[a-f0-9]{40}',revision) and re.fullmatch('[a-f0-9]{64}',expected_sha) and
            22<=expected_bytes<=512*1024**2,'explicit-client-artifact-identity-required')
    client.fetch_sources.verify_checkout(source,dict(commit=revision,submodules={}),[])
    # The exact trusted source must contain the opt-in diagnostic; an older
    # qualified entry-only client cannot satisfy this gate through stale output.
    diagnostic=client.source_blob(source,revision,'WoW/Source/Win64/AuthCheck.cpp')
    require(b'executable-grunt-authentication-only' in diagnostic,'client-has-no-grunt-check')
    pin=dict(bytes=expected_bytes,sha256=expected_sha);client.verify_identity(artifact,pin)
    with client.archives.plain_file(artifact) as incoming,client.checked_zip(incoming,required=SELECTED) as archive:
        for original,name in SELECTED.items():
            info=archive.getinfo(original);limit=128*1024**2 if name.endswith(('.exe','.dll')) else client.META_LIMIT
            require(0<info.file_size<=limit,'client-auth-artifact-member-limit')
            with archive.open(info) as stream,(fixture/name).open('xb') as target:
                client.archives.hash_stream(stream,info.file_size,target)
    raw=client.small(fixture/'client-build.json');manifest=json.loads(raw)
    parser=types.ModuleType('committed_client_manifest')
    exec(compile(client.source_blob(source,revision,'Tools/RuntimeManifest/generate.py'),
                 'committed-client/Tools/RuntimeManifest/generate.py','exec'),parser.__dict__)
    images=[parser.inspect_file(fixture/name,'ARM64',name.endswith('.dll')) for name in client.BINARIES]
    expected=dict(schema_version=1,component='esteria-reconstructed-client',evidence='build-only',architecture='ARM64',
        source_revision=revision,build_id=manifest.get('build_id'),protocol=dict(parser.PROTOCOL),
        descriptor_manifest=parser.descriptor_info(fixture/'limits.json'),files=images)
    require(type(expected['build_id']) is str and re.fullmatch(r'[0-9]+\.[0-9]+',expected['build_id']) and manifest==expected,
            'client-auth-manifest-source-or-image-mismatch')
    require(manifest['protocol']==dict(build=12340,container_slots=254,quest_slots=25,max_class_id=32),'client-auth-protocol-mismatch')
    for name in client.BINARIES:client.no_delay_imports(fixture/name)
    return dict(sourceRevision=revision,buildId=manifest['build_id'],artifact=pin,
        manifestSha256=hashlib.sha256(raw).hexdigest(),files=images,
        authDiagnosticSourceSha256=hashlib.sha256(diagnostic).hexdigest())


def prepared_wine(runtime):
    runtime=client.archives.directory(runtime);lock,_=wine.read_json(client.archives.DEFAULT_LOCK)
    package=lock['packages']['wine-arm64'];receipt,digest=wine.read_json(runtime/'package-receipt.json')
    pin=hashlib.sha256(json.dumps(package,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    require(receipt.get('archiveSha256')==package['archive']['sha256'] and
            receipt.get('manifestSha256')==package['manifest']['sha256'] and receipt.get('packagePinSha256')==pin and
            receipt.get('preparerSha256')==hashlib.sha256(Path(client.archives.__file__).read_bytes()).hexdigest() and
            receipt.get('archiveExtracted') is True and receipt.get('stagedFilesReadBack') is True,'wine-runtime-not-prepared-here')
    for name,expected in package['components'].items():
        with client.archives.plain_file(runtime/'rootfs'/name) as stream:
            client.archives.verify_stream(stream,dict(file=Path(name).name,**expected))
    return dict(archiveSha256=package['archive']['sha256'],preparedReceiptSha256=digest)


def typed_success(value, exit_code):
    return (type(exit_code) is int and exit_code==0 and value.get('workerCompleted') is True and
        type(value.get('formatVersion')) is int and value['formatVersion']==1 and value.get('scope')==SCOPE and
        value.get('phase')=='complete' and value.get('cleanupFailures')==[] and
        all(value.get(name) is False for name in ('androidRuntimeQualified','worldEntryQualified','gameplayQualified')) and
        value.get('expectedExit')==0 and type(value.get('expectedExit')) is int and
        all(value.get(name) is True for name in ('networkIsolated','ownedLoopbackListenerVerified',
            'reconstructedClientAuthenticated','persistedSessionKeyVerified','credentialsAndTrackersPreserved',
            'schemaLedgerPreserved','cleanShutdownVerified','privateKeyRemoved','logsComplete')))


def worker(plan_path):
    require(os.getpid()==1 and os.geteuid()==0 and os.environ.get('ESTERIA_AUTH_NAMESPACE')=='1',
            'authentication-worker-requires-owned-pid-namespace')
    plan,_=wine.read_json(plan_path);output=Path(plan['output']);private=output/'private';public=output/'evidence'
    root=Path(plan['runtime'])/'rootfs';fixture=root/wine.GUEST.lstrip('/')
    result=dict(formatVersion=1,scope=SCOPE,workerCompleted=False,expectedExit=None,phase='isolate',
        **{name:False for name in ('networkIsolated','ownedLoopbackListenerVerified','reconstructedClientAuthenticated',
           'persistedSessionKeyVerified','credentialsAndTrackersPreserved','schemaLedgerPreserved','cleanShutdownVerified',
           'privateKeyRemoved','logsComplete','androidRuntimeQualified','worldEntryQualified','gameplayQualified')})
    mysql_capture=auth_capture=display=None;captures=[];key=None;state=None;wine_started=False;failed=False
    try:
        for name in ('/dev','/proc','/sys'):
            target=client.archives.directory(root/name.lstrip('/'),create=True)
            subprocess.run(['mount','--bind',name,str(target)],check=True,timeout=15)
            if name=='/sys':subprocess.run(['mount','-o','remount,bind,ro',str(target)],check=True,timeout=15)
        subprocess.run(['ip','link','set','lo','up'],check=True,timeout=15)
        interfaces=json.loads(subprocess.check_output(['ip','-j','link','show'],timeout=15))
        require({row['ifname'] for row in interfaces}=={'lo'},'authentication-namespace-has-external-interface')
        result['networkIsolated']=True;result['phase']='fresh-compiled-updater'
        install=Path(plan['install']);content=Path(plan['content']);lock=Path(plan['lock'])
        mysql=Path(plan['mysql']);mysqld=Path(plan['mysqld']);version=plan['version']
        fresh=private/'server'
        updated=importer.run(install,content,plan['contentReceiptSha256'],lock,mysql,mysqld,version,fresh)
        require(updated['qualificationSucceeded'],'compiled-updater-did-not-qualify')
        result['compiledUpdaterReceiptSha256']=identities.identity(fresh/'qualification.json')['sha256']
        state=fresh/'private-state';source=fresh/'content/source'
        manifest,_=modules.read_json(fresh/'content/metadata/content-manifest.json')
        compiled,_=modules.read_json(fresh/'content/metadata/compiled-modules.json')
        build,_=importer.verify_install(install,compiled,lock)
        binary=[row for row in build['files'] if row['path']=='bin/authserver']
        require(len(binary)==1 and binary[0].get('elf',{}).get('machine')=='AArch64','exact-arm64-authserver-required')
        binary=binary[0]
        require(identities.identity(install/'bin/authserver')=={key:binary[key] for key in ('bytes','sha256')},'authserver-changed')
        result.update(serverBuildId=build['buildId'],serverSource=updated['source'],sourceLockSha256=updated['sourceLockSha256'],
                      authserver={key:binary[key] for key in ('bytes','sha256')})
        render_source=server.templates(install,fresh,source,build)
        config.render(render_source,state,fresh/'unavailable-game-data',source,mysql)
        password=db.read_secret(state/'accounts/database-secret');generation=realm.active_config(state,password)
        configuration=state/'config/generations'/generation/'authserver.conf'
        require(realm.settings(realm.read_text(configuration),('StrictVersionCheck',))=={'StrictVersionCheck':'0'},
                'source-auth-version-proof-policy-differs')
        result['phase']='start-owned-mysql'
        mysql_capture=db.EngineCapture(base.engine_command(mysqld,state),state/'logs/mysql-client-auth-engine.log')
        base.wait_owned(mysql,state,version,mysql_capture);realm.provision(mysql,state,version);account.provision(mysql,state,version)
        journal=state/account.JOURNAL;journal_bytes=journal.read_bytes()
        intent=account.read_intent(journal,db.read_receipt(state/'database-bootstrap.json',version))
        expected={name:importer.expected_updates(source,manifest,name) for name in importer.DATABASES}
        with db.option_file(state,'esteria',password) as options,db.Mysql(mysql,options) as connection:
            before=importer.schema_snapshot(connection,expected)
            trackers=connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')
        result['phase']='start-owned-authserver'
        auth_capture=server.OwnedAuthserver(install/'bin/authserver',configuration,state/'logs/authserver-private.log')
        server.wait_authserver(auth_capture);result['ownedLoopbackListenerVerified']=True
        for name in ('home','prefix'):(fixture/name).mkdir(mode=0o700)
        display=wine.Capture(wine.guest_command(root,'/usr/bin/Xtigervnc',':8','-geometry','640x480','-depth','24',
            '-rfbport','-1','-SecurityTypes','None','-nolisten','tcp','-ac'),private/'display.log');captures.append(display)
        deadline=time.monotonic()+20;socket=root/'tmp/.X11-unix/X8'
        while time.monotonic()<deadline and display.process.poll() is None:
            if socket.exists() and stat.S_ISSOCK(socket.lstat().st_mode):break
            time.sleep(.1)
        require(display.process.poll() is None and socket.exists() and stat.S_ISSOCK(socket.lstat().st_mode),
                'private-headless-display-not-ready')
        result['phase']='initialize-private-wine-prefix';wine_started=True
        require(wine.run_logged(wine.guest_command(root,'/opt/wine/bin/wine','wineboot.exe','-u'),
            private/'wineboot.log',180,captures).exit_code==0,'private-wine-prefix-failed')
        require(server.owns_listener(auth_capture.process.pid) and auth_capture.group.observe() is None,
                'owned-authserver-listener-lost-before-credentials')
        for image in plan['client']['files']:
            actual=wine.pe_identity(fixture/image['name'],image['name'].endswith('.dll'))
            require((actual['bytes'],actual['sha256'])==(image['size'],image['sha256']),'client-image-changed-before-authentication')
        for name in (contract.INPUT,contract.RECEIPT,contract.KEY):
            require(not os.path.lexists(fixture/name),'private-client-auth-output-already-exists')
        nonce=secrets.token_bytes(16);contract.write_input(fixture/contract.INPUT,intent,nonce)
        result['phase']='actual-reconstructed-grunt-client'
        capture=wine.run_logged(wine.guest_command(root,'/opt/wine/bin/wine',wine.GUEST+'/WowClient64.exe',
            '--auth-check','--local-offline'),private/'client-auth.log',120,captures)
        require(capture.exit_code==0,'actual-grunt-client-failed')
        receipt,digest=contract.read_receipt(fixture/contract.RECEIPT,nonce);key=contract.read_key(fixture/contract.KEY)
        result.update(clientReceipt=receipt,clientReceiptSha256=digest,reconstructedClientAuthenticated=True)
        with db.option_file(state,'esteria',password) as options,db.Mysql(mysql,options) as connection:
            session=connection.query('SELECT LOWER(HEX(session_key)),os,locale FROM acore_auth.account WHERE id='+str(intent['accountId']))
            require(len(session)==1 and hmac.compare_digest(session[0],key.hex()+'\tWin\t0'),'client-and-persisted-server-session-key-differ')
            result['persistedSessionKeyVerified']=True
            require(importer.schema_snapshot(connection,expected)==before,'authentication-changed-schema-or-ledger')
            result['schemaLedgerPreserved']=True
            require(connection.query('SELECT * FROM acore_auth.realmcharacters ORDER BY realmid,acctid')==trackers,
                    'authentication-changed-character-trackers')
            account.match_account(account.selected_account(connection,intent['username']),intent)
            require(connection.query(realm.ROW_SQL)==[realm.EXPECTED_ROW],'local-realm-changed-after-authentication')
        require(journal.read_bytes()==journal_bytes,'authentication-changed-private-credentials')
        result['credentialsAndTrackersPreserved']=True
        result['phase']='controlled-shutdown'
    except BaseException as error:
        failed=True;result['failureType']=type(error).__name__ # Never export exception text containing SQL or credentials.
    finally:
        cleanup=[]
        if wine_started:
            for label,argument in (('stop','-k'),('wait','-w')):
                try:require(wine.run_logged(wine.guest_command(root,'/opt/wine/bin/wineserver',argument),
                    private/('wineserver-'+label+'.log'),30,captures).exit_code==0,'wine-clean-shutdown-failed')
                except BaseException:cleanup.append('wine-'+label)
        for label,capture in (('authserver',auth_capture),('mysql',mysql_capture)):
            if capture is not None:
                try:capture.stop() if label=='authserver' else base.stop_owned(capture)
                except BaseException:cleanup.append(label)
        if display is not None:
            try:
                if display.process.poll() is None:display.process.terminate()
                display.wait(10)
                require(display.exit_code in (0,-signal.SIGTERM),'headless-display-stop-failed')
            except BaseException:cleanup.append('display')
        for capture in captures:
            if not capture.finish(5) or capture.truncated or capture.error is not None:cleanup.append('private-log-drain')
        try:
            for name in (contract.INPUT,contract.KEY):(fixture/name).unlink(missing_ok=True)
            result['privateKeyRemoved']=True
        except BaseException:cleanup.append('private-client-secret-removal')
        try:
            if (private/'client-auth.log').exists():contract.export_status(private/'client-auth.log',public/'client-status.log')
            # Server/Wine crash text can expose memory before a session key was
            # returned. Keep it private even when ordinary account redaction is
            # possible; this gate exports fixed client statuses and typed phases.
        except BaseException:cleanup.append('public-log-redaction')
        result['cleanupFailures']=cleanup
        result['logsComplete']=not any(item=='private-log-drain' for item in cleanup)
        result['cleanShutdownVerified']=not failed and not cleanup
        result['expectedExit']=0 if not failed and not cleanup else 1;result['workerCompleted']=True
        if not failed and not cleanup:result['phase']='complete'
        db.atomic_json(public/'worker.json',result)
    return result['expectedExit']


def qualify(args):
    require(platform.machine().lower() in ('aarch64','arm64') and os.geteuid()==0,'native-arm64-root-environment-required')
    runtime=client.archives.directory(args.runtime);runtime_proof=prepared_wine(runtime)
    output=Path(os.path.abspath(args.output));client.archives.directory(output.parent,create=True)
    require(not os.path.lexists(output),'existing-client-auth-state-refused')
    root=runtime/'rootfs';fixture=root/wine.GUEST.lstrip('/')
    require(not os.path.lexists(fixture),'wine-runtime-already-used-for-qualification')
    output.mkdir(mode=0o700);(output/'private').mkdir(mode=0o700);(output/'evidence').mkdir(mode=0o700);fixture.mkdir(mode=0o700)
    report=dict(formatVersion=1,scope=SCOPE,qualificationSucceeded=False,wineRuntime=runtime_proof,
        androidRuntimeQualified=False,worldEntryQualified=False,gameplayQualified=False,versionChecksumQualified=False)
    try:
        report['client']=prepare_client(args.client_artifact,args.client_source,args.client_revision,
            args.client_artifact_sha256,args.client_artifact_bytes,fixture)
        plan={name:str(getattr(args,name).resolve(strict=True)) for name in ('runtime','install','content','lock','mysql','mysqld')}
        plan.update(output=str(output),version=args.expected_version,contentReceiptSha256=args.content_receipt_sha256,
                    client=report['client'])
        plan_path=output/'private/plan.json';db.atomic_json(plan_path,plan)
        command=['unshare','--mount','--propagation','private','--pid','--fork','--kill-child=SIGKILL','--mount-proc','--net',
            sys.executable,str(Path(__file__).resolve()),'--namespace-worker','--plan',str(plan_path)]
        # Capture owns the unshare leader. Killing that still-owned process on a
        # timeout kills namespace PID1; the kernel then kills every descendant.
        command=['env','ESTERIA_AUTH_NAMESPACE=1',*command]
        capture=wine.Capture(command,output/'private/namespace.log')
        try:report['namespaceExit']=capture.wait(7200).exit_code
        finally:require(capture.finish(10) and not capture.truncated and capture.error is None,'namespace-log-drain-failed')
        result,_=wine.read_json(output/'evidence/worker.json');report['worker']=result
        report['qualificationSucceeded']=typed_success(result,report['namespaceExit'])
        require(report['qualificationSucceeded'],'compiled-server-client-authentication-did-not-qualify')
        return report
    finally:db.atomic_json(output/'evidence/qualification.json',report)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace-worker',action='store_true',help=argparse.SUPPRESS);parser.add_argument('--plan',type=Path,help=argparse.SUPPRESS)
    for name in ('runtime','install','content','lock','mysql','mysqld','client-artifact','client-source','output'):parser.add_argument('--'+name,type=Path)
    for name in ('client-revision','client-artifact-sha256','content-receipt-sha256','expected-version'):parser.add_argument('--'+name)
    parser.add_argument('--client-artifact-bytes',type=int);args=parser.parse_args()
    try:
        if args.namespace_worker:return worker(args.plan)
        require(all(getattr(args,name) is not None for name in ('runtime','install','content','lock','mysql','mysqld',
            'client_artifact','client_source','output','client_revision','client_artifact_sha256','client_artifact_bytes',
            'content_receipt_sha256','expected_version')),'all-qualified-inputs-required')
        result=qualify(args);print(json.dumps(dict(scope=result['scope'],qualificationSucceeded=True,
            androidRuntimeQualified=False,worldEntryQualified=False,gameplayQualified=False)));return 0
    except BaseException:
        print('Reconstructed client/authserver qualification failed; inspect bounded public phase evidence. Private state withheld.',file=sys.stderr)
        return 1


if __name__=='__main__':raise SystemExit(main())
