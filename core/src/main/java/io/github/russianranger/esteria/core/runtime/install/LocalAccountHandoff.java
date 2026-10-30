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
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.EnumSet;

/** One-use ESTLOGN1 file for a stopped, owned launch view. The caller must first
 * verify the selected client capability and the live local account/services.
 * Close only after the client has stopped; a changed or foreign file is preserved.
 * A kernel lease and durable private receipt recover only a known unconsumed
 * handoff after process death, without changing the selected client wire format.
 * PRoot and same-UID paths do not constitute a security boundary.
 */
public final class LocalAccountHandoff implements AutoCloseable {
    public static final String FILENAME = "Esteria-local-login.bin";
    public static final int BYTES = 57;
    private static final String ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
    private final byte[] digest;
    private final LocalHandoffRecovery owner;
    private boolean closed;
    private IOException closeFailure;

    private LocalAccountHandoff(byte[] digest, LocalHandoffRecovery owner) {
        this.digest = digest; this.owner = owner;
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
        LocalHandoffRecovery owner = LocalHandoffRecovery.begin(directory, view.generation);
        byte[] record = new byte[BYTES], nonce = new byte[16];
        Path target = owner.stage;
        Object createdKey = null;
        try {
            System.arraycopy("ESTLOGN1".getBytes(StandardCharsets.US_ASCII), 0, record, 0, 8);
            new SecureRandom().nextBytes(nonce); System.arraycopy(nonce, 0, record, 8, nonce.length);
            for (int i = 0; i < username.length; i++) record[24 + i] = (byte) username[i];
            for (int i = 0; i < password.length; i++) record[41 + i] = (byte) password[i];
            // Unique staging never replaces an unrecognized crash leftover.
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
            owner.publish(createdKey, expectedDigest, check);
            check.reached("synced");
            return new LocalAccountHandoff(expectedDigest, owner);
        } catch (IOException | RuntimeException failure) {
            try { owner.abort(createdKey, record); }
            catch (IOException | RuntimeException cleanup) { failure.addSuppressed(cleanup); }
            try { owner.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw new IOException("local-login-handoff-prepare-failed; preserved files require support export", failure);
        } finally { Arrays.fill(record, (byte) 0); Arrays.fill(nonce, (byte) 0); }
    }

    static void removeFailedCreation(Path path, Object key, byte[] expected) throws IOException {
        byte[] bytes = new byte[expected.length + 1];
        try {
            BasicFileAttributes before;
            try { before = attributes(path); } catch (java.nio.file.NoSuchFileException absent) { return; }
            RuntimeFiles.require(key.equals(before.fileKey()) && before.size() <= expected.length,
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

    static BasicFileAttributes attributes(Path file) throws IOException {
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

    /** The reader deletes its file before login. Remove only our unchanged,
     * recorded file. A failed cleanup releases the kernel lease, preserving the
     * invalid record/proof so another process cannot silently adopt it. */
    @Override public synchronized void close() throws IOException {
        if (closed) {
            if (closeFailure != null) { owner.close(); owner.retryFinish(); closeFailure = null; }
            return;
        }
        try { owner.finish(); }
        catch (IOException | RuntimeException failure) { closeFailure = new IOException("local-login-handoff-recovery-preserved; export support", failure); }
        finally {
            try { owner.close(); } catch (IOException failure) { if (closeFailure == null) closeFailure = failure; else closeFailure.addSuppressed(failure); }
            closed = true; Arrays.fill(digest, (byte) 0);
        }
        if (closeFailure != null) throw closeFailure;
    }
}
