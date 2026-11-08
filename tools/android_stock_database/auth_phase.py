"""Exercise only the authenticated authserver leg on a real, previously promoted private database."""
import hmac
import json
from pathlib import Path
import re
import secrets
import sys
import time
import types

# Make the fully authenticated helper installation the runtime package for the existing
# host test-client codec. This keeps application code in the installed signed APK.
work=Path('/work')
helper,operation,db_operation,version,uuid,setup_hash,program_hash,program_bytes,world_hash,world_bytes=sys.argv[1:]
assert all(re.fullmatch(r'[a-f0-9]{64}',v) for v in (helper,setup_hash,program_hash))
assert re.fullmatch(r'[a-f0-9]{32}',db_operation) and operation in ('cold','warm')
package=types.ModuleType('runtime')
package.__path__=[str(work/'qa-auth-helpers'/helper)]
sys.modules['runtime']=package
from runtime import android_server_schema_setup as owners
from runtime import mysql_bootstrap as db
from runtime import provision_local_account as accounts
from runtime import provision_local_realm as realm
from runtime import server_schema_baseline as baseline
from runtime import server_session_process as processes
import client_auth_contract as contract

def require(valid,message):
    if not valid: raise ValueError(message)

def status(phase):
    db.atomic_json(observation/'phase.json',{'phase':phase,'elapsedMs':int((time.monotonic()-start)*1000)})

state=work/'state'
observation=work/('qa-auth-'+operation)
start=time.monotonic()
status('verify-promoted-instance')
proof_path=state/'server-setup-complete.json'
require(baseline.file_identity(proof_path)['sha256']==setup_hash,'Promoted setup changed')
proof=json.loads(proof_path.read_bytes())
require(proof['mysqlUuid']==uuid and proof['fourSchemasVerified'] and proof['localAccountVerified'],'Missing promoted schema identity')
executable=Path('/esteria-server-programs/bin/authserver')
require(baseline.file_identity(executable)==dict(bytes=int(program_bytes),sha256=program_hash),'Selected authserver changed')
secret=db.read_secret(state/'accounts/database-secret')
intent=accounts.read_intent(state/accounts.JOURNAL,db.read_receipt(state/'database-bootstrap.json',version))
with realm.config_lock(state),db.option_file(observation,'esteria',secret) as options:
    generation,_=realm._active_generation(state,secret)
    require(generation==proof['configGeneration'],'Promoted configuration generation changed')
    del secret
    with db.Mysql(Path('/usr/bin/mysql'),options) as connection:
        def verify_sql():
            owners.live_service(connection,state,work/'mysql-sessions'/db_operation,version,db_operation,uuid)
        verify_sql()
        child=processes.ServerChild('authserver',executable,state/'config/generations'/generation/'authserver.conf',
                                    state/'run/authserver',observation/'auth-private.log')
        try:
            status('start-selected-authserver')
            child.start()
            status('check-retained-listener')
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                require(child.alive(),'Auth child exited before listener')
                if processes.owns_loopback_listener(child.group,3724):break
                time.sleep(.05)
            else: raise RuntimeError('Auth listener readiness deadline')
            status('build-12340-challenge')
            require(processes.auth_challenge(timeout=1),'Production challenge callback failed')
            status('reconstructed-grunt-authenticate')
            peer=work/'qa-grunt'
            nonce=secrets.token_bytes(16)
            private=[peer/'bin'/name for name in (contract.INPUT,contract.RECEIPT,contract.KEY)]
            require(all(not path.exists() and not path.is_symlink() for path in private),'Stale private challenge')
            try:
                contract.write_input(private[0],intent,nonce)
                db.atomic_json(peer/('ready-'+operation+'.json'),{'operation':operation})
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    require(child.alive(),'Auth child exited during Grunt')
                    if (peer/operation/'exited').is_file(): break
                    time.sleep(.1)
                else: raise RuntimeError('Reconstructed client deadline')
                receipt,digest=contract.read_receipt(private[1],nonce)
                key=contract.read_key(private[2])
            finally:
                for path in private:
                    path.unlink(missing_ok=True)
            verify_sql()
            rows=connection.query('SELECT LOWER(HEX(session_key)),os,locale FROM acore_auth.account WHERE id='+str(intent['accountId']))
            require(len(rows)==1 and hmac.compare_digest(rows[0],key.hex()+'\tWin\t0'),'Auth key differs from owned database')
            require(processes.owns_loopback_listener(child.group,3724),'Listener ownership changed')
            del key,rows,intent
        finally:
            child.stop(auth_timeout=30)
        require(child.closed and child.shutdown_acknowledged,'Auth shutdown not acknowledged')
        verify_sql()
        world_result=None
        if operation=='warm':
            import world_probe
            try:
                world_result=world_probe.observe(state,state/'config/generations'/generation,observation,
                                                world_hash,world_bytes,verify_sql)
            except (OSError,RuntimeError,ValueError) as failure:
                world_result={'phase':'world-observation-failed','errorClass':type(failure).__name__,
                              'worldReadyQualified':False}
            verify_sql()
status('auth-cleanly-stopped')
db.atomic_json(observation/'verified.json',dict(build=12340,sourceChallenge=True,ownedListener=True,
    srpAndRealmList=True,mysqlKeyMatched=True,worldAddress='127.0.0.1:8085',authserverExitedCleanly=True,
    clientReceiptSha256=digest,gruntChecks=len(receipt['checks']),
    supplementalWorld=world_result,commonMainStarted=receipt['commonMainStarted'],assetsLoaded=receipt['assetsLoaded'],authserverSha256=program_hash,authserverElapsedMs=int((time.monotonic()-start)*1000)))
