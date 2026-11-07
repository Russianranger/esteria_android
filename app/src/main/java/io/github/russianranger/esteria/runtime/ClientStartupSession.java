package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/** Internal real-client title investigation, independently of SQL/world setup.
 * No exported Android component or launcher action invokes this owner. It uses
 * the production providers, imported content, shaders and presentation path.
 * CLIENT_STARTED means only that the owned wrapper started: actual CommonMain,
 * content/shader reads and a genuine title frame require runtime evidence.
 */
public final class ClientStartupSession implements AutoCloseable {
    public enum State { ALLOCATED, STARTING, CLIENT_STARTED, FAILED, STOPPING, CLOSED }
    private static final Map<Path,ClientStartupSession> OWNERS=new ConcurrentHashMap<>();
    private final Context context;
    private final Path root;
    private final RuntimeSetup wine;
    private final ClientRuntimeSetup client;
    private final GuestBridgeSetup bridges;
    private final ShaderToolsSetup tools;
    private final ShaderSetup.Result selectedShaders;
    private final TurnipSetup turnip;
    private final ClientPresentationSession.Events events;
    private final GameSession.Leases leases;
    private final ServiceOperationGuard operations=new ServiceOperationGuard();
    private volatile State state=State.ALLOCATED;
    private volatile OwnedProcess process;
    private volatile ClientPresentationSession presentation;
    private volatile IOException failure;
    private volatile Map<String,String> selection=Map.of();

    private ClientStartupSession(Context context,Path root,RuntimeSetup wine,ClientRuntimeSetup client,
            GuestBridgeSetup bridges,ShaderToolsSetup tools,ShaderSetup.Result shaders,TurnipSetup turnip,
            ClientPresentationSession.Events events,GameSession.Leases leases) {
        this.context=context;this.root=root;this.wine=wine;this.client=client;this.bridges=bridges;
        this.tools=tools;selectedShaders=shaders;this.turnip=turnip;this.events=events;this.leases=leases;
    }
    /** Call off the UI thread after selecting/preparing shaders, with every
     * preparation handle closed. The same real import/view locks exclude both
     * GameSession and preparation for the entire client lifetime. */
    public static ClientStartupSession begin(Context context,Path root,RuntimeSetup wine,ClientRuntimeSetup client,
            GuestBridgeSetup bridges,ShaderToolsSetup tools,ShaderSetup.Result shaders,TurnipSetup turnip,
            ClientPresentationSession.Events events)throws IOException {
        background();
        if(context==null||root==null||wine==null||client==null||bridges==null||tools==null||shaders==null||
                !root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Title investigation requires selected providers/shaders and private canonical storage");
        client.requireWineArchive(wine.archiveSha256());bridges.requireWineArchive(wine.archiveSha256());
        tools.requireWineArchive(wine.archiveSha256());
        if(turnip!=null)turnip.requireWineArchive(wine.archiveSha256());
        if(!client.sourceRevision().equals(shaders.clientRevision))throw new IOException("Title client/shader source differs");
        if(OWNERS.containsKey(root))throw new IOException("Previous title investigation still owns its client");
        GameSession.Leases leases=GameSession.claim(root);
        try {
            ClientStartupSession owner=new ClientStartupSession(context.getApplicationContext(),root,wine,client,
                bridges,tools,shaders,turnip,events,leases);
            if(OWNERS.putIfAbsent(root,owner)!=null)throw new IOException("Previous title investigation still owns its client");
            return owner;
        }catch(IOException|RuntimeException error){try{leases.close();}catch(IOException cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    public State state(){return state;}
    public boolean isClientAlive(){OwnedProcess owned=process;return owned!=null&&owned.isAlive();}
    public IOException failure(){return failure;}
    public boolean wasForced(){OwnedProcess child=process;return child!=null&&child.wasForced();}
    /** Exact selected identities, never an assertion that the game read them. */
    public Map<String,String> selection(){return selection;}
    public ClientPresentationSession presentation(){return presentation;}
    public Map<String,Path> diagnosticLogs(){
        ClientPresentationSession owned=presentation;
        return owned==null?Map.of():owned.diagnosticLogs();
    }
    public void start(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
        background();operations.run(()->{
            if(state!=State.ALLOCATED)throw new IOException("Title startup is single-use; close the retained owner");
            state=State.STARTING;
            RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
            RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
            try {
                check(stop);leases.client.require(root);
                ShaderSetup.Result shaders=ShaderSetup.requireCurrent(context,root,wine,tools,selectedShaders,updates,stop);
                ClientLaunchSetup.Prepared view=ClientLaunchSetup.prepareUnderOwnedLease(context,root,client,leases.client,updates,stop);
                if(view==null||!view.plan.importedGeneration.equals(shaders.importGeneration))
                    throw new IOException("Title investigation import and shaders differ");
                ClientPresentationSession.Prepared display=ClientPresentationSession.Prepared.inspect(context,view.work);
                if(!display.wineArchiveSha256.equals(wine.archiveSha256())||!display.bridgeArchiveSha256.equals(bridges.archiveSha256()))
                    throw new IOException("Title presentation selection changed");
                Map<String,String> identity=new TreeMap<>();
                identity.put("scope","real-client-title-investigation-not-qualified");
                identity.put("clientSource",client.sourceRevision());identity.put("clientArchive",client.archiveSha256());
                identity.put("clientGeneration",client.generation());identity.put("importGeneration",shaders.importGeneration);
                identity.put("clientExecutableSha256",client.packagePlan().required.get("bin/WowClient64.exe").sha256);
                identity.put("windowsExecutable",view.plan.windowsExecutable());
                if(turnip!=null)identity.put("turnipGeneration",turnip.generation());
                identity.put("shaderGeneration",shaders.generation);identity.put("effectiveLocale",shaders.locale);
                identity.put("wineArchive",display.wineArchiveSha256);identity.put("bridgeArchive",display.bridgeArchiveSha256);
                identity.put("x11Lock",display.x11LockSha256);identity.put("launchGeneration",view.view.generation);
                selection=java.util.Collections.unmodifiableMap(identity);
                check(stop);presentation=ClientPresentationSession.begin(context,display,events);
                presentation.start();check(stop);
                process=presentation.startClientTitle(client,view,shaders,turnip);
                check(stop);state=State.CLIENT_STARTED;
                updates.update("real-client-title-started-awaiting-evidence","",0,-1);return null;
            }catch(IOException|RuntimeException error){
                state=State.FAILED;remember(error instanceof IOException?(IOException)error:new IOException("Title startup failed",error));throw error;
            }
        });
    }
    @Override public void close()throws IOException {close(Duration.ofSeconds(30));}
    /** No server/account exists in this lifecycle. Attempt normal client exit,
     * then terminate/reap the diagnostic process if necessary. Forced cleanup
     * is reported by the process and never called a clean save. A live process
     * retains presentation, provider selection and both filesystem leases. */
    public void close(Duration timeout)throws IOException {
        background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
            throw new IllegalArgumentException("Title close timeout must be zero to 30 seconds");
        try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
            if(state==State.CLOSED){if(failure!=null)throw failure;return;}
            state=State.STOPPING;OwnedProcess child=process;
            if(child!=null&&child.isAlive()) {
                if(presentation!=null&&permit.remaining().toMillis()>0) {
                    try{presentation.requestClientClose();}catch(IOException error){remember(error);}
                    long deadline=System.nanoTime()+Math.min(permit.remaining().toNanos(),TimeUnit.SECONDS.toNanos(5));
                    while(child.isAlive()&&System.nanoTime()<deadline)try{Thread.sleep(25);}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Title cleanup interrupted; owner retained",error);}
                }
                if(child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException error){remember(error);}
                if(child.isAlive())throw new IOException("Title client cleanup remains active; bindings and leases retained",failure);
            }
            if(presentation!=null) {
                try{presentation.close(permit.remaining());}catch(IOException error){remember(error);}
                if(!presentation.isClosed())throw new IOException("Title presentation cleanup remains active; leases retained",failure);
            }
            leases.close();state=State.CLOSED;OWNERS.remove(root,this);
            if(failure!=null)throw failure;
        }
    }
    public static void retryPendingCleanup(Path root,Duration timeout)throws IOException {
        background();ClientStartupSession owner=OWNERS.get(root);if(owner==null)return;
        if(owner.state!=State.FAILED&&owner.state!=State.STOPPING&&!owner.operations.isStopRequested())
            throw new IOException("Title investigation remains active with its caller");
        owner.close(timeout);
    }
    private synchronized void remember(IOException error){if(failure==null)failure=error;else if(failure!=error&&failure.getSuppressed().length<15)failure.addSuppressed(error);}
    private static void check(RuntimeWork.Cancellation cancelled)throws IOException {
        if(cancelled.isCancelled()||Thread.currentThread().isInterrupted())throw new RuntimeWork.CancelledException();
    }
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Title lifecycle work must run off the UI thread");}
}
