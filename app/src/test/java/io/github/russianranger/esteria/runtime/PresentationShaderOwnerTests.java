package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Handler;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.WineRuntimeProfile;
import io.github.russianranger.esteria.core.presentation.X11SessionPlan;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Real Java lifecycle/process owners and actual filesystem locks, with a
 * delayed backend and private cleanup fixtures. No native/SQL/GPU/Android run. */
public final class PresentationShaderOwnerTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Object field(Object target,String name)throws Exception {
        Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(target);
    }
    private static void set(Object target,String name,Object value)throws Exception {
        Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);field.set(target,value);
    }
    private static void retain(Object owner)throws Exception {
        Class<?> type=owner instanceof ShaderSetup.Handle?ShaderSetup.class:ClientPresentationSession.class;
        Method method=type.getDeclaredMethod("retain",owner.getClass());method.setAccessible(true);
        try{method.invoke(null,owner);}catch(InvocationTargetException error){throw (Exception)error.getCause();}
    }
    private static boolean retained(Object owner,Path key)throws Exception {
        Class<?> type=owner instanceof ShaderSetup.Handle?ShaderSetup.class:ClientPresentationSession.class;
        Field field=type.getDeclaredField("OWNERS");field.setAccessible(true);return ((Map<?,?>)field.get(null)).get(key)==owner;
    }
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);
        @Override public long start(OwnedProcess.Specification specification){return 1;}
        @Override public int waitFor(long handle,long timeout)throws IOException {
            try{Thread.sleep(2);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
            return OwnedProcess.RUNNING;
        }
        @Override public int terminate(long handle)throws IOException {
            terminating.countDown();
            try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_BACKEND_RELEASE_TIMEOUT");}
            catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
            return 143;
        }
        @Override public long[] diagnostics(long handle){return new long[5];}
    }
    private static OwnedProcess start(Backend backend,Path root)throws IOException {
        return OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture-executable"),List.of(),Map.of(),root,
            root.resolve("fixture-stdout"),root.resolve("fixture-stderr")),null);
    }
    private static void settle(OwnedProcess child,Backend backend)throws Exception {
        backend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(1);
        check(!child.isAlive(),"Retained native owner must settle before releasing resources");
    }
    private static ClientPresentationSession presentation(Path root)throws Exception {
        Path session=Files.createDirectory(root.resolve("session"));Files.createDirectory(session.resolve("io"));Files.createDirectory(session.resolve("x11"));
        Files.writeString(session.resolve("io/Xauthority"),"PRIVATE_TEST_ONLY_AUTHORITY");
        Constructor<ClientPresentationSession> constructor=ClientPresentationSession.class.getDeclaredConstructor(Context.class,
            ClientPresentationSession.Prepared.class,ClientPresentationSession.Events.class,Path.class,Path.class,int.class,Handler.class);
        constructor.setAccessible(true);return constructor.newInstance(null,null,null,session,root.resolve("work"),987,null);
    }
    private static void presentationTimeout()throws Exception {
        Path root=Files.createTempDirectory("esteria-presentation-owner-").toRealPath();Backend backend=new Backend();
        OwnedProcess child=null;ClientPresentationSession owner=null;
        try {
            owner=presentation(root);retain(owner);child=start(backend,root);
            @SuppressWarnings("unchecked") List<OwnedProcess> children=(List<OwnedProcess>)field(owner,"children");children.add(child);
            @SuppressWarnings("unchecked") AtomicReference<String> failure=(AtomicReference<String>)field(owner,"failure");failure.set("TEST_ONLY_STARTUP_FAILURE");
            Path key=root.resolve("work"),authority=root.resolve("session/io/Xauthority");Object bindings=field(owner,"bindings");
            try{owner.close(Duration.ZERO);throw new AssertionError("Delayed cleanup must remain a failure");}
            catch(IOException expected){check(child.isAlive(),"Fixture cleanup must still own its guest");}
            check(backend.terminating.getCount()==0,"Actual auxiliary termination was requested");
            check(!owner.isClosed()&&retained(owner,key),"Startup failure cannot drop retained ownership or mark a live session closed");
            check(Files.exists(authority)&&field(owner,"bindings")==bindings,"Authority and exact IPC bindings survive timeout");
            try{retain(owner);throw new AssertionError("Another startup cannot replace pending ownership");}catch(IOException expected){ }
            ClientPresentationSession pending=owner;AtomicReference<Throwable> interruptFailure=new AtomicReference<>();
            Thread interrupted=new Thread(()->{try{Thread.currentThread().interrupt();try{pending.close(Duration.ZERO);throw new AssertionError("Interrupted close cannot succeed");}
                catch(IOException expected){check(Thread.currentThread().isInterrupted(),"Interruption remains visible");}}catch(Throwable failureInThread){interruptFailure.set(failureInThread);}});
            interrupted.start();interrupted.join(2000);check(!interrupted.isAlive()&&interruptFailure.get()==null,"Interrupted retry remains bounded and preserves its interruption");
            check(!owner.isClosed()&&retained(owner,key)&&Files.exists(authority),"Interrupted retry also preserves live resources");
            settle(child,backend);
            try{owner.close(Duration.ofSeconds(1));}catch(IOException expected){check(owner.cleanupFailure()!=null,"Original timeout remains diagnostic");}
            check(owner.isClosed()&&!retained(owner,key)&&!Files.exists(authority),"Only a confirmed dead child permits final binding cleanup");
        } finally {
            backend.release.countDown();if(child!=null&&child.isAlive())try{child.terminateAuxiliary();}catch(IOException ignored){ }
            if(owner!=null&&!owner.isClosed())try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void prefixUpdateCleanup()throws Exception {
        Path root=Files.createTempDirectory("esteria-prefix-update-owner-").toRealPath();
        Backend backend=new Backend();
        ClientLaunchSetup.Lease work=ClientLaunchSetup.claim(root);
        ClientPresentationSession display=presentation(root);
        retain(display);
        OwnedProcess updater=start(backend,root);
        set(display,"prefixUpdater",updater);
        Class<?> ownerType=Class.forName(StockWinePrefixRepair.class.getName()+"$Owner");
        Constructor<?> factory=ownerType.getDeclaredConstructor(ClientLaunchSetup.Lease.class);
        factory.setAccessible(true);
        Object owner=factory.newInstance(work);
        set(owner,"presentation",display);
        set(owner,"operating",false);
        Field ownersField=StockWinePrefixRepair.class.getDeclaredField("OWNERS");
        ownersField.setAccessible(true);
        @SuppressWarnings("unchecked") Map<Path,Object> owners=(Map<Path,Object>)ownersField.get(null);
        check(owners.putIfAbsent(root,owner)==null,"Fresh retained prefix owner required");
        Path authority=root.resolve("session/io/Xauthority");
        try {
            long start=System.nanoTime();
            try {StockWinePrefixRepair.retryPendingCleanup(root);throw new AssertionError("Live updater released");}
            catch(IOException expected) {
                check(updater.isAlive() && backend.terminating.getCount()==0 && Files.isRegularFile(authority)
                    && System.nanoTime()-start<TimeUnit.SECONDS.toNanos(12),"Bounded failure retains updater and Xauthority");
            }
            try(ClientLaunchSetup.Lease ignored=ClientLaunchSetup.claim(root)){throw new AssertionError("Live prefix lease released");}
            catch(IOException expected){check(owners.get(root)==owner,"Named owner retained across refused concurrent claim");}
            settle(updater,backend);

            // Fail cleanup of the authority once after the native process is reaped.
            Files.delete(authority);Files.createDirectory(authority);
            Path obstruction=Files.createFile(authority.resolve("fixture"));
            try {StockWinePrefixRepair.retryPendingCleanup(root);throw new AssertionError("Failed authority cleanup succeeded");}
            catch(IOException expected){check(!display.isClosed()&&owners.get(root)==owner,"Incomplete bindings remain owned");}
            Files.delete(obstruction);
            StockWinePrefixRepair.retryPendingCleanup(root);
            check(display.isClosed() && !Files.exists(authority) && !owners.containsKey(root),"Single recovered retry releases all ownership");
            try(ClientLaunchSetup.Lease next=ClientLaunchSetup.claim(root)){next.require(root);}
        } finally {
            backend.release.countDown();
            if(updater.isAlive())updater.terminateAuxiliary();
            owners.remove(root,owner);
            work.close();
            remove(root);
        }
    }
    private static void unrelatedPrefixDelegatesToProviders()throws Exception {
        Path root=Files.createTempDirectory("esteria-prefix-provider-fallback-").toRealPath();
        try {
            Path runtime=Files.createDirectory(root.resolve("wine-runtime"));
            try(ClientLaunchSetup.Lease owner=ClientLaunchSetup.claim(root)) {
                Path prefix=Files.createDirectories(owner.work.resolve("home/.wine"));
                Path settings=Files.writeString(prefix.resolve("user.reg"),"unrelated retained user settings");
                var stamp=Files.getLastModifiedTime(settings);
                String archive="c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46";
                for(boolean hasPending:new boolean[]{false,true}) {
                    Path pending=owner.work.resolve(".stock-wine-prefix-repair-v1.pending");
                    if(hasPending)Files.writeString(pending,"unrelated retained repair intent");
                    var phases=new java.util.ArrayList<String>();
                    var selected=StockWinePrefixRepair.selectForUpdate(owner.work,runtime,archive,
                            (phase,path,completed,total)->phases.add(phase));
                    check(selected==null && phases.equals(List.of("client-prefix-preserved")),
                            "Unknown prefix must select only the existing provider fallback, never the Wine updater");
                    check(Files.readString(settings).equals("unrelated retained user settings")
                            && Files.getLastModifiedTime(settings).equals(stamp),"Retain unrelated user prefix state");
                    check(hasPending ? Files.readString(pending).equals("unrelated retained repair intent") : !Files.exists(pending),
                            "Never create, replace or retire an unrelated prefix intent");
                }
            }
            try(ClientLaunchSetup.Lease providers=ClientLaunchSetup.claim(root)){providers.require(root);}
        } finally {remove(root);}
    }
    private static ShaderSetup.Handle shader(Path root,ExclusiveFileLease lock)throws Exception {
        Constructor<ShaderSetup.Handle> constructor=ShaderSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,
            RuntimeSetup.class,ShaderToolsSetup.class,String.class,Path.class,Path.class,ExclusiveFileLease.class);
        constructor.setAccessible(true);return constructor.newInstance(null,root,root.resolve("work"),null,null,"enUS",root.resolve("wine"),root.resolve("tools"),lock);
    }
    private static void shaderTimeout()throws Exception {
        Path root=Files.createTempDirectory("esteria-shader-owner-").toRealPath();Backend backend=new Backend();OwnedProcess child=null;ShaderSetup.Handle owner=null;
        try {
            Files.createDirectory(root.resolve("work"));Path output=root.resolve("work/retained-partial-output");Files.writeString(output,"TEST_ONLY_PARTIAL_OUTPUT");
            Path lockPath=root.resolve("work/.android-shader-setup.lock");ExclusiveFileLease lock=ExclusiveFileLease.acquire(lockPath,"TEST_ONLY_BUSY");
            owner=shader(root,lock);retain(owner);
            // Model the public compatibility entrypoint after its native work
            // has failed: the handle was retained before this process existed.
            child=start(backend,root);set(owner,"process",child);set(owner,"state",ShaderSetup.State.FAILED);
            try{owner.close(Duration.ZERO);throw new AssertionError("Live shader cleanup cannot close its lease");}
            catch(IOException expected){check(child.isAlive(),"Shader backend must still be cleaning up");}
            check(lock.isValid()&&retained(owner,root.resolve("work"))&&owner.state()!=ShaderSetup.State.CLOSED,"Shader process and actual file lease remain retained");
            try{ExclusiveFileLease unexpected=ExclusiveFileLease.acquire(lockPath,"TEST_ONLY_BUSY");unexpected.close();throw new AssertionError("Another shader/import stage must not acquire the active shader lease");}catch(IOException expected){check("TEST_ONLY_BUSY".equals(expected.getMessage()),"Retained lease refuses before a competing descriptor opens");}
            try{owner.prepare(null,null);throw new AssertionError("Failed helper must never be replayed on its retained owner");}catch(IOException expected){ }
            check(Files.readString(output).equals("TEST_ONLY_PARTIAL_OUTPUT"),"Staged outputs survive failure without fabrication or deletion");
            settle(child,backend);
            try{ShaderSetup.retryPendingCleanup(root.resolve("work"));}catch(IOException expected){ /* Actual forced status is never hidden. */ }
            check(owner.state()==ShaderSetup.State.CLOSED&&!lock.isValid()&&!retained(owner,root.resolve("work")),"Compatibility retry releases ownership only after known-child completion");
            try(ExclusiveFileLease admitted=ExclusiveFileLease.acquire(lockPath,"TEST_ONLY_BUSY")){check(admitted!=null,"New work is admitted after completed cleanup");}
        } finally {
            backend.release.countDown();if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }
            if(owner!=null&&owner.state()!=ShaderSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void shaderPrelaunchStop()throws Exception {
        Path root=Files.createTempDirectory("esteria-shader-prelaunch-owner-").toRealPath();ShaderSetup.Handle owner=null;
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);Thread operation=null;
        AtomicReference<Throwable> error=new AtomicReference<>();
        try {
            Files.createDirectory(root.resolve("work"));Path lockPath=root.resolve("work/.android-shader-setup.lock");
            ExclusiveFileLease lock=ExclusiveFileLease.acquire(lockPath,"TEST_ONLY_BUSY");
            owner=shader(root,lock);retain(owner);ServiceOperationGuard guard=(ServiceOperationGuard)field(owner,"operations");
            operation=new Thread(()->{try{guard.run(()->{entered.countDown();try{release.await();}catch(InterruptedException interrupted){throw new IOException(interrupted);}return null;});}
                catch(Throwable failure){error.set(failure);}});operation.start();check(entered.await(2,TimeUnit.SECONDS),"Actual operation guard entered");
            try{owner.close(Duration.ZERO);throw new AssertionError("An in-flight allocation/launch must retain its owner");}catch(IOException expected){ }
            check(lock.isValid()&&retained(owner,root.resolve("work"))&&guard.isStopRequested(),"Stop requests cancellation without releasing a prelaunch lease");
            release.countDown();operation.join(2000);check(error.get()==null&&!operation.isAlive(),"Prelaunch operation reaches its safe boundary");
            owner.close(Duration.ofSeconds(1));check(!lock.isValid()&&owner.state()==ShaderSetup.State.CLOSED,"No-child close releases only at the safe boundary");
        } finally {
            release.countDown();if(operation!=null)operation.join(2000);
            if(owner!=null&&owner.state()!=ShaderSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            remove(root);
        }
    }
    /** Check the actual PRoot argv produced from the same client mounts used
     * at launch. Helpers in separate PRoot processes cannot supply this bind. */
    private static void clientAudioMount()throws Exception {
        Path root=Files.createTempDirectory("esteria-client-audio-mount-").toRealPath();
        try {
            Path rootfs=Files.createDirectory(root.resolve("wine")),work=Files.createDirectory(root.resolve("work"));
            Path temporary=Files.createDirectory(root.resolve("tmp")),logs=Files.createDirectory(root.resolve("logs"));
            Path data=Files.createDirectory(root.resolve("data")),shaders=Files.createDirectory(root.resolve("shaders"));
            Path bridge=Files.createDirectory(root.resolve("bridges"));
            Files.createDirectories(bridge.resolve("etc"));Files.createDirectories(bridge.resolve("lib/alsa-lib"));
            Files.writeString(bridge.resolve("etc/alsa-esteria.conf"),"TEST_ONLY_ALSA_CONFIGURATION");
            Files.writeString(bridge.resolve("lib/alsa-lib/libasound_module_pcm_esteria.so"),"TEST_ONLY_PLUGIN_PATH");
            Path tracer=Files.writeString(root.resolve("tracer"),"TEST_ONLY_NOT_EXECUTED");
            Path loader=Files.writeString(root.resolve("loader"),"TEST_ONLY_NOT_EXECUTED");
            check(tracer.toFile().setExecutable(true)&&loader.toFile().setExecutable(true),"Host executable fixture permission");
            Path endpoints=Files.createDirectory(root.resolve("io")),x11=Files.createDirectory(root.resolve("x11"));
            Method method=ClientPresentationSession.class.getDeclaredMethod("clientMounts",Path.class,Path.class,Path.class);
            method.setAccessible(true);
            @SuppressWarnings("unchecked") List<ProotLaunch.Mount> mounts=(List<ProotLaunch.Mount>)method.invoke(null,data,shaders,bridge);
            Map<String,String> presentation=X11SessionPlan.environment(987);
            WineRuntimeProfile wine=new WineRuntimeProfile(Map.of(WineRuntimeProfile.PRIVATE_PE_COPY,"1"));
            Method compose=ClientPresentationSession.class.getDeclaredMethod("clientEnvironment",Map.class,Map.class,String.class,boolean.class);
            compose.setAccessible(true);
            ProotLaunch.PresentationBindings bindings=new ProotLaunch.PresentationBindings(endpoints,x11);
            List<String> command=List.of("/opt/wine/bin/wine","Z:\\work\\launch\\WowClient64.exe");
            String shaderPath="Z:\\esteria-shaders";
            for (String profile:List.of("stock-3.3.5a","esteria-custom")) {
                for (boolean localLogin:List.of(true,false)) {
                    @SuppressWarnings("unchecked") Map<String,String> client=(Map<String,String>)compose.invoke(null,
                            wine.merge(presentation),Map.of("GX_VULKAN_SHADERS",shaderPath),profile,localLogin);
                    List<String> guest=ProotLaunch.create(tracer,loader,rootfs,work,temporary,logs,command,
                            wine.merge(client),mounts,bindings).arguments;
                    String overrides="WINEDLLOVERRIDES=winepulse.drv="+(profile.equals("stock-3.3.5a")?";mscoree=":"");
                    check(guest.contains(overrides)&&guest.stream().filter(s->s.startsWith("WINEDLLOVERRIDES=")).count()==1,
                            "Only stock PE launches suppress the interactive Mono installer");
                    check(guest.contains("WINEDEBUG=+file")==!localLogin,"Only the title investigation traces file access");
                    check(guest.containsAll(List.of("HOME=/work/home","WINE_ANDROID_PRIVATE_PE_COPY=1",
                            "GX_VULKAN_SHADERS="+shaderPath,"DISPLAY=:987","WINEESYNC=0","WINEFSYNC=0")),
                            "Client retains its existing prefix, display, shader and private PE settings");
                }
            }
            check(presentation.get("WINEDLLOVERRIDES").equals("winepulse.drv="),"Presentation helper override remains independent");
            List<String> argv=ProotLaunch.create(tracer,loader,rootfs,work,temporary,logs,command,presentation,mounts,bindings).arguments;
            check(argv.contains("ALSA_CONFIG_PATH="+GuestBridgeSetup.alsaConfigPath()),"Wine retains the selected ALSA configuration");
            for(String guest:List.of(GuestBridgeSetup.alsaConfigPath(),"/esteria-bridges/lib/alsa-lib/libasound_module_pcm_esteria.so")) {
                Path actual=null;
                for(int i=0;i+1<argv.size();i++)if(argv.get(i).equals("-b")) {
                    String bind=argv.get(i+1);int colon=bind.indexOf(':');if(colon<0)continue;
                    String destination=bind.substring(colon+1);if(destination.endsWith("!"))destination=destination.substring(0,destination.length()-1);
                    if(guest.startsWith(destination+"/"))actual=Path.of(bind.substring(0,colon)).resolve(guest.substring(destination.length()+1));
                }
                check(actual!=null&&actual.startsWith(bridge)&&Files.isRegularFile(actual),"Wine ALSA path must resolve through its own verified provider bind: "+guest);
            }
            check(argv.contains(bridge+":"+GuestBridgeSetup.guestMount()+"!"),"Bridge bind cannot dereference a guest destination link");
            check(!argv.contains(root+":/esteria-bridges!"),"Only the bridge provider is exposed, never the application root");
        } finally { remove(root); }
    }
    private static void remove(Path root)throws IOException {
        try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
    }
    private static void prefixSocketBudget()throws Exception {
        Field leaf=ClientPresentationSession.class.getDeclaredField("PREFIX_UPDATE_LEAF");
        leaf.setAccessible(true);
        String chosen=(String)leaf.get(null);
        String session="/io.github.russianranger.esteria.stock/files/s/0123456789abcdef/";
        // Pinned PRoot's exact Unix socket fallback uses six mktemp characters
        // and the decimal tracer PID (Linux PID_MAX_LIMIT is 4,194,304).
        String socket="/tmp/proot-4194304-XXXXXX";
        for(String user:List.of("/data/data","/data/user/0","/data/user/10","/data/user/21474")) {
            int bytes=(user+session+chosen+socket).getBytes(java.nio.charset.StandardCharsets.UTF_8).length;
            check(bytes<=108,"The complete chosen PRoot socket fits sockaddr_un on standard Android app storage");
        }
        check(("/data/data"+session+"prefix-update"+socket).length()>108,"Match the original native bind EINVAL");
        check(("/data/user/0"+session+"client"+socket).length()<=108,"Original stock client runtime leaf still fits");
    }
    private static void prefixWorkerDiagnostic()throws Exception {
        Path root=Files.createTempDirectory("wine-prefix-worker-log-").toRealPath();
        Backend backend=new Backend();
        OwnedProcess child=start(backend,root);
        try {
            Path stderr=root.resolve("prefix.stderr");
            Files.writeString(stderr,"permission denied".repeat(1024)+"\n"+ "x".repeat(8192)
                    +"\nwineserver: bind: Invalid argument\nwine: could not load kernel32.dll, status c0000135; /private/TEST_SECRET\n");
            Method report=ClientPresentationSession.class.getDeclaredMethod("prefixUpdateFailure",OwnedProcess.class,
                    Path.class,boolean.class,long.class,boolean.class);
            report.setAccessible(true);
            IOException timeout=(IOException)report.invoke(null,child,stderr,false,System.nanoTime()-2_000_000_000L,true);
            check(timeout.getMessage().matches("Wine prefix update timed out after [0-9]+ ms [(]wineboot.exe -u, still running[)].*")
                    && timeout.getMessage().contains("wineserver: bind: invalid argument")
                    && timeout.getMessage().contains("c0000135")&&!timeout.getMessage().contains("permission denied")
                    && !timeout.getMessage().contains("TEST_SECRET"),"Only typed redacted reasons from the final bounded log are returned");
            backend.release.countDown();
            child.terminateAuxiliary();
            Files.delete(stderr);
            Files.createSymbolicLink(stderr,Files.writeString(root.resolve("unrelated-private.log"),"could not load kernel32.dll"));
            IOException failed=(IOException)report.invoke(null,child,stderr,true,System.nanoTime(),false);
            check(failed.getMessage().contains("Wine service shutdown failed") && failed.getMessage().contains("wineserver -w, exit 143")
                    && !failed.getMessage().contains("kernel32"),"Final owned status survives an absent or unsafe native log");
        } finally {
            backend.release.countDown();
            if(child.isAlive())child.terminateAuxiliary();
            remove(root);
        }
    }
    private static void shaderWorkerDiagnostic()throws IOException {
        Path root=Files.createTempDirectory("shader-worker-diagnostic-").toRealPath();
        try {
            Path stderr=root.resolve("stderr.log");
            String rejection="strict setup refuses 10 undecodable or mismatched-stage record(s): Terrain1w:0";
            Files.writeString(stderr,"[owned child log tail]\nshader input validation failed: "+rejection+
                    "\ntranslation failed (2)\n");
            String message=ShaderSetup.workerFailure(1,stderr).getMessage();
            check(message.contains(rejection)&&message.contains("(exit 1)"),"Show the shader rejection and helper exit");
            Files.writeString(stderr,"shader input validation failed: token=TEST_PRIVATE_TOKEN\n");
            check(!ShaderSetup.workerFailure(1,stderr).getMessage().contains("TEST_PRIVATE_TOKEN"),"Redact the diagnostic");
            Files.delete(stderr);
            check(ShaderSetup.workerFailure(1,stderr).getMessage().contains("(exit 1)"),"Missing stderr preserves the worker failure");
        } finally { remove(root); }
    }
    public static void main(String[] arguments)throws Exception {
        presentationTimeout();prefixUpdateCleanup();unrelatedPrefixDelegatesToProviders();shaderTimeout();shaderPrelaunchStop();clientAudioMount();shaderWorkerDiagnostic();prefixWorkerDiagnostic();prefixSocketBudget();
        System.out.println("Nine presentation, prefix and shader owner and diagnostic host checks passed");
    }
}
