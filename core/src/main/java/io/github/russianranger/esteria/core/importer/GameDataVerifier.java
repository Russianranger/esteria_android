package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.stream.Stream;

/** Bounded structural checks, not a claim that arbitrary custom content is compatible. */
public final class GameDataVerifier {
    private static final String[] BASE_ARCHIVES = {"common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ", "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ"};
    private GameDataVerifier() {}

    /** Cheap filename-layout preflight only; header and version checks still run while importing. */
    static void verifyBaseLayout(Iterable<String> paths) throws IOException {
        Set<String> missing = new HashSet<>(); missing.add("wow.exe");
        for (String archive : BASE_ARCHIVES) missing.add("data/" + archive.toLowerCase(Locale.ROOT));
        boolean locale = false;
        for (String original : paths) {
            String path = original.toLowerCase(Locale.ROOT); missing.remove(path);
            if (path.startsWith("data/") && path.contains("/locale-")) {
                String[] parts = path.split("/");
                if (parts.length == 3 && parts[1].matches("[a-z]{4}") && parts[2].equals("locale-" + parts[1] + ".mpq")) locale = true;
            }
        }
        if (!missing.isEmpty()) throw new IOException("Incomplete conventional build 12340 client layout; missing " + String.join(", ", new java.util.TreeSet<>(missing)));
        if (!locale) throw new IOException("Missing Data/<locale>/locale-<locale>.MPQ");
    }

    public static void verifyBaseClient(Path root) throws IOException {
        Path wow = childIgnoringCase(root, "Wow.exe");
        if (wow == null) throw new IOException("Missing Wow.exe: import the 3.3.5a build 12340 client folder");
        verifyWowVersion(wow);
        Path data = childIgnoringCase(root, "Data");
        if (data == null || !Files.isDirectory(data)) throw new IOException("Missing Data directory");
        for (String name : BASE_ARCHIVES) {
            Path file = childIgnoringCase(data, name);
            if (file == null) throw new IOException("Missing base client archive Data/" + name);
            verifyMpq(file);
        }
        boolean localeFound = false;
        try (Stream<Path> children = Files.list(data)) {
            for (Path child : (Iterable<Path>) children::iterator) {
                String locale = child.getFileName().toString();
                if (Files.isDirectory(child) && locale.matches("[a-zA-Z]{4}")) {
                    Path archive = childIgnoringCase(child, "locale-" + locale + ".MPQ");
                    if (archive != null) { verifyMpq(archive); localeFound = true; }
                }
            }
        }
        if (!localeFound) throw new IOException("Missing Data/<locale>/locale-<locale>.MPQ");
    }

    public static void verifyKnownFile(Path file, String relativePath) throws IOException {
        String lower = relativePath.toLowerCase(Locale.ROOT);
        if (lower.endsWith(".mpq")) verifyMpq(file);
        if (lower.equals("wow.exe")) verifyWowVersion(file);
        EsteriaCatalogVerifier.verifyKnown(file, relativePath);
    }

    private static Path childIgnoringCase(Path parent, String name) throws IOException {
        try (Stream<Path> children = Files.list(parent)) {
            for (Path child : (Iterable<Path>) children::iterator)
                if (child.getFileName().toString().equalsIgnoreCase(name)) return child;
        }
        return null;
    }

    /** Locate PE version resources through the section/resource tables; never scan for a loose string. */
    public static void verifyWowVersion(Path exe) throws IOException {
        try (RandomAccessFile f = new RandomAccessFile(exe.toFile(), "r")) {
            if (f.length() < 256 || u16(f, 0) != 0x5a4d) throw new IOException("Wow.exe is not a PE executable");
            long pe = u32(f, 0x3c);
            range(f, pe, 24);
            if (u32(f, pe) != 0x00004550) throw new IOException("Invalid Wow.exe PE signature");
            int sections = u16(f, pe + 6), optionalSize = u16(f, pe + 20);
            if (sections < 1 || sections > 96) throw new IOException("Invalid PE section count");
            long optional = pe + 24;
            range(f, optional, optionalSize);
            int magic = u16(f, optional);
            int directoryOffset = magic == 0x10b ? 96 : magic == 0x20b ? 112 : -1;
            if (directoryOffset < 0 || optionalSize < directoryOffset + 24 || u32(f, optional + directoryOffset - 4) < 3)
                throw new IOException("Missing PE resource directory");
            long resourceRva = u32(f, optional + directoryOffset + 16), resourceSize = u32(f, optional + directoryOffset + 20);
            if (resourceSize < 16 || resourceSize > 32 * 1024 * 1024) throw new IOException("Invalid PE resource size");
            List<long[]> map = new ArrayList<>();
            long table = optional + optionalSize;
            range(f, table, sections * 40L);
            for (int i = 0; i < sections; i++) {
                long pos = table + i * 40L;
                map.add(new long[]{u32(f, pos + 12), u32(f, pos + 16), u32(f, pos + 20)});
            }
            long resource = mapRva(map, resourceRva, resourceSize);
            range(f, resource, resourceSize);
            long type = findResource(f, resource, resourceSize, 0, 16);
            if (type < 0 || (type & 0x80000000L) == 0) throw new IOException("No VERSIONINFO resource in Wow.exe");
            List<Long> entries = new ArrayList<>();
            collectVersionEntries(f, resource, resourceSize, type & 0x7fffffffL, 0, entries);
            if (entries.isEmpty()) throw new IOException("No version resource data");
            boolean found = false;
            for (long entry : entries) {
                resourceRange(resourceSize, entry, 16);
                long rva = u32(f, resource + entry), size = u32(f, resource + entry + 4);
                if (size < 92 || size > 1024 * 1024) throw new IOException("Invalid version resource data size");
                long data = mapRva(map, rva, size);
                range(f, data, size);
                int length = u16(f, data), valueLength = u16(f, data + 2), kind = u16(f, data + 4);
                if (length > size || length < 92 || valueLength != 52 || kind != 0) throw new IOException("Malformed VS_VERSION_INFO");
                String key = "VS_VERSION_INFO";
                for (int i = 0; i <= key.length(); i++)
                    if (u16(f, data + 6 + i * 2L) != (i < key.length() ? key.charAt(i) : 0)) throw new IOException("Invalid VERSIONINFO key");
                long fixed = data + 40; // wLength,wValueLength,wType + UTF-16 key + DWORD alignment
                if (u32(f, fixed) != 0xfeef04bdL || u32(f, fixed + 4) != 0x00010000L) throw new IOException("Invalid VS_FIXEDFILEINFO");
                long ms = u32(f, fixed + 8), ls = u32(f, fixed + 12);
                if (ms != 0x00030003L || ls != 0x00053034L)
                    throw new IOException("Client version is " + (ms >>> 16) + "." + (ms & 65535) + "." + (ls >>> 16) + "." + (ls & 65535) + "; required 3.3.5.12340");
                found = true;
            }
            if (!found) throw new IOException("No build 12340 version evidence");
        }
    }

    private static void collectVersionEntries(RandomAccessFile f, long base, long size, long directory, int depth, List<Long> out) throws IOException {
        if (depth > 2 || out.size() > 128) throw new IOException("Invalid version resource tree");
        resourceRange(size, directory, 16);
        int count = u16(f, base + directory + 12) + u16(f, base + directory + 14);
        if (count > 128) throw new IOException("Excessive version resources");
        resourceRange(size, directory + 16, count * 8L);
        for (int i = 0; i < count; i++) {
            long child = u32(f, base + directory + 20 + i * 8L);
            if ((child & 0x80000000L) != 0) collectVersionEntries(f, base, size, child & 0x7fffffffL, depth + 1, out);
            else out.add(child);
        }
    }

    private static long findResource(RandomAccessFile f, long base, long size, long directory, int id) throws IOException {
        resourceRange(size, directory, 16);
        int count = u16(f, base + directory + 12) + u16(f, base + directory + 14);
        resourceRange(size, directory + 16, count * 8L);
        for (int i = 0; i < count; i++) {
            long name = u32(f, base + directory + 16 + i * 8L);
            if (name == id) return u32(f, base + directory + 20 + i * 8L);
        }
        return -1;
    }

    private static long mapRva(List<long[]> sections, long rva, long length) throws IOException {
        for (long[] s : sections) if (rva >= s[0] && rva - s[0] <= s[1] && length <= s[1] - (rva - s[0])) return s[2] + rva - s[0];
        throw new IOException("PE RVA lies outside file-backed sections");
    }
    private static void resourceRange(long total, long offset, long size) throws IOException {
        if (offset < 0 || size < 0 || offset > total || size > total - offset) throw new IOException("PE resource range out of bounds");
    }

    public static void verifyMpq(Path archive) throws IOException {
        try (RandomAccessFile f = new RandomAccessFile(archive.toFile(), "r")) {
            long start = -1;
            if (f.length() >= 16 && u32(f, 0) == 0x1b51504dL) {
                start = u32(f, 8); range(f, start, 32);
                if (u32(f, start) != 0x1a51504dL) throw new IOException("MPQ user-data header has an invalid archive offset");
            } else {
                for (long at = 0; at <= Math.min(f.length() - 32, 1024 * 1024); at += 512)
                    if (u32(f, at) == 0x1a51504dL) { start = at; break; }
            }
            if (start < 0) throw new IOException("Missing MPQ header: " + archive.getFileName());
            long header = u32(f, start + 4), archiveSize = u32(f, start + 8);
            int version = u16(f, start + 12), blockShift = u16(f, start + 14);
            if (version > 1 || header < (version == 0 ? 32 : 44) || header > 4096 || blockShift > 16)
                throw new IOException("Unsupported or invalid MPQ header: " + archive.getFileName());
            range(f, start, header);
            // 3.3.5 archives use MPQ v0/v1. v1 can exceed 4 GiB, so the low archive-size field is not authoritative there.
            long available = f.length() - start;
            if (version == 0 && (archiveSize < header || archiveSize > available)) throw new IOException("Truncated MPQ archive");
            long hashOffset = u32(f, start + 16), blockOffset = u32(f, start + 20);
            long hashCount = u32(f, start + 24), blockCount = u32(f, start + 28);
            if (version == 1) { hashOffset |= ((long) u16(f, start + 40)) << 32; blockOffset |= ((long) u16(f, start + 42)) << 32; }
            long limit = version == 0 ? archiveSize : available;
            if (hashCount < 1 || hashCount > 0x1000000 || (hashCount & (hashCount - 1)) != 0 || blockCount > 0x1000000)
                throw new IOException("Invalid MPQ table counts");
            if (hashOffset < header || blockOffset < header) throw new IOException("MPQ tables overlap header");
            if (version == 0) {
                resourceRange(limit, hashOffset, hashCount * 16);
                resourceRange(limit, blockOffset, blockCount * 16);
                if (blockCount > 0 && overlaps(hashOffset, hashCount * 16, blockOffset, blockCount * 16))
                    throw new IOException("MPQ tables overlap each other");
            } else {
                // TBC-format tables can be compressed *before* encryption. Counts describe
                // decoded entries, not stored bytes. See the pinned client's
                // SFileArchives.cpp::LoadTables and StormLib SBaseFileTable.cpp.
                // This is an extent preflight; the client reader must still decode tables.
                long extendedBlocks = u64(f, start + 32);
                if (blockOffset <= hashOffset) throw new IOException("Unsupported MPQ v1 table ordering");
                long hashStored = blockOffset - hashOffset;
                if (hashStored > hashCount * 16 || hashStored < 2)
                    throw new IOException("Unsupported MPQ v1 hash table extent");
                resourceRange(limit, hashOffset, hashStored);
                long blockEnd;
                if (extendedBlocks != 0) {
                    resourceRange(limit, extendedBlocks, blockCount * 2);
                    if (extendedBlocks < header || extendedBlocks < blockOffset
                            || overlaps(extendedBlocks, blockCount * 2, hashOffset, hashStored))
                        throw new IOException("MPQ extended table overlaps header/hash/block tables");
                    blockEnd = extendedBlocks;
                } else {
                    // An uncompressed table ends after count*16 even when a signature follows.
                    // A shorter final extent is a possible compressed table, not corruption.
                    blockEnd = Math.min(limit, blockOffset + blockCount * 16);
                }
                long blockStored = blockEnd - blockOffset;
                if (blockStored < 0 || blockStored > blockCount * 16 || (blockCount > 0 && blockStored < 2))
                    throw new IOException("Unsupported MPQ v1 block table extent");
                resourceRange(limit, blockOffset, blockStored);
            }
        }
    }

    private static boolean overlaps(long offsetA, long sizeA, long offsetB, long sizeB) {
        return sizeA > 0 && sizeB > 0 && offsetA < offsetB + sizeB && offsetB < offsetA + sizeA;
    }

    static long u32(RandomAccessFile f, long at) throws IOException { f.seek(at); return Integer.toUnsignedLong(Integer.reverseBytes(f.readInt())); }
    static int u16(RandomAccessFile f, long at) throws IOException { f.seek(at); return Short.toUnsignedInt(Short.reverseBytes(f.readShort())); }
    static long u64(RandomAccessFile f, long at) throws IOException { f.seek(at); long value = Long.reverseBytes(f.readLong()); if (value < 0) throw new IOException("Unsupported unsigned 64-bit length"); return value; }
    static void range(RandomAccessFile f, long at, long length) throws IOException { resourceRange(f.length(), at, length); }
}
