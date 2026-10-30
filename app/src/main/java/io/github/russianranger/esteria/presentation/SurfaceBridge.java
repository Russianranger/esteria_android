package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.net.LocalSocket;
import android.net.LocalSocketAddress;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.view.Surface;
import java.io.File;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Real private X11 readback into ANativeWindow. This does not start a display or client. */
public final class SurfaceBridge implements AutoCloseable {
    public interface Events {
        void frameSize(int width, int height);
        void failed(String reason);
    }
    private static final int CACHE_BYTES = 1280 * 720 * 4 + 16;
    private final Events events;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final Path directory;
    private Run active;
    private final List<Run> workers = new ArrayList<>();
    private boolean closed;
    private long frames, unchanged, pixelBytes, captureNanos, receiveNanos, surfaceNanos;

    public SurfaceBridge(Context context, File sessionDirectory, Events events) throws IOException {
        directory = BridgePaths.directory(context, sessionDirectory);
        this.events = events;
        try { System.loadLibrary("esteria-presentation"); }
        catch (UnsatisfiedLinkError error) { throw new IOException("Presentation JNI is not packaged", error); }
    }
    private static native int receiveFrame(Surface surface, int fd, ByteBuffer pixels, long[] measurements);
    /** Call when SurfaceHolder creates a surface; the caller continues to own/release that surface. */
    public synchronized void attach(Surface surface) throws IOException {
        if (closed) throw new IOException("Presentation is closed");
        if (surface == null || !surface.isValid()) throw new IOException("Presentation surface is unavailable");
        detach();
        workers.removeIf(run -> !run.thread.isAlive());
        if (workers.size() >= 8) throw new IOException("Previous presentation workers have not stopped");
        Run run = new Run(surface, new ArrayList<>(workers));
        active = run; workers.add(run);
        run.thread.start();
    }
    /** Interrupt socket I/O immediately; a later attach waits for the previous native writer. */
    public synchronized void detach() {
        Run old = active; active = null;
        if (old != null) old.cancel();
    }
    private synchronized boolean current(Run run) { return !closed && active == run; }
    private final class Run implements Runnable {
        final Surface surface;
        List<Run> predecessors;
        final Thread thread;
        volatile LocalSocket socket;
        volatile boolean cancelled;
        Run(Surface surface, List<Run> predecessors) {
            this.surface = surface; this.predecessors = predecessors;
            thread = new Thread(this, "esteria-surface"); thread.setDaemon(true);
        }
        void cancel() {
            cancelled = true;
            LocalSocket local = socket;
            if (local != null) try { local.shutdownInput(); local.shutdownOutput(); local.close(); }
            catch (IOException ignored) { try { local.close(); } catch (IOException alsoClosed) { /* Already stopped. */ } }
        }
        @Override public void run() {
            try {
                long deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(3);
                for (Run predecessor : predecessors) {
                    long remaining = deadline - System.nanoTime();
                    if (remaining > 0) predecessor.thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(remaining)));
                    if (predecessor.thread.isAlive()) throw new IOException("Previous presentation worker did not stop");
                }
                predecessors = null;
                if (!current(this) || cancelled) return;
                String path = BridgePaths.endpoint(directory, "frame.sock", true);
                try (LocalSocket local = new LocalSocket()) {
                    socket = local;
                    if (!current(this) || cancelled) return;
                    local.connect(new LocalSocketAddress(path, LocalSocketAddress.Namespace.FILESYSTEM));
                    local.setSoTimeout(2000);
                    if (local.getPeerCredentials().getUid() != android.os.Process.myUid())
                        throw new IOException("Presentation peer does not belong to this application");
                    try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.dup(local.getFileDescriptor())) {
                        ByteBuffer pixels = ByteBuffer.allocateDirect(CACHE_BYTES);
                        long[] stats = new long[6]; int width = 0, height = 0;
                        while (current(this) && !cancelled && surface.isValid()) {
                            int result = receiveFrame(surface, descriptor.getFd(), pixels, stats);
                            if (result == 1) { synchronized (SurfaceBridge.this) { unchanged++; } continue; }
                            if (result != 0) throw new IOException("Presentation transport failed: " + result);
                            synchronized (SurfaceBridge.this) {
                                frames++; pixelBytes += stats[5]; captureNanos += stats[2];
                                receiveNanos += stats[3]; surfaceNanos += stats[4];
                            }
                            if (width != stats[0] || height != stats[1]) {
                                width = (int)stats[0]; height = (int)stats[1];
                                int w = width, h = height;
                                main.post(() -> { if (current(this) && events != null) events.frameSize(w, h); });
                            }
                        }
                    }
                } finally { socket = null; }
            } catch (IOException | RuntimeException error) {
                if (current(this)) main.post(() -> { if (current(this) && events != null) events.failed("presentation-worker-failed"); });
            } catch (InterruptedException error) { Thread.currentThread().interrupt(); }
            finally { predecessors = null; }
        }
    }
    /** Fixed numeric counters only; no captured pixels are retained in diagnostics. */
    public synchronized long[] counters() { return new long[]{frames, unchanged, pixelBytes, captureNanos, receiveNanos, surfaceNanos}; }
    /** Call off the UI thread. Failure to stop remains an error, never a successful cleanup. */
    @Override public void close() throws IOException {
        List<Run> pending;
        synchronized (this) { closed = true; detach(); pending = new ArrayList<>(workers); }
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(3500);
        try {
            for (Run run : pending) {
                run.cancel();
                long remaining = deadline - System.nanoTime();
                if (remaining > 0) run.thread.join(Math.max(1, TimeUnit.NANOSECONDS.toMillis(remaining)));
                if (run.thread.isAlive()) throw new IOException("Presentation worker did not stop");
            }
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt(); throw new IOException("Presentation shutdown interrupted", error);
        }
    }
}
