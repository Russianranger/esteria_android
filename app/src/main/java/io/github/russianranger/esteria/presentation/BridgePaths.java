package io.github.russianranger.esteria.presentation;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;

/** Socket endpoints are contained in one caller-owned private session directory. */
final class BridgePaths {
    private BridgePaths() {}
    static Path directory(Context context, File directory) throws IOException {
        Path root = context.getFilesDir().toPath().toRealPath();
        Path path = directory.toPath().toAbsolutePath().normalize();
        if (!path.startsWith(root)) throw new IOException("Bridge directory is outside private application files");
        Path current = root;
        for (Path part : root.relativize(path)) {
            current = current.resolve(part);
            if (!Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Bridge directory must not contain links");
        }
        try {
            StructStat stat = Os.lstat(path.toString());
            if (stat.st_uid != android.os.Process.myUid() || (stat.st_mode & 0077) != 0)
                throw new IOException("Bridge directory must be private to this application");
        } catch (ErrnoException exception) { throw new IOException("Cannot inspect bridge directory", exception); }
        return path;
    }
    static String endpoint(Path directory, String name, boolean mustExist) throws IOException {
        Path path = directory.resolve(name);
        String value = path.toString();
        if (value.getBytes(StandardCharsets.UTF_8).length >= 108)
            throw new IOException("Private bridge socket path is too long");
        if (mustExist) {
            try {
                StructStat stat = Os.lstat(value);
                if (!OsConstants.S_ISSOCK(stat.st_mode) || stat.st_uid != android.os.Process.myUid() ||
                        (stat.st_mode & 0077) != 0) throw new IOException("Bridge endpoint is not a private owned socket");
            } catch (ErrnoException exception) { throw new IOException("Bridge endpoint is unavailable", exception); }
        } else if (Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            throw new IOException("Bridge endpoint already exists; previous ownership must be resolved first");
        }
        return value;
    }
    static void deleteOwnedSocket(String path, long device, long inode) throws IOException {
        try {
            StructStat now = Os.lstat(path);
            if (!OsConstants.S_ISSOCK(now.st_mode) || now.st_dev != device || now.st_ino != inode)
                throw new IOException("Bridge socket identity changed before cleanup");
            Files.deleteIfExists(Paths.get(path));
        } catch (ErrnoException exception) {
            if (exception.errno != OsConstants.ENOENT) throw new IOException("Bridge socket cleanup failed", exception);
        }
    }
}
