package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.InputStream;
import java.io.ByteArrayInputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Dependency-free host behavior tests. Synthetic headers are not gameplay assets. */
public final class ImporterTests {
    private static int passed;
    public static void main(String[] args) throws Exception {
        run("PE version resource validates exact build", ImporterTests::versionResources);
        run("MPQ signature and table bounds", ImporterTests::mpqBounds);
        run("folder import and repeat skips copied bytes", ImporterTests::folderCommit);
        run("cancel resumes completed files without publication", ImporterTests::resume);
        run("partial journal record and changed staged file recover", ImporterTests::journalRecovery);
        run("failed overlay preserves current generation", ImporterTests::overlayRollback);
        run("successful overlay preserves base and old bytes", ImporterTests::overlaySuccess);
        run("ZIP wrapper extraction and resume", ImporterTests::zipWrapper);
        run("ZIP64 directory accepted without loading asset into memory", ImporterTests::zip64);
        run("ZIP traversal and case collisions rejected", ImporterTests::zipPaths);
        run("ZIP CRC corruption and truncation rejected", ImporterTests::zipCorruption);
        run("ZIP Unix symlink rejected", ImporterTests::zipSymlink);
        run("folder symlink and source mutation rejected", ImporterTests::folderSafety);
        run("archive declared-size limits enforced", ImporterTests::sizeLimits);
        run("concurrent importer cannot publish over active work", ImporterTests::concurrency);
        run("64 MiB asset streams with a 32 MiB test heap", ImporterTests::boundedStreaming);
        run("document source streams once and maps wrapped paths", ImporterTests::documentSource);
        run("document cancellation resumes known identities", ImporterTests::documentResume);
        run("document metadata changes reject publication", ImporterTests::documentMutation);
        run("document paths IDs sizes and unknown times are bounded", ImporterTests::documentValidation);
        run("incomplete client inventory fails before any asset is copied", ImporterTests::incompleteInventory);
        run("metadata budget stops long-name inventories before heap pressure", ImporterTests::metadataBudget);
        System.out.println("Importer tests passed: " + passed);
    }
    private interface Test { void run() throws Exception; }
    private static void run(String name, Test test) throws Exception { test.run(); passed++; System.out.println("PASS " + name); }
    private static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void fails(Test test, String reason) throws Exception { try { test.run(); } catch (IOException expected) { return; } throw new AssertionError("Expected IOException: " + reason); }
    private static Path temp() throws IOException { return Files.createTempDirectory("esteria-import-test-").toRealPath(); }
    private static void write(Path file, byte[] content) throws IOException { Files.createDirectories(file.getParent()); Files.write(file, content); }
    private static GameDataImporter importer(Path root) throws IOException { return new GameDataImporter(root.resolve("store")); }
    private static GameDataImporter.Result folder(GameDataImporter importer, Path path, GameDataImporter.ImportKind kind) throws IOException {
        return importer.importFolder(path, kind, GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
    }
    private static GameDataImporter.Result zip(GameDataImporter importer, Path path) throws IOException {
        return importer.importZip(path, GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
    }
    private static Path client(Path root) throws IOException {
        Path client = root.resolve("source"); write(client.resolve("Wow.exe"), pe(12340));
        for (String name : new String[]{"common", "common-2", "expansion", "lichking", "patch", "patch-2", "patch-3"}) write(client.resolve("Data/" + name + ".MPQ"), mpq());
        write(client.resolve("Data/enUS/locale-enUS.MPQ"), mpq());
        write(client.resolve("Interface/AddOns/MyAddon/config.txt"), "old config".getBytes(StandardCharsets.UTF_8));
        return client;
    }
    private static byte[] pe(int build) {
        ByteBuffer b = ByteBuffer.allocate(1024).order(ByteOrder.LITTLE_ENDIAN);
        b.putShort(0, (short) 0x5a4d); b.putInt(0x3c, 0x80); b.putInt(0x80, 0x4550);
        b.putShort(0x84, (short) 0x14c); b.putShort(0x86, (short) 1); b.putShort(0x94, (short) 224);
        int optional = 0x98; b.putShort(optional, (short) 0x10b); b.putInt(optional + 92, 16);
        b.putInt(optional + 112, 0x1000); b.putInt(optional + 116, 512);
        int section = optional + 224; b.putInt(section + 8, 512); b.putInt(section + 12, 0x1000); b.putInt(section + 16, 512); b.putInt(section + 20, 512);
        int res = 512;
        b.putShort(res + 14, (short) 1); b.putInt(res + 16, 16); b.putInt(res + 20, 0x80000020);
        b.putShort(res + 32 + 14, (short) 1); b.putInt(res + 32 + 16, 1); b.putInt(res + 32 + 20, 0x80000040);
        b.putShort(res + 64 + 14, (short) 1); b.putInt(res + 64 + 16, 1033); b.putInt(res + 64 + 20, 96);
        b.putInt(res + 96, 0x1080); b.putInt(res + 100, 92);
        int data = res + 128; b.putShort(data, (short) 92); b.putShort(data + 2, (short) 52);
        String key = "VS_VERSION_INFO"; for (int i = 0; i < key.length(); i++) b.putChar(data + 6 + i * 2, key.charAt(i));
        b.putInt(data + 40, 0xfeef04bd); b.putInt(data + 44, 0x10000); b.putInt(data + 48, 0x30003); b.putInt(data + 52, (5 << 16) | build);
        return b.array();
    }
    private static byte[] mpq() {
        ByteBuffer b = ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0, 0x1a51504d); b.putInt(4, 32); b.putInt(8, 64); b.putShort(14, (short) 3);
        b.putInt(16, 32); b.putInt(20, 48); b.putInt(24, 1); b.putInt(28, 1); return b.array();
    }
    private static void versionResources() throws Exception {
        Path file = temp().resolve("Wow.exe"); Files.write(file, pe(12340)); GameDataVerifier.verifyWowVersion(file);
        Files.write(file, pe(12341)); fails(() -> GameDataVerifier.verifyWowVersion(file), "wrong build");
        byte[] loose = pe(12340); ByteBuffer.wrap(loose).order(ByteOrder.LITTLE_ENDIAN).putInt(512 + 16, 24);
        Files.write(file, loose); fails(() -> GameDataVerifier.verifyWowVersion(file), "version signature outside type16 resource");
        byte[] bad = pe(12340); ByteBuffer.wrap(bad).order(ByteOrder.LITTLE_ENDIAN).putInt(512 + 96, 0x9999);
        Files.write(file, bad); fails(() -> GameDataVerifier.verifyWowVersion(file), "out of bounds resource RVA");
    }
    private static void mpqBounds() throws Exception {
        Path file = temp().resolve("base.MPQ"); Files.write(file, mpq()); GameDataVerifier.verifyMpq(file);
        Files.write(file, Arrays.copyOf(mpq(), 40)); fails(() -> GameDataVerifier.verifyMpq(file), "truncated table");
        byte[] bad = mpq(); ByteBuffer.wrap(bad).order(ByteOrder.LITTLE_ENDIAN).putInt(24, 3);
        Files.write(file, bad); fails(() -> GameDataVerifier.verifyMpq(file), "non power of two hash count");
        ByteBuffer wrapper = ByteBuffer.allocate(80).order(ByteOrder.LITTLE_ENDIAN);
        wrapper.putInt(0, 0x1b51504d).putInt(8, 16).putInt(12, 16); wrapper.position(16); wrapper.put(mpq());
        Files.write(file, wrapper.array()); GameDataVerifier.verifyMpq(file);
        wrapper.putInt(8, 1000); Files.write(file, wrapper.array()); fails(() -> GameDataVerifier.verifyMpq(file), "userdata offset bounds");
        // Format1 counts are decoded lengths; table extents can be compressed. These
        // synthetic bytes qualify only header/extent handling, never table decoding.
        ByteBuffer v1 = ByteBuffer.allocate(68).order(ByteOrder.LITTLE_ENDIAN);
        v1.putInt(0, 0x1a51504d).putInt(4, 44).putInt(8, 0).putShort(12, (short) 1).putShort(14, (short) 3);
        v1.putInt(16, 44).putInt(20, 56).putInt(24, 1).putInt(28, 1);
        Files.write(file, v1.array()); GameDataVerifier.verifyMpq(file);
        // A high-block table may not point into the hash table.
        v1.putLong(32, 48); Files.write(file, v1.array());
        fails(() -> GameDataVerifier.verifyMpq(file), "extended table overlaps hash");
        v1.putLong(32, 0).putInt(20, 43); Files.write(file, v1.array());
        fails(() -> GameDataVerifier.verifyMpq(file), "reversed v1 table ordering");
    }
    private static void folderCommit() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root);
        GameDataImporter.Result result = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT);
        check(result.copiedFiles == 10 && result.reusedFiles == 0, "all initial files copied");
        check(im.resolveCurrent().equals(result.gameDirectory), "active data points at validated generation");
        GameDataImporter.Result repeat = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT);
        check(repeat.copiedBytes == 0 && repeat.reusedFiles == 10 && repeat.generation.equals(result.generation), "repeat avoids hashing/copying");
    }
    private static void resume() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root); AtomicBoolean cancel = new AtomicBoolean();
        fails(() -> im.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> { if (n == 3) cancel.set(true); }, cancel::get), "cancel");
        check(im.resolveCurrent() == null, "interrupted first import must not publish");
        GameDataImporter.Result result = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT);
        check(result.reusedFiles == 3 && result.copiedFiles == 7, "resume only copies remaining files");
    }
    private static void overlayRollback() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root);
        Path old = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT).gameDirectory;
        Path overlay = root.resolve("overlay"); write(overlay.resolve("Data/patch-3.MPQ"), new byte[]{1,2,3});
        fails(() -> folder(im, overlay, GameDataImporter.ImportKind.CONTENT_OVERLAY), "bad patch MPQ");
        check(im.resolveCurrent().equals(old), "failed update must keep old pointer");
        check(Arrays.equals(Files.readAllBytes(old.resolve("Data/patch-3.MPQ")), mpq()), "old archive is unchanged");
    }
    private static void journalRecovery() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root); AtomicBoolean cancel = new AtomicBoolean();
        fails(() -> im.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> { if (n == 3) cancel.set(true); }, cancel::get), "cancel");
        Path generation;
        try (java.util.stream.Stream<Path> dirs = Files.list(root.resolve("store/generations"))) { generation = dirs.findFirst().orElseThrow(AssertionError::new); }
        Files.write(generation.resolve("journal.tsv"), "unfinished-record".getBytes(StandardCharsets.UTF_8), java.nio.file.StandardOpenOption.APPEND);
        Path changed = generation.resolve("data/Data/common-2.MPQ");
        Files.write(changed, new byte[]{1,2,3});
        GameDataImporter.Result result = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT);
        check(result.reusedFiles == 2 && result.copiedFiles == 8, "partial journal and staged size mismatch must be recopied safely");
        check(Arrays.equals(Files.readAllBytes(result.gameDirectory.resolve("Data/common-2.MPQ")), mpq()), "recopied archive restored");
    }
    private static void overlaySuccess() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root);
        Path old = folder(im, source, GameDataImporter.ImportKind.BASE_CLIENT).gameDirectory;
        Path overlay = root.resolve("overlay"); write(overlay.resolve("interface/addons/myaddon/config.txt"), "new config".getBytes(StandardCharsets.UTF_8));
        Path next = folder(im, overlay, GameDataImporter.ImportKind.CONTENT_OVERLAY).gameDirectory;
        check(!next.equals(old), "new generation after overlay");
        check(new String(Files.readAllBytes(old.resolve("Interface/AddOns/MyAddon/config.txt")), StandardCharsets.UTF_8).equals("old config"), "hardlinks not mutated in place");
        check(new String(Files.readAllBytes(next.resolve("Interface/AddOns/MyAddon/config.txt")), StandardCharsets.UTF_8).equals("new config"), "case-matched overlay replaced file");
        GameDataImporter.Result repeat = folder(im, overlay, GameDataImporter.ImportKind.CONTENT_OVERLAY);
        check(repeat.gameDirectory.equals(next) && repeat.copiedBytes == 0, "repeated same overlay avoids another generation");
    }
    private static void zipWrapper() throws Exception {
        Path root = temp(), source = client(root), archive = root.resolve("client.zip");
        try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(archive)); java.util.stream.Stream<Path> paths = Files.walk(source)) {
            for (Path file : (Iterable<Path>) paths.filter(Files::isRegularFile)::iterator) {
                zip.putNextEntry(new ZipEntry("WoW335/" + source.relativize(file).toString().replace('\\', '/'))); Files.copy(file, zip); zip.closeEntry();
            }
        }
        GameDataImporter.Result result = zip(importer(root), archive); check(result.copiedFiles == 10, "single wrapper removed");
        check(Files.exists(result.gameDirectory.resolve("Wow.exe")), "client is at generation root");
    }
    private static Path zipEntries(Path root, String[] names, byte[][] data) throws Exception {
        Path file = root.resolve("inputs-" + System.nanoTime() + ".zip");
        try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(file))) {
            for (int i = 0; i < names.length; i++) {
                CRC32 crc = new CRC32(); crc.update(data[i]); ZipEntry entry = new ZipEntry(names[i]);
                entry.setMethod(ZipEntry.STORED); entry.setSize(data[i].length); entry.setCompressedSize(data[i].length); entry.setCrc(crc.getValue());
                zip.putNextEntry(entry); zip.write(data[i]); zip.closeEntry();
            }
        }
        return file;
    }
    private static void zip64() throws Exception {
        Path root = temp(), source = client(root), archive = root.resolve("zip64.zip");
        List<String> names = new ArrayList<>(); List<byte[]> content = new ArrayList<>();
        try (java.util.stream.Stream<Path> paths = Files.walk(source)) {
            for (Path file : (Iterable<Path>) paths.filter(Files::isRegularFile)::iterator) { names.add(source.relativize(file).toString().replace('\\', '/')); content.add(Files.readAllBytes(file)); }
        }
        byte[] original = Files.readAllBytes(zipEntries(root, names.toArray(new String[0]), content.toArray(new byte[0][])));
        ByteBuffer input = ByteBuffer.wrap(original).order(ByteOrder.LITTLE_ENDIAN);
        int end = original.length - 22, count = Short.toUnsignedInt(input.getShort(end + 10));
        long centralSize = Integer.toUnsignedLong(input.getInt(end + 12)), centralOffset = Integer.toUnsignedLong(input.getInt(end + 16));
        ByteBuffer output = ByteBuffer.allocate(original.length + 76).order(ByteOrder.LITTLE_ENDIAN); output.put(original, 0, end);
        output.putInt(0x06064b50).putLong(44).putShort((short)45).putShort((short)45).putInt(0).putInt(0).putLong(count).putLong(count).putLong(centralSize).putLong(centralOffset);
        output.putInt(0x07064b50).putInt(0).putLong(end).putInt(1);
        output.putInt(0x06054b50).putShort((short)0).putShort((short)0).putShort((short)0xffff).putShort((short)0xffff).putInt(-1).putInt(-1).putShort((short)0);
        Files.write(archive, output.array());
        check(zip(importer(root), archive).copiedFiles == 10, "ZIP64 end metadata accepted");
    }
    private static void zipPaths() throws Exception {
        for (String name : new String[]{"../escape", "/absolute", "C:/escape", "dir\\escape", "dir/../escape", "dir//file"}) {
            Path root = temp(), archive = zipEntries(root, new String[]{name}, new byte[][]{new byte[]{1}});
            fails(() -> zip(importer(root), archive), name);
        }
        Path root = temp(), archive = zipEntries(root, new String[]{"Data/x", "data/X"}, new byte[][]{new byte[0], new byte[0]});
        fails(() -> zip(importer(root), archive), "case duplicate");
        Path dirs = zipEntries(root, new String[]{"Data/x", "data/y"}, new byte[][]{new byte[0], new byte[0]});
        fails(() -> zip(importer(root), dirs), "case directory ambiguity");
        Path collision = zipEntries(root, new String[]{"Data", "Data/x"}, new byte[][]{new byte[0], new byte[0]});
        fails(() -> zip(importer(root), collision), "file parent collision");
    }
    private static void zipCorruption() throws Exception {
        Path root = temp(), source = client(root);
        List<String> names = new ArrayList<>(); List<byte[]> content = new ArrayList<>();
        try (java.util.stream.Stream<Path> paths = Files.walk(source)) {
            for (Path file : (Iterable<Path>) paths.filter(Files::isRegularFile)::iterator) { names.add(source.relativize(file).toString().replace('\\', '/')); content.add(Files.readAllBytes(file)); }
        }
        Path archive = zipEntries(root, names.toArray(new String[0]), content.toArray(new byte[0][]));
        byte[] bytes = Files.readAllBytes(archive); ByteBuffer header = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        int payload = 30 + Short.toUnsignedInt(header.getShort(26)) + Short.toUnsignedInt(header.getShort(28));
        bytes[payload] ^= 0x7f; Files.write(archive, bytes);
        try { zip(importer(root), archive); throw new AssertionError("CRC corruption accepted"); }
        catch (IOException expected) { check(expected.getMessage().contains("Truncated or corrupt source"), "CRC must be checked after valid inventory: " + expected.getMessage()); }
        Files.write(archive, Arrays.copyOf(bytes, bytes.length - 12)); fails(() -> zip(importer(root), archive), "truncated directory");
    }
    private static void zipSymlink() throws Exception {
        Path root = temp(), archive = zipEntries(root, new String[]{"link"}, new byte[][]{"../../outside".getBytes(StandardCharsets.UTF_8)});
        byte[] bytes = Files.readAllBytes(archive); ByteBuffer b = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        for (int at = 0; at <= bytes.length - 46; at++) if (b.getInt(at) == 0x02014b50) { b.putShort(at + 4, (short) 0x0314); b.putInt(at + 38, 0120777 << 16); break; }
        Files.write(archive, bytes); fails(() -> zip(importer(root), archive), "Unix symlink");
    }
    private static void folderSafety() throws Exception {
        Path root = temp(), source = client(root); Files.createSymbolicLink(source.resolve("link"), root.resolve("outside"));
        fails(() -> folder(importer(root), source, GameDataImporter.ImportKind.BASE_CLIENT), "source symlink");
        Files.delete(source.resolve("link")); AtomicBoolean changed = new AtomicBoolean();
        fails(() -> importer(root).importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> {
            if (p.equals("Data/common-2.MPQ") && changed.compareAndSet(false, true)) try { Files.setLastModifiedTime(source.resolve(p), FileTime.fromMillis(System.currentTimeMillis() + 10000)); } catch (IOException e) { throw new RuntimeException(e); }
        }, GameDataImporter.NEVER_CANCELLED), "source mtime changed during copy");
    }
    private static void sizeLimits() throws Exception {
        Path root = temp(), archive = zipEntries(root, new String[]{"huge"}, new byte[][]{new byte[64]});
        GameDataImporter im = new GameDataImporter(root.resolve("store"), new GameDataImporter.Limits(10, 32, 128));
        fails(() -> zip(im, archive), "per-file bound");
    }
    private static void concurrency() throws Exception {
        Path root = temp(), source = client(root); GameDataImporter im = importer(root); AtomicBoolean checked = new AtomicBoolean();
        im.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> {
            if (checked.compareAndSet(false, true)) try {
                try { folder(importer(root), source, GameDataImporter.ImportKind.BASE_CLIENT); throw new AssertionError("concurrent import accepted"); }
                catch (IOException expected) { }
            } catch (Exception e) { throw new RuntimeException(e); }
        }, GameDataImporter.NEVER_CANCELLED);
        check(checked.get(), "lock tested while first import active");
    }
    private static void boundedStreaming() throws Exception {
        Path root = temp(), source = client(root), large = source.resolve("Data/streaming-fixture.bin");
        try {
            try (java.io.RandomAccessFile file = new java.io.RandomAccessFile(large.toFile(), "rw")) { file.setLength(64L * 1024 * 1024); }
            GameDataImporter.Result result = folder(importer(root), source, GameDataImporter.ImportKind.BASE_CLIENT);
            check(Files.size(result.gameDirectory.resolve("Data/streaming-fixture.bin")) == 64L * 1024 * 1024, "large file copied without whole-file allocation");
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>) paths.sorted(java.util.Comparator.reverseOrder())::iterator) Files.deleteIfExists(path);
            }
        }
    }
    private static final class Documents implements GameDataImporter.InputSource {
        final List<GameDataImporter.InputEntry> entries = new ArrayList<>();
        final Map<String, byte[]> bytes = new LinkedHashMap<>();
        final Map<String, Long> modified = new LinkedHashMap<>();
        int snapshots, opened, closed, finalChecks;
        boolean changedRoot, truncateStreams;
        public String identity() { return "content://test-provider/tree/client"; }
        public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation) { snapshots++; return entries; }
        public InputStream open(GameDataImporter.InputEntry entry) {
            opened++;
            byte[] contents = bytes.get(entry.id);
            return new ByteArrayInputStream(contents, 0, truncateStreams ? Math.max(0, contents.length - 1) : contents.length) {
                @Override public void close() throws IOException { closed++; super.close(); }
            };
        }
        public void verifyUnchanged(GameDataImporter.InputEntry entry) throws IOException {
            byte[] data = bytes.get(entry.id);
            if (data == null || data.length != entry.size || modified.get(entry.id) != entry.modifiedMillis) throw new IOException("Document changed");
        }
        public void verifySnapshot(List<GameDataImporter.InputEntry> snapshot) throws IOException {
            finalChecks++; if (changedRoot) throw new IOException("Document root changed");
            try { snapshot.clear(); throw new AssertionError("snapshot must be immutable"); } catch (UnsupportedOperationException expected) { }
        }
        void put(String id, String path, byte[] data, long time) {
            entries.add(new GameDataImporter.InputEntry(id, path, data.length, time)); bytes.put(id, data); modified.put(id, time);
        }
    }
    private static Documents documents(Path root, String prefix, long time) throws Exception {
        Path source = client(root); Documents docs = new Documents();
        try (java.util.stream.Stream<Path> paths = Files.walk(source)) {
            for (Path file : (Iterable<Path>) paths.filter(Files::isRegularFile)::iterator) {
                String relative = source.relativize(file).toString().replace('\\', '/');
                docs.put("document:" + relative, prefix + relative, Files.readAllBytes(file), time);
            }
        }
        return docs;
    }
    private static GameDataImporter.Result documentImport(GameDataImporter importer, Documents documents) throws IOException {
        return importer.importSource(documents, GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
    }
    private static void documentSource() throws Exception {
        Path root = temp(); Documents docs = documents(root, "SelectedClient/", 1234); GameDataImporter im = importer(root);
        GameDataImporter.Result result = documentImport(im, docs);
        check(docs.snapshots == 1 && docs.opened == 10 && docs.closed == 10 && docs.finalChecks == 1, "one inventory, bounded streams closed, final source check");
        check(Files.exists(result.gameDirectory.resolve("Wow.exe")), "wrapper stripped without altering source document mapping");
        GameDataImporter.Result repeated = documentImport(im, docs);
        check(repeated.copiedBytes == 0 && repeated.generation.equals(result.generation) && docs.opened == 10, "stable provider identities avoid rereading assets");
    }
    private static void documentResume() throws Exception {
        Path root = temp(); Documents docs = documents(root, "", 1234); GameDataImporter im = importer(root); AtomicBoolean cancelled = new AtomicBoolean();
        fails(() -> im.importSource(docs, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> { if (n == 4) cancelled.set(true); }, cancelled::get), "document cancellation");
        check(im.resolveCurrent() == null && docs.opened == docs.closed, "cancel closes streams and preserves pointer");
        GameDataImporter.Result result = documentImport(im, docs);
        check(result.reusedFiles == 4 && result.copiedFiles == 6 && docs.opened == 10, "document resume skips four finished files");
    }
    private static void documentMutation() throws Exception {
        Path root = temp(); Documents docs = documents(root, "", 1234); GameDataImporter im = importer(root); AtomicBoolean changed = new AtomicBoolean();
        fails(() -> im.importSource(docs, GameDataImporter.ImportKind.BASE_CLIENT, (p,b,t,n,f) -> {
            if (changed.compareAndSet(false, true)) {
                String id = "document:" + p; byte[] replacement = docs.bytes.get(id).clone(); replacement[0] ^= 1;
                docs.bytes.put(id, replacement); docs.modified.put(id, 5678L);
            }
        }, GameDataImporter.NEVER_CANCELLED), "metadata changed during document read");
        check(im.resolveCurrent() == null, "changed provider source never publishes");
        Path other = temp(); Documents moved = documents(other, "", 1234); moved.changedRoot = true;
        fails(() -> documentImport(importer(other), moved), "changed provider root");
        Path truncatedRoot = temp(); Documents truncated = documents(truncatedRoot, "", 1234); truncated.truncateStreams = true;
        fails(() -> documentImport(importer(truncatedRoot), truncated), "provider stream shorter than reported document size");
    }
    private static void documentValidation() throws Exception {
        Path root = temp(); Documents docs = documents(root, "", 0); GameDataImporter im = importer(root);
        GameDataImporter.Result first = documentImport(im, docs), second = documentImport(im, docs);
        check(!first.generation.equals(second.generation) && second.copiedFiles == 10, "unversioned documents never reuse old source assumptions");
        Documents duplicate = documents(temp(), "", 1234); GameDataImporter.InputEntry entry = duplicate.entries.get(0);
        duplicate.entries.add(new GameDataImporter.InputEntry(entry.id, "different", entry.size, entry.modifiedMillis));
        fails(() -> documentImport(importer(temp()), duplicate), "duplicate opaque IDs");
        Documents unknown = new Documents(); unknown.entries.add(new GameDataImporter.InputEntry("id", "Data/file", -1, 1234));
        fails(() -> documentImport(importer(temp()), unknown), "unknown document size");
        Documents unsafe = new Documents(); unsafe.put("id", "../escape", new byte[0], 1234);
        fails(() -> documentImport(importer(temp()), unsafe), "provider path traversal");
    }
    private static void incompleteInventory() throws Exception {
        Path root = temp(); Documents incomplete = documents(root, "", 1234);
        incomplete.entries.removeIf(entry -> entry.relativePath.equals("Data/lichking.MPQ"));
        GameDataImporter im = importer(root);
        fails(() -> documentImport(im, incomplete), "missing required archive caught by snapshot layout");
        check(incomplete.opened == 0 && im.resolveCurrent() == null, "no partial copy for a visibly incomplete client");
    }
    private static void metadataBudget() throws Exception {
        GameDataImporter.MetadataBudget budget = new GameDataImporter.MetadataBudget();
        StringBuilder longName = new StringBuilder(); for (int i = 0; i < 200; i++) longName.append('a');
        int accepted = 0;
        try {
            for (; accepted < 10_000; accepted++) budget.add("Data/" + longName + "/asset-" + accepted + ".bin", "provider:" + longName + accepted, false);
            throw new AssertionError("metadata budget was not enforced");
        } catch (IOException expected) {
            check(expected.getMessage().contains("memory budget") && accepted < 5000, "long names trigger a clear bounded inventory error");
            check(budget.estimatedBytes() <= GameDataImporter.MetadataBudget.DEFAULT_MAX_BYTES, "budget never overruns");
        }
        Path root = temp(), source = client(root);
        GameDataImporter.Limits small = new GameDataImporter.Limits(200_000, 32L << 30, 256L << 30, 8192);
        GameDataImporter folder = new GameDataImporter(root.resolve("small-folder"), small);
        try { folder(folder, source, GameDataImporter.ImportKind.BASE_CLIENT); throw new AssertionError("folder inventory budget ignored"); }
        catch (IOException expected) { check(expected.getMessage().contains("memory budget"), "folder rejects metadata before copying"); }
        Documents docs = documents(temp(), "", 1234);
        try { documentImport(new GameDataImporter(root.resolve("small-documents"), small), docs); throw new AssertionError("document inventory budget ignored"); }
        catch (IOException expected) { check(expected.getMessage().contains("memory budget") && docs.opened == 0, "provider metadata rejected before opening streams"); }
        Path archive = root.resolve("many-names.zip");
        try (ZipOutputStream zip = new ZipOutputStream(Files.newOutputStream(archive))) {
            for (int i = 0; i < 50; i++) { zip.putNextEntry(new ZipEntry("Data/" + longName + "/entry-" + i)); zip.closeEntry(); }
        }
        try { zip(new GameDataImporter(root.resolve("small-zip"), small), archive); throw new AssertionError("ZIP metadata budget ignored"); }
        catch (IOException expected) { check(expected.getMessage().contains("memory budget"), "central-directory budget rejects before ZipFile materialization"); }
    }
}
