package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.diagnostics.SupportLogSelection;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.TurnipAdmissionReadFixture;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.TurnipProbeContract;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Actual owner and filesystem locks with a delayed opaque backend. No native,
 * Android, KGSL or Vulkan execution is claimed by this fixture. */
public final class TurnipReadinessOwnerTests {
    static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    static Field field(Class<?> type,String name)throws Exception {Field field=type.getDeclaredField(name);field.setAccessible(true);return field;}
    @SuppressWarnings("unchecked") static Map<Path,TurnipReadinessProbe.Handle> owners()throws Exception {
        return (Map<Path,TurnipReadinessProbe.Handle>)field(TurnipReadinessProbe.class,"OWNERS").get(null);
    }
    static TurnipReadinessProbe.Handle owner(Path root)throws Exception {
        Path wine=Files.createDirectories(root.resolve("runtimes/wine")),driver=Files.createDirectories(root.resolve("runtimes/driver"));
        Path work=Files.createDirectories(root.resolve("state/turnip-probe-work/"+"a".repeat(32)));
        Path session=Files.createDirectories(root.resolve("state/turnip-probe-operations/"+"a".repeat(32)));
        Path lockPath=root.resolve("owner.lock");ExclusiveFileLease lease=ExclusiveFileLease.acquire(lockPath,"TEST_ONLY_OWNER_BUSY");
        Constructor<TurnipReadinessProbe.Handle> constructor=TurnipReadinessProbe.Handle.class.getDeclaredConstructor(Context.class,Path.class,
            RuntimeSetup.class,TurnipSetup.class,Path.class,Path.class,Path.class,Path.class,ExclusiveFileLease.class);
        constructor.setAccessible(true);
        TurnipReadinessProbe.Handle result=constructor.newInstance(null,root,null,null,wine,driver,work,session,lease);
        owners().put(root,result);return result;
    }
    static final class Backend implements OwnedProcess.Backend {
        final AtomicBoolean release=new AtomicBoolean();final CountDownLatch terminating=new CountDownLatch(1);
        @Override public long start(OwnedProcess.Specification specification){return 7;}
        @Override public int waitFor(long handle,long timeout)throws IOException {
            try{Thread.sleep(2);}catch(InterruptedException e){Thread.currentThread().interrupt();throw new IOException(e);}return OwnedProcess.RUNNING;
        }
        @Override public int terminate(long handle){terminating.countDown();return release.get()?143:OwnedProcess.RUNNING;}
        @Override public long[] diagnostics(long handle){return new long[5];}
    }
    static void await(OwnedProcess child)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(2);
        check(!child.isAlive(),"Delayed opaque child was not reaped");
    }
    static void remove(Path root)throws Exception {try(var all=Files.walk(root)){for(Path p:all.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(p);}}
    /** Real host children, not the Android JNI/group backend. Timing semantics
     * use an injected clock; actual Android JNI execution has its own test. */
    static final class HostChildBackend implements OwnedProcess.Backend {
        private Process process;
        @Override public long start(OwnedProcess.Specification spec)throws IOException {
            java.util.ArrayList<String> command=new java.util.ArrayList<>();command.add(spec.executable.toString());command.addAll(spec.arguments);
            ProcessBuilder builder=new ProcessBuilder(command).directory(spec.cwd.toFile());builder.environment().clear();builder.environment().putAll(spec.environment);
            process=builder.redirectOutput(spec.stdout.toFile()).redirectError(spec.stderr.toFile()).start();return 1;
        }
        @Override public int waitFor(long handle,long timeout)throws IOException {
            try{return process.waitFor(timeout,TimeUnit.MILLISECONDS)?process.exitValue():OwnedProcess.RUNNING;}
            catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
        }
        @Override public int terminate(long handle)throws IOException {
            process.destroyForcibly();return waitFor(handle,3000);
        }
        @Override public long[] diagnostics(long handle){return new long[5];}
    }
    static OwnedProcess.Specification command(Path root,String script)throws IOException {
        Path work=Files.createDirectory(root.resolve("child"));
        return new OwnedProcess.Specification(java.nio.file.Paths.get("/bin/sh"),List.of("-c",script),Map.of("PATH","/usr/bin:/bin"),
            work,work.resolve("stdout"),work.resolve("stderr"));
    }
    static void retained(Path root,TurnipReadinessProbe.Handle owner)throws Exception {
        check(owner.state()==TurnipReadinessProbe.State.FAILED&&TurnipReadinessProbe.pendingCleanup(root)==owner,"Failed timed owner was not retained");
        try(ExclusiveFileLease stolen=ExclusiveFileLease.acquire(root.resolve("owner.lock"),"TEST_ONLY_OWNER_BUSY")){throw new AssertionError("Timed failure released its lock");}
        catch(IOException expected){check(expected.getMessage().equals("TEST_ONLY_OWNER_BUSY"),"Unexpected lock refusal");}
    }
    static void timing()throws Exception {
        Path root=Files.createTempDirectory("turnip-admission-window-").toRealPath();
        java.util.ArrayList<TurnipReadinessProbe.Handle> handles=new java.util.ArrayList<>();java.util.ArrayList<OwnedProcess> children=new java.util.ArrayList<>();
        long budget=TimeUnit.MILLISECONDS.toNanos(TurnipProbeContract.TIMEOUT_MILLIS);
        try {
            Path slow=Files.createDirectory(root.resolve("slow")),input=slow.resolve("provider");byte[] bytes=new byte[512<<10];java.util.Arrays.fill(bytes,(byte)37);Files.write(input,bytes);
            String expected=TurnipAdmissionReadFixture.hash(input,bytes.length,RuntimeWork.NEVER_CANCELLED);
            TurnipReadinessProbe.Handle owner=owner(slow);handles.add(owner);AtomicLong clock=new AtomicLong(),observed=new AtomicLong();
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{observed.addAndGet(count);clock.addAndGet(TimeUnit.SECONDS.toNanos(2));})) {
                long elapsed=owner.runPrepared(()->{check(expected.equals(TurnipAdmissionReadFixture.hash(input,bytes.length,RuntimeWork.NEVER_CANCELLED)),"Provider hash changed under read policy");return command(slow,"exit 0");},
                    spec->{OwnedProcess child=OwnedProcess.start(new HostChildBackend(),spec,null);children.add(child);return child;},clock::get,RuntimeWork.NEVER_CANCELLED);
                check(clock.get()>budget&&observed.get()==bytes.length&&elapsed==0,"Paced admission spent native budget or replaced hash");
            }
            check(children.get(children.size()-1).exitCode()==0,"Fast admitted host child did not succeed");owner.close(Duration.ZERO);

            for(String mode:List.of("hung","slow-launch","late-result")) {
                Path at=Files.createDirectory(root.resolve(mode));owner=owner(at);handles.add(owner);AtomicLong now=new AtomicLong();AtomicInteger ticks=new AtomicInteger();AtomicReference<OwnedProcess> child=new AtomicReference<>();
                try {
                    owner.runPrepared(()->command(at,mode.equals("late-result")?"exit 0":"exec sleep 30"),spec->{
                        OwnedProcess launched=OwnedProcess.start(new HostChildBackend(),spec,null);children.add(launched);child.set(launched);
                        if(mode.equals("late-result")){try{await(launched);}catch(Exception failure){throw new IOException(failure);}now.set(budget+1);}
                        if(mode.equals("slow-launch"))now.set(budget);
                        return launched;
                    },mode.equals("hung")?()->ticks.getAndIncrement()==0?0:budget:now::get,RuntimeWork.NEVER_CANCELLED);
                    throw new AssertionError("Over-budget child/result accepted: "+mode);
                }catch(IOException timeout){check(timeout.getMessage().contains("exceeded"),"Expected bounded native window: "+mode);}
                check(child.get()!=null&&!child.get().isAlive(),"Timed child not reaped: "+mode);retained(at,owner);owner.close(Duration.ZERO);
            }

            for(boolean duringRead:List.of(true,false)) {
                Path at=Files.createDirectory(root.resolve(duringRead?"cancel-read":"cancel-after-admission"));owner=owner(at);handles.add(owner);AtomicBoolean cancelled=new AtomicBoolean();AtomicInteger launches=new AtomicInteger();
                try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{cancelled.set(true);throw new RuntimeWork.CancelledException();})) {
                    try {
                        owner.runPrepared(()->{if(duringRead)TurnipAdmissionReadFixture.hash(input,bytes.length,RuntimeWork.NEVER_CANCELLED);cancelled.set(true);return command(at,"exit 0");},
                            spec->{launches.incrementAndGet();return OwnedProcess.start(new HostChildBackend(),spec,null);},System::nanoTime,cancelled::get);
                        throw new AssertionError("Cancelled admission launched");
                    }catch(RuntimeWork.CancelledException cancelledAsExpected){ }
                }
                check(launches.get()==0,"Cancelled admission forked a child");retained(at,owner);owner.close(Duration.ZERO);
            }

            Path altered=Files.createDirectory(root.resolve("changed-input"));owner=owner(altered);handles.add(owner);Files.write(input,new byte[bytes.length]);AtomicInteger launches=new AtomicInteger();
            try {
                owner.runPrepared(()->{if(!expected.equals(TurnipAdmissionReadFixture.hash(input,bytes.length,RuntimeWork.NEVER_CANCELLED)))throw new IOException("TEST_ONLY_PIN_CHANGED");return command(altered,"exit 0");},
                    spec->{launches.incrementAndGet();return OwnedProcess.start(new HostChildBackend(),spec,null);},System::nanoTime,RuntimeWork.NEVER_CANCELLED);
                throw new AssertionError("Provider mutation accepted");
            }catch(IOException expectedFailure){check(expectedFailure.getMessage().equals("TEST_ONLY_PIN_CHANGED"),"Mutation validation changed");}
            check(launches.get()==0,"Changed provider launched a child");retained(altered,owner);owner.close(Duration.ZERO);
        }finally {
            for(OwnedProcess child:children)if(child.isAlive())child.terminateAuxiliary();
            for(TurnipReadinessProbe.Handle owner:handles)if(owner.state()!=TurnipReadinessProbe.State.CLOSED)owner.close(Duration.ZERO);
            remove(root);
        }
    }
    public static void main(String[] args)throws Exception {
        Path first=Files.createTempDirectory("turnip-owner-allocation-").toRealPath();
        try {
            var owner=owner(first);String saved=SupportLogSelection.encode(first,owner.diagnosticLogs());
            try{TurnipReadinessProbe.pendingCleanup(first);throw new AssertionError("Active allocation was stolen by recovery");}catch(IOException expected){ }
            check(SupportLogSelection.decode(first,saved).equals(owner.diagnosticLogs()),"Fixed GPU log roles did not persist/revalidate");
            try{owner.diagnosticLogs().clear();throw new AssertionError("Owned log map is mutable");}catch(UnsupportedOperationException expected){ }
            owner.close(Duration.ZERO);owner.close(Duration.ZERO);
            check(owner.state()==TurnipReadinessProbe.State.CLOSED&&!owners().containsKey(first),"Unused allocation did not close/release registry");
            check(TurnipReadinessProbe.pendingCleanup(first)==null,"Closed owner remained recoverable");
            try{owner.run(null,null);throw new AssertionError("Closed owner replayed");}catch(IOException expected){ }
        }finally{remove(first);}
        Path root=Files.createTempDirectory("turnip-owner-delayed-cleanup-").toRealPath();Backend backend=new Backend();OwnedProcess child=null;TurnipReadinessProbe.Handle owner=null;
        try {
            owner=owner(root);child=OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture"),List.of(),Map.of(),root,
                root.resolve("fixture.stdout"),root.resolve("fixture.stderr")),null);
            field(TurnipReadinessProbe.Handle.class,"process").set(owner,child);field(TurnipReadinessProbe.Handle.class,"state").set(owner,TurnipReadinessProbe.State.FAILED);
            try{owner.close(Duration.ZERO);throw new AssertionError("Live auxiliary cleanup was reported closed");}catch(IOException expected){ }
            check(backend.terminating.getCount()==0&&child.isAlive(),"Opaque auxiliary termination was not attempted");
            check(owner.state()!=TurnipReadinessProbe.State.CLOSED&&owners().get(root)==owner&&owner.cleanupFailure()!=null,"Failed cleanup dropped retained owner/failure");
            check(TurnipReadinessProbe.pendingCleanup(root)==owner,"Recovery did not return the exact known failed owner");
            field(TurnipReadinessProbe.Handle.class,"state").set(owner,TurnipReadinessProbe.State.RUNNING);
            check(TurnipReadinessProbe.pendingCleanup(root)==owner,"Stop-requested owner could not be retained by recovery");
            field(TurnipReadinessProbe.Handle.class,"state").set(owner,TurnipReadinessProbe.State.FAILED);
            try{ExclusiveFileLease stolen=ExclusiveFileLease.acquire(root.resolve("owner.lock"),"TEST_ONLY_OWNER_BUSY");stolen.close();throw new AssertionError("Live probe lease was released");}
            catch(IOException expected){check(expected.getMessage().equals("TEST_ONLY_OWNER_BUSY"),"Unexpected lease refusal");}
            backend.release.set(true);await(child);owner.close(Duration.ZERO);
            check(owner.state()==TurnipReadinessProbe.State.CLOSED&&!owners().containsKey(root),"Confirmed reap did not release lock/registry");
            try(ExclusiveFileLease available=ExclusiveFileLease.acquire(root.resolve("owner.lock"),"TEST_ONLY_OWNER_BUSY")) {
                check(available.isValid(),"Reaped probe lock is unavailable");
            }
        }finally {
            backend.release.set(true);if(child!=null&&child.isAlive())await(child);
            if(owner!=null&&owner.state()!=TurnipReadinessProbe.State.CLOSED)owner.close(Duration.ZERO);remove(root);
        }
        timing();
        System.out.println("Turnip owner passed3 filesystem/ownership/timing groups: governed admission hash, fresh bounded launch/result window, real host child cleanup, cancellation without launch, changed provider refusal and retained locks; no GPU/Android execution");
    }
}
