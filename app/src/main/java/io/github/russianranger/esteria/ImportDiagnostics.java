package io.github.russianranger.esteria;

import io.github.russianranger.esteria.core.diagnostics.SupportBundle;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/** Small app-owned receipt for the last import, including failures before a generation exists. */
final class ImportDiagnostics implements ImportIoController.Diagnostics {
    private static final int MAX_BYTES = 32 * 1024;
    private static final Set<String> KEYS = Set.of("route", "kind", "sourceProvider", "sourceIdentitySha256",
            "selectedRoot", "detectedRoot", "phase", "path", "result", "failure", "startedAtEpochMs",
            "javaHeapUsedBytes", "javaHeapPeakObservedBytes", "javaHeapLimitBytes", "memorySampleAtEpochMs",
            "ioPolicy", "ioNormalBytesPerSecond", "ioPressureBytesPerSecond", "ioPressureLevel", "ioActiveBytesPerSecond",
            "ioMemoryAvailableBytes", "ioMemoryThresholdBytes", "ioMemoryLow", "ioMemorySampleAtEpochMs",
            "ioTrimLevel", "ioTrimAtEpochMs", "ioCacheDropCalls", "ioCacheDropBytes", "ioCacheDropErrno",
            "ioCacheDropStatus", "ioCacheDropErrors", "ioSystemDirtyKiB", "ioSystemWritebackKiB",
            "ioSystemDirtyPeakKiB", "ioSystemWritebackPeakKiB");
    private final Path receipt;
    private final Map<String, String> values = new LinkedHashMap<>();
    private long savedAt;
    private long memorySampleAt, heapPeak;

    ImportDiagnostics(Path receipt) {
        this.receipt = receipt;
        try {
            if (!Files.isRegularFile(receipt, LinkOption.NOFOLLOW_LINKS) || Files.size(receipt) > MAX_BYTES) return;
            Properties retained = new Properties();
            retained.load(new ByteArrayInputStream(Files.readAllBytes(receipt)));
            for (String key : KEYS) if (retained.containsKey(key)) values.put(key, bounded(retained.getProperty(key), key.equals("failure") ? 8192 : 2048));
        } catch (IOException | RuntimeException unavailable) { values.clear(); }
    }

    synchronized void begin(String route, String kind, String provider, String sourceIdentity, String selectedRoot) {
        values.clear(); values.put("route", bounded(route, 32)); values.put("kind", bounded(kind, 32));
        values.put("sourceProvider", bounded(provider, 256));
        // Document IDs and URIs can contain user information and are opaque; never interpret or retain them as paths.
        values.put("sourceIdentitySha256", fingerprint(sourceIdentity));
        values.put("selectedRoot", bounded(selectedRoot, 2048)); values.put("detectedRoot", "not-yet-detected");
        values.put("phase", "source-selection"); values.put("result", "running");
        values.put("startedAtEpochMs", Long.toString(System.currentTimeMillis()));
        memorySampleAt = 0; heapPeak = 0; memory(); save();
    }

    synchronized void phase(String phase, String detectedRoot, String path) {
        boolean rootChanged = !detectedRoot.equals(values.get("detectedRoot"));
        boolean changed = !phase.equals(values.get("phase"));
        values.put("phase", bounded(phase, 128)); values.put("detectedRoot", bounded(detectedRoot, 2048));
        values.put("path", bounded(path, 2048));
        // Keep progress in memory for concurrent support export, without a disk write for every file/chunk.
        if (rootChanged || (changed && path.isEmpty()) || System.nanoTime() - savedAt > 2_000_000_000L) save();
    }

    synchronized void phase(String phase) { phase(phase, values.getOrDefault("detectedRoot", "not-yet-detected"), ""); }
    public synchronized void io(String key, long value) { io(key, Long.toString(value)); }
    public synchronized void io(String key, String value) {
        if (!KEYS.contains(key) || !key.startsWith("io")) throw new IllegalArgumentException("Unknown bounded import I/O fact");
        values.put(key, bounded(value, 256));
        if (savedAt != 0 && System.nanoTime() - savedAt > 2_000_000_000L) save();
    }
    public synchronized void checkpoint() { save(); }
    synchronized void selectedRoot(String name) {
        String bounded = bounded(name, 2048);
        if (!bounded.equals(values.get("selectedRoot"))) { values.put("selectedRoot", bounded); save(); }
    }
    synchronized void finish(String result, Throwable failure) {
        values.put("result", bounded(result, 32));
        if (failure != null) values.put("failure", failure(failure));
        save();
    }
    public synchronized void memory() {
        long now = System.nanoTime();
        if (memorySampleAt != 0 && now - memorySampleAt < 1_000_000_000L) return;
        memorySampleAt = now;
        Runtime runtime = Runtime.getRuntime();
        long used = runtime.totalMemory() - runtime.freeMemory();
        heapPeak = Math.max(heapPeak, used);
        values.put("javaHeapUsedBytes", Long.toString(used));
        values.put("javaHeapPeakObservedBytes", Long.toString(heapPeak));
        values.put("javaHeapLimitBytes", Long.toString(runtime.maxMemory()));
        values.put("memorySampleAtEpochMs", Long.toString(System.currentTimeMillis()));
        // Cheap VM counters only, at most once per second; no PSS/asset/process scan.
        if (savedAt != 0 && now - savedAt > 2_000_000_000L) save();
    }
    synchronized Map<String, String> facts() {
        Map<String, String> facts = new LinkedHashMap<>();
        for (Map.Entry<String, String> entry : values.entrySet()) facts.put("import.last." + entry.getKey(), entry.getValue());
        return facts;
    }
    synchronized String context() { return values.toString(); }

    /** Full cause/suppressed traversal, bounded even for cycles and pathological provider exceptions. */
    static String failure(Throwable failure) {
        StringBuilder output = new StringBuilder();
        Set<Throwable> seen = Collections.newSetFromMap(new IdentityHashMap<>());
        describe(output, failure, "failure", seen, 0);
        return SupportBundle.redact(bounded(output.toString(), 8192));
    }
    private static void describe(StringBuilder out, Throwable error, String relation, Set<Throwable> seen, int depth) {
        if (error == null || out.length() >= 8192) return;
        if (depth > 12 || seen.size() >= 24) { out.append("\n[exception chain truncated]"); return; }
        if (!seen.add(error)) { out.append("\n[exception cycle]"); return; }
        out.append('\n').append(relation).append('=').append(error.getClass().getName()).append(": ").append(bounded(error.getMessage(), 2048));
        StackTraceElement[] trace = error.getStackTrace();
        for (int i = 0; i < Math.min(16, trace.length) && out.length() < 8192; i++) out.append("\n at ").append(trace[i]);
        for (Throwable suppressed : error.getSuppressed()) describe(out, suppressed, "suppressed", seen, depth + 1);
        describe(out, error.getCause(), "caused-by", seen, depth + 1);
    }
    private void save() {
        try {
            Properties props = new Properties(); props.putAll(values);
            ByteArrayOutputStream bytes = new ByteArrayOutputStream(); props.store(bytes, "Last bounded import diagnostic; no document URI or client bytes");
            if (bytes.size() > MAX_BYTES) return;
            Files.createDirectories(receipt.getParent());
            Path temporary = receipt.resolveSibling(receipt.getFileName() + ".tmp");
            Files.write(temporary, bytes.toByteArray());
            Files.move(temporary, receipt, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            savedAt = System.nanoTime();
        } catch (IOException | RuntimeException unavailable) { /* Diagnostics cannot invalidate an otherwise valid import. */ }
    }
    private static String bounded(String value, int maximum) {
        if (value == null) return "";
        return value.length() <= maximum ? value : value.substring(0, maximum) + "[truncated]";
    }
    private static String fingerprint(String value) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder text = new StringBuilder();
            for (byte b : digest) text.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
            return text.toString();
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }
}
