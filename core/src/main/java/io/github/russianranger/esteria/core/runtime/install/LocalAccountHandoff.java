package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.EnumSet;

/** One-use ESTLOGN1 file for a stopped, owned launch view. The caller must first
 * verify the selected client capability and the live local account/services.
 * Close only after the client has stopped; a changed or foreign file is preserved.
 * PRoot and same-UID paths do not constitute a security boundary.
 */
public final class LocalAccountHandoff implements AutoCloseable {
    public static final String FILENAME = "Esteria-local-login.bin";
    public static final int BYTES = 57;
    private static final String ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    private final Path path;
    private final Object fileKey;
    private final byte[] digest;
    private boolean closed;

    private LocalAccountHandoff(Path path, Object fileKey, byte[] digest) {
        this.path = path; this.fileKey = fileKey; this.digest = digest;
    }

    /** Copies credentials without retaining their arrays. Caller owns and clears its inputs. */
    public static LocalAccountHandoff create(ClientLaunchView.Result view, char[] username, char[] password) throws IOException {
        return create(view, username, password, phase -> { });
    }

    interface CreationCheck { void reached(String phase) throws IOException; }
    static LocalAccountHandoff create(ClientLaunchView.Result view, char[] username, char[] password, CreationCheck check) throws IOException {
        RuntimeFiles.require(view != null, "Missing prepared client launch view");
        Path directory = view.directory.toAbsolutePath().normalize();
        RuntimeFiles.plain(directory.resolve(".owner"));
        RuntimeFiles.require(RuntimeFiles.smallText(directory.resolve(".owner"), 256).equals(
                "esteria-client-launch-v1\n" + view.generation + "\n"), "Client launch view ownership differs");
        RuntimeFiles.plain(directory.resolve("WowClient64.exe"));
        RuntimeFiles.require(username != null && username.length == 17 && password != null && password.length == 16,
                "Invalid owned local account length");
        RuntimeFiles.require(username[0] == 'E' && username[1] == 'S' && username[2] == 'T', "Invalid owned local account name");
        for (int i = 3; i < username.length; i++)
            RuntimeFiles.require("0123456789ABCDEF".indexOf(username[i]) >= 0, "Invalid owned local account name");
        for (char value : password) RuntimeFiles.require(ALPHABET.indexOf(value) >= 0, "Invalid owned local account password");
        byte[] record = new byte[BYTES], nonce = new byte[16];
        Path target = directory.resolve(FILENAME);
        Object createdKey = null;
        try {
            System.arraycopy("ESTLOGN1".getBytes(StandardCharsets.US_ASCII), 0, record, 0, 8);
            new SecureRandom().nextBytes(nonce); System.arraycopy(nonce, 0, record, 8, nonce.length);
            for (int i = 0; i < username.length; i++) record[24 + i] = (byte) username[i];
            for (int i = 0; i < password.length; i++) record[41 + i] = (byte) password[i];
            // CREATE_NEW rejects an interrupted handoff, foreign file, or link. Never replace it.
            try (FileChannel output = FileChannel.open(target,
                    EnumSet.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                createdKey = Files.readAttributes(target, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS).fileKey();
                RuntimeFiles.require(createdKey != null, "Local account handoff identity unavailable");
                check.reached("created");
                ByteBuffer data = ByteBuffer.wrap(record);
                while (data.hasRemaining()) output.write(data);
                check.reached("written");
                output.force(true);
            }
            BasicFileAttributes attributes = attributes(target);
            RuntimeFiles.require(attributes.size() == BYTES && createdKey.equals(attributes.fileKey()), "Local account handoff identity changed; preserved");
            byte[] expectedDigest = RuntimeFiles.digest().digest(record);
            RuntimeFiles.require(RuntimeFiles.hashFile(target, BYTES, RuntimeWork.NEVER_CANCELLED).equals(RuntimeFiles.hex(expectedDigest)),
                    "Local account handoff readback differs; preserved");
            RuntimeFiles.require(RuntimeFiles.sync(directory), "Local account handoff directory sync failed");
            check.reached("synced");
            return new LocalAccountHandoff(target, createdKey, expectedDigest);
        } catch (IOException | RuntimeException failure) {
            if (createdKey != null) {
                try { removeFailedCreation(target, createdKey, record); }
                catch (IOException | RuntimeException cleanup) { failure.addSuppressed(cleanup); }
            }
            throw failure;
        } finally { Arrays.fill(record, (byte) 0); Arrays.fill(nonce, (byte) 0); }
    }

    private static void removeFailedCreation(Path path, Object key, byte[] expected) throws IOException {
        byte[] bytes = new byte[BYTES + 1];
        try {
            BasicFileAttributes before;
            try { before = attributes(path); } catch (java.nio.file.NoSuchFileException absent) { return; }
            RuntimeFiles.require(key.equals(before.fileKey()) && before.size() <= BYTES,
                    "Failed local account handoff changed; preserved");
            try (FileChannel input = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer data = ByteBuffer.wrap(bytes);
                while (data.hasRemaining() && input.read(data) != -1) { }
                RuntimeFiles.require(data.position() == before.size(), "Failed local account handoff changed; preserved");
                for (int i = 0; i < data.position(); i++)
                    RuntimeFiles.require(bytes[i] == expected[i], "Failed local account handoff changed; preserved");
            }
            BasicFileAttributes after = attributes(path);
            RuntimeFiles.require(key.equals(after.fileKey()) && before.size() == after.size() &&
                    before.lastModifiedTime().equals(after.lastModifiedTime()), "Failed local account handoff changed; preserved");
            Files.delete(path);
            RuntimeFiles.require(RuntimeFiles.sync(path.getParent()), "Failed local account handoff cleanup sync failed");
        } finally { Arrays.fill(bytes, (byte) 0); }
    }

    private static BasicFileAttributes attributes(Path file) throws IOException {
        BasicFileAttributes value = Files.readAttributes(file, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
        RuntimeFiles.plain(file);
        RuntimeFiles.require(value.isRegularFile() && !value.isSymbolicLink(), "Local account handoff type changed; preserved");
        Object links = Files.getAttribute(file, "unix:nlink", LinkOption.NOFOLLOW_LINKS);
        RuntimeFiles.require(links instanceof Number && ((Number) links).longValue() == 1,
                "Local account handoff has multiple links; preserved");
        RuntimeFiles.require(Files.getPosixFilePermissions(file, LinkOption.NOFOLLOW_LINKS).equals(
                PosixFilePermissions.fromString("rw-------")), "Local account handoff permissions changed; preserved");
        return value;
    }

    /** The reader deletes its file before login. Remove only our unchanged, unconsumed file. */
    @Override public synchronized void close() throws IOException {
        if (closed) return;
        byte[] bytes = new byte[BYTES + 1];
        try {
            BasicFileAttributes before;
            try { before = attributes(path); }
            catch (java.nio.file.NoSuchFileException consumed) { closed = true; return; }
            RuntimeFiles.require(fileKey.equals(before.fileKey()) && before.size() == BYTES,
                    "Local account handoff identity changed; preserved");
            try (FileChannel input = FileChannel.open(path, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                ByteBuffer data = ByteBuffer.wrap(bytes);
                while (data.hasRemaining() && input.read(data) != -1) { /* At most 58 bytes. */ }
                MessageDigest actual = RuntimeFiles.digest(); actual.update(bytes, 0, BYTES);
                RuntimeFiles.require(data.position() == BYTES && MessageDigest.isEqual(digest,
                        actual.digest()), "Local account handoff changed; preserved");
            }
            BasicFileAttributes after = attributes(path);
            RuntimeFiles.require(fileKey.equals(after.fileKey()) && after.size() == BYTES &&
                    before.lastModifiedTime().equals(after.lastModifiedTime()), "Local account handoff changed during cleanup; preserved");
            Files.delete(path);
            RuntimeFiles.require(RuntimeFiles.sync(path.getParent()), "Local account handoff cleanup sync failed");
            closed = true;
        } finally { Arrays.fill(bytes, (byte) 0); if (closed) Arrays.fill(digest, (byte) 0); }
    }
}
