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

/** Retained owner for source-bound setup phases. No launcher action uses this;
 * a measured helper and a complete sealed programs provider are prerequisites. */
public final class ServerInstallationSetup {
    private static final Set<String> HELPERS=Set.of("android_server_installation_setup.py","android_server_schema_setup.py",
        "mysql_bootstrap.py","mysql_service.py","server_content.py","server_schema_setup.py","server_schema_baseline.py",
        "server_schema_adaptations.py","server_update_setup.py","server_updater.py","server_playerbots_setup.py","owned_process_group.py","server_config.py",
        "provision_local_realm.py","provision_local_account.py","server/appearance-schema-v1.sql",
        "server/appearance-schema.lock.json","local-server.json");
    private ServerInstallationSetup(){ }
    private static final String VERIFIED_SCOPE="owned-server-installation-four-schemas-verified";
    private static final String COMPLETE_SCOPE="owned-server-installation-four-schemas-cleanly-stopped";
    public enum State { ALLOCATED,PREPARING,STAGED_PENDING_PLAYERBOTS,VERIFYING_PLAYERBOTS,SCHEMAS_VERIFIED,PROMOTED,FAILED,CLOSED }
    public static final class Result {
        public final String instanceUuid,sourceLockSha256,configurationGeneration;
        public final Path privateProcessLogs;
        private final String reportJson;
        private Result(JSONObject report,Path logs) throws JSONException {
            instanceUuid=report.getString("mysqlUuid");sourceLockSha256=report.getString("sourceLockSha256");
            configurationGeneration=report.getString("configGeneration");privateProcessLogs=logs;reportJson=report.toString();
        }
    }
    /** Internal source-admitted inputs. Ordinary entry points always construct
     * ProductionInputs. The separate debug fixture must admit its exact actual
     * build/source/SQL receipts before it can implement this contract; no Intent
     * or caller-authored completion flag is accepted by the coordinator. */
    interface InstalledInputs {
        ServerDatabaseService.InstallationRuntime runtime();
        void requireCurrentSelection()throws IOException;
        Path programsDirectory()throws IOException;
        RuntimePackagePlan programsPlan();
        String programsArchiveSha256();
        Path contentDirectory()throws IOException;
        Path contentReceiptPath()throws IOException;
        String contentReceiptSha256();
        String sourceLockSha256();
        JSONObject serverSource()throws IOException;
        JSONObject compiledModulesIdentity()throws IOException;
        JSONObject measuredPlayerbotsSelection()throws IOException;
        default HelperSelection helpers()throws IOException{return new HelperSelection("server-installation",HELPERS,"android_server_installation_setup.py");}
    }
    static final class HelperSelection {
        final String prefix,entry;final Set<String> files;
        HelperSelection(String prefix,Set<String> files,String entry)throws IOException {
            if(prefix==null||!prefix.matches("[a-z-]+")||files==null||files.isEmpty()||files.size()>32||
                    entry==null||!entry.matches("[a-z][a-z0-9_]*\\.py")||!files.contains(entry)||!files.contains("local-server.json"))
                throw new IOException("Fixed source-owned installation helper selection required");
            this.prefix=prefix;this.files=Set.copyOf(files);this.entry=entry;
        }
    }
    private static final class ProductionInputs implements InstalledInputs {
        private final ServerRuntimeSetup runtime;
        private final ServerProgramsSetup programs;
        private final ServerContentSetup content;
        private final ServerDatabaseService.InstallationRuntime installedRuntime;
        ProductionInputs(Context context,ServerRuntimeSetup runtime,ServerProgramsSetup programs,ServerContentSetup content) {
            this.runtime=runtime;this.programs=programs;this.content=content;
            installedRuntime=ServerDatabaseService.installedRuntime(context,runtime);
        }
        public ServerDatabaseService.InstallationRuntime runtime(){return installedRuntime;}
        public void requireCurrentSelection()throws IOException {
            if(runtime==null||programs==null||content==null||runtime.current()==null||programs.current()==null||content.current()==null)
                throw new IOException("Sealed immutable server dependencies, programs and content are required");
            programs.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);content.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
            if(!programs.sourceLockSha256().equals(content.sourceLockSha256())||
                    !same(pin(programs.packagePlan(),"provenance/server-modules.json"),content.compiledModulesIdentity()))
                throw new IOException("Programs and content source/module selections differ");
        }
        public Path programsDirectory()throws IOException{return programs.current();}
        public RuntimePackagePlan programsPlan(){return programs.packagePlan();}
        public String programsArchiveSha256(){return programs.archiveSha256();}
        public Path contentDirectory()throws IOException{return content.current();}
        public Path contentReceiptPath()throws IOException{return content.receiptPath();}
        public String contentReceiptSha256(){return content.receiptSha256();}
        public String sourceLockSha256(){return content.sourceLockSha256();}
        public JSONObject serverSource()throws IOException{return content.serverSource();}
        public JSONObject compiledModulesIdentity()throws IOException{return content.compiledModulesIdentity();}
        public JSONObject measuredPlayerbotsSelection()throws IOException{return playerbotsSelection(programs);}
    }
    /** Opens ownership before any native work, so callers retain this handle
     * across prepare failures. requiredFreeBytes is the caller's setup reserve;
     * serverData is its separate canonical imported-data directory (not qualified here). */
    public static Handle beginFresh(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
            ServerContentSetup content,Path serverData,long requiredFreeBytes) throws IOException {
        return beginInstalled(context,root,new ProductionInputs(context,runtime,programs,content),serverData,requiredFreeBytes);
    }
    static Handle beginInstalled(Context context,Path root,InstalledInputs inputs,Path serverData,long requiredFreeBytes)throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical application storage required");
        if(inputs==null)throw new IOException("Admitted installation inputs are required");
        inputs.requireCurrentSelection();ServerDatabaseService.InstallationRuntime runtime=inputs.runtime();
        if(!serverData.equals(serverData.toRealPath()) || !serverData.startsWith(root) || serverData.equals(root) ||
                !Files.isDirectory(serverData,LinkOption.NOFOLLOW_LINKS))throw new IOException("Separate private canonical server data required");
        for(Path installed:Arrays.asList(runtime.current(),inputs.programsDirectory(),inputs.contentDirectory(),root.resolve("db"),
                root.resolve("state"),root.resolve("runtimes"),root.resolve("runtime-embedded-cache")))
            if(serverData.startsWith(installed) || installed.startsWith(serverData))
                throw new IOException("Imported server data must be separate from runtime and database workspaces");
        FreshServerInstallations.Selection selected=selection(inputs);
        FreshServerInstallations.Attempt attempt=new FreshServerInstallations(root).begin(selected,requiredFreeBytes);
        try {return new Handle(context.getApplicationContext(),root,inputs,serverData,attempt,attempt.retainWorkspace());}
        catch(IOException|RuntimeException error){attempt.close();throw error;}
    }
    /** Resolves only a proof-bound promoted database. It does not start a service,
     * qualify game data or accept a caller-authored completion Boolean. */
    public static FreshServerInstallations.Active completed(Context context,Path root,ServerRuntimeSetup runtime,
            ServerProgramsSetup programs,ServerContentSetup content) throws IOException {
        FreshServerInstallations.Active active=completedOrNull(context,root,runtime,programs,content);
        if(active==null)throw new IOException("A complete source-bound fresh installation is required");
        return active;
    }
    /** Absence alone returns null. An incompatible, partial or changed active
     * installation still throws; callers must never catch it and initialize a
     * replacement database. Checks the measured helper before allocating SQL. */
    public static FreshServerInstallations.Active completedOrNull(Context context,Path root,ServerRuntimeSetup runtime,
            ServerProgramsSetup programs,ServerContentSetup content) throws IOException {
        return completedInstalledOrNull(context,root,new ProductionInputs(context,runtime,programs,content));
    }
    static FreshServerInstallations.Active completedInstalledOrNull(Context context,Path root,InstalledInputs inputs)throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical application storage required");
        JSONObject helper=inputs.measuredPlayerbotsSelection();
        FreshServerInstallations.Active active=new FreshServerInstallations(root).active(selection(inputs));
        if(active==null) {
            if(Files.exists(root.resolve("state/server-work"),LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Legacy server state is retained; explicit migration is required before local world setup");
            return null;
        }
        Path work=active.directoryFor(root);
        try {
            byte[] raw=read(work.resolve("state/server-setup-complete.json"),128<<10);
            if(!hash(raw).equals(active.setupReceiptSha256))throw new IOException("Promoted setup receipt differs from its proof");
            JSONObject report=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            validateComplete(report,helper,active.mysqlUuid,inputs.runtime().expectedMysqlVersion());
            requireRecordedFile(work.resolve("state/server-installation-verified.json"),report.getJSONObject("fourSchemaReceipt"));
            if(!inputs.sourceLockSha256().equals(report.getString("sourceLockSha256")) ||
                    !same(inputs.compiledModulesIdentity(),report.getJSONObject("compiledModules")) ||
                    !inputs.contentReceiptSha256().equals(report.getJSONObject("contentReceipt").getString("sha256")) ||
                    !same(pin(inputs.programsPlan(),"provenance/server-build.json"),report.getJSONObject("originalBuild")))
                throw new IOException("Promoted setup source/content selection differs");
            String operation=report.getString("serviceOperationId");
            Path stopped=work.resolve("mysql-sessions").resolve(operation).resolve("stopped.json");
            requireRecordedFile(stopped,report.getJSONObject("stoppedReceipt"));
            validateStopped(new JSONObject(new String(read(stopped,128<<10),StandardCharsets.UTF_8)),operation,
                report.getString("mysqlVersion"),active.mysqlUuid);
            for(Map.Entry<String,String> entry:Map.of("sourceBaselineJournal",".server-schema-initialization.json",
                    "compiledUpdaterJournal",".server-compiled-updater.json","playerbotsSchemaJournal",".server-playerbots-schema.json",
                    "localAccountJournal","accounts/local-player.json","stagedInstallationReceipt","server-installation-staged.json",
                    "playerbotsFinishJournal",".server-playerbots-finish.json").entrySet())
                requireRecordedFile(work.resolve("state").resolve(entry.getValue()),report.getJSONObject(entry.getKey()));
            return active;
        } catch(JSONException error){throw new IOException("Invalid promoted installation receipt",error);}
    }
    private static FreshServerInstallations.Selection selection(InstalledInputs inputs) throws IOException {
        inputs.requireCurrentSelection();
        return new FreshServerInstallations.Selection(Map.of("sourceLock",inputs.sourceLockSha256(),
            "runtimeArchive",inputs.runtime().archiveSha256(),"programsArchive",inputs.programsArchiveSha256(),
            "contentReceipt",inputs.contentReceiptSha256(),"compiledModules",sha(inputs.compiledModulesIdentity())));
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,data;
        private final ServerDatabaseService.InstallationRuntime runtime;
        private final InstalledInputs inputs;
        private final FreshServerInstallations.Attempt attempt;
        private final FreshServerInstallations.Workspace workspace;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private ServerDatabaseService.Handle database;
        private OwnedProcess setupProcess;
        private volatile Map<String,Path> diagnosticLogs=Map.of();
        private ServerDatabaseSetup.BootstrapLease bootstrapLease;
        private FreshServerInstallations.Workspace setupProcessWorkspace;
        private Result result;
        private boolean promotionAttempted;
        private Handle(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,ServerContentSetup content,
                Path data,FreshServerInstallations.Attempt attempt,FreshServerInstallations.Workspace workspace) {
            this(context,root,new ProductionInputs(context,runtime,programs,content),data,attempt,workspace);
        }
        private Handle(Context context,Path root,InstalledInputs inputs,Path data,FreshServerInstallations.Attempt attempt,
                FreshServerInstallations.Workspace workspace) {
            this.context=context;this.root=root;this.inputs=inputs;this.runtime=inputs.runtime();
            this.data=data;this.attempt=attempt;this.workspace=workspace;
        }
        public State state(){return state;}
        /** Wrapper streams only. Engine-private capture and account/config files are excluded. */
        public Map<String,Path> diagnosticLogs(){return diagnosticLogs;}
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
                    inputs.requireCurrentSelection();
                    setupProcessWorkspace=attempt.retainWorkspace();
                    ServerDatabaseSetup.Result bootstrap;
                    try {bootstrap=ServerDatabaseSetup.prepareFreshInstalled(context,root,runtime,workspace,progress,cancelled,
                            lease->{bootstrapLease=lease;});}
                    finally {releaseStoppedSetupProcess();}
                    if(bootstrap.cancellationRequested)throw new RuntimeWork.CancelledException();
                    check(cancelled);
                    database=ServerDatabaseService.startFreshInstalled(context,root,runtime,attempt);
                    try {ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),cancelled);}
                    catch(java.util.concurrent.CancellationException error){throw new RuntimeWork.CancelledException();}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Database readiness interrupted; owner retained",error);}
                    check(cancelled);
                    result=database.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->
                        runGuest(this,context,root,inputs,data,database,serviceOperation,version,uuid,progress,cancelled,false));
                    state=State.STAGED_PENDING_PLAYERBOTS;return result;
                } catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
            });
        }
        /** Runs the fourth-schema phase only when the sealed immutable provider
         * contains the measured helper and both provenance receipts. */
        public Result finishPlayerbots(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation) throws IOException {
            return operations.run(()->{
                if(state!=State.STAGED_PENDING_PLAYERBOTS || database==null || !database.isAlive())
                    throw new IOException("A staged owned live database is required before playerbots setup");
                // Current three-program providers refuse here, before SQL or a new process.
                inputs.measuredPlayerbotsSelection();selection(inputs);
                state=State.VERIFYING_PLAYERBOTS;
                RuntimeWork.Cancellation cancelled=()->operations.isStopRequested() || (cancellation!=null && cancellation.isCancelled());
                try {
                    check(cancelled);
                    result=database.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->
                        runGuest(this,context,root,inputs,data,database,serviceOperation,version,uuid,progress,cancelled,true));
                    state=State.SCHEMAS_VERIFIED;return result;
                } catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
            });
        }
        /** Stops the retained engine, checks its real acknowledgment, and only
         * then writes the bound marker and atomically promotes this fresh slot. */
        public FreshServerInstallations.Active stopAndPromote(Duration timeout) throws IOException {
            if(timeout==null || timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Shutdown timeout must be zero to 30 seconds");
            return operations.run(()->{
                if(state!=State.SCHEMAS_VERIFIED || result==null || database==null)
                    throw new IOException("Live four-schema verification is required before clean-stop promotion");
                JSONObject helper=inputs.measuredPlayerbotsSelection();
                selection(inputs);
                try {
                    // Refresh live four-schema checks immediately before shutdown.
                    // Completed finish reentry cannot replay its updater or loader.
                    result=database.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->
                        runGuest(this,context,root,inputs,data,database,serviceOperation,version,uuid,null,
                            ()->operations.isStopRequested(),true));
                    JSONObject verified=new JSONObject(result.reportJson);
                    String operation=verified.getString("serviceOperationId"),version=verified.getString("mysqlVersion"),uuid=verified.getString("mysqlUuid");
                    Path work=database.privateWorkDirectory();
                    JSONObject stored=new JSONObject(new String(read(work.resolve("state/server-installation-verified.json"),128<<10),StandardCharsets.UTF_8));
                    JSONObject expected=new JSONObject(result.reportJson);expected.remove("operationId");expected.remove("serviceOperationId");
                    if(!ServerSourceSelection.sameJson(stored,expected))throw new IOException("Four-schema verification receipt changed");
                    database.stop(timeout);
                    if(database.isAlive())throw new IOException("A live database cannot be promoted");
                    Path stoppedPath=database.privateSessionDirectory().resolve("stopped.json");
                    JSONObject stopped=new JSONObject(new String(read(stoppedPath,128<<10),StandardCharsets.UTF_8));
                    validateStopped(stopped,operation,version,uuid);
                    JSONObject complete=new JSONObject(stored.toString()).put("scope",COMPLETE_SCOPE)
                        .put("completeSetupQualified",true).put("engineStopped",true).put("cleanEngineStopped",true)
                        .put("databaseServiceStopped",true).put("pendingComponents",new org.json.JSONArray())
                        .put("serviceOperationId",operation).put("fourSchemaReceipt",identity(read(work.resolve("state/server-installation-verified.json"),128<<10)))
                        .put("stoppedReceipt",identity(read(stoppedPath,128<<10)));
                    validateComplete(complete,helper,uuid,version);
                    Path completePath=work.resolve("state/server-setup-complete.json");
                    write(completePath,(complete.toString()+"\n").getBytes(StandardCharsets.UTF_8));
                    String bootstrap=hash(read(work.resolve("state/database-bootstrap.json"),128<<10));
                    Map<String,Boolean> flags=Map.of("baselineComplete",true,"compiledUpdaterComplete",true,"coreLedgersVerified",true,
                        "sameRevisionReentryVerified",true,"localRealmVerified",true,"localAccountVerified",true,
                        "playerbotsSchemaVerified",true,"cleanEngineStopped",true);
                    FreshServerInstallations.PromotionProof proof=new FreshServerInstallations.PromotionProof(attempt.selection,uuid,version,operation,
                        bootstrap,hash(read(stoppedPath,128<<10)),hash(read(completePath,128<<10)),flags);
                    releaseStoppedSetupProcess();workspace.close();promotionAttempted=true;
                    FreshServerInstallations.Active active=attempt.promote(proof);attempt.close();state=State.PROMOTED;return active;
                } catch(JSONException error){state=State.FAILED;throw new IOException("Invalid four-schema or stopped receipt",error);}
                catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
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
                if(!promotionAttempted) {
                    try {attempt.abandon(shutdownFailure!=null || state==State.FAILED?"failed":"cancelled");}
                    catch(IOException error){if(shutdownFailure==null)shutdownFailure=error;else shutdownFailure.addSuppressed(error);}
                }
                try {attempt.close();state=State.CLOSED;}
                catch(IOException error){if(shutdownFailure==null)shutdownFailure=error;else shutdownFailure.addSuppressed(error);}
                if(shutdownFailure!=null)throw shutdownFailure;
            }
        }
    }
    private static Result runGuest(Handle owner,Context context,Path root,InstalledInputs inputs,
            Path data,ServerDatabaseService.Handle service,String serviceOperation,String version,String uuid,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled,boolean playerbots) throws IOException {
        check(cancelled);Path work=service.privateWorkDirectory();
        inputs.requireCurrentSelection();HelperSelection helpers=inputs.helpers();
        String generation=GuestHelperAssets.install(context,helpers.prefix,GuestHelperAssets.directory(work,"installation-helpers"),helpers.files);
        String operation=UUID.randomUUID().toString().replace("-","");
        Path operationFiles=GuestHelperAssets.directory(work,"installation-operations").resolve(operation);createPrivate(operationFiles);
        Path processSession=GuestHelperAssets.directory(root,"state/server-installation-processes").resolve(operation);createPrivate(processSession);
        owner.diagnosticLogs=Map.of("setup.installation.stdout.log",processSession.resolve("logs/stdout.log"),
            "setup.installation.stderr.log",processSession.resolve("logs/stderr.log"));
        try {
            byte[] receipt=read(inputs.contentReceiptPath(),16<<20);
            if(!hash(receipt).equals(inputs.contentReceiptSha256()))throw new IOException("Server content receipt changed");
            write(operationFiles.resolve("content-receipt.json"),receipt);
            byte[] profile=asset(context,helpers.prefix+"/local-server.json",65536);
            JSONObject selected=new JSONObject().put("formatVersion",1).put("scope","android-owned-server-installation-selection")
                .put("source",inputs.serverSource()).put("sourceLockSha256",inputs.sourceLockSha256())
                .put("contentReceipt",identity(receipt)).put("compiledModules",inputs.compiledModulesIdentity())
                .put("program",pin(inputs.programsPlan(),"bin/dbimport")).put("template",pin(inputs.programsPlan(),"etc/dbimport.conf.dist"))
                .put("originalBuild",pin(inputs.programsPlan(),"provenance/server-build.json")).put("profile",identity(profile));
            if(playerbots)selected.put("playerbotsHelper",inputs.measuredPlayerbotsSelection());
            write(operationFiles.resolve("selection.json"),(selected.toString()+"\n").getBytes(StandardCharsets.UTF_8));check(cancelled);
            owner.setupProcessWorkspace=owner.attempt.retainWorkspace();
            OwnedProcess process;
            try {process=inputs.runtime().launch(work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/installation-helpers/"+generation+"/"+helpers.entry,
                    "--expected-version",version,"--operation-id",operation,"--service-operation-id",serviceOperation,"--instance-uuid",uuid,
                    "--phase",playerbots?"playerbots":"core"),
                Arrays.asList(new ProotLaunch.Mount(inputs.contentDirectory(),ServerContentSetup.guestMount()),
                    new ProotLaunch.Mount(inputs.programsDirectory(),ServerProgramsSetup.guestMount()),new ProotLaunch.Mount(data,"/esteria-data")));
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
                validate(report,selected,operation,serviceOperation,version,uuid,playerbots);
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
    private static void validate(JSONObject report,JSONObject selected,String operation,String serviceOperation,String version,String uuid,boolean playerbots) throws IOException,JSONException {
        if(report.getInt("formatVersion")!=1 || !(playerbots?VERIFIED_SCOPE:"owned-server-installation-staged-pending-playerbots").equals(report.getString("scope")) ||
                !operation.equals(report.getString("operationId")) || !serviceOperation.equals(report.getString("serviceOperationId")) ||
                !version.equals(report.getString("mysqlVersion")) || !uuid.equals(report.getString("mysqlUuid")) ||
                !selected.getString("sourceLockSha256").equals(report.getString("sourceLockSha256")) ||
                !same(selected.getJSONObject("contentReceipt"),report.getJSONObject("contentReceipt")) ||
                !same(selected.getJSONObject("compiledModules"),report.getJSONObject("compiledModules")) ||
                !same(selected.getJSONObject("originalBuild"),report.getJSONObject("originalBuild")) ||
                !same(selected.getJSONObject("program"),report.getJSONObject("selectedProgram")) ||
                !report.getString("configGeneration").matches("[a-f0-9]{64}") || (!playerbots && report.getInt("contentFilesVerified")<1) ||
                report.getJSONArray("pendingComponents").length()!=1 || !(playerbots?"owned-clean-engine-stop":"playerbots-schema").equals(report.getJSONArray("pendingComponents").getString(0)))
            throw new IOException("Installation receipt differs from selected source and owned instance");
        for(String field:Set.of("baselineComplete","compiledUpdaterCompleted","sourceLedgersVerified","sameRevisionReentryVerified",
                "localRealmVerified","localAccountVerified","ownedServiceIdentityVerified"))
            if(!report.getBoolean(field))throw new IOException("Installation phase is incomplete");
        if(playerbots) {
            requireFlag(report,"playerbotsSchemaVerified",true);requireFlag(report,"fourSchemasVerified",true);requireFlag(report,"engineStopped",false);
            validateHelper(report,selected.getJSONObject("playerbotsHelper"));
        } else requireFlag(report,"playerbotsSchemaVerified",false);
        for(String field:Set.of("completeSetupQualified","slotPromoted","databaseServiceStarted",
                "databaseServiceStopped","authserverExecuted","worldserverExecuted","serverDataQualified","androidRuntimeQualified","gameplayQualified"))
            if(report.getBoolean(field))throw new IOException("Unexpected complete setup or gameplay claim");
    }
    private static JSONObject playerbotsSelection(ServerProgramsSetup programs) throws IOException {
        if(programs==null || programs.current()==null)throw new IOException("A sealed measured playerbots helper provider is required");
        RuntimePackagePlan plan=programs.packagePlan();
        RuntimePackagePlan.RequiredFile executable=plan.required.get("helpers/playerbots-schema");
        if(executable==null || executable.elfMachine!=183 || executable.bytes<=0 || executable.bytes>(64L<<20))
            throw new IOException("This sealed programs provider has no measured playerbots helper");
        try {
            JSONObject selected=new JSONObject().put("executable",pin(plan,"helpers/playerbots-schema"))
                .put("buildReceipt",pin(plan,"provenance/playerbots-helper-build.json"))
                .put("nativeReceipt",pin(plan,"provenance/playerbots-native-sql.json"));
            Path installed=programs.current();
            requireRecordedFile(installed.resolve("provenance/playerbots-helper-build.json"),selected.getJSONObject("buildReceipt"));
            requireRecordedFile(installed.resolve("provenance/playerbots-native-sql.json"),selected.getJSONObject("nativeReceipt"));
            JSONObject build=new JSONObject(new String(read(installed.resolve("provenance/playerbots-helper-build.json"),128<<10),StandardCharsets.UTF_8));
            JSONObject nativeProof=new JSONObject(new String(read(installed.resolve("provenance/playerbots-native-sql.json"),128<<10),StandardCharsets.UTF_8));
            if(!"source-built-playerbots-schema-helper".equals(build.getString("scope")) ||
                    !"disposable-native-arm64-product-playerbots-schema".equals(nativeProof.getString("scope")) ||
                    !same(build.getJSONObject("executable"),selected.getJSONObject("executable")) ||
                    !same(nativeProof.getJSONObject("helperExecutable"),selected.getJSONObject("executable")) ||
                    !same(nativeProof.getJSONObject("helperBuildReceipt"),selected.getJSONObject("buildReceipt")) ||
                    !same(build.getJSONObject("originalBuild"),pin(plan,"provenance/server-build.json")) ||
                    !same(build.getJSONObject("originalModules"),pin(plan,"provenance/server-modules.json")) ||
                    !same(build.getJSONObject("sourceLock"),pin(plan,"provenance/sources.lock.json")) ||
                    build.getInt("preparedStatementCountDeclared")!=52 || nativeProof.getInt("preparedStatementCount")!=52)
                throw new IOException("Measured playerbots helper source or native proof differs");
            requireFlag(build,"actualCompileSucceeded",true);requireFlag(build,"actualDatabaseSourcesAndDefinitionVerified",true);
            requireFlag(nativeProof,"qualificationSucceeded",true);requireFlag(nativeProof,"restartPersistenceVerified",true);
            requireFlag(nativeProof,"finalFourSchemaProductVerification",true);requireFlag(nativeProof,"cleanShutdownVerified",true);
            for(String name:Set.of("playerbotsAiQualified","androidRuntimeQualified","gameplayQualified")) {
                requireFlag(build,name,false);requireFlag(nativeProof,name,false);
            }
            return selected;
        } catch(JSONException error){throw new IOException("Invalid playerbots helper provenance",error);}
    }
    private static void validateHelper(JSONObject report,JSONObject helper) throws IOException,JSONException {
        if(!same(report.getJSONObject("helperExecutable"),helper.getJSONObject("executable")) ||
                !same(report.getJSONObject("helperBuildReceipt"),helper.getJSONObject("buildReceipt")) ||
                !same(report.getJSONObject("helperNativeReceipt"),helper.getJSONObject("nativeReceipt")))
            throw new IOException("Four-schema helper selection differs");
    }
    private static void requireFlag(JSONObject object,String name,boolean expected) throws IOException,JSONException {
        Object value=object.get(name);
        if(!(value instanceof Boolean) || !Boolean.valueOf(expected).equals(value))
            throw new IOException("Invalid source-bound installation state: "+name);
    }
    private static void validateStopped(JSONObject stopped,String operation,String version,String uuid) throws IOException,JSONException {
        if(stopped.getInt("formatVersion")!=1 || !"owned-local-mysql-stopped".equals(stopped.getString("scope")) ||
                !operation.matches("[a-f0-9]{32}") || !operation.equals(stopped.getString("operationId")) ||
                !version.equals(stopped.getString("version")) || !uuid.equals(stopped.getString("uuid")) ||
                !"command".equals(stopped.getString("stopReason")))
            throw new IOException("Clean database stop belongs to another operation or instance");
        for(String name:Set.of("engineStarted","readyBeforeStop","cleanEngineExit"))requireFlag(stopped,name,true);
        for(String name:Set.of("dataRemoved","characterPersistenceQualified","gameplayQualified"))requireFlag(stopped,name,false);
    }
    private static void validateComplete(JSONObject report,JSONObject helper,String uuid,String version) throws IOException,JSONException {
        if(report.getInt("formatVersion")!=1 || !COMPLETE_SCOPE.equals(report.getString("scope")) ||
                !uuid.equals(report.getString("mysqlUuid")) || !version.equals(report.getString("mysqlVersion")) ||
                !report.getString("serviceOperationId").matches("[a-f0-9]{32}") ||
                !report.getString("configGeneration").matches("[a-f0-9]{64}") || report.getJSONArray("pendingComponents").length()!=0)
            throw new IOException("Complete installation scope or identity differs");
        for(String name:Set.of("baselineComplete","compiledUpdaterCompleted","sourceLedgersVerified","sameRevisionReentryVerified",
                "localRealmVerified","localAccountVerified","ownedServiceIdentityVerified","fourSchemasVerified","playerbotsSchemaVerified",
                "engineStopped","cleanEngineStopped","databaseServiceStopped","completeSetupQualified"))requireFlag(report,name,true);
        for(String name:Set.of("slotPromoted","databaseServiceStarted","authserverExecuted","worldserverExecuted","serverDataQualified",
                "androidRuntimeQualified","gameplayQualified","playerbotsAiQualified","botCharactersCreated"))requireFlag(report,name,false);
        validateHelper(report,helper);
    }
    private static void requireRecordedFile(Path path,JSONObject pin) throws IOException,JSONException {
        byte[] raw=read(path,128<<10);
        if(raw.length!=pin.getLong("bytes") || !hash(raw).equals(pin.getString("sha256")))
            throw new IOException("Source-bound installation receipt changed");
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
