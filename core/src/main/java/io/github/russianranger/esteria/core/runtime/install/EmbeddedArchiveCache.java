package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;

/** Resumable private cache for immutable APK asset bytes; never performs network I/O. */
public final class EmbeddedArchiveCache {
    public interface Source { InputStream open(long offset) throws IOException; }
    private final Path root;
    private final boolean directorySync;
    public EmbeddedArchiveCache(Path directory) throws IOException {
        root = RuntimeFiles.directory(directory);
        directorySync = RuntimeFiles.sync(root);
    }
    public Path obtain(String name, long bytes, String sha, Source source,
            RuntimeWork.Progress progress, RuntimeWork.Cancellation cancellation) throws IOException {
        RuntimeFiles.hashPin(sha);
        RuntimeFiles.require(name != null && name.matches("[A-Za-z0-9._-]{1,128}") &&
                !name.equals(".") && !name.equals("..") && bytes > 0 && bytes <= (8L << 30), "Invalid embedded archive pin");
        String pin = "esteria-embedded-archive-v1\n" + name + "\n" + bytes + "\n" + sha + "\n";
        String id = RuntimeFiles.hashText(pin);
        Path archive = root.resolve(id + ".archive"), partial = root.resolve(id + ".partial");
        Path owner = root.resolve(id + ".owner"), receipt = root.resolve(id + ".verified");
        try (RuntimeFiles.Lock ignored = RuntimeFiles.lock(root)) {
            RuntimeWork.check(cancellation);
            if (Files.exists(archive, LinkOption.NOFOLLOW_LINKS)) {
                RuntimeFiles.plain(archive);
                RuntimeFiles.require(Files.size(archive) == bytes, "Cached embedded archive size differs; preserved");
                String proof = pin + Files.getLastModifiedTime(archive, LinkOption.NOFOLLOW_LINKS).toMillis() + "\n";
                if (!Files.exists(receipt, LinkOption.NOFOLLOW_LINKS) || !RuntimeFiles.smallText(receipt, 1024).equals(proof)) {
                    RuntimeFiles.require(RuntimeFiles.hashFile(archive, bytes, cancellation).equals(sha),
                            "Cached embedded archive hash differs; preserved");
                    RuntimeFiles.atomicText(receipt, proof, directorySync);
                }
                progress.update("embedded-runtime-cached", name, bytes, bytes);
                return archive;
            }
            if (Files.exists(owner, LinkOption.NOFOLLOW_LINKS))
                RuntimeFiles.require(RuntimeFiles.smallText(owner, 1024).equals(pin), "Embedded cache owner differs");
            else {
                RuntimeFiles.require(!Files.exists(partial, LinkOption.NOFOLLOW_LINKS), "Unowned embedded partial preserved");
                RuntimeFiles.atomicText(owner, pin, directorySync);
            }
            long offset = 0;
            if (Files.exists(partial, LinkOption.NOFOLLOW_LINKS)) {
                RuntimeFiles.plain(partial); offset = Files.size(partial);
                RuntimeFiles.require(offset <= bytes, "Embedded partial exceeds expected size");
            }
            RuntimeFiles.require(root.toFile().getUsableSpace() >= bytes - offset + (16L << 20),
                    "Insufficient storage for embedded runtime cache");
            MessageDigest hash = RuntimeFiles.digest();
            byte[] buffer = new byte[RuntimeFiles.BUFFER];
            if (offset > 0) {
                long total = 0;
                try (InputStream input = Files.newInputStream(partial, LinkOption.NOFOLLOW_LINKS)) {
                    for (int count; (count = input.read(buffer)) != -1;) {
                        RuntimeWork.check(cancellation); total += count;
                        RuntimeFiles.require(total <= offset, "Embedded partial changed"); hash.update(buffer, 0, count);
                        progress.update("verify-embedded-resume", name, total, offset);
                    }
                }
                RuntimeFiles.require(total == offset, "Embedded partial changed");
            }
            if (offset < bytes) {
                try (InputStream input = source.open(offset);
                     FileChannel output = FileChannel.open(partial, StandardOpenOption.CREATE,
                             StandardOpenOption.WRITE, LinkOption.NOFOLLOW_LINKS)) {
                    RuntimeFiles.privateMode(partial, false, false); output.position(offset);
                    long total = offset;
                    try {
                        for (int count; (count = input.read(buffer)) != -1;) {
                            RuntimeWork.check(cancellation);
                            RuntimeFiles.require(count <= bytes - total, "Embedded archive exceeds pinned size");
                            ByteBuffer block = ByteBuffer.wrap(buffer, 0, count);
                            while (block.hasRemaining()) output.write(block);
                            hash.update(buffer, 0, count); total += count;
                            progress.update("copy-embedded-runtime", name, total, bytes);
                        }
                        RuntimeFiles.require(total == bytes, "Embedded asset ended early; owned partial retained");
                    } finally { output.force(true); }
                }
            }
            RuntimeWork.check(cancellation);
            if (!RuntimeFiles.hex(hash.digest()).equals(sha)) {
                Files.deleteIfExists(partial);
                throw new IOException("Embedded runtime hash differs; active runtime preserved");
            }
            RuntimeFiles.plain(partial);
            RuntimeFiles.require(Files.size(partial) == bytes, "Embedded cache changed before publication");
            Files.move(partial, archive, StandardCopyOption.ATOMIC_MOVE);
            RuntimeFiles.require(!directorySync || RuntimeFiles.sync(root), "Embedded archive cache sync failed");
            RuntimeFiles.atomicText(receipt, pin + Files.getLastModifiedTime(archive, LinkOption.NOFOLLOW_LINKS).toMillis() + "\n", directorySync);
            progress.update("embedded-runtime-verified", name, bytes, bytes);
            return archive;
        }
    }
}
