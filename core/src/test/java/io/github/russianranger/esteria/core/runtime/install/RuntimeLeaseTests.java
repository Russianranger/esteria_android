package io.github.russianranger.esteria.core.runtime.install;

import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Comparator;
import java.util.concurrent.TimeUnit;

/** Real cross-JVM POSIX regression; a Java FileLock can stay nominally valid
 * after another descriptor's close has already released its kernel lock. */
public final class RuntimeLeaseTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    @FunctionalInterface private interface Attempt{void run()throws Exception;}
    private static void refused(Attempt attempt)throws Exception {
        try{attempt.run();}catch(IOException expected){return;}
        throw new AssertionError("Competing lease admitted");
    }
    private static void child(Path file,boolean admit)throws Exception {
        Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),
                "-Xmx32m","-cp",System.getProperty("java.class.path"),RuntimeLeaseTests.class.getName(),
                "--child",file.toString(),Boolean.toString(admit)).redirectErrorStream(true).start();
        try {
            check(child.waitFor(10,TimeUnit.SECONDS),"Cross-JVM acquisition deadline");
            String diagnostic=new String(child.getInputStream().readNBytes(4096),java.nio.charset.StandardCharsets.UTF_8);
            check(child.exitValue()==0,"Cross-JVM expected admission="+admit+": "+diagnostic);
        }finally {if(child.isAlive()){child.destroyForcibly();check(child.waitFor(5,TimeUnit.SECONDS),"Cross-JVM fixture reaped");}}
    }
    private static void rawNegativeControl(Path root)throws Exception {
        Path file=root.resolve("negative-control");
        try(FileChannel first=FileChannel.open(file,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);FileLock owner=first.tryLock()) {
            check(owner!=null,"Raw control acquired");child(file,false);
            try(FileChannel duplicate=FileChannel.open(file,StandardOpenOption.WRITE)) {
                try{duplicate.tryLock();throw new AssertionError("JVM overlap expected");}catch(OverlappingFileLockException expected){}
            }
            check(owner.isValid(),"Java still believes the control lock is valid");
            child(file,true); // Actual kernel exclusion has been lost.
        }
    }
    private static void fixedRuntimeLease(Path root)throws Exception {
        Path runtime=Files.createDirectory(root.resolve("runtime"));Path file=runtime.resolve(".lock");
        try(RuntimeFiles.Lock owner=RuntimeFiles.lock(runtime)) {
            child(file,false);
            for(int i=0;i<32;i++)refused(()->RuntimeFiles.lock(runtime));
            refused(()->ExclusiveFileLease.acquire(runtime.resolve("../runtime/.lock"),"already owned"));
            check(owner.lock.isValid(),"Original runtime owner remains valid");
            child(file,false);
        }
        child(file,true);
        ExclusiveFileLease retry=ExclusiveFileLease.acquire(file,"already owned");
        retry.close();retry.close();check(!retry.isValid(),"Closed lease is idempotent and invalid");
        try(ExclusiveFileLease next=ExclusiveFileLease.acquire(file,"already owned")){check(next.isValid(),"Next owner after close");child(file,false);}
    }
    private static void invalidPaths(Path root)throws Exception {
        Path target=Files.writeString(root.resolve("unrelated"),"PRESERVED");
        Path linked=root.resolve("symlink");Files.createSymbolicLink(linked,target);
        refused(()->ExclusiveFileLease.acquire(linked,"busy"));
        Path directory=Files.createDirectory(root.resolve("directory"));
        refused(()->ExclusiveFileLease.acquire(directory,"busy"));
        Path alias=root.resolve("parent-alias");Files.createSymbolicLink(alias,root);
        refused(()->ExclusiveFileLease.acquire(alias.resolve("new-lease"),"busy"));
        Path hardlink=root.resolve("hardlink");Files.createLink(hardlink,target);
        refused(()->ExclusiveFileLease.acquire(hardlink,"busy"));
        check(Files.readString(target).equals("PRESERVED"),"Invalid lease paths leave unrelated content unchanged");
        Files.delete(hardlink);
        try(ExclusiveFileLease recovered=ExclusiveFileLease.acquire(target,"busy")){check(recovered.isValid(),"Failed admission releases reservation");}
    }
    public static void main(String[] args)throws Exception {
        if(args.length>0) {
            boolean admitted=false;
            try(ExclusiveFileLease lease=ExclusiveFileLease.acquire(Path.of(args[1]),"owned")){admitted=true;}
            catch(IOException expected){}
            check(admitted==Boolean.parseBoolean(args[2]),"Unexpected kernel lease admission");return;
        }
        check(System.getProperty("os.name").equals("Linux"),"POSIX regression requires Linux");
        Path root=Files.createTempDirectory("esteria-runtime-lease-").toRealPath();
        try{rawNegativeControl(root);fixedRuntimeLease(root);invalidPaths(root);}
        finally{try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
        System.out.println("Runtime lease PASS: actual POSIX negative control, cross-JVM exclusion after32 duplicate refusals, canonical aliases, close/reacquire, foreign/link preservation; host only");
    }
}
