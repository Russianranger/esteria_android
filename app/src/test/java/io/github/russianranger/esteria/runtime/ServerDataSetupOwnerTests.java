package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.ServerDataToolSelection;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Java ownership/file/importer exclusion fixtures with a delayed backend.
 * No source-qualified provider, game input, extractor, native or Android run. */
public final class ServerDataSetupOwnerTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static Object field(Object target,String name)throws Exception {Field value=target.getClass().getDeclaredField(name);value.setAccessible(true);return value.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field field=target.getClass().getDeclaredField(name);field.setAccessible(true);field.set(target,value);}
    @SuppressWarnings("unchecked") private static Map<Path,ServerDataSetup.Handle> owners()throws Exception {Field value=ServerDataSetup.class.getDeclaredField("OWNERS");value.setAccessible(true);return (Map<Path,ServerDataSetup.Handle>)value.get(null);}
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);
        public long start(OwnedProcess.Specification specification){return 1;}
        public int waitFor(long handle,long timeout)throws IOException {try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return OwnedProcess.RUNNING;}
        public int terminate(long handle)throws IOException {terminating.countDown();try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_BACKEND_TIMEOUT");}catch(InterruptedException error){throw new IOException(error);}return 143;}
        public long[] diagnostics(long handle){return new long[5];}
    }
    private static OwnedProcess start(Backend backend,Path root)throws IOException {return OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture-tool"),List.of(),Map.of(),root,root.resolve("fixture-out"),root.resolve("fixture-err")),null);}
    private static ServerDataSetup.Handle owner(Path root,Path game,Path work,ServerDataSetup.Leases leases)throws Exception {
        Constructor<ServerDataSetup.Handle> constructor=ServerDataSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,Path.class,ServerRuntimeSetup.class,ServerDataToolsSetup.class,Path.class,Path.class,String.class,String.class,int.class,ServerDataSetup.Leases.class,boolean.class);
        constructor.setAccessible(true);ServerDataSetup.Handle owner=constructor.newInstance(null,root,game,work,null,null,root.resolve("runtime"),root.resolve("tools"),"a".repeat(64),"enUS",1,leases,true);
        check(owners().putIfAbsent(work,owner)==null,"Fixture registry must be allocated before native work");return owner;
    }
    private static GameDataImporter.InputSource source(AtomicInteger scans) {
        return new GameDataImporter.InputSource(){
            public String identity(){return "TEST_ONLY_SOURCE";}
            public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation)throws IOException {scans.incrementAndGet();throw new IOException("TEST_ONLY_ADMITTED_SNAPSHOT");}
            public java.io.InputStream open(GameDataImporter.InputEntry entry){throw new AssertionError("No actual game source may be opened");}
            public void verifyUnchanged(GameDataImporter.InputEntry entry){throw new AssertionError("No game source read authorized");}
            public void verifySnapshot(List<GameDataImporter.InputEntry> values){throw new AssertionError("No actual import authorized");}
        };
    }
    private static void importerBlocked(GameDataImporter importer,AtomicInteger scans)throws IOException {
        try{importer.importSource(source(scans),GameDataImporter.ImportKind.BASE_CLIENT,GameDataImporter.NO_PROGRESS,GameDataImporter.NEVER_CANCELLED);throw new AssertionError("Actual importer acquired a live setup's import lock");}
        catch(IOException expected){check(expected.getMessage().contains("Another import"),"Must fail on actual importer lease, before source processing");}
        check(scans.get()==0,"No import rescan or source read occurs while the data owner remains live");
    }
    private static void delayedChild()throws Exception {
        Path root=Files.createTempDirectory("esteria-data-owner-").toRealPath(),game=Files.createDirectory(root.resolve("game")),work=Files.createDirectory(root.resolve("work"));
        Backend backend=new Backend();OwnedProcess process=null;ServerDataSetup.Handle owner=null;
        try {
            GameDataImporter importer=new GameDataImporter(game);AtomicInteger scans=new AtomicInteger();
            Files.writeString(game.resolve("retained-user-sentinel"),"TEST_ONLY_IMPORTED_STATE");Files.writeString(work.resolve("partial-output"),"TEST_ONLY_INTERRUPTED_STAGE");
            ServerDataSetup.Leases leases=ServerDataSetup.claim(work,game);owner=owner(root,game,work,leases);
            process=start(backend,root);set(owner,"process",process);set(owner,"state",ServerDataSetup.State.FAILED);
            try{owner.close(Duration.ZERO);throw new AssertionError("Live delayed cleanup cannot release import/setup leases");}catch(IOException expected){check(process.isAlive(),"Fixture must still be cleaning up its actual Java owner");}
            check(backend.terminating.getCount()==0&&owner.state()!=ServerDataSetup.State.CLOSED&&owners().get(work)==owner,"Timeout keeps a retryable strongly retained data owner");
            importerBlocked(importer,scans);
            try{ServerDataSetup.claim(work,game);throw new AssertionError("A new data job stole live setup ownership");}catch(IOException expected){ }
            backend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);while(process.isAlive()&&System.nanoTime()<deadline)Thread.sleep(1);
            check(!process.isAlive(),"Known native owner settles before retry release");
            try{owner.close(Duration.ofSeconds(1));}catch(IOException expected){check(owner.cleanupFailure()!=null,"Original cleanup failure remains diagnostic");}
            check(owner.state()==ServerDataSetup.State.CLOSED&&!owners().containsKey(work),"Only completed reaping permits final lease release");
            try{importer.importSource(source(scans),GameDataImporter.ImportKind.BASE_CLIENT,GameDataImporter.NO_PROGRESS,GameDataImporter.NEVER_CANCELLED);throw new AssertionError();}
            catch(IOException expected){check(expected.getMessage().equals("TEST_ONLY_ADMITTED_SNAPSHOT"),"Actual importer is admitted after the data owner stops");}
            check(scans.get()==1,"Source snapshot occurs only after confirmed cleanup");
            check(Files.readString(game.resolve("retained-user-sentinel")).equals("TEST_ONLY_IMPORTED_STATE")&&Files.readString(work.resolve("partial-output")).equals("TEST_ONLY_INTERRUPTED_STAGE"),"Imported and partial output bytes remain intact");
        } finally {
            backend.release.countDown();if(process!=null&&process.isAlive())try{process.stop(Duration.ZERO);}catch(IOException ignored){ }
            if(owner!=null&&owner.state()!=ServerDataSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void prelaunchGuard()throws Exception {
        Path root=Files.createTempDirectory("esteria-data-prelaunch-owner-").toRealPath(),game=Files.createDirectory(root.resolve("game")),work=Files.createDirectory(root.resolve("work"));
        ServerDataSetup.Handle owner=null;Thread worker=null;CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);AtomicReference<Throwable> error=new AtomicReference<>();
        try {
            owner=owner(root,game,work,ServerDataSetup.claim(work,game));ServiceOperationGuard guard=(ServiceOperationGuard)field(owner,"operations");
            worker=new Thread(()->{try{guard.run(()->{entered.countDown();try{release.await();}catch(InterruptedException interrupted){throw new IOException(interrupted);}return null;});}catch(Throwable failure){error.set(failure);}});worker.start();
            check(entered.await(2,TimeUnit.SECONDS),"Real operation guard entered before any launch");
            try{owner.close(Duration.ZERO);throw new AssertionError("Prelaunch close must retain leases until the operation observes cancellation");}catch(IOException expected){ }
            check(guard.isStopRequested()&&owners().get(work)==owner,"Close requests cancellation before its deadline expires");
            importerBlocked(new GameDataImporter(game),new AtomicInteger());
            release.countDown();worker.join(2000);check(!worker.isAlive()&&error.get()==null,"Operation reaches its safe boundary");
            owner.close(Duration.ofSeconds(1));check(owner.state()==ServerDataSetup.State.CLOSED,"No-child owner releases only at safe boundary");
        } finally {release.countDown();if(worker!=null)worker.join(2000);if(owner!=null&&owner.state()!=ServerDataSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }remove(root);}
    }
    private static void busyImportDoesNotLeakSetupLease()throws Exception {
        Path root=Files.createTempDirectory("esteria-data-lock-unwind-").toRealPath(),game=Files.createDirectory(root.resolve("game")),work=Files.createDirectory(root.resolve("work"));
        try(ExclusiveFileLease held=ExclusiveFileLease.acquire(game.resolve("import.lock"),"TEST_ONLY_BUSY")) {
            try{ServerDataSetup.claim(work,game);throw new AssertionError("A live importer must exclude data setup");}catch(IOException expected){ }
            check(held.isValid(),"The original importer lease remains owned");
            try(ExclusiveFileLease setup=ExclusiveFileLease.acquire(work.resolve(".android-server-data-setup.lock"),"TEST_ONLY_BUSY")) {
                check(setup!=null,"Secondary-lock failure cannot leak the first setup lease");
            }
        }finally{remove(root);}
    }
    private static ServerDataToolSelection selection()throws IOException {
        TreeMap<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
        for(String name:ServerDataToolSelection.FILES)files.put(name,new RuntimePackagePlan.RequiredFile(64,"a".repeat(64),name.startsWith("bin/")?183:0,0));
        files.put("etc/mmaps-config.yaml",new RuntimePackagePlan.RequiredFile(7888,ServerDataToolSelection.CONFIG_SHA256,0,0));
        return new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,files,files.get("provenance/ordered-source-receipt.json"));
    }
    private static void atomicSelectionAndBoundedProgress()throws Exception {
        Path root=Files.createTempDirectory("esteria-data-selection-progress-").toRealPath();
        try {
            Path target=root.resolve("data-tools-selection.json");Files.writeString(target,"OLD_TEST_ONLY_SELECTION");ServerDataToolSelection selection=selection();
            ServerDataSetup.atomicSelection(target,selection.bytes(),true);check(java.util.Arrays.equals(Files.readAllBytes(target),selection.bytes()),"Atomic private selection preserves exact typed canonical bytes");
            Path kept=root.resolve("retained-user-file"),linked=root.resolve("linked-selection");Files.writeString(kept,"TEST_ONLY_PRESERVED");Files.createSymbolicLink(linked,kept);
            try{ServerDataSetup.atomicSelection(linked,selection.bytes(),true);throw new AssertionError("A linked metadata target must be preserved/refused");}catch(IOException expected){ }
            check(Files.readString(kept).equals("TEST_ONLY_PRESERVED")&&Files.isSymbolicLink(linked),"Atomic metadata cannot write through a link");
            Class<?> type=Class.forName(ServerDataSetup.class.getName()+"$ProgressLines");Constructor<?> constructor=type.getDeclaredConstructor();constructor.setAccessible(true);Object progress=constructor.newInstance();Method read=type.getDeclaredMethod("read",Path.class);read.setAccessible(true);
            Path log=root.resolve("stdout.log");Files.writeString(log,"UNTRUSTED_PRIVATE_TEXT\nextraction-map_ext");check(read.invoke(progress,log)==null,"Partial/unapproved messages never reach progress UI");
            Files.writeString(log,"ractor\n",StandardOpenOption.APPEND);check(read.invoke(progress,log).equals("maps-dbc-cameras"),"Split fixed phase line resolves without rescanning prior bytes");
            Files.writeString(log,"x".repeat(100000)+"\nextraction-mmaps_generator\n",StandardOpenOption.APPEND);Object observed=null;
            for(int i=0;i<4&&observed==null;i++)observed=read.invoke(progress,log);
            check("navigation".equals(observed),"Bounded overlong log discard preserves the next valid phase");
        }finally{remove(root);}
    }
    private static void remove(Path root)throws IOException {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    public static void main(String[] args)throws Exception {
        delayedChild();prelaunchGuard();busyImportDoesNotLeakSetupLease();atomicSelectionAndBoundedProgress();
        System.out.println("Server data setup passed4 host retained-owner/importer/atomic/progress groups; no tool/source/native/Android execution");
    }
}
