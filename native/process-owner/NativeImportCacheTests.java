package io.github.russianranger.esteria;

import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;

/** Real JNI/libc execution on Linux. File bytes and caller-owned descriptor survive advice. */
public final class NativeImportCacheTests {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    public static void main(String[] args) throws Exception {
        check(NativeImportCache.drop(-1,0,4096)==22,"Reject invalid descriptors");
        check(NativeImportCache.drop(1,-1,4096)==22,"Reject negative offsets");
        check(NativeImportCache.drop(1,0,0)==22,"Zero length must not mean the entire file");
        check(NativeImportCache.drop(1,Long.MAX_VALUE,1)==22,"Reject range overflow");
        Path path=Files.createTempFile("esteria-import-cache-", ".bin");
        try (RandomAccessFile file=new RandomAccessFile(path.toFile(),"rw")) {
            byte[] bytes=new byte[32768]; for(int i=0;i<bytes.length;i++)bytes[i]=(byte)(i*31);
            file.write(bytes); file.getFD().sync();
            // Enumerate this process's descriptors without reflective/private JVM fields.
            int fd=-1;
            try(var descriptors=Files.list(Path.of("/proc/self/fd"))) {
                for(Path candidate:(Iterable<Path>)descriptors::iterator) {
                    try { if(Files.readSymbolicLink(candidate).equals(path))fd=Integer.parseInt(candidate.getFileName().toString()); }
                    catch(java.io.IOException ignored) { }
                }
            }
            check(fd>=0,"Locate the real open fixture descriptor");
            check(NativeImportCache.drop(fd,0,16384)==0,"Kernel accepts completed-window advice");
            check(NativeImportCache.drop(fd,16384,16384)==0,"Kernel accepts later-window advice");
            check(file.length()==bytes.length,"Advice does not truncate");
            file.seek(0); byte[] actual=new byte[bytes.length]; file.readFully(actual);
            check(Arrays.equals(bytes,actual),"Advice preserves every byte and leaves descriptor open");
            file.seek(bytes.length); file.write(7); file.getFD().sync();
            check(file.length()==bytes.length+1,"Caller can continue writing after advice");
        } finally { Files.delete(path); }
        System.out.println("PASS native import cache: invalid ranges, real synced windows, bytes and descriptor ownership");
    }
}
