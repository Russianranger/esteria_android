import io.github.russianranger.esteria.core.presentation.X11SessionPlan;
import java.nio.ByteBuffer;
import java.nio.channels.SeekableByteChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.SecureRandom;
import java.util.Arrays;
import java.util.Set;

/** Host-only fixture: execute the application's formatter without exporting its random cookie. */
public final class X11AuthorityFixture {
    private static void write(Path file, byte[] data) throws Exception {
        try (SeekableByteChannel out = Files.newByteChannel(file,
                Set.of(StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes = ByteBuffer.wrap(data);
            while (bytes.hasRemaining()) out.write(bytes);
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 3) throw new IllegalArgumentException("session, command output and display required");
        Path session = Path.of(args[0]);
        if (!Files.isDirectory(session, LinkOption.NOFOLLOW_LINKS) ||
                !Files.getPosixFilePermissions(session).equals(PosixFilePermissions.fromString("rwx------")))
            throw new IllegalArgumentException("fresh private session required");
        int display = Integer.parseInt(args[2]);
        byte[] cookie = new byte[16];
        new SecureRandom().nextBytes(cookie);
        byte[] wrong = cookie.clone(); wrong[0] ^= 1;
        try {
            write(session.resolve("Xauthority"), X11SessionPlan.authority(display, cookie));
            write(session.resolve("Xauthority-wrong"), X11SessionPlan.authority(display, wrong));
            write(Path.of(args[1]), (String.join("\n", X11SessionPlan.server(display)) + "\n")
                    .getBytes(StandardCharsets.US_ASCII));
        } finally { Arrays.fill(cookie, (byte) 0); Arrays.fill(wrong, (byte) 0); }
        System.out.println("ESTERIA_X11_AUTHORITY_FORMATTED");
    }
}
