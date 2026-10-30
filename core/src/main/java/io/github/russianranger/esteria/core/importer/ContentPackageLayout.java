package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.Objects;
import java.util.ArrayList;
import java.util.List;
import java.util.Comparator;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Closed import routes. Server payloads remain separate from client providers. */
public final class ContentPackageLayout {
    public static final String SERVER_DIRECTORY = "EsteriaServerData";
    public static final String SERVER_MANIFEST = "manifest.properties";
    private static final String SERVER = "f35f04d01689f034778e3474b3c820092f51e461";
    private static final Set<String> GROUPS = Set.of("dbc", "dbc-continuations", "maps", "vmaps", "mmaps", "Cameras");
    private static final Set<String> COMPLETE = Set.of("dbc", "maps", "vmaps", "mmaps", "Cameras");
    private static final Set<String> MANIFEST_KEYS = Set.of("format", "scope", "serverRevision", "clientBuild", "mode", "provenance", "clientProviderOrderSha256");
    // OpenArchives with common.MPQ present uses the classical complete-client
    // availability mask (2). Segmented/trial and streaming roots are separate
    // unsupported profiles; runtime/extractor_order.py preserves the same table.
    private static final Set<String> CLASSICAL_BASES = Set.of("alternate.mpq", "expansion.mpq", "lichking.mpq", "common.mpq", "common-2.mpq", "common-3.mpq");
    private static final Set<String> CLIENT_LOCALES = Set.of("dede", "engb", "enus", "eses", "frfr", "kokr", "zhcn", "zhtw", "encn", "entw", "esmx", "ruru");
    private static final String[] LOCALE_BASES = {"locale-", "speech-", "expansion-locale-", "lichking-locale-", "expansion-speech-", "lichking-speech-"};
    private ContentPackageLayout() { }

    public static final class ServerManifest {
        public final String mode, clientProviderOrderSha256, manifestSha256;
        public final long manifestBytes;
        private ServerManifest(String mode, String order, byte[] raw) {
            this.mode = mode; clientProviderOrderSha256 = order; manifestBytes = raw.length;
            try {
                byte[] digest = MessageDigest.getInstance("SHA-256").digest(raw);
                StringBuilder encoded = new StringBuilder(64);
                for (byte value : digest) encoded.append(String.format(Locale.ROOT, "%02x", value & 255));
                manifestSha256 = encoded.toString();
            } catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
        }
        @Override public boolean equals(Object value) {
            if (!(value instanceof ServerManifest)) return false;
            ServerManifest other = (ServerManifest) value;
            return manifestBytes == other.manifestBytes && mode.equals(other.mode) &&
                    clientProviderOrderSha256.equals(other.clientProviderOrderSha256) && manifestSha256.equals(other.manifestSha256);
        }
        @Override public int hashCode() { return Objects.hash(mode, clientProviderOrderSha256, manifestBytes, manifestSha256); }
    }

    /** Tiny manifest binding for a retained runtime plan; this does not validate payload headers. */
    public static ServerManifest inspectServerManifest(Path importedRoot) throws IOException {
        if (importedRoot == null || !importedRoot.isAbsolute() || !importedRoot.normalize().equals(importedRoot) ||
                !Files.isDirectory(importedRoot, LinkOption.NOFOLLOW_LINKS) || !importedRoot.toRealPath().equals(importedRoot))
            throw new IOException("A canonical imported client directory is required");
        try (java.nio.file.DirectoryStream<Path> children = Files.newDirectoryStream(importedRoot)) {
            int count = 0;
            for (Path child : children) {
                if (++count > 200_000) throw new IOException("Imported root entry bound exceeded");
                String name = child.getFileName().toString();
                if (name.equalsIgnoreCase(SERVER_DIRECTORY) && !name.equals(SERVER_DIRECTORY))
                    throw new IOException("Server data must use the exact EsteriaServerData/ directory name");
            }
        }
        Path namespace = importedRoot.resolve(SERVER_DIRECTORY);
        if (!Files.exists(namespace, LinkOption.NOFOLLOW_LINKS)) return null;
        if (!Files.isDirectory(namespace, LinkOption.NOFOLLOW_LINKS) || !namespace.toRealPath().equals(namespace))
            throw new IOException("EsteriaServerData must be an unlinked directory");
        return readManifest(namespace.resolve(SERVER_MANIFEST));
    }

    /** Returns whether this import supplies a complete replacement reserved namespace. */
    static boolean inspect(Iterable<String> paths, boolean overlay) throws IOException {
        boolean server = false, manifest = false, supportedRoot = false, wrappedData = false;
        for (String path : paths) {
            String[] parts = path.split("/");
            String first = parts[0].toLowerCase(Locale.ROOT);
            validateClientProviderLocation(parts);
            if (first.equals(SERVER_DIRECTORY.toLowerCase(Locale.ROOT))) {
                server = true; supportedRoot = true;
                if (!parts[0].equals(SERVER_DIRECTORY)) throw new IOException("Server data must use the exact EsteriaServerData/ directory name");
                if (parts.length == 1) throw new IOException("EsteriaServerData must be a directory containing manifest.properties and data/");
                if (path.equals(SERVER_DIRECTORY + "/" + SERVER_MANIFEST)) manifest = true;
                else validateServerPath(path.substring(SERVER_DIRECTORY.length() + 1));
            }
            if (first.equals("data") || first.equals("interface") || first.equals("fonts") ||
                    (parts.length == 1 && first.matches("esteria[a-z0-9_.-]*\\.bin"))) supportedRoot = true;
            if (first.endsWith(".mpq")) throw new IOException("Place custom archives and folder MPQs under Data/ (for example Data/patch-Z.MPQ); select the package parent, not Data itself");
            if (first.equals("esteria") && parts[parts.length - 1].toLowerCase(Locale.ROOT).endsWith(".bin"))
                throw new IOException("Loose Esteria*.bin catalogs belong beside Wow.exe at the package root, or inside Data/patch-*.MPQ/Esteria/; a root Esteria/ directory is not loaded");
            if (overlay) {
                for (int i = 1; i < parts.length - 1; i++) if (parts[i].equalsIgnoreCase("Data")) wrappedData = true;
            }
        }
        if (overlay && wrappedData && !supportedRoot) throw new IOException("Custom content is wrapped in another folder; choose the folder containing Data/ or create a ZIP with Data/ at its root");
        if (server && !manifest) throw new IOException("EsteriaServerData/ requires manifest.properties and the complete replacement payload for this package");
        return server;
    }

    private static boolean effectiveProvider(String[] parts, int boundary) {
        if (!parts[0].equalsIgnoreCase("Data")) return false;
        String name = parts[boundary].toLowerCase(Locale.ROOT);
        if (!name.endsWith(".mpq")) return false;
        if (boundary == 1) return CLASSICAL_BASES.contains(name) || name.equals("patch.mpq") || name.startsWith("patch-");
        if (boundary != 2) return false;
        String locale = parts[1].toLowerCase(Locale.ROOT);
        if (!CLIENT_LOCALES.contains(locale)) return false;
        if (name.equals("patch-" + locale + ".mpq") || name.startsWith("patch-" + locale + "-")) return true;
        for (String prefix : LOCALE_BASES) if (name.equals(prefix + locale + ".mpq")) return true;
        return false;
    }

    private static void validateClientProviderLocation(String[] parts) throws IOException {
        // Once an effective folder-MPQ boundary is reached, everything below it
        // is a virtual asset path, including folders named Data or the reserved
        // server namespace. Those names must not be reinterpreted as packages.
        if ((parts.length > 1 && effectiveProvider(parts, 1)) || (parts.length > 2 && effectiveProvider(parts, 2))) return;
        String first = parts[0].toLowerCase(Locale.ROOT);
        if (first.equals(SERVER_DIRECTORY.toLowerCase(Locale.ROOT))) return;
        for (int i = 1; i < parts.length; i++) if (parts[i].equalsIgnoreCase(SERVER_DIRECTORY))
            throw new IOException("EsteriaServerData/ is a reserved server package and must be at the client/package root, not inside another folder");
        if (first.equals("interface") || first.equals("fonts")) return;
        for (String component : parts) if (component.toLowerCase(Locale.ROOT).endsWith(".mpq"))
            throw new IOException("MPQ content is not at an effective client provider location; place custom archives and folder MPQs under Data/patch-*.MPQ or Data/<locale>/patch-<locale>-*.MPQ, without a wrapper folder");
    }

    static boolean reserved(String relative) {
        String first = relative.split("/", 2)[0];
        return first.equalsIgnoreCase(SERVER_DIRECTORY);
    }

    private static String validateServerPath(String relative) throws IOException {
        serverRelativePath(relative);
        String[] parts = relative.split("/");
        if (parts.length < 3 || !parts[0].equals("data") || !GROUPS.contains(parts[1]))
            throw new IOException("Server data files belong only under EsteriaServerData/data/{dbc,dbc-continuations,maps,vmaps,mmaps,Cameras}/");
        return parts[1];
    }
    private static void serverRelativePath(String relative) throws IOException {
        GameDataImporter.validatePath(relative);
        for (int i = 0; i < relative.length(); i++) if (relative.charAt(i) < 32 || relative.charAt(i) > 126)
            throw new IOException("Server data package paths must use supported ASCII names");
    }

    /** Header/length checks only. Actual coverage, rows and runtime compatibility remain unqualified. */
    public static void validateFinal(Path imported) throws IOException {
        ServerManifest manifest = inspectServerManifest(imported);
        if (manifest == null) return;
        Path namespace = imported.resolve(SERVER_DIRECTORY);
        Set<String> checked = new HashSet<>(), folded = new HashSet<>();
        Map<String, long[]> baseDbc = new HashMap<>(), continuations = new HashMap<>();
        final int[] count = {0};
        Files.walkFileTree(namespace, new SimpleFileVisitor<Path>() {
            @Override public FileVisitResult preVisitDirectory(Path directory, BasicFileAttributes attributes) throws IOException {
                String relative = namespace.relativize(directory).toString().replace('\\', '/');
                if (!relative.isEmpty()) serverRelativePath(relative);
                // Runtime data inventory removes the leading data/ component
                // and permits at most 16 parent components below that root.
                if (attributes.isSymbolicLink() || namespace.relativize(directory).getNameCount() > 17) throw new IOException("Unsafe or excessively deep server data directory");
                if (!relative.isEmpty() && !relative.equals("data") && !(relative.startsWith("data/") && GROUPS.contains(relative.split("/")[1])))
                    throw new IOException("Unexpected server data directory: " + relative);
                if (!folded.add(relative.toLowerCase(Locale.ROOT))) throw new IOException("Case-colliding server data paths");
                return FileVisitResult.CONTINUE;
            }
            @Override public FileVisitResult visitFile(Path path, BasicFileAttributes attributes) throws IOException {
                if (++count[0] > 200_000 || !attributes.isRegularFile() || attributes.isSymbolicLink()) throw new IOException("Unsafe or excessive server data files");
                String relative = namespace.relativize(path).toString().replace('\\', '/');
                if (!folded.add(relative.toLowerCase(Locale.ROOT))) throw new IOException("Case-colliding server data paths");
                if (relative.equals(SERVER_MANIFEST)) return FileVisitResult.CONTINUE;
                String group = validateServerPath(relative);
                if (manifest.mode.equals("overlay") && !group.equals("dbc") && !group.equals("dbc-continuations"))
                    throw new IOException("Server data mode=overlay permits only dbc and dbc-continuations; use mode=complete for prepared maps and geometry");
                String name = path.getFileName().toString(), lower = name.toLowerCase(Locale.ROOT);
                boolean recognized = true;
                if (group.equals("dbc") && lower.endsWith(".dbc")) {
                    long[] layout = dbc(path), previous = baseDbc.putIfAbsent(lower, layout);
                    if (previous != null && (previous[0] != layout[0] || previous[1] != layout[1])) throw new IOException("Base DBC variants have different field counts or record strides: " + name);
                } else if (group.equals("dbc-continuations") && name.matches("[A-Za-z][A-Za-z0-9_]*\\.dbc[1-9]-[A-Za-z0-9_-]+")) {
                    long[] layout = dbc(path); continuations.put(relative, layout);
                } else if (group.equals("dbc-continuations") && name.equals("wxl-dbc.manifest")) {
                    if (!relative.equals("data/dbc-continuations/wxl-dbc.manifest")) throw new IOException("wxl-dbc.manifest must be at the dbc-continuations root");
                    if (attributes.size() > 1L << 20) throw new IOException("wxl-dbc.manifest exceeds its byte bound");
                    recognized = false;
                } else if (group.equals("dbc") && name.matches("component\\.wow-[A-Za-z]{4}\\.txt")) {
                    if (attributes.size() > 65536) throw new IOException("DBC component build metadata exceeds its byte bound");
                    recognized = false;
                } else if (group.equals("maps") && lower.endsWith(".map")) map(path);
                else if (group.equals("vmaps") && (lower.endsWith(".vmtree") || lower.endsWith(".vmtile") || lower.endsWith(".vmo") || lower.equals("gameobjectmodels.dtree"))) magic(path, "VMAP_4.8", 8);
                else if (group.equals("mmaps") && lower.endsWith(".mmap")) { header(path, 28); if (attributes.size() != 28) throw new IOException("Expected 28-byte mmap index"); }
                else if (group.equals("mmaps") && lower.endsWith(".mmtile")) {
                    ByteBuffer h = header(path, 56);
                    if (h.getInt(0) != 0x4d4d4150 || h.getInt(4) != 7 || h.getInt(8) != 20 || u32(h, 12) == 0 || u32(h, 12) != attributes.size() - 56)
                        throw new IOException("Expected mmap20/Detour7 tile and exact payload length");
                } else if (group.equals("Cameras") && lower.endsWith(".m2")) magic(path, "MD20", 8);
                else throw new IOException("Unrecognized server data file in " + group + ": " + name);
                if (recognized) checked.add(group);
                return FileVisitResult.CONTINUE;
            }
        });
        if (manifest.mode.equals("complete") && !checked.containsAll(COMPLETE)) throw new IOException("Complete server data requires recognized files in dbc, maps, vmaps, mmaps and Cameras");
        if (manifest.mode.equals("overlay") && !checked.contains("dbc") && !checked.contains("dbc-continuations")) throw new IOException("Server data overlay contains no DBC or continuation files");
        for (Map.Entry<String, long[]> row : continuations.entrySet()) {
            String name = row.getKey().substring(row.getKey().lastIndexOf('/') + 1);
            String table = name.substring(0, name.indexOf(".dbc")) + ".dbc";
            long[] base = baseDbc.get(table.toLowerCase(Locale.ROOT)), extra = row.getValue();
            if (base != null && (base[0] != extra[0] || base[1] != extra[1])) throw new IOException("DBC continuation field count or record stride differs from base " + table);
        }
        validateContinuationOrder(namespace, continuations.keySet());
    }

    /** Mirror WxlDbcScan's ordering without merging or modifying any rows. */
    private static void validateContinuationOrder(Path namespace, Set<String> paths) throws IOException {
        String prefix = "data/dbc-continuations/";
        Set<String> known = new HashSet<>();
        for (String path : paths) known.add(path.substring(prefix.length()));
        Map<String, Integer> positions = new HashMap<>();
        Path manifest = namespace.resolve(prefix + "wxl-dbc.manifest");
        if (Files.exists(manifest, LinkOption.NOFOLLOW_LINKS)) {
            if (!Files.isRegularFile(manifest, LinkOption.NOFOLLOW_LINKS) || Files.size(manifest) > 1L << 20)
                throw new IOException("wxl-dbc.manifest must be a bounded regular file");
            byte[] raw = readAtMost(manifest, (1 << 20) + 1);
            if (raw.length > 1 << 20) throw new IOException("wxl-dbc.manifest exceeds its byte bound");
            for (byte value : raw) if (value < 0 || (value < 32 && value != '\n' && value != '\r' && value != '\t') || value == 127)
                throw new IOException("wxl-dbc.manifest requires ASCII text without other control characters");
            int position = 0;
            // The pinned C++ reader uses std::getline('\n'), followed by
            // trailing CR/SP/TAB and leading SP/TAB removal.
            int start = 0;
            for (int at = 0; at <= raw.length; at++) {
                if (at < raw.length && raw[at] != '\n') continue;
                int begin = start, end = at; start = at + 1;
                while (end > begin && (raw[end - 1] == '\r' || raw[end - 1] == ' ' || raw[end - 1] == '\t')) end--;
                while (begin < end && (raw[begin] == ' ' || raw[begin] == '\t')) begin++;
                String line = new String(raw, begin, end - begin, StandardCharsets.US_ASCII);
                if (line.isEmpty() || line.charAt(0) == '#') continue;
                if (line.startsWith("/") || line.indexOf('\\') >= 0 || line.indexOf(':') >= 0)
                    throw new IOException("Continuation manifest references an unsafe or absent file");
                for (int i = 0; i < line.length(); i++) if (line.charAt(i) < 32 || line.charAt(i) > 126)
                    throw new IOException("Continuation manifest references an unsafe or absent file");
                for (String part : line.split("/", -1)) if (part.isEmpty() || part.equals(".") || part.equals(".."))
                    throw new IOException("Continuation manifest references an unsafe or absent file");
                if (!known.contains(line)) throw new IOException("Continuation manifest references an unsafe or absent file");
                positions.putIfAbsent(line, position++); // The source preserves the first explicit occurrence.
            }
        }
        List<ContinuationOrder> order = new ArrayList<>();
        for (String path : known) {
            String name = path.substring(path.lastIndexOf('/') + 1);
            int dbc = name.indexOf(".dbc");
            order.add(new ContinuationOrder(name.charAt(dbc + 4) - '0', positions.getOrDefault(path, Integer.MAX_VALUE),
                    name.substring(dbc + 6).toLowerCase(Locale.ROOT), (name.substring(0, dbc) + ".dbc").toLowerCase(Locale.ROOT)));
        }
        Comparator<ContinuationOrder> sourceOrder = Comparator.comparingInt((ContinuationOrder row) -> row.tier)
                .thenComparingInt(row -> row.position).thenComparing(row -> row.project).thenComparing(row -> row.table);
        order.sort(sourceOrder);
        for (int i = 1; i < order.size(); i++) if (sourceOrder.compare(order.get(i - 1), order.get(i)) == 0)
            throw new IOException("Ambiguous continuation order; list both files in wxl-dbc.manifest");
    }
    private static final class ContinuationOrder {
        final int tier, position; final String project, table;
        ContinuationOrder(int tier, int position, String project, String table) {
            this.tier = tier; this.position = position; this.project = project; this.table = table;
        }
    }

    private static ServerManifest readManifest(Path path) throws IOException {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) > 2048) throw new IOException("Server manifest.properties must be a regular file of at most 2048 bytes");
        byte[] raw = readAtMost(path, 2049);
        if (raw.length == 0 || raw.length > 2048 || raw[raw.length - 1] != '\n') throw new IOException("Server manifest.properties must be newline-terminated strict ASCII");
        for (int i = 0; i < raw.length; i++) {
            byte value = raw[i];
            if (value == '\r' && i + 1 < raw.length && raw[i + 1] == '\n') continue;
            if (value != '\n' && (value < 32 || value > 126)) throw new IOException("Server manifest.properties must contain strict ASCII without escapes or control characters");
        }
        Map<String, String> result = new HashMap<>();
        String[] lines = new String(raw, StandardCharsets.US_ASCII).split("\n", -1);
        if (lines.length != 8) throw new IOException("Server manifest.properties requires exactly seven documented key=value lines");
        for (int i = 0; i < lines.length - 1; i++) {
            String line = lines[i];
            if (line.endsWith("\r")) line = line.substring(0, line.length() - 1);
            int equal = line.indexOf('=');
            if (equal <= 0 || line.indexOf('=', equal + 1) >= 0 || !MANIFEST_KEYS.contains(line.substring(0, equal)) || result.put(line.substring(0, equal), line.substring(equal + 1)) != null)
                throw new IOException("Server manifest.properties requires exactly seven unique documented key=value lines");
        }
        if (!result.keySet().equals(MANIFEST_KEYS) || !result.get("format").equals("1") ||
                !result.get("scope").equals("esteria-user-supplied-server-data") || !result.get("serverRevision").equals(SERVER) ||
                !result.get("clientBuild").equals("12340") || !Set.of("complete", "overlay").contains(result.get("mode")) ||
                !result.get("provenance").equals("user-supplied-format-checked") ||
                !result.get("clientProviderOrderSha256").matches("none|[0-9a-f]{64}"))
            throw new IOException("Server data manifest does not select the pinned server, build12340 and supported package mode");
        return new ServerManifest(result.get("mode"), result.get("clientProviderOrderSha256"), raw);
    }

    private static ByteBuffer header(Path path, int length) throws IOException {
        byte[] raw = readAtMost(path, length);
        if (raw.length != length) throw new IOException("Truncated server data header: " + path.getFileName());
        return ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
    }
    private static byte[] readAtMost(Path path, int maximum) throws IOException {
        byte[] raw = new byte[maximum]; int count = 0;
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            while (count < raw.length) {
                int amount = input.read(raw, count, raw.length - count);
                if (amount < 0) break;
                if (amount == 0) throw new IOException("Server data stream made no progress");
                count += amount;
            }
        }
        return count == raw.length ? raw : java.util.Arrays.copyOf(raw, count);
    }
    private static long u32(ByteBuffer bytes, int offset) { return Integer.toUnsignedLong(bytes.getInt(offset)); }
    private static void magic(Path path, String expected, int headerLength) throws IOException {
        ByteBuffer header = header(path, headerLength);
        byte[] bytes = expected.getBytes(StandardCharsets.US_ASCII);
        for (int i = 0; i < bytes.length; i++) if (header.get(i) != bytes[i]) throw new IOException("Unexpected server data signature: " + path.getFileName());
    }
    private static long[] dbc(Path path) throws IOException {
        ByteBuffer h = header(path, 20);
        long rows = u32(h, 4), fields = u32(h, 8), stride = u32(h, 12), strings = u32(h, 16);
        if (h.getInt(0) != 0x43424457 || fields == 0 || stride == 0 || rows > (Long.MAX_VALUE - 20 - strings) / stride || Files.size(path) != 20 + rows * stride + strings)
            throw new IOException("Expected WDBC header and exact declared length: " + path.getFileName());
        return new long[]{fields, stride};
    }
    private static void map(Path path) throws IOException {
        ByteBuffer h = header(path, 44);
        if (h.getInt(0) != 0x5350414d || h.getInt(4) != 9 || h.getInt(8) != 12340) throw new IOException("Expected MAPS9 build12340");
        long[] starts = new long[4], ends = new long[4]; int count = 0;
        for (int at = 12; at < 44; at += 8) {
            long offset = u32(h, at), length = u32(h, at + 4);
            if (length == 0) continue;
            if (offset < 44 || offset > Files.size(path) || length > Files.size(path) - offset) throw new IOException("Map chunk lies outside its file");
            for (int i = 0; i < count; i++) if (offset < ends[i] && starts[i] < offset + length) throw new IOException("Map chunks overlap");
            starts[count] = offset; ends[count++] = offset + length;
        }
    }
}
