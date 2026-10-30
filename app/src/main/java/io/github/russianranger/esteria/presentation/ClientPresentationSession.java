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
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.runtime.GuestBridgeSetup;
import io.github.russianranger.esteria.runtime.ProotProcess;
import io.github.russianranger.esteria.runtime.RuntimeSetup;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
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
    private final Context context;
    private final Prepared prepared;
    private final Events events;
    private final Handler main=new Handler(Looper.getMainLooper());
    private final Path session,endpoints,x11;
    private final int display;
    private final ProotLaunch.PresentationBindings bindings;
    private final List<OwnedProcess> children=new ArrayList<>();
    private final AtomicBoolean closing=new AtomicBoolean();
    private final AtomicReference<String> failure=new AtomicReference<>();
    private AudioBridge audio;
    private InputBridge input;
    private SurfaceBridge surface;
    private Thread monitor;
    private volatile boolean ready,closed;
    private IOException closeFailure;

    private ClientPresentationSession(Context context,Prepared prepared,Events events)throws IOException {
        this.context=context.getApplicationContext();this.prepared=prepared;this.events=events;
        Path root=this.context.getFilesDir().getCanonicalFile().toPath(),sessions=root.resolve("s");
        if(!Files.exists(sessions,LinkOption.NOFOLLOW_LINKS))directory(sessions);
        BridgePaths.directory(this.context,sessions.toFile());
        SecureRandom random=new SecureRandom();byte[] token=new byte[8],cookie=new byte[16];random.nextBytes(token);random.nextBytes(cookie);
        StringBuilder name=new StringBuilder();for(byte b:token)name.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        session=directory(sessions.resolve(name.toString()));endpoints=directory(session.resolve("io"));x11=directory(session.resolve("x11"));
        BridgePaths.endpoint(endpoints,"frame.sock",false);BridgePaths.endpoint(endpoints,"input.sock",false);BridgePaths.endpoint(endpoints,"audio.sock",false);
        display=64+random.nextInt(16320);bindings=new ProotLaunch.PresentationBindings(endpoints,x11);
        Path authority=endpoints.resolve("Xauthority");
        try(java.nio.channels.SeekableByteChannel out=Files.newByteChannel(authority,
                java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            java.nio.ByteBuffer bytes=java.nio.ByteBuffer.wrap(X11SessionPlan.authority(display,cookie));while(bytes.hasRemaining())out.write(bytes);
        }finally{java.util.Arrays.fill(cookie,(byte)0);}
    }
    public static ClientPresentationSession start(Context context,Prepared prepared,Events events)throws IOException {
        background();if(prepared==null)throw new IOException("Verified presentation inputs required");
        // Re-resolve active identities before making any socket/process. Replaced
        // generations must be inspected again rather than silently substituted.
        if(!prepared.runtimeRoot.equals(prepared.runtime.current())||!prepared.bridgeRoot.equals(prepared.bridges.current()))
            throw new IOException("Presentation providers changed after inspection");
        ClientPresentationSession owner=new ClientPresentationSession(context,prepared,events);
        try { owner.startComponents();return owner; }
        catch(IOException|RuntimeException error) {
            try { owner.close(); }catch(IOException cleanup){error.addSuppressed(cleanup);}
            throw error;
        }
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
    private void check()throws IOException {if(closing.get()||failure.get()!=null)throw new IOException("Presentation session is unavailable");}
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
    public synchronized IOException cleanupFailure(){return closeFailure;}
    @Override public synchronized void close()throws IOException {
        background();
        if(closed){if(closeFailure!=null)throw closeFailure;return;}
        closing.set(true);ready=false;IOException error=null;
        if(monitor!=null&&monitor!=Thread.currentThread()){monitor.interrupt();try{monitor.join(2000);if(monitor.isAlive())error=add(error,new IOException("Presentation monitor remains alive"));}
            catch(InterruptedException interrupted){Thread.currentThread().interrupt();error=add(error,new IOException("Presentation close interrupted",interrupted));}}
        // Close input first: production helper releases every held XTest state on EOF.
        if(input!=null)try{input.close();}catch(IOException failure){error=add(error,failure);}
        if(surface!=null)try{surface.close();}catch(IOException failure){error=add(error,failure);}
        for(int i=children.size()-1;i>=0;i--)try{
            OwnedProcess child=children.get(i);
            if(!child.isAlive())error=add(error,new IOException("Presentation guest exited before requested shutdown"));
            child.terminateAuxiliary();
        }catch(IOException failure){error=add(error,failure);}
        if(audio!=null)try{audio.close();}catch(IOException failure){error=add(error,failure);}
        // Guest helpers remove only their own sockets. Keep residual endpoints
        // for diagnosis rather than deleting a potentially changed inode.
        try{Files.deleteIfExists(endpoints.resolve("Xauthority"));}catch(IOException failure){error=add(error,failure);}
        closed=true;closeFailure=error;if(error!=null)throw error;
    }
    private static IOException add(IOException first,IOException next){if(first==null)return next;first.addSuppressed(next);return first;}
    private static Path directory(Path path)throws IOException{return Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Presentation lifecycle work must run off the UI thread");}
}
