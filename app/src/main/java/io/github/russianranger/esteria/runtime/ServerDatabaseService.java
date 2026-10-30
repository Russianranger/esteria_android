package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.SessionSupervisor;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Persistent database component; launcher activation awaits actual runtime gates. */
public final class ServerDatabaseService {
    private ServerDatabaseService(){ }
    /** Internal seam for an already verified runtime. The public entry point
     * below always uses ServerRuntimeSetup and the production PRoot inspector.
     * Only androidTest supplies the independently verified x64 probe runtime. */
    interface InstalledRuntime {
        Path current() throws IOException;
        String expectedMysqlVersion();
        OwnedProcess launch(Path work,Path session,List<String> command,
                            OwnedProcess.GracefulInputStop shutdown) throws IOException;
    }
    public static final class Handle implements SessionSupervisor.Child {
        private final OwnedProcess process;
        private final FileChannel leaseChannel;
        private final FileLock lease;
        private final Path guestSession,runtimeGeneration,workDirectory;
        private final FreshServerInstallations.Workspace freshWorkspace;
        private final String operation,version;
        private String instanceUuid;
        private boolean released;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private Handle(OwnedProcess process,FileChannel channel,FileLock lease,Path session,String operation,String version,Path runtimeGeneration,Path workDirectory,FreshServerInstallations.Workspace workspace) {
            this.process=process;leaseChannel=channel;this.lease=lease;guestSession=session;this.operation=operation;this.version=version;this.runtimeGeneration=runtimeGeneration;this.workDirectory=workDirectory;freshWorkspace=workspace;
        }
        @Override public boolean isAlive(){return process.isAlive();}
        @Override public int exitCode(){return process.exitCode();}
        /** This identity is available only after live SQL readiness, not merely setup. */
        public String instanceUuid(){return instanceUuid;}
        public Path privateSessionDirectory(){return guestSession;}
        /** Only the owned wrapper's bounded stdout/stderr. Engine-private.log,
         * option files, accounts and configuration remain excluded. */
        public java.util.Map<String,Path> diagnosticLogs(){return process.logPaths();}
        public io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot usage(){return process.usage();}
        Path privateWorkDirectory(){return workDirectory;}
        @Override public void stop(Duration timeout) throws IOException {
            if(timeout==null || timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Shutdown timeout must be between zero and 30 seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                stopOwned(permit.remaining());
            }
        }
        private void stopOwned(Duration timeout) throws IOException {
            try {
                process.stop(timeout);
                if(process.isAlive() || process.exitCode()!=0 || process.wasForced() || process.failure()!=null)
                    throw new IOException("Local database did not stop cleanly; recovery is required");
                JSONObject receipt=read(guestSession.resolve("stopped.json"));
                identity(receipt,"owned-local-mysql-stopped");
                boolean started=receipt.getBoolean("engineStarted");
                if(!"command".equals(receipt.getString("stopReason")) || receipt.getBoolean("cleanEngineExit")!=started ||
                        (!started && receipt.getBoolean("readyBeforeStop")) ||
                        receipt.getBoolean("dataRemoved") || receipt.getBoolean("characterPersistenceQualified"))
                    throw new IOException("Database shutdown acknowledgment is incomplete");
            } catch(JSONException error){throw new IOException("Invalid database shutdown acknowledgment",error);}
            finally {
                // A still-running native owner must keep its lease. The guest
                // service lock also remains held until its real engine stops.
                if(!process.isAlive())release();
            }
        }
        interface ReadyOperation<T> { T run(String operation,String version,String uuid) throws IOException; }
        /** Setup observes this request and cancels only at a SQL file boundary. */
        boolean schemaCancellationRequested(){return operations.isStopRequested();}
        /** Keep the same live engine and exclusive Android service lease for an
         * off-main-thread operation. Shutdown waits only its caller's deadline. */
        <T> T withReadyLease(Path expectedRuntime,ReadyOperation<T> action) throws IOException {
            return operations.run(()->{
                if(released || !lease.isValid() || instanceUuid==null || !runtimeGeneration.equals(expectedRuntime) || !process.isAlive())
                    throw new IOException("A live owned database service from this runtime is required");
                T result=action.run(operation,version,instanceUuid);
                if(released || !lease.isValid() || !process.isAlive())
                    throw new IOException("Database service exited during schema setup; state retained");
                return result;
            });
        }
        private synchronized void release() throws IOException {
            if(!released){released=true;try{lease.release();}finally{try{leaseChannel.close();}finally{if(freshWorkspace!=null)freshWorkspace.close();}}}
        }
        private void identity(JSONObject receipt,String scope) throws IOException,JSONException {
            String uuid=receipt.getString("uuid");
            if(receipt.getInt("formatVersion")!=1 || !scope.equals(receipt.getString("scope")) ||
                    !operation.equals(receipt.getString("operationId")) || !version.equals(receipt.getString("version")) ||
                    !uuid.matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}") ||
                    (instanceUuid!=null && !instanceUuid.equals(uuid)) || receipt.getBoolean("gameplayQualified"))
                throw new IOException("Database service identity differs");
        }
    }
    /** Caller retains this child and always stops it, including failed readiness. */
    public static Handle start(Context context,Path root,ServerRuntimeSetup runtime) throws IOException {
        return startInstalled(context,root,installedRuntime(context,runtime));
    }
    private static InstalledRuntime installedRuntime(Context context,ServerRuntimeSetup runtime) {
        return new InstalledRuntime(){
            @Override public Path current() throws IOException {return runtime.current();}
            @Override public String expectedMysqlVersion(){return runtime.expectedMysqlVersion();}
            @Override public OwnedProcess launch(Path work,Path session,List<String> command,
                    OwnedProcess.GracefulInputStop shutdown) throws IOException {
                return ProotProcess.startInteractive(context,runtime.installer(),runtime.packagePlan(),work,session,
                        command,Collections.emptyMap(),Collections.emptyList(),shutdown);
            }
        };
    }
    /** The handle retains a child workspace token until its owned service exits. */
    static Handle startFresh(Context context,Path root,ServerRuntimeSetup runtime,FreshServerInstallations.Attempt attempt) throws IOException {
        FreshServerInstallations.Workspace workspace=attempt.retainWorkspace();
        try {
            workspace.requireRuntimeArchive(runtime.packagePlan().archiveSha256);
            return startAtWorkspace(context,root,installedRuntime(context,runtime),workspace.directoryFor(root),workspace);
        } catch(IOException|RuntimeException error){workspace.close();throw error;}
    }
    /** Existing promoted storage is started directly, never initialized again. */
    static Handle startActive(Context context,Path root,ServerRuntimeSetup runtime,FreshServerInstallations.Active active) throws IOException {
        if(!active.runtimeArchiveSha256.equals(runtime.packagePlan().archiveSha256))
            throw new IOException("Active database requires its pinned server runtime; existing state retained");
        return startAtWorkspace(context,root,installedRuntime(context,runtime),active.directoryFor(root),null);
    }
    static Handle startInstalled(Context context,Path root,InstalledRuntime runtime) throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()) || runtime.current()==null)throw new IOException("Canonical private application storage required");
        return startAtWorkspace(context,root,runtime,GuestHelperAssets.directory(root,"state/server-work"),null);
    }
    private static Handle startAtWorkspace(Context context,Path root,InstalledRuntime runtime,Path work,
            FreshServerInstallations.Workspace workspace) throws IOException {
        Path installed=runtime.current();
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()) || installed==null)
            throw new IOException("Prepared runtime and canonical private storage required");
        // PRoot expands guest UNIX sockets to these physical Android filenames.
        // mysql_service.py creates only s-XXXXXXXX/m.sock directly below /work.
        if(work.resolve("s-12345678/m.sock").toString().getBytes(StandardCharsets.UTF_8).length>100)
            throw new IOException("Private database socket path exceeds the Android address bound");
        Path lockPath=work.resolve(".android-database-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS) && !Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid database ownership lock");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        FileLock lock=null;
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            try{lock=channel.tryLock();}catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException("Database is already in use",busy);}
            if(lock==null)throw new IOException("Database is already in use");
            String generation=GuestHelperAssets.install(context,"database-service",
                    GuestHelperAssets.directory(work,"service-helpers"),
                    new HashSet<>(Arrays.asList("mysql_bootstrap.py","mysql_service.py")));
            Path guestSessions=GuestHelperAssets.directory(work,"mysql-sessions");
            Path sessions=GuestHelperAssets.directory(root,"state/database-service-operations");
            String operation=UUID.randomUUID().toString().replace("-","");
            Path session=sessions.resolve(operation);
            Files.createDirectory(session,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            OwnedProcess process=runtime.launch(work,session,
                    Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/service-helpers/"+generation+"/mysql_service.py",
                            "--expected-version",runtime.expectedMysqlVersion(),"--operation-id",operation),
                    child->{
                        if(!child.writeInput("shutdown\n".getBytes(StandardCharsets.US_ASCII),Duration.ofSeconds(1)))
                            throw new IOException("Database shutdown request was not delivered");
                    });
            return new Handle(process,channel,lock,guestSessions.resolve(operation),operation,runtime.expectedMysqlVersion(),installed,work,workspace);
        } catch(IOException|RuntimeException error) {
            try{if(lock!=null)lock.release();}finally{channel.close();}
            throw error;
        }
    }
    public static void awaitReady(Handle child,long deadlineNanos,AtomicBoolean cancelled) throws IOException,InterruptedException {
        awaitReady(child,deadlineNanos,(RuntimeWork.Cancellation)cancelled::get);
    }
    static void awaitReady(Handle child,long deadlineNanos,RuntimeWork.Cancellation cancelled) throws IOException,InterruptedException {
        while(true) {
            if(cancelled.isCancelled())throw new java.util.concurrent.CancellationException("Database startup cancelled");
            if(!child.isAlive())throw new IOException("Database service exited before readiness (exit "+child.exitCode()+")");
            if(System.nanoTime()>=deadlineNanos)throw new IOException("Database live readiness timed out");
            Path file=child.guestSession.resolve("ready.json");
            if(Files.exists(file,LinkOption.NOFOLLOW_LINKS)) {
                try {
                    JSONObject receipt=read(file);
                    child.identity(receipt,"owned-local-mysql-live-service");
                    if(!"/work/state/database".equals(receipt.getString("datadir")) ||
                            !"127.0.0.1".equals(receipt.getString("bindAddress")) || receipt.getInt("port")!=13306 ||
                            !receipt.getBoolean("liveSqlAuthenticated") || !receipt.getBoolean("ownedEngineIdentityVerified") ||
                            receipt.getBoolean("applicationSchemaUpdatesQualified"))
                        throw new IOException("Database live readiness result is incomplete");
                    JSONArray databases=receipt.getJSONArray("databases");Set<String> actual=new HashSet<>();
                    for(int i=0;i<databases.length();i++)if(!actual.add(databases.getString(i)))throw new IOException("Duplicate database name");
                    if(!actual.equals(new HashSet<>(Arrays.asList("acore_auth","acore_world","acore_characters","acore_playerbots"))))
                        throw new IOException("Database schema access differs");
                    if(!child.isAlive())throw new IOException("Database service exited during readiness");
                    child.instanceUuid=receipt.getString("uuid");
                    return;
                } catch(JSONException error){throw new IOException("Invalid database readiness result",error);}
            }
            Thread.sleep(50);
        }
    }
    private static JSONObject read(Path path) throws IOException,JSONException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS) || !path.toRealPath().equals(path) || Files.size(path)>16384)
            throw new IOException("Missing or oversized private database receipt");
        try(var stream=Files.newInputStream(path);var bytes=new java.io.ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];
            for(int count;(count=stream.read(buffer))!=-1;){
                if(bytes.size()+count>16384)throw new IOException("Private database receipt exceeded bound");
                bytes.write(buffer,0,count);
            }
            return new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
        }
    }
}
