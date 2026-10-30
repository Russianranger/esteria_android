package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.ServerDataToolSelection;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/** Retained source-qualified data preparation. A format-checked binding is not
 * world coverage, Android execution or gameplay qualification. Main never calls
 * this adapter until its separately measured provider prerequisites are met. */
public final class ServerDataSetup {
    private static final String WORK="server-data-work",SETUP_LOCK=".android-server-data-setup.lock";
    private static final ConcurrentHashMap<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private ServerDataSetup(){ }
    public enum State { ALLOCATED,PREPARING,PREPARED,FAILED,CLOSED }
    /** Acquire both actual file leases before observing import selection or
     * starting any helper. Caller retains this owner through cleanup failures. */
    public static Handle begin(Context context,Path root,ServerRuntimeSetup runtime,ServerDataToolsSetup tools,
            String locale,int threads)throws IOException {
        background();options(locale,threads);
        if(context==null||root==null||runtime==null||tools==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Typed prepared data tools and private canonical application storage required");
        tools.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        Path runtimeRoot=runtime.current(),toolsRoot=tools.current(),game=directory(root.resolve("game"));
        if(runtimeRoot==null||toolsRoot==null)throw new IOException("Prepare the source-qualified Ubuntu runtime and composed data tools first");
        privateDirectory(root,runtimeRoot);privateDirectory(root,toolsRoot);
        Path work=GuestHelperAssets.directory(root,WORK);
        for(Path[] pair:new Path[][]{{game,work},{game,toolsRoot},{game,runtimeRoot},{work,toolsRoot},{work,runtimeRoot}})
            if(pair[0].startsWith(pair[1])||pair[1].startsWith(pair[0]))throw new IOException("Data, import and provider directories must be separate");
        if(OWNERS.containsKey(work))throw new IOException("A retained data owner remains active; close or retry that owner first");
        Leases leases=claim(work,game);
        try {
            String imported=ShaderRunPlan.current(game);
            directory(directory(game.resolve("generations")).resolve(imported).resolve("data"));
            Handle owner=new Handle(context.getApplicationContext(),root,game,work,runtime,tools,runtimeRoot,toolsRoot,
                imported,locale,threads,leases,sync(work));
            retain(owner);return owner;
        }catch(IOException|RuntimeException error){try{leases.close();}catch(IOException cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    private static void retain(Handle owner)throws IOException {
        if(OWNERS.putIfAbsent(owner.work,owner)!=null)throw new IOException("Previous data ownership remains retained");
    }
    /** Known-child cleanup only. It cannot steal an allocated/running handle,
     * replay extraction or remove interrupted/completed user data generations. */
    public static void retryPendingCleanup(Context context,Path root,Duration timeout)throws IOException {
        background();if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical data storage required");
        Handle owner=OWNERS.get(root.resolve(WORK));if(owner==null)return;
        if(owner.state!=State.FAILED&&!owner.operations.isStopRequested())throw new IOException("Data setup remains with its active caller");
        owner.close(timeout);
    }
    /** Real import/setup leases, shared with GameDataImporter and the future
     * playing-session owner. No lease is released while its native child lives. */
    static final class Leases implements AutoCloseable {
        private final FileChannel setupChannel,importChannel;
        private final FileLock setup,imported;
        private boolean closed;
        private Leases(FileChannel setupChannel,FileLock setup,FileChannel importChannel,FileLock imported) {
            this.setupChannel=setupChannel;this.setup=setup;this.importChannel=importChannel;this.imported=imported;
        }
        @Override public void close()throws IOException {
            if(closed)return;IOException failure=null;
            try{imported.release();}catch(IOException error){failure=error;}
            try{importChannel.close();}catch(IOException error){if(failure==null)failure=error;else failure.addSuppressed(error);}
            try{setup.release();}catch(IOException error){if(failure==null)failure=error;else failure.addSuppressed(error);}
            try{setupChannel.close();}catch(IOException error){if(failure==null)failure=error;else failure.addSuppressed(error);}
            closed=true;if(failure!=null)throw failure;
        }
    }
    static Leases claim(Path work,Path game)throws IOException {
        FileChannel setupChannel=lockChannel(work.resolve(SETUP_LOCK));FileLock setup=null;
        FileChannel importChannel=null;FileLock imported=null;
        try {
            setup=exclusive(setupChannel,"Another data setup is active");
            importChannel=lockChannel(game.resolve("import.lock"));
            imported=exclusive(importChannel,"Import/client data is already in use");
            return new Leases(setupChannel,setup,importChannel,imported);
        }catch(IOException|RuntimeException error) {
            try{if(imported!=null)imported.release();}finally{try{if(importChannel!=null)importChannel.close();}finally{
                try{if(setup!=null)setup.release();}finally{setupChannel.close();}}}
            throw error;
        }
    }
    private static FileChannel lockChannel(Path path)throws IOException {
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)&&(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path)))
            throw new IOException("Invalid data operation/import lock");
        FileChannel channel=FileChannel.open(path,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        try{Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));return channel;}
        catch(IOException|RuntimeException error){channel.close();throw error;}
    }
    private static FileLock exclusive(FileChannel channel,String message)throws IOException {
        try{FileLock lock=channel.tryLock();if(lock==null)throw new IOException(message);return lock;}
        catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException(message,busy);}
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root,game,work,runtimeRoot,toolsRoot;
        private final ServerRuntimeSetup runtime;
        private final ServerDataToolsSetup tools;
        private final String imported,locale;
        private final int threads;
        private final Leases leases;
        public final boolean directorySyncSupported;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private volatile OwnedProcess process;
        private volatile IOException failure,cleanupFailure;
        private volatile Path logs;
        private volatile String phase="allocated";
        private volatile long beganNanos;
        private ServerDataRunPlan plan;
        private Handle(Context context,Path root,Path game,Path work,ServerRuntimeSetup runtime,ServerDataToolsSetup tools,
                Path runtimeRoot,Path toolsRoot,String imported,String locale,int threads,Leases leases,boolean directorySyncSupported) {
            this.context=context;this.root=root;this.game=game;this.work=work;this.runtime=runtime;this.tools=tools;
            this.runtimeRoot=runtimeRoot;this.toolsRoot=toolsRoot;this.imported=imported;this.locale=locale;this.threads=threads;
            this.leases=leases;this.directorySyncSupported=directorySyncSupported;
        }
        public State state(){return state;}
        public IOException failure(){return failure;}
        public IOException cleanupFailure(){return cleanupFailure;}
        public Path privateLogs(){return logs;}
        public String phase(){return phase;}
        public long elapsedSeconds(){return beganNanos==0?0:TimeUnit.NANOSECONDS.toSeconds(System.nanoTime()-beganNanos);}
        /** Single-use. Canonical selection is supplied by the typed source-
         * qualified provider; no public self-hashed plan can replace it. */
        public ServerDataBinding prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Data preparation already ran; close/retry with a new owner");
                state=State.PREPARING;beganNanos=System.nanoTime();
                RuntimeWork.Cancellation cancelled=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    check(cancelled);providers();
                    if(!imported.equals(ShaderRunPlan.current(game)))throw new IOException("Import changed after data ownership allocation");
                    phase="helpers";report(progress);
                    String helper=ServerDataAssets.install(context,work);
                    ServerDataToolSelection selected=tools.selection();
                    atomicSelection(work.resolve("data-tools-selection.json"),selected.bytes(),directorySyncSupported);
                    plan=new ServerDataRunPlan(game,toolsRoot,work,helper,selected.sha256,locale,threads);
                    check(cancelled);providers();
                    Path sessions=GuestHelperAssets.directory(root,"state/server-data-operations");
                    Path session=Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","")),
                        PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
                    logs=session.resolve("logs");phase="preparing";report(progress);
                    check(cancelled);
                    long deadline=beganNanos+TimeUnit.HOURS.toNanos(24);
                    if(System.nanoTime()>=deadline)throw new IOException("Data preparation exceeded24hours before launch; outputs retained");
                    process=ProotProcess.start(context,runtime.installer(),runtime.packagePlan(),work,session,
                        plan.arguments,java.util.Collections.emptyMap(),plan.mounts,null);
                    long nextProgress=0;
                    ProgressLines lines=new ProgressLines();
                    while(process.isAlive()) {
                        check(cancelled);
                        if(System.nanoTime()>=deadline)throw new IOException("Data preparation exceeded24hours; previous and staged outputs retained");
                        if(System.nanoTime()>=nextProgress) {
                            String observed=lines.read(logs.resolve("stdout.log"));if(observed!=null)phase=observed;
                            report(progress);nextProgress=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);
                        }
                        try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Data preparation interrupted; owner and outputs retained",error);}
                    }
                    if(process.failure()!=null||process.wasForced()||process.exitCode()!=0)
                        throw new IOException("Source-qualified data preparation failed; private logs and outputs retained",process.failure());
                    check(cancelled);providers();plan.requireInputsUnchanged();
                    ServerDataBinding binding=ServerDataBinding.inspect(plan,ServerDataToolSelection.SERVER_REVISION);
                    check(cancelled);phase="format-checked";state=State.PREPARED;report(progress);return binding;
                }catch(IOException|RuntimeException error) {
                    state=State.FAILED;failure=error instanceof IOException?(IOException)error:new IOException("Data setup owner failed",error);
                    if(process!=null&&process.isAlive()) {
                        boolean interrupted=Thread.interrupted();
                        try{process.stop(Duration.ZERO);}catch(IOException cleanup){cleanupFailure=cleanup;if(cleanup!=error)error.addSuppressed(cleanup);}
                        finally{if(interrupted)Thread.currentThread().interrupt();}
                    }
                    throw error;
                }
            });
        }
        private void providers()throws IOException {
            if(!runtimeRoot.equals(runtime.current())||!toolsRoot.equals(tools.current()))throw new IOException("Data runtime/provider selection changed after allocation");
            tools.requireServerRuntimeArchive(runtime.packagePlan().archiveSha256);
        }
        private void report(RuntimeWork.Progress progress) {
            if(progress!=null)progress.update("server-data-"+phase,"Elapsed: "+elapsedSeconds()+"s",0,-1);
        }
        @Override public void close()throws IOException {close(Duration.ofSeconds(20));}
        /** Stop requests cancellation before the safe-boundary wait. A timeout
         * retains both real locks and every native/provider owner for retry. */
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Data close timeout must be zero to30seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED){throwCleanup();return;}
                if(process!=null&&process.isAlive()) {
                    try{process.stop(permit.remaining());}catch(IOException error){cleanupFailure=error;}
                    if(process.isAlive())throw new IOException("Data native cleanup remains active; setup and import leases retained",cleanupFailure);
                }
                try{leases.close();}finally{state=State.CLOSED;OWNERS.remove(work,this);}
                throwCleanup();
            }
        }
        private void throwCleanup()throws IOException {
            if(cleanupFailure!=null)throw new IOException("Earlier data cleanup failure remains visible; stopped outputs retained",cleanupFailure);
        }
    }
    /** Read only new bounded log bytes; only known phase identifiers reach UI. */
    private static final class ProgressLines {
        private long offset;
        private final ByteArrayOutputStream pending=new ByteArrayOutputStream();
        private boolean overflow;
        String read(Path path)throws IOException {
            if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return null;
            if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))throw new IOException("Invalid data progress log");
            String last=null;
            try(FileChannel input=FileChannel.open(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
                if(input.size()<offset)throw new IOException("Data progress log was replaced/truncated");input.position(offset);
                ByteBuffer buffer=ByteBuffer.allocate(4096);int budget=65536;
                while(budget>0) {
                    buffer.clear();buffer.limit(Math.min(buffer.capacity(),budget));int got=input.read(buffer);if(got<=0)break;
                    offset+=got;budget-=got;buffer.flip();
                    while(buffer.hasRemaining()) {
                        byte value=buffer.get();
                        if(value=='\n') {
                            if(!overflow){String phase=known(new String(pending.toByteArray(),StandardCharsets.US_ASCII).replace("\r",""));if(phase!=null)last=phase;}
                            pending.reset();overflow=false;
                        }else if(!overflow){if(pending.size()<4096)pending.write(value);else{pending.reset();overflow=true;}}
                    }
                }
            }
            return last;
        }
        private static String known(String value) {
            switch(value) {
                case "extraction-provider-order":return "provider-order";
                case "extraction-map_extractor":return "maps-dbc-cameras";
                case "extraction-vmap4_extractor":return "raw-collision";
                case "extraction-vmap4_assembler":return "assembled-collision";
                case "extraction-mmaps_generator":return "navigation";
                case "extraction-supplied-server-data":return "matched-server-data";
                case "extraction-format-checked":return "format-checked";
                default:return null;
            }
        }
    }
    static void atomicSelection(Path target,byte[] bytes,boolean directorySync)throws IOException {
        if(bytes.length==0||bytes.length>65536)throw new IOException("Bounded canonical tool selection required");
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)&&(!Files.isRegularFile(target,LinkOption.NOFOLLOW_LINKS)||!target.toRealPath().equals(target)))
            throw new IOException("Existing data selection metadata is not a regular owned file");
        Path temporary=target.resolveSibling("."+target.getFileName()+"-"+UUID.randomUUID());
        try {
            try(FileChannel output=FileChannel.open(temporary,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                Files.setPosixFilePermissions(temporary,PosixFilePermissions.fromString("rw-------"));ByteBuffer value=ByteBuffer.wrap(bytes);while(value.hasRemaining())output.write(value);output.force(true);
            }
            Files.move(temporary,target,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            if(directorySync&&!sync(target.getParent()))throw new IOException("Data selection directory sync failed");
        }finally{Files.deleteIfExists(temporary);}
    }
    private static void check(RuntimeWork.Cancellation cancelled)throws IOException {if(Thread.currentThread().isInterrupted()||cancelled.isCancelled())throw new RuntimeWork.CancelledException();}
    private static void options(String locale,int threads)throws IOException {if(locale==null||!List.of("deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU").contains(locale)||threads<1||threads>2)throw new IOException("Explicit data locale and one/two extraction workers required");}
    private static Path directory(Path path)throws IOException {if(!path.isAbsolute()||!path.normalize().equals(path)||!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||!path.toRealPath().equals(path))throw new IOException("Canonical private data directory required");return path;}
    private static void privateDirectory(Path root,Path path)throws IOException {directory(path);if(!path.startsWith(root)||path.equals(root))throw new IOException("Runtime/data tools must be in private application storage");}
    private static boolean sync(Path directory){try(FileChannel channel=FileChannel.open(directory,StandardOpenOption.READ)){channel.force(true);return true;}catch(IOException|UnsupportedOperationException unsupported){return false;}}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Data preparation lifecycle must run off the UI thread");}
}
