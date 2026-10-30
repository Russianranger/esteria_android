package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.CancellationException;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

public final class SessionSupervisorTest {
    private static int passed;
    private static final Duration SECOND = Duration.ofSeconds(1);
    private static final class Fake implements SessionSupervisor.Child {
        final String name; final List<String> events;
        volatile boolean alive = true; boolean failStop;
        Fake(String name, List<String> events) { this.name = name; this.events = events; }
        public boolean isAlive() { return alive; }
        public int exitCode() { return 7; }
        public void stop(Duration timeout) throws IOException { events.add("stop:" + name); alive = false; if (failStop) throw new IOException("save failed"); }
    }
    private static SessionSupervisor.Component component(String name, Fake child) {
        return new SessionSupervisor.Component(name, () -> { child.events.add("start:" + name); return child; },
                (p, deadline, cancelled) -> child.events.add("ready:" + name), SECOND);
    }
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static void test(String name, Throwing test) throws Exception { test.run(); passed++; System.out.println("PASS " + name); }
    interface Throwing { void run() throws Exception; }
    private static void awaitTerminal(SessionSupervisor supervisor) throws Exception {
        long end = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
        while (System.nanoTime() < end) {
            if (supervisor.state() == SessionSupervisor.State.STOPPED || supervisor.state() == SessionSupervisor.State.FAILED) return;
            Thread.sleep(5);
        }
        throw new AssertionError("Supervisor did not stop");
    }
    public static void main(String[] args) throws Exception {
        test("dependency order and reverse cleanup", () -> {
            List<String> events = Collections.synchronizedList(new ArrayList<>());
            Fake db = new Fake("database", events), auth = new Fake("auth", events);
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            supervisor.start(Arrays.asList(component("database", db), component("auth", auth)));
            check(supervisor.state() == SessionSupervisor.State.RUNNING, "not running");
            supervisor.close(); awaitTerminal(supervisor);
            check(events.equals(Arrays.asList("start:database", "ready:database", "start:auth", "ready:auth", "stop:auth", "stop:database")), events.toString());
        });
        test("failed readiness rolls back earlier services", () -> {
            List<String> events = new ArrayList<>(); Fake db = new Fake("database", events), world = new Fake("world", events);
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            try {
                supervisor.start(Arrays.asList(component("database", db), new SessionSupervisor.Component("world", () -> world,
                        (p, d, c) -> { throw new IOException("world data missing"); }, SECOND)));
                throw new AssertionError("failed readiness accepted");
            } catch (IOException expected) { }
            check(supervisor.state() == SessionSupervisor.State.FAILED && !db.alive && !world.alive, "rollback incomplete");
            check(events.subList(events.size() - 2, events.size()).equals(Arrays.asList("stop:world", "stop:database")), "wrong rollback order");
        });
        test("dependency death tears down complete session", () -> {
            List<String> events = Collections.synchronizedList(new ArrayList<>()); Fake db = new Fake("database", events), world = new Fake("world", events);
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            supervisor.start(Arrays.asList(component("database", db), component("world", world)));
            db.alive = false; awaitTerminal(supervisor);
            check(supervisor.state() == SessionSupervisor.State.FAILED && !world.alive, "dependency death ignored");
            check(supervisor.detail().contains("database exited with code 7"), "missing exit evidence");
        });
        test("cancellation during readiness cleans up", () -> {
            List<String> events = Collections.synchronizedList(new ArrayList<>()); Fake db = new Fake("database", events);
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND); CountDownLatch ready = new CountDownLatch(1);
            Thread worker = new Thread(() -> {
                try { supervisor.start(Collections.singletonList(new SessionSupervisor.Component("database", () -> db, (p, d, c) -> {
                    ready.countDown(); while (!c.get()) Thread.sleep(5); throw new CancellationException("cancelled");
                }, SECOND))); throw new AssertionError("cancellation accepted"); }
                catch (CancellationException expected) { } catch (Exception failure) { throw new RuntimeException(failure); }
            });
            worker.start(); check(ready.await(1, TimeUnit.SECONDS), "readiness not entered"); supervisor.requestStop(); worker.join(2000);
            check(!worker.isAlive() && !db.alive && supervisor.state() == SessionSupervisor.State.STOPPED, "cancel failed");
        });
        test("dependency death interrupts a later readiness probe", () -> {
            List<String> events = Collections.synchronizedList(new ArrayList<>()); Fake db = new Fake("database", events), world = new Fake("world", events);
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND); CountDownLatch entered = new CountDownLatch(1);
            AtomicBoolean failed = new AtomicBoolean();
            Thread worker = new Thread(() -> {
                try { supervisor.start(Arrays.asList(component("database", db), new SessionSupervisor.Component("world", () -> world, (p, d, c) -> {
                    entered.countDown(); Thread.sleep(60_000);
                }, Duration.ofMinutes(2)))); }
                catch (Exception expected) { failed.set(true); }
            });
            worker.start(); check(entered.await(1, TimeUnit.SECONDS), "probe not entered"); db.alive = false; worker.join(2000);
            check(!worker.isAlive() && failed.get() && !world.alive && supervisor.state() == SessionSupervisor.State.FAILED, "startup dependency failure was delayed");
        });
        test("shutdown failure is preserved", () -> {
            Fake db = new Fake("database", new ArrayList<>()); db.failStop = true;
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND); supervisor.start(Collections.singletonList(component("database", db)));
            supervisor.close(); awaitTerminal(supervisor);
            check(supervisor.state() == SessionSupervisor.State.FAILED && supervisor.detail().contains("Shutdown failed"), "false successful shutdown");
        });
        test("live failed child retains dependencies and supports explicit cleanup retry", () -> {
            List<String> events = Collections.synchronizedList(new ArrayList<>());
            Fake db = new Fake("database", events);
            Process nativeChild = new ProcessBuilder("/bin/sh", "-c", "read line").start();
            AtomicBoolean mayStop = new AtomicBoolean();
            SessionSupervisor.Child world = new SessionSupervisor.Child() {
                public boolean isAlive() { return nativeChild.isAlive(); }
                public int exitCode() { return nativeChild.exitValue(); }
                public void stop(Duration timeout) throws Exception {
                    events.add("stop:world");
                    if (!mayStop.get()) throw new IOException("Owned shutdown timed out");
                    nativeChild.getOutputStream().write("stop\n".getBytes(java.nio.charset.StandardCharsets.US_ASCII));
                    nativeChild.getOutputStream().flush();
                    if (!nativeChild.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) throw new IOException("Test child did not exit");
                }
            };
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            try {
                supervisor.start(Arrays.asList(component("database", db), new SessionSupervisor.Component("world", () -> world, (p,d,c) -> { }, SECOND)));
                supervisor.close(); awaitTerminal(supervisor);
                check(world.isAlive() && db.alive && !events.contains("stop:database"), "dependency stopped while child remained live");
                check(supervisor.retainedComponents().equals(Arrays.asList("database", "world")), "live owners lost");
                check(supervisor.detail().contains("cleanup ownership retained"), "missing retained-owner evidence");
                mayStop.set(true); supervisor.close();
                check(!world.isAlive() && !db.alive && supervisor.retainedComponents().isEmpty(), "cleanup retry failed");
                check(supervisor.state() == SessionSupervisor.State.FAILED && supervisor.detail().contains("Shutdown failed"), "retry erased failure");
            } finally { nativeChild.destroyForcibly(); nativeChild.waitFor(2, TimeUnit.SECONDS); }
        });
        test("a stop method returning with a live child is never successful cleanup", () -> {
            Fake db = new Fake("database", new ArrayList<>());
            AtomicBoolean alive = new AtomicBoolean(true);
            SessionSupervisor.Child broken = new SessionSupervisor.Child() {
                public boolean isAlive() { return alive.get(); }
                public int exitCode() { return 0; }
                public void stop(Duration timeout) { }
            };
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            supervisor.start(Arrays.asList(component("database", db), new SessionSupervisor.Component("client", () -> broken, (p,d,c) -> { }, SECOND)));
            supervisor.close(); awaitTerminal(supervisor);
            check(db.alive && supervisor.state() == SessionSupervisor.State.FAILED && supervisor.retainedComponents().size() == 2,
                    "live child/dependencies were abandoned");
            alive.set(false); supervisor.close();
            check(!db.alive && supervisor.retainedComponents().isEmpty(), "dead child cleanup did not release dependencies");
        });
        test("concurrent close waits for the active retained-owner retry", () -> {
            Fake db = new Fake("database", new ArrayList<>());
            AtomicBoolean retry = new AtomicBoolean(), alive = new AtomicBoolean(true), otherClosed = new AtomicBoolean();
            CountDownLatch entered = new CountDownLatch(1), release = new CountDownLatch(1);
            SessionSupervisor.Child child = new SessionSupervisor.Child() {
                public boolean isAlive() { return alive.get(); }
                public int exitCode() { return 0; }
                public void stop(Duration timeout) throws Exception {
                    if (!retry.get()) throw new IOException("Retain for retry");
                    entered.countDown();
                    if (!release.await(2, TimeUnit.SECONDS)) throw new IOException("Test retry not released");
                    alive.set(false);
                }
            };
            SessionSupervisor supervisor = new SessionSupervisor(null, SECOND);
            supervisor.start(Arrays.asList(component("database", db), new SessionSupervisor.Component("client", () -> child, (p,d,c) -> { }, SECOND)));
            supervisor.close(); awaitTerminal(supervisor); retry.set(true);
            Thread first = new Thread(supervisor::close), second = new Thread(() -> { supervisor.close(); otherClosed.set(true); });
            try {
                first.start(); check(entered.await(1, TimeUnit.SECONDS), "cleanup retry not entered");
                second.start(); second.join(150);
                check(!otherClosed.get() && db.alive, "concurrent close skipped active cleanup");
            } finally { release.countDown(); first.join(2000); second.join(2000); }
            check(!first.isAlive() && !second.isAlive() && otherClosed.get() && !db.alive && supervisor.retainedComponents().isEmpty(),
                    "concurrent cleanup did not complete");
        });
        test("real process exit and bounded logs", () -> {
            Path dir = Files.createTempDirectory("esteria-process-test-"); Path log = dir.resolve("world.log");
            LoggedProcess child = LoggedProcess.start(Arrays.asList("/bin/sh", "-c", "i=0; while [ $i -lt 2000 ]; do echo abcdefghijklmnopqrstuvwxyz; i=$((i+1)); done"), dir, Collections.emptyMap(), log, 8192);
            long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
            while (child.isAlive() && System.nanoTime() < deadline) Thread.sleep(5);
            child.stop(SECOND);
            check(!child.isAlive() && child.exitCode() == 0, "process failed");
            check(Files.size(log) <= 8192 && Files.size(dir.resolve("world.log.previous")) <= 8192, "unbounded logs");
        });
        System.out.println("SessionSupervisor: " + passed + " tests passed");
    }
}
