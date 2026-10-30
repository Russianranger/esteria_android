package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Starts a dependency chain and tears it down in reverse order on any failure.
 * Readiness must test the real service (for example SQL query or realm protocol),
 * not merely sleep. Process groups and runtime-specific graceful commands belong
 * to the supplied Child implementation; this class never claims descendant control.
 */
public final class SessionSupervisor implements AutoCloseable {
    public enum State { IDLE, STARTING, RUNNING, STOPPING, STOPPED, FAILED }
    public interface Child {
        boolean isAlive();
        int exitCode();
        /** Must finish cleanup before returning; throw if graceful shutdown failed. */
        void stop(Duration timeout) throws Exception;
    }
    public interface Factory { Child start() throws Exception; }
    public interface Readiness {
        void await(Child child, long deadlineNanos, AtomicBoolean cancelled) throws Exception;
    }
    public interface Observer { void changed(State state, String detail); }
    public static final class Component {
        public final String name;
        public final Factory factory;
        public final Readiness readiness;
        public final Duration startupTimeout;
        public Component(String name, Factory factory, Readiness readiness, Duration startupTimeout) {
            if (!name.matches("[a-z][a-z0-9-]{0,47}")) throw new IllegalArgumentException("Invalid component name");
            if (startupTimeout.isNegative() || startupTimeout.isZero() || startupTimeout.compareTo(Duration.ofMinutes(30)) > 0)
                throw new IllegalArgumentException("Invalid startup timeout");
            this.name = name; this.factory = factory; this.readiness = readiness; this.startupTimeout = startupTimeout;
        }
    }
    private static final class Active {
        final Component component; final Child child;
        Active(Component component, Child child) { this.component = component; this.child = child; }
    }
    private final Object lock = new Object();
    private final Object cleanupLock = new Object();
    private final Observer observer;
    private final Duration stopTimeout;
    private final AtomicBoolean cancelled = new AtomicBoolean();
    private final AtomicBoolean terminating = new AtomicBoolean();
    private final List<Active> active = new ArrayList<>();
    private volatile State state = State.IDLE;
    private volatile String detail = "No session";
    private Thread monitor;
    private volatile Thread startupOwner;
    private volatile CountDownLatch stopped = new CountDownLatch(1);
    private volatile Thread cleanupOwner;
    private Exception terminationFailure;

    public SessionSupervisor(Observer observer, Duration stopTimeout) {
        if (stopTimeout.isNegative() || stopTimeout.isZero()) throw new IllegalArgumentException("Invalid stop timeout");
        this.observer = observer; this.stopTimeout = stopTimeout;
    }
    public State state() { return state; }
    public String detail() { return detail; }
    /** Dependencies remain owned while a later child still needs shutdown. */
    public List<String> retainedComponents() {
        synchronized (lock) {
            List<String> names = new ArrayList<>();
            for (Active item : active) names.add(item.component.name);
            return Collections.unmodifiableList(names);
        }
    }

    /** One supervisor instance owns one session. Call off the Android main thread. */
    public void start(List<Component> components) throws Exception {
        synchronized (lock) {
            if (state != State.IDLE) throw new IllegalStateException("Session already used");
            if (components.isEmpty()) throw new IllegalArgumentException("No runtime components");
            state = State.STARTING;
            startupOwner = Thread.currentThread();
        }
        emit(State.STARTING, "Preparing local services");
        try {
            for (Component component : components) {
                checkCancelled(); checkDependencies();
                emit(State.STARTING, "Starting " + component.name);
                Child child = component.factory.start();
                synchronized (lock) { active.add(new Active(component, child)); }
                checkCancelled();
                long deadline = System.nanoTime() + component.startupTimeout.toNanos();
                awaitReady(component, child, deadline);
                checkCancelled(); checkDependencies();
                if (System.nanoTime() > deadline) throw new IOException(component.name + " readiness timed out");
            }
            synchronized (lock) {
                checkCancelled();
                state = State.RUNNING;
                monitor = new Thread(this::monitorLoop, "esteria-session-monitor");
                monitor.setDaemon(true);
            }
            emit(State.RUNNING, "Local session running");
            monitor.start();
        } catch (Exception failure) {
            // The startup thread always owns cleanup until the monitor starts.
            terminate(failure instanceof CancellationException ? null : failure);
            throw failure;
        }
    }

    /** Nonblocking cancellation request; readiness implementations must observe it. */
    public void requestStop() { cancelled.set(true); }

    private void monitorLoop() {
        Exception failure = null;
        try {
            while (!cancelled.get()) {
                checkDependencies();
                Thread.sleep(100);
            }
        } catch (Exception e) { failure = e; }
        terminate(failure);
    }

    private void checkCancelled() { if (cancelled.get()) throw new CancellationException("Session cancelled"); }
    private void awaitReady(Component component, Child child, long deadline) throws Exception {
        FutureTask<Void> ready = new FutureTask<>(() -> { component.readiness.await(child, deadline, cancelled); return null; });
        Thread probe = new Thread(ready, "esteria-ready-" + component.name); probe.setDaemon(true); probe.start();
        try {
            while (true) {
                checkCancelled(); checkDependencies();
                long remaining = deadline - System.nanoTime();
                if (remaining <= 0) throw new IOException(component.name + " readiness timed out");
                try { ready.get(Math.min(remaining, TimeUnit.MILLISECONDS.toNanos(100)), TimeUnit.NANOSECONDS); return; }
                catch (TimeoutException pending) { /* Recheck every dependency while waiting. */ }
                catch (ExecutionException e) {
                    if (e.getCause() instanceof Exception) throw (Exception) e.getCause();
                    throw new IOException(component.name + " readiness failed", e.getCause());
                }
            }
        } finally { ready.cancel(true); }
    }
    private void checkDependencies() throws IOException {
        synchronized (lock) {
            for (Active item : active) if (!item.child.isAlive())
                throw new IOException(item.component.name + " exited with code " + item.child.exitCode());
        }
    }
    private void terminate(Exception failure) {
        synchronized (cleanupLock) { terminateOwned(failure); }
    }
    private void terminateOwned(Exception failure) {
        if (!terminating.compareAndSet(false, true)) return;
        CountDownLatch completion = stopped;
        if (completion.getCount() == 0) { completion = new CountDownLatch(1); stopped = completion; }
        cleanupOwner = Thread.currentThread();
        try {
            if (terminationFailure == null) terminationFailure = failure;
            else if (failure != null && failure != terminationFailure) terminationFailure.addSuppressed(failure);
            cancelled.set(true);
            emit(State.STOPPING, "Saving and stopping local services");
            List<Active> reverse;
            synchronized (lock) { reverse = new ArrayList<>(active); }
            Collections.reverse(reverse);
            for (Active item : reverse) {
                try { item.child.stop(stopTimeout); }
                catch (Exception cleanupFailure) { rememberCleanupFailure(item.component.name, cleanupFailure); }
                boolean alive = true;
                try { alive = item.child.isAlive(); }
                catch (RuntimeException observationFailure) { rememberCleanupFailure(item.component.name, observationFailure); }
                if (alive) {
                    // A running world/client must keep its database/display dependencies.
                    rememberCleanupFailure(item.component.name, new IOException("Owned child is still active; retry shutdown"));
                    break;
                }
                synchronized (lock) { active.remove(item); }
            }
            List<String> retained = retainedComponents();
            emit(terminationFailure == null ? State.STOPPED : State.FAILED,
                    terminationFailure == null ? "Local session stopped" : terminationFailure.getClass().getSimpleName() + ": " +
                    terminationFailure.getMessage() + (retained.isEmpty() ? "" : "; cleanup ownership retained for " + String.join(", ", retained)));
        } finally {
            cleanupOwner = null;
            terminating.set(false);
            completion.countDown();
        }
    }
    private void rememberCleanupFailure(String component, Exception failure) {
        if (terminationFailure == null) terminationFailure = new IOException("Shutdown failed for " + component, failure);
        else terminationFailure.addSuppressed(failure);
    }
    private void emit(State next, String message) {
        state = next; detail = message;
        if (observer != null) {
            try { observer.changed(next, message); } catch (RuntimeException ignored) { /* UI cannot break cleanup. */ }
        }
    }
    @Override public void close() {
        requestStop();
        if (cleanupOwner == Thread.currentThread()) return;
        // A subsequent close explicitly retries retained owners. Preserve the first
        // failure even if cleanup succeeds later; it is not evidence of a clean save.
        if (state == State.FAILED && activeCount() != 0) { terminate(null); return; }
        if (state != State.IDLE && !(state == State.STARTING && startupOwner == Thread.currentThread()) && monitor != Thread.currentThread()) {
            try { stopped.await(stopTimeout.toMillis() * Math.max(1, activeCount()) + 1000, TimeUnit.MILLISECONDS); }
            catch (InterruptedException e) { Thread.currentThread().interrupt(); }
        }
    }
    private int activeCount() { synchronized (lock) { return active.size(); } }
}
