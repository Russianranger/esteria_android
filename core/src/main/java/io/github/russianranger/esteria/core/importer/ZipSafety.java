package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.file.Path;

/** Reads ZIP/ZIP64 central attributes absent from java.util.zip.ZipEntry. */
final class ZipSafety {
    private ZipSafety() {}

    static long inspect(Path zip, int maxEntries, GameDataImporter.Cancellation cancellation) throws IOException {
        if (cancellation == null) throw new IllegalArgumentException("Cancellation must not be null");
        try (RandomAccessFile f = new RandomAccessFile(zip.toFile(), "r")) {
            long end = -1;
            for (long at = f.length() - 22; at >= Math.max(0, f.length() - 65557); at--) {
                if (GameDataVerifier.u32(f, at) == 0x06054b50L && at + 22 + GameDataVerifier.u16(f, at + 20) == f.length()) { end = at; break; }
            }
            if (end < 0) throw new IOException("ZIP end directory is missing or truncated");
            if (GameDataVerifier.u16(f, end + 4) != 0 || GameDataVerifier.u16(f, end + 6) != 0) throw new IOException("Split ZIP archives are not supported");
            long diskEntries = GameDataVerifier.u16(f, end + 8), count = GameDataVerifier.u16(f, end + 10);
            long size = GameDataVerifier.u32(f, end + 12), offset = GameDataVerifier.u32(f, end + 16);
            long directoryEnd = end;
            if (count == 65535 || size == 0xffffffffL || offset == 0xffffffffL) {
                if (end < 20 || GameDataVerifier.u32(f, end - 20) != 0x07064b50L || GameDataVerifier.u32(f, end - 16) != 0 || GameDataVerifier.u32(f, end - 4) != 1)
                    throw new IOException("Invalid or split ZIP64 locator");
                long zip64 = GameDataVerifier.u64(f, end - 12);
                GameDataVerifier.range(f, zip64, 56);
                if (GameDataVerifier.u32(f, zip64) != 0x06064b50L || GameDataVerifier.u64(f, zip64 + 4) < 44 || GameDataVerifier.u32(f, zip64 + 16) != 0 || GameDataVerifier.u32(f, zip64 + 20) != 0)
                    throw new IOException("Invalid ZIP64 directory");
                diskEntries = GameDataVerifier.u64(f, zip64 + 24);
                count = GameDataVerifier.u64(f, zip64 + 32);
                size = GameDataVerifier.u64(f, zip64 + 40);
                offset = GameDataVerifier.u64(f, zip64 + 48);
                directoryEnd = zip64;
            }
            if (diskEntries != count || count > maxEntries) throw new IOException("Too many entries or split ZIP archive");
            GameDataVerifier.range(f, offset, size);
            if (offset + size != directoryEnd) throw new IOException("Unsupported trailing ZIP directory records");
            long at = offset;
            for (long i = 0; i < count; i++) {
                if (cancellation.isCancelled() || Thread.currentThread().isInterrupted()) throw new GameDataImporter.ImportCancelledException();
                GameDataVerifier.range(f, at, 46);
                if (GameDataVerifier.u32(f, at) != 0x02014b50L) throw new IOException("Invalid ZIP central directory entry");
                int madeBy = GameDataVerifier.u16(f, at + 4) >>> 8;
                int flags = GameDataVerifier.u16(f, at + 8), method = GameDataVerifier.u16(f, at + 10);
                if ((flags & 0x0041) != 0 || (method != 0 && method != 8)) throw new IOException("Encrypted or unsupported ZIP entry");
                long attributes = GameDataVerifier.u32(f, at + 38);
                if (madeBy == 3 || madeBy == 19) {
                    int type = (int) (attributes >>> 16) & 0170000;
                    if (type != 0 && type != 0100000 && type != 0040000) throw new IOException("ZIP symlinks and special files are forbidden");
                }
                if (GameDataVerifier.u16(f, at + 34) != 0) throw new IOException("Split ZIP entry");
                long next = at + 46 + GameDataVerifier.u16(f, at + 28) + GameDataVerifier.u16(f, at + 30) + GameDataVerifier.u16(f, at + 32);
                if (next > offset + size) throw new IOException("ZIP central directory overrun");
                at = next;
            }
            if (at != offset + size) throw new IOException("ZIP entry count does not match directory");
            return count;
        }
    }
}
