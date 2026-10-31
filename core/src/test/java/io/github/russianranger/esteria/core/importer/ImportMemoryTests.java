package io.github.russianranger.esteria.core.importer;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.lang.management.ManagementFactory;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Host allocation/streaming regression. Synthetic headers are not owner assets or game execution. */
public final class ImportMemoryTests {
    private static final long MIB = 1L << 20;
    private static final String LARGE = "Data/streamed-memory-fixture.bin";
    private ImportMemoryTests() { }

    public static void main(String[] args) throws Exception {
        metadataBudgetCounts();
        com.sun.management.ThreadMXBean allocation = allocatedBytes();
        // Warm cryptography, NIO and importer metadata before comparing logical payload sizes.
        measure(8 * MIB, allocation);
        measure(8 * MIB, allocation);
        Measurement small = measure(64 * MIB, allocation);
        Measurement large = measure(256 * MIB, allocation);
        System.out.println("streaming-small bytes=" + small.bytes + " reads=" + small.reads + " allocatedBytes=" + small.allocated);
        System.out.println("streaming-large bytes=" + large.bytes + " reads=" + large.reads + " allocatedBytes=" + large.allocated);
        check(small.reads >= 64 * 1024 && large.reads >= 256 * 1024, "provider short reads must exercise the copy loop");
        if (allocation != null) {
            long growth = large.allocated - small.allocated;
            System.out.println("streaming-allocation-growth bytes=" + growth + " addedPayloadBytes=" + (large.bytes - small.bytes));
            // Both imports retain the same tiny metadata set and one copy buffer.
            // Additional payload must not allocate an object for each 1 KiB read.
            check(growth < MIB, "streaming payload grew per-thread allocations by " + growth + " bytes; expected below 1 MiB");
        } else System.out.println("SKIP allocation-counter assertion: JVM does not expose thread allocations; low-heap streaming still executed");
        folderZipStreaming();
        System.out.println("Import memory tests passed: 64/256 MiB short-read imports and equivalent 128 MiB public folder/ZIP imports; no asset-sized buffers");
    }

    private static void metadataBudgetCounts() throws Exception {
        String[][] cases = {
                {"Data/patch-Z.MPQ/file.bin", "opaque:tree/../../token"},
                {"Data/安装/资源.bin", "provider:漢字"},
                {"Data/emoji🙂/file.bin", "id🙂"},
                {"Data/\ud800/\udc00.bin", "opaque\ud800:\udc00"},
                {"a".repeat(1024), "b".repeat(4096)},
                {"🙂".repeat(256), "é".repeat(2048)}
        };
        for (String[] names : cases) for (boolean directory : new boolean[]{false, true}) {
            GameDataImporter.MetadataBudget budget = new GameDataImporter.MetadataBudget();
            budget.add(names[0], names[1], directory);
            long expected = (directory ? 512L : 1024L) + names[0].getBytes(StandardCharsets.UTF_8).length * 8L + names[1].getBytes(StandardCharsets.UTF_8).length * 6L;
            for (int slash = names[0].indexOf('/'); slash >= 0; slash = names[0].indexOf('/', slash + 1))
                expected += 256L + names[0].substring(0, slash).getBytes(StandardCharsets.UTF_8).length * 8L;
            check(budget.estimatedBytes() == expected, "UTF-8 metadata charge changed: " + budget.estimatedBytes() + " != " + expected);
        }
        rejectsMetadata("a".repeat(1025), "id");
        rejectsMetadata("汉".repeat(342), "id");
        rejectsMetadata("🙂".repeat(257), "id");
        rejectsMetadata("file", "x".repeat(4097));
        rejectsMetadata("file", "é".repeat(2049));
        // Java's UTF-8 encoder replaces isolated surrogates with one '?' byte.
        GameDataImporter.MetadataBudget replacement = new GameDataImporter.MetadataBudget();
        replacement.add("\ud800".repeat(1024), "\udc00".repeat(4096), false);
        check(replacement.estimatedBytes() == 1024L + 1024L * 8 + 4096L * 6, "isolated surrogate replacement length");
        System.out.println("PASS metadata budget matches exact UTF-8 byte formula and byte caps without changing admission");
    }
    private static void rejectsMetadata(String path, String id) throws Exception {
        try { new GameDataImporter.MetadataBudget().add(path, id, false); }
        catch (IOException expected) { return; }
        throw new AssertionError("Oversized metadata accepted");
    }

    private static Measurement measure(long bytes, com.sun.management.ThreadMXBean allocation) throws Exception {
        Path root = Files.createTempDirectory("esteria-import-memory-").toRealPath();
        try {
            SyntheticSource source = new SyntheticSource(bytes);
            GameDataImporter importer = new GameDataImporter(root.resolve("store"));
            long before = allocation == null ? -1 : allocation.getThreadAllocatedBytes(Thread.currentThread().getId());
            GameDataImporter.Result imported = importer.importSource(source, GameDataImporter.ImportKind.BASE_CLIENT,
                    GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
            long used = allocation == null ? -1 : allocation.getThreadAllocatedBytes(Thread.currentThread().getId()) - before;
            check(Files.size(imported.gameDirectory.resolve(LARGE)) == bytes, "all declared streamed bytes must be committed");
            check(importer.resolveCurrent().equals(imported.gameDirectory), "only complete import activates");
            check(source.opened == source.closed && source.finalChecks == 1, "source streams close and final identity check runs");
            return new Measurement(bytes, source.largeReads, used);
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.deleteIfExists(path);
            }
        }
    }

    private static void folderZipStreaming() throws Exception {
        Path root = Files.createTempDirectory("esteria-import-route-memory-").toRealPath();
        try {
            long size = 128 * MIB;
            SyntheticSource fixture = new SyntheticSource(size);
            Path source = root.resolve("source");
            Map<String, Long> sourceTimes = new LinkedHashMap<>();
            for (GameDataImporter.InputEntry entry : fixture.entries) {
                Path file = source.resolve(entry.relativePath); Files.createDirectories(file.getParent());
                byte[] small = fixture.small.get(entry.id);
                if (small != null) Files.write(file, small);
                else try (RandomAccessFile sparse = new RandomAccessFile(file.toFile(), "rw")) { sparse.setLength(size); }
                sourceTimes.put(entry.relativePath, Files.getLastModifiedTime(file).toMillis());
            }
            Fingerprint expected = fingerprint(source.resolve(LARGE));
            Path archive = root.resolve("complete-client.zip");
            byte[] copy = new byte[128 * 1024];
            try (ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(archive)); java.util.stream.Stream<Path> paths = Files.walk(source)) {
                for (Path file : (Iterable<Path>) paths.filter(Files::isRegularFile).sorted()::iterator) {
                    output.putNextEntry(new ZipEntry(source.relativize(file).toString().replace('\\', '/')));
                    try (InputStream input = Files.newInputStream(file)) {
                        for (int count; (count = input.read(copy)) != -1;) output.write(copy, 0, count);
                    }
                    output.closeEntry();
                }
            }
            GameDataImporter folderImporter = new GameDataImporter(root.resolve("folder-store"));
            GameDataImporter zipImporter = new GameDataImporter(root.resolve("zip-store"));
            GameDataImporter.Result folder = folderImporter.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT,
                    GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
            GameDataImporter.Result zip = zipImporter.importZip(archive, GameDataImporter.ImportKind.BASE_CLIENT,
                    GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
            for (GameDataImporter.Result result : List.of(folder, zip)) {
                Path payload = result.gameDirectory.resolve(LARGE);
                check(Files.size(payload) == size && result.copiedBytes >= size, "public route streamed every declared payload byte");
                check(expected.equals(fingerprint(payload)), "folder and ZIP payload SHA-256/CRC must match source");
            }
            check(folderImporter.resolveCurrent().equals(folder.gameDirectory) && zipImporter.resolveCurrent().equals(zip.gameDirectory), "both routes activate complete generations");
            check(expected.equals(fingerprint(source.resolve(LARGE))), "source payload is unchanged");
            for (GameDataImporter.InputEntry entry : fixture.entries) {
                Path file = source.resolve(entry.relativePath);
                check(Files.getLastModifiedTime(file).toMillis() == sourceTimes.get(entry.relativePath), "source modification time changed");
                byte[] small = fixture.small.get(entry.id);
                if (small != null) {
                    check(Arrays.equals(small, Files.readAllBytes(file)), "source header fixture changed");
                    check(Arrays.equals(small, Files.readAllBytes(folder.gameDirectory.resolve(entry.relativePath))) &&
                            Arrays.equals(small, Files.readAllBytes(zip.gameDirectory.resolve(entry.relativePath))), "public route header fixture differs");
                }
            }
            System.out.println("PASS public folder/ZIP streaming bytes=" + size + " compressedZipBytes=" + Files.size(archive) +
                    " sha256=" + java.util.HexFormat.of().formatHex(expected.sha256) + " crc32=" + expected.crc32 + "; original client bytes/mtimes preserved");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.deleteIfExists(path);
            }
        }
    }
    private static Fingerprint fingerprint(Path file) throws Exception {
        MessageDigest sha256 = MessageDigest.getInstance("SHA-256"); CRC32 crc32 = new CRC32(); byte[] bytes = new byte[128 * 1024];
        try (InputStream input = Files.newInputStream(file)) {
            for (int count; (count = input.read(bytes)) != -1;) { sha256.update(bytes, 0, count); crc32.update(bytes, 0, count); }
        }
        return new Fingerprint(sha256.digest(), crc32.getValue());
    }
    private static final class Fingerprint {
        final byte[] sha256; final long crc32;
        Fingerprint(byte[] sha256, long crc32) { this.sha256 = sha256; this.crc32 = crc32; }
        @Override public boolean equals(Object other) { return other instanceof Fingerprint && crc32 == ((Fingerprint) other).crc32 && Arrays.equals(sha256, ((Fingerprint) other).sha256); }
        @Override public int hashCode() { return Arrays.hashCode(sha256) * 31 + Long.hashCode(crc32); }
    }

    private static com.sun.management.ThreadMXBean allocatedBytes() {
        java.lang.management.ThreadMXBean bean = ManagementFactory.getThreadMXBean();
        if (!(bean instanceof com.sun.management.ThreadMXBean)) return null;
        com.sun.management.ThreadMXBean counter = (com.sun.management.ThreadMXBean) bean;
        if (!counter.isThreadAllocatedMemorySupported()) return null;
        if (!counter.isThreadAllocatedMemoryEnabled()) counter.setThreadAllocatedMemoryEnabled(true);
        return counter;
    }
    private static void check(boolean value, String message) { if (!value) throw new AssertionError(message); }
    private static byte[] fixture(String method, Class<?>[] types, Object... args) throws Exception {
        Method fixture = ImporterTests.class.getDeclaredMethod(method, types); fixture.setAccessible(true);
        return (byte[]) fixture.invoke(null, args);
    }
    private static final class Measurement {
        final long bytes, reads, allocated;
        Measurement(long bytes, long reads, long allocated) { this.bytes = bytes; this.reads = reads; this.allocated = allocated; }
    }
    private static final class SyntheticSource implements GameDataImporter.InputSource {
        final List<GameDataImporter.InputEntry> entries = new ArrayList<>();
        final Map<String, byte[]> small = new LinkedHashMap<>();
        final long bytes; int opened, closed, finalChecks; long largeReads;
        SyntheticSource(long bytes) throws Exception {
            this.bytes = bytes;
            put("Wow.exe", fixture("pe", new Class<?>[]{int.class}, 12340));
            byte[] archive = fixture("mpq", new Class<?>[0]);
            for (String name : List.of("common", "common-2", "expansion", "lichking", "patch", "patch-2", "patch-3")) put("Data/" + name + ".MPQ", archive);
            put("Data/enUS/locale-enUS.MPQ", archive); put("Data/enUS/speech-enUS.MPQ", archive);
            entries.add(new GameDataImporter.InputEntry("opaque:large/../../unchanged", LARGE, bytes, 1234));
        }
        private void put(String path, byte[] data) {
            String id = "opaque:" + entries.size(); entries.add(new GameDataImporter.InputEntry(id, path, data.length, 1234)); small.put(id, data);
        }
        public String identity() { return "host-short-read-source:" + bytes; }
        public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation) { return entries; }
        public InputStream open(GameDataImporter.InputEntry entry) throws IOException {
            opened++;
            byte[] content = small.get(entry.id);
            if (content != null) return new ByteArrayInputStream(content) { @Override public void close() { closed++; } };
            if (!entry.relativePath.equals(LARGE) || entry.size != bytes) throw new IOException("Unknown fixture source token");
            return new InputStream() {
                long remaining = bytes;
                @Override public int read(byte[] target, int offset, int length) {
                    if (length == 0) return 0;
                    if (remaining == 0) return -1;
                    int count = (int) Math.min(remaining, Math.min(length, 1024));
                    Arrays.fill(target, offset, offset + count, (byte) 0); remaining -= count; largeReads++; return count;
                }
                @Override public int read() { if (remaining == 0) return -1; remaining--; return 0; }
                @Override public void close() { closed++; }
            };
        }
        public void verifyUnchanged(GameDataImporter.InputEntry entry) throws IOException {
            if (!entries.contains(entry)) throw new IOException("Source mapping changed");
        }
        public void verifySnapshot(List<GameDataImporter.InputEntry> snapshot) throws IOException {
            finalChecks++;
            if (snapshot.size() != entries.size() || !snapshot.containsAll(entries)) throw new IOException("Source snapshot changed");
        }
    }
}
