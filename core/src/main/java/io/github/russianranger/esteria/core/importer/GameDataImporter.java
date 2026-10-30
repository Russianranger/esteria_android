package io.github.russianranger.esteria.core.importer;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Comparator;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.zip.CRC32;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * Transactional file-level resume. Game generations are immutable after publication;
 * runtime state (WTF, saves, databases, logs) belongs outside this store.
 * Memory use is one 128 KiB copy buffer plus a bounded manifest, never whole assets.
 */
public final class GameDataImporter {
    public enum ImportKind { BASE_CLIENT, CONTENT_OVERLAY }
    public interface ProgressListener { void onProgress(String path, long completedBytes, long totalBytes, int completedFiles, int totalFiles); }
    public interface Cancellation { boolean isCancelled(); }
    public static final Cancellation NEVER_CANCELLED = () -> false;
    public static final ProgressListener NO_PROGRESS = (p, b, t, n, f) -> {};
    public static final class ImportCancelledException extends IOException {
        private static final long serialVersionUID = 1L;
        public ImportCancelledException() { super("Import cancelled; completed files are retained for resume"); }
    }
    public static final class Result {
        public final Path gameDirectory;
        public final String generation;
        public final int copiedFiles, reusedFiles;
        public final long copiedBytes;
        Result(Path gameDirectory, String generation, int copiedFiles, int reusedFiles, long copiedBytes) {
            this.gameDirectory = gameDirectory; this.generation = generation; this.copiedFiles = copiedFiles; this.reusedFiles = reusedFiles; this.copiedBytes = copiedBytes;
        }
    }
    public static final class Limits {
        public final int maxFiles;
        public final long maxFileBytes, maxTotalBytes;
        public Limits(int maxFiles, long maxFileBytes, long maxTotalBytes) {
            if (maxFiles < 1 || maxFileBytes < 1 || maxTotalBytes < maxFileBytes) throw new IllegalArgumentException("Invalid import limits");
            this.maxFiles = maxFiles; this.maxFileBytes = maxFileBytes; this.maxTotalBytes = maxTotalBytes;
        }
        public static Limits defaults() { return new Limits(200_000, 32L << 30, 256L << 30); }
    }
    private final Path root;
    private final Limits limits;
    /** True when this filesystem accepted directory fsync; false means process-crash guarantees only. */
    public final boolean directorySyncSupported;

    public GameDataImporter(Path storeRoot) throws IOException { this(storeRoot, Limits.defaults()); }
    public GameDataImporter(Path storeRoot, Limits limits) throws IOException {
        this.root = storeRoot.toAbsolutePath().normalize(); this.limits = limits;
        Files.createDirectories(root);
        rejectSymlinkAncestors(root);
        Files.createDirectories(root.resolve("generations"));
        rejectSymlinkAncestors(root.resolve("generations"));
        directorySyncSupported = probeDirectorySync(root);
    }

    public Path resolveCurrent() throws IOException {
        String id = currentId();
        if (id == null) return null;
        Path data = root.resolve("generations").resolve(id).resolve("data");
        rejectSymlinkAncestors(data);
        if (!Files.isRegularFile(data.getParent().resolve("complete"), LinkOption.NOFOLLOW_LINKS) || !Files.isDirectory(data, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Active game generation is incomplete");
        return data;
    }

    public Result importFolder(Path folder, ImportKind kind, ProgressListener listener, Cancellation cancellation) throws IOException {
        Path source = folder.toAbsolutePath().normalize();
        if (root.startsWith(source) || source.startsWith(root)) throw new IOException("Source and destination must not contain each other");
        rejectSymlinkAncestors(source);
        try (ImportLock ignored = lock()) {
            FolderSource input = new FolderSource(source);
            return importSource(input, kind, listener, cancellation);
        }
    }

    public Result importZip(Path archive, ImportKind kind, ProgressListener listener, Cancellation cancellation) throws IOException {
        Path source = archive.toAbsolutePath().normalize();
        rejectSymlinkAncestors(source);
        try (ImportLock ignored = lock()) {
            ZipSafety.inspect(source, limits.maxFiles, cancellation);
            try (ZipSource input = new ZipSource(source)) { return importSource(input, kind, listener, cancellation); }
        }
    }

    private Result importSource(Source source, ImportKind kind, ProgressListener listener, Cancellation cancellation) throws IOException {
        if (kind == null || listener == null || cancellation == null) throw new IllegalArgumentException("Import arguments must not be null");
        checkCancelled(cancellation);
        List<Entry> entries = source.entries(cancellation);
        if (entries.isEmpty()) throw new IOException("No files to import");
        if (kind == ImportKind.BASE_CLIENT) stripClientWrapper(entries);
        validateEntries(entries);
        entries.sort(Comparator.comparing(e -> e.path));
        Path current = resolveCurrent();
        String base = kind == ImportKind.CONTENT_OVERLAY ? currentId() : "base";
        if (kind == ImportKind.CONTENT_OVERLAY && current == null) throw new IOException("Import a base client before custom content");
        MessageDigest identity = sha256();
        identity.update(("esteria-import-v1\n" + kind + "\n" + source.identity() + "\n").getBytes(StandardCharsets.UTF_8));
        for (Entry entry : entries) identity.update((entry.path + "\0" + entry.size + "\0" + entry.modified + "\0" + entry.crc + "\n").getBytes(StandardCharsets.UTF_8));
        String sourceId = hex(identity.digest());
        if (current != null && matchesCompletedSource(current.getParent().resolve("complete"), sourceId)) return new Result(current, currentId(), 0, entries.size(), 0);
        identity.update((sourceId + "\n" + base).getBytes(StandardCharsets.UTF_8));
        String id = hex(identity.digest());
        Path generation = root.resolve("generations").resolve(id), data = generation.resolve("data");
        if (id.equals(currentId())) return new Result(resolveCurrent(), id, 0, entries.size(), 0);
        createDirectoriesDurably(data);
        rejectSymlinkAncestors(data);
        syncDirectory(root.resolve("generations")); syncDirectory(generation);
        Path journal = generation.resolve("journal.tsv");
        Map<String, Saved> saved = readJournal(journal);
        if (kind == ImportKind.CONTENT_OVERLAY && !Files.exists(generation.resolve("base-ready"))) {
            seedBase(current, data, cancellation);
            atomicWrite(generation.resolve("base-ready"), base + "\n");
        }
        if (kind == ImportKind.CONTENT_OVERLAY) canonicalizeOverlayPaths(data, entries);
        long total = 0, remaining = 0;
        for (Entry entry : entries) { total += entry.size; if (!reusable(data, entry, saved.get(entry.path))) remaining += entry.size; }
        long reserve = 64L << 20;
        if (Files.getFileStore(root).getUsableSpace() < remaining + reserve) throw new IOException("Not enough free storage for staged import (needs " + (remaining + reserve) + " bytes)");
        long completed = 0, copiedBytes = 0;
        int copied = 0, reused = 0, finished = 0;
        byte[] buffer = new byte[128 * 1024];
        for (Entry entry : entries) {
            checkCancelled(cancellation);
            Path target = safeTarget(data, entry.path);
            if (reusable(data, entry, saved.get(entry.path))) {
                completed += entry.size; reused++; finished++;
                listener.onProgress(entry.path, completed, total, finished, entries.size());
                continue;
            }
            createDirectoriesDurably(target.getParent()); rejectSymlinkAncestors(target.getParent());
            Path partial = target.resolveSibling(target.getFileName() + ".esteria-part");
            if (Files.isSymbolicLink(partial) || Files.isSymbolicLink(target)) throw new IOException("Symlink in import destination");
            MessageDigest digest = sha256(); CRC32 crc = new CRC32(); long bytes = 0;
            try (InputStream input = source.open(entry); FileChannel output = FileChannel.open(partial, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE)) {
                int read;
                long reportAt = 0;
                while ((read = input.read(buffer)) != -1) {
                    checkCancelled(cancellation);
                    if (bytes > entry.size - read) throw new IOException("Source grew beyond declared length: " + entry.path);
                    ByteBuffer block = ByteBuffer.wrap(buffer, 0, read);
                    while (block.hasRemaining()) output.write(block);
                    digest.update(buffer, 0, read); crc.update(buffer, 0, read); bytes += read;
                    long now = System.nanoTime();
                    if (now - reportAt > 100_000_000L) { listener.onProgress(entry.path, completed + bytes, total, finished, entries.size()); reportAt = now; }
                }
                if (bytes != entry.size || (entry.crc >= 0 && crc.getValue() != entry.crc)) throw new IOException("Truncated or corrupt source: " + entry.path);
                output.force(true);
            } catch (IOException | RuntimeException failure) { Files.deleteIfExists(partial); throw failure; }
            source.verifyUnchanged(entry);
            GameDataVerifier.verifyKnownFile(partial, entry.path);
            Files.move(partial, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            syncDirectory(target.getParent());
            long modified = Files.getLastModifiedTime(target, LinkOption.NOFOLLOW_LINKS).toMillis();
            appendJournal(journal, entry.path, entry.size, modified, hex(digest.digest()));
            copied++; copiedBytes += bytes; completed += bytes; finished++;
            listener.onProgress(entry.path, completed, total, finished, entries.size());
        }
        checkCancelled(cancellation);
        source.verifyUnchanged(null);
        GameDataVerifier.verifyBaseClient(data);
        // No active pointer is changed until every file and the whole client satisfy the checks.
        atomicWrite(generation.resolve("complete"), "format=1\nclientBuild=12340\nrequest=" + id + "\nsource=" + sourceId + "\ndirectorySync=" + directorySyncSupported + "\ncontentCompatibility=unqualified\n");
        atomicWrite(root.resolve("current"), id + "\n");
        return new Result(data, id, copied, reused, copiedBytes);
    }

    private void seedBase(Path source, Path destination, Cancellation cancellation) throws IOException {
        Files.walkFileTree(source, new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path dir, BasicFileAttributes attributes) throws IOException {
                checkCancelled(cancellation); if (attributes.isSymbolicLink()) throw new IOException("Symlink in active data");
                Path target = destination.resolve(source.relativize(dir)); createDirectoriesDurably(target); rejectSymlinkAncestors(target); return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attributes) throws IOException {
                checkCancelled(cancellation); if (!attributes.isRegularFile() || attributes.isSymbolicLink()) throw new IOException("Nonregular active data");
                Path target = destination.resolve(source.relativize(file));
                if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) {
                    if (!Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS) || Files.size(target) != attributes.size()) throw new IOException("Invalid resumed base file");
                    return FileVisitResult.CONTINUE;
                }
                try { Files.createLink(target, file); }
                catch (UnsupportedOperationException | IOException noLinks) {
                    Path partial = target.resolveSibling(target.getFileName() + ".esteria-seed");
                    if (Files.isSymbolicLink(partial)) throw new IOException("Symlink seed destination");
                    try {
                        try (InputStream input = Files.newInputStream(file); FileChannel output = FileChannel.open(partial, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE)) {
                            byte[] buffer = new byte[128 * 1024]; int read;
                            while ((read = input.read(buffer)) != -1) {
                                checkCancelled(cancellation);
                                ByteBuffer block = ByteBuffer.wrap(buffer, 0, read); while (block.hasRemaining()) output.write(block);
                            }
                            output.force(true);
                        }
                        Files.move(partial, target, StandardCopyOption.ATOMIC_MOVE);
                    } finally { Files.deleteIfExists(partial); }
                }
                syncDirectory(target.getParent());
                return FileVisitResult.CONTINUE;
            }
        });
    }

    private void canonicalizeOverlayPaths(Path data, List<Entry> entries) throws IOException {
        Map<String, String> names = new HashMap<>();
        try (java.util.stream.Stream<Path> paths = Files.walk(data)) {
            for (Path path : (Iterable<Path>) paths::iterator) {
                String relative = data.relativize(path).toString().replace('\\', '/');
                names.put(relative.toLowerCase(Locale.ROOT), relative);
                if (names.size() > limits.maxFiles * 2L) throw new IOException("Combined content manifest is too large");
            }
        }
        for (Entry entry : entries) {
            String canonical = names.get(entry.path.toLowerCase(Locale.ROOT));
            if (canonical != null) { if (Files.isDirectory(data.resolve(canonical))) throw new IOException("Overlay file conflicts with directory"); entry.path = canonical; continue; }
            int slash = entry.path.lastIndexOf('/');
            while (slash > 0) {
                String prefix = entry.path.substring(0, slash), existing = names.get(prefix.toLowerCase(Locale.ROOT));
                if (existing != null) {
                    if (!Files.isDirectory(data.resolve(existing))) throw new IOException("Overlay directory conflicts with file");
                    entry.path = existing + entry.path.substring(slash); break;
                }
                slash = entry.path.lastIndexOf('/', slash - 1);
            }
        }
    }

    private void validateEntries(List<Entry> entries) throws IOException {
        if (entries.size() > limits.maxFiles) throw new IOException("Too many import files");
        Map<String, Boolean> paths = new HashMap<>(); Map<String, String> spelling = new HashMap<>(); long total = 0;
        for (Entry entry : entries) {
            entry.path = validatePath(entry.path);
            if (entry.path.toLowerCase(Locale.ROOT).endsWith(".esteria-part") || entry.path.toLowerCase(Locale.ROOT).endsWith(".esteria-seed")) throw new IOException("Reserved staging filename");
            if (entry.size < 0 || entry.size > limits.maxFileBytes || entry.size > limits.maxTotalBytes - total) throw new IOException("Import size limit exceeded");
            total += entry.size;
            String key = entry.path.toLowerCase(Locale.ROOT);
            if (paths.containsKey(key)) throw new IOException("Duplicate or conflicting path: " + entry.path);
            paths.put(key, true);
            int slash = key.lastIndexOf('/');
            while (slash > 0) {
                String parent = key.substring(0, slash);
                if (Boolean.TRUE.equals(paths.get(parent))) throw new IOException("File/directory collision: " + entry.path);
                String actual = entry.path.substring(0, slash), previous = spelling.putIfAbsent(parent, actual);
                if (previous != null && !previous.equals(actual)) throw new IOException("Conflicting directory capitalization: " + entry.path);
                paths.put(parent, false); slash = parent.lastIndexOf('/');
            }
            if (paths.size() > limits.maxFiles * 2L) throw new IOException("Import directory manifest is too large");
        }
    }

    private static void stripClientWrapper(List<Entry> entries) {
        if (entries.stream().anyMatch(e -> e.path.equalsIgnoreCase("Wow.exe"))) return;
        String prefix = null;
        for (Entry entry : entries) if (entry.path.toLowerCase(Locale.ROOT).endsWith("/wow.exe")) {
            String candidate = entry.path.substring(0, entry.path.length() - 7);
            if (entries.stream().allMatch(e -> e.path.startsWith(candidate))) { prefix = candidate; break; }
        }
        if (prefix != null) for (Entry entry : entries) entry.path = entry.path.substring(prefix.length());
    }

    static String validatePath(String path) throws IOException {
        if (path.isEmpty() || path.getBytes(StandardCharsets.UTF_8).length > 1024 || path.startsWith("/") || path.indexOf('\\') >= 0 || path.indexOf(':') >= 0) throw new IOException("Unsafe import path: " + path);
        for (int i = 0; i < path.length(); i++) if (path.charAt(i) < 32 || path.charAt(i) == 127) throw new IOException("Control character in import path");
        String[] components = path.split("/", -1);
        if (components.length > 32) throw new IOException("Import path is too deeply nested");
        for (String component : components) if (component.isEmpty() || component.equals(".") || component.equals("..") || component.endsWith(".") || component.endsWith(" ")) throw new IOException("Unsafe import path: " + path);
        return path;
    }
    private static Path safeTarget(Path base, String path) throws IOException {
        Path target = base.resolve(validatePath(path)).normalize();
        if (!target.startsWith(base)) throw new IOException("Import path escapes destination"); return target;
    }
    private static void rejectSymlinkAncestors(Path path) throws IOException {
        for (Path at = path; at != null; at = at.getParent()) if (Files.isSymbolicLink(at)) throw new IOException("Symlink path is not permitted: " + at);
    }
    private static boolean reusable(Path data, Entry entry, Saved saved) throws IOException {
        if (saved == null || saved.size != entry.size) return false;
        Path target = safeTarget(data, entry.path);
        if (!Files.isRegularFile(target, LinkOption.NOFOLLOW_LINKS)) return false;
        return Files.size(target) == saved.size && Files.getLastModifiedTime(target, LinkOption.NOFOLLOW_LINKS).toMillis() == saved.modified;
    }
    private static void checkCancelled(Cancellation cancellation) throws ImportCancelledException { if (cancellation.isCancelled() || Thread.currentThread().isInterrupted()) throw new ImportCancelledException(); }
    private String currentId() throws IOException {
        Path pointer = root.resolve("current");
        if (!Files.exists(pointer, LinkOption.NOFOLLOW_LINKS)) return null;
        if (!Files.isRegularFile(pointer, LinkOption.NOFOLLOW_LINKS) || Files.size(pointer) > 80) throw new IOException("Invalid active generation pointer");
        String id = new String(Files.readAllBytes(pointer), StandardCharsets.UTF_8).trim();
        if (!id.matches("[0-9a-f]{64}")) throw new IOException("Invalid active generation ID"); return id;
    }
    private void atomicWrite(Path target, String content) throws IOException {
        Path temporary = target.resolveSibling(target.getFileName() + ".tmp");
        if (Files.isSymbolicLink(temporary) || Files.isSymbolicLink(target)) throw new IOException("Symlink metadata path");
        try (FileChannel out = FileChannel.open(temporary, StandardOpenOption.CREATE, StandardOpenOption.TRUNCATE_EXISTING, StandardOpenOption.WRITE)) {
            ByteBuffer data = ByteBuffer.wrap(content.getBytes(StandardCharsets.UTF_8)); while (data.hasRemaining()) out.write(data); out.force(true);
        }
        Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        syncDirectory(target.getParent());
    }
    private static boolean matchesCompletedSource(Path complete, String sourceId) throws IOException {
        if (!Files.isRegularFile(complete, LinkOption.NOFOLLOW_LINKS) || Files.size(complete) > 1024) return false;
        String text = new String(Files.readAllBytes(complete), StandardCharsets.UTF_8);
        return text.contains("\nsource=" + sourceId + "\n");
    }
    private static boolean probeDirectorySync(Path directory) {
        try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); return true; }
        catch (IOException | UnsupportedOperationException unavailable) { return false; }
    }
    private void syncDirectory(Path directory) throws IOException {
        if (directorySyncSupported) try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); }
    }
    private void createDirectoriesDurably(Path directory) throws IOException {
        if (Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) {
            rejectSymlinkAncestors(directory);
            if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Import directory conflicts with a file");
            return;
        }
        createDirectoriesDurably(directory.getParent());
        Files.createDirectory(directory); syncDirectory(directory.getParent());
    }
    private Map<String, Saved> readJournal(Path path) throws IOException {
        Map<String, Saved> entries = new HashMap<>();
        if (!Files.exists(path, LinkOption.NOFOLLOW_LINKS)) return entries;
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) > limits.maxFiles * 2048L) throw new IOException("Invalid import journal");
        try (BufferedReader in = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            String line; while ((line = boundedLine(in)) != null) {
                try {
                    String[] parts = line.split("\t"); if (parts.length != 4 || !parts[3].matches("[0-9a-f]{64}")) continue;
                    String name = validatePath(new String(Base64.getDecoder().decode(parts[0]), StandardCharsets.UTF_8));
                    entries.put(name, new Saved(Long.parseLong(parts[1]), Long.parseLong(parts[2])));
                    if (entries.size() > limits.maxFiles) throw new IOException("Excessive import journal entries");
                } catch (IllegalArgumentException ignored) { /* Incomplete last record is safely recopied. */ }
            }
        }
        return entries;
    }
    private static String boundedLine(BufferedReader in) throws IOException {
        StringBuilder line = new StringBuilder(); int value;
        while ((value = in.read()) != -1) {
            if (value == '\n') return line.toString();
            if (line.length() >= 2048) throw new IOException("Invalid long import journal record");
            line.append((char) value);
        }
        // A record interrupted before its newline is not committed.
        return null;
    }
    private static void appendJournal(Path path, String name, long size, long modified, String sha) throws IOException {
        if (Files.isSymbolicLink(path)) throw new IOException("Symlink import journal");
        // A leading newline isolates any partially written last record after process death.
        String record = "\n" + Base64.getEncoder().encodeToString(name.getBytes(StandardCharsets.UTF_8)) + "\t" + size + "\t" + modified + "\t" + sha + "\n";
        try (FileChannel out = FileChannel.open(path, StandardOpenOption.CREATE, StandardOpenOption.WRITE, StandardOpenOption.APPEND)) {
            ByteBuffer data = ByteBuffer.wrap(record.getBytes(StandardCharsets.UTF_8)); while (data.hasRemaining()) out.write(data); out.force(true);
        }
    }
    private ImportLock lock() throws IOException {
        Path lockPath = root.resolve("import.lock"); if (Files.isSymbolicLink(lockPath)) throw new IOException("Symlink lock path");
        FileChannel channel = FileChannel.open(lockPath, StandardOpenOption.CREATE, StandardOpenOption.WRITE);
        try {
            FileLock held = channel.tryLock(); if (held == null) throw new IOException("Another import is active"); return new ImportLock(channel, held);
        } catch (OverlappingFileLockException | IOException e) { channel.close(); throw new IOException("Another import is active or lock unavailable", e); }
    }
    private static MessageDigest sha256() { try { return MessageDigest.getInstance("SHA-256"); } catch (NoSuchAlgorithmException e) { throw new AssertionError(e); } }
    private static String hex(byte[] value) { StringBuilder out = new StringBuilder(value.length * 2); for (byte b : value) out.append(String.format(Locale.ROOT, "%02x", b & 255)); return out.toString(); }
    private static final class Saved { final long size, modified; Saved(long s, long m) { size = s; modified = m; } }
    private static final class ImportLock implements AutoCloseable { final FileChannel channel; final FileLock lock; ImportLock(FileChannel c, FileLock l) { channel = c; lock = l; } public void close() throws IOException { try { lock.release(); } finally { channel.close(); } } }
    private static final class Entry { String path; final String original; final long size, modified, crc; Entry(String path, long size, long modified, long crc) { this.path = path; this.original = path; this.size = size; this.modified = modified; this.crc = crc; } }
    private interface Source { List<Entry> entries(Cancellation cancellation) throws IOException; String identity(); InputStream open(Entry entry) throws IOException; void verifyUnchanged(Entry entry) throws IOException; }
    private final class FolderSource implements Source {
        final Path source;
        List<Entry> snapshot;
        final Map<Path, Long> directoryTimes = new HashMap<>();
        FolderSource(Path source) { this.source = source; }
        public String identity() { return source.toString(); }
        public List<Entry> entries(Cancellation cancellation) throws IOException {
            List<Entry> entries = new ArrayList<>();
            if (!Files.isDirectory(source, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Client source is not a folder");
            Files.walkFileTree(source, new SimpleFileVisitor<Path>() {
                @Override public FileVisitResult preVisitDirectory(Path directory, BasicFileAttributes attributes) throws IOException {
                    checkCancelled(cancellation);
                    if (directoryTimes.size() >= limits.maxFiles) throw new IOException("Too many source directories");
                    directoryTimes.put(directory, attributes.lastModifiedTime().toMillis());
                    return FileVisitResult.CONTINUE;
                }
                @Override public FileVisitResult visitFile(Path file, BasicFileAttributes attributes) throws IOException {
                    checkCancelled(cancellation);
                    if (!attributes.isRegularFile() || attributes.isSymbolicLink()) throw new IOException("Source symlinks and special files are forbidden");
                    if (entries.size() >= limits.maxFiles) throw new IOException("Too many source files");
                    entries.add(new Entry(source.relativize(file).toString().replace('\\', '/'), attributes.size(), attributes.lastModifiedTime().toMillis(), -1));
                    return FileVisitResult.CONTINUE;
                }
            });
            snapshot = entries;
            return entries;
        }
        public InputStream open(Entry entry) throws IOException { verifyUnchanged(entry); return Files.newInputStream(source.resolve(entry.original), LinkOption.NOFOLLOW_LINKS); }
        public void verifyUnchanged(Entry entry) throws IOException {
            if (entry == null) {
                for (Entry file : snapshot) verifyUnchanged(file);
                for (Map.Entry<Path, Long> directory : directoryTimes.entrySet()) {
                    rejectSymlinkAncestors(directory.getKey());
                    if (Files.getLastModifiedTime(directory.getKey(), LinkOption.NOFOLLOW_LINKS).toMillis() != directory.getValue()) throw new IOException("Source directory changed during import");
                }
                return;
            }
            Path path = source.resolve(entry.original); rejectSymlinkAncestors(path);
            BasicFileAttributes attrs = Files.readAttributes(path, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!attrs.isRegularFile() || attrs.size() != entry.size || attrs.lastModifiedTime().toMillis() != entry.modified) throw new IOException("Source changed during import: " + entry.path);
        }
    }
    private final class ZipSource implements Source, AutoCloseable {
        final Path source; final ZipFile zip; final long length, modified;
        ZipSource(Path source) throws IOException { this.source = source; length = Files.size(source); modified = Files.getLastModifiedTime(source).toMillis(); zip = new ZipFile(source.toFile()); }
        public String identity() { return source + "\n" + length + "\n" + modified; }
        public List<Entry> entries(Cancellation cancellation) throws IOException {
            List<Entry> entries = new ArrayList<>(); Set<String> allNames = new HashSet<>();
            Enumeration<? extends ZipEntry> iterator = zip.entries();
            while (iterator.hasMoreElements()) {
                checkCancelled(cancellation);
                ZipEntry file = iterator.nextElement();
                String name = file.getName(); String checked = file.isDirectory() ? name.substring(0, name.length() - 1) : name;
                validatePath(checked);
                if (!allNames.add(checked.toLowerCase(Locale.ROOT))) throw new IOException("Duplicate ZIP entry: " + name);
                if (allNames.size() > limits.maxFiles) throw new IOException("Too many ZIP entries");
                if (!file.isDirectory()) entries.add(new Entry(name, file.getSize(), file.getTime(), file.getCrc()));
            }
            return entries;
        }
        public InputStream open(Entry entry) throws IOException { return zip.getInputStream(zip.getEntry(entry.original)); }
        public void verifyUnchanged(Entry entry) throws IOException {
            if (Files.size(source) != length || Files.getLastModifiedTime(source).toMillis() != modified) throw new IOException("ZIP changed during import");
        }
        public void close() throws IOException { zip.close(); }
    }
}
