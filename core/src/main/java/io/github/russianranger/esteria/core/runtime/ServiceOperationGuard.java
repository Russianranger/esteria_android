package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.locks.ReentrantLock;

/** Serialize service work with shutdown while preserving the caller's deadline. */
public final class ServiceOperationGuard {
    @FunctionalInterface public interface Operation<T> { T run() throws IOException; }
    private final ReentrantLock lock=new ReentrantLock();
    private final AtomicBoolean stopRequested=new AtomicBoolean();
    public boolean isStopRequested(){return stopRequested.get();}
    public <T> T run(Operation<T> operation) throws IOException {
        if(!lock.tryLock())throw new IOException("Another owned service operation is active");
        try {
            if(stopRequested.get())throw new IOException("Service shutdown has been requested");
            return operation.run();
        } finally {lock.unlock();}
    }
    /** A timed-out caller retains the service and retries after its operation
     * reaches a safe boundary. This guard never terminates a service process. */
    public StopPermit stopWithin(Duration timeout) throws IOException {
        final long budget;
        try {budget=timeout.toNanos();}catch(ArithmeticException error){throw new IOException("Invalid shutdown timeout",error);}
        if(budget<0)throw new IOException("Invalid shutdown timeout");
        long started=System.nanoTime();
        stopRequested.set(true);
        try {
            if(!lock.tryLock(budget,TimeUnit.NANOSECONDS))
                throw new IOException("Service operation has not reached its safe boundary; live service and lease retained");
        } catch(InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new IOException("Shutdown interrupted; live service and lease retained",error);
        }
        return new StopPermit(started,budget);
    }
    public final class StopPermit implements AutoCloseable {
        private final long started,budget;
        private boolean closed;
        private StopPermit(long started,long budget){this.started=started;this.budget=budget;}
        public Duration remaining(){return Duration.ofNanos(Math.max(0,budget-(System.nanoTime()-started)));}
        @Override public void close(){if(!closed){closed=true;lock.unlock();}}
    }
}
