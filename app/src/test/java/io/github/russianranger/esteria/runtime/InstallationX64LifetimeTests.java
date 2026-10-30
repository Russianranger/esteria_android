package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Actual ownership/lease ordering with a delayed opaque backend. No SQL/JNI,
 * Android process, original setup ELF or database is executed by this fixture. */
public final class InstallationX64LifetimeTests {
    static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
    static void refuse(Action action)throws Exception {try{action.run();throw new AssertionError("Retained live owner was released");}catch(IOException expected){}}
    interface Action {void run()throws Exception;}
    static final class Backend implements OwnedProcess.Backend {
        final AtomicBoolean release=new AtomicBoolean();
        public long start(OwnedProcess.Specification specification){return 7;}
        public int waitFor(long handle,long timeout)throws IOException {try{Thread.sleep(2);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}return OwnedProcess.RUNNING;}
        public int terminate(long handle){return release.get()?143:OwnedProcess.RUNNING;}
        public long[] diagnostics(long handle){return new long[5];}
    }
    static void await(OwnedProcess child)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(2);
        check(!child.isAlive(),"Known child did not reap after release");
    }
    static void remove(Path root)throws Exception {try(var files=Files.walk(root)){for(Path file:files.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(file);}}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("installation-x64-observer-lifetime-").toRealPath();Backend backend=new Backend();OwnedProcess child=null;
        InstallationX64Lifetime lifetime=InstallationX64Lifetime.acquire(root);
        try {
            List<String> order=new ArrayList<>();
            child=lifetime.observe(()->OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture"),List.of(),Map.of(),root,
                root.resolve("fixture.stdout"),root.resolve("fixture.stderr")),null));OwnedProcess actual=child;
            lifetime.database(()->{check(!actual.isAlive(),"Database closed before actual observer reap");order.add("database");});
            lifetime.installation(()->{check(!actual.isAlive(),"Coordinator closed before observer reap");order.add("installation");});
            refuse(lifetime::finishObservation);check(child.isAlive(),"Fault fixture stopped before timeout");
            check(order.isEmpty()&&InstallationX64Lifetime.retained(root),"Observer timeout dropped parent owners");
            refuse(()->InstallationX64Lifetime.acquire(root));
            refuse(()->{try(ExclusiveFileLease ignored=ExclusiveFileLease.acquire(root.resolve(".installation-x64-fixture.lock"),"test-only-busy")) {}});
            AtomicBoolean started=new AtomicBoolean();refuse(()->lifetime.observe(()->{started.set(true);return actual;}));
            check(!started.get(),"Replacement observation launched while prior child remains owned");
            backend.release.set(true);await(child);lifetime.close();lifetime.close();
            check(order.equals(List.of("database","installation"))&&!InstallationX64Lifetime.retained(root),"Cleanup did not close in observer/database/coordinator order");
            try(ExclusiveFileLease ignored=ExclusiveFileLease.acquire(root.resolve(".installation-x64-fixture.lock"),"test-only-busy")){}
        }finally{backend.release.set(true);if(child!=null&&child.isAlive())await(child);lifetime.close();remove(root);}
        Path failed=Files.createTempDirectory("installation-x64-parent-cleanup-").toRealPath();InstallationX64Lifetime retained=InstallationX64Lifetime.acquire(failed);
        try {
            AtomicBoolean fail=new AtomicBoolean(true),later=new AtomicBoolean();
            retained.database(()->{if(fail.get())throw new IOException("test-only-delayed-database-cleanup");});
            retained.installation(()->later.set(true));refuse(retained::close);
            check(!later.get()&&InstallationX64Lifetime.retained(failed),"Failed database cleanup released later coordinator/lease");
            fail.set(false);retained.close();check(later.get()&&!InstallationX64Lifetime.retained(failed),"Known cleanup retry did not finish");
        }finally{retained.close();remove(failed);}
        System.out.println("Installation x64 lifetime passed2 actual owner/lease groups: timed-out observer retains DB/coordinator/lease, no replacement start, reaped retry closes parents in order, parent cleanup failure retains later owners; no SQL/Android execution");
    }
}
