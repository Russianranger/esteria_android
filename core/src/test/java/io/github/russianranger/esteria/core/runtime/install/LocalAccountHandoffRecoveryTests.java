package io.github.russianranger.esteria.core.runtime.install;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/** Host-only real JVM SIGKILL/kernel-lock recovery. Never copied into Android
 * instrumentation: a host JVM, unlike an Android app, can launch this JDK. */
public final class LocalAccountHandoffRecoveryTests {
    private static final String GENERATION="a".repeat(64);
    private static final char[] USER="EST0123456789ABCD".toCharArray(),PASSWORD="ABCDEFGHJKLMNPQR".toCharArray();
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    @FunctionalInterface private interface Attempt{void run()throws Exception;}
    private static void fails(Attempt action)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError("Expected preserved/refused handoff");}
    private static ClientLaunchView.Result view(Path root){return new ClientLaunchView.Result(root,GENERATION,0,true,true);}
    private static Path setup()throws IOException {
        Path root=Files.createTempDirectory("esteria-handoff-recovery-").toRealPath();
        Files.writeString(root.resolve(".owner"),"esteria-client-launch-v1\n"+GENERATION+"\n");
        Files.write(root.resolve("WowClient64.exe"),new byte[]{77,90});
        Files.createDirectory(root.resolve("WTF"));Files.writeString(root.resolve("WTF/Config.wtf"),"PRESERVED_TEST_SETTINGS");
        Files.writeString(root.resolve("database-and-account-sibling"),"PRESERVED_TEST_ACCOUNT_AND_SAVE");
        Files.writeString(root.resolve(".esteria-local-login-data-"+"0".repeat(32)+".pending"),"UNRECOGNIZED_STAGE_PRESERVED");
        return root;
    }
    private static void remove(Path root)throws IOException {
        try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
    }
    private static void siblings(Path root)throws IOException {
        check(Files.readString(root.resolve("WTF/Config.wtf")).equals("PRESERVED_TEST_SETTINGS"),"Settings preserved");
        check(Files.readString(root.resolve("database-and-account-sibling")).equals("PRESERVED_TEST_ACCOUNT_AND_SAVE"),"Account/save sibling preserved");
        check(Files.readString(root.resolve(".esteria-local-login-data-"+"0".repeat(32)+".pending")).equals("UNRECOGNIZED_STAGE_PRESERVED"),"Unrecognized stage preserved");
    }
    private static Process child(Path root,String mode,String phase)throws IOException {
        return new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin/java").toString(),"-Xmx32m","-cp",
                System.getProperty("java.class.path"),LocalAccountHandoffRecoveryTests.class.getName(),mode,root.toString(),phase)
                .redirectErrorStream(true).start();
    }
    private static void crash(Path root,String phase)throws Exception {
        Process child=child(root,"--child",phase);var reader=Executors.newSingleThreadExecutor();
        try(BufferedReader lines=new BufferedReader(new InputStreamReader(child.getInputStream(),StandardCharsets.UTF_8))) {
            String line=reader.submit(lines::readLine).get(10,TimeUnit.SECONDS);
            check(("READY "+phase).equals(line),"Child reached the exact handoff durability boundary");
            child.destroyForcibly();check(child.waitFor(5,TimeUnit.SECONDS),"SIGKILL child must be reaped");
            check(child.exitValue()==137,"Actual Linux child termination must be SIGKILL");
        }finally {
            if(child.isAlive()){child.destroyForcibly();check(child.waitFor(5,TimeUnit.SECONDS),"Fixture child cleanup/reap");}
            reader.shutdownNow();check(reader.awaitTermination(2,TimeUnit.SECONDS),"Fixture reader terminates");
        }
    }
    private static void processDeath()throws Exception {
        for(String phase:new String[]{"created","written","proof-synced","synced","consumed"}) {
            Path root=setup();
            try {
                crash(root,phase);Map<Path,byte[]> unpublished=new LinkedHashMap<>();
                if(phase.equals("created")||phase.equals("written"))try(var paths=Files.list(root)) {
                    for(Path path:paths.toArray(Path[]::new))if(path.getFileName().toString().endsWith(".pending"))unpublished.put(path,Files.readAllBytes(path));
                }
                try(LocalAccountHandoff next=LocalAccountHandoff.create(view(root),USER,PASSWORD)) {
                    check(Files.size(root.resolve(LocalAccountHandoff.FILENAME))==57,"Relaunch publishes a fresh compatible record");
                    check(Files.isRegularFile(root.resolve(LocalHandoffRecovery.OWNER)),"Published handoff has a complete owner receipt");
                }
                check(!Files.exists(root.resolve(LocalAccountHandoff.FILENAME))&&!Files.exists(root.resolve(LocalHandoffRecovery.OWNER)),"Known stale and current records cleaned without replay");
                for(var entry:unpublished.entrySet())check(Arrays.equals(Files.readAllBytes(entry.getKey()),entry.getValue()),"Pre-proof orphan is preserved, not adopted");
                siblings(root);
            }finally{remove(root);}
        }
    }
    private static void activeOwner()throws Exception {
        Path root=setup();
        try(LocalAccountHandoff active=LocalAccountHandoff.create(view(root),USER,PASSWORD)) {
            byte[] prior=Files.readAllBytes(root.resolve(LocalAccountHandoff.FILENAME));
            fails(()->LocalAccountHandoff.create(view(root),USER,PASSWORD));
            Process competing=child(root,"--try","");
            try {check(competing.waitFor(10,TimeUnit.SECONDS)&&competing.exitValue()==0,"Another JVM must refuse the active kernel lease");}
            finally{if(competing.isAlive()){competing.destroyForcibly();check(competing.waitFor(5,TimeUnit.SECONDS),"Competing JVM reap");}}
            check(Arrays.equals(prior,Files.readAllBytes(root.resolve(LocalAccountHandoff.FILENAME))),"Active record unchanged");siblings(root);
        }finally{remove(root);}
    }
    private static void preservedFailures()throws Exception {
        for(String kind:new String[]{"changed","replaced","hardlink","symlink","proof","escaped-proof","proof-symlink","missing-proof"}) {
            Path root=setup();LocalAccountHandoff active=null;
            try {
                active=LocalAccountHandoff.create(view(root),USER,PASSWORD);
                Path data=root.resolve(LocalAccountHandoff.FILENAME),proof=root.resolve(LocalHandoffRecovery.OWNER);
                byte[] before=Files.readAllBytes(data);FileTime time=Files.getLastModifiedTime(data);
                if(kind.equals("changed")){before[56]^=1;Files.write(data,before);Files.setLastModifiedTime(data,time);}
                else if(kind.equals("replaced")){Files.move(data,root.resolve("original-record"));Files.write(data,before);Files.setPosixFilePermissions(data,PosixFilePermissions.fromString("rw-------"));Files.setLastModifiedTime(data,time);}
                else if(kind.equals("hardlink"))Files.createLink(root.resolve("record-alias"),data);
                else if(kind.equals("symlink")){Files.move(data,root.resolve("original-record"));Files.createSymbolicLink(data,root.resolve("database-and-account-sibling"));}
                else if(kind.equals("proof"))Files.writeString(proof,"UNRECOGNIZED_OWNER_PROOF\n");
                else if(kind.equals("escaped-proof"))Files.writeString(proof,Files.readString(proof).replaceFirst("stage=[^\\n]+","stage=../../database-and-account-sibling"));
                else if(kind.equals("proof-symlink")){Files.move(proof,root.resolve("original-proof"));Files.createSymbolicLink(proof,root.resolve("database-and-account-sibling"));}
                else Files.delete(proof);
                LocalAccountHandoff failed=active;fails(failed::close);
                check(Files.exists(data,LinkOption.NOFOLLOW_LINKS),"Changed/foreign record preserved");
                fails(()->LocalAccountHandoff.create(view(root),USER,PASSWORD));
                check(Files.exists(data,LinkOption.NOFOLLOW_LINKS),"Relaunch cannot silently repair a changed record");siblings(root);
            }finally {if(active!=null)try{active.close();}catch(IOException expected){}remove(root);}
        }
        Path root=setup();
        try {
            Path legacy=root.resolve(LocalAccountHandoff.FILENAME);Files.writeString(legacy,"UNRECOGNIZED_LEGACY_FILE");
            Files.setPosixFilePermissions(legacy,PosixFilePermissions.fromString("rw-------"));
            fails(()->LocalAccountHandoff.create(view(root),USER,PASSWORD));
            check(Files.readString(legacy).equals("UNRECOGNIZED_LEGACY_FILE"),"Unknown legacy file preserved");siblings(root);
        }finally{remove(root);}
        Path linkedRoot=setup();
        try {
            Files.createSymbolicLink(linkedRoot.resolve(LocalHandoffRecovery.LOCK),linkedRoot.resolve("database-and-account-sibling"));
            fails(()->LocalAccountHandoff.create(view(linkedRoot),USER,PASSWORD));
            check(Files.isSymbolicLink(linkedRoot.resolve(LocalHandoffRecovery.LOCK)),"Unknown lock link preserved");siblings(linkedRoot);
        }finally{remove(linkedRoot);}
    }
    private static void publicationFailure()throws Exception {
        Path root=setup();
        try {
            Path target=root.resolve(LocalAccountHandoff.FILENAME);
            fails(()->LocalAccountHandoff.create(view(root),USER,PASSWORD,phase->{
                if(phase.equals("proof-synced")){Files.writeString(target,"FOREIGN_PUBLICATION_TARGET");Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rw-------"));}
            }));
            check(Files.readString(target).equals("FOREIGN_PUBLICATION_TARGET"),"Publication never replaces an existing foreign target");
            siblings(root);
        }finally{remove(root);}
    }
    public static void main(String[] arguments)throws Exception {
        if(arguments.length>0) {
            Path root=Path.of(arguments[1]).toRealPath();
            if(arguments[0].equals("--try")) {
                try(LocalAccountHandoff ignored=LocalAccountHandoff.create(view(root),USER,PASSWORD)){throw new AssertionError("Active owner admitted in another JVM");}
                catch(IOException expected){return;}
            }
            String phase=arguments[2];
            try(LocalAccountHandoff retained=LocalAccountHandoff.create(view(root),USER,PASSWORD,reached->{
                if(reached.equals(phase))awaitKill(phase);
            })) {
                if(phase.equals("consumed")){Files.delete(root.resolve(LocalAccountHandoff.FILENAME));awaitKill(phase);}
                throw new AssertionError("Crash boundary not reached");
            }
        }
        check(System.getProperty("os.name").equals("Linux"),"SIGKILL fixture requires a Linux host");
        processDeath();activeOwner();preservedFailures();publicationFailure();
        System.out.println("Local handoff recovery:5 durability/consumed-boundary SIGKILL/relaunch fixtures, cross-JVM active lease and preserved foreign/sibling/link/proof fixtures PASS; host only, no Android/gameplay");
    }
    private static void awaitKill(String phase)throws IOException {
        System.out.println("READY "+phase);System.out.flush();
        for(;;)try{Thread.sleep(1000);}catch(InterruptedException failure){throw new IOException(failure);}
    }
}
