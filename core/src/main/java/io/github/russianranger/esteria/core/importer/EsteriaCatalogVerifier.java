package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Set;

/** Structural selection-catalog checks from the pinned reconstructed reader.
 * Packed MPQ catalogs and referenced art still require effective-data validation.
 */
final class EsteriaCatalogVerifier {
    private static final Set<String> SELECTIONS = Set.of("naga", "tuskarr", "vrykul", "thinhuman",
            "sethrak", "gnoll", "saberon", "tarasek", "drakonid", "darkfallen", "vulpera",
            "highmountain", "earthen", "haranir", "kyrian", "venthyr");
    private static final int RECORD_BYTES = 156, MAX_RECORDS = 16384;
    private EsteriaCatalogVerifier() { }

    static void verifyKnown(Path file, String relative) throws IOException {
        String name = relative.substring(relative.lastIndexOf('/') + 1).toLowerCase(Locale.ROOT);
        if (!name.startsWith("esteria") || !name.endsWith(".bin") ||
                !SELECTIONS.contains(name.substring(7, name.length() - 4))) return;
        try (RandomAccessFile input = new RandomAccessFile(file.toFile(), "r")) {
            if (input.length() < 12 || readU32(input) != 0x314d4845L || readU32(input) != 1)
                throw new IOException("Unsupported Esteria selection catalog signature or version: " + name);
            long count = readU32(input);
            if (count > MAX_RECORDS || input.length() != 12 + count * RECORD_BYTES)
                throw new IOException("Esteria selection catalog record count or length differs: " + name);
            byte[] record = new byte[RECORD_BYTES];
            for (int i = 0; i < count; i++) {
                input.readFully(record);
                long gender = u32(record, 0), kind = u32(record, 4), target = u32(record, 8), value = u32(record, 12);
                boolean valid = gender < 2 && kind <= 5;
                boolean terminated = false;
                for (int at = 28; at < RECORD_BYTES; at++) if (record[at] == 0) { terminated = true; break; }
                valid &= terminated;
                if (kind == 0) valid &= target < 52 && value >= target * 100 && value < target * 100 + 100;
                else if (kind == 1) valid &= target < 16 && record[28] != 0;
                else if (kind == 2) valid &= target < 5200 && value >= 10000 && value < 30000;
                else if (kind == 3) valid &= target < 9 && value >= 16;
                else if (kind == 4) valid &= target != 0 && value < 52;
                else if (kind == 5) valid &= target < 16 && value != 0 && record[28] != 0;
                for (int at = 16; at < 28; at += 4) {
                    long selector = u32(record, at);
                    valid &= selector == 0xffffffffL || ((selector & 0xffff) < 32 && (selector >>> 16) < 256);
                }
                if (!valid) throw new IOException("Invalid Esteria selection catalog record " + i + ": " + name);
            }
        }
    }
    private static long readU32(RandomAccessFile file) throws IOException {
        return Integer.toUnsignedLong(Integer.reverseBytes(file.readInt()));
    }
    private static long u32(byte[] bytes, int at) {
        return (bytes[at] & 255L) | ((bytes[at + 1] & 255L) << 8) |
                ((bytes[at + 2] & 255L) << 16) | ((bytes[at + 3] & 255L) << 24);
    }
}
