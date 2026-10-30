package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.Collections;
import java.util.concurrent.ConcurrentHashMap;

/** Retained setup pipeline. Data preparation holds the import lease throughout
 * shader generation and schema setup. Only actual completed SQL/clean-stop
 * proofs promote a database; nothing here qualifies world entry or gameplay. */
public final class LocalWorldSetup {
    private static final ConcurrentHashMap<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private LocalWorldSetup(){ }
    public enum State { ALLOCATED,PREPARING,PREPARED,FAILED,CLOSED }
    public static final class Result {
        public final ServerDataBinding data;
        public final ShaderSetup.Result shaders;
        public final FreshServerInstallations.Active installation;
        public final boolean reusedInstallation;
        final Path applicationRoot;
        final ServerRuntimeSetup server;
        final ServerProgramsSetup programs;
        final ServerContentSetup content;
        final RuntimeSetup wine;
        final ShaderToolsSetup shaderTools;
        private Result(Handle owner,ServerDataBinding data,ShaderSetup.Result shaders,FreshServerInstallations.Active installation) {
            this.data=data;this.shaders=shaders;this.installation=installation;reusedInstallation=owner.previous!=null;
            applicationRoot=owner.root;server=owner.server;programs=owner.programs;content=owner.content;
            wine=owner.wine;shaderTools=owner.shaderTools;
        }
    }
    /** Allocate before any setup child. Providers must already be installed.
     * The free-space budget is a conservative caller policy, not a measured
     * database footprint or a promise that all supplied world data is usable. */
    public static Handle begin(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,
            ServerContentSetup content,ServerDataToolsSetup dataTools,RuntimeSetup wine,ShaderToolsSetup shaderTools,
            String locale,int threads,long freshDatabaseReserve)throws IOException {
        background();
        if(context==null||root==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Private canonical setup storage required");
        if(server==null||programs==null||content==null||dataTools==null||wine==null||shaderTools==null)
            throw new IOException("The complete source-qualified local setup profile is required");
        if(freshDatabaseReserve<=0||freshDatabaseReserve>(32L<<30))throw new IOException("Invalid fresh database storage budget");
        programs.requireServerRuntimeArchive(server.archiveSha256());content.requireServerRuntimeArchive(server.archiveSha256());
        dataTools.requireServerRuntimeArchive(server.archiveSha256());shaderTools.requireWineArchive(wine.archiveSha256());
        if(server.current()==null||programs.current()==null||content.current()==null||dataTools.current()==null||
                wine.current()==null||shaderTools.current()==null)throw new IOException("Prepare all pinned runtime providers before local world setup");
        // This is deliberately before extraction and before fresh SQL. A stock
        // programs-only APK must not begin an installation it cannot complete.
        FreshServerInstallations.Active previous=ServerInstallationSetup.completedOrNull(context,root,server,programs,content);
        Path state=GuestHelperAssets.directory(root,"state");Path lockPath=state.resolve(".local-world-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&(!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS)||
                !lockPath.equals(lockPath.toRealPath())))throw new IOException("Invalid local setup ownership file");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        FileLock lock=null;
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            try{lock=channel.tryLock();}catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException("Local world setup is already owned",busy);}
            if(lock==null)throw new IOException("Local world setup is already owned");
            Handle owner=new Handle(context.getApplicationContext(),root,server,programs,content,dataTools,wine,shaderTools,
                locale,threads,freshDatabaseReserve,previous,channel,lock);
            if(OWNERS.putIfAbsent(root,owner)!=null)throw new IOException("Previous local setup cleanup remains retained");
            return owner;
        }catch(IOException|RuntimeException error){try{if(lock!=null)lock.release();}finally{channel.close();}throw error;}
    }
    public static final class Handle implements AutoCloseable {
        private final Context context;
        private final Path root;
        private final ServerRuntimeSetup server;
        private final ServerProgramsSetup programs;
        private final ServerContentSetup content;
        private final ServerDataToolsSetup tools;
        private final RuntimeSetup wine;
        private final ShaderToolsSetup shaderTools;
        private final String locale;
        private final int threads;
        private final long reserve;
        private final FreshServerInstallations.Active previous;
        private final FileChannel channel;
        private final FileLock lock;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private volatile IOException failure;
        private volatile ServerDataSetup.Handle data;
        private volatile ShaderSetup.Handle shaders;
        private volatile ServerInstallationSetup.Handle installation;
        private Handle(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,ServerContentSetup content,
                ServerDataToolsSetup tools,RuntimeSetup wine,ShaderToolsSetup shaderTools,String locale,int threads,long reserve,
                FreshServerInstallations.Active previous,FileChannel channel,FileLock lock) {
            this.context=context;this.root=root;this.server=server;this.programs=programs;this.content=content;this.tools=tools;
            this.wine=wine;this.shaderTools=shaderTools;this.locale=locale;this.threads=threads;this.reserve=reserve;
            this.previous=previous;this.channel=channel;this.lock=lock;
        }
        public State state(){return state;}
        /** Known operation streams; no directory discovery or credential files. */
        public Map<String,Path> diagnosticLogs(){
            Map<String,Path> logs=new LinkedHashMap<>();
            ServerDataSetup.Handle currentData=data;
            if(currentData!=null&&currentData.privateLogs()!=null){Path directory=currentData.privateLogs();
                logs.put("setup.data.stdout.log",directory.resolve("stdout.log"));
                logs.put("setup.data.stderr.log",directory.resolve("stderr.log"));}
            ShaderSetup.Handle currentShaders=shaders;
            if(currentShaders!=null)logs.putAll(currentShaders.diagnosticLogs());
            ServerInstallationSetup.Handle currentInstallation=installation;
            if(currentInstallation!=null)logs.putAll(currentInstallation.diagnosticLogs());
            return Collections.unmodifiableMap(logs);
        }
        public IOException failure(){return failure;}
        public Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Local world setup is single-use; retain and close this owner");
                state=State.PREPARING;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
                try {
                    check(stop);data=ServerDataSetup.begin(context,root,server,tools,locale,threads);
                    ServerDataBinding binding=data.prepare(updates,stop);
                    check(stop);shaders=ShaderSetup.begin(context,root,wine,shaderTools,locale);
                    ShaderSetup.Result generated=shaders.prepare(updates,stop);
                    binding.requireUnchanged();check(stop);
                    FreshServerInstallations.Active active=previous;
                    if(active==null) {
                        // Recheck absence under the transactional installation
                        // lock in beginFresh; never replace an intervening save.
                        installation=ServerInstallationSetup.beginFresh(context,root,server,programs,content,binding.directory,reserve);
                        installation.prepare(updates,stop);check(stop);
                        installation.finishPlayerbots(updates,stop);check(stop);
                        active=installation.stopAndPromote(Duration.ofSeconds(30));
                    } else active=ServerInstallationSetup.completed(context,root,server,programs,content);
                    binding.requireUnchanged();check(stop);
                    if(!generated.importGeneration.equals(binding.inputs().getString("importGeneration")))
                        throw new IOException("Shader and server data import generations differ");
                    state=State.PREPARED;
                    return new Result(this,binding,generated,active);
                }catch(org.json.JSONException error){failure=new IOException("Invalid prepared input identity",error);state=State.FAILED;throw failure;}
                catch(IOException|RuntimeException error){failure=error instanceof IOException?(IOException)error:new IOException("Local world setup failed",error);state=State.FAILED;throw error;}
            });
        }
        @Override public void close()throws IOException {close(Duration.ofSeconds(30));}
        /** Keep data/import ownership until every dependent SQL/shader child
         * has confirmed cleanup. Deadline failures leave this exact owner and
         * all later dependencies retained for another bounded close attempt. */
        public void close(Duration timeout)throws IOException {
            background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
                throw new IllegalArgumentException("Setup close timeout must be zero to30seconds");
            try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED)return;
                IOException error=null;
                if(installation!=null)try{installation.close(permit.remaining());}catch(IOException issue){error=issue;}
                if(installation!=null&&installation.state()!=ServerInstallationSetup.State.CLOSED)throw retained(error);
                if(shaders!=null)try{shaders.close(permit.remaining());}catch(IOException issue){error=add(error,issue);}
                if(shaders!=null&&shaders.state()!=ShaderSetup.State.CLOSED)throw retained(error);
                if(data!=null)try{data.close(permit.remaining());}catch(IOException issue){error=add(error,issue);}
                if(data!=null&&data.state()!=ServerDataSetup.State.CLOSED)throw retained(error);
                try{lock.release();}finally{try{channel.close();}finally{state=State.CLOSED;OWNERS.remove(root,this);}}
                if(error!=null)throw error;
            }
        }
        private static IOException retained(IOException error){return error==null?new IOException("Local setup cleanup remains active; import and provider owners retained"):error;}
        private static IOException add(IOException error,IOException next){if(error==null)return next;if(error!=next&&error.getSuppressed().length<15)error.addSuppressed(next);return error;}
    }
    private static void check(RuntimeWork.Cancellation stop)throws RuntimeWork.CancelledException {
        if(stop.isCancelled()||Thread.currentThread().isInterrupted())throw new RuntimeWork.CancelledException();
    }
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Local world setup must run off the UI thread");}
}
