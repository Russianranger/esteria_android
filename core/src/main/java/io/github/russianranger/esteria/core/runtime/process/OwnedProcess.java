package io.github.russianranger.esteria.core.runtime.process;

import io.github.russianranger.esteria.core.runtime.SessionSupervisor;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.ArrayList;
import java.util.Collections;
import java.util.TreeMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Keeps the native creating thread alive until its owned child is reaped.
 * Linux parent-death signals belong to the creating thread, not just the JVM.
 * A service must retain this child and stop it off the Android main thread.
 */
public final class OwnedProcess implements SessionSupervisor.Child {
    public static final int RUNNING = Integer.MIN_VALUE;
    public interface Backend {
        long start(Specification spec) throws IOException;
        int waitFor(long handle, long timeoutMillis) throws IOException;
        int terminate(long handle) throws IOException;
        long[] diagnostics(long handle) throws IOException;
        default boolean writeInput(long handle,byte[] bytes,long timeoutMillis) throws IOException {
            throw new IOException("Backend has no interactive process input");
        }
        default void closeInput(long handle) throws IOException { throw new IOException("Backend has no interactive process input"); }
    }
    /** Must send the actual component's save/shutdown request; no signal substitutes. */
    public interface GracefulStop { void request() throws Exception; }
    /** Input acceptance alone is not a shutdown acknowledgment; the owned process must exit. */
    public interface GracefulInputStop { void request(OwnedProcess process) throws Exception; }
    public static final class Specification {
        public final Path executable, cwd, stdout, stderr;
        public final List<String> arguments;
        public final Map<String,String> environment;
        public final boolean interactiveInput;
        public Specification(Path executable, List<String> arguments, Map<String,String> environment,
                Path cwd, Path stdout, Path stderr) {
            this(executable,arguments,environment,cwd,stdout,stderr,false);
        }
        public Specification(Path executable, List<String> arguments, Map<String,String> environment,
                Path cwd, Path stdout, Path stderr,boolean interactiveInput) {
            for (Path path : new Path[]{executable,cwd,stdout,stderr})
                if (path == null || !path.isAbsolute()) throw new IllegalArgumentException("Absolute process paths required");
            if (stdout.equals(stderr) || arguments.size() > 128 || environment.size() > 64)
                throw new IllegalArgumentException("Invalid process specification");
            for (String value : arguments) bounded(value);
            for (Map.Entry<String,String> item : environment.entrySet()) {
                if (!item.getKey().matches("[A-Za-z_][A-Za-z0-9_]*")) throw new IllegalArgumentException("Invalid environment key");
                bounded(item.getKey()+"="+item.getValue());
            }
            this.executable=executable; this.cwd=cwd; this.stdout=stdout; this.stderr=stderr;
            this.arguments=Collections.unmodifiableList(new ArrayList<>(arguments));
            this.environment=Collections.unmodifiableMap(new TreeMap<>(environment));
            this.interactiveInput=interactiveInput;
        }
        private static void bounded(String value) {
            if (value == null || value.indexOf('\0') >= 0 || value.length() > 16384)
                throw new IllegalArgumentException("Invalid process argument");
        }
    }
    private final Backend backend;
    private final GracefulInputStop graceful;
    private final boolean interactiveInput;
    private final CountDownLatch started=new CountDownLatch(1), finished=new CountDownLatch(1);
    private volatile IOException failure;
    private volatile int status=RUNNING;
    private volatile long stopDeadline;
    private volatile boolean stopRequested, forced, auxiliaryStop;
    private volatile long inputHandle;
    private volatile long[] metrics=new long[5];

    private OwnedProcess(Backend backend, Specification spec, GracefulInputStop graceful) {
        this.backend=backend; this.graceful=graceful; this.interactiveInput=spec.interactiveInput;
    }
    public static OwnedProcess start(Backend backend, Specification spec, GracefulStop graceful) throws IOException {
        return launch(backend,spec,graceful==null?null:child->graceful.request());
    }
    public static OwnedProcess startInteractive(Backend backend,Specification spec,GracefulInputStop graceful) throws IOException {
        if (!spec.interactiveInput) throw new IllegalArgumentException("Interactive process specification required");
        return launch(backend,spec,graceful);
    }
    private static OwnedProcess launch(Backend backend,Specification spec,GracefulInputStop graceful) throws IOException {
        OwnedProcess child=new OwnedProcess(backend,spec,graceful);
        Thread owner=new Thread(()->child.own(spec),"esteria-native-owner");
        owner.setDaemon(true); owner.start();
        try { child.started.await(); }
        catch (InterruptedException e) {
            child.requestStop(Duration.ZERO);
            boolean interrupted=false;
            // Do not abandon an already-created native child on caller cancellation.
            while (true) try { child.finished.await(); break; } catch (InterruptedException again) { interrupted=true; }
            Thread.currentThread().interrupt();
            throw new IOException("Process launch interrupted"+(interrupted?" during cleanup":""),e);
        }
        if (child.failure!=null) {
            // The started latch can be released before a subsequent ownership
            // failure finishes native termination. Callers releasing storage
            // leases on launch failure must not race that still-owned child.
            boolean interrupted=false;
            while(true) try {child.finished.await();break;}
            catch(InterruptedException error){child.requestStop(Duration.ZERO);interrupted=true;}
            if(interrupted)Thread.currentThread().interrupt();
            throw child.failure;
        }
        return child;
    }
    private void own(Specification spec) {
        long handle=0;
        FutureTask<Void> shutdown=null;
        try {
            handle=backend.start(spec);
            if (handle<=0) throw new IOException("Native owner returned an invalid handle");
            inputHandle=handle;
            started.countDown();
            while (status==RUNNING) {
                status=backend.waitFor(handle,40);
                if (status!=RUNNING) break;
                if (!stopRequested) continue;
                if (shutdown==null && graceful!=null && System.nanoTime()<stopDeadline) {
                    shutdown=new FutureTask<>(()->{graceful.request(this);return null;});
                    Thread request=new Thread(shutdown,"esteria-graceful-stop"); request.setDaemon(true); request.start();
                }
                boolean callbackFailed=false;
                if (shutdown!=null && shutdown.isDone()) try { shutdown.get(); }
                catch (Exception e) { remember(new IOException("Component shutdown request failed",e)); callbackFailed=true; }
                if (graceful==null || callbackFailed || System.nanoTime()>=stopDeadline) {
                    forced=true;
                    status=backend.terminate(handle);
                    if (status==RUNNING) throw new IOException("Native process did not terminate");
                    if (!auxiliaryStop) remember(new IOException("Graceful shutdown did not complete; owned process was terminated"));
                }
            }
            if (stopRequested && shutdown!=null) {
                try { shutdown.get(Math.max(0,stopDeadline-System.nanoTime()),TimeUnit.NANOSECONDS); }
                catch (Exception e) { remember(new IOException("Component shutdown was not acknowledged",e)); }
                if (status!=0) remember(new IOException("Component shutdown exited with code "+status));
            }
        } catch (Exception e) {
            remember(e instanceof IOException?(IOException)e:new IOException("Native process ownership failed",e));
        } finally {
            inputHandle=0;
            if (shutdown!=null) shutdown.cancel(true);
            if (handle>0) {
                if (status==RUNNING) try {
                    forced=true; status=backend.terminate(handle);
                    if (status==RUNNING) remember(new IOException("Native process cleanup remains incomplete"));
                } catch (IOException e) { remember(e); }
                try {
                    long[] observed=backend.diagnostics(handle);
                    if (observed.length!=5) throw new IOException("Invalid native process diagnostics");
                    metrics=observed.clone();
                    if (metrics[4]!=0) remember(new IOException("Native process log IO failed"));
                } catch (IOException e) { remember(e); }
            }
            if (status==RUNNING) status=127;
            started.countDown(); finished.countDown();
        }
    }
    private void remember(IOException error) { if (failure==null) failure=error; else failure.addSuppressed(error); }
    private void requestStop(Duration timeout) { requestStop(timeout,false); }
    private synchronized void requestStop(Duration timeout, boolean auxiliary) {
        if (auxiliary && graceful!=null) throw new IllegalStateException("A persistent component must use its graceful shutdown protocol");
        // The first caller owns shutdown semantics; an auxiliary request must
        // never erase a prior normal stop's failure or save acknowledgment.
        if (!stopRequested) { stopDeadline=System.nanoTime()+timeout.toNanos(); auxiliaryStop=auxiliary; stopRequested=true; }
    }
    @Override public boolean isAlive() { return finished.getCount()!=0; }
    @Override public int exitCode() { if (isAlive()) throw new IllegalThreadStateException("Process still owned"); return status; }
    public boolean wasForced() { return forced; }
    public IOException failure() { return failure; }
    /** Queues one atomic 1..4096-byte message; false means timeout with zero bytes queued.
     * Does not log bytes or prove the child consumed/acted upon them. Never call on the UI thread.
     */
    public boolean writeInput(byte[] bytes,Duration timeout) throws IOException {
        if (bytes==null || bytes.length==0 || bytes.length>4096 || timeout==null || timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(1))>0)
            throw new IllegalArgumentException("Process input must be 1..4096 bytes with timeout zero to one second");
        long handle=inputHandle;
        if (!interactiveInput || handle==0 || !isAlive()) throw new IOException("Owned process input is unavailable");
        return backend.writeInput(handle,bytes.clone(),timeout.toMillis());
    }
    /** EOF only; never a substitute for the component's explicit save/shutdown command. */
    public void closeInput() throws IOException {
        long handle=inputHandle;
        if (!interactiveInput || handle==0 || !isAlive()) throw new IOException("Owned process input is unavailable");
        backend.closeInput(handle);
    }
    /** Captured stdout read/stored, stderr read/stored, log errors; available after completion. */
    public long[] diagnostics() { return metrics.clone(); }
    @Override public void stop(Duration timeout) throws IOException {
        if (timeout.isNegative() || timeout.compareTo(Duration.ofSeconds(30))>0)
            throw new IllegalArgumentException("Shutdown timeout must be between zero and 30 seconds");
        requestStop(timeout);
        awaitStop(timeout);
    }
    /** Terminate a stateless auxiliary process through the same owned native
     * TERM/KILL/reap path. This never reports a save or graceful acknowledgment;
     * wasForced and the actual exit status remain available. Existing failures
     * and cleanup/log errors are still thrown. Not valid for graceful callbacks.
     */
    public void terminateAuxiliary() throws IOException {
        requestStop(Duration.ZERO,true);
        awaitStop(Duration.ZERO);
    }
    private void awaitStop(Duration timeout) throws IOException {
        try {
            if (!finished.await(timeout.toMillis()+7000,TimeUnit.MILLISECONDS)) throw new IOException("Native cleanup is still running");
        } catch (InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException("Interrupted while waiting for native cleanup",e); }
        if (failure!=null) throw failure;
    }
}
