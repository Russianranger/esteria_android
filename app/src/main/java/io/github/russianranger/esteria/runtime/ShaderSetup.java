package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
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
import java.util.concurrent.ConcurrentHashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONException;
import org.json.JSONObject;

/** Executes only the pinned offline shader helper. No launcher action calls this
 * until its Android guest and imported-data qualification gates are met.
 */
public final class ShaderSetup {
    private ShaderSetup() { }
    public static final class Result {
        public final String generation,importGeneration,clientRevision,locale;
        public final Path shaders,processLogs;
        public final int outputFiles;
        public final long outputBytes;
        public final boolean cancellationRequested;
        private Result(ShaderRunPlan plan,String generation,Path shaders,Path logs,int files,long bytes,boolean cancelled) {
            this.generation=generation;importGeneration=plan.importGeneration;clientRevision=plan.clientRevision;locale=plan.locale;
            this.shaders=shaders;processLogs=logs;outputFiles=files;outputBytes=bytes;cancellationRequested=cancelled;
        }
    }
    public enum State { ALLOCATED, RUNNING, SUCCEEDED, FAILED, CLOSED }
    // A failed compatibility prepare() must not drop its process or real file
    // lease when cleanup times out. New Handle callers share the same registry.
    private static final Map<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    /** Off main thread. Allocate ownership and the exclusive file lease before
     * starting any helper. Caller MUST serialize import activation and keep the
     * client stopped until this handle is closed, including failed cleanup. */
    public static Handle begin(Context context,Path privateRoot,RuntimeSetup wine,ShaderToolsSetup tools,String locale)throws IOException {
        background();
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Shader setup requires private canonical application storage");
        tools.requireWineArchive(wine.archiveSha256());
        Path wineRoot=wine.current(),toolsRoot=tools.current();
        if(wineRoot==null||toolsRoot==null)throw new IOException("Prepare the pinned Wine runtime and shader tools first");
        Path work=directories(privateRoot,"state/shader-work");
        if(OWNERS.containsKey(work))throw new IOException("Shader owner remains active; close or retry cleanup first");
        Path lockPath=work.resolve(".android-shader-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid shader setup operation lock");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        FileLock lock=null;
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            try{lock=channel.tryLock();}catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException("Shader setup is already running",busy);}
            if(lock==null)throw new IOException("Shader setup is already running");
            Handle owner=new Handle(context.getApplicationContext(),privateRoot,work,wine,tools,locale,wineRoot,toolsRoot,channel,lock);
            retain(owner);return owner;
        } catch(IOException|RuntimeException error){try{if(lock!=null)lock.release();}finally{channel.close();}throw error;}
    }
    private static void retain(Handle owner)throws IOException {
        if(OWNERS.putIfAbsent(owner.work,owner)!=null)throw new IOException("Shader ownership is already retained");
    }
    /** Compatibility entrypoint. It retains failed child cleanup internally;
     * a later prepare first retries that cleanup, never overlaps/replays it. */
    public static Result prepare(Context context,Path privateRoot,RuntimeSetup wine,ShaderToolsSetup tools,String locale,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        retryPendingCleanup(context,privateRoot);
        try(Handle owner=begin(context,privateRoot,wine,tools,locale)) {return owner.prepare(progress,cancelled);}
    }
    /** Known-child cleanup only, no shader replay or deletion of outputs. An
     * allocated/running owner belongs to its caller and is never stolen. */
    public static void retryPendingCleanup(Context context,Path privateRoot)throws IOException {
        background();if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Private canonical shader storage required");
        retryPendingCleanup(privateRoot.resolve("state/shader-work"));
    }
    static void retryPendingCleanup(Path work)throws IOException {
        Handle owner=OWNERS.get(work);if(owner==null)return;
        if(owner.state!=State.FAILED&&!owner.operations.isStopRequested())
            throw new IOException("Shader setup remains active; use its retained owner");
        owner.close(Duration.ofSeconds(2));
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,work,wineRoot,toolsRoot;
        private final RuntimeSetup wine;
        private final ShaderToolsSetup tools;
        private final String locale;
        private final FileChannel channel;
        private final FileLock lock;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private OwnedProcess process;
        private IOException cleanupFailure;
        private Handle(Context context,Path root,Path work,RuntimeSetup wine,ShaderToolsSetup tools,String locale,
                Path wineRoot,Path toolsRoot,FileChannel channel,FileLock lock) {
            this.context=context;this.root=root;this.work=work;this.wine=wine;this.tools=tools;this.locale=locale;
            this.wineRoot=wineRoot;this.toolsRoot=toolsRoot;this.channel=channel;this.lock=lock;
        }
        public State state(){return state;}
        public IOException cleanupFailure(){return cleanupFailure;}
        /** Single use. Keep this owner on failure; cancellation stops the
         * complete owned guest. Atomic shader promotion may win that race. */
        public Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Shader setup already ran; retained state must not be replayed");
                state=State.RUNNING;
                RuntimeWork.Cancellation cancelled=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    Result result=run(progress,cancelled);state=State.SUCCEEDED;return result;
                }catch(IOException|RuntimeException error) {
                    state=State.FAILED;
                    if(process!=null&&process.isAlive()) {
                        boolean interrupted=Thread.interrupted();
                        try{process.stop(Duration.ZERO);}catch(IOException cleanup){cleanupFailure=cleanup;error.addSuppressed(cleanup);}
                        finally{if(interrupted)Thread.currentThread().interrupt();}
                    }
                    throw error;
                }
            });
        }
        private Result run(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
            checkCancelled(cancelled);
            if(!wineRoot.equals(wine.current())||!toolsRoot.equals(tools.current()))throw new IOException("Shader providers changed after allocation");
            ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),toolsRoot,work,tools.revision(),locale);
            Path sessions=directories(root,"state/shader-operations");
            Path session=sessions.resolve(UUID.randomUUID().toString().replace("-",""));
            Files.createDirectory(session,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            checkCancelled(cancelled);
            if(progress!=null)progress.update("shaders-generating","",0,-1);
            process=ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,session,
                plan.arguments,wine.wineEnvironment(),plan.mounts,null);
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(125);
            while(process.isAlive()) {
                checkCancelled(cancelled);
                if(System.nanoTime()>=deadline)throw new IOException("Shader setup timed out; previous and staged outputs were retained");
                try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Shader setup interrupted; outputs were retained",error);}
            }
            if(process.failure()!=null)throw new IOException("Shader setup process ownership failed",process.failure());
            if(process.exitCode()!=0||process.wasForced())throw new IOException("Shader setup failed (exit "+process.exitCode()+"); retained private logs describe the failure");
            plan.requireCurrentImport();
            Result result=validatePrepared(plan,tools.toolManifestSha256(),session.resolve("logs"),cancelled!=null&&cancelled.isCancelled());
            if(progress!=null)progress.update("shaders-prepared-not-render-qualified","",result.outputFiles,result.outputFiles);
            return result;
        }
        @Override public void close()throws IOException {close(Duration.ofSeconds(20));}
        /** A timeout/interruption keeps the actual FileLock and providers until
         * the process owner confirms its child has stopped. Retry this handle. */
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Shutdown timeout must be zero to 30 seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED)return;
                IOException error=null;
                if(process!=null) {
                    try{process.stop(permit.remaining());}catch(IOException failure){error=failure;cleanupFailure=failure;}
                    if(process.isAlive())throw error!=null?error:new IOException("Shader helper remains alive; file lease retained");
                }
                try{lock.release();}finally{try{channel.close();}finally{state=State.CLOSED;OWNERS.remove(work,this);}}
                if(error!=null)throw error;
            }
        }
    }
    /** Recheck current provider/import/output metadata while the caller owns
     * import and client-view leases. This remains format-only shader evidence. */
    static Result requireCurrent(Context context,Path root,RuntimeSetup wine,ShaderToolsSetup tools,Result expected)throws IOException {
        background();
        if(expected==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private prepared shaders required");
        tools.requireWineArchive(wine.archiveSha256());
        if(wine.current()==null||tools.current()==null)throw new IOException("Prepared shader providers required");
        ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),tools.current(),root.resolve("state/shader-work"),tools.revision(),expected.locale);
        Result current=validatePrepared(plan,tools.toolManifestSha256(),expected.processLogs,false);
        requireSameSelection(current,expected);return current;
    }
    static void requireSameSelection(Result current,Result expected)throws IOException {
        if(!current.generation.equals(expected.generation)||!current.shaders.equals(expected.shaders)||
                !current.importGeneration.equals(expected.importGeneration)||!current.clientRevision.equals(expected.clientRevision)||
                !current.locale.equals(expected.locale)||current.outputFiles!=expected.outputFiles||current.outputBytes!=expected.outputBytes)
            throw new IOException("Prepared shader selection changed; run local setup again");
    }
    /** Validate the owned helper's completed receipt and metadata, without a full
     * rescan of imported MPQs. The helper itself hashes every generated output.
     * This host readback checks those output paths/sizes, not GPU correctness.
     */
    static Result validatePrepared(ShaderRunPlan plan,String manifest,Path logs,boolean cancelled)throws IOException {
        Path store=canonicalDirectory(plan.work.resolve("shaders"));
        String generation=new String(read(store.resolve("current"),65),StandardCharsets.US_ASCII);
        if(!generation.matches("[0-9a-f]{64}\\n"))throw new IOException("Invalid prepared shader generation");
        generation=generation.substring(0,64);
        Path parent=canonicalDirectory(store.resolve("generations"));
        Path destination=canonicalDirectory(parent.resolve(generation));
        Path shaders=canonicalDirectory(destination.resolve("shaders"));
        try {
            JSONObject receipt=new JSONObject(new String(read(destination.resolve("receipt.json"),16<<20),StandardCharsets.UTF_8));
            requireKeys(receipt,"formatVersion","scope","generation","inputs","outputs","graphicsQualified","androidQualified","gameplayQualified");
            if(integer(receipt,"formatVersion")!=1||!"local-generated-shaders-not-render-qualified".equals(receipt.get("scope"))||
                !generation.equals(receipt.get("generation"))||!Boolean.FALSE.equals(receipt.get("graphicsQualified"))||
                !Boolean.FALSE.equals(receipt.get("androidQualified"))||!Boolean.FALSE.equals(receipt.get("gameplayQualified")))
                throw new IOException("Shader result scope differs");
            JSONObject inputs=receipt.getJSONObject("inputs");
            requireKeys(inputs,"formatVersion","importGeneration","clientRevision","locale","importMetadata","toolManifestSha256");
            if(integer(inputs,"formatVersion")!=1||!plan.importGeneration.equals(inputs.get("importGeneration"))||
                !plan.clientRevision.equals(inputs.get("clientRevision"))||!plan.locale.equals(inputs.get("locale"))||
                !manifest.equals(inputs.get("toolManifestSha256"))||!sha256((canonical(inputs)+"\n").getBytes(StandardCharsets.UTF_8)).equals(generation))
                throw new IOException("Shader result input identity differs");
            JSONObject metadata=inputs.getJSONObject("importMetadata");
            if(metadata.length()<2||metadata.length()>96||!metadata.has(plan.importGeneration+"/complete")||
                !metadata.has(plan.importGeneration+"/journal.tsv"))throw new IOException("Invalid shader import ancestry receipt");
            long metadataBytes=0;
            for(Iterator<String> names=metadata.keys();names.hasNext();) {
                String name=names.next();
                if(!name.matches("[0-9a-f]{64}/(?:complete|journal\\.tsv|base-ready)"))throw new IOException("Unexpected shader import metadata path");
                JSONObject item=metadata.getJSONObject(name);long bytes=filePin(item,32L<<20);
                metadataBytes+=bytes;if(metadataBytes>64L<<20)throw new IOException("Shader import metadata exceeds bound");
                Path file=plan.game.resolve("generations").resolve(name);canonicalFile(file);
                if(Files.size(file)!=bytes||!hashFile(file,bytes).equals(item.getString("sha256")))throw new IOException("Import metadata changed after shader setup");
            }
            JSONObject outputs=receipt.getJSONObject("outputs");
            if(outputs.length()<4||outputs.length()>32768*3+2||!outputs.has("manifest.txt")||!outputs.has("index.txt"))
                throw new IOException("Incomplete shader output inventory");
            long total=0;int vertex=0,pixel=0;
            for(Iterator<String> names=outputs.keys();names.hasNext();) {
                String name=names.next();
                if(!name.equals("manifest.txt")&&!name.equals("index.txt")&&!name.matches("(?:vertex|pixel)/[0-9a-f]{32}\\.(?:spv|glsl|spvasm)"))
                    throw new IOException("Unexpected shader output path");
                long bytes=filePin(outputs.getJSONObject(name),16L<<20);total+=bytes;
                if(total>2L<<30)throw new IOException("Shader output exceeds bound");
                Path file=shaders.resolve(name);canonicalFile(file);
                if(Files.size(file)!=bytes)throw new IOException("Prepared shader output size changed");
                if(name.startsWith("vertex/")&&name.endsWith(".spv"))vertex++;
                if(name.startsWith("pixel/")&&name.endsWith(".spv"))pixel++;
            }
            if(vertex==0||pixel==0)throw new IOException("Both prepared shader stages are required");
            plan.requireCurrentImport();
            return new Result(plan,generation,shaders,logs,outputs.length(),total,cancelled);
        }catch(JSONException error){throw new IOException("Invalid prepared shader receipt",error);}
    }
    private static long filePin(JSONObject item,long maximum)throws IOException,JSONException {
        requireKeys(item,"bytes","sha256");long size=integer(item,"bytes");Object hash=item.get("sha256");
        if(size<0||size>maximum||!(hash instanceof String)||!((String)hash).matches("[0-9a-f]{64}"))throw new IOException("Invalid shader file identity");
        return size;
    }
    private static long integer(JSONObject value,String key)throws JSONException,IOException {
        Object number=value.get(key);if(!(number instanceof Integer)&&!(number instanceof Long))throw new IOException("Shader receipt integer type differs");
        return ((Number)number).longValue();
    }
    private static void requireKeys(JSONObject object,String... expected)throws IOException {
        Set<String> names=new HashSet<>();object.keys().forEachRemaining(names::add);
        if(!names.equals(new HashSet<>(Arrays.asList(expected))))throw new IOException("Shader receipt fields differ");
    }
    private static String canonical(JSONObject value)throws JSONException,IOException {
        TreeSet<String> keys=new TreeSet<>();value.keys().forEachRemaining(keys::add);StringBuilder out=new StringBuilder("{");
        for(String key:keys) {
            if(out.length()>1)out.append(',');out.append(JSONObject.quote(key)).append(':');Object item=value.get(key);
            if(item instanceof JSONObject)out.append(canonical((JSONObject)item));
            else if(item instanceof String)out.append(JSONObject.quote((String)item));
            else if(item instanceof Integer||item instanceof Long)out.append(item);
            else throw new IOException("Unsupported shader input receipt value");
        }
        return out.append('}').toString();
    }
    private static Path directories(Path root,String relative)throws IOException {
        Path path=root;for(Path part:java.nio.file.Paths.get(relative)) {
            path=path.resolve(part);if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))
                Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            canonicalDirectory(path);
        }return path;
    }
    private static Path canonicalDirectory(Path path)throws IOException {
        if(!path.isAbsolute()||!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))
            throw new IOException("Shader path is not canonical private storage");return path;
    }
    private static void canonicalFile(Path path)throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))throw new IOException("Shader metadata/output is not a canonical regular file");
    }
    private static byte[] read(Path path,int maximum)throws IOException {
        canonicalFile(path);if(Files.size(path)>maximum)throw new IOException("Shader metadata exceeds bound");
        try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);var out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[8192];for(int count;(count=input.read(buffer))!=-1;){if(out.size()+count>maximum)throw new IOException("Shader metadata grew beyond bound");out.write(buffer,0,count);}return out.toByteArray();
        }
    }
    private static MessageDigest digest()throws IOException {
        try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException error){throw new IOException("SHA-256 unavailable",error);}
    }
    private static String hex(byte[] raw){StringBuilder out=new StringBuilder(64);for(byte b:raw)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();}
    private static String sha256(byte[] raw)throws IOException{return hex(digest().digest(raw));}
    private static String hashFile(Path path,long maximum)throws IOException {
        MessageDigest digest=digest();long total=0;
        try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer=new byte[65536];for(int count;(count=input.read(buffer))!=-1;){total+=count;if(total>maximum)throw new IOException("Shader input grew beyond bound");digest.update(buffer,0,count);}
        }if(total!=maximum)throw new IOException("Shader input size changed");return hex(digest.digest());
    }
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Shader lifecycle work must run off the UI thread");}
    private static void checkCancelled(RuntimeWork.Cancellation cancelled)throws IOException {
        if(Thread.currentThread().isInterrupted()||(cancelled!=null&&cancelled.isCancelled()))throw new RuntimeWork.CancelledException();
    }
}
