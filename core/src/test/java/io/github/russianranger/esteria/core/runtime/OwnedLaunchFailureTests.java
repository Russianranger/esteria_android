package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Exercise the real owner thread and public launch race with native-backend
 * fixture synchronization. These tests execute no operating-system child. */
public final class OwnedLaunchFailureTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static void retryUntilConfirmedReap() throws Exception {
        AtomicReference<Thread> creatingThread=new AtomicReference<>();
        AtomicInteger attempts=new AtomicInteger(),diagnostics=new AtomicInteger();
        CountDownLatch firstTermination=new CountDownLatch(1),allowReap=new CountDownLatch(1);
        OwnedProcess.Backend backend=new OwnedProcess.Backend(){
            public long start(OwnedProcess.Specification specification){creatingThread.set(Thread.currentThread());return 1;}
            public int waitFor(long handle,long timeout)throws IOException {
                try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return OwnedProcess.RUNNING;
            }
            public int terminate(long handle)throws IOException {
                int attempt=attempts.incrementAndGet();firstTermination.countDown();
                if(allowReap.getCount()==0)return 143;
                if((attempt&1)==1)throw new IOException("TEST_ONLY_REAP_FAILURE_"+attempt);
                return OwnedProcess.RUNNING;
            }
            public long[] diagnostics(long handle){diagnostics.incrementAndGet();return new long[5];}
        };
        OwnedProcess child=OwnedProcess.start(backend,new OwnedProcess.Specification(Path.of("/test/executable"),List.of(),Map.of(),
            Path.of("/test"),Path.of("/test/stdout"),Path.of("/test/stderr")),null);
        try {
            long began=System.nanoTime();
            try{child.stop(Duration.ZERO);throw new AssertionError("Cleanup without a confirmed reap must time out");}
            catch(IOException expected){check(expected.getMessage().contains("still running"),"Caller receives the bounded cleanup timeout");}
            check(TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-began)<9000,"Caller stop remains bounded while owner retries");
            check(firstTermination.getCount()==0&&attempts.get()>16,"Both throwing and RUNNING backend cleanup paths were exercised repeatedly");
            check(child.isAlive()&&creatingThread.get().isAlive(),"Creating thread and owned child stay live until confirmed reap");
            check(diagnostics.get()==0,"Final metrics cannot consume/release a still-live native handle");
            check(child.failure()!=null&&child.failure().getSuppressed().length<=15,"Repeated permanent failure history stays bounded");
            try{child.exitCode();throw new AssertionError("A fabricated127 exit must not release live ownership");}catch(IllegalThreadStateException expected){ }
        } finally {allowReap.countDown();}
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(1);
        check(!child.isAlive()&&child.exitCode()==143&&child.wasForced()&&diagnostics.get()==1,"Actual final status/diagnostics publish only after backend confirms reap");
        try{child.stop(Duration.ZERO);throw new AssertionError("Earlier failed termination must remain visible after cleanup");}catch(IOException expected){ }
    }
    public static void main(String[] arguments) throws Exception {
        int retainedHandles=0,finishedExceptions=0;
        for(int attempt=0;attempt<200;attempt++) {
            CountDownLatch terminateEntered=new CountDownLatch(1),finishTermination=new CountDownLatch(1);
            AtomicBoolean cleanupDone=new AtomicBoolean(),exceptionBeforeCleanup=new AtomicBoolean();
            AtomicReference<OwnedProcess> process=new AtomicReference<>();AtomicReference<Throwable> failure=new AtomicReference<>();
            OwnedProcess.Backend backend=new OwnedProcess.Backend(){
                @Override public long start(OwnedProcess.Specification specification){return 1;}
                @Override public int waitFor(long handle,long timeout) throws IOException {throw new IOException("TEST_ONLY_OWNER_FAILURE");}
                @Override public int terminate(long handle) throws IOException {
                    terminateEntered.countDown();
                    try {if(!finishTermination.await(3,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_CLEANUP_TIMEOUT");}
                    catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
                    cleanupDone.set(true);return 1;
                }
                @Override public long[] diagnostics(long handle){return new long[5];}
            };
            Thread launcher=new Thread(()->{
                try {process.set(OwnedProcess.start(backend,new OwnedProcess.Specification(Path.of("/test/executable"),List.of(),Map.of(),
                    Path.of("/test"),Path.of("/test/stdout"),Path.of("/test/stderr")),null));}
                catch(Throwable error){if(!cleanupDone.get())exceptionBeforeCleanup.set(true);failure.set(error);}
            },"launch-failure-race-fixture");
            launcher.start();
            try {
                check(terminateEntered.await(2,TimeUnit.SECONDS),"Native cleanup fixture must actually be reached");
                // Give a failing launcher a scheduling opportunity while cleanup
                // remains blocked. Returning a retained Handle is also valid.
                Thread.sleep(1);
            } finally {finishTermination.countDown();}
            launcher.join(2000);check(!launcher.isAlive(),"Launch must settle after native cleanup finishes");
            check(!exceptionBeforeCleanup.get(),"A launch exception must not escape before owned cleanup completes");
            if(process.get()!=null) {
                retainedHandles++;
                long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
                while(process.get().isAlive() && System.nanoTime()<deadline)Thread.sleep(1);
                check(!process.get().isAlive() && process.get().failure()!=null,"A returned Handle retains its failed owner until cleanup");
            } else {finishedExceptions++;check(failure.get() instanceof IOException && cleanupDone.get(),"A failed launch settles only after cleanup");}
        }
        retryUntilConfirmedReap();
        System.out.println("Owned cleanup retry passed throwing/RUNNING/reap fixture; launch cleanup race passed200 trials: retainedHandles="+retainedHandles+", settledExceptions="+finishedExceptions+"; backend fixture only");
    }
}
