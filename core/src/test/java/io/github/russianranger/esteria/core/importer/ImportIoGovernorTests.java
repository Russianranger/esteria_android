package io.github.russianranger.esteria.core.importer;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Method;
import java.nio.ByteBuffer;
import java.nio.MappedByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.ReadableByteChannel;
import java.nio.channels.WritableByteChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;

/** Deterministic rate/pressure tests plus actual folder/ZIP transaction and resume checks. */
public final class ImportIoGovernorTests {
    private static final long MIB = 1L << 20;
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static final class Time implements ImportIoGovernor.NanoClock, ImportIoGovernor.Sleeper {
        long now, largestSleep, slept; int sleeps; Runnable duringSleep;
        public long now() { return now; }
        public void sleep(long nanos) {
            check(nanos > 0 && nanos <= 100_000_000L, "Waits remain bounded to 100ms");
            now += nanos; slept += nanos; largestSleep = Math.max(largestSleep, nanos); sleeps++;
            if (duringSleep != null) duringSleep.run();
        }
    }
    private static ImportIoGovernor governor(Time time, AtomicInteger pressure, ImportIoGovernor.Relief relief) {
        return new ImportIoGovernor(8 * MIB, 2 * MIB, pressure::get, relief, time, time);
    }
    private static void ratesAndSharedFiles() throws Exception {
        Time time = new Time(); AtomicInteger pressure = new AtomicInteger();
        ImportIoGovernor io = governor(time, pressure, (p, o, n) -> { });
        io.read(8 * MIB, GameDataImporter.NEVER_CANCELLED);
        check(time.now == 1_000_000_000L, "Normal transfer is capped at8MiB/s");
        pressure.set(1); io.read(2 * MIB, GameDataImporter.NEVER_CANCELLED);
        check(time.now == 2_000_000_000L, "Pressure transfer is capped at2MiB/s");
        pressure.set(0);
        try (TrackingChannel channel = new TrackingChannel()) {
            for (int file = 0; file < 2; file++) {
                ImportIoGovernor.Transfer transfer = io.begin(Path.of("file" + file), channel, 0, GameDataImporter.NEVER_CANCELLED);
                transfer.wrote(MIB); transfer.finish();
            }
        }
        check(time.now == 2_250_000_000L, "Pacing covers small sequential files, not just large-file loops");
        // A slow provider does not accumulate tokens that allow a later output burst.
        time.now += 9_000_000_000L; long before = time.now;
        io.read(MIB, GameDataImporter.NEVER_CANCELLED);
        check(time.now - before == 125_000_000L, "Provider delays cannot buy an unbounded later burst");
        System.out.println("PASS shared8/2MiB rates and bounded waits across files");
    }
    private static void severePressureAndCancellation() throws Exception {
        Time time = new Time(); AtomicInteger pressure = new AtomicInteger(2);
        ImportIoGovernor io = governor(time, pressure, (p, o, n) -> { });
        time.duringSleep = () -> { if (time.now >= 500_000_000L) pressure.set(0); };
        io.checkpoint(GameDataImporter.NEVER_CANCELLED);
        check(time.now == 500_000_000L, "Severe pressure waits until recovery");
        AtomicBoolean cancel = new AtomicBoolean();
        time.duringSleep = () -> cancel.set(true); long before = time.now;
        try { io.read(8 * MIB, cancel::get); throw new AssertionError("Pacing ignored cancellation"); }
        catch (GameDataImporter.ImportCancelledException expected) { check(time.now - before <= 100_000_000L, "Pacing cancellation within100ms"); }
        cancel.set(false); pressure.set(2); time.duringSleep = () -> cancel.set(true); before = time.now;
        try { io.checkpoint(cancel::get); throw new AssertionError("Pressure wait ignored cancellation"); }
        catch (GameDataImporter.ImportCancelledException expected) { check(time.now - before <= 100_000_000L, "Pressure cancellation within100ms"); }
        time.duringSleep = null; before = time.now;
        try { io.checkpoint(GameDataImporter.NEVER_CANCELLED); throw new AssertionError("Sustained severe pressure did not pause"); }
        catch (GameDataImporter.ImportMemoryPressureException expected) {
            check(time.now - before == 60_000_000_000L, "Sustained pressure pauses after60seconds");
            check(expected.getMessage().equals("Import paused because Android still reports low memory; completed files are retained. Retry the same source after memory recovers."),
                    "Memory pause remains distinct from user cancellation with recovery instructions");
        }
        Thread.currentThread().interrupt();
        try { io.checkpoint(GameDataImporter.NEVER_CANCELLED); throw new AssertionError("Thread interrupt ignored"); }
        catch (GameDataImporter.ImportCancelledException expected) { check(Thread.currentThread().isInterrupted(), "Interrupt flag preserved"); }
        finally { Thread.interrupted(); }
        System.out.println("PASS pressure recovery, bounded pause, cancellation and interrupt");
    }
    private static void flushOrderAndRanges() throws Exception {
        Time time = new Time(); AtomicInteger pressure = new AtomicInteger();
        List<String> events = new ArrayList<>();
        try (TrackingChannel channel = new TrackingChannel()) {
            ImportIoGovernor io = governor(time, pressure, (path, offset, length) -> {
                check(channel.forces > events.size(), "Every release follows a new successful force");
                events.add(offset + ":" + length);
            });
            ImportIoGovernor.Transfer transfer = io.begin(Path.of("partial"), channel, MIB, GameDataImporter.NEVER_CANCELLED);
            for (int i = 0; i < 40; i++) transfer.wrote(128 << 10);
            transfer.finish();
            check(events.equals(List.of(MIB + ":" + 2 * MIB, 3 * MIB + ":" + 2 * MIB, 5 * MIB + ":" + MIB)), "Only written resumed windows are released exactly once");
            check(channel.metadata.equals(List.of(false, false, true)), "Periodic data sync and final durable metadata sync retained");
        }
        try (TrackingChannel failed = new TrackingChannel()) {
            failed.fail = true; AtomicBoolean relieved = new AtomicBoolean();
            ImportIoGovernor io = governor(time, pressure, (p, o, n) -> relieved.set(true));
            try { io.begin(Path.of("bad"), failed, 0, GameDataImporter.NEVER_CANCELLED).wrote(2 * MIB); throw new AssertionError("Force failure ignored"); }
            catch (IOException expected) { check(!relieved.get(), "Failed sync never releases dirty output"); }
        }
        System.out.println("PASS2MiB force-before-release windows, resumed offsets, final tail and force failure");
    }
    private static void resumePrefixPacing() throws Exception {
        Time time = new Time(); AtomicInteger pressure = new AtomicInteger();
        ImportIoGovernor io = governor(time, pressure, (p, o, n) -> { });
        InputStream pipe = new InputStream() {
            public long skip(long count) { return 0; }
            public int read() { throw new AssertionError("Bulk discard required"); }
            public int read(byte[] b, int offset, int length) { Arrays.fill(b, offset, offset + length, (byte) 7); return length; }
        };
        SourceStreamPositioner.advance(pipe, 2 * MIB, GameDataImporter.NEVER_CANCELLED, io);
        check(time.now == 250_000_000L, "Nonseekable resume discarded bytes are paced");
        SourceStreamPositioner.advance(new ByteArrayInputStream(new byte[1 << 20]), MIB, GameDataImporter.NEVER_CANCELLED, io);
        check(time.now == 375_000_000L, "Provider skip bytes cannot bypass the governor");
        pressure.set(2); AtomicBoolean cancel = new AtomicBoolean(); time.duringSleep = () -> cancel.set(true);
        InputStream untouched = new InputStream() {
            public long skip(long n) { throw new AssertionError("Severe pressure must be checked before consuming a prefix"); }
            public int read() { throw new AssertionError("Severe pressure must be checked before reading a prefix"); }
        };
        try { SourceStreamPositioner.advance(untouched, MIB, cancel::get, io); throw new AssertionError("Severe-prefix wait ignored cancellation"); }
        catch (GameDataImporter.ImportCancelledException expected) { check(cancel.get(), "Prefix waits before touching the provider"); }
        System.out.println("PASS bounded prefix discard and relative skip remain paced");
    }
    private static Object fixture(String name, Class<?>[] signature, Object... args) throws Exception {
        Method method = ImporterTests.class.getDeclaredMethod(name, signature); method.setAccessible(true); return method.invoke(null, args);
    }
    private static byte[] sha(Path file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256"); byte[] buffer = new byte[32 << 10];
        try (InputStream input = Files.newInputStream(file)) { for (int n; (n = input.read(buffer)) != -1;) digest.update(buffer, 0, n); }
        return digest.digest();
    }
    private static void actualRoutesAndResume() throws Exception {
        Path root = Files.createTempDirectory("esteria-governor-").toRealPath();
        try {
            Path source = (Path) fixture("client", new Class<?>[]{Path.class}, root);
            Path payload = source.resolve("Data/z-streamed.bin");
            byte[] block = new byte[128 << 10]; new java.util.Random(9876).nextBytes(block);
            try (var out = Files.newOutputStream(payload)) { for (int i = 0; i < 40; i++) out.write(block); }
            Path zip = (Path) fixture("zipTree", new Class<?>[]{Path.class, Path.class}, root, source);
            for (String route : List.of("folder", "zip")) {
                AtomicBoolean cancelled = new AtomicBoolean(); AtomicInteger pressure = new AtomicInteger(); Time time = new Time();
                List<long[]> windows = new ArrayList<>();
                ImportIoGovernor io = governor(time, pressure, (path, offset, length) -> {
                    check(Files.size(path) >= offset + length, "Released output range exists on disk"); windows.add(new long[]{offset, length});
                    if (length >= 2 * MIB) cancelled.set(true);
                });
                Path store = root.resolve(route + "-store"); GameDataImporter importer = new GameDataImporter(store, io);
                try { run(route, importer, source, zip, cancelled::get); throw new AssertionError("Actual route ignored cancellation"); }
                catch (GameDataImporter.ImportCancelledException expected) { check(importer.resolveCurrent() == null, "Interrupted generation never promoted"); }
                check(windows.stream().anyMatch(w -> w[1] == 2 * MIB), "Actual route flushes beforeEOF");
                cancelled.set(false); windows.clear();
                ImportIoGovernor resumedIo = governor(time, pressure, (path, offset, length) -> windows.add(new long[]{offset, length}));
                importer = new GameDataImporter(store, resumedIo);
                GameDataImporter.Result result = run(route, importer, source, zip, GameDataImporter.NEVER_CANCELLED);
                check(result.reusedFiles > 0 && result.copiedFiles > 0, "Completed files resume and interrupted file recopies");
                check(Arrays.equals(sha(payload), sha(result.gameDirectory.resolve("Data/z-streamed.bin"))), "Actual route payload hash remains exact");
                check(windows.stream().filter(w -> w[1] >= MIB).count() == 3, "Actual5MiB file flushes2+2+1MiB");
                GameDataImporter.Result repeated = run(route, new GameDataImporter(store), source, zip, GameDataImporter.NEVER_CANCELLED);
                check(repeated.generation.equals(result.generation) && repeated.copiedFiles == 0, "Governed imports preserve legacy source fingerprints and resume generation");
                System.out.println("PASS actual " + route + " checkpoint cancellation/resume SHA exact generation=" + result.generation);
            }
        } finally {
            try (var paths = Files.walk(root)) { for (Path p : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.deleteIfExists(p); }
        }
    }
    private static GameDataImporter.Result run(String route, GameDataImporter importer, Path source, Path zip, GameDataImporter.Cancellation cancellation) throws IOException {
        return route.equals("folder") ? importer.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, cancellation)
                : importer.importZip(zip, GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, cancellation);
    }
    private static final class TrackingChannel extends FileChannel {
        int forces; boolean fail; final List<Boolean> metadata = new ArrayList<>();
        public void force(boolean metadata) throws IOException { if (fail) throw new IOException("Injected sync failure"); forces++; this.metadata.add(metadata); }
        protected void implCloseChannel() { }
        public int read(ByteBuffer dst) { throw new UnsupportedOperationException(); }
        public long read(ByteBuffer[] dst, int offset, int length) { throw new UnsupportedOperationException(); }
        public int write(ByteBuffer src) { throw new UnsupportedOperationException(); }
        public long write(ByteBuffer[] src, int offset, int length) { throw new UnsupportedOperationException(); }
        public long position() { throw new UnsupportedOperationException(); }
        public FileChannel position(long p) { throw new UnsupportedOperationException(); }
        public long size() { throw new UnsupportedOperationException(); }
        public FileChannel truncate(long size) { throw new UnsupportedOperationException(); }
        public long transferTo(long p, long count, WritableByteChannel target) { throw new UnsupportedOperationException(); }
        public long transferFrom(ReadableByteChannel src, long p, long count) { throw new UnsupportedOperationException(); }
        public int read(ByteBuffer dst, long p) { throw new UnsupportedOperationException(); }
        public int write(ByteBuffer src, long p) { throw new UnsupportedOperationException(); }
        public MappedByteBuffer map(MapMode mode, long p, long size) { throw new UnsupportedOperationException(); }
        public FileLock lock(long p, long size, boolean shared) { throw new UnsupportedOperationException(); }
        public FileLock tryLock(long p, long size, boolean shared) { throw new UnsupportedOperationException(); }
    }
    public static void main(String[] args) throws Exception {
        ratesAndSharedFiles(); severePressureAndCancellation(); flushOrderAndRanges(); resumePrefixPacing(); actualRoutesAndResume();
        System.out.println("Import I/O governor tests passed; generated host fixtures do not establish the owner's Android kill cause");
    }
}
