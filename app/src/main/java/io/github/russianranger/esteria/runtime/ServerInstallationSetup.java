package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONException;
import org.json.JSONObject;

/** Retained owner for the available real setup phases. No launcher action uses
 * this yet; playerbots qualification and complete promotion remain separate. */
public final class ServerInstallationSetup {
    private static final Set<String> HELPERS=Set.of("android_server_installation_setup.py","android_server_schema_setup.py",
        "mysql_bootstrap.py","mysql_service.py","server_content.py","server_schema_setup.py","server_schema_baseline.py",
        "server_schema_adaptations.py","server_update_setup.py","server_updater.py","server_playerbots_setup.py","owned_process_group.py","server_config.py",
        "provision_local_realm.py","provision_local_account.py","server/appearance-schema-v1.sql",
        "server/appearance-schema.lock.json","local-server.json");
    private ServerInstallationSetup(){ }
    public enum State { ALLOCATED,PREPARING,STAGED_PENDING_PLAYERBOTS,FAILED,CLOSED }
    public static final class Result {
        public final String instanceUuid,sourceLockSha256,configurationGeneration;
        public final Path privateProcessLogs;
        private Result(JSONObject report,Path logs) throws JSONException {
            instanceUuid=report.getString("mysqlUuid");sourceLockSha256=report.getString("sourceLockSha256");
            configurationGeneration=report.getString("configGeneration");privateProcessLogs=logs;
        }
    }
    /** Opens ownership before any native work, so callers retain this handle
     * across prepare failures. requiredFreeBytes is the caller's setup reserve;
     * serverData is its separate canonical imported-data directory (not qualified here). */
    public static Handle beginFresh(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
            ServerContentSetup content,Path serverData,long requiredFreeBytes) throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical application storage required");
        if(runtime.current()==null || programs.current()==null || content.current()==null)
            throw new IOException("Prepare the sealed server dependencies, programs and content first");
        if(!serverData.equals(serverData.toRealPath()) || !serverData.startsWith(root) || serverData.equals(root) ||
                !Files.isDirectory(serverData,LinkOption.NOFOLLOW_LINKS))throw new IOException("Separate private canonical server data required");
        for(Path installed:Arrays.asList(runtime.current(),programs.current(),content.current(),root.resolve("db"),
                root.resolve("state"),root.resolve("runtimes"),root.resolve("runtime-embedded-cache")))
            if(serverData.startsWith(installed) || installed.startsWith(serverData))
                throw new IOException("Imported server data must be separate from runtime and database workspaces");
        programs.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        content.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        if(!programs.sourceLockSha256().equals(content.sourceLockSha256()) ||
                !same(pin(programs.packagePlan(),"provenance/server-modules.json"),content.compiledModulesIdentity()))
            throw new IOException("Programs and content use different server source/module selections");
        FreshServerInstallations.Selection selected=new FreshServerInstallations.Selection(Map.of(
            "sourceLock",content.sourceLockSha256(),"runtimeArchive",runtime.packagePlan().archiveSha256,
            "programsArchive",programs.archiveSha256(),"contentReceipt",content.receiptSha256(),
            "compiledModules",sha(content.compiledModulesIdentity())));
        FreshServerInstallations.Attempt attempt=new FreshServerInstallations(root).begin(selected,requiredFreeBytes);
        try {return new Handle(context.getApplicationContext(),root,runtime,programs,content,serverData,attempt,attempt.retainWorkspace());}
        catch(IOException|RuntimeException error){attempt.close();throw error;}
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,data;
        private final ServerRuntimeSetup runtime;
        private final ServerProgramsSetup programs;
        private final ServerContentSetup content;
        private final FreshServerInstallations.Attempt attempt;
        private final FreshServerInstallations.Workspace workspace;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private ServerDatabaseService.Handle database;
        private OwnedProcess setupProcess;
        private ServerDatabaseSetup.BootstrapLease bootstrapLease;
        private FreshServerInstallations.Workspace setupProcessWorkspace;
        private Result result;
        private Handle(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,ServerContentSetup content,
                Path data,FreshServerInstallations.Attempt attempt,FreshServerInstallations.Workspace workspace) {
            this.context=context;this.root=root;this.runtime=runtime;this.programs=programs;this.content=content;
            this.data=data;this.attempt=attempt;this.workspace=workspace;
        }
        public State state(){return state;}
        public String slotId(){return attempt.slotId;}
        /** Off main thread. Keep this owner on every failure, then close/retry
         * shutdown; a timeout keeps the live engine and workspace leases held. */
        public Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation) throws IOException {
            return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("This fresh attempt has already run; retained state must not be replayed");
                state=State.PREPARING;
                RuntimeWork.Cancellation cancelled=()->operations.isStopRequested() || (cancellation!=null && cancellation.isCancelled());
                try {
                    check(cancelled);
                    setupProcessWorkspace=attempt.retainWorkspace();
                    ServerDatabaseSetup.Result bootstrap;
                    try {bootstrap=ServerDatabaseSetup.prepareFresh(context,root,runtime,workspace,progress,cancelled,
                            lease->{bootstrapLease=lease;});}
                    finally {releaseStoppedSetupProcess();}
                    if(bootstrap.cancellationRequested)throw new RuntimeWork.CancelledException();
                    check(cancelled);
                    database=ServerDatabaseService.startFresh(context,root,runtime,attempt);
                    try {ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),cancelled);}
                    catch(java.util.concurrent.CancellationException error){throw new RuntimeWork.CancelledException();}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Database readiness interrupted; owner retained",error);}
                    check(cancelled);
                    result=database.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->
                        runGuest(this,context,root,runtime,programs,content,data,database,serviceOperation,version,uuid,progress,cancelled));
                    state=State.STAGED_PENDING_PLAYERBOTS;return result;
                } catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
            });
        }
        /** Available only to a later owned playerbots phase in this package. */
        ServerDatabaseService.Handle retainedDatabase() throws IOException {
            if(state!=State.STAGED_PENDING_PLAYERBOTS || database==null || !database.isAlive())
                throw new IOException("Staged live database required");return database;
        }
        private void releaseStoppedSetupProcess() throws IOException {
            if(bootstrapLease!=null && (bootstrapLease.process()==null || !bootstrapLease.process().isAlive())) {
                bootstrapLease.close();bootstrapLease=null;
            }
            if(bootstrapLease==null && (setupProcess==null || !setupProcess.isAlive())) {
                if(setupProcessWorkspace!=null)setupProcessWorkspace.close();
                setupProcessWorkspace=null;setupProcess=null;
            }
        }
        @Override public void close() throws IOException {close(Duration.ofSeconds(20));}
        public void close(Duration timeout) throws IOException {
            if(timeout==null || timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Shutdown timeout must be zero to 30 seconds");
            if(state==State.CLOSED)return;
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED)return;
                IOException shutdownFailure=null;
                OwnedProcess helper=bootstrapLease!=null?bootstrapLease.process():setupProcess;
                if(helper!=null) {
                    try {helper.stop(permit.remaining());}
                    catch(IOException error){if(helper.isAlive())throw error;shutdownFailure=error;}
                    finally {releaseStoppedSetupProcess();}
                } else releaseStoppedSetupProcess();
                if(database!=null) {
                    try {database.stop(permit.remaining());}
                    catch(IOException error){if(database.isAlive())throw error;
                        if(shutdownFailure==null)shutdownFailure=error;else shutdownFailure.addSuppressed(error);}
                }
                workspace.close();
                try {attempt.abandon(shutdownFailure!=null || state==State.FAILED?"failed":"cancelled");}
                catch(IOException error){if(shutdownFailure==null)shutdownFailure=error;else shutdownFailure.addSuppressed(error);}
                try {attempt.close();state=State.CLOSED;}
                catch(IOException error){if(shutdownFailure==null)shutdownFailure=error;else shutdownFailure.addSuppressed(error);}
                if(shutdownFailure!=null)throw shutdownFailure;
            }
        }
    }
    private static Result runGuest(Handle owner,Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
            ServerContentSetup content,Path data,ServerDatabaseService.Handle service,String serviceOperation,String version,String uuid,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled) throws IOException {
        check(cancelled);Path work=service.privateWorkDirectory();
        String generation=GuestHelperAssets.install(context,"server-installation",GuestHelperAssets.directory(work,"installation-helpers"),HELPERS);
        String operation=UUID.randomUUID().toString().replace("-","");
        Path operationFiles=GuestHelperAssets.directory(work,"installation-operations").resolve(operation);createPrivate(operationFiles);
        Path processSession=GuestHelperAssets.directory(root,"state/server-installation-processes").resolve(operation);createPrivate(processSession);
        try {
            byte[] receipt=read(content.receiptPath(),16<<20);
            if(!hash(receipt).equals(content.receiptSha256()))throw new IOException("Server content receipt changed");
            write(operationFiles.resolve("content-receipt.json"),receipt);
            byte[] profile=asset(context,"server-installation/local-server.json",65536);
            JSONObject selected=new JSONObject().put("formatVersion",1).put("scope","android-owned-server-installation-selection")
                .put("source",content.serverSource()).put("sourceLockSha256",content.sourceLockSha256())
                .put("contentReceipt",identity(receipt)).put("compiledModules",content.compiledModulesIdentity())
                .put("program",pin(programs.packagePlan(),"bin/dbimport")).put("template",pin(programs.packagePlan(),"etc/dbimport.conf.dist"))
                .put("originalBuild",pin(programs.packagePlan(),"provenance/server-build.json")).put("profile",identity(profile));
            write(operationFiles.resolve("selection.json"),(selected.toString()+"\n").getBytes(StandardCharsets.UTF_8));check(cancelled);
            owner.setupProcessWorkspace=owner.attempt.retainWorkspace();
            OwnedProcess process;
            try {process=ProotProcess.start(context,runtime.installer(),runtime.packagePlan(),work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/installation-helpers/"+generation+"/android_server_installation_setup.py",
                    "--expected-version",version,"--operation-id",operation,"--service-operation-id",serviceOperation,"--instance-uuid",uuid),
                Collections.emptyMap(),Arrays.asList(new ProotLaunch.Mount(content.current(),ServerContentSetup.guestMount()),
                    new ProotLaunch.Mount(programs.current(),ServerProgramsSetup.guestMount()),new ProotLaunch.Mount(data,"/esteria-data")),null);
                owner.setupProcess=process;
            } catch(IOException|RuntimeException error){owner.releaseStoppedSetupProcess();throw error;}
            boolean cancelSeen=false;String lastProgress="";long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(90);
            try {
                while(process.isAlive()) {
                    if(!service.isAlive())throw new IOException("Owned database exited during setup; staging retained");
                    if((cancelled.isCancelled() || service.schemaCancellationRequested()) && !cancelSeen) {
                        write(operationFiles.resolve("cancel"),new byte[0]);cancelSeen=true;
                        if(progress!=null)progress.update("installation-finishing-safe-point","",0,-1);
                    }
                    Path path=operationFiles.resolve("progress.json");
                    if(progress!=null && Files.exists(path,LinkOption.NOFOLLOW_LINKS)) {
                        String current=new String(read(path,16384),StandardCharsets.UTF_8);
                        if(!current.equals(lastProgress)) {
                            JSONObject event=new JSONObject(current);String phase=event.getString("phase");
                            if(!phase.matches("[a-z][a-z0-9-]{0,79}"))throw new IOException("Invalid installation progress phase");
                            progress.update(phase,event.optString("path",""),event.optLong("bytes",event.optLong("files",0)),
                                event.optLong("totalBytes",event.optLong("totalFiles",-1)));lastProgress=current;
                        }
                    }
                    if(System.nanoTime()>=deadline)throw new IOException("Installation phase timed out; staging retained");
                    try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Installation interrupted; staging retained",error);}
                }
                if(process.failure()!=null)throw new IOException("Installation process ownership failed",process.failure());
                if(process.wasForced() || process.exitCode()!=0) {
                    if(cancelSeen && process.exitCode()==2 && !process.wasForced())throw new RuntimeWork.CancelledException();
                    throw new IOException("Installation helper failed (exit "+process.exitCode()+"); private staging retained");
                }
                JSONObject report=new JSONObject(new String(read(operationFiles.resolve("result.json"),256<<10),StandardCharsets.UTF_8));
                validate(report,selected,operation,serviceOperation,version,uuid);
                return new Result(report,processSession.resolve("logs"));
            } finally {
                try {
                    if(process.isAlive()) {
                        boolean interrupted=Thread.interrupted();try{process.stop(Duration.ZERO);}finally{if(interrupted)Thread.currentThread().interrupt();}
                    }
                } finally {owner.releaseStoppedSetupProcess();}
            }
        } catch(JSONException error){throw new IOException("Invalid installation metadata",error);}
    }
    private static void validate(JSONObject report,JSONObject selected,String operation,String serviceOperation,String version,String uuid) throws IOException,JSONException {
        if(report.getInt("formatVersion")!=1 || !"owned-server-installation-staged-pending-playerbots".equals(report.getString("scope")) ||
                !operation.equals(report.getString("operationId")) || !serviceOperation.equals(report.getString("serviceOperationId")) ||
                !version.equals(report.getString("mysqlVersion")) || !uuid.equals(report.getString("mysqlUuid")) ||
                !selected.getString("sourceLockSha256").equals(report.getString("sourceLockSha256")) ||
                !same(selected.getJSONObject("contentReceipt"),report.getJSONObject("contentReceipt")) ||
                !same(selected.getJSONObject("compiledModules"),report.getJSONObject("compiledModules")) ||
                !same(selected.getJSONObject("originalBuild"),report.getJSONObject("originalBuild")) ||
                !same(selected.getJSONObject("program"),report.getJSONObject("selectedProgram")) ||
                !report.getString("configGeneration").matches("[a-f0-9]{64}") || report.getInt("contentFilesVerified")<1 ||
                report.getJSONArray("pendingComponents").length()!=1 || !"playerbots-schema".equals(report.getJSONArray("pendingComponents").getString(0)))
            throw new IOException("Installation receipt differs from selected source and owned instance");
        for(String field:Set.of("baselineComplete","compiledUpdaterCompleted","sourceLedgersVerified","sameRevisionReentryVerified",
                "localRealmVerified","localAccountVerified","ownedServiceIdentityVerified"))
            if(!report.getBoolean(field))throw new IOException("Installation phase is incomplete");
        for(String field:Set.of("playerbotsSchemaVerified","completeSetupQualified","slotPromoted","databaseServiceStarted",
                "databaseServiceStopped","authserverExecuted","worldserverExecuted","serverDataQualified","androidRuntimeQualified","gameplayQualified"))
            if(report.getBoolean(field))throw new IOException("Unexpected complete setup or gameplay claim");
    }
    private static JSONObject pin(RuntimePackagePlan plan,String name) throws IOException {
        RuntimePackagePlan.RequiredFile file=plan.required.get(name);
        if(file==null)throw new IOException("Required server program provenance is missing");
        try{return new JSONObject().put("bytes",file.bytes).put("sha256",file.sha256);}catch(JSONException error){throw new IOException(error);}
    }
    private static String sha(JSONObject pin) throws IOException {try{return pin.getString("sha256");}catch(JSONException error){throw new IOException(error);}}
    private static boolean same(JSONObject first,JSONObject second) throws IOException {
        try{return first.getLong("bytes")==second.getLong("bytes") && first.getString("sha256").equals(second.getString("sha256"));}
        catch(JSONException error){throw new IOException(error);}
    }
    private static JSONObject identity(byte[] bytes) throws JSONException {return new JSONObject().put("bytes",bytes.length).put("sha256",hash(bytes));}
    private static byte[] asset(Context context,String name,int maximum) throws IOException {
        try(var stream=context.getAssets().open(name);var output=new java.io.ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=stream.read(buffer))!=-1;){if(output.size()+count>maximum)throw new IOException("Installation asset exceeds bound");output.write(buffer,0,count);}return output.toByteArray();
        }
    }
    private static byte[] read(Path path,int maximum) throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !path.equals(path.toRealPath()) || Files.size(path)>maximum)
            throw new IOException("Missing or oversized installation metadata");
        try(var stream=Files.newInputStream(path);var output=new java.io.ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=stream.read(buffer))!=-1;){if(output.size()+count>maximum)throw new IOException("Installation metadata exceeds bound");output.write(buffer,0,count);}return output.toByteArray();
        }
    }
    private static void createPrivate(Path path) throws IOException {Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));}
    private static void write(Path path,byte[] bytes) throws IOException {
        try(FileChannel file=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));java.nio.ByteBuffer buffer=java.nio.ByteBuffer.wrap(bytes);
            while(buffer.hasRemaining())file.write(buffer);file.force(true);
        }
        try(FileChannel folder=FileChannel.open(path.getParent(),StandardOpenOption.READ)){folder.force(true);}
    }
    private static String hash(byte[] bytes) {
        try{StringBuilder out=new StringBuilder();for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();}
        catch(NoSuchAlgorithmException impossible){throw new AssertionError(impossible);}
    }
    private static void check(RuntimeWork.Cancellation cancelled) throws RuntimeWork.CancelledException {if(cancelled.isCancelled())throw new RuntimeWork.CancelledException();}
}
