package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.diagnostics.SupportLogSelection;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
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
        System.out.println("Turnip owner passed2 actual filesystem/ownership groups: fixed support roles, single-use close, active-owner recovery refusal, exact failed/stop-requested recovery, retained opaque child/lock after timeout and confirmed-reap retry; no GPU/Android execution");
    }
}
