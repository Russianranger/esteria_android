package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
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

/** Actual Java owner/guard/FileLock fault fixtures. These use a delayed backend,
 * no native/SQL processes, source proof, Android APIs or gameplay qualification. */
public final class LocalServerSessionOwnerTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static Object field(Object target,String name)throws Exception {Field value=target.getClass().getDeclaredField(name);value.setAccessible(true);return value.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field item=target.getClass().getDeclaredField(name);item.setAccessible(true);item.set(target,value);}
    @SuppressWarnings("unchecked") private static Map<Path,LocalServerSession.Handle> owners()throws Exception {Field value=LocalServerSession.class.getDeclaredField("OWNERS");value.setAccessible(true);return (Map<Path,LocalServerSession.Handle>)value.get(null);}
    private static final class Backend implements OwnedProcess.Backend {
        final boolean delayed;final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);final AtomicInteger stops=new AtomicInteger();
        Backend(boolean delayed){this.delayed=delayed;}
        public long start(OwnedProcess.Specification specification){return 1;}
        public int waitFor(long handle,long timeout)throws IOException {try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return OwnedProcess.RUNNING;}
        public int terminate(long handle)throws IOException {stops.incrementAndGet();terminating.countDown();if(delayed)try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_BACKEND_TIMEOUT");}catch(InterruptedException error){throw new IOException(error);}return 143;}
        public long[] diagnostics(long handle){return new long[5];}
    }
    private static OwnedProcess start(Backend backend,Path root)throws IOException {return OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture-executable"),List.of(),Map.of(),root,root.resolve("fixture-out"),root.resolve("fixture-err")),null);}
    private static ServerDatabaseService.Handle database(OwnedProcess child,FileChannel channel,FileLock lock,Path root,Path work)throws Exception {
        Constructor<ServerDatabaseService.Handle> constructor=ServerDatabaseService.Handle.class.getDeclaredConstructor(OwnedProcess.class,FileChannel.class,FileLock.class,Path.class,String.class,String.class,Path.class,Path.class,FreshServerInstallations.Workspace.class);
        constructor.setAccessible(true);ServerDatabaseService.Handle result=constructor.newInstance(child,channel,lock,root.resolve("fixture-db-service"),"a".repeat(32),"8.0.46",root,work,null);
        set(result,"instanceUuid","01234567-89ab-4cde-8fab-0123456789ab");return result;
    }
    private static LocalServerSession.Handle owner(Path root,Path work,ServerDatabaseService.Handle database,FileChannel channel,FileLock lock)throws Exception {
        Constructor<LocalServerSession.Handle> constructor=LocalServerSession.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,ServerRuntimeSetup.class,ServerProgramsSetup.class,ServerContentSetup.class,FreshServerInstallations.Active.class,ServerDatabaseService.Handle.class,ServerDataBinding.class,LocalServerSession.Events.class,FileChannel.class,FileLock.class);
        constructor.setAccessible(true);LocalServerSession.Handle owner=constructor.newInstance(null,root,work,null,null,null,null,database,null,null,channel,lock);
        check(owners().putIfAbsent(work,owner)==null,"Fixture owner must register before a child starts");return owner;
    }
    private static void activeLease(boolean prelaunch)throws Exception {
        Path root=Files.createTempDirectory("esteria-local-server-owner-").toRealPath(),work=Files.createDirectory(root.resolve("work"));
        Backend childBackend=new Backend(true),databaseBackend=new Backend(false);OwnedProcess child=null,engine=null;
        LocalServerSession.Handle owner=null;ServerDatabaseService.Handle database=null;Thread worker=null;
        CountDownLatch entered=new CountDownLatch(1),releasePrelaunch=new CountDownLatch(1);AtomicReference<Throwable> workerFailure=new AtomicReference<>();
        try {
            Path sessionLock=work.resolve(".session.lock"),databaseLock=work.resolve(".database.lock");
            FileChannel channel=FileChannel.open(sessionLock,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            FileChannel dbChannel=FileChannel.open(databaseLock,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock dbLock=dbChannel.tryLock();
            engine=start(databaseBackend,root);database=database(engine,dbChannel,dbLock,root,work);owner=owner(root,work,database,channel,lock);
            Files.writeString(work.resolve("retained-state"),"TEST_ONLY_PERSISTENT_STATE");set(owner,"state",LocalServerSession.State.STARTING);
            if(!prelaunch){child=start(childBackend,root);set(owner,"process",child);}
            OwnedProcess retainedChild=child;ServerDatabaseService.Handle retainedDatabase=database;LocalServerSession.Handle retainedOwner=owner;
            worker=new Thread(()->{try{retainedDatabase.withReadyLease(root,(operation,version,uuid)->{
                entered.countDown();
                if(prelaunch)try{releasePrelaunch.await();}catch(InterruptedException error){throw new IOException(error);}
                else while(retainedChild.isAlive())try{retainedChild.stop(Duration.ZERO);}catch(IOException expected){/* Retain DB guard through native cleanup. */}
                return null;
            });}catch(Throwable error){workerFailure.set(error);}finally{try{((CountDownLatch)field(retainedOwner,"finished")).countDown();}catch(Exception error){workerFailure.set(error);}}});
            set(owner,"worker",worker);worker.start();check(entered.await(2,TimeUnit.SECONDS),"Actual database ready lease must be held");
            if(!prelaunch)check(childBackend.terminating.await(2,TimeUnit.SECONDS),"Actual native cleanup path reached");
            try{owner.close(Duration.ZERO);throw new AssertionError("Close cannot discard a running/launching server owner");}catch(IOException expected){ }
            check(owner.state()!=LocalServerSession.State.CLOSED&&lock.isValid()&&owners().get(work)==owner,"Session timeout retains its actual operation lease and registry owner");
            try{database.stop(Duration.ZERO);throw new AssertionError("Database must remain available while server worker owns it");}catch(IOException expected){ }
            check(engine.isAlive()&&dbLock.isValid()&&databaseBackend.stops.get()==0,"Database shutdown cannot pass the retained server dependency guard");
            try(FileChannel competing=FileChannel.open(sessionLock,StandardOpenOption.WRITE)) {
                try{FileLock unexpected=competing.tryLock();if(unexpected!=null)unexpected.close();throw new AssertionError("Another session cannot acquire the retained operation lock");}catch(OverlappingFileLockException expected){ }
            }
            childBackend.release.countDown();releasePrelaunch.countDown();worker.join(3000);
            check(!worker.isAlive()&&workerFailure.get()==null,"Worker releases dependency only after the known child is stopped");
            owner.close(Duration.ofSeconds(1));check(owner.state()==LocalServerSession.State.CLOSED&&!lock.isValid()&&!owners().containsKey(work),"Retry closes the actual session after worker completion");
            check(engine.isAlive()&&dbLock.isValid()&&databaseBackend.stops.get()==0,"Closing the server session does not itself stop/delete its caller-owned database");
            check(Files.readString(work.resolve("retained-state")).equals("TEST_ONLY_PERSISTENT_STATE"),"Persistent bytes remain intact");
            try{database.stop(Duration.ZERO);}catch(IOException expected){/* Forced controlled backend is never a clean SQL save. */}
            check(!engine.isAlive()&&!dbLock.isValid(),"Explicit caller shutdown is admitted after server cleanup");
        } finally {
            releasePrelaunch.countDown();childBackend.release.countDown();if(worker!=null)worker.join(3000);
            if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }
            if(owner!=null&&owner.state()!=LocalServerSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            if(database!=null&&database.isAlive())try{database.stop(Duration.ZERO);}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void completedWorkerCannotHideLiveChild()throws Exception {
        Path root=Files.createTempDirectory("esteria-local-server-finished-race-").toRealPath(),work=Files.createDirectory(root.resolve("work"));
        Backend backend=new Backend(true);OwnedProcess child=null;LocalServerSession.Handle owner=null;
        try {
            Path path=work.resolve(".session.lock");FileChannel channel=FileChannel.open(path,StandardOpenOption.CREATE,StandardOpenOption.WRITE);FileLock lock=channel.tryLock();
            owner=owner(root,work,null,channel,lock);child=start(backend,root);set(owner,"process",child);set(owner,"worker",new Thread());
            ((CountDownLatch)field(owner,"finished")).countDown();
            try{owner.close(Duration.ZERO);throw new AssertionError("A completion flag cannot replace native liveness");}catch(IOException expected){ }
            check(child.isAlive()&&lock.isValid()&&owners().get(work)==owner,"Live native child retains operation/provider owner independently of worker flag");
            OwnedProcess retained=child;Thread cleanup=new Thread(()->{try{retained.stop(Duration.ZERO);}catch(IOException expected){ }});cleanup.start();
            check(backend.terminating.await(2,TimeUnit.SECONDS),"Known-child cleanup actually started");backend.release.countDown();cleanup.join(3000);
            owner.close(Duration.ofSeconds(1));check(owner.state()==LocalServerSession.State.CLOSED&&!lock.isValid(),"Confirmed native completion permits retry release");
        } finally {
            backend.release.countDown();if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }
            if(owner!=null&&owner.state()!=LocalServerSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void remove(Path root)throws IOException {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    public static void main(String[] arguments)throws Exception {
        activeLease(false);activeLease(true);completedWorkerCannotHideLiveChild();
        System.out.println("Local auth/world owner passed3 host cleanup/dependency/prelaunch fixtures; no SQL/native/Android/gameplay execution");
    }
}
