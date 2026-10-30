package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import io.github.russianranger.esteria.core.presentation.InputSink;
import io.github.russianranger.esteria.core.presentation.X11SessionPlan;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.runtime.GuestBridgeSetup;
import io.github.russianranger.esteria.runtime.ClientLaunchSetup;
import io.github.russianranger.esteria.runtime.ClientRuntimeSetup;
import io.github.russianranger.esteria.runtime.ShaderSetup;
import io.github.russianranger.esteria.runtime.TurnipSetup;
import io.github.russianranger.esteria.runtime.ProotProcess;
import io.github.russianranger.esteria.runtime.RuntimeSetup;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Owns the local display/input/audio components, not a game process. Creating
 * this session establishes no Android rendering, audible-output, or gameplay
 * qualification. Full client activation must separately require the qualified
 * offline-capable client, complete data/shaders and local server readiness.
 */
public final class ClientPresentationSession implements AutoCloseable {
    public interface Events {
        void frameSize(int width,int height);
        void failed(String reason);
    }
    /** Constructed only from installed, matching providers; no arbitrary guest executable. */
    public static final class Prepared {
        private final RuntimeSetup runtime;
        private final GuestBridgeSetup bridges;
        private final Path runtimeRoot,bridgeRoot,work;
        public final String wineArchiveSha256,bridgeArchiveSha256,x11LockSha256;
        private Prepared(RuntimeSetup runtime,GuestBridgeSetup bridges,Path runtimeRoot,Path bridgeRoot,Path work,String lock) {
            this.runtime=runtime;this.bridges=bridges;this.runtimeRoot=runtimeRoot;this.bridgeRoot=bridgeRoot;this.work=work;
            wineArchiveSha256=runtime.archiveSha256();bridgeArchiveSha256=bridges.archiveSha256();x11LockSha256=lock;
        }
        /** Performs bounded verification off the UI thread; downloads nothing. */
        public static Prepared inspect(Context context,Path work)throws IOException {
            background();Context app=context.getApplicationContext();Path root=app.getFilesDir().getCanonicalFile().toPath();
            RuntimeSetup runtime=new RuntimeSetup(app,root);GuestBridgeSetup bridges=new GuestBridgeSetup(app,root);
            bridges.requireWineArchive(runtime.archiveSha256());
            Path runtimeRoot=runtime.current(),bridgeRoot=bridges.current();
            if(runtimeRoot==null||bridgeRoot==null)throw new IOException("Presentation runtime providers are not prepared");
            Path privateWork=BridgePaths.directory(app,work.toFile());
            String lock=PresentationRuntimeChecks.verify(app,runtimeRoot,runtime.archiveSha256());
            return new Prepared(runtime,bridges,runtimeRoot,bridgeRoot,privateWork,lock);
        }
    }
    // Also retain legacy start() failures: neither a caller exception nor GC may
    // discard a still-running guest and its IPC/provider identities.
    private static final Map<Path,ClientPresentationSession> OWNERS=new ConcurrentHashMap<>();
    private final Context context;
    private final Prepared prepared;
    private final Events events;
    private final Handler main;
    private final Path ownershipKey;
    private final ServiceOperationGuard operations=new ServiceOperationGuard();
    private final Path session,endpoints,x11;
    private final int display;
    private final ProotLaunch.PresentationBindings bindings;
    private final List<OwnedProcess> children=new ArrayList<>();
    private final AtomicBoolean closing=new AtomicBoolean();
    private final AtomicReference<String> failure=new AtomicReference<>();
    private volatile OwnedProcess client;
    private boolean clientStartAttempted;
    private AudioBridge audio;
    private InputBridge input;
    private SurfaceBridge surface;
    private Thread monitor;
    private volatile boolean ready,closed,started;
    private volatile IOException closeFailure;

    private ClientPresentationSession(Context context,Prepared prepared,Events events,Path session,Path ownershipKey,int display,Handler main) {
        this.context=context;this.prepared=prepared;this.events=events;this.main=main;this.ownershipKey=ownershipKey;
        this.session=session;endpoints=session.resolve("io");x11=session.resolve("x11");this.display=display;
        bindings=new ProotLaunch.PresentationBindings(endpoints,x11);
    }
    /** Allocate/retain this owner before any Android bridge or guest starts.
     * Keep it across start() failures and retry close() until isClosed(). */
    public static ClientPresentationSession begin(Context context,Prepared prepared,Events events)throws IOException {
        background();if(prepared==null)throw new IOException("Verified presentation inputs required");
        Context app=context.getApplicationContext();
        Path privateRoot=app.getFilesDir().getCanonicalFile().toPath();
        if(!prepared.work.startsWith(privateRoot)||prepared.work.equals(privateRoot))throw new IOException("Private presentation work required");
        synchronized(OWNERS) {
            if(OWNERS.containsKey(prepared.work))throw new IOException("Presentation ownership remains active; close or retry its retained owner first");
            providersUnchanged(prepared);
            Path root=app.getFilesDir().getCanonicalFile().toPath(),sessions=root.resolve("s");
            if(!Files.exists(sessions,LinkOption.NOFOLLOW_LINKS))directory(sessions);
            BridgePaths.directory(app,sessions.toFile());
            SecureRandom random=new SecureRandom();byte[] token=new byte[8],cookie=new byte[16];random.nextBytes(token);random.nextBytes(cookie);
            StringBuilder name=new StringBuilder();for(byte value:token)name.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
            Path session=directory(sessions.resolve(name.toString()));
            Path endpoints=directory(session.resolve("io"));directory(session.resolve("x11"));
            BridgePaths.endpoint(endpoints,"frame.sock",false);BridgePaths.endpoint(endpoints,"input.sock",false);BridgePaths.endpoint(endpoints,"audio.sock",false);
            int display=64+random.nextInt(16320);
            Path authority=endpoints.resolve("Xauthority");
            try(java.nio.channels.SeekableByteChannel out=Files.newByteChannel(authority,
                    java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                java.nio.ByteBuffer bytes=java.nio.ByteBuffer.wrap(X11SessionPlan.authority(display,cookie));while(bytes.hasRemaining())out.write(bytes);
            }finally{java.util.Arrays.fill(cookie,(byte)0);}
            ClientPresentationSession owner=new ClientPresentationSession(app,prepared,events,session,prepared.work,display,new Handler(Looper.getMainLooper()));
            retain(owner);return owner;
        }
    }
    private static void retain(ClientPresentationSession owner)throws IOException {
        if(OWNERS.putIfAbsent(owner.ownershipKey,owner)!=null)throw new IOException("Presentation ownership is already retained");
    }
    private static void providersUnchanged(Prepared prepared)throws IOException {
        if(!prepared.runtimeRoot.equals(prepared.runtime.current())||!prepared.bridgeRoot.equals(prepared.bridges.current()))
            throw new IOException("Presentation providers changed after inspection");
    }
    /** Start using an owner the service already holds. No failed start releases
     * a live child or binding. Startup is single-use, including failed attempts. */
    public void start()throws IOException {
        background();operations.run(()->{
            if(started)throw new IOException("Presentation startup has already run");started=true;
            try{check();providersUnchanged(prepared);startComponents();return null;}
            catch(IOException|RuntimeException error){failure.compareAndSet(null,"presentation-startup-failed");throw error;}
        });
    }
    /** Compatibility convenience. Failed cleanup remains strongly retained and
     * excludes another start until retryPendingCleanup() confirms termination. */
    public static ClientPresentationSession start(Context context,Prepared prepared,Events events)throws IOException {
        ClientPresentationSession owner=begin(context,prepared,events);
        try{owner.start();return owner;}
        catch(IOException|RuntimeException error){try{owner.close();}catch(IOException cleanup){error.addSuppressed(cleanup);}throw error;}
    }
    /** Off main thread. Does not stop a successful active/prelaunch session. */
    public static void retryPendingCleanup(Context context,Prepared prepared)throws IOException {
        background();if(prepared==null)throw new IOException("Verified presentation inputs required");
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        if(!prepared.work.startsWith(root)||prepared.work.equals(root))throw new IOException("Private presentation work required");
        ClientPresentationSession owner=OWNERS.get(prepared.work);if(owner==null)return;
        if(!owner.closing.get()&&owner.failure.get()==null)throw new IOException("Presentation session remains active; use its retained owner");
        owner.close(Duration.ofSeconds(2));
    }
    private void startComponents()throws IOException {
        audio=AudioBridge.start(context,endpoints.toFile(),code->{if(code.endsWith("failed"))fail("presentation-audio-failed");});
        OwnedProcess server=launch("xserver",X11SessionPlan.server(display));
        await(server,()->x11Socket(),null,null);
        OwnedProcess frame=launch("frame",X11SessionPlan.frame());
        await(frame,()->privateSocket("frame.sock"),session.resolve("frame/logs/stderr.log"),"ESTERIA_X11_FRAME_READY protocol=full-v1 capture=XGetImage");
        OwnedProcess keys=launch("input",X11SessionPlan.input());
        await(keys,()->privateSocket("input.sock"),session.resolve("input/logs/stderr.log"),"ESTERIA_X11_INPUT_READY protocol=1");
        input=InputBridge.connect(context,endpoints.toFile(),code->fail("presentation-input-failed"));
        surface=new SurfaceBridge(context,endpoints.toFile(),new SurfaceBridge.Events(){
            public void frameSize(int width,int height){if(!closing.get()&&events!=null)events.frameSize(width,height);}
            public void failed(String reason){fail("presentation-frame-failed");}
        });
        check();ready=true;
        monitor=new Thread(()->{
            try {
                while(!closing.get()) {
                    if(failure.get()!=null){scheduleCleanup();return;}
                    for(OwnedProcess child:children)if(!child.isAlive()) {fail("presentation-guest-exited");return;}
                    Thread.sleep(100);
                }
            }catch(InterruptedException interrupted){if(!closing.get())fail("presentation-monitor-interrupted");}
        },"esteria-presentation-owner");monitor.setDaemon(true);monitor.start();
    }
    private OwnedProcess launch(String name,List<String> command)throws IOException {
        check();Path process=directory(session.resolve(name));
        OwnedProcess child=ProotProcess.startPresentation(context,prepared.runtime.installer(),prepared.runtime.packagePlan(),
                prepared.work,process,command,prepared.runtime.wineEnvironment(X11SessionPlan.environment(display)),
                List.of(new ProotLaunch.Mount(prepared.bridgeRoot,GuestBridgeSetup.guestMount())),bindings);
        children.add(child);return child;
    }
    /** Fixed reconstructed-client launch only. This owner retains the client
     * before returning; no failed caller may discard its presentation bindings.
     * The higher session owner establishes local services/account first. */
    public OwnedProcess startClient(ClientRuntimeSetup provider,ClientLaunchSetup.Prepared view,ShaderSetup.Result shaders,
            TurnipSetup turnip)throws IOException {
        background();return operations.run(()->{
            check();if(!ready||clientStartAttempted)throw new IOException("Client presentation launch is unavailable or already attempted");
            clientStartAttempted=true;providersUnchanged(prepared);
            provider.requireWineArchive(prepared.runtime.archiveSha256());
            if(view==null||shaders==null||provider.current()==null||!prepared.work.equals(view.work)||
                    !provider.generation().equals(view.plan.clientGeneration)||!view.plan.generation.equals(view.view.generation)||
                    !view.plan.importedGeneration.equals(shaders.importGeneration)||!provider.sourceRevision().equals(shaders.clientRevision))
                throw new IOException("Current matched reconstructed client, view and shaders required");
            List<String> command=new ArrayList<>();command.add("/opt/wine/bin/wine");command.add(view.plan.windowsExecutable());
            command.addAll(view.plan.arguments());command.addAll(provider.localLoginArguments());
            Map<String,String> environment=new java.util.TreeMap<>(wineEnvironment());environment.putAll(view.plan.environment());
            List<ProotLaunch.Mount> mounts=new ArrayList<>();
            mounts.add(new ProotLaunch.Mount(view.importedData,"/esteria-data"));
            mounts.add(new ProotLaunch.Mount(shaders.shaders,"/esteria-shaders"));
            if(turnip!=null) {
                turnip.requireWineArchive(prepared.runtime.archiveSha256());Path driver=turnip.current();
                if(driver==null)throw new IOException("Selected Turnip generation is not prepared");
                mounts.add(new ProotLaunch.Mount(driver,TurnipSetup.guestMount()));
                environment.putAll(turnip.selectedEnvironment(prepared.runtime.archiveSha256()));
            }
            Path process=directory(session.resolve("client"));
            client=ProotProcess.startPresentation(context,prepared.runtime.installer(),prepared.runtime.packagePlan(),
                prepared.work,process,command,prepared.runtime.wineEnvironment(environment),mounts,bindings);
            return client;
        });
    }
    /** Source471 maps Alt+F4 through WM_CLOSE to normal engine shutdown. Queue
     * acceptance alone is not a close/save acknowledgment; the caller awaits
     * the exact owned client process. Keep input/display/audio alive meanwhile. */
    public void requestClientClose()throws IOException {
        background();if(closed||input==null)throw new IOException("Client close input is unavailable; live dependencies retained");
        sendClientClose(input);
    }
    private static void sendClientClose(InputSink sink)throws IOException {
        sink.releaseAll();sink.keySequence(new int[]{0xffe9,0xffc1,0xffc1,0xffe9},new boolean[]{true,true,false,false});
    }
    @FunctionalInterface private interface Readiness { boolean check()throws IOException; }
    private void await(OwnedProcess child,Readiness readiness,Path log,String marker)throws IOException {
        long deadline=System.nanoTime()+java.util.concurrent.TimeUnit.SECONDS.toNanos(20);
        while(System.nanoTime()<deadline) {
            check();if(!child.isAlive())throw new IOException("Presentation guest exited before readiness");
            if(readiness.check()&&(marker==null||marker(log,marker)))return;
            try{Thread.sleep(40);}catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new IOException("Presentation startup interrupted",interrupted);}
        }
        throw new IOException("Presentation component readiness timed out");
    }
    private boolean x11Socket()throws IOException {
        try {StructStat stat=Os.lstat(x11.resolve("X"+display).toString());
            if(!OsConstants.S_ISSOCK(stat.st_mode)||stat.st_uid!=android.os.Process.myUid())throw new IOException("X11 socket ownership differs");return true;
        }catch(ErrnoException error){if(error.errno==OsConstants.ENOENT)return false;throw new IOException("Cannot inspect X11 socket",error);}
    }
    private boolean privateSocket(String name)throws IOException {
        if(!Files.exists(endpoints.resolve(name),LinkOption.NOFOLLOW_LINKS))return false;
        BridgePaths.endpoint(endpoints,name,true);return true;
    }
    private static boolean marker(Path path,String line)throws IOException {
        if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS))return false;
        if(Files.isSymbolicLink(path)||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)>65536)
            throw new IOException("Presentation readiness log exceeds bounds");
        byte[] bytes;
        try(java.io.InputStream in=Files.newInputStream(path)){
            java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream();byte[] buffer=new byte[4096];int count;
            while((count=in.read(buffer))!=-1){if(out.size()+count>65536)throw new IOException("Presentation readiness log grew beyond bounds");out.write(buffer,0,count);}bytes=out.toByteArray();
        }
        if(bytes.length>65536)throw new IOException("Presentation readiness log grew beyond bounds");
        return ("\n"+new String(bytes,StandardCharsets.UTF_8)).contains("\n"+line+"\n");
    }
    private void check()throws IOException {if(closing.get()||operations.isStopRequested()||failure.get()!=null)throw new IOException("Presentation session is unavailable");}
    private void fail(String reason) {
        if(closing.get()||!failure.compareAndSet(null,reason))return;
        if(events!=null)main.post(()->events.failed(reason));
        // Starting thread owns rollback until ready. Afterwards this dedicated
        // cleanup thread can join all producers without blocking Android's UI.
        if(ready)scheduleCleanup();
    }
    private void scheduleCleanup(){
        Thread cleanup=new Thread(()->{try{close();}catch(IOException ignored){/* retained in closeFailure */}},"esteria-presentation-cleanup");
        cleanup.setDaemon(true);cleanup.start();
    }
    public InputSink input()throws IOException {check();if(!ready)throw new IOException("Input is not ready");return input;}
    /** Fixed display/audio settings plus this runtime's required Wine adaptation. */
    public Map<String,String> wineEnvironment()throws IOException {
        check();if(!ready)throw new IOException("Presentation session is not ready");
        return prepared.runtime.wineEnvironment(X11SessionPlan.environment(display));
    }
    public SurfaceBridge surface()throws IOException {check();if(!ready)throw new IOException("Display is not ready");return surface;}
    /** GameInputView also clears its own controller state on lifecycle pause. */
    public void pauseInput()throws IOException {
        try{if(input!=null)input.releaseAll();}
        finally{if(surface!=null)surface.detach();if(audio!=null)audio.setSuspended(true);}
    }
    public void resumeInput()throws IOException {check();if(audio!=null)audio.setSuspended(false);}
    public boolean isReady(){return ready&&!closing.get()&&failure.get()==null;}
    /** Component-only metrics; does not imply pixels/audio/gameplay were observed. */
    public long[] diagnostics(){return new long[]{ready?1:0,closed?1:0,children.size(),failure.get()==null?0:1};}
    public IOException cleanupFailure(){return closeFailure;}
    public boolean isClosed(){return closed;}
    @Override public void close()throws IOException {close(Duration.ofSeconds(20));}
    /** Bounded safe-boundary wait; each owned native cleanup has its existing
     * seven-second reap budget. Failure preserves this owner for another close. */
    public void close(Duration timeout)throws IOException {
        background();if(timeout==null||timeout.isNegative()||timeout.compareTo(Duration.ofSeconds(30))>0)
            throw new IllegalArgumentException("Shutdown timeout must be zero to 30 seconds");
        boolean firstClose=!closing.getAndSet(true);ready=false;
        try(ServiceOperationGuard.StopPermit ignored=operations.stopWithin(timeout)) {
            if(closed){if(closeFailure!=null)throw closeFailure;return;}
            if(client!=null&&client.isAlive())throw new IOException("Client still owns presentation bindings; stop and reap it before presentation cleanup");
            IOException error=null;boolean stopped=true;
            if(monitor!=null&&monitor!=Thread.currentThread()) {
                monitor.interrupt();try{monitor.join(2000);if(monitor.isAlive()){stopped=false;error=add(error,new IOException("Presentation monitor remains alive"));}}
                catch(InterruptedException interrupted){Thread.currentThread().interrupt();stopped=false;error=add(error,new IOException("Presentation close interrupted",interrupted));}
            }
            // Input EOF releases held XTest states before any guest is stopped.
            if(input!=null)try{input.close();}catch(IOException failure){stopped=false;error=add(error,failure);}
            if(surface!=null)try{surface.close();}catch(IOException failure){stopped=false;error=add(error,failure);}
            for(int i=children.size()-1;i>=0;i--) {
                OwnedProcess child=children.get(i);
                if(firstClose&&!child.isAlive())error=add(error,new IOException("Presentation guest exited before requested shutdown"));
                try{child.terminateAuxiliary();}catch(IOException failure){error=add(error,failure);}
                if(child.isAlive())stopped=false;
            }
            // Retain audio, authority and every binding while any guest still
            // owns them. A timeout is not final cleanup and must be retryable.
            if(stopped) {
                if(audio!=null)try{audio.close();}catch(IOException failure){stopped=false;error=add(error,failure);}
                if(stopped)try{Files.deleteIfExists(endpoints.resolve("Xauthority"));}catch(IOException failure){stopped=false;error=add(error,failure);}
            }
            closeFailure=add(closeFailure,error);
            if(stopped){closed=true;OWNERS.remove(ownershipKey,this);}
            if(closeFailure!=null)throw closeFailure;
        }
    }
    private static IOException add(IOException first,IOException next){if(next==null)return first;if(first==null)return next;if(first!=next)first.addSuppressed(next);return first;}
    private static Path directory(Path path)throws IOException{return Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Presentation lifecycle work must run off the UI thread");}
}
