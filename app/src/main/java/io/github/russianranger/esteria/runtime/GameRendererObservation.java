package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.SeekableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.FileTime;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** The pinned renderer opens its private vulkan.log in truncate mode at its first diagnostic.
 * Both observations take place under the exclusive client-work lease. */
final class GameRendererObservation {
    private static final int MAX_BYTES = 64 * 1024;
    private static final Pattern CHOSEN = Pattern.compile(
        "(?m)^\\[debug\\] vulkan: chose adapter [0-9]+ '([^'\\r\\n]{1,255})' out of [0-9]+: [^\\r\\n]{1,128}\\. "
        + "(integrated|discrete|cpu|virtual|other), api [^\\r\\n]{1,48}, driver [^\\r\\n]{1,64}, "
        + "VID ([0-9a-f]{4,8}) DID ([0-9a-f]{4,8})\\r?\\n");
    private final Path log;
    private final FileTime previousWrite;

    private GameRendererObservation(Path log, FileTime previousWrite) {
        this.log = log;
        this.previousWrite = previousWrite;
    }

    static GameRendererObservation beforeStart(Path work) {
        Path log = work.resolve("client-state/Logs/vulkan.log");
        try {
            if (!log.getParent().toRealPath().equals(log.getParent())) return null;
            try {
                BasicFileAttributes prior = Files.readAttributes(log, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
                return prior.isRegularFile() ? new GameRendererObservation(log, prior.lastModifiedTime()) : null;
            } catch (NoSuchFileException absent) {
                return new GameRendererObservation(log, null);
            }
        } catch (IOException | RuntimeException unavailable) {
            return null;
        }
    }

    String afterExit() {
        try {
            if (!log.getParent().toRealPath().equals(log.getParent())) return null;
            BasicFileAttributes current = Files.readAttributes(log, BasicFileAttributes.class, LinkOption.NOFOLLOW_LINKS);
            if (!current.isRegularFile() || current.lastModifiedTime().equals(previousWrite)) return null;
            ByteBuffer prefix = ByteBuffer.allocate((int)Math.min(current.size(), MAX_BYTES));
            try (SeekableByteChannel channel = Files.newByteChannel(log, StandardOpenOption.READ, LinkOption.NOFOLLOW_LINKS)) {
                while (prefix.hasRemaining() && channel.read(prefix) > 0) { /* Bounded prefix. */ }
            }
            prefix.flip();
            Matcher marker = CHOSEN.matcher(StandardCharsets.US_ASCII.decode(prefix));
            if (!marker.find()) return null;
            String name = marker.group(1).toLowerCase(Locale.ROOT);
            String type = marker.group(2), vendor = marker.group(3), device = marker.group(4);
            // Only fixed labels and hexadecimal IDs leave the private log.
            String model = "";
            if (type.equals("integrated") && vendor.equals("5143") && name.contains("740")) model = "Adreno 740 ";
            if (type.equals("cpu") && name.contains("llvmpipe")) model = "llvmpipe ";
            return model + type + " (VID " + vendor + ", DID " + device + ")";
        } catch (IOException | RuntimeException unavailable) {
            return null;
        }
    }
}
