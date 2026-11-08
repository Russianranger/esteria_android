package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
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
    public enum Component {
        CLIENT_RUNTIME("Client runtime"),SERVER_RUNTIME("Server runtime"),WORLD_DATA("World data"),SHADERS("Shaders"),DATABASE("Database setup");
        public final String label;
        Component(String label){this.label=label;}
    }
    /** A named missing/incompatible selection is not an instruction to delete
     * retained work. Repairs remain explicit and limited to this component. */
    public static final class PreparationRequired extends IOException {
        public final Component component;
        public PreparationRequired(Component component,IOException cause) {
            this(component,cause,false);
        }
        private PreparationRequired(Component component,IOException cause,boolean repairAttempted) {
            super(repairAttempted
                    ? component.label+" repair failed. "+cause.getMessage()+". Export support bundle before retrying."
                    : component.label+" is not ready: "+cause.getMessage()+". Use Repair local component → "+component.label+". Existing imports and saves are retained.",cause);
            this.component=component;
        }
    }
    private interface Checked<T>{T get()throws IOException;}
    private static <T> T component(Component selected,Checked<T> action)throws IOException {
        try{return action.get();}
        catch(RuntimeWork.CancelledException error){throw error;}
        catch(PreparationRequired error){throw error;}
        catch(IOException error){throw new PreparationRequired(selected,error);}
    }
    private static Path installed(Component selected,Checked<Path> action)throws IOException {
        return component(selected,()->{Path path=action.get();if(path==null)throw new IOException("The selected bundled provider is not installed");return path;});
    }
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
        return begin(context,root,server,programs,content,dataTools,wine,shaderTools,locale,threads,freshDatabaseReserve,RuntimeWork.NONE);
    }
    public static Handle begin(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,
            ServerContentSetup content,ServerDataToolsSetup dataTools,RuntimeSetup wine,ShaderToolsSetup shaderTools,
            String locale,int threads,long freshDatabaseReserve,RuntimeWork.Progress progress)throws IOException {
        background();
        if(context==null||root==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Private canonical setup storage required");
        if(server==null||programs==null||content==null||dataTools==null||wine==null||shaderTools==null)
            throw new IOException("The complete source-qualified local setup profile is required");
        if(freshDatabaseReserve<=0||freshDatabaseReserve>(32L<<30))throw new IOException("Invalid fresh database storage budget");
        programs.requireServerRuntimeArchive(server.archiveSha256());content.requireServerRuntimeArchive(server.archiveSha256());
        dataTools.requireServerRuntimeArchive(server.archiveSha256());shaderTools.requireWineArchive(wine.archiveSha256());
        RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
        updates.update("world-admission-server-runtime","",0,-1);installed(Component.SERVER_RUNTIME,server::current);
        updates.update("world-admission-server-programs","",0,-1);installed(Component.SERVER_RUNTIME,programs::current);
        updates.update("world-admission-server-content","",0,-1);installed(Component.SERVER_RUNTIME,content::current);
        updates.update("world-admission-data-tools","",0,-1);installed(Component.SERVER_RUNTIME,dataTools::current);
        updates.update("world-admission-client-runtime","",0,-1);installed(Component.CLIENT_RUNTIME,wine::current);
        updates.update("world-admission-shader-tools","",0,-1);installed(Component.CLIENT_RUNTIME,shaderTools::current);
        // This is deliberately before extraction and before fresh SQL. A stock
        // programs-only APK must not begin an installation it cannot complete.
        updates.update("world-admission-existing-database","",0,-1);
        FreshServerInstallations.Active previous=component(Component.DATABASE,()->ServerInstallationSetup.completedOrNull(context,root,server,programs,content));
        return allocate(context,root,server,programs,content,dataTools,wine,shaderTools,locale,threads,freshDatabaseReserve,previous);
    }
    public static Handle beginShaderRepair(Context context,Path root,RuntimeSetup wine,ShaderToolsSetup shaderTools,String locale)throws IOException {
        background();
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical setup storage required");
        shaderTools.requireWineArchive(wine.archiveSha256());
        installed(Component.CLIENT_RUNTIME,wine::current);
        installed(Component.CLIENT_RUNTIME,shaderTools::current);
        return allocate(context,root,null,null,null,null,wine,shaderTools,locale,0,0,null);
    }
    private static Handle allocate(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,
            ServerContentSetup content,ServerDataToolsSetup dataTools,RuntimeSetup wine,ShaderToolsSetup shaderTools,
            String locale,int threads,long freshDatabaseReserve,FreshServerInstallations.Active previous)throws IOException {
        Path state=GuestHelperAssets.directory(root,"state");Path lockPath=state.resolve(".local-world-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&(!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS)||
                !lockPath.equals(lockPath.toRealPath())))throw new IOException("Invalid local setup ownership file");
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(lockPath,"Local world setup is already owned");
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            Handle owner=new Handle(context.getApplicationContext(),root,server,programs,content,dataTools,wine,shaderTools,
                locale,threads,freshDatabaseReserve,previous,lease);
            if(OWNERS.putIfAbsent(root,owner)!=null)throw new IOException("Previous local setup cleanup remains retained");
            return owner;
        }catch(IOException|RuntimeException|Error error){try{lease.close();}catch(IOException close){error.addSuppressed(close);}throw error;}
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
        private final ExclusiveFileLease lease;
        private final ServiceOperationGuard operations=new ServiceOperationGuard();
        private volatile State state=State.ALLOCATED;
        private volatile IOException failure;
        private volatile ServerDataSetup.Handle data;
        private volatile ShaderSetup.Handle shaders;
        private ExclusiveFileLease shaderImport;
        private volatile ServerInstallationSetup.Handle installation;
        private Handle(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,ServerContentSetup content,
                ServerDataToolsSetup tools,RuntimeSetup wine,ShaderToolsSetup shaderTools,String locale,int threads,long reserve,
                FreshServerInstallations.Active previous,ExclusiveFileLease lease) {
            this.context=context;this.root=root;this.server=server;this.programs=programs;this.content=content;this.tools=tools;
            this.wine=wine;this.shaderTools=shaderTools;this.locale=locale;this.threads=threads;this.reserve=reserve;
            this.previous=previous;this.lease=lease;
        }
        public State state(){return state;}
        /** Known operation streams; no directory discovery or credential files. */
        public String installationDiagnostic(){
            ServerInstallationSetup.Handle owner=installation;
            return owner==null?null:owner.diagnosticState();
        }
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
        public Map<String,ProcessUsageSnapshot> diagnosticUsage(){
            Map<String,ProcessUsageSnapshot> usage=new LinkedHashMap<>();
            ServerDataSetup.Handle currentData=data;if(currentData!=null&&currentData.processAlive())usage.put("data",currentData.usage());
            ShaderSetup.Handle currentShaders=shaders;if(currentShaders!=null&&currentShaders.processAlive())usage.put("shader",currentShaders.usage());
            return usage;
        }
        /** Named shader repair owns only the import, selected shader runtime and derived output. */
        public ShaderSetup.Result repairShaders(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();
            return operations.run(()->{
                if(state!=State.ALLOCATED||server!=null)throw new IOException("A fresh shader repair owner is required");
                state=State.PREPARING;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    check(stop);
                    shaderImport=ExclusiveFileLease.acquire(root.resolve("game/import.lock"),"Import/client data is already in use");
                    shaders=component(Component.SHADERS,()->ShaderSetup.begin(context,root,wine,shaderTools,locale));
                    ShaderSetup.Result result=shaders.repair(progress,stop);
                    check(stop);state=State.PREPARED;
                    return result;
                }catch(RuntimeWork.CancelledException error){state=State.FAILED;failure=error;throw error;}
                catch(IOException error){state=State.FAILED;failure=error;throw new PreparationRequired(Component.SHADERS,error,true);}
            });
        }
        public Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            return run(null,false,progress,cancellation);
        }
        /** Normal startup selects completed receipts only. No extraction,
         * translation, SQL setup, download or runtime installer is invoked. */
        public Result selectPrepared(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            return run(null,true,progress,cancellation);
        }
        /** Rebuild/revalidate just the named derived component. Database setup
         * uses the existing transactional owner and never initializes over an
         * active save. Other components must already be selectable. */
        public Result repair(Component selected,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            if(selected!=Component.WORLD_DATA&&selected!=Component.SHADERS&&selected!=Component.DATABASE)
                throw new IOException("Runtime components use their separate runtime preparation action");
            try{return run(selected,false,progress,cancellation);}
            catch(PreparationRequired error){
                // A successful repair can expose a different missing component.
                if(error.component!=selected)throw error;
                throw new PreparationRequired(selected,(IOException)error.getCause(),true);
            }
        }
        private Result run(Component repair,boolean selectOnly,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Local world setup is single-use; retain and close this owner");
                state=State.PREPARING;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
                try {
                    updates.update("world-data-owner-admission","",0,-1);
                    check(stop);data=component(Component.WORLD_DATA,()->ServerDataSetup.begin(context,root,server,tools,locale,threads));
                    ServerDataBinding binding=component(Component.WORLD_DATA,()->
                        !selectOnly&&(repair==null||repair==Component.WORLD_DATA)?data.prepare(updates,stop):data.selectPrepared(updates,stop));
                    updates.update("world-shader-owner-admission","",0,-1);
                    check(stop);shaders=component(Component.SHADERS,()->ShaderSetup.begin(context,root,wine,shaderTools,locale));
                    ShaderSetup.Result generated=component(Component.SHADERS,()->
                        repair==Component.SHADERS?shaders.repair(updates,stop):
                        !selectOnly&&repair==null?shaders.prepare(updates,stop):shaders.selectPrepared(updates,stop));
                    if(!generated.locale.equals(binding.effectiveLocale))
                        throw new IOException("Shader and server data effective client locales differ; prepared outputs are retained");
                    binding.requireUnchanged();check(stop);
                    FreshServerInstallations.Active active=previous;
                    if(active==null) {
                        if(selectOnly||(repair!=null&&repair!=Component.DATABASE))
                            throw new PreparationRequired(Component.DATABASE,new IOException("No completed source-matched database setup is selected"));
                        // Recheck absence under the transactional installation
                        // lock in beginFresh; never replace an intervening save.
                        updates.update("world-database-owner-admission","",0,-1);
                        installation=component(Component.DATABASE,()->ServerInstallationSetup.beginFresh(context,root,server,programs,content,binding.directory,reserve));
                        active=component(Component.DATABASE,()->{
                            installation.prepare(updates,stop);check(stop);
                            installation.finishPlayerbots(updates,stop);check(stop);
                            updates.update("installation-clean-stop-and-promotion","",0,-1);
                            return installation.stopAndPromote(Duration.ofSeconds(30));
                        });
                    } else active=component(Component.DATABASE,()->ServerInstallationSetup.completed(context,root,server,programs,content));
                    binding.requireUnchanged();check(stop);
                    if(!generated.importGeneration.equals(binding.inputs().getString("importGeneration")))
                        throw new IOException("Shader and server data import generations differ");
                    state=State.PREPARED;
                    if(selectOnly)updates.update("world-reused-source-bound-prepared-selection","Payload integrity is checked by the new session owner",0,-1);
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
                if(shaderImport!=null){shaderImport.close();shaderImport=null;}
                lease.close();state=State.CLOSED;OWNERS.remove(root,this);
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
