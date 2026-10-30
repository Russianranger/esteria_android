package io.github.russianranger.esteria.core.runtime.install;

import java.io.ByteArrayOutputStream;
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
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.UUID;

/** Exact SHA authority from the fixed private index, never imported game data.
 * No production fast path is enabled by this class. The publisher remains
 * package-private until a source-owned Android full-verification adapter and
 * actual Android/PRoot stat qualification are integrated. */
public final class PreparedDataCachePin {
    public static final boolean PRODUCTION_FAST_PATH_ENABLED=false;
    public static final long MAX_CACHE_BYTES=128L<<20;
    private static final String STORE="state/prepared-data-cache";
    private static final Set<String> FIELDS=Set.of("format","scope","generation","receiptBytes","receiptSha256",
        "helperGeneration","implementationSha256","cacheBytes","cacheSha256");
    public static final class Selection {
        public final String generation,receiptSha256,helperGeneration,implementationSha256;
        public final long receiptBytes;
        /** Values come from typed current data/helper selection, not an Intent. */
        public Selection(String generation,long receiptBytes,String receiptSha256,String helperGeneration,String implementationSha256)throws IOException {
            hash(generation);hash(receiptSha256);hash(helperGeneration);hash(implementationSha256);
            require(receiptBytes>0&&receiptBytes<=(64L<<20),"Bounded prepared-data receipt required");
            this.generation=generation;this.receiptBytes=receiptBytes;this.receiptSha256=receiptSha256;
            this.helperGeneration=helperGeneration;this.implementationSha256=implementationSha256;
        }
    }
    public final Selection selection;
    public final Path file;
    public final long bytes;
    public final String sha256;
    private PreparedDataCachePin(Selection selection,Path file,long bytes,String sha256) {
        this.selection=selection;this.file=file;this.bytes=bytes;this.sha256=sha256;
    }
    /** Missing index means full verification. Invalid or foreign state fails
     * visibly; it never becomes a caller-selected cache or an implicit success. */
    public static PreparedDataCachePin read(Path applicationRoot,Selection selected)throws IOException {
        Path root=root(applicationRoot),key=key(root,selected);
        if(!existingDirectories(root,key))return null;
        Path pointer=key.resolve("current");if(!Files.exists(pointer,LinkOption.NOFOLLOW_LINKS))return null;
        String chosen=new String(small(pointer,65),StandardCharsets.US_ASCII);
        require(chosen.matches("[0-9a-f]{64}\\n"),"Invalid private prepared-data cache pointer");
        chosen=chosen.substring(0,64);Path generation=key.resolve(chosen);
        require(existingDirectories(root,generation),"Private cache generation missing");
        Map<String,String> fields=properties(small(generation.resolve("cache.pin"),2048));
        require(fields.keySet().equals(FIELDS)&&"1".equals(fields.get("format"))&&
            "private-prepared-data-cache-sha-anchor".equals(fields.get("scope"))&&
            selected.generation.equals(fields.get("generation"))&&Long.toString(selected.receiptBytes).equals(fields.get("receiptBytes"))&&
            selected.receiptSha256.equals(fields.get("receiptSha256"))&&selected.helperGeneration.equals(fields.get("helperGeneration"))&&
            selected.implementationSha256.equals(fields.get("implementationSha256"))&&chosen.equals(fields.get("cacheSha256")),
            "Private prepared-data cache source/receipt/helper binding differs");
        long bytes=number(fields.get("cacheBytes"));require(bytes>0&&bytes<=MAX_CACHE_BYTES,"Private cache size exceeds bound");
        Path file=generation.resolve("cache.jsonl");require(identity(file,bytes).equals(chosen),"Private prepared-data cache bytes changed");
        return new PreparedDataCachePin(selected,file,bytes,chosen);
    }
    /** Internal publisher only. Future Android callers must additionally prove
     * the exact source-owned full-verification child completed successfully.
     * There is deliberately no public user-path/boolean publication API. */
    static PreparedDataCachePin anchor(Path applicationRoot,Selection selected,String operation,long expectedBytes,String expectedSha)throws IOException {
        Path root=root(applicationRoot);require(operation!=null&&operation.matches("[0-9a-f]{32}"),"Owned cache operation required");
        hash(expectedSha);require(expectedBytes>0&&expectedBytes<=MAX_CACHE_BYTES,"Bounded verified cache required");
        Path candidate=root.resolve("server-data-work/server-data/cache-candidates/"+operation+"/cache.jsonl");
        require(existingDirectories(root,candidate.getParent()),"Owned cache candidate directory missing");
        require(identity(candidate,expectedBytes).equals(expectedSha),"Owned cache candidate bytes differ");
        Path key=key(root,selected);directories(root,key);Path destination=key.resolve(expectedSha);
        if(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS)) {
            Path stage=Files.createDirectory(key.resolve(".pending-"+UUID.randomUUID()),PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            try {
                Path file=stage.resolve("cache.jsonl");copy(candidate,file,expectedBytes,expectedSha);
                write(stage.resolve("cache.pin"),description(selected,expectedBytes,expectedSha));
                sync(stage);Files.move(stage,destination,StandardCopyOption.ATOMIC_MOVE);sync(key);
            }finally{
                if(Files.exists(stage,LinkOption.NOFOLLOW_LINKS)) {
                    Files.deleteIfExists(stage.resolve("cache.jsonl"));Files.deleteIfExists(stage.resolve("cache.pin"));Files.delete(stage);
                }
            }
        } else {
            require(existingDirectories(root,destination)&&identity(destination.resolve("cache.jsonl"),expectedBytes).equals(expectedSha)&&
                java.util.Arrays.equals(small(destination.resolve("cache.pin"),2048),description(selected,expectedBytes,expectedSha)),
                "Existing private cache generation changed; original retained");
        }
        Path next=key.resolve(".current-"+UUID.randomUUID());
        try{write(next,(expectedSha+"\n").getBytes(StandardCharsets.US_ASCII));Files.move(next,key.resolve("current"),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);sync(key);}
        finally{Files.deleteIfExists(next);}
        return read(root,selected);
    }
    private static byte[] description(Selection s,long bytes,String sha) {
        return ("format=1\nscope=private-prepared-data-cache-sha-anchor\ngeneration="+s.generation+"\nreceiptBytes="+s.receiptBytes+
            "\nreceiptSha256="+s.receiptSha256+"\nhelperGeneration="+s.helperGeneration+"\nimplementationSha256="+s.implementationSha256+
            "\ncacheBytes="+bytes+"\ncacheSha256="+sha+"\n").getBytes(StandardCharsets.US_ASCII);
    }
    private static Path key(Path root,Selection s){return root.resolve(STORE).resolve(s.generation).resolve(s.receiptSha256).resolve(s.helperGeneration).resolve(s.implementationSha256);}
    private static Path root(Path path)throws IOException {require(path!=null&&path.isAbsolute()&&path.normalize().equals(path)&&Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)&&path.toRealPath().equals(path),"Canonical private application root required");return path;}
    private static boolean existingDirectories(Path root,Path target)throws IOException {
        Path cursor=root;
        for(Path part:root.relativize(target)) {
            cursor=cursor.resolve(part);if(!Files.exists(cursor,LinkOption.NOFOLLOW_LINKS))return false;
            require(Files.isDirectory(cursor,LinkOption.NOFOLLOW_LINKS)&&cursor.toRealPath().equals(cursor)&&
                PosixFilePermissions.toString(Files.getPosixFilePermissions(cursor,LinkOption.NOFOLLOW_LINKS)).equals("rwx------"),
                "Private prepared-data cache contains a link or non-private directory");
        }
        return true;
    }
    private static void directories(Path root,Path target)throws IOException {
        Path cursor=root;
        for(Path part:root.relativize(target)) {
            cursor=cursor.resolve(part);if(!Files.exists(cursor,LinkOption.NOFOLLOW_LINKS))Files.createDirectory(cursor,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            require(existingDirectories(root,cursor),"Private cache directory creation failed");
        }
    }
    private static BasicFileAttributes plain(Path path)throws IOException {
        require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&path.toRealPath().equals(path)&&
            PosixFilePermissions.toString(Files.getPosixFilePermissions(path,LinkOption.NOFOLLOW_LINKS)).equals("rw-------"),
            "Private regular cache file required");
        final Object links;
        try{links=Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS);}
        catch(UnsupportedOperationException unsupported){throw new IOException("Private cache hard-link checks unavailable; full verification required",unsupported);}
        require(links instanceof Number&&((Number)links).longValue()==1,"Private cache file has multiple links; preserved");
        return Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
    }
    private static String identity(Path path,long bytes)throws IOException {
        BasicFileAttributes before=plain(path);require(before.size()==bytes&&bytes>0&&bytes<=MAX_CACHE_BYTES,"Private cache byte count differs");
        MessageDigest digest=digest();long read=0;
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] buffer=new byte[65536];for(int got;(got=input.read(buffer))!=-1;){read+=got;require(read<=bytes,"Private cache grew");digest.update(buffer,0,got);}
        }
        BasicFileAttributes after=plain(path);require(read==bytes&&same(before,after),"Private cache changed while hashing");return hex(digest.digest());
    }
    private static void copy(Path source,Path destination,long bytes,String sha)throws IOException {
        BasicFileAttributes before=plain(source);MessageDigest digest=digest();long count=0;
        try(InputStream input=Files.newInputStream(source,LinkOption.NOFOLLOW_LINKS);
                FileChannel output=FileChannel.open(destination,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            Files.setPosixFilePermissions(destination,PosixFilePermissions.fromString("rw-------"));byte[] buffer=new byte[65536];
            for(int got;(got=input.read(buffer))!=-1;){count+=got;require(count<=bytes,"Cache candidate grew while copying");digest.update(buffer,0,got);ByteBuffer block=ByteBuffer.wrap(buffer,0,got);while(block.hasRemaining())output.write(block);}
            output.force(true);
        }
        require(count==bytes&&hex(digest.digest()).equals(sha)&&same(before,plain(source)),"Cache candidate changed while copying");
    }
    private static byte[] small(Path path,int maximum)throws IOException {
        BasicFileAttributes before=plain(path);require(before.size()<=maximum,"Private cache metadata exceeds bound");
        ByteArrayOutputStream output=new ByteArrayOutputStream();
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){byte[] buffer=new byte[256];for(int got;(got=input.read(buffer))!=-1;){require(output.size()+got<=maximum,"Private cache metadata grew");output.write(buffer,0,got);}}
        require(same(before,plain(path)),"Private cache metadata changed");return output.toByteArray();
    }
    private static Map<String,String> properties(byte[] raw)throws IOException {
        require(raw.length>0&&raw[raw.length-1]=='\n',"Incomplete private cache pin");Map<String,String> result=new HashMap<>();
        for(byte value:raw)require(value=='\n'||value>=32&&value<=126,"Private cache pin must be strict ASCII");
        String[] lines=new String(raw,StandardCharsets.US_ASCII).split("\n",-1);require(lines.length==FIELDS.size()+1,"Private cache pin field count differs");
        for(int i=0;i<lines.length-1;i++){int equal=lines[i].indexOf('=');require(equal>0&&lines[i].indexOf('=',equal+1)<0&&result.put(lines[i].substring(0,equal),lines[i].substring(equal+1))==null,"Duplicate or invalid private cache pin field");}
        return result;
    }
    private static long number(String text)throws IOException {try{long value=Long.parseLong(text);require(Long.toString(value).equals(text),"Noncanonical private cache byte count");return value;}catch(RuntimeException error){throw new IOException("Invalid private cache byte count",error);}}
    private static void write(Path path,byte[] raw)throws IOException {try(FileChannel output=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)){Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));ByteBuffer value=ByteBuffer.wrap(raw);while(value.hasRemaining())output.write(value);output.force(true);}}
    private static void sync(Path directory)throws IOException {try(FileChannel channel=FileChannel.open(directory,StandardOpenOption.READ)){channel.force(true);}}
    private static boolean same(BasicFileAttributes a,BasicFileAttributes b){return a.size()==b.size()&&a.lastModifiedTime().equals(b.lastModifiedTime())&&Objects.equals(a.fileKey(),b.fileKey());}
    private static void hash(String value)throws IOException {require(value!=null&&value.matches("[0-9a-f]{64}"),"Exact private cache hash required");}
    private static MessageDigest digest(){try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException impossible){throw new AssertionError(impossible);}}
    private static String hex(byte[] raw){StringBuilder result=new StringBuilder(64);for(byte value:raw)result.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return result.toString();}
    private static void require(boolean condition,String message)throws IOException {if(!condition)throw new IOException(message);}
}
