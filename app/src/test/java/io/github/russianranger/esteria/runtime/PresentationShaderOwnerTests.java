package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Handler;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
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
    private static ShaderSetup.Handle shader(Path root,FileChannel channel,FileLock lock)throws Exception {
        Constructor<ShaderSetup.Handle> constructor=ShaderSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,
            RuntimeSetup.class,ShaderToolsSetup.class,String.class,Path.class,Path.class,FileChannel.class,FileLock.class);
        constructor.setAccessible(true);return constructor.newInstance(null,root,root.resolve("work"),null,null,"enUS",root.resolve("wine"),root.resolve("tools"),channel,lock);
    }
    private static void shaderTimeout()throws Exception {
        Path root=Files.createTempDirectory("esteria-shader-owner-").toRealPath();Backend backend=new Backend();OwnedProcess child=null;ShaderSetup.Handle owner=null;
        try {
            Files.createDirectory(root.resolve("work"));Path output=root.resolve("work/retained-partial-output");Files.writeString(output,"TEST_ONLY_PARTIAL_OUTPUT");
            Path lockPath=root.resolve("work/.android-shader-setup.lock");FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            owner=shader(root,channel,lock);retain(owner);
            // Model the public compatibility entrypoint after its native work
            // has failed: the handle was retained before this process existed.
            child=start(backend,root);set(owner,"process",child);set(owner,"state",ShaderSetup.State.FAILED);
            try{owner.close(Duration.ZERO);throw new AssertionError("Live shader cleanup cannot close its lease");}
            catch(IOException expected){check(child.isAlive(),"Shader backend must still be cleaning up");}
            check(lock.isValid()&&retained(owner,root.resolve("work"))&&owner.state()!=ShaderSetup.State.CLOSED,"Shader process and actual file lease remain retained");
            try(FileChannel competing=FileChannel.open(lockPath,StandardOpenOption.WRITE)) {
                try{FileLock unexpected=competing.tryLock();if(unexpected!=null)unexpected.close();throw new AssertionError("Another shader/import stage must not acquire the active shader lease");}
                catch(OverlappingFileLockException expected){ }
            }
            try{owner.prepare(null,null);throw new AssertionError("Failed helper must never be replayed on its retained owner");}catch(IOException expected){ }
            check(Files.readString(output).equals("TEST_ONLY_PARTIAL_OUTPUT"),"Staged outputs survive failure without fabrication or deletion");
            settle(child,backend);
            try{ShaderSetup.retryPendingCleanup(root.resolve("work"));}catch(IOException expected){ /* Actual forced status is never hidden. */ }
            check(owner.state()==ShaderSetup.State.CLOSED&&!lock.isValid()&&!retained(owner,root.resolve("work")),"Compatibility retry releases ownership only after known-child completion");
            try(FileChannel next=FileChannel.open(lockPath,StandardOpenOption.WRITE);FileLock admitted=next.tryLock()){check(admitted!=null,"New work is admitted after completed cleanup");}
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
            FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            owner=shader(root,channel,lock);retain(owner);ServiceOperationGuard guard=(ServiceOperationGuard)field(owner,"operations");
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
    private static void remove(Path root)throws IOException {
        try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
    }
    public static void main(String[] arguments)throws Exception {
        presentationTimeout();shaderTimeout();shaderPrelaunchStop();
        System.out.println("Presentation/shader owners passed3 host delayed-cleanup, interruption and prelaunch guard fixtures; no native or Android execution");
    }
}
