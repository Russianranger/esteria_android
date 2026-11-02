package io.github.russianranger.esteria;

import android.app.ActivityManager;
import android.content.ComponentCallbacks2;
import android.content.Context;
import android.os.ParcelFileDescriptor;
import android.system.Os;
import android.system.OsConstants;
import io.github.russianranger.esteria.core.importer.ImportIoGovernor;
import io.github.russianranger.esteria.core.runtime.install.PreparationSpeed;
import java.io.BufferedReader;
import java.io.FileReader;
import java.io.IOException;
import java.nio.file.Path;

/** Import-only pressure probe and advisory cache release. Never raises the app heap limit. */
final class ImportIoController {
    interface Diagnostics {
        void io(String key, long value);
        void io(String key, String value);
        void memory();
        void checkpoint();
    }
    static final long NORMAL_BYTES_PER_SECOND = 8L << 20;
    static final long PRESSURE_BYTES_PER_SECOND = 2L << 20;
    private static final long SAMPLE_INTERVAL_NANOS = 1_000_000_000L;
    private static final long TRIM_WINDOW_NANOS = 15_000_000_000L;
    private static final long CACHE_WINDOW = 2L << 20;
    private final ActivityManager manager;
    private final Diagnostics diagnostics;
    private final ImportIoGovernor governor;
    private final String operationLabel;
    private final long normalBytesPerSecond;
    private final boolean preparation;
    private volatile int trimLevel = -1;
    private volatile long trimAtNanos, trimAtEpochMs;
    private int pressureTrimLevel = -1;
    private long pressureTrimAtNanos;
    private long sampledAt, cacheCalls, cacheBytes, cacheErrors, peakDirty, peakWriteback;
    private int pressure, lastCacheErrno;
    private volatile String statusHint = "Import speed is limited to 8 MiB/s to reduce memory pressure.";

    private Path readPath;
    private long readStart, readBytes;
    ImportIoController(Context context, Diagnostics diagnostics) {
        this(context,diagnostics,"Import");
    }
    ImportIoController(Context context, Diagnostics diagnostics, String operationLabel) {
        this(context, diagnostics, operationLabel, PreparationSpeed.GENTLE, false);
    }
    ImportIoController(Context context, Diagnostics diagnostics, String operationLabel, PreparationSpeed speed) {
        this(context, diagnostics, operationLabel, speed, true);
    }
    private ImportIoController(Context context, Diagnostics diagnostics, String operationLabel, PreparationSpeed speed, boolean preparation) {
        manager = context.getSystemService(ActivityManager.class);
        this.diagnostics = diagnostics;
        this.operationLabel = operationLabel;
        this.preparation = preparation;
        normalBytesPerSecond = java.util.Objects.requireNonNull(speed).bytesPerSecond;
        governor = new ImportIoGovernor(normalBytesPerSecond, PRESSURE_BYTES_PER_SECOND, this::pressure, this::release);
        diagnostics.io("ioPolicy", (normalBytesPerSecond >> 20) + "MiB-per-second-2MiB-sync-cache-windows");
        diagnostics.io("ioNormalBytesPerSecond", normalBytesPerSecond);
        diagnostics.io("ioPressureBytesPerSecond", PRESSURE_BYTES_PER_SECOND);
        pressure();
    }
    ImportIoGovernor governor() { return governor; }
    int pressureLevel() { return pressure(); }
    void readObserved(Path path, long offset, int count, io.github.russianranger.esteria.core.importer.GameDataImporter.Cancellation cancellation) throws IOException {
        if (path == null || offset < 0 || count <= 0) throw new IllegalArgumentException("Bounded prepared file read required");
        governor.read(count, cancellation);
        if (!path.equals(readPath) || offset != readStart + readBytes) { releaseRead(); readPath = path; readStart = offset; }
        readBytes += count;
        if (readBytes >= CACHE_WINDOW) releaseRead();
    }
    private void releaseRead() {
        if (readPath != null && readBytes > 0) release(readPath, readStart, readBytes);
        readPath = null; readStart = 0; readBytes = 0;
    }
    String statusHint() { return statusHint; }
    synchronized void recordFinal() { releaseRead(); sampledAt = 0; pressure(); diagnostics.checkpoint(); }
    synchronized void onTrimMemory(int level) {
        trimLevel = level; trimAtEpochMs = System.currentTimeMillis(); trimAtNanos = System.nanoTime();
        if (trimPressure(level) > 0) { pressureTrimLevel = level; pressureTrimAtNanos = trimAtNanos; }
        sampledAt = 0;
    }
    synchronized int recentTrimPressure() {
        return pressureTrimAtNanos != 0 && System.nanoTime() - pressureTrimAtNanos <= TRIM_WINDOW_NANOS ? trimPressure(pressureTrimLevel) : 0;
    }
    /** Trim constants are not a monotonically ordered foreground-pressure scale. */
    @SuppressWarnings("deprecation") // Android 13 still emits these foreground pressure signals.
    static int trimPressure(int level) {
        switch (level) {
            case ComponentCallbacks2.TRIM_MEMORY_RUNNING_MODERATE:
            case ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW:
            case ComponentCallbacks2.TRIM_MEMORY_BACKGROUND:
            case ComponentCallbacks2.TRIM_MEMORY_MODERATE: return 1;
            case ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL:
            case ComponentCallbacks2.TRIM_MEMORY_COMPLETE: return 2;
            default: return 0; // UI_HIDDEN (20) says nothing about memory pressure.
        }
    }
    static int pressureLevel(long available, long threshold, boolean low, long heapUsed, long heapLimit, int trim) {
        if (low || (available >= 0 && available <= Math.max(threshold, 128L << 20))
                || (heapLimit > 0 && heapUsed >= heapLimit - heapLimit / 10)) return 2;
        if ((available >= 0 && available < Math.max(threshold + (256L << 20), 384L << 20))
                || (heapLimit > 0 && heapUsed >= heapLimit - heapLimit / 4)) return Math.max(1, trim);
        return trim;
    }
    /** A trim callback can outlive the system shortage. Preparation keeps useful
     * completed work running slowly when a fresh system/heap sample is healthy. */
    static int preparationPressureLevel(long available, long threshold, boolean low, long heapUsed, long heapLimit, int trim) {
        boolean healthy = !low && available >= Math.max(threshold + (512L << 20), 768L << 20)
                && heapLimit > 0 && heapUsed < heapLimit - heapLimit / 4;
        return pressureLevel(available, threshold, low, heapUsed, heapLimit, healthy ? Math.min(trim, 1) : trim);
    }
    private synchronized int pressure() {
        long now = System.nanoTime();
        if (sampledAt != 0 && now - sampledAt < SAMPLE_INTERVAL_NANOS) return pressure;
        sampledAt = now;
        long available = -1, threshold = 0;
        boolean low = false;
        try {
            if (manager != null) {
                ActivityManager.MemoryInfo sample = new ActivityManager.MemoryInfo();
                manager.getMemoryInfo(sample); available = sample.availMem; threshold = sample.threshold; low = sample.lowMemory;
            }
        } catch (RuntimeException unavailable) { /* Preserve pacing and trim checks. */ }
        Runtime vm = Runtime.getRuntime();
        int recentTrim = recentTrimPressure();
        int previousPressure = pressure;
        long heapUsed = vm.totalMemory() - vm.freeMemory(), heapLimit = vm.maxMemory();
        pressure = preparation ? preparationPressureLevel(available, threshold, low, heapUsed, heapLimit, recentTrim)
                : pressureLevel(available, threshold, low, heapUsed, heapLimit, recentTrim);
        statusHint = pressure == 2 ? "Waiting for Android memory to recover. Stop remains available."
                : pressure == 1 ? "Android memory is low; "+operationLabel.toLowerCase(java.util.Locale.ROOT)+" is limited to 2 MiB/s."
                : operationLabel+" verification/copy limit is "+(normalBytesPerSecond >> 20)+" MiB/s.";
        diagnostics.memory();
        diagnostics.io("ioPressureLevel", pressure);
        diagnostics.io("ioActiveBytesPerSecond", pressure == 2 ? 0 : pressure == 1 ? PRESSURE_BYTES_PER_SECOND : normalBytesPerSecond);
        diagnostics.io("ioMemoryAvailableBytes", available);
        diagnostics.io("ioMemoryThresholdBytes", threshold);
        diagnostics.io("ioMemoryLow", Boolean.toString(low));
        diagnostics.io("ioMemorySampleAtEpochMs", System.currentTimeMillis());
        diagnostics.io("ioTrimLevel", trimLevel);
        diagnostics.io("ioTrimAtEpochMs", trimAtEpochMs);
        diagnostics.io("ioCacheDropCalls", cacheCalls);
        diagnostics.io("ioCacheDropBytes", cacheBytes);
        diagnostics.io("ioCacheDropErrors", cacheErrors);
        diagnostics.io("ioCacheDropErrno", lastCacheErrno);
        diagnostics.io("ioCacheDropStatus", lastCacheErrno == 0 ? "advisory-supported-or-not-yet-needed" : "unavailable-pacing-and-sync-retained");
        sampleKernelWrites();
        if (pressure != previousPressure) diagnostics.checkpoint();
        return pressure;
    }
    private void sampleKernelWrites() {
        try (BufferedReader input = new BufferedReader(new FileReader("/proc/meminfo"), 2048)) {
            for (int i = 0; i < 128; i++) {
                String line = input.readLine(); if (line == null) break;
                if (line.startsWith("Dirty:")) {
                    long value = valueKiB(line); peakDirty = Math.max(peakDirty, value);
                    diagnostics.io("ioSystemDirtyKiB", value); diagnostics.io("ioSystemDirtyPeakKiB", peakDirty);
                } else if (line.startsWith("Writeback:")) {
                    long value = valueKiB(line); peakWriteback = Math.max(peakWriteback, value);
                    diagnostics.io("ioSystemWritebackKiB", value); diagnostics.io("ioSystemWritebackPeakKiB", peakWriteback);
                }
            }
        } catch (IOException | RuntimeException unavailable) { /* Optional system counters, not app attribution. */ }
    }
    private static long valueKiB(String line) {
        long result = 0; boolean digits = false;
        for (int i = line.indexOf(':') + 1; i < line.length(); i++) {
            char c = line.charAt(i);
            if (c >= '0' && c <= '9') { digits = true; result = result * 10 + c - '0'; }
            else if (digits) break;
        }
        return result;
    }
    private void release(Path output, long offset, long length) {
        try (ParcelFileDescriptor descriptor = ParcelFileDescriptor.open(output.toFile(), ParcelFileDescriptor.MODE_READ_ONLY)) {
            advise(descriptor.getFd(), offset, length);
        } catch (IOException | RuntimeException unavailable) { synchronized (this) { lastCacheErrno = -1; cacheErrors++; } }
    }
    private synchronized void advise(int fd, long offset, long length) {
        if (length <= 0) return;
        cacheCalls++;
        int result = NativeImportCache.drop(fd, offset, length);
        lastCacheErrno = result;
        if (result == 0) cacheBytes += length;
        else cacheErrors++;
    }
    SourceCache sourceCache(ParcelFileDescriptor descriptor, long startOffset) {
        try {
            if (!OsConstants.S_ISREG(Os.fstat(descriptor.getFileDescriptor()).st_mode)) return null;
            return new SourceCache(descriptor.getFd(), Math.max(0, startOffset));
        } catch (android.system.ErrnoException | RuntimeException unavailable) { return null; }
    }
    final class SourceCache {
        private final int fd;
        private long offset, pending;
        private boolean closed;
        SourceCache(int fd, long offset) { this.fd = fd; this.offset = offset; }
        synchronized void consumed(int bytes) { if (!closed && bytes > 0) { pending += bytes; if (pending >= CACHE_WINDOW) release(); } }
        synchronized void release() { if (!closed && pending > 0) { advise(fd, offset, pending); offset += pending; pending = 0; } }
        synchronized void finish() { if (!closed) { release(); closed = true; } }
    }
}
