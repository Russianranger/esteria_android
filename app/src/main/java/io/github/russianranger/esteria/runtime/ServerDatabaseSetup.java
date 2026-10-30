package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
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

/** Real guest bootstrap adapter. Not called by the launcher until Android MySQL
 * qualification passes. Compilation and a completed receipt are not live SQL readiness.
 */
public final class ServerDatabaseSetup {
    private static final Set<String> HELPERS=Collections.unmodifiableSet(new HashSet<>(Arrays.asList(
        "mysql_bootstrap.py","android_database_setup.py")));
    private ServerDatabaseSetup() { }
    public static final class Result {
        public final String operation, version, instanceUuid;
        public final Path state, processLogs;
        public final boolean cancellationRequested;
        Result(JSONObject report,Path state,Path logs,boolean cancellationRequested) throws JSONException {
            operation=report.getString("operation"); version=report.getString("version");
            instanceUuid=report.getString("uuid"); this.state=state; processLogs=logs;
            this.cancellationRequested=cancellationRequested;
        }
    }
    /** Off the main thread. Cancellation before launch is immediate; after launch
     * it waits for initialization's safe completion, up to the operation deadline.
     * Forced interruption preserves staging and is an error requiring recovery.
     */
    public static Result prepare(Context context,Path privateRoot,ServerRuntimeSetup runtime,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled) throws IOException {
        if (!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Database setup requires private canonical application storage");
        retryPendingCleanup(context,privateRoot,Duration.ofSeconds(2));
        if (runtime.current()==null) throw new IOException("Prepare the server dependencies before database setup");
        return prepareWork(context,privateRoot,directories(privateRoot,"state/server-work"),runtime,progress,cancelled,null);
    }
    /** The fresh coordinator retains this token until the complete operation
     * and any required process cleanup have finished. Never accepts an arbitrary path. */
    static Result prepareFresh(Context context,Path privateRoot,ServerRuntimeSetup runtime,
            FreshServerInstallations.Workspace workspace,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled,
            java.util.function.Consumer<BootstrapLease> processOwner) throws IOException {
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()) || processOwner==null)
            throw new IOException("Canonical private storage and a retained bootstrap owner required");
        workspace.requireRuntimeArchive(runtime.packagePlan().archiveSha256);
        if(runtime.current()==null)throw new IOException("Prepare the selected server runtime before fresh database setup");
        return prepareWork(context,privateRoot,workspace.directoryFor(privateRoot),runtime,progress,cancelled,processOwner);
    }
    static final class BootstrapLease implements AutoCloseable {
        private final FileChannel channel;
        private final FileLock lock;
        private OwnedProcess process;
        private boolean closed;
        private boolean operationActive=true;
        BootstrapLease(FileChannel channel,FileLock lock){this.channel=channel;this.lock=lock;}
        OwnedProcess process(){return process;}
        @Override public synchronized void close() throws IOException {
            if(closed)return;
            if(process!=null && process.isAlive())throw new IOException("Bootstrap process is still owned; database lease retained");
            try{lock.release();}finally{try{channel.close();}finally{closed=true;}}
        }
    }
    // Legacy callers do not return a retained Handle. Keep their process and
    // file lease strongly reachable until a bounded retry confirms cleanup.
    private static final java.util.concurrent.ConcurrentHashMap<Path,BootstrapLease> LEGACY_OWNERS=
        new java.util.concurrent.ConcurrentHashMap<>();
    static void retainLegacy(Path work,BootstrapLease ownership) throws IOException {
        if(LEGACY_OWNERS.putIfAbsent(work,ownership)!=null)
            throw new IOException("Previous database setup cleanup remains owned");
    }
    static void finishLegacy(Path work,BootstrapLease ownership) throws IOException {
        synchronized(ownership) {
            ownership.operationActive=false;
            if(ownership.process==null || !ownership.process.isAlive()) {
                ownership.close();LEGACY_OWNERS.remove(work,ownership);
            }
        }
    }
    static boolean legacyCleanupPending(Path work){return LEGACY_OWNERS.containsKey(work);}
    /** Off main thread; operates only on this process's retained child, never a
     * discovered PID. It does not initialize SQL or claim successful recovery. */
    public static void retryPendingCleanup(Context context,Path privateRoot,Duration timeout) throws IOException {
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Database cleanup requires canonical private storage");
        retryLegacyCleanup(privateRoot.resolve("state/server-work"),timeout);
    }
    static void retryLegacyCleanup(Path work,Duration timeout) throws IOException {
        if(timeout==null || timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(30))>0)
            throw new IllegalArgumentException("Cleanup timeout must be zero to 30 seconds");
        BootstrapLease ownership=LEGACY_OWNERS.get(work);
        if(ownership==null)return;
        synchronized(ownership) {
            if(ownership.operationActive)throw new IOException("Database setup is still running; its lease is retained");
            IOException failure=null;
            if(ownership.process!=null && ownership.process.isAlive()) {
                try{ownership.process.stop(timeout);}
                catch(IOException error) {
                    if(ownership.process.isAlive())throw new IOException("Database cleanup remains active; process and file lease retained",error);
                    failure=error;
                }
            }
            ownership.close();LEGACY_OWNERS.remove(work,ownership);
            if(failure!=null)throw new IOException("Previous database cleanup finished with a failure; preserved state requires setup recovery",failure);
        }
    }
    private static Result prepareWork(Context context,Path privateRoot,Path work,ServerRuntimeSetup runtime,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled,java.util.function.Consumer<BootstrapLease> processOwner) throws IOException {
        Path lockPath=work.resolve(".android-database-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS) && !regular(lockPath))throw new IOException("Invalid database operation lock");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        BootstrapLease ownership=null;boolean transferred=false,legacyRegistered=false;
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            FileLock lock;
            try{lock=channel.tryLock();}catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException("Database setup is already running",busy);}
            if(lock==null)throw new IOException("Database setup is already running");
            ownership=new BootstrapLease(channel,lock);
            if(processOwner!=null){processOwner.accept(ownership);transferred=true;}
            else {retainLegacy(work,ownership);legacyRegistered=true;}
            return run(context,privateRoot,work,runtime,progress,cancelled,ownership);
        } finally {
            if(ownership==null)channel.close();
            else if(legacyRegistered)finishLegacy(work,ownership);
            else if(!transferred)ownership.close();
        }
    }
    private static Result run(Context context,Path root,Path work,ServerRuntimeSetup runtime,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled,BootstrapLease ownership) throws IOException {
        checkCancelled(cancelled);
        String helperGeneration=installHelpers(context,work);
        directories(work,"state"); directories(work,"setup-results");
        String id=UUID.randomUUID().toString().replace("-","");
        Path sessions=directories(root,"state/database-operations");
        Path session=sessions.resolve(id);
        Files.createDirectory(session,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        checkCancelled(cancelled);
        if (progress!=null) progress.update("database-initializing","",0,-1);
        OwnedProcess process=ProotProcess.start(context,runtime.installer(),runtime.packagePlan(),work,session,
            Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/helpers/"+helperGeneration+"/android_database_setup.py",
                "--expected-version",runtime.expectedMysqlVersion(),"--operation-id",id),Collections.emptyMap(),null);
        ownership.process=process;
        boolean cancelSeen=false;
        long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(12);
        try {
            while (process.isAlive()) {
                if (cancelled!=null && cancelled.isCancelled() && !cancelSeen) {
                    cancelSeen=true;
                    if (progress!=null) progress.update("database-finishing-safe-point","",0,-1);
                }
                if (System.nanoTime()>=deadline) throw new IOException("Database setup timed out; staging is preserved for recovery");
                try { Thread.sleep(100); }
                catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    throw new IOException("Database setup interrupted; staging is preserved for recovery",interrupted);
                }
            }
            if (process.failure()!=null) throw new IOException("Database setup process ownership failed",process.failure());
            if (process.exitCode()!=0 || process.wasForced())
                throw new IOException("Database setup failed (exit "+process.exitCode()+"); private state and logs were preserved");
            Path receipt=work.resolve("setup-results/"+id+".json");
            if (!regular(receipt) || Files.size(receipt)>16384)
                throw new IOException("Missing or oversized database setup result");
            JSONObject report=new JSONObject(new String(Files.readAllBytes(receipt),StandardCharsets.UTF_8));
            validateReport(report,runtime.expectedMysqlVersion());
            if (progress!=null) progress.update("database-prepared","",1,1);
            return new Result(report,work.resolve("state"),session.resolve("logs"),cancelSeen);
        } catch (JSONException error) { throw new IOException("Invalid database setup result",error); }
        finally {
            // Ordinary completion already reaped the entire owned native process.
            // A forced path is never reported as successful initialization.
            if (process.isAlive()) {
                boolean interrupted=Thread.interrupted();
                try { process.stop(Duration.ZERO); }
                finally { if (interrupted) Thread.currentThread().interrupt(); }
            }
        }
    }
    private static void validateReport(JSONObject report,String version) throws IOException,JSONException {
        if (report.getInt("formatVersion")!=1 || !"database-prepared-no-readiness-claim".equals(report.getString("scope")) ||
                !version.equals(report.getString("version")) || !"/work/state/database".equals(report.getString("datadir")) ||
                !Arrays.asList("initialized","already-initialized","recovered-promotion").contains(report.getString("operation")) ||
                !report.getString("uuid").matches("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}") ||
                report.getBoolean("persistentServiceStarted") || report.getBoolean("liveServiceStateVerified") || report.getBoolean("liveSqlAuthenticated"))
            throw new IOException("Database setup result identity differs");
        Set<String> databases=new HashSet<>();
        org.json.JSONArray names=report.getJSONArray("databases");
        for (int i=0;i<names.length();i++) if (!databases.add(names.getString(i))) throw new IOException("Duplicate database in setup result");
        if (!databases.equals(new HashSet<>(Arrays.asList("acore_auth","acore_world","acore_characters","acore_playerbots"))))
            throw new IOException("Unexpected database setup schemas");
        report.getBoolean("bootstrapPopulatedApplicationSchemas"); // Explicit field, not inferred from success.
    }
    private static String installHelpers(Context context,Path work) throws IOException {
        byte[] manifest=readAsset(context,"manifest.json",16384);
        String generation=sha256(manifest);
        Path directory=directories(work,"helpers/"+generation);
        try {
            JSONObject descriptor=new JSONObject(new String(manifest,StandardCharsets.UTF_8));
            JSONObject files=descriptor.getJSONObject("files");
            Set<String> names=new HashSet<>(); files.keys().forEachRemaining(names::add);
            if (descriptor.getInt("formatVersion")!=1 || !names.equals(HELPERS)) throw new IOException("Unexpected database helper manifest");
            for (String name:HELPERS) {
                JSONObject item=files.getJSONObject(name);
                byte[] bytes=readAsset(context,name,131072);
                if (item.getInt("bytes")!=bytes.length || !sha256(bytes).equals(item.getString("sha256")))
                    throw new IOException("Database helper differs from its bundled manifest");
                Path destination=directory.resolve(name);
                if (Files.exists(destination,LinkOption.NOFOLLOW_LINKS)) {
                    if (!regular(destination) || Files.size(destination)!=bytes.length || !sha256(Files.readAllBytes(destination)).equals(item.getString("sha256")))
                        throw new IOException("Prepared database helper identity differs; original retained");
                    continue;
                }
                Path staged=Files.createTempFile(directory,".helper-",".tmp",PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                try {
                    Files.write(staged,bytes);
                    try (FileChannel output=FileChannel.open(staged,StandardOpenOption.WRITE)) { output.force(true); }
                    Files.move(staged,destination,StandardCopyOption.ATOMIC_MOVE);
                    if (!Arrays.equals(bytes,Files.readAllBytes(destination))) throw new IOException("Database helper readback failed");
                } finally { Files.deleteIfExists(staged); }
            }
        } catch (JSONException error) { throw new IOException("Invalid bundled database helper manifest",error); }
        return generation;
    }
    private static Path directories(Path root,String relative) throws IOException {
        Path path=root;
        for (Path part:java.nio.file.Paths.get(relative)) {
            path=path.resolve(part);
            if (!Files.exists(path,LinkOption.NOFOLLOW_LINKS))
                Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            if (!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS) || !path.toRealPath().equals(path))
                throw new IOException("Database setup directory is not canonical private storage");
        }
        return path;
    }
    private static boolean regular(Path path) { return Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS); }
    private static void checkCancelled(RuntimeWork.Cancellation cancelled) throws IOException {
        if (cancelled!=null && cancelled.isCancelled()) throw new RuntimeWork.CancelledException();
    }
    private static byte[] readAsset(Context context,String name,int maximum) throws IOException {
        try (InputStream input=context.getAssets().open("database-setup/"+name); ByteArrayOutputStream bytes=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];
            for (int count;(count=input.read(buffer))!=-1;) {
                if (bytes.size()+count>maximum) throw new IOException("Database setup asset exceeds bound");
                bytes.write(buffer,0,count);
            }
            return bytes.toByteArray();
        }
    }
    private static String sha256(byte[] value) throws IOException {
        try {
            StringBuilder result=new StringBuilder(64);
            for (byte item:MessageDigest.getInstance("SHA-256").digest(value)) result.append(String.format(java.util.Locale.ROOT,"%02x",item&255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable",impossible); }
    }
}
