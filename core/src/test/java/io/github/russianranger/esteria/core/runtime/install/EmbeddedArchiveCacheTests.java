package io.github.russianranger.esteria.core.runtime.install;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

public final class EmbeddedArchiveCacheTests {
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private interface Throwing { void run() throws Exception; }
    private static void fails(Throwing operation) throws Exception {
        try { operation.run(); throw new AssertionError("Expected failure"); } catch (IOException expected) { }
    }
    public static void main(String[] args) throws Exception {
        Path root=Path.of(args[0]);Files.createDirectories(root);
        byte[] data=new byte[1024*1024];Arrays.fill(data,(byte)17);String sha=RuntimeFiles.hex(MessageDigest.getInstance("SHA-256").digest(data));
        EmbeddedArchiveCache cache=new EmbeddedArchiveCache(root.resolve("cache"));
        AtomicBoolean cancelled=new AtomicBoolean();AtomicLong resumed=new AtomicLong(-1);
        EmbeddedArchiveCache.Source source=offset->{resumed.set(offset);return new ByteArrayInputStream(data,(int)offset,data.length-(int)offset);};
        fails(()->cache.obtain("data.gz",data.length,sha,source,(phase,path,done,total)->{if(done>=262144)cancelled.set(true);},cancelled::get));
        cancelled.set(false);
        Path result=cache.obtain("data.gz",data.length,sha,source,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        check(resumed.get()>0);check(Arrays.equals(data,Files.readAllBytes(result)));
        Path reused=cache.obtain("data.gz",data.length,sha,offset->{throw new AssertionError("Cached asset reopened");},RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        check(reused.equals(result));
        byte[] altered=data.clone();altered[0]=18;Files.write(result,altered);Files.setLastModifiedTime(result,FileTime.fromMillis(Files.getLastModifiedTime(result).toMillis()+2000));
        fails(()->cache.obtain("data.gz",data.length,sha,source,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));check(Files.readAllBytes(result)[0]==18);
        EmbeddedArchiveCache shortCache=new EmbeddedArchiveCache(root.resolve("short"));
        fails(()->shortCache.obtain("data.gz",data.length,sha,offset->new ByteArrayInputStream(data,0,400000),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));
        resumed.set(-1);shortCache.obtain("data.gz",data.length,sha,source,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);check(resumed.get()==400000);
        EmbeddedArchiveCache invalid=new EmbeddedArchiveCache(root.resolve("invalid"));
        fails(()->invalid.obtain("data.gz",data.length,sha,offset->new ByteArrayInputStream(altered),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));
        check(Files.list(root.resolve("invalid")).noneMatch(p->p.toString().endsWith(".archive")));
        Path real=root.resolve("large-source");MessageDigest hash=MessageDigest.getInstance("SHA-256");byte[] block=new byte[65536];
        try(OutputStream output=Files.newOutputStream(real)){for(int i=0;i<1024;i++){block[0]=(byte)i;output.write(block);hash.update(block);}}
        String bigSha=RuntimeFiles.hex(hash.digest());EmbeddedArchiveCache big=new EmbeddedArchiveCache(root.resolve("large-cache"));
        Path copied=big.obtain("large.gz",64L<<20,bigSha,offset->{InputStream in=Files.newInputStream(real);in.skipNBytes(offset);return in;},RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        check(Files.size(copied)==(64L<<20));
        System.out.println("PASS: embedded cache cancellation/resume, reuse, corruption preservation, truncation recovery, rejection and64MiB streaming under32MiB heap");
    }
}
