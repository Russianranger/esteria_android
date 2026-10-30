package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
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
import java.util.concurrent.atomic.AtomicReference;

/** Actual production close methods and importer locks with a controlled delayed
 * Java native backend. No source provider, guest, SQL or Android execution. */
public final class LocalWorldSetupOwnerTests {
    private static void check(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
    private static Object field(Object target,String name)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field f=target.getClass().getDeclaredField(name);f.setAccessible(true);f.set(target,value);}
    @SuppressWarnings("unchecked") private static <T> Map<Path,T> registry(Class<?> owner)throws Exception {Field f=owner.getDeclaredField("OWNERS");f.setAccessible(true);return (Map<Path,T>)f.get(null);}
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);
        public long start(OwnedProcess.Specification ignored){return 1;}
        public int waitFor(long handle,long timeout)throws IOException {try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return OwnedProcess.RUNNING;}
        public int terminate(long handle)throws IOException {terminating.countDown();try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_CLEANUP_TIMEOUT");}catch(InterruptedException error){throw new IOException(error);}return 143;}
        public long[] diagnostics(long handle){return new long[5];}
    }
    private static final class Fixture implements AutoCloseable {
        final Path root=Files.createTempDirectory("esteria-world-setup-owner-").toRealPath();
        final Path game=Files.createDirectory(root.resolve("game")),work=Files.createDirectory(root.resolve("server-data-work"));
        final Path shaders=Files.createDirectory(root.resolve("shader-work")),state=Files.createDirectory(root.resolve("state"));
        ExclusiveFileLease lock=ExclusiveFileLease.acquire(state.resolve(".local-world-setup.lock"),"TEST_ONLY_BUSY");
        final LocalWorldSetup.Handle owner;
        Fixture()throws Exception {
            Constructor<LocalWorldSetup.Handle> constructor=LocalWorldSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,
                ServerRuntimeSetup.class,ServerProgramsSetup.class,ServerContentSetup.class,ServerDataToolsSetup.class,RuntimeSetup.class,
                ShaderToolsSetup.class,String.class,int.class,long.class,FreshServerInstallations.Active.class,ExclusiveFileLease.class);
            constructor.setAccessible(true);owner=constructor.newInstance(null,root,null,null,null,null,null,null,"enUS",1,1L<<30,null,lock);
            check(registry(LocalWorldSetup.class).putIfAbsent(root,owner)==null,"Outer owner registered before children");
        }
        void data()throws Exception {
            ServerDataSetup.Leases leases=ServerDataSetup.claim(work,game);
            Constructor<ServerDataSetup.Handle> c=ServerDataSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,Path.class,
                ServerRuntimeSetup.class,ServerDataToolsSetup.class,Path.class,Path.class,String.class,String.class,int.class,ServerDataSetup.Leases.class,boolean.class);
            c.setAccessible(true);ServerDataSetup.Handle data=c.newInstance(null,root,game,work,null,null,root.resolve("runtime"),root.resolve("tools"),"a".repeat(64),"enUS",1,leases,true);
            registry(ServerDataSetup.class).put(work,data);set(owner,"data",data);
        }
        ShaderSetup.Handle shader(OwnedProcess process)throws Exception {
            ExclusiveFileLease lock=ExclusiveFileLease.acquire(shaders.resolve(".android-shader-setup.lock"),"TEST_ONLY_BUSY");
            Constructor<ShaderSetup.Handle> c=ShaderSetup.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,RuntimeSetup.class,ShaderToolsSetup.class,
                String.class,Path.class,Path.class,ExclusiveFileLease.class);c.setAccessible(true);
            ShaderSetup.Handle shader=c.newInstance(null,root,shaders,null,null,"enUS",root.resolve("wine"),root.resolve("tools"),lock);
            set(shader,"process",process);set(shader,"state",ShaderSetup.State.FAILED);registry(ShaderSetup.class).put(shaders,shader);set(owner,"shaders",shader);return shader;
        }
        @Override public void close()throws Exception {
            if(owner.state()!=LocalWorldSetup.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            lock.close();try(var all=Files.walk(root)){for(Path path:all.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
        }
    }
    private static void importer(Path game,AtomicInteger scans,boolean admitted)throws IOException {
        GameDataImporter.InputSource source=new GameDataImporter.InputSource(){
            public String identity(){return "TEST_ONLY_WORLD_LOCK";}
            public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancelled)throws IOException {scans.incrementAndGet();throw new IOException("TEST_ONLY_SCAN_ADMITTED");}
            public java.io.InputStream open(GameDataImporter.InputEntry entry)throws IOException {throw new IOException("TEST_ONLY_UNEXPECTED_OPEN");}
            public void verifyUnchanged(GameDataImporter.InputEntry entry){throw new AssertionError("No source read is authorized by this fixture");}
            public void verifySnapshot(List<GameDataImporter.InputEntry> entries){throw new AssertionError("No actual import is authorized by this fixture");}
        };
        try{new GameDataImporter(game).importSource(source,GameDataImporter.ImportKind.BASE_CLIENT,GameDataImporter.NO_PROGRESS,GameDataImporter.NEVER_CANCELLED);throw new AssertionError();}
        catch(IOException error){check(admitted==error.getMessage().equals("TEST_ONLY_SCAN_ADMITTED"),"Importer admission must follow confirmed cleanup");}
    }
    private static void dependentCleanup()throws Exception {
        Backend backend=new Backend();OwnedProcess process=null;
        try(Fixture fixture=new Fixture()) {
            fixture.data();Files.writeString(fixture.work.resolve("retained-output"),"TEST_ONLY_GENERATED_DATA");
            process=OwnedProcess.start(backend,new OwnedProcess.Specification(fixture.root.resolve("fixture"),List.of(),Map.of(),fixture.root,
                fixture.root.resolve("out"),fixture.root.resolve("err")),null);
            ShaderSetup.Handle shader=fixture.shader(process);AtomicInteger scans=new AtomicInteger();
            try{fixture.owner.close(Duration.ZERO);throw new AssertionError("Delayed shader cannot release imported data");}catch(IOException expected){ }
            check(backend.terminating.getCount()==0&&process.isAlive(),"The actual owned process is still cleaning up");
            check(fixture.owner.state()!=LocalWorldSetup.State.CLOSED&&registry(LocalWorldSetup.class).get(fixture.root)==fixture.owner,"Outer owner remains strongly retained");
            check(shader.state()!=ShaderSetup.State.CLOSED&&((ServerDataSetup.Handle)field(fixture.owner,"data")).state()!=ServerDataSetup.State.CLOSED,"Later dependencies remain owned");
            importer(fixture.game,scans,false);check(scans.get()==0&&fixture.lock.isValid(),"Neither import nor outer setup lease is released early");
            backend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);while(process.isAlive()&&System.nanoTime()<deadline)Thread.sleep(1);
            check(!process.isAlive(),"Controlled native cleanup completes before retry");
            try{fixture.owner.close(Duration.ofSeconds(1));throw new AssertionError("A forced shader cleanup must remain diagnostic");}
            catch(IOException expected){check(fixture.owner.state()==LocalWorldSetup.State.CLOSED,"Known-reaped cleanup may close while preserving its first failure");}
            check(fixture.owner.state()==LocalWorldSetup.State.CLOSED&&!fixture.lock.isValid()&&!registry(LocalWorldSetup.class).containsKey(fixture.root),"Reaped dependency permits complete graph release");
            importer(fixture.game,scans,true);check(scans.get()==1&&Files.readString(fixture.work.resolve("retained-output")).equals("TEST_ONLY_GENERATED_DATA"),"Retry admits import and preserves generated data");
        }finally{backend.release.countDown();if(process!=null&&process.isAlive())try{process.stop(Duration.ZERO);}catch(IOException ignored){ }}
    }
    private static void prelaunchCancellation()throws Exception {
        try(Fixture fixture=new Fixture()) {
            ServiceOperationGuard guard=(ServiceOperationGuard)field(fixture.owner,"operations");CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);AtomicReference<Throwable> error=new AtomicReference<>();
            Thread worker=new Thread(()->{try{guard.run(()->{entered.countDown();try{release.await();}catch(InterruptedException interrupted){throw new IOException(interrupted);}return null;});}catch(Throwable issue){error.set(issue);}});worker.start();
            try {
                check(entered.await(2,TimeUnit.SECONDS),"Actual operation entered before launch");
                try{fixture.owner.close(Duration.ZERO);throw new AssertionError("An active prelaunch operation must keep its outer lease");}catch(IOException expected){ }
                check(guard.isStopRequested()&&fixture.lock.isValid()&&fixture.owner.state()!=LocalWorldSetup.State.CLOSED,"Deadline requests cancellation without discarding ownership");
            }finally{release.countDown();worker.join(2000);}
            check(!worker.isAlive()&&error.get()==null,"Operation settles after stop intent");fixture.owner.close(Duration.ofSeconds(1));
            check(fixture.owner.state()==LocalWorldSetup.State.CLOSED&&!fixture.lock.isValid(),"Safe boundary permits lease release");
        }
    }
    public static void main(String[] ignored)throws Exception {
        dependentCleanup();prelaunchCancellation();System.out.println("Local world setup passed2 actual Java dependency/import-lock/prelaunch cleanup groups; no guest SQL or Android execution");
    }
}
