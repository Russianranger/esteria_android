package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.LocalAccountHandoff;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Arrays;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONException;
import org.json.JSONObject;

/** Retains the matched local database, auth/world, presentation and rebuilt
 * client. Starting this owner is not proof of login, world entry, saving, bots,
 * audio, rendering, Android execution or gameplay qualification. */
public final class GameSession {
    private static final ConcurrentHashMap<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private GameSession(){ }
    public enum State { ALLOCATED,STARTING,CLIENT_STARTED,STOPPING,FAILED,CLOSED }
    /** Callbacks may originate on a retained worker, never contain guest logs or credentials. */
    public interface Events extends ClientPresentationSession.Events {
        /** Central lifecycle owner schedules close; this callback never claims a save. */
        default void clientExited(int exitCode,boolean forced){failed("game-client-exited");}
    }
    public static Handle begin(Context context,Path root,LocalWorldSetup.Result setup,ClientRuntimeSetup client,
            GuestBridgeSetup bridges,TurnipSetup turnip,Events events)throws IOException {
        background();
        if(context==null||root==null||setup==null||client==null||bridges==null||
                !root.equals(context.getFilesDir().getCanonicalFile().toPath())||!root.equals(setup.applicationRoot))
            throw new IOException("Typed completed local setup and private canonical application storage required");
        client.requireWineArchive(setup.wine.archiveSha256());bridges.requireWineArchive(setup.wine.archiveSha256());
        if(turnip!=null){turnip.requireWineArchive(setup.wine.archiveSha256());if(turnip.current()==null)throw new IOException("Prepare the selected Turnip provider first");}
        if(client.current()==null||bridges.current()==null||setup.wine.current()==null)
            throw new IOException("Prepare the matching reconstructed client, Wine and presentation providers first");
        if(!client.sourceRevision().equals(setup.shaders.clientRevision))throw new IOException("Client and prepared shaders use different source revisions");
        if(OWNERS.containsKey(root))throw new IOException("Previous game session ownership remains retained");
        Leases leases=claim(root);
        try {
            setup.data.requireUnchanged();
            Handle owner=new Handle(context.getApplicationContext(),root,setup,client,bridges,turnip,events,leases);
            if(OWNERS.putIfAbsent(root,owner)!=null)throw new IOException("Previous game session ownership remains retained");
            return owner;
        }catch(IOException|RuntimeException error){try{leases.close();}catch(IOException cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    /** Known cleanup only; never steals an allocated/running caller's session. */
    public static void retryPendingCleanup(Context context,Path root,Duration timeout)throws IOException {
        background();if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical game storage required");
        Handle owner=OWNERS.get(root);if(owner==null)return;
        if(owner.state!=State.FAILED&&!owner.operations.isStopRequested())throw new IOException("Game session remains with its active caller");
        owner.close(timeout);
    }
    /** LocalServerSession retains its cancellation predicate. Link it to the
     * outer startup only, then irreversibly detach before a client may launch.
     * Synchronization drains in-flight checks; an observed cancellation is
     * latched so even a transient caller signal cannot be lost at handoff. */
    static final class StartupCancellation implements RuntimeWork.Cancellation {
        private final RuntimeWork.Cancellation startup;
        private boolean armed=true,observed;
        StartupCancellation(RuntimeWork.Cancellation startup){this.startup=startup;}
        @Override public synchronized boolean isCancelled(){
            if(!armed)return false;
            if(startup.isCancelled())observed=true;
            return observed;
        }
        synchronized void handOff()throws RuntimeWork.CancelledException {
            armed=false;if(observed)throw new RuntimeWork.CancelledException();
        }
    }
    static final class Leases implements AutoCloseable {
        final ClientLaunchSetup.Lease client;
        private final ExclusiveFileLease imported;
        private boolean closed;
        private Leases(ClientLaunchSetup.Lease client,ExclusiveFileLease imported){this.client=client;this.imported=imported;}
        @Override public void close()throws IOException {
            if(closed)return;client.close();imported.close();closed=true;
        }
    }
    static Leases claim(Path root)throws IOException {
        Path game=root.resolve("game");
        if(!Files.isDirectory(game,LinkOption.NOFOLLOW_LINKS)||!game.equals(game.toRealPath()))throw new IOException("Canonical imported game store required");
        Path path=game.resolve("import.lock");
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)&&!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))throw new IOException("Invalid import ownership file");
        ExclusiveFileLease imported=ExclusiveFileLease.acquire(path,"Import or local setup already owns game data");
        try {
            Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));
            return new Leases(ClientLaunchSetup.claim(root),imported);
        }catch(IOException|RuntimeException|Error error){try{imported.close();}catch(IOException close){error.addSuppressed(close);}throw error;}
    }

    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root;
        private final LocalWorldSetup.Result setup;
        private final ClientRuntimeSetup client;
        // Keep provider identities strongly reachable throughout native cleanup.
        private final GuestBridgeSetup bridges;
        private final TurnipSetup turnip;
        private final Events events;
        private final Leases leases;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private final AtomicBoolean forceRequested=new AtomicBoolean();
        private volatile State state=State.ALLOCATED;
        private volatile IOException failure;
        private volatile boolean needsForce,recovery,clientExitAcknowledged,handoffRecovery;
        private volatile OwnedProcess process;
        private volatile ServerDatabaseService.Handle database;
        private volatile LocalServerSession.Handle servers;
        private volatile ClientPresentationSession presentation;
        private LocalAccountHandoff handoff;
        private Thread monitor;
        private Handle(Context context,Path root,LocalWorldSetup.Result setup,ClientRuntimeSetup client,
                GuestBridgeSetup bridges,TurnipSetup turnip,Events events,Leases leases) {
            this.context=context;this.root=root;this.setup=setup;this.client=client;this.bridges=bridges;this.turnip=turnip;this.events=events;this.leases=leases;
        }
        public State state(){return state;}
        public IOException failure(){return failure;}
        public boolean isClientAlive(){OwnedProcess child=process;return child!=null&&child.isAlive();}
        public boolean needsForceStop(){return needsForce&&isClientAlive();}
        public boolean wasForced(){OwnedProcess child=process;return child!=null&&child.wasForced();}
        public boolean recoveryRequired(){return recovery;}
        /** A foreign/changed handoff is preserved after native dependencies stop;
         * this needs support/manual recovery, not another native force request. */
        public boolean handoffRecoveryRequired(){return handoffRecovery;}
        /** Process exit acknowledgment alone does not establish character saving. */
        public boolean clientExitAcknowledged(){return clientExitAcknowledged;}
        public ClientPresentationSession presentation(){return presentation;}
        /** Read-only fixed log selection survives known cleanup; no credential
         * record, database engine-private output or configuration is selected. */
        public java.util.Map<String,Path> diagnosticLogs() {
            java.util.Map<String,Path> result=new java.util.TreeMap<>();
            ServerDatabaseService.Handle db=database;LocalServerSession.Handle server=servers;ClientPresentationSession display=presentation;
            if(db!=null)db.diagnosticLogs().forEach((name,path)->result.put("game.database."+name+".log",path));
            if(server!=null)server.diagnosticLogs().forEach((name,path)->result.put("game.server."+name,path));
            if(display!=null)display.diagnosticLogs().forEach((name,path)->result.put("game.presentation."+name,path));
            return java.util.Collections.unmodifiableMap(result);
        }
        /** Observed native wrapper groups only. PRoot guest tracees can detach;
         * these observations never establish combined game/server/bot memory. */
        public java.util.Map<String,io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot> usage() {
            java.util.Map<String,io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot> result=new java.util.TreeMap<>();
            OwnedProcess child=process;if(child!=null)result.put("client-wrapper",child.usage());
            ServerDatabaseService.Handle db=database;if(db!=null)result.put("database-wrapper",db.usage());
            LocalServerSession.Handle server=servers;
            if(server!=null){var observed=server.usage();if(observed!=null)result.put("auth-world-wrapper",observed);}
            return java.util.Collections.unmodifiableMap(result);
        }
        /** Explicit user policy only, admitted after a graceful timeout/failure.
         * close() performs the actual bounded force/reap; this flag never saves. */
        public void requestForceStop()throws IOException {
            if(!needsForceStop())throw new IOException("Force stop is available only after unsuccessful graceful client shutdown");
            recovery=true;forceRequested.set(true);
        }
        public void start(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Game startup is single-use; retain and close this owner");
                state=State.STARTING;RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    check(stop);leases.client.require(root);setup.data.requireUnchanged();
                    ShaderSetup.Result shaders=ShaderSetup.requireCurrent(context,root,setup.wine,setup.shaderTools,setup.shaders);
                    ClientLaunchSetup.Prepared view=ClientLaunchSetup.prepareUnderOwnedLease(context,root,client,leases.client,updates,stop);
                    if(view==null||!view.plan.importedGeneration.equals(shaders.importGeneration))throw new IOException("Current client data and shaders differ; prepare local setup again");
                    var current=ServerInstallationSetup.completed(context,root,setup.server,setup.programs,setup.content);
                    if(!current.proofSha256.equals(setup.installation.proofSha256)||
                            !current.setupReceiptSha256.equals(setup.installation.setupReceiptSha256)||
                            !current.directoryFor(root).equals(setup.installation.directoryFor(root)))
                        throw new IOException("Promoted database selection changed after local setup");
                    check(stop);updates.update("game-database-starting","",0,-1);
                    database=ServerDatabaseService.startActive(context,root,setup.server,setup.installation);
                    try{ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),stop);}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Database startup interrupted; owner retained",error);}
                    check(stop);servers=LocalServerSession.begin(context,root,setup.server,setup.programs,setup.content,setup.installation,database,setup.data,code->notifyFailure(code));
                    StartupCancellation serverStartup=new StartupCancellation(stop);
                    servers.start(updates,serverStartup);serverStartup.handOff();check(stop);
                    // Presentation inspect recreates providers from the exact APK metadata;
                    // source compatibility above still binds the retained setup Wine.
                    ClientPresentationSession.Prepared display=ClientPresentationSession.Prepared.inspect(context,view.work);
                    if(!display.wineArchiveSha256.equals(setup.wine.archiveSha256())||!display.bridgeArchiveSha256.equals(bridges.archiveSha256()))
                        throw new IOException("Presentation provider selection changed after local setup");
                    presentation=ClientPresentationSession.begin(context,display,new ClientPresentationSession.Events(){
                        public void frameSize(int width,int height){if(events!=null)events.frameSize(width,height);}
                        public void failed(String code){notifyFailure(code);}
                    });
                    presentation.start();check(stop);
                    if(!servers.isReady()||!database.isAlive())throw new IOException("Owned local services exited before client startup");
                    ServerInstallationSetup.completed(context,root,setup.server,setup.programs,setup.content);
                    handoff=localLogin(root,setup,client,view,database.instanceUuid());
                    check(stop);setup.data.requireUnchanged();
                    process=presentation.startClient(client,view,shaders,turnip);
                    state=State.CLIENT_STARTED;updates.update("client-started-not-gameplay-qualified","",0,-1);
                    monitor=new Thread(this::monitor,"esteria-game-session-owner");monitor.setDaemon(true);monitor.start();return null;
                }catch(IOException|RuntimeException error){remember(error instanceof IOException?(IOException)error:new IOException("Game session startup failed"));state=State.FAILED;throw error;}
            });
        }
        private void monitor() {
            try {
                while(!operations.isStopRequested()) {
                    if(process==null)return;
                    if(!process.isAlive()){if(events!=null)events.clientExited(process.exitCode(),process.wasForced());return;}
                    if(process.failure()!=null){recovery=true;notifyFailure("game-client-owner-failed");return;}
                    if(database==null||!database.isAlive()||servers==null||!servers.isReady()||presentation==null||!presentation.isReady()) {
                        recovery=true;notifyFailure("game-session-dependency-failed");return;
                    }
                    Thread.sleep(100);
                }
            }catch(InterruptedException error){if(!operations.isStopRequested())notifyFailure("game-session-monitor-interrupted");}
        }
        private void notifyFailure(String code){remember(new IOException(code));if(events!=null)events.failed(code);}
        private synchronized void remember(IOException error){if(failure==null)failure=error;else if(failure!=error&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
        @Override public void close()throws IOException {close(Duration.ofSeconds(30));}
        /** No automatic force after Alt+F4. A live client keeps all lower
         * services, handoff and display bindings, import/view leases and owner.
         * Explicit requestForceStop permits actual kill/reap and marks recovery. */
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)throw new IllegalArgumentException("Game close timeout must be zero to30seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED){if(failure!=null)throw failure;return;}
                state=State.STOPPING;
                if(monitor!=null&&monitor!=Thread.currentThread()) {
                    monitor.interrupt();try{monitor.join(Math.min(1000,Math.max(1,permit.remaining().toMillis())));}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw retained("Game monitor close interrupted",error);}
                    if(monitor.isAlive())throw retained("Game monitor remains active",null);
                }
                stopClient(permit);
                IOException error=null;
                if(handoff!=null)try{handoff.close();handoff=null;}catch(IOException issue){error=issue;recovery=true;handoffRecovery=true;}
                if(presentation!=null)try{presentation.close(permit.remaining());}catch(IOException issue){error=add(error,issue);recovery=true;}
                if(presentation!=null&&!presentation.isClosed())throw retained("Presentation cleanup remains active",error);
                if(servers!=null&&servers.state()!=LocalServerSession.State.CLOSED) {
                    if(permit.remaining().compareTo(Duration.ofSeconds(10))<0)
                        throw retained("World/auth shutdown needs a fresh close budget; live services and database retained",error);
                    try{servers.close(permit.remaining());}catch(IOException issue){error=add(error,issue);recovery=true;}
                }
                if(servers!=null&&servers.state()!=LocalServerSession.State.CLOSED)throw retained("Local server cleanup remains active",error);
                if(database!=null&&database.isAlive()&&permit.remaining().compareTo(Duration.ofSeconds(5))<0)
                    throw retained("Database shutdown needs a fresh close budget; owned engine retained",error);
                if(database!=null)try{database.stop(permit.remaining());}catch(IOException issue){error=add(error,issue);recovery=true;}
                if(database!=null&&database.isAlive())throw retained("Database cleanup remains active",error);
                // With all native dependencies confirmed dead, preserve a
                // foreign/changed file and its explicit diagnostic, but release
                // playing/import ownership so support/import remains possible.
                // The strict CREATE_NEW handoff writer rejects reuse of this
                // same view until the preserved file is explicitly recovered.
                if(handoff!=null){handoffRecovery=true;handoff=null;}
                leases.close();state=State.CLOSED;OWNERS.remove(root,this);
                if(error!=null)remember(error);
                if(failure!=null)throw failure;
            }
        }
        private void stopClient(ServiceOperationGuard.StopPermit permit)throws IOException {
            OwnedProcess child=process;
            if(child!=null&&child.isAlive()) {
                if(forceRequested.get()) {
                    recovery=true;
                    try{child.stop(Duration.ZERO);}catch(IOException error){if(child.isAlive())throw retained("Forced client cleanup remains active",error);remember(error);}
                } else {
                    try{if(presentation==null)throw new IOException("Client close input is unavailable");presentation.requestClientClose();}
                    catch(IOException error){needsForce=true;throw retained("Normal client close request failed; client and dependencies retained",error);}
                    long deadline=System.nanoTime()+permit.remaining().toNanos();
                    while(child.isAlive()&&System.nanoTime()<deadline)try{Thread.sleep(Math.min(50,Math.max(1,TimeUnit.NANOSECONDS.toMillis(deadline-System.nanoTime()))));}
                        catch(InterruptedException error){Thread.currentThread().interrupt();needsForce=true;throw retained("Client graceful shutdown interrupted",error);}
                    if(child.isAlive()){needsForce=true;throw retained("Client did not acknowledge normal shutdown; explicit force stop or another close attempt is required",null);}
                }
            }
            if(child!=null) {
                if(child.isAlive()){needsForce=true;throw retained("Client cleanup remains active",null);}
                clientExitAcknowledged=child.exitCode()==0&&!child.wasForced()&&child.failure()==null&&!forceRequested.get();
                if(!clientExitAcknowledged){recovery=true;remember(new IOException("Client did not exit normally; recovery is required"));}
                needsForce=false;
            }
        }
        private IOException retained(String text,Throwable cause){IOException error=new IOException(text,cause);remember(error);return error;}
        private static IOException add(IOException first,IOException next){if(first==null)return next;if(first!=next&&first.getSuppressed().length<15)first.addSuppressed(next);return first;}
    }
    private static LocalAccountHandoff localLogin(Path root,LocalWorldSetup.Result setup,ClientRuntimeSetup client,
            ClientLaunchSetup.Prepared view,String uuid)throws IOException {
        Path state=setup.installation.directoryFor(root).resolve("state"),journal=state.resolve("accounts/local-player.json");
        byte[] raw=null;char[] username=null,password=null;
        try {
            byte[] setupBytes=read(state.resolve("server-setup-complete.json"),128<<10);
            if(!hash(setupBytes).equals(setup.installation.setupReceiptSha256))throw new IOException("Promoted account proof changed before local login");
            JSONObject complete=new JSONObject(new String(setupBytes,StandardCharsets.UTF_8));
            raw=read(journal,8192);JSONObject pin=complete.getJSONObject("localAccountJournal");
            if(pin.getLong("bytes")!=raw.length||!pin.getString("sha256").equals(hash(raw)))throw new IOException("Owned account journal differs from promoted setup proof");
            StructStat metadata=Os.lstat(journal.toString());
            if(!OsConstants.S_ISREG(metadata.st_mode)||metadata.st_uid!=android.os.Process.myUid()||metadata.st_nlink!=1||(metadata.st_mode&0777)!=0600)
                throw new IOException("Owned account journal must be an unshared private regular file");
            JSONObject intent=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            Set<String> fields=new java.util.HashSet<>();intent.keys().forEachRemaining(fields::add);
            if(!fields.equals(Set.of("formatVersion","serverRevision","mysqlUuid","mysqlVersion","phase","accountId","realmId","expansion","username","password","saltHex","verifierHex"))||
                    !Integer.valueOf(1).equals(intent.get("formatVersion"))||!"ready".equals(intent.get("phase"))||!uuid.equals(intent.get("mysqlUuid"))||
                    !setup.server.expectedMysqlVersion().equals(intent.get("mysqlVersion"))||!Integer.valueOf(1).equals(intent.get("realmId"))||!Integer.valueOf(2).equals(intent.get("expansion"))||
                    !setup.content.serverSource().getString("commit").equals(intent.get("serverRevision"))||intent.getLong("accountId")<=0||intent.getLong("accountId")>=1L<<32||
                    !intent.getString("username").matches("EST[0-9A-F]{14}")||!intent.getString("password").matches("[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{16}")||
                    !intent.getString("saltHex").matches("[0-9a-f]{64}")||!intent.getString("verifierHex").matches("[0-9a-f]{64}"))
                throw new IOException("Owned account journal is not ready for this exact database/source");
            username=intent.getString("username").toCharArray();password=intent.getString("password").toCharArray();
            return client.prepareLocalLogin(view.plan,view.view,username,password);
        }catch(JSONException|ErrnoException error){throw new IOException("Invalid private owned account journal; preserved");}
        finally{if(raw!=null)Arrays.fill(raw,(byte)0);if(username!=null)Arrays.fill(username,'\0');if(password!=null)Arrays.fill(password,'\0');}
    }
    private static byte[] read(Path path,int maximum)throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.equals(path.toRealPath())||Files.size(path)>maximum)throw new IOException("Private game-session metadata is missing or exceeds its bound");
        try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);var output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=input.read(buffer))!=-1;){if(output.size()+count>maximum)throw new IOException("Private game-session metadata grew beyond its bound");output.write(buffer,0,count);}return output.toByteArray();
        }
    }
    private static String hash(byte[] bytes)throws IOException {
        try{StringBuilder value=new StringBuilder(64);for(byte item:MessageDigest.getInstance("SHA-256").digest(bytes))value.append(String.format(java.util.Locale.ROOT,"%02x",item&255));return value.toString();}
        catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
    private static void check(RuntimeWork.Cancellation stop)throws RuntimeWork.CancelledException {if(stop.isCancelled()||Thread.currentThread().isInterrupted())throw new RuntimeWork.CancelledException();}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Game session lifecycle must run off the UI thread");}
}
