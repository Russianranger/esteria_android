package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;

/** Actual private-filesystem/index guards; these bytes are not a qualified cache
 * producer or world data, and cannot enable the production fast path. */
public final class PreparedDataCachePinTests {
    interface Action{void run()throws Exception;}
    static void reject(Action action)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError("Unsafe cache index accepted");}
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static PreparedDataCachePin.Selection selected()throws Exception{return new PreparedDataCachePin.Selection("a".repeat(64),123,"b".repeat(64),"c".repeat(64),"d".repeat(64));}
    static void privateDirectories(Path root,Path target)throws Exception {
        Path at=root;for(Path part:root.relativize(target)){at=at.resolve(part);if(!Files.exists(at))Files.createDirectory(at);Files.setPosixFilePermissions(at,PosixFilePermissions.fromString("rwx------"));}
    }
    static Path candidate(Path root,String operation,byte[] raw)throws Exception {
        Path path=root.resolve("server-data-work/server-data/cache-candidates/"+operation+"/cache.jsonl");privateDirectories(root,path.getParent());
        Files.write(path,raw);Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rw-------"));return path;
    }
    static String hash(Path path)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");try(var input=Files.newInputStream(path)){byte[] block=new byte[65536];for(int got;(got=input.read(block))!=-1;)digest.update(block,0,got);}
        StringBuilder result=new StringBuilder();for(byte value:digest.digest())result.append(String.format("%02x",value&255));return result.toString();
    }
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("prepared-data-private-index-").toRealPath();int passed=0;
        try {
            var source=selected();String operation="1".repeat(32);
            check(PreparedDataCachePin.read(root,source)==null,"Missing index did not require full verification");
            check(!Files.exists(root.resolve("state")),"Read-only lookup created private state");passed++;
            Path input=candidate(root,operation,"unexecuted hash-index fixture\n".getBytes(StandardCharsets.US_ASCII));
            byte[] original=Files.readAllBytes(input);String digest=hash(input);
            PreparedDataCachePin first=PreparedDataCachePin.anchor(root,source,operation,Files.size(input),digest);
            check(first.file.startsWith(root.resolve("state/prepared-data-cache"))&&!first.file.startsWith(root.resolve("server-data-work")),"Guest path became cache authority");
            check(first.sha256.equals(digest)&&PreparedDataCachePin.read(root,source).sha256.equals(digest),"Private SHA anchor did not round trip");
            check(java.util.Arrays.equals(Files.readAllBytes(input),original),"Publisher changed owned source candidate");
            check(PreparedDataCachePin.read(root,new PreparedDataCachePin.Selection(source.generation,123,"f".repeat(64),source.helperGeneration,source.implementationSha256))==null,"Foreign receipt adopted existing proof");
            reject(()->PreparedDataCachePin.read(root,new PreparedDataCachePin.Selection(source.generation,124,source.receiptSha256,source.helperGeneration,source.implementationSha256)));passed++;
            Files.writeString(input,"source changed after anchoring\n");check(PreparedDataCachePin.read(root,source).sha256.equals(digest),"Private copy aliases writable candidate");
            Files.writeString(first.file,"tampered anchored bytes\n");reject(()->PreparedDataCachePin.read(root,source));
            String replacement=hash(input);PreparedDataCachePin second=PreparedDataCachePin.anchor(root,source,operation,Files.size(input),replacement);
            check(second.sha256.equals(replacement)&&Files.exists(first.file),"Explicit new proof did not preserve old generation");passed++;
            Path pin=second.file.resolveSibling("cache.pin");byte[] goodPin=Files.readAllBytes(pin);
            Files.write(pin,new String(goodPin,StandardCharsets.US_ASCII).replace("format=1\n","format=1\nformat=1\n").getBytes(StandardCharsets.US_ASCII));
            reject(()->PreparedDataCachePin.read(root,source));Files.write(pin,goodPin);
            Files.setPosixFilePermissions(second.file,PosixFilePermissions.fromString("rw-r--r--"));reject(()->PreparedDataCachePin.read(root,source));
            Files.setPosixFilePermissions(second.file,PosixFilePermissions.fromString("rw-------"));
            Path saved=second.file.resolveSibling("original");Files.move(second.file,saved);Files.createSymbolicLink(second.file,saved);
            reject(()->PreparedDataCachePin.read(root,source));Files.delete(second.file);Files.move(saved,second.file);
            Path alias=Files.createSymbolicLink(root.resolveSibling(root.getFileName()+"-alias"),root);
            try{reject(()->PreparedDataCachePin.read(alias,source));}finally{Files.delete(alias);}passed++;
            Path hardlink=root.resolve("external-cache-link");
            for(Path linked:new Path[]{input,second.file,pin,second.file.getParent().getParent().resolve("current")}) {
                Files.createLink(hardlink,linked);
                try {
                    if(linked.equals(input))reject(()->PreparedDataCachePin.anchor(root,source,operation,Files.size(input),replacement));
                    else reject(()->PreparedDataCachePin.read(root,source));
                }finally{Files.delete(hardlink);}
            }
            check(PreparedDataCachePin.read(root,source).sha256.equals(replacement),"Rejected aliases damaged retained index");passed++;
            reject(()->PreparedDataCachePin.anchor(root,source,"../foreign",1,"0".repeat(64)));
            reject(()->PreparedDataCachePin.anchor(root,source,operation,PreparedDataCachePin.MAX_CACHE_BYTES+1,replacement));
            reject(()->new PreparedDataCachePin.Selection("A".repeat(64),123,source.receiptSha256,source.helperGeneration,source.implementationSha256));
            reject(()->new PreparedDataCachePin.Selection(source.generation,0,source.receiptSha256,source.helperGeneration,source.implementationSha256));
            check(!PreparedDataCachePin.PRODUCTION_FAST_PATH_ENABLED,"Unqualified cache fast path enabled");passed++;
            String largeOperation="2".repeat(32);Path large=candidate(root,largeOperation,new byte[0]);long bytes=48L<<20;
            try(FileChannel channel=FileChannel.open(large,StandardOpenOption.WRITE)){channel.position(bytes-1);channel.write(ByteBuffer.wrap(new byte[]{0}));channel.force(true);}
            PreparedDataCachePin largePin=PreparedDataCachePin.anchor(root,source,largeOperation,bytes,hash(large));
            check(largePin.bytes==bytes&&PreparedDataCachePin.read(root,source).bytes==bytes,"Large private cache did not stream on bounded heap");passed++;
            System.out.println("Prepared data private SHA index passed"+passed+" actual filesystem groups at bounded heap; fast path OFF, no guest/data producer qualification");
        }finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    }
}
