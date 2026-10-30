package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Handler;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
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
            Map<String,String> environment=X11SessionPlan.environment(987);
            OwnedProcess.Specification specification=ProotLaunch.create(tracer,loader,rootfs,work,temporary,logs,
                    List.of("/opt/wine/bin/wine","Z:\\work\\launch\\WowClient64.exe"),environment,mounts,
                    new ProotLaunch.PresentationBindings(endpoints,x11));
            List<String> argv=specification.arguments;
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
    public static void main(String[] arguments)throws Exception {
        presentationTimeout();shaderTimeout();shaderPrelaunchStop();clientAudioMount();
        System.out.println("Presentation/shader owners passed4 host delayed-cleanup, interruption, prelaunch guard and client ALSA mount fixtures; no native or Android execution");
    }
}
