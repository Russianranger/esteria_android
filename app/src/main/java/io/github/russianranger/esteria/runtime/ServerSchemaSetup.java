package io.github.russianranger.esteria.runtime;

import android.content.Context;
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
import java.util.HashSet;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONException;
import org.json.JSONObject;

/** Source baseline setup on the caller's retained live database lease. This
 * does not run the compiled updater, auth/world servers or qualify gameplay. */
public final class ServerSchemaSetup {
    private static final Set<String> HELPERS=Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "android_server_schema_setup.py","mysql_bootstrap.py","mysql_service.py","server_content.py",
        "server_schema_setup.py","server_schema_baseline.py","server_schema_adaptations.py",
        "server/appearance-schema-v1.sql","server/appearance-schema.lock.json")));
    private ServerSchemaSetup(){ }
    public static final class Result {
        public final String operation,instanceUuid;
        public final int appliedFiles,verifiedContentFiles;
        public final boolean cancellationRequested;
        public final Path privateProcessLogs;
        private Result(JSONObject report,boolean cancellationRequested,Path logs) throws JSONException {
            operation=report.getString("operation");instanceUuid=report.getString("mysqlUuid");
            appliedFiles=report.getInt("appliedFiles");verifiedContentFiles=report.getInt("contentFilesVerified");
            this.cancellationRequested=cancellationRequested;privateProcessLogs=logs;
        }
    }
    /** Off the main thread. Once a SQL file begins, cancellation waits for its
     * completion. A failed or interrupted file is retained, never replayed. */
    public static Result prepare(Context context,Path privateRoot,ServerRuntimeSetup runtime,
            ServerProgramsSetup programs,ServerContentSetup content,ServerDatabaseService.Handle service,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled) throws IOException {
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Schema setup requires canonical private application storage");
        if(runtime.current()==null || programs.current()==null || content.current()==null)
            throw new IOException("Prepare the pinned runtime, programs and content before schema setup");
        programs.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        if(!programs.packagePlan().required.get("provenance/server-modules.json").sha256.equals(
                identityHash(content.compiledModulesIdentity())))
            throw new IOException("Server content and installed programs use different compiled modules");
        return service.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->
            run(context,privateRoot,runtime,programs,content,service,serviceOperation,version,uuid,progress,cancelled));
    }
    private static Result run(Context context,Path root,ServerRuntimeSetup runtime,ServerProgramsSetup programs,
            ServerContentSetup content,ServerDatabaseService.Handle service,String serviceOperation,String version,String uuid,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled) throws IOException {
        checkCancelled(cancelled,service);
        Path work=GuestHelperAssets.directory(root,"state/server-work");
        String generation=GuestHelperAssets.install(context,"server-schema",GuestHelperAssets.directory(work,"schema-helpers"),HELPERS);
        String operation=UUID.randomUUID().toString().replace("-","");
        Path guestOperations=GuestHelperAssets.directory(work,"schema-operations");
        Path operationFiles=guestOperations.resolve(operation);createPrivate(operationFiles);
        Path processSessions=GuestHelperAssets.directory(root,"state/server-schema-processes");
        Path processSession=processSessions.resolve(operation);createPrivate(processSession);
        try {
            byte[] receipt=read(content.receiptPath(),16<<20);
            if(!hash(receipt).equals(content.receiptSha256()))throw new IOException("Prepared server content receipt changed");
            write(operationFiles.resolve("content-receipt.json"),receipt);
            JSONObject selection=new JSONObject().put("formatVersion",1).put("scope","android-owned-server-schema-selection")
                .put("source",content.serverSource()).put("sourceLockSha256",content.sourceLockSha256())
                .put("contentReceipt",new JSONObject().put("bytes",receipt.length).put("sha256",content.receiptSha256()))
                .put("compiledModules",content.compiledModulesIdentity());
            write(operationFiles.resolve("selection.json"),(selection.toString()+"\n").getBytes(StandardCharsets.UTF_8));
            checkCancelled(cancelled,service);
            if(progress!=null)progress.update("server-content-verifying","",0,-1);
            OwnedProcess process=ProotProcess.start(context,runtime.installer(),runtime.packagePlan(),work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/schema-helpers/"+generation+"/android_server_schema_setup.py",
                    "--expected-version",version,"--operation-id",operation,"--service-operation-id",serviceOperation,"--instance-uuid",uuid),
                Collections.emptyMap(),Arrays.asList(new ProotLaunch.Mount(content.current(),"/esteria-server-content"),
                    new ProotLaunch.Mount(programs.current(),ServerProgramsSetup.guestMount())),null);
            boolean cancelSeen=false;
            String lastProgress="";
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(30);
            try {
                while(process.isAlive()) {
                    if(!service.isAlive())throw new IOException("Database service exited during schema setup; state retained");
                    if(((cancelled!=null && cancelled.isCancelled()) || service.schemaCancellationRequested()) && !cancelSeen) {
                        write(operationFiles.resolve("cancel"),new byte[0]);cancelSeen=true;
                        if(progress!=null)progress.update("server-schema-finishing-safe-point","",0,-1);
                    }
                    Path progressPath=operationFiles.resolve("progress.json");
                    if(progress!=null && Files.exists(progressPath,LinkOption.NOFOLLOW_LINKS)) {
                        String current=new String(read(progressPath,16384),StandardCharsets.UTF_8);
                        if(!current.equals(lastProgress)) {
                            JSONObject event=new JSONObject(current);String phase=event.getString("phase");
                            if(!Set.of("files","receipt","schema-file-started","schema-file-complete").contains(phase))
                                throw new IOException("Unexpected schema progress phase");
                            progress.update("server-"+phase,event.optString("path",""),event.optLong("bytes",event.optLong("files",0)),
                                event.optLong("totalBytes",event.optLong("totalFiles",-1)));lastProgress=current;
                        }
                    }
                    if(System.nanoTime()>=deadline)throw new IOException("Schema setup timed out; partial state retained");
                    try {Thread.sleep(100);}catch(InterruptedException interrupted) {
                        Thread.currentThread().interrupt();throw new IOException("Schema setup interrupted; partial state retained",interrupted);
                    }
                }
                if(process.failure()!=null)throw new IOException("Schema setup process ownership failed",process.failure());
                if(process.wasForced() || process.exitCode()!=0) {
                    if(cancelSeen && process.exitCode()==2 && !process.wasForced())throw new RuntimeWork.CancelledException();
                    throw new IOException("Schema setup failed (exit "+process.exitCode()+"); database and private diagnostics retained");
                }
                JSONObject report=new JSONObject(new String(read(operationFiles.resolve("result.json"),128<<10),StandardCharsets.UTF_8));
                validateReport(report,content,operation,serviceOperation,version,uuid);
                if(progress!=null)progress.update("server-source-baseline-prepared","",1,1);
                return new Result(report,cancelSeen,processSession.resolve("logs"));
            } finally {
                if(process.isAlive()) {
                    boolean interrupted=Thread.interrupted();
                    try{process.stop(Duration.ZERO);}finally{if(interrupted)Thread.currentThread().interrupt();}
                }
            }
        } catch(JSONException error){throw new IOException("Invalid source baseline metadata",error);}
    }
    private static void validateReport(JSONObject report,ServerContentSetup content,String operation,String serviceOperation,String version,String uuid)
            throws IOException,JSONException {
        if(report.getInt("formatVersion")!=1 || !"owned-packaged-content-source-baseline-only".equals(report.getString("scope")) ||
                !operation.equals(report.getString("operationId")) || !serviceOperation.equals(report.getString("serviceOperationId")) ||
                !version.equals(report.getString("mysqlVersion")) || !uuid.equals(report.getString("mysqlUuid")) ||
                !content.sourceLockSha256().equals(report.getString("sourceLockSha256")) ||
                !content.receiptSha256().equals(report.getJSONObject("contentReceipt").getString("sha256")) ||
                !identityHash(content.compiledModulesIdentity()).equals(identityHash(report.getJSONObject("compiledModules"))) ||
                !Set.of("initialized-source-baseline","already-prepared").contains(report.getString("operation")) ||
                !report.getBoolean("baselineImportCompleted") || !report.getBoolean("ownedServiceIdentityVerified") ||
                report.getInt("appliedFiles")<1 || report.getInt("contentFilesVerified")<1)
            throw new IOException("Schema result differs from the owned source selection");
        for(String flag:Arrays.asList("liveSchemaReadinessVerified","compiledUpdaterExecuted","gameSchemasQualified",
                "existingSaveUpgradesQualified","playerbotsRuntimeQualified","authserverExecuted","worldserverExecuted",
                "androidRuntimeQualified","gameplayQualified","databaseServiceStarted","databaseServiceStopped"))
            if(report.getBoolean(flag))throw new IOException("Unexpected schema qualification claim");
    }
    private static String identityHash(JSONObject identity) throws IOException {
        try {
            if(identity.getLong("bytes")<=0 || !identity.getString("sha256").matches("[a-f0-9]{64}"))throw new IOException("Invalid content identity");
            return identity.getString("sha256");
        }catch(JSONException error){throw new IOException("Invalid content identity",error);}
    }
    private static void createPrivate(Path path) throws IOException {
        Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }
    private static byte[] read(Path path,int maximum) throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !path.toRealPath().equals(path) || Files.size(path)>maximum)
            throw new IOException("Missing or oversized schema metadata");
        try(var stream=Files.newInputStream(path);var output=new java.io.ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];
            for(int count;(count=stream.read(buffer))!=-1;){if(output.size()+count>maximum)throw new IOException("Schema metadata exceeded bound");output.write(buffer,0,count);}
            return output.toByteArray();
        }
    }
    private static void write(Path path,byte[] data) throws IOException {
        try(FileChannel file=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));
            java.nio.ByteBuffer buffer=java.nio.ByteBuffer.wrap(data);while(buffer.hasRemaining())file.write(buffer);file.force(true);
        }
        try(FileChannel folder=FileChannel.open(path.getParent(),StandardOpenOption.READ)){folder.force(true);}
    }
    private static String hash(byte[] data) throws IOException {
        try {
            StringBuilder value=new StringBuilder();for(byte item:MessageDigest.getInstance("SHA-256").digest(data))
                value.append(String.format(java.util.Locale.ROOT,"%02x",item&255));return value.toString();
        }catch(NoSuchAlgorithmException error){throw new IOException("SHA-256 unavailable",error);}
    }
    private static void checkCancelled(RuntimeWork.Cancellation cancelled,ServerDatabaseService.Handle service) throws RuntimeWork.CancelledException {
        if((cancelled!=null && cancelled.isCancelled()) || service.schemaCancellationRequested())throw new RuntimeWork.CancelledException();
    }
}
