package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;

/** Recognizes interrupted first use of the selected stock Wine 10.13 package.
 * Only a named repair may mutate the prefix. Its pending intent outlives a
 * killed owner, but cannot be reused for a different prefix or Wine install. */
public final class StockWinePrefix {
    public enum Status { ABSENT, NO_REPAIR, INCOMPLETE, RESUME, UNRECOGNIZED }
    private static final String ARCHIVE = "c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46";
    private static final String INF = "c2042873062d575d2700672e3187674240019f64e740e4f36e82cc90fe75b4c0";
    private static final LinkOption NOFOLLOW = LinkOption.NOFOLLOW_LINKS;
    private final Path work, runtime, prefix, pending;
    private final String archive;
    private Status state = Status.UNRECOGNIZED;
    private byte[] identity;
    private boolean complete;

    private StockWinePrefix(Path work, Path runtime, String archive) {
        this.work = work;
        this.runtime = runtime;
        this.archive = archive;
        prefix = work.resolve("home/.wine");
        pending = work.resolve(".stock-wine-prefix-repair-v1.pending");
    }

    public Status status() { return state; }
    public boolean requiresRepair() { return state == Status.INCOMPLETE || state == Status.RESUME; }

    public static StockWinePrefix inspect(Path clientWork, Path runtimeRoot, String wineArchiveSha256) {
        StockWinePrefix result = new StockWinePrefix(clientWork, runtimeRoot, wineArchiveSha256);
        try {
            result.state = result.classify();
        } catch (IOException | UnsupportedOperationException unavailable) {
            // Failure to establish this specific historical defect does not authorize an update.
            result.state = Status.UNRECOGNIZED;
        }
        return result;
    }

    private Status classify() throws IOException {
        if (!ARCHIVE.equals(archive) || !directory(work)) return Status.UNRECOGNIZED;
        boolean interruptedRepair = Files.exists(pending, NOFOLLOW);
        if (Files.notExists(prefix, NOFOLLOW)) return interruptedRepair ? Status.UNRECOGNIZED : Status.ABSENT;
        if (!directory(prefix)) return Status.UNRECOGNIZED;
        Path system32 = prefix.resolve("drive_c/windows/system32");
        if (!directory(system32)) return Status.UNRECOGNIZED;
        Path vulkanManifest = system32.resolve("winevulkan.json"), drivers = system32.resolve("driverstore");
        boolean manifest = regular(vulkanManifest) && Files.size(vulkanManifest) == 137;
        boolean driverStore = directory(drivers);
        if (!interruptedRepair && manifest && driverStore) return Status.NO_REPAIR;
        if ((!manifest && !Files.notExists(vulkanManifest, NOFOLLOW))
                || (!driverStore && !Files.notExists(drivers, NOFOLLOW))) return Status.UNRECOGNIZED;
        // Both were missing on the old, timestamp-matched Mono interruption.
        // An arbitrary missing/customized file in another prefix is insufficient.
        if (!interruptedRepair && (manifest || driverStore)) return Status.UNRECOGNIZED;

        Path inf = runtime.resolve("opt/wine/share/wine/wine.inf");
        Path marker = prefix.resolve(".update-timestamp");
        if (!directory(runtime) || !regular(inf) || !privateFile(marker) || !directory(prefix.resolve("dosdevices"))
                || !prefix.getFileSystem().getPath("../drive_c").equals(Files.readSymbolicLink(prefix.resolve("dosdevices/c:")))
                || !privateFile(prefix.resolve("user.reg")) || !privateFile(prefix.resolve("userdef.reg"))
                || !privateFile(prefix.resolve("system.reg"))) return Status.UNRECOGNIZED;
        long stamp = Files.getLastModifiedTime(inf, NOFOLLOW).toMillis() / 1000;
        byte[] expectedMarker = (stamp + "\r\n").getBytes(StandardCharsets.US_ASCII);
        if (!matches(marker, expectedMarker) || !pinned(inf, 58179, INF)
                || !matchesPrefixImages(system32)) return Status.UNRECOGNIZED;

        identity = ("esteria-stock-wine-prefix-repair-v1\n" + ARCHIVE + "\n" + INF + "\n"
                + inode(runtime) + "\n" + inode(prefix) + "\n" + stamp + "\n").getBytes(StandardCharsets.US_ASCII);
        if (interruptedRepair && (!privateFile(pending) || !matches(pending, identity))) return Status.UNRECOGNIZED;
        StockWinePrefixRegistry.Stage stage = StockWinePrefixRegistry.inspect(prefix);
        if (manifest && !pinned(vulkanManifest, 137, "b77c0e5163c2a0ad07fd6c3b3a00b05f8bd77efab10afc3d768a620c0bf3e56d"))
            return Status.UNRECOGNIZED;
        if (stage == StockWinePrefixRegistry.Stage.COMPLETE && manifest && driverStore) {
            complete = true;
            return Status.RESUME;
        }
        if (stage == StockWinePrefixRegistry.Stage.MISSING_DEFAULTS
                || (interruptedRepair && (stage == StockWinePrefixRegistry.Stage.RESUMABLE
                    || stage == StockWinePrefixRegistry.Stage.COMPLETE))) {
            if (StockWinePrefixRegistry.safeToUpdate(prefix))
                return interruptedRepair ? Status.RESUME : Status.INCOMPLETE;
        }
        return Status.UNRECOGNIZED;
    }

    private static boolean matchesPrefixImages(Path system32) throws IOException {
        return pinned(system32.resolve("wineboot.exe"), 589824,
                "a53dbf5b78a8ac0d1c1dd9712c2cfa5351e165c5c3ad6dd3ca206e556d761923")
                && pinned(system32.resolve("ntdll.dll"), 1769472,
                    "ee9faf7292b63a890ed1d42e65b79dffd83f7650d82f21d2d9b54a838aa2d6e4")
                && pinned(system32.resolve("kernel32.dll"), 1114112,
                    "366e1aeb898a451da12334ca74013df911f8a93dad1585c74588a55c14920dfa");
    }

    private StockWinePrefix recheck(ExclusiveFileLease owner) throws IOException {
        if (owner == null || !owner.owns(work.resolve(".client-launch-setup.lock")))
            throw new IOException("Stock Wine prefix repair needs the retained client-work lease");
        StockWinePrefix observed = inspect(work, runtime, archive);
        if (!requiresRepair() || !observed.requiresRepair() || !Arrays.equals(identity, observed.identity))
            throw new IOException("The selected Wine prefix or source changed before repair");
        return observed;
    }

    /** Commit a pending attempt before starting Wine. No successful receipt is inferred from it. */
    public void beginRepair(ExclusiveFileLease owner) throws IOException {
        StockWinePrefix observed = recheck(owner);
        if (observed.complete) throw new IOException("Wine prefix is already complete");
        if (observed.state == Status.RESUME) {
            syncDirectory(work);
            return;
        }
        Path temp = Files.createTempFile(work, ".stock-wine-prefix-attempt-", ".tmp");
        try {
            try (FileChannel output = FileChannel.open(temp, StandardOpenOption.WRITE, NOFOLLOW)) {
                ByteBuffer bytes = ByteBuffer.wrap(identity);
                while (bytes.hasRemaining()) output.write(bytes);
                output.force(true);
            }
            Files.move(temp, pending, StandardCopyOption.ATOMIC_MOVE);
            syncDirectory(work);
        } finally { Files.deleteIfExists(temp); }
    }

    /** Recover the case where the helper finished before the previous owner retired the intent. */
    public boolean finishVerifiedIfComplete(ExclusiveFileLease owner) throws IOException {
        StockWinePrefix observed = recheck(owner);
        if (observed.state != Status.RESUME || !observed.complete) return false;
        Files.delete(pending);
        syncDirectory(work);
        return true;
    }

    /** Called only after the named Wine update and its owned guest processes have exited. */
    public void finishRepair(ExclusiveFileLease owner) throws IOException {
        if (!finishVerifiedIfComplete(owner))
            throw new IOException("Wine update did not complete the selected stock prefix; retained repair can be retried");
    }

    private static void syncDirectory(Path dir) throws IOException {
        try (FileChannel channel = FileChannel.open(dir, StandardOpenOption.READ)) { channel.force(true); }
    }

    private static String inode(Path path) throws IOException {
        return Files.getAttribute(path, "unix:dev", NOFOLLOW) + ":" + Files.getAttribute(path, "unix:ino", NOFOLLOW);
    }
    private static boolean directory(Path path) throws IOException {
        return Files.isDirectory(path, NOFOLLOW) && path.equals(path.toRealPath());
    }
    private static boolean regular(Path path) throws IOException {
        return Files.isRegularFile(path, NOFOLLOW) && path.equals(path.toRealPath());
    }
    private static boolean privateFile(Path path) throws IOException {
        return regular(path) && ((Number) Files.getAttribute(path, "unix:nlink", NOFOLLOW)).intValue() == 1;
    }
    private static boolean matches(Path path, byte[] data) throws IOException {
        if (!regular(path) || Files.size(path) != data.length) return false;
        try (InputStream input = Files.newInputStream(path, NOFOLLOW)) {
            for (byte value : data) if (input.read() != (value & 255)) return false;
            return input.read() == -1;
        }
    }
    private static boolean pinned(Path path, int bytes, String expected) throws IOException {
        if (!regular(path) || Files.size(path) != bytes) return false;
        MessageDigest hash;
        try { hash = MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException absent) { throw new AssertionError(absent); }
        try (InputStream input = Files.newInputStream(path, NOFOLLOW)) {
            byte[] buffer = new byte[16384];
            int count, total = 0;
            while ((count = input.read(buffer)) > 0) {
                total += count;
                if (total > bytes) return false;
                hash.update(buffer, 0, count);
            }
            if (total != bytes) return false;
        }
        byte[] digest = hash.digest();
        for (int i = 0; i < digest.length; i++)
            if ((digest[i] & 255) != Integer.parseInt(expected.substring(i * 2, i * 2 + 2), 16)) return false;
        return true;
    }
}
