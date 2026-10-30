package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.core.runtime.process.WorldConsoleShutdown;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONException;
import org.json.JSONObject;

/** Retained auth/world owner over an already live promoted database. No launcher
 * action uses this adapter. Readiness proves local owned listeners/protocol/CLI,
 * never world entry, character/bot persistence, Android or gameplay qualification. */
public final class LocalServerSession {
    static final Set<String> HELPERS=Set.of("server_session.py","server_session_process.py",
        "android_server_schema_setup.py","mysql_bootstrap.py","mysql_service.py","server_content.py",
        "server_schema_setup.py","server_schema_baseline.py","server_schema_adaptations.py","server_update_setup.py",
        "server_updater.py","server_playerbots_setup.py","owned_process_group.py","server_config.py",
        "provision_local_realm.py","provision_local_account.py","server_data_generation.py","server_data_preflight.py",
        "shader_generation.py","extractor_order.py","server/appearance-schema-v1.sql","server/appearance-schema.lock.json","local-server.json");
    private static final ConcurrentHashMap<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private LocalServerSession(){ }
    public enum State { ALLOCATED,STARTING,READY,STOPPING,FAILED,CLOSED }
    /** Called on the retained worker, never with guest logs or credentials. */
    public interface Events { void failed(String code); }
    public static final class Result {
        public final String mysqlUuid,configurationGeneration;
        public final Path privateLogs;
        private Result(JSONObject receipt,Path logs)throws JSONException {
            mysqlUuid=receipt.getString("mysqlUuid");configurationGeneration=receipt.getString("configGeneration");privateLogs=logs;
        }
    }
    /** Allocate before native launch. The typed installation and data binding
     * cannot be replaced with caller-authored qualification booleans. */
    public static Handle begin(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
            ServerContentSetup content,FreshServerInstallations.Active active,ServerDatabaseService.Handle database,
            ServerDataBinding data,Events events)throws IOException {
        background();
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath())||active==null||database==null||data==null)
            throw new IOException("Owned promoted installation, data binding and database required");
        FreshServerInstallations.Active current=ServerInstallationSetup.completed(context,root,runtime,programs,content);
        Path work=active.directoryFor(root);
        if(!current.proofSha256.equals(active.proofSha256)||!current.directoryFor(root).equals(work)||
                !database.privateWorkDirectory().equals(work)||!active.mysqlUuid.equals(database.instanceUuid())||!database.isAlive())
            throw new IOException("Promoted installation and live database identities differ");
        if(runtime.current()==null||programs.current()==null||content.current()==null||
                !active.runtimeArchiveSha256.equals(runtime.packagePlan().archiveSha256))
            throw new IOException("Prepared pinned server providers required");
        programs.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        content.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);data.requireUnchanged();
        if(!data.directory.startsWith(root)||data.directory.equals(root)||!data.directory.equals(data.directory.toRealPath()))
            throw new IOException("Private canonical prepared data required");
        for(Path other:List.of(work,runtime.current(),programs.current(),content.current()))
            if(data.directory.startsWith(other)||other.startsWith(data.directory))throw new IOException("Prepared data overlaps a live provider/workspace");
        Path lockPath=work.resolve(".android-local-server-session.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid server session lock");
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(lockPath,"Local server session is already owned");
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            Handle owner=new Handle(context.getApplicationContext(),root,work,runtime,programs,content,active,database,data,events,lease);
            if(OWNERS.putIfAbsent(work,owner)!=null)throw new IOException("Previous local server ownership remains retained");
            return owner;
        }catch(IOException|RuntimeException|Error error){try{lease.close();}catch(IOException close){error.addSuppressed(close);}throw error;}
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,work;
        private final ServerRuntimeSetup runtime;
        private final ServerProgramsSetup programs;
        private final ServerContentSetup content;
        private final FreshServerInstallations.Active active;
        private final ServerDatabaseService.Handle database;
        private final ServerDataBinding data;
        private final Events events;
        private final ExclusiveFileLease lease;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private final AtomicBoolean stopping=new AtomicBoolean();
        private final CountDownLatch startup=new CountDownLatch(1),finished=new CountDownLatch(1);
        private volatile State state=State.ALLOCATED;
        private volatile OwnedProcess process;
        private volatile Thread worker;
        private volatile IOException failure;
        private volatile Result result;
        private volatile Path guestSession,logs;
        private Handle(Context context,Path root,Path work,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
                ServerContentSetup content,FreshServerInstallations.Active active,ServerDatabaseService.Handle database,
                ServerDataBinding data,Events events,ExclusiveFileLease lease) {
            this.context=context;this.root=root;this.work=work;this.runtime=runtime;this.programs=programs;this.content=content;
            this.active=active;this.database=database;this.data=data;this.events=events;this.lease=lease;
        }
        public State state(){return state;}
        public IOException failure(){return failure;}
        /** Fixed owned component logs; never private options/account/config. */
        public java.util.Map<String,Path> diagnosticLogs() {
            java.util.Map<String,Path> result=new java.util.TreeMap<>();Path wrapperLogs=logs;
            if(wrapperLogs!=null){result.put("helper.stdout.log",wrapperLogs.resolve("stdout.log"));
                result.put("helper.stderr.log",wrapperLogs.resolve("stderr.log"));}
            Path operation=guestSession;
            if(operation!=null){result.put("authserver.log",operation.resolve("authserver.log"));result.put("worldserver.log",operation.resolve("worldserver.log"));}
            return java.util.Collections.unmodifiableMap(result);
        }
        /** Null means the wrapper has not been allocated yet. */
        public io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot usage() {
            OwnedProcess child=process;
            return child==null?null:child.usage();
        }
        public boolean isReady(){return state==State.READY&&!stopping.get()&&process!=null&&process.isAlive()&&database.isAlive();}
        /** Keep this owner after every exception. The worker retains the same
         * database operation lease for the entire running auth/world session. */
        public Result start(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Local server startup is single-use");
                state=State.STARTING;
                worker=new Thread(()->run(progress,cancellation),"esteria-local-server-session");worker.setDaemon(true);worker.start();
                long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(12);
                while(startup.getCount()!=0) {
                    if(stopping.get()||(cancellation!=null&&cancellation.isCancelled())){stopping.set(true);throw new RuntimeWork.CancelledException();}
                    if(System.nanoTime()>=deadline){stopping.set(true);throw new IOException("Local server startup timed out; retained owner is stopping");}
                    try{startup.await(100,TimeUnit.MILLISECONDS);}catch(InterruptedException error){stopping.set(true);Thread.currentThread().interrupt();throw new IOException("Local server startup interrupted; owner retained",error);}
                }
                if(failure!=null)throw failure;
                if(result==null||!isReady())throw new IOException("Local server did not reach live owned readiness");
                return result;
            });
        }
        private void run(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation) {
            try {
                database.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->{
                    runGuest(serviceOperation,version,uuid,progress,cancellation);return null;
                });
            }catch(IOException|RuntimeException error){remember(error instanceof IOException?(IOException)error:new IOException("Local server owner failed",error));state=State.FAILED;}
            finally{startup.countDown();finished.countDown();}
            if(failure!=null&&events!=null)events.failed("local-server-session-failed");
        }
        private boolean stopRequested(RuntimeWork.Cancellation cancellation) {
            return stopping.get()||operations.isStopRequested()||database.schemaCancellationRequested()||
                (cancellation!=null&&cancellation.isCancelled());
        }
        private void runGuest(String serviceOperation,String version,String uuid,RuntimeWork.Progress progress,
                RuntimeWork.Cancellation cancellation)throws IOException {
            if(stopRequested(cancellation))throw new RuntimeWork.CancelledException();
            data.requireUnchanged();
            Path helpers=GuestHelperAssets.directory(work,"session-helpers");
            String helper=GuestHelperAssets.install(context,"server-session",helpers,HELPERS);
            String operation=UUID.randomUUID().toString().replace("-","");
            guestSession=directory(GuestHelperAssets.directory(work,"server-sessions").resolve(operation));
            Path outer=directory(GuestHelperAssets.directory(root,"state/server-session-runtime-operations").resolve(operation));logs=outer.resolve("logs");
            JSONObject selected;
            try {
                JSONObject profile=new JSONObject(new String(read(helpers.resolve(helper).resolve("local-server.json"),65536),StandardCharsets.UTF_8));
                JSONObject contentPin=identity(content.receiptPath(),16L<<20);
                if(!content.receiptSha256().equals(contentPin.getString("sha256")))throw new IOException("Prepared content receipt differs from APK selection");
                selected=new JSONObject().put("formatVersion",1).put("scope","android-owned-auth-world-selection")
                    .put("source",content.serverSource()).put("sourceLockSha256",content.sourceLockSha256())
                    .put("compiledModules",content.compiledModulesIdentity()).put("originalBuild",pin(programs.packagePlan(),"provenance/server-build.json"))
                    .put("contentReceipt",contentPin).put("profile",identity(helpers.resolve(helper).resolve("local-server.json"),65536))
                    .put("setupReceipt",new JSONObject().put("bytes",Files.size(work.resolve("state/server-setup-complete.json"))).put("sha256",active.setupReceiptSha256))
                    .put("activeProofSha256",active.proofSha256).put("dataInputs",data.inputs()).put("dataReceipt",data.receiptIdentity())
                    .put("programs",new JSONObject().put("authserver",pin(programs.packagePlan(),"bin/authserver")).put("worldserver",pin(programs.packagePlan(),"bin/worldserver")));
                // Reading the profile here also checks that an object, rather
                // than an arbitrary text payload, is selected by the APK pin.
                if(profile.length()==0)throw new IOException("Sealed local profile is empty");
                privateFile(guestSession.resolve("selection.json"),(selected.toString()+"\n").getBytes(StandardCharsets.UTF_8));
                privateFile(guestSession.resolve("content-receipt.json"),read(content.receiptPath(),16<<20));
            }catch(JSONException error){throw new IOException("Cannot bind local server selection",error);}
            if(stopRequested(cancellation))throw new RuntimeWork.CancelledException();
            if(progress!=null)progress.update("server-session-starting","",0,-1);
            process=ProotProcess.startInteractive(context,runtime.installer(),runtime.packagePlan(),work,outer,
                List.of("/usr/bin/python3","-B","-s","-E","/work/session-helpers/"+helper+"/server_session.py",
                    "--expected-version",version,"--operation-id",operation,"--service-operation-id",serviceOperation,"--instance-uuid",uuid),
                java.util.Collections.emptyMap(),List.of(new ProotLaunch.Mount(programs.current(),ServerProgramsSetup.guestMount()),
                    new ProotLaunch.Mount(content.current(),ServerContentSetup.guestMount()),new ProotLaunch.Mount(data.directory,"/esteria-data")),
                new WorldConsoleShutdown());
            try {
                while(process.isAlive()) {
                    if(stopRequested(cancellation)||!database.isAlive()) {
                        stopping.set(true);state=State.STOPPING;
                        try{process.stop(Duration.ofSeconds(30));}catch(IOException error){remember(error);if(process.isAlive())continue;}
                    }
                    Path ready=guestSession.resolve("ready.json");
                    if(result==null&&Files.exists(ready,LinkOption.NOFOLLOW_LINKS)&&!stopping.get()) {
                        JSONObject receipt=object(ready);ready(receipt,selected,operation,serviceOperation,uuid,version);
                        try{result=new Result(receipt,logs);}catch(JSONException error){throw new IOException(error);}
                        state=State.READY;startup.countDown();
                        if(progress!=null)progress.update("server-session-owned-listeners-ready","",1,1);
                    }
                    try{Thread.sleep(100);}catch(InterruptedException error){stopping.set(true);Thread.currentThread().interrupt();throw new IOException("Server session monitor interrupted",error);}
                }
                if(process.failure()!=null||process.wasForced()||process.exitCode()!=0)
                    throw new IOException("Local auth/world helper did not exit cleanly",process.failure());
                stopped(object(guestSession.resolve("stopped.json")),operation,serviceOperation,uuid,version,active.proofSha256);
            }finally {
                // Do not return/release the database lease while native cleanup
                // remains active. This retained worker is the retry mechanism.
                boolean interrupted=Thread.interrupted();
                while(process.isAlive())try{process.stop(Duration.ofSeconds(30));}
                    catch(IOException error){remember(error);if(process.isAlive())try{Thread.sleep(100);}catch(InterruptedException again){interrupted=true;}}
                if(interrupted)Thread.currentThread().interrupt();
            }
        }
        private synchronized void remember(IOException error){if(failure==null)failure=error;else if(failure!=error&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
        @Override public void close()throws IOException {close(Duration.ofSeconds(30));}
        /** Deadline failure retains process, worker, operation lock, providers
         * and the worker's database lease. Retry this exact owner later. */
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Session close timeout must be zero to30seconds");
            stopping.set(true);
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED){if(failure!=null)throw failure;return;}
                if(worker!=null)try{if(!finished.await(permit.remaining().toNanos(),TimeUnit.NANOSECONDS))throw new IOException("Local server cleanup remains active; database and session leases retained");}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Local server close interrupted; owner retained",error);}
                if(process!=null&&process.isAlive())throw new IOException("Local server native owner remains active; leases retained");
                lease.close();state=State.CLOSED;OWNERS.remove(work,this);
                if(failure!=null)throw failure;
            }
        }
    }
    private static void ready(JSONObject receipt,JSONObject selected,String operation,String serviceOperation,String uuid,String version)throws IOException {
        common(receipt,"owned-local-auth-world-session-not-gameplay-qualified",operation,serviceOperation,uuid,version);
        try {
            for(String flag:List.of("ownedAuthListenerVerified","ownedWorldListenerVerified","liveSqlAuthenticated","authChallengeProcessed","worldChallengeVerified","worldConsoleLoopVerified"))
                if(!Boolean.TRUE.equals(receipt.get(flag)))throw new IOException("Incomplete owned server readiness");
            if(!selected.get("activeProofSha256").equals(receipt.get("activeProofSha256"))||
                    !selected.get("sourceLockSha256").equals(receipt.get("sourceLockSha256"))||
                    !ServerDataBinding.canonical(selected.getJSONObject("contentReceipt")).equals(ServerDataBinding.canonical(receipt.getJSONObject("contentReceipt")))||
                    !ServerDataBinding.canonical(selected.getJSONObject("dataReceipt")).equals(ServerDataBinding.canonical(receipt.getJSONObject("dataReceipt")))||
                    !receipt.getString("configGeneration").matches("[0-9a-f]{64}"))throw new IOException("Owned server readiness selection differs");
        }catch(JSONException error){throw new IOException("Invalid server readiness receipt",error);}
    }
    private static void stopped(JSONObject receipt,String operation,String serviceOperation,String uuid,String version,String activeProof)throws IOException {
        common(receipt,"owned-local-auth-world-stopped",operation,serviceOperation,uuid,version);
        try {
            if(!activeProof.equals(receipt.get("activeProofSha256"))||!"command".equals(receipt.get("stopReason"))||!Boolean.TRUE.equals(receipt.get("ownedChildrenStopped"))||
                    !Boolean.TRUE.equals(receipt.get("worldConsoleShutdownAcknowledged"))||!Boolean.TRUE.equals(receipt.get("authSourceSignalShutdownAcknowledged"))||
                    !Boolean.FALSE.equals(receipt.get("databaseStopped"))||!Boolean.FALSE.equals(receipt.get("databaseRemoved"))||!receipt.isNull("failureType"))
                throw new IOException("Auth/world source shutdown was not acknowledged");
        }catch(JSONException error){throw new IOException("Invalid server stop receipt",error);}
    }
    private static void common(JSONObject receipt,String scope,String operation,String serviceOperation,String uuid,String version)throws IOException {
        try {
            Object format=receipt.get("formatVersion");
            if((!(format instanceof Integer)&&!(format instanceof Long))||((Number)format).longValue()!=1||!scope.equals(receipt.get("scope"))||!operation.equals(receipt.get("operationId"))||
                    !serviceOperation.equals(receipt.get("serviceOperationId"))||!uuid.equals(receipt.get("mysqlUuid"))||!version.equals(receipt.get("mysqlVersion")))
                throw new IOException("Server session identity differs");
            for(String flag:List.of("characterPersistenceQualified","botAiQualified","androidRuntimeQualified","gameplayQualified"))
                if(!Boolean.FALSE.equals(receipt.get(flag)))throw new IOException("Unqualified server session scope differs");
        }catch(JSONException error){throw new IOException("Invalid server session identity",error);}
    }
    private static JSONObject pin(RuntimePackagePlan plan,String name)throws IOException {var value=plan.required.get(name);if(value==null)throw new IOException("Pinned server component missing");try{return new JSONObject().put("bytes",value.bytes).put("sha256",value.sha256);}catch(JSONException error){throw new IOException(error);}}
    private static JSONObject identity(Path path,long maximum)throws IOException {try {byte[] bytes=read(path,(int)maximum);return new JSONObject().put("bytes",bytes.length).put("sha256",hex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes)));}catch(JSONException|java.security.NoSuchAlgorithmException error){throw new IOException(error);}}
    private static String hex(byte[] bytes){StringBuilder out=new StringBuilder(64);for(byte value:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();}
    private static JSONObject object(Path path)throws IOException {try{return new JSONObject(new String(read(path,16384),StandardCharsets.UTF_8));}catch(JSONException error){throw new IOException("Invalid private server receipt",error);}}
    private static byte[] read(Path path,int maximum)throws IOException {if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path)||Files.size(path)>maximum)throw new IOException("Invalid/bounded private server metadata required");try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);var out=new ByteArrayOutputStream()){byte[] block=new byte[8192];for(int count;(count=input.read(block))!=-1;){if(out.size()+count>maximum)throw new IOException("Server metadata grew beyond bound");out.write(block,0,count);}return out.toByteArray();}}
    private static void privateFile(Path path,byte[] bytes)throws IOException {try(var out=Files.newByteChannel(path,java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))){java.nio.ByteBuffer data=java.nio.ByteBuffer.wrap(bytes);while(data.hasRemaining())out.write(data);}}
    private static Path directory(Path path)throws IOException{return Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Server session lifecycle must run off the UI thread");}
}
