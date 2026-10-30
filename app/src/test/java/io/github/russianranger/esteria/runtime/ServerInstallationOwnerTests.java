package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Host fault injection for private owner cleanup only. It deliberately creates
 * no provider proof, SQL process, Android service or complete installation. */
public final class ServerInstallationOwnerTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void set(Object target,String name,Object value) throws Exception {
        Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);field.set(target,value);
    }
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);
        final AtomicInteger stops=new AtomicInteger();
        final boolean delayed;
        Backend(boolean delayed){this.delayed=delayed;}
        @Override public long start(OwnedProcess.Specification specification){return 1;}
        @Override public int waitFor(long handle,long timeout){return OwnedProcess.RUNNING;}
        @Override public int terminate(long handle) throws IOException {
            stops.incrementAndGet();terminating.countDown();
            if(delayed)try{if(!release.await(30,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_CLEANUP_TIMEOUT");}
            catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
            return 1;
        }
        @Override public long[] diagnostics(long handle){return new long[5];}
    }
    private static OwnedProcess start(Backend backend,Path root) throws IOException {
        return OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture-executable"),List.of(),Map.of(),
            root,root.resolve("fixture-out"),root.resolve("fixture-err")),null);
    }
    private static ServerInstallationSetup.Handle owner(Path root,FreshServerInstallations.Attempt attempt,
            FreshServerInstallations.Workspace workspace) throws Exception {
        Constructor<ServerInstallationSetup.Handle> constructor=ServerInstallationSetup.Handle.class.getDeclaredConstructor(Context.class,
            Path.class,ServerRuntimeSetup.class,ServerProgramsSetup.class,ServerContentSetup.class,Path.class,
            FreshServerInstallations.Attempt.class,FreshServerInstallations.Workspace.class);
        constructor.setAccessible(true);return constructor.newInstance(null,root,null,null,null,root,attempt,workspace);
    }
    private static void fixture(String phase) throws Exception {
        Path root=Files.createTempDirectory("esteria-installation-owner-fixture-").toRealPath();
        Backend helperBackend=new Backend(true),databaseBackend=new Backend(false);
        OwnedProcess helper=null;ServerInstallationSetup.Handle owner=null;
        try {
            FreshServerInstallations store=new FreshServerInstallations(root);
            FreshServerInstallations.Selection selected=new FreshServerInstallations.Selection(Map.of("sourceLock","a".repeat(64),
                "runtimeArchive","b".repeat(64),"programsArchive","c".repeat(64),"contentReceipt","d".repeat(64),"compiledModules","e".repeat(64)));
            FreshServerInstallations.Attempt attempt=store.begin(selected,1);
            FreshServerInstallations.Workspace ownerWorkspace=attempt.retainWorkspace();Path work=ownerWorkspace.directory();
            Files.writeString(work.resolve("retained-partial-fixture"),"TEST_ONLY_PARTIAL_STATE\n");
            owner=owner(root,attempt,ownerWorkspace);set(owner,"state",ServerInstallationSetup.State.FAILED);
            set(owner,"setupProcessWorkspace",attempt.retainWorkspace());helper=start(helperBackend,root);
            Path lockPath=work.resolve(".android-database-setup.lock");
            FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            if(phase.equals("bootstrap")) {
                ServerDatabaseSetup.BootstrapLease bootstrap=new ServerDatabaseSetup.BootstrapLease(channel,lock);
                set(bootstrap,"process",helper);set(owner,"bootstrapLease",bootstrap);
            } else {
                set(owner,"setupProcess",helper);
                Constructor<ServerDatabaseService.Handle> constructor=ServerDatabaseService.Handle.class.getDeclaredConstructor(OwnedProcess.class,
                    FileChannel.class,FileLock.class,Path.class,String.class,String.class,Path.class,Path.class,FreshServerInstallations.Workspace.class);
                constructor.setAccessible(true);
                Object database=constructor.newInstance(start(databaseBackend,root),channel,lock,root.resolve("fixture-service"),"f".repeat(32),
                    "8.0.46",root,work,attempt.retainWorkspace());set(owner,"database",database);
            }
            if(phase.equals("installation")) {
                set(owner,"state",ServerInstallationSetup.State.STAGED_PENDING_PLAYERBOTS);
                try{owner.finishPlayerbots(null,()->false);throw new AssertionError("An unsealed/missing helper cannot run SQL");}
                catch(IOException expected){ }
                check(owner.state()==ServerInstallationSetup.State.STAGED_PENDING_PLAYERBOTS,"Missing provider preserves the staged owner");
                check(databaseBackend.stops.get()==0 && helperBackend.stops.get()==0,"Missing helper gate launches/stops no process");
                try{owner.stopAndPromote(Duration.ZERO);throw new AssertionError("Pending fourth schema cannot promote");}
                catch(IOException expected){ }
                set(owner,"state",ServerInstallationSetup.State.SCHEMAS_VERIFIED);
                try{owner.stopAndPromote(Duration.ZERO);throw new AssertionError("A state enum without a verified result cannot promote");}
                catch(IOException expected){ }
                check(!Files.exists(work.resolve("state/server-setup-complete.json")),"Refused completion writes no setup marker");
                check(databaseBackend.stops.get()==0,"Refused promotion keeps the live database owner");
                set(owner,"state",ServerInstallationSetup.State.FAILED);
            }
            try{owner.close(Duration.ZERO);throw new AssertionError("A live cleanup child must retain its installation owner");}
            catch(IOException expected){check(helper.isAlive(),"First timeout must occur while backend cleanup remains active");}
            check(helperBackend.terminating.getCount()==0,"Actual owner cleanup path must be reached");
            check(databaseBackend.stops.get()==0,"The database must not stop while the installation helper remains alive");
            check(lock.isValid(),"The bootstrap/database file lease must remain valid during child cleanup timeout");
            try{attempt.abandon("failed");throw new AssertionError("Live child token must block abandonment");}catch(IOException expected){ }
            try{store.begin(selected,1);throw new AssertionError("Another setup must not replace this owner");}catch(IOException expected){ }
            helperBackend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(helper.isAlive() && System.nanoTime()<deadline)Thread.sleep(1);
            check(!helper.isAlive(),"Retained helper can be settled before retrying close");
            try{owner.close(Duration.ofSeconds(1));}catch(IOException expected){ /* Forced fixture shutdown stays visible. */ }
            check(owner.state()==ServerInstallationSetup.State.CLOSED,"Retry releases ownership only after both children settle");
            check(Files.readString(work.resolve("retained-partial-fixture")).equals("TEST_ONLY_PARTIAL_STATE\n"),"Failed staging bytes remain intact");
            try(FreshServerInstallations.Attempt retry=store.begin(selected,1)){check(!retry.slotId.equals(attempt.slotId),"Retry allocates a fresh slot");}
        } finally {
            helperBackend.release.countDown();
            if(helper!=null && helper.isAlive())try{helper.stop(Duration.ZERO);}catch(IOException expected){ }
            if(owner!=null && owner.state()!=ServerInstallationSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException expected){ }
            try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
        }
    }
    private static void legacyFixture() throws Exception {
        Path root=Files.createTempDirectory("esteria-legacy-bootstrap-owner-fixture-").toRealPath();
        Backend backend=new Backend(true);OwnedProcess helper=null;
        try {
            Path lockPath=root.resolve(".android-database-setup.lock");
            FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            ServerDatabaseSetup.BootstrapLease ownership=new ServerDatabaseSetup.BootstrapLease(channel,lock);
            ServerDatabaseSetup.retainLegacy(root,ownership);
            // A concurrent legacy prepare/retry cannot close a lease before its
            // helper is even attached. It must refuse the active operation.
            try{ServerDatabaseSetup.retryLegacyCleanup(root,Duration.ZERO);throw new AssertionError("Active setup must retain its lease");}
            catch(IOException expected){check(lock.isValid(),"Active prelaunch file lease is retained");}
            helper=start(backend,root);set(ownership,"process",helper);
            ServerDatabaseSetup.finishLegacy(root,ownership);
            check(ServerDatabaseSetup.legacyCleanupPending(root),"Exceptional legacy ownership remains strongly registered");
            try{ServerDatabaseSetup.retryLegacyCleanup(root,Duration.ZERO);throw new AssertionError("Live legacy cleanup must remain pending");}
            catch(IOException expected){check(helper.isAlive(),"Fault fixture must still be cleaning up");}
            check(ServerDatabaseSetup.legacyCleanupPending(root) && lock.isValid(),"Legacy timeout cannot release its registry/file lease");
            try(FileChannel competing=FileChannel.open(lockPath,StandardOpenOption.WRITE)) {
                try{FileLock unexpected=competing.tryLock();if(unexpected!=null)unexpected.close();throw new AssertionError("Reseeding/startup must remain excluded");}
                catch(java.nio.channels.OverlappingFileLockException expected){ }
            }
            backend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(helper.isAlive() && System.nanoTime()<deadline)Thread.sleep(1);
            check(!helper.isAlive(),"Legacy retained process must settle before retry");
            ServerDatabaseSetup.retryLegacyCleanup(root,Duration.ofSeconds(1));
            check(!ServerDatabaseSetup.legacyCleanupPending(root) && !lock.isValid(),"Known-stopped retry releases only the prior legacy owner");
            try(FileChannel next=FileChannel.open(lockPath,StandardOpenOption.WRITE);FileLock admitted=next.tryLock()) {
                check(admitted!=null,"A later bootstrap may acquire ownership only after cleanup");
            }
        } finally {
            backend.release.countDown();
            if(helper!=null && helper.isAlive())try{helper.stop(Duration.ZERO);}catch(IOException expected){ }
            try{ServerDatabaseSetup.retryLegacyCleanup(root,Duration.ofSeconds(1));}catch(IOException expected){ }
            try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
        }
    }
    public static void main(String[] arguments) throws Exception {
        fixture("bootstrap");fixture("installation");legacyFixture();
        System.out.println("Retained setup owner passed3 actual cleanup-timeout/retry cases including legacy public-path ownership; Java backend fixtures only, no SQL/Android execution");
    }
}
