package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.UUID;
import java.util.Map;
import java.util.Arrays;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/** Private source-owned receipt and kernel lease, never a caller-selected path
 * or PID. Unknown stages are preserved. Only opaque bounded record hashes are
 * read during recovery; credentials are not decoded. */
final class LocalHandoffRecovery implements AutoCloseable {
    static final String OWNER=".esteria-local-login.owner",LOCK=".esteria-local-login.lock";
    // POSIX record locks can be released by closing another descriptor for the
    // same inode in this process. Refuse a second local opener before any FD is
    // acquired, as well as holding the cross-process kernel lock.
    private static final Map<Path,Object> OWNERS=new ConcurrentHashMap<>();
    private final Path directory,lockPath;
    final Path stage,target;
    private final String generation;
    private final FileChannel channel;
    private final FileLock lock;
    private final Object lockKey;
    private final Object reservation;
    private Receipt expected;
    private boolean released;

    private LocalHandoffRecovery(Path directory,String generation,FileChannel channel,FileLock lock,Object key,Object reservation) {
        this.directory=directory;this.generation=generation;this.channel=channel;this.lock=lock;lockKey=key;
        this.reservation=reservation;
        lockPath=directory.resolve(LOCK);target=directory.resolve(LocalAccountHandoff.FILENAME);
        stage=directory.resolve(".esteria-local-login-data-"+token()+".pending");
    }
    private static String token(){return UUID.randomUUID().toString().replace("-","");}
    static LocalHandoffRecovery begin(Path directory,String generation)throws IOException {
        LocalHandoffRecovery owner=claim(directory,generation);
        try{owner.cleanup(null);return owner;}
        catch(IOException|RuntimeException failure){try{owner.close();}catch(IOException cleanup){failure.addSuppressed(cleanup);}throw failure;}
    }
    private static LocalHandoffRecovery claim(Path directory,String generation)throws IOException {
        RuntimeFiles.hashPin(generation);
        RuntimeFiles.require(directory.equals(directory.toRealPath()),"local-login-view-not-canonical");
        Object reservation=new Object();RuntimeFiles.require(OWNERS.putIfAbsent(directory,reservation)==null,"local-login-active-owner");
        Path path=directory.resolve(LOCK);FileChannel channel=null;FileLock lock=null;
        try {
            try{channel=newFile(path);}catch(java.nio.file.FileAlreadyExistsException existing){attributes(path,0);channel=FileChannel.open(path,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);}
            BasicFileAttributes before=attributes(path,0);
            try{lock=channel.tryLock();}catch(OverlappingFileLockException busy){throw new IOException("local-login-active-owner",busy);}
            RuntimeFiles.require(lock!=null,"local-login-active-owner");
            LocalHandoffRecovery owner=new LocalHandoffRecovery(directory,generation,channel,lock,before.fileKey(),reservation);
            owner.requireLease();return owner;
        }catch(IOException|RuntimeException failure){
            try{if(lock!=null)lock.release();}finally{try{if(channel!=null)channel.close();}finally{if(channel==null||!channel.isOpen())OWNERS.remove(directory,reservation);}}
            throw failure;
        }
    }
    void publish(Object stageKey,byte[] digest,LocalAccountHandoff.CreationCheck check)throws IOException {
        requireLease();BasicFileAttributes data=attributes(stage,LocalAccountHandoff.BYTES);
        RuntimeFiles.require(stageKey.equals(data.fileKey()),"local-login-stage-identity-changed");
        Proof proof=new Proof(generation,stage.getFileName().toString(),number(stage,"dev"),number(stage,"ino"),
                data.lastModifiedTime().to(TimeUnit.NANOSECONDS),RuntimeFiles.hex(digest));
        verify(stage,proof);
        byte[] raw=proof.text().getBytes(StandardCharsets.US_ASCII);
        Path temporary=directory.resolve(".esteria-local-login-proof-"+token()+".pending");Object key=null;
        try {
            try(FileChannel output=newFile(temporary)) {
                key=attributes(temporary,1024).fileKey();ByteBuffer bytes=ByteBuffer.wrap(raw);
                while(bytes.hasRemaining())output.write(bytes);output.force(true);
            }
            requireLease();moveNew(temporary,directory.resolve(OWNER));
        }catch(IOException|RuntimeException failure) {
            if(key!=null)try{LocalAccountHandoff.removeFailedCreation(temporary,key,raw);}
                catch(IOException|RuntimeException preserved){failure.addSuppressed(preserved);}
            throw failure;
        }
        RuntimeFiles.require(RuntimeFiles.sync(directory),"local-login-proof-sync-failed");
        expected=receipt();RuntimeFiles.require(expected.proof.text().equals(proof.text()),"local-login-proof-changed");
        check.reached("proof-synced");
        requireLease();verify(stage,proof);moveNew(stage,target);verify(target,proof);
        RuntimeFiles.require(RuntimeFiles.sync(directory),"local-login-publication-sync-failed");
    }
    void abort(Object stageKey,byte[] record)throws IOException {
        if(Files.exists(directory.resolve(OWNER),LinkOption.NOFOLLOW_LINKS))cleanup(expected);
        else if(stageKey!=null)LocalAccountHandoff.removeFailedCreation(stage,stageKey,record);
    }
    void finish()throws IOException {
        RuntimeFiles.require(expected!=null,"local-login-owner-proof-required");cleanup(expected);
    }
    void retryFinish()throws IOException {
        LocalHandoffRecovery retry=claim(directory,generation);
        try{RuntimeFiles.require(expected!=null,"local-login-owner-proof-required");retry.cleanup(expected);}
        finally{retry.close();}
    }
    private static FileChannel newFile(Path path)throws IOException {
        return FileChannel.open(path,java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
    }
    private static void moveNew(Path source,Path target)throws IOException {
        RuntimeFiles.require(source.getParent().equals(target.getParent())&&!Files.exists(target,LinkOption.NOFOLLOW_LINKS),"local-login-publication-target-exists");
        // No replace option: ATOMIC_MOVE can overwrite on Unix. Within this
        // canonical same parent, the Unix provider renames the existing inode.
        Files.move(source,target);
    }
    private static long number(Path path,String name)throws IOException {
        Object value=Files.getAttribute(path,"unix:"+name,LinkOption.NOFOLLOW_LINKS);
        RuntimeFiles.require(value instanceof Number,"local-login-file-identity-unavailable");return ((Number)value).longValue();
    }
    private static BasicFileAttributes attributes(Path path,int maximum)throws IOException {
        BasicFileAttributes value=LocalAccountHandoff.attributes(path);
        RuntimeFiles.require(value.fileKey()!=null&&value.size()<=maximum&&number(path,"uid")==number(path.getParent(),"uid"),"local-login-private-file-changed");return value;
    }
    private static boolean same(BasicFileAttributes before,BasicFileAttributes after) {
        return before.fileKey().equals(after.fileKey())&&before.size()==after.size()&&before.lastModifiedTime().equals(after.lastModifiedTime());
    }
    private void requireLease()throws IOException {
        RuntimeFiles.require(!released&&OWNERS.get(directory)==reservation&&lock.isValid()&&lockKey.equals(attributes(lockPath,0).fileKey())&&directory.equals(directory.toRealPath())&&
                RuntimeFiles.smallText(directory.resolve(".owner"),256).equals("esteria-client-launch-v1\n"+generation+"\n"),"local-login-owner-lease-changed");
    }
    private static void verify(Path path,Proof proof)throws IOException {
        BasicFileAttributes before=attributes(path,LocalAccountHandoff.BYTES);
        RuntimeFiles.require(before.size()==LocalAccountHandoff.BYTES&&number(path,"dev")==proof.device&&number(path,"ino")==proof.inode&&
                before.lastModifiedTime().to(TimeUnit.NANOSECONDS)==proof.modifiedNanos,"local-login-record-identity-changed");
        RuntimeFiles.require(opaqueHash(path).equals(proof.sha256),"local-login-record-changed");
        RuntimeFiles.require(same(before,attributes(path,LocalAccountHandoff.BYTES))&&number(path,"dev")==proof.device&&number(path,"ino")==proof.inode,"local-login-record-changed-during-read");
    }
    private static String opaqueHash(Path path)throws IOException {
        byte[] block=new byte[64];java.security.MessageDigest hash=RuntimeFiles.digest();int total=0;
        try(FileChannel input=FileChannel.open(path,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer bytes=ByteBuffer.wrap(block);
            for(int got;(got=input.read(bytes))!=-1;) {
                RuntimeFiles.require(got>0&&(total+=got)<=LocalAccountHandoff.BYTES,"local-login-record-length-changed");
                hash.update(block,0,got);bytes.clear();
            }
            RuntimeFiles.require(total==LocalAccountHandoff.BYTES,"local-login-record-length-changed");return RuntimeFiles.hex(hash.digest());
        }finally{Arrays.fill(block,(byte)0);}
    }
    private static final class Proof {
        final String generation,stage,sha256;final long device,inode,modifiedNanos;
        Proof(String generation,String stage,long device,long inode,long modifiedNanos,String sha256) {
            this.generation=generation;this.stage=stage;this.device=device;this.inode=inode;this.modifiedNanos=modifiedNanos;this.sha256=sha256;
        }
        String text(){return "esteria-local-handoff-owner-v1\nview="+generation+"\nstage="+stage+"\ndev="+device+"\nino="+inode+
                "\nmodifiedNanos="+modifiedNanos+"\nbytes=57\nsha256="+sha256+"\n";}
        static Proof parse(String raw,String generation)throws IOException {
            String[] rows=raw.split("\n",-1);
            RuntimeFiles.require(rows.length==9&&rows[0].equals("esteria-local-handoff-owner-v1")&&rows[1].equals("view="+generation)&&
                    rows[2].matches("stage=\\.esteria-local-login-data-[a-f0-9]{32}\\.pending")&&rows[3].matches("dev=-?[0-9]{1,20}")&&
                    rows[4].matches("ino=-?[0-9]{1,20}")&&rows[5].matches("modifiedNanos=-?[0-9]{1,20}")&&rows[6].equals("bytes=57")&&
                    rows[7].matches("sha256=[a-f0-9]{64}")&&rows[8].isEmpty(),"local-login-proof-invalid");
            try {
                Proof proof=new Proof(generation,rows[2].substring(6),Long.parseLong(rows[3].substring(4)),Long.parseLong(rows[4].substring(4)),
                        Long.parseLong(rows[5].substring(14)),rows[7].substring(7));
                RuntimeFiles.require(proof.text().equals(raw),"local-login-proof-noncanonical");return proof;
            }catch(NumberFormatException invalid){throw new IOException("local-login-proof-invalid",invalid);}
        }
    }
    private static final class Receipt {
        final Proof proof;final Object key;final String text;
        Receipt(Proof proof,Object key,String text){this.proof=proof;this.key=key;this.text=text;}
    }
    private Receipt receipt()throws IOException {
        Path path=directory.resolve(OWNER);BasicFileAttributes before=attributes(path,1024);
        String text=RuntimeFiles.smallText(path,1024);Proof proof=Proof.parse(text,generation);
        RuntimeFiles.require(same(before,attributes(path,1024)),"local-login-proof-changed-during-read");return new Receipt(proof,before.fileKey(),text);
    }
    private static void sameReceipt(Receipt a,Receipt b)throws IOException {
        RuntimeFiles.require(a.key.equals(b.key)&&a.text.equals(b.text),"local-login-proof-changed");
    }
    private void cleanup(Receipt expected)throws IOException {
        requireLease();Path path=directory.resolve(OWNER);
        if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS)) {
            RuntimeFiles.require(expected==null&&!Files.exists(target,LinkOption.NOFOLLOW_LINKS),"local-login-unrecognized-handoff-preserved");return;
        }
        Receipt observed=receipt();if(expected!=null)sameReceipt(expected,observed);
        Path pending=directory.resolve(observed.proof.stage);
        boolean targetExists=Files.exists(target,LinkOption.NOFOLLOW_LINKS),stageExists=Files.exists(pending,LinkOption.NOFOLLOW_LINKS);
        RuntimeFiles.require(!(targetExists&&stageExists),"local-login-multiple-records-preserved");
        if(targetExists||stageExists) {
            Path data=targetExists?target:pending;
            verify(data,observed.proof);sameReceipt(observed,receipt());requireLease();
            verify(data,observed.proof);Files.delete(data);
            RuntimeFiles.require(RuntimeFiles.sync(directory),"local-login-cleanup-sync-failed");
        }
        sameReceipt(observed,receipt());requireLease();Files.delete(path);
        RuntimeFiles.require(RuntimeFiles.sync(directory),"local-login-cleanup-sync-failed");
    }
    @Override public synchronized void close()throws IOException {
        if(released)return;
        try{if(lock.isValid())lock.release();}
        finally{try{channel.close();}finally{if(!channel.isOpen()){released=true;OWNERS.remove(directory,reservation);}}}
    }
}
