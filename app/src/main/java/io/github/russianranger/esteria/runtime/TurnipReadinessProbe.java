package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.core.runtime.process.TurnipProbeContract;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.function.LongSupplier;
import org.json.JSONException;
import org.json.JSONObject;

/** Source-owned, single-use offscreen GPU check for explicit setup. It launches
 * the existing pinned C probe, never a game, shell, Python wrapper or user path.
 * Callers retain this owner until close confirms native cleanup. */
public final class TurnipReadinessProbe {
    private static final Map<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private TurnipReadinessProbe(){ }
    public enum State { ALLOCATED,RUNNING,PASSED,FAILED,CLOSED }
    @FunctionalInterface interface Admission { OwnedProcess.Specification prepare()throws IOException; }
    @FunctionalInterface interface Launcher { OwnedProcess start(OwnedProcess.Specification specification)throws IOException; }
    public static final class Result {
        public final String deviceName,wineGeneration,driverGeneration,wineArchiveSha256,driverArchiveSha256,driverSourceRevision,buildReceiptSha256;
        /** Native launch/execution time; paced provider reads are separate. */
        public final long deviceId,elapsedMillis;
        public final Map<String,Path> diagnosticLogs;
        private Result(Handle owner,TurnipProbeContract.Receipt receipt,long elapsed) {
            deviceName=receipt.deviceName;deviceId=receipt.deviceId;elapsedMillis=elapsed;
            wineGeneration=owner.wine.generation();driverGeneration=owner.turnip.generation();
            wineArchiveSha256=owner.wine.archiveSha256();driverArchiveSha256=owner.turnip.archiveSha256();diagnosticLogs=owner.diagnosticLogs;
            driverSourceRevision=BuildConfig.TURNIP_REVISION;
            buildReceiptSha256=owner.turnip.packagePlan().required.get("provenance/turnip-build.json").sha256;
        }
        /** Bounded component facts, no account/config/import paths or game claims. */
        public Map<String,String> diagnosticFacts(){return Map.ofEntries(
            Map.entry("turnip.probe.result","4096 offscreen pixels verified"),Map.entry("turnip.probe.device",deviceName),
            Map.entry("turnip.probe.deviceId",Long.toUnsignedString(deviceId)),Map.entry("turnip.probe.elapsedMs",Long.toString(elapsedMillis)),
            Map.entry("turnip.probe.wineGeneration",wineGeneration),Map.entry("turnip.probe.driverGeneration",driverGeneration),
            Map.entry("turnip.probe.wineArchive",wineArchiveSha256),Map.entry("turnip.probe.driverArchive",driverArchiveSha256),
            Map.entry("turnip.probe.driverSource",driverSourceRevision),Map.entry("turnip.probe.buildReceipt",buildReceiptSha256),
            Map.entry("turnip.probe.componentOnly","true"),Map.entry("turnip.probe.x11PresentationQualified","false"),
            Map.entry("turnip.probe.gameplayQualified","false"));}
    }
    /** Does not download/install providers or accept caller commands/PIDs/paths. */
    public static Handle begin(Context context,RuntimeSetup wine,TurnipSetup turnip)throws IOException {
        background();if(context==null||wine==null||turnip==null)throw new IOException("Prepared Wine and Turnip providers are required");
        Context application=context.getApplicationContext();Path root=application.getFilesDir().getCanonicalFile().toPath();
        if(OWNERS.containsKey(root))throw new IOException("A Turnip probe owner remains active; finish its cleanup first");
        turnip.requireWineArchive(wine.archiveSha256());
        Path wineRoot=wine.current(),driverRoot=turnip.current();
        if(wineRoot==null||driverRoot==null)throw new IOException("Prepare the pinned Wine and Turnip providers before probing");
        privateDirectory(root,wineRoot);privateDirectory(root,driverRoot);noGlobalPreload(wineRoot);
        // The provider validator binds both actual ELFs and the exact C recipe.
        for(String name:List.of("bin/esteria-turnip-probe","lib/libvulkan_freedreno.so","etc/turnip-icd.json","provenance/turnip-build.json"))
            if(!turnip.packagePlan().required.containsKey(name))throw new IOException("Pinned Turnip component is missing");
        Path lockRoot=directories(root,"state/turnip-probe"),lockPath=lockRoot.resolve(".operation.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS))throw new IOException("Invalid Turnip operation lock");
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(lockPath,"Turnip probe is already running");
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            String operation=UUID.randomUUID().toString().replace("-","");
            Path work=Files.createDirectory(directories(root,"state/turnip-probe-work").resolve(operation),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Files.createDirectory(work.resolve("empty"),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Path session=Files.createDirectory(directories(root,"state/turnip-probe-operations").resolve(operation),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Handle owner=new Handle(application,root,wine,turnip,wineRoot,driverRoot,work,session,lease);
            if(OWNERS.putIfAbsent(root,owner)!=null)throw new IOException("Turnip probe ownership is already retained");
            return owner;
        }catch(IOException|RuntimeException|Error error){try{lease.close();}catch(IOException cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    /** Recover only this application's known failed/stop-requested owner. The
     * caller must retain it and finish cleanup before publishing an idle state. */
    public static Handle pendingCleanup(Context context)throws IOException {
        background();if(context==null)throw new IOException("Application context required");
        Context application=context.getApplicationContext();
        Handle owner=pendingCleanup(application.getFilesDir().getCanonicalFile().toPath());
        if(owner!=null&&owner.context!=application)throw new IOException("Retained Turnip probe belongs to another application context");
        return owner;
    }
    static Handle pendingCleanup(Path root)throws IOException {
        if(!root.isAbsolute()||!root.normalize().equals(root)||!root.toRealPath().equals(root))throw new IOException("Canonical application storage required");
        Handle owner=OWNERS.get(root);if(owner==null)return null;
        if(owner.state!=State.FAILED&&!owner.operations.isStopRequested())throw new IOException("Turnip probe remains owned by its active caller");
        return owner;
    }
    /** Compatibility cleanup only; callers needing retry must retain the owner
     * exposed by pendingCleanup rather than treating a timeout as completion. */
    public static void retryPendingCleanup(Context context)throws IOException {
        Handle owner=pendingCleanup(context);if(owner!=null)owner.close(Duration.ofSeconds(2));
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,wineRoot,driverRoot,work,session;
        private final RuntimeSetup wine;
        private final TurnipSetup turnip;
        private final ExclusiveFileLease lease;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private volatile OwnedProcess process;
        private volatile IOException cleanupFailure;
        private final Map<String,Path> diagnosticLogs;
        private Handle(Context context,Path root,RuntimeSetup wine,TurnipSetup turnip,Path wineRoot,Path driverRoot,
                Path work,Path session,ExclusiveFileLease lease) {
            this.context=context;this.root=root;this.wine=wine;this.turnip=turnip;this.wineRoot=wineRoot;this.driverRoot=driverRoot;
            this.work=work;this.session=session;this.lease=lease;
            diagnosticLogs=Map.of("setup.turnip.stdout.log",session.resolve("logs/stdout.log"),"setup.turnip.stderr.log",session.resolve("logs/stderr.log"));
        }
        public State state(){return state;}
        public Map<String,Path> diagnosticLogs(){return diagnosticLogs;}
        public IOException cleanupFailure(){return cleanupFailure;}
        public Result run(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Turnip probe is single-use; explicit setup must allocate a new owner");
                state=State.RUNNING;
                RuntimeWork.Cancellation cancelled=()->operations.isStopRequested()||Thread.currentThread().isInterrupted()||
                    (cancellation!=null&&cancellation.isCancelled());
                try {
                    if(progress!=null)progress.update("graphics-provider-admission","",0,1);
                    checkCancelled(cancelled);requireCurrent();noGlobalPreload(wineRoot);
                    Map<String,String> environment=TurnipProbeContract.environment(turnip.selectedEnvironment(wine.archiveSha256()));
                    long elapsed=runPrepared(()->{
                        OwnedProcess.Specification prepared=ProotProcess.prepare(context,wine.installer(),wine.packagePlan(),work,session,
                            TurnipProbeContract.arguments(),wine.wineEnvironment(environment),List.of(new ProotLaunch.Mount(driverRoot,TurnipProbeContract.MOUNT)));
                        if(progress!=null)progress.update("graphics-component-probe","",0,1);
                        return prepared;
                    },prepared->OwnedProcess.start(new NativeProcessBridge(),prepared,null),System::nanoTime,cancelled);
                    if(progress!=null)progress.update("graphics-component-readback","",0,1);
                    requireCurrent();TurnipProbeContract.Receipt receipt=readReceipt(work.resolve(TurnipProbeContract.RECEIPT));
                    Result result=new Result(this,receipt,elapsed);
                    state=State.PASSED;if(progress!=null)progress.update("graphics-component-verified-not-gameplay","",1,1);return result;
                }catch(IOException|RuntimeException|Error error) {
                    if(state!=State.FAILED)failAndCleanup(error);
                    throw error;
                }
            });
        }
        /** Five seconds cover native launch/execution, after every potentially
         * paced admission read. Failure retains the owner and lease for close. */
        long runPrepared(Admission admission,Launcher launcher,LongSupplier nanoTime,RuntimeWork.Cancellation cancelled)throws IOException {
            if(state==State.ALLOCATED)state=State.RUNNING;
            if(state!=State.RUNNING||process!=null)throw new IOException("Turnip probe launch is single-use");
            try {
                checkCancelled(cancelled);
                OwnedProcess.Specification prepared=admission.prepare();
                checkCancelled(cancelled);
                long started=nanoTime.getAsLong(),budget=TimeUnit.MILLISECONDS.toNanos(TurnipProbeContract.TIMEOUT_MILLIS);
                process=launcher.start(prepared);
                while(process.isAlive()) {
                    checkCancelled(cancelled);
                    if(nanoTime.getAsLong()-started>=budget)throw new IOException("Turnip component probe exceeded five seconds; owned cleanup requested");
                    try{Thread.sleep(10);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new RuntimeWork.CancelledException();}
                }
                long elapsed=nanoTime.getAsLong()-started;
                if(elapsed>=budget)throw new IOException("Turnip component probe exceeded five seconds; result was not accepted");
                checkCancelled(cancelled);
                if(process.failure()!=null)throw new IOException("Turnip probe ownership or log capture failed",process.failure());
                if(process.wasForced()||process.exitCode()!=0)throw new IOException("Turnip component probe failed (exit "+process.exitCode()+"); export the retained component logs");
                return TimeUnit.NANOSECONDS.toMillis(elapsed);
            }catch(IOException|RuntimeException|Error error){failAndCleanup(error);throw error;}
        }
        private void failAndCleanup(Throwable error) {
            state=State.FAILED;
            if(process!=null&&process.isAlive()) {
                boolean interrupted=Thread.interrupted();
                try{process.terminateAuxiliary();}catch(IOException cleanup){cleanupFailure=cleanup;error.addSuppressed(cleanup);}
                finally{if(interrupted)Thread.currentThread().interrupt();}
            }
        }
        private void requireCurrent()throws IOException {
            if(!wineRoot.equals(wine.current())||!driverRoot.equals(turnip.current()))throw new IOException("Turnip or Wine provider changed during the component probe");
            turnip.requireWineArchive(wine.archiveSha256());
        }
        @Override public void close()throws IOException {close(Duration.ofSeconds(2));}
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)throw new IllegalArgumentException("Cleanup timeout must be zero to thirty seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED)return;
                IOException error=null;
                if(process!=null&&process.isAlive())try{process.terminateAuxiliary();}catch(IOException failure){cleanupFailure=failure;error=failure;}
                if(process!=null&&process.isAlive())throw error!=null?error:new IOException("Turnip probe still owns a native child; lock retained");
                try{lease.close();}
                catch(IOException failure){cleanupFailure=failure;if(error!=null)failure.addSuppressed(error);throw failure;}
                state=State.CLOSED;OWNERS.remove(root,this);
                if(error!=null)throw error;
            }
        }
    }
    private static TurnipProbeContract.Receipt readReceipt(Path path)throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))throw new IOException("Source-owned Turnip receipt is missing or linked");
        BasicFileAttributes before=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(before.size()<=0||before.size()>TurnipProbeContract.MAX_RECEIPT_BYTES)throw new IOException("Turnip component receipt exceeds its bound");
        byte[] raw;
        try(InputStream incoming=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);ByteArrayOutputStream outgoing=new ByteArrayOutputStream()) {
            byte[] block=new byte[1024];for(int count;(count=incoming.read(block))!=-1;){if(outgoing.size()+count>TurnipProbeContract.MAX_RECEIPT_BYTES)throw new IOException("Turnip component receipt grew");outgoing.write(block,0,count);}raw=outgoing.toByteArray();
        }
        BasicFileAttributes after=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(raw.length!=before.size()||!Objects.equals(before.fileKey(),after.fileKey())||before.fileKey()==null||before.size()!=after.size()||
                !before.lastModifiedTime().equals(after.lastModifiedTime())||!path.toRealPath().equals(path))throw new IOException("Turnip component receipt changed during readback");
        try {
            JSONObject receipt=new JSONObject(new String(raw,StandardCharsets.UTF_8));Map<String,Object> fields=new TreeMap<>();
            for(Iterator<String> names=receipt.keys();names.hasNext();){String name=names.next();fields.put(name,receipt.get(name));}
            return TurnipProbeContract.validate(fields);
        }catch(JSONException invalid){throw new IOException("Invalid Turnip component receipt",invalid);}
    }
    private static void noGlobalPreload(Path wineRoot)throws IOException {
        Path preload=wineRoot.resolve("etc/ld.so.preload");
        if(Files.exists(preload,LinkOption.NOFOLLOW_LINKS)&&(!Files.isRegularFile(preload,LinkOption.NOFOLLOW_LINKS)||
                !preload.toRealPath().equals(preload)||Files.size(preload)!=0))throw new IOException("Global loader preload is not allowed for the fixed Turnip component probe");
    }
    private static Path privateDirectory(Path root,Path path)throws IOException {
        if(!path.isAbsolute()||!path.normalize().equals(path)||!path.startsWith(root)||path.equals(root)||
                !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))throw new IOException("Private canonical Turnip probe directories required");return path;
    }
    private static Path directories(Path root,String relative)throws IOException {
        Path at=root;for(String part:relative.split("/")) {
            at=at.resolve(part);if(!Files.exists(at,LinkOption.NOFOLLOW_LINKS))Files.createDirectory(at,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            privateDirectory(root,at);
        }return at;
    }
    private static void checkCancelled(RuntimeWork.Cancellation cancelled)throws IOException {if(cancelled.isCancelled())throw new RuntimeWork.CancelledException();}
    private static void background()throws IOException {if(Looper.myLooper()==Looper.getMainLooper())throw new IOException("Turnip component setup must run off the main thread");}
}
