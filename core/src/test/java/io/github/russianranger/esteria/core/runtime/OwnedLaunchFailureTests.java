package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.nio.file.Path;
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
        System.out.println("Owned launch cleanup race passed200 trials: retainedHandles="+retainedHandles+", settledExceptions="+finishedExceptions+"; backend fixture only");
    }
}
