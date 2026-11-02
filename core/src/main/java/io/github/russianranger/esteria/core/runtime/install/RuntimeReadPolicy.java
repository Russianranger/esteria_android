package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.file.Path;
import java.util.Objects;
import java.util.Map;
import java.util.LinkedHashMap;

/** Worker-local pacing/cache observations; bytes and verification are never replaced. */
public final class RuntimeReadPolicy {
    public interface ReadObserver {
        /** Start offset and positive length of the chunk just consumed. */
        void onRead(Path file, long offset, int bytes) throws IOException;
    }
    private static final ThreadLocal<Scope> CURRENT = new ThreadLocal<>();
    private RuntimeReadPolicy() { }
    public static Scope install(ReadObserver observer) {
        Scope current = CURRENT.get();
        return installScope(observer, current == null ? null : current.speed);
    }
    /** Explicit preparation selection; import and ordinary runtime reads keep their old policy. */
    public static Scope install(ReadObserver observer, PreparationSpeed speed) {
        return installScope(observer, Objects.requireNonNull(speed));
    }
    private static Scope installScope(ReadObserver observer, PreparationSpeed speed) {
        Scope scope = new Scope(Objects.requireNonNull(observer), CURRENT.get(), speed);
        CURRENT.set(scope); return scope;
    }
    /** Put the same worker-local selection into the sanitized guest environment. */
    public static Map<String,String> preparationEnvironment(Map<String,String> environment) {
        Objects.requireNonNull(environment);
        Scope scope = CURRENT.get();
        if (scope == null || scope.speed == null) return environment;
        Map<String,String> selected = new LinkedHashMap<>(environment);
        selected.put(PreparationSpeed.ENVIRONMENT_KEY, scope.speed.id);
        return java.util.Collections.unmodifiableMap(selected);
    }
    public static void consumed(Path file, long offset, int bytes) throws IOException {
        Scope scope = CURRENT.get(); if (scope == null) return;
        if (file == null || offset < 0 || bytes <= 0 || bytes > Long.MAX_VALUE - offset)
            throw new IllegalArgumentException("Invalid runtime read range");
        scope.observer.onRead(file, offset, bytes);
    }
    public static final class Scope implements AutoCloseable {
        private final ReadObserver observer;
        private final Scope previous;
        private final PreparationSpeed speed;
        private final Thread owner = Thread.currentThread();
        private boolean closed;
        private Scope(ReadObserver observer, Scope previous, PreparationSpeed speed) {
            this.observer = observer; this.previous = previous; this.speed = speed;
        }
        @Override public void close() {
            if (owner != Thread.currentThread()) throw new IllegalStateException("Runtime read scope belongs to another worker");
            if (closed) return;
            if (CURRENT.get() != this) throw new IllegalStateException("Runtime read scopes must close in reverse order");
            if (previous == null) CURRENT.remove(); else CURRENT.set(previous);
            closed = true;
        }
    }
}
