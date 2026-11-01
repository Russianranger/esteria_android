package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;

/** Shared callbacks for explicit runtime setup, never background gameplay downloads. */
public final class RuntimeWork {
    private RuntimeWork() {}
    public interface Progress { void update(String phase, String path, long completed, long total); }
    public interface Cancellation { boolean isCancelled(); }
    public static final Progress NONE = (phase, path, completed, total) -> {};
    public static final Cancellation NEVER_CANCELLED = () -> false;
    public static final class CancelledException extends IOException {
        private static final long serialVersionUID = 1L;
        public CancelledException() { super("Runtime setup cancelled; completed work is retained for resume"); }
    }
    public static final class MemoryPressureException extends IOException {
        private static final long serialVersionUID = 1L;
        public MemoryPressureException() { super("World preparation paused because Android memory is low. Completed work and saves are retained; retry after memory recovers."); }
    }
    public static void checkMemoryPressureExit(int exitCode) throws MemoryPressureException {
        if (exitCode == 75) throw new MemoryPressureException();
    }
    static void check(Cancellation cancellation) throws IOException {
        if (cancellation.isCancelled() || Thread.currentThread().isInterrupted()) throw new CancelledException();
    }
}
