package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
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
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONException;
import org.json.JSONObject;

/** Executes only the pinned offline shader helper. No launcher action calls this
 * until its Android guest and imported-data qualification gates are met.
 */
public final class ShaderSetup {
    private ShaderSetup() { }
    // Both older strict recipes aborted on the input newly handled by their
    // successors. Only a completed donor and this exact installed recipe can use
    // this exception. Every other helper, input and output check stays active.
    private static final Set<String> COMPATIBLE_PREVIOUS_HELPER_FILES = Set.of(
            "60584deae493d314e347cc25818e75122029d0daa5789c81256cfed123d274cc", // v12
            "7234a79084dcdf524e239fe93cf62d779d2052793d1bc8b8a78d4c5371ad85a0"); // v13
    private static final String V14_HELPER_FILES_SHA256="31a2073b5145571c88febb57437d6cffbdc232c8ab7ac080673ba59b17680c7d";

    public static final class Result {
        public final String generation,importGeneration,clientRevision,requestedLocale,locale,toolManifestSha256;
        public final Path shaders,processLogs;
        public final int outputFiles;
        public final long outputBytes;
        public final boolean cancellationRequested;
        private Result(ShaderRunPlan plan,String generation,Path shaders,Path logs,int files,long bytes,boolean cancelled,String toolManifestSha256) {
            this.toolManifestSha256=toolManifestSha256;
            this.generation=generation;importGeneration=plan.importGeneration;clientRevision=plan.clientRevision;requestedLocale=plan.requestedLocale;locale=plan.locale;
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
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(lockPath,"Shader setup is already running");
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            Handle owner=new Handle(context.getApplicationContext(),privateRoot,work,wine,tools,locale,wineRoot,toolsRoot,lease);
            retain(owner);return owner;
        } catch(IOException|RuntimeException|Error error){try{lease.close();}catch(IOException close){error.addSuppressed(close);}throw error;}
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
        private final ExclusiveFileLease lease;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private OwnedProcess process;
        private volatile Map<String,Path> diagnosticLogs=Map.of();
        private IOException cleanupFailure;
        private Handle(Context context,Path root,Path work,RuntimeSetup wine,ShaderToolsSetup tools,String locale,
                Path wineRoot,Path toolsRoot,ExclusiveFileLease lease) {
            this.context=context;this.root=root;this.work=work;this.wine=wine;this.tools=tools;this.locale=locale;
            this.wineRoot=wineRoot;this.toolsRoot=toolsRoot;this.lease=lease;
        }
        public State state(){return state;}
        /** Fixed wrapper streams only; retained after failed startup and close. */
        public Map<String,Path> diagnosticLogs(){return diagnosticLogs;}
        public IOException cleanupFailure(){return cleanupFailure;}
        public boolean processAlive(){OwnedProcess child=process;return child!=null&&child.isAlive();}
        public io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot usage(){OwnedProcess child=process;return child==null?null:child.usage();}
        /** Receipt selection only; no translator is launched. Caller holds the
         * import lease, as for prepare. A new client owner performs full output
         * verification at its own admission boundary through requireCurrent. */
        public Result selectPrepared(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Shader selection already ran; close/retry with a new owner");
                state=State.RUNNING;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    checkCancelled(stop);
                    if(progress!=null)progress.update("shaders-selecting-prepared","",0,-1);
                    if(!wineRoot.equals(wine.current())||!toolsRoot.equals(tools.current()))throw new IOException("Shader providers changed after allocation");
                    ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),toolsRoot,work,StockClientSetup.installHelpers(context,root),tools.revision(),locale);
                    Result result=validatePrepared(plan,tools.toolManifestSha256(),null,false);
                    checkCancelled(stop);state=State.SUCCEEDED;
                    if(progress!=null)progress.update("shaders-reused-bound-receipt-payload-verification-at-client-admission","",result.outputFiles,result.outputFiles);
                    return result;
                }catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
            });
        }
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
            if(progress!=null)progress.update("shaders-provider-admission","",0,-1);
            if(!wineRoot.equals(wine.current())||!toolsRoot.equals(tools.current()))throw new IOException("Shader providers changed after allocation");
            ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),toolsRoot,work,StockClientSetup.installHelpers(context,root),tools.revision(),locale);
            if(progress!=null)progress.update("shaders-locale-selected","requested "+plan.requestedLocale+"; effective "+plan.locale,0,-1);
            Result retained=verifyCompatibleCompleted(plan,tools.toolManifestSha256(),progress,cancelled);
            if(retained!=null)return retained;
            Path sessions=directories(root,"state/shader-operations");
            Path session=sessions.resolve(UUID.randomUUID().toString().replace("-",""));
            Files.createDirectory(session,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            diagnosticLogs=Map.of("setup.shader.stdout.log",session.resolve("logs/stdout.log"),
                "setup.shader.stderr.log",session.resolve("logs/stderr.log"));
            checkCancelled(cancelled);
            if(progress!=null)progress.update("shaders-generating","",0,-1);
            process=ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,session,
                plan.arguments,wine.wineEnvironment(),plan.mounts,null);
            if(progress!=null)progress.update("shaders-child-started","",0,-1);
            // The translator has a two-hour budget; paced output validation
            // can take another seventeen minutes for its allowed 2 GiB output.
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(150);
            long nextProgress=0;
            ServerDataSetup.ProgressLines lines=new ServerDataSetup.ProgressLines();
            String observedPhase="shaders-generating";
            while(process.isAlive()) {
                checkCancelled(cancelled);
                if(progress!=null&&System.nanoTime()>=nextProgress){String observed=lines.read(session.resolve("logs/stdout.log"));if(observed!=null)observedPhase="shaders-"+observed;progress.update(observedPhase,"",0,-1);nextProgress=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);}
                if(System.nanoTime()>=deadline)throw new IOException("Shader setup timed out; previous and staged outputs were retained");
                try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Shader setup interrupted; outputs were retained",error);}
            }
            RuntimeWork.checkMemoryPressureExit(process.exitCode());
            if(process.failure()!=null)throw new IOException("Shader setup process ownership failed",process.failure());
            if(process.exitCode()!=0||process.wasForced())throw workerFailure(process.exitCode(),session.resolve("logs/stderr.log"));
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
                lease.close();state=State.CLOSED;OWNERS.remove(work,this);
                if(error!=null)throw error;
            }
        }
    }
    /** Recheck current provider/import/output metadata while the caller owns
     * import and client-view leases. This remains format-only shader evidence. */
    static Result requireCurrent(Context context,Path root,RuntimeSetup wine,ShaderToolsSetup tools,Result expected)throws IOException {
        return requireCurrent(context,root,wine,tools,expected,RuntimeWork.NONE,null);
    }
    static Result requireCurrent(Context context,Path root,RuntimeSetup wine,ShaderToolsSetup tools,Result expected,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
        background();
        checkCancelled(cancellation);
        if(expected==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private prepared shaders required");
        tools.requireWineArchive(wine.archiveSha256());
        if(wine.current()==null||tools.current()==null)throw new IOException("Prepared shader providers required");
        ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),tools.current(),root.resolve("state/shader-work"),StockClientSetup.installHelpers(context,root),tools.revision(),expected.requestedLocale);
        if(progress!=null)progress.update("shaders-session-integrity","Verifying prepared shaders under current session ownership",0,expected.outputBytes);
        Result current=validatePrepared(plan,tools.toolManifestSha256(),expected.processLogs,false,true,cancellation);
        if(progress!=null)progress.update("shaders-session-integrity-complete","Prepared shaders match their bound receipt",current.outputBytes,current.outputBytes);
        requireSameSelection(current,expected);return current;
    }
    static void requireSameSelection(Result current,Result expected)throws IOException {
        if(!current.generation.equals(expected.generation)||!current.shaders.equals(expected.shaders)||
                !current.toolManifestSha256.equals(expected.toolManifestSha256)||!current.importGeneration.equals(expected.importGeneration)||!current.clientRevision.equals(expected.clientRevision)||
                !current.requestedLocale.equals(expected.requestedLocale)||!current.locale.equals(expected.locale)||current.outputFiles!=expected.outputFiles||current.outputBytes!=expected.outputBytes)
            throw new IOException("Prepared shader selection changed; run local setup again");
    }
    /** Called under import and shader ownership. Keep a compatible completed
     * receipt and generation in place. An interrupted read changes no pointer. */
    static Result verifyCompatibleCompleted(ShaderRunPlan plan,String manifest,RuntimeWork.Progress progress,
            RuntimeWork.Cancellation cancellation)throws IOException {
        checkCancelled(cancellation);
        if(!Files.exists(plan.work.resolve("shaders/current"),LinkOption.NOFOLLOW_LINKS))return null;
        try {
            Result retained=validatePrepared(plan,manifest,null,false,true,cancellation,true);
            if(retained!=null&&progress!=null)progress.update("shaders-reused-verified-previous-recipe","Verified compatible completed shader payload",
                    retained.outputBytes,retained.outputBytes);
            return retained;
        }catch(RuntimeWork.CancelledException error){throw error;}
        catch(IOException error){
            // A previous selection may belong to another locale/import. Leave
            // it intact and let the normal coordinator prepare the current one.
            checkCancelled(cancellation);
            if(progress!=null)progress.update("shaders-preparing-current-selection",error.getMessage(),0,-1);
            return null;
        }
    }
    /** Validate the owned helper's completed receipt and metadata, without a full
     * rescan of imported MPQs. The helper itself hashes every generated output.
     * This host readback checks those output paths/sizes, not GPU correctness.
     */
    static Result validatePrepared(ShaderRunPlan plan,String manifest,Path logs,boolean cancelled)throws IOException {
        return validatePrepared(plan,manifest,logs,cancelled,false);
    }
    /** Full verification is required after ownership changes. The selection
     * path above does only metadata admission; it never supplies an integrity
     * lease or authorizes skipping these hashes in a later client session. */
    static Result validatePrepared(ShaderRunPlan plan,String manifest,Path logs,boolean cancelled,boolean verifyPayload)throws IOException {
        return validatePrepared(plan,manifest,logs,cancelled,verifyPayload,null);
    }
    static Result validatePrepared(ShaderRunPlan plan,String manifest,Path logs,boolean cancelled,boolean verifyPayload,
            RuntimeWork.Cancellation cancellation)throws IOException {
        return validatePrepared(plan,manifest,logs,cancelled,verifyPayload,cancellation,false);
    }
    private static Result validatePrepared(ShaderRunPlan plan,String manifest,Path logs,boolean cancelled,boolean verifyPayload,
            RuntimeWork.Cancellation cancellation,boolean previousOnly)throws IOException {
        checkCancelled(cancellation);
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
            requireKeys(inputs,"formatVersion","contentProfile","importGeneration","clientRevision","locale","importMetadata","toolManifestSha256","preparationHelperSha256","preparationHelperFiles");
            JSONObject helperFiles=inputs.getJSONObject("preparationHelperFiles");
            requireKeys(helperFiles,"stock_content_inspection.py","stock_shader_generation.py","stock_shader_translate.py","shader_generation.py","extractor_order.py","server_data_preflight.py","world_io.py");
            String receiptRecipe=sha256((canonical(helperFiles)+"\n").getBytes(StandardCharsets.UTF_8));
            boolean previous=COMPATIBLE_PREVIOUS_HELPER_FILES.contains(receiptRecipe);
            if(previousOnly&&!previous)return null;
            JSONObject installed=new JSONObject();
            for(Iterator<String> names=helperFiles.keys();names.hasNext();){
                String name=names.next();filePin(helperFiles.getJSONObject(name),131072);
                Path selected=plan.helpers.resolve(name);canonicalFile(selected);
                long selectedBytes=Files.size(selected);
                if(selectedBytes<=0||selectedBytes>131072)throw new IOException("Invalid installed shader helper size");
                installed.put(name,new JSONObject().put("bytes",selectedBytes).put("sha256",hashFile(selected,selectedBytes,cancellation)));
            }
            String installedRecipe=sha256((canonical(installed)+"\n").getBytes(StandardCharsets.UTF_8));
            boolean compatible=previous&&V14_HELPER_FILES_SHA256.equals(installedRecipe);
            if(!receiptRecipe.equals(installedRecipe)&&!compatible)throw new IOException("Prepared shader helper closure changed");
            if(previousOnly&&!compatible)return null;
            String coordinator=helperFiles.getJSONObject("stock_shader_generation.py").getString("sha256");
            if(!coordinator.equals(inputs.get("preparationHelperSha256"))||
                !io.github.russianranger.esteria.core.content.ContentProfile.ID.equals(inputs.get("contentProfile"))||
                integer(inputs,"formatVersion")!=1||!plan.importGeneration.equals(inputs.get("importGeneration"))||
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
                if(Files.size(file)!=bytes||!hashFile(file,bytes,cancellation).equals(item.getString("sha256")))throw new IOException("Import metadata changed after shader setup");
            }
            JSONObject outputs=receipt.getJSONObject("outputs");
            if(outputs.length()<4||outputs.length()>32768*3+2||!outputs.has("manifest.txt")||!outputs.has("index.txt"))
                throw new IOException("Incomplete shader output inventory");
            long total=0;int vertex=0,pixel=0;
            for(Iterator<String> names=outputs.keys();names.hasNext();) {
                checkCancelled(cancellation);
                String name=names.next();
                if(!name.equals("manifest.txt")&&!name.equals("index.txt")&&!name.matches("(?:vertex|pixel)/[0-9a-f]{32}\\.(?:spv|glsl|spvasm)"))
                    throw new IOException("Unexpected shader output path");
                long bytes=filePin(outputs.getJSONObject(name),16L<<20);total+=bytes;
                if(total>2L<<30)throw new IOException("Shader output exceeds bound");
                Path file=shaders.resolve(name);canonicalFile(file);
                if(Files.size(file)!=bytes)throw new IOException("Prepared shader output size changed");
                if(verifyPayload&&!hashFile(file,bytes,cancellation).equals(outputs.getJSONObject(name).getString("sha256")))
                    throw new IOException("Prepared shader output bytes changed: "+name+"; repair shaders");
                if(name.startsWith("vertex/")&&name.endsWith(".spv"))vertex++;
                if(name.startsWith("pixel/")&&name.endsWith(".spv"))pixel++;
            }
            if(vertex==0||pixel==0)throw new IOException("Both prepared shader stages are required");
            if(verifyPayload) {
                // Detect additions as well as changed/deleted listed files.
                int count=0;
                try(var paths=Files.walk(shaders)) {
                    for(var iterator=paths.iterator();iterator.hasNext();) {
                        Path path=iterator.next();checkCancelled(cancellation);
                        String relative=shaders.relativize(path).toString().replace(java.io.File.separatorChar,'/');
                        if(Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)) {
                            canonicalDirectory(path);
                            if(!relative.isEmpty()&&!relative.equals("vertex")&&!relative.equals("pixel"))
                                throw new IOException("Unexpected prepared shader directory: "+relative+"; repair shaders");
                            continue;
                        }
                        canonicalFile(path);
                        if(++count>outputs.length()||!outputs.has(relative))throw new IOException("Unexpected prepared shader output: "+relative+"; repair shaders");
                    }
                }
                if(count!=outputs.length())throw new IOException("Prepared shader output inventory changed; repair shaders");
            }
            plan.requireCurrentImport();
            return new Result(plan,generation,shaders,logs,outputs.length(),total,cancelled,manifest);
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
        return PythonReceiptJson.canonical(value,false);
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
    static IOException workerFailure(int exitCode,Path stderr) {
        String message="Shader setup failed (exit "+exitCode+")";
        String prefix="shader input validation failed: ";
        try {
            for(String line:new String(read(stderr,64<<10),StandardCharsets.UTF_8).split("\\r?\\n")) {
                if(line.startsWith(prefix)) {
                    String detail=io.github.russianranger.esteria.core.diagnostics.SupportBundle.redact(line.substring(prefix.length()));
                    detail=detail.replaceAll("[\\p{Cntrl}\\p{Cf}]"," ").trim();
                    if(!detail.isEmpty())return new IOException(message+". "+detail.substring(0,Math.min(320,detail.length())));
                }
            }
        } catch(IOException ignored) {
            // A rotated, oversized or absent diagnostic cannot mask the worker exit.
        }
        return new IOException(message+". See setup.shader.stderr.log in the support bundle");
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
        return hashFile(path,maximum,null);
    }
    private static String hashFile(Path path,long maximum,RuntimeWork.Cancellation cancellation)throws IOException {
        MessageDigest digest=digest();long total=0;
        try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer=new byte[65536];for(int count;(count=input.read(buffer))!=-1;){checkCancelled(cancellation);total+=count;if(total>maximum)throw new IOException("Shader input grew beyond bound");digest.update(buffer,0,count);io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy.consumed(path,total-count,count);}
        }if(total!=maximum)throw new IOException("Shader input size changed");return hex(digest.digest());
    }
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Shader lifecycle work must run off the UI thread");}
    private static void checkCancelled(RuntimeWork.Cancellation cancelled)throws IOException {
        if(Thread.currentThread().isInterrupted()||(cancelled!=null&&cancelled.isCancelled()))throw new RuntimeWork.CancelledException();
    }
}
