package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.UUID;

final class RuntimeFiles {
    static final int BUFFER = 128 * 1024;
    static void require(boolean value, String message) throws IOException { if (!value) throw new IOException(message); }
    static MessageDigest digest() {
        try { return MessageDigest.getInstance("SHA-256"); }
        catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    static String hex(byte[] data) {
        char[] result = new char[data.length * 2]; String digits = "0123456789abcdef";
        for (int i=0; i<data.length; i++) { result[i*2] = digits.charAt((data[i] & 255) >>> 4); result[i*2+1] = digits.charAt(data[i] & 15); }
        return new String(result);
    }
    static String hashText(String text) { return hex(digest().digest(text.getBytes(StandardCharsets.UTF_8))); }
    static void hashPin(String pin) throws IOException { require(pin != null && pin.matches("[0-9a-f]{64}"), "Runtime input needs an exact SHA-256"); }
    static Path directory(Path path) throws IOException {
        path = path.toAbsolutePath().normalize(); Path current = path.getRoot();
        for (Path part : path) {
            current = current.resolve(part);
            if (!Files.exists(current, LinkOption.NOFOLLOW_LINKS)) {
                try { Files.createDirectory(current); privateMode(current, true, false); }
                catch (java.nio.file.FileAlreadyExistsException raced) { /* Validate below. */ }
            }
            require(Files.isDirectory(current, LinkOption.NOFOLLOW_LINKS), "Runtime directory has a link or file ancestor");
        }
        return path;
    }
    static void plain(Path path) throws IOException {
        Path parent = path.toAbsolutePath().normalize().getParent();
        while (parent != null) {
            require(Files.isDirectory(parent, LinkOption.NOFOLLOW_LINKS), "Runtime input has a link ancestor"); parent = parent.getParent();
        }
        require(Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS), "Runtime input is not a regular file");
    }
    static void privateMode(Path path, boolean directory, boolean execute) throws IOException {
        try { Files.setPosixFilePermissions(path, PosixFilePermissions.fromString(directory || execute ? "rwx------" : "rw-------")); }
        catch (UnsupportedOperationException unsupported) {
            require(path.toFile().setReadable(false, false) && path.toFile().setWritable(false, false) &&
                path.toFile().setExecutable(false, false) && path.toFile().setReadable(true, true) &&
                path.toFile().setWritable(true, true) && (!(directory || execute) || path.toFile().setExecutable(true, true)), "Private runtime permissions unavailable");
        }
    }
    static String memberPath(String raw, int maxBytes) throws IOException {
        require(raw != null, "Missing runtime member path");
        if (raw.startsWith("./")) raw = raw.substring(2);
        while (raw.endsWith("/")) raw = raw.substring(0, raw.length()-1);
        require(!raw.isEmpty() && !raw.startsWith("/") && raw.getBytes(StandardCharsets.UTF_8).length <= maxBytes, "Unsafe runtime member path");
        for (String part : raw.split("/", -1)) require(!part.isEmpty() && !part.equals(".") && !part.equals(".."), "Unsafe runtime member component");
        for (int i=0; i<raw.length(); i++) require(raw.charAt(i) >= 32 && raw.charAt(i) != '\\', "Unsafe runtime member character");
        return raw;
    }
    static boolean sync(Path directory) {
        try (FileChannel channel = FileChannel.open(directory, StandardOpenOption.READ)) { channel.force(true); return true; }
        catch (IOException | UnsupportedOperationException failure) { return false; }
    }
    static void atomicText(Path target, String text, boolean directorySync) throws IOException {
        directory(target.getParent());
        if (Files.exists(target, LinkOption.NOFOLLOW_LINKS)) plain(target);
        Path temporary = target.resolveSibling("." + target.getFileName() + "-" + UUID.randomUUID());
        try {
            try (FileChannel output = FileChannel.open(temporary, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE)) {
                privateMode(temporary, false, false); ByteBuffer bytes = ByteBuffer.wrap(text.getBytes(StandardCharsets.UTF_8));
                while (bytes.hasRemaining()) output.write(bytes); output.force(true);
            }
            Files.move(temporary, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            require(!directorySync || sync(target.getParent()), "Runtime directory sync failed");
        } finally { Files.deleteIfExists(temporary); }
    }
    static String smallText(Path path, int max) throws IOException {
        plain(path); require(Files.size(path) <= max, "Oversized runtime metadata");
        try (InputStream input = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = new byte[max+1]; int used=0, count;
            while (used < bytes.length && (count=input.read(bytes,used,bytes.length-used)) != -1) used+=count;
            require(used <= max, "Runtime metadata grew during read");
            return new String(bytes,0,used,StandardCharsets.UTF_8);
        }
    }
    static String hashFile(Path path, long expected, RuntimeWork.Cancellation cancellation) throws IOException {
        plain(path); require(Files.size(path)==expected, "Runtime file size differs");
        MessageDigest digest = digest(); long total=0; byte[] buffer=new byte[BUFFER];
        try (InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            int count; while ((count=input.read(buffer))!=-1) { RuntimeWork.check(cancellation); total+=count; require(total<=expected,"Runtime file grew"); digest.update(buffer,0,count); }
        }
        require(total==expected,"Runtime file was truncated"); return hex(digest.digest());
    }
    static Lock lock(Path root) throws IOException {
        Path file=root.resolve(".lock"); if(Files.exists(file,LinkOption.NOFOLLOW_LINKS)) plain(file);
        FileChannel channel=FileChannel.open(file,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        try { FileLock lock=channel.tryLock(); require(lock!=null,"Runtime setup is already active"); return new Lock(channel,lock); }
        catch(IOException | OverlappingFileLockException error) { channel.close(); throw new IOException("Runtime setup is already active",error); }
    }
    static final class Lock implements AutoCloseable {
        final FileChannel channel; final FileLock lock;
        Lock(FileChannel channel,FileLock lock){this.channel=channel;this.lock=lock;}
        public void close() throws IOException {try{lock.release();}finally{channel.close();}}
    }
}
