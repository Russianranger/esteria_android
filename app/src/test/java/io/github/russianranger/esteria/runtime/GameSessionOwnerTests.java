package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Handler;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.presentation.InputSink;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.LocalAccountHandoff;
import io.github.russianranger.esteria.core.runtime.install.ClientLaunchView;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.StandardOpenOption;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/** Actual Java owners, native-owner protocol and filesystem locks with a
 * controlled backend. No game/SQL/native/Android/GPU source qualification. */
public final class GameSessionOwnerTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static Object field(Object target,String name)throws Exception {Field value=target.getClass().getDeclaredField(name);value.setAccessible(true);return value.get(target);}
    private static void set(Object target,String name,Object value)throws Exception {Field item=target.getClass().getDeclaredField(name);item.setAccessible(true);item.set(target,value);}
    @SuppressWarnings("unchecked") private static Map<Path,GameSession.Handle> owners()throws Exception {Field value=GameSession.class.getDeclaredField("OWNERS");value.setAccessible(true);return (Map<Path,GameSession.Handle>)value.get(null);}
    private static final class Backend implements OwnedProcess.Backend {
        final AtomicInteger status=new AtomicInteger(OwnedProcess.RUNNING),stops=new AtomicInteger();
        final CountDownLatch terminating=new CountDownLatch(1),release=new CountDownLatch(1);
        public long start(OwnedProcess.Specification specification){return 1;}
        public int waitFor(long handle,long timeout)throws IOException {try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return status.get();}
        public int terminate(long handle)throws IOException {stops.incrementAndGet();terminating.countDown();try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_TIMEOUT");}catch(InterruptedException error){throw new IOException(error);}return 143;}
        public long[] diagnostics(long handle){return new long[5];}
    }
    private static OwnedProcess start(Backend backend,Path root)throws IOException {return OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture-exe"),List.of(),Map.of(),root,root.resolve("out"),root.resolve("err")),null);}
    private static GameSession.Handle owner(Path root,GameSession.Leases leases)throws Exception {return owner(root,leases,null);}
    private static GameSession.Handle owner(Path root,GameSession.Leases leases,GameSession.Events events)throws Exception {
        Constructor<GameSession.Handle> constructor=GameSession.Handle.class.getDeclaredConstructor(Context.class,Path.class,LocalWorldSetup.Result.class,ClientRuntimeSetup.class,GuestBridgeSetup.class,TurnipSetup.class,GameSession.Events.class,GameSession.Leases.class);
        constructor.setAccessible(true);GameSession.Handle owner=constructor.newInstance(null,root,null,null,null,null,events,leases);
        check(owners().putIfAbsent(root,owner)==null,"Fixture owner registered before any child");return owner;
    }
    private static ClientPresentationSession presentation(Path root,OwnedProcess child)throws Exception {
        Path session=Files.createDirectory(root.resolve("session"));Files.createDirectory(session.resolve("io"));Files.createDirectory(session.resolve("x11"));
        Files.writeString(session.resolve("io/Xauthority"),"TEST_ONLY_PRIVATE_AUTHORITY");
        Constructor<ClientPresentationSession> constructor=ClientPresentationSession.class.getDeclaredConstructor(Context.class,ClientPresentationSession.Prepared.class,ClientPresentationSession.Events.class,Path.class,Path.class,int.class,Handler.class);
        constructor.setAccessible(true);ClientPresentationSession result=constructor.newInstance(null,null,null,session,root.resolve("state/client-work"),987,null);
        set(result,"client",child);return result;
    }
    private static GameDataImporter.InputSource source(AtomicInteger scans){return new GameDataImporter.InputSource(){
        public String identity(){return "TEST_ONLY_SOURCE";}
        public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation)throws IOException {scans.incrementAndGet();throw new IOException("TEST_ONLY_ADMITTED");}
        public java.io.InputStream open(GameDataImporter.InputEntry entry){throw new AssertionError();}
        public void verifyUnchanged(GameDataImporter.InputEntry entry){throw new AssertionError();}
        public void verifySnapshot(List<GameDataImporter.InputEntry> entries){throw new AssertionError();}
    };}
    private static void blocked(Path root)throws IOException {
        AtomicInteger scans=new AtomicInteger();
        try{new GameDataImporter(root.resolve("game")).importSource(source(scans),GameDataImporter.ImportKind.BASE_CLIENT,GameDataImporter.NO_PROGRESS,GameDataImporter.NEVER_CANCELLED);throw new AssertionError("Live session admitted import");}
        catch(IOException expected){check(expected.getMessage().contains("Another import"),"Actual importer lock refuses before source scan");}
        check(scans.get()==0,"No source scan while owned child remains");
        try{ClientLaunchSetup.claim(root);throw new AssertionError("Live session admitted another client view");}catch(IOException expected){ }
    }
    private static void admitted(Path root)throws IOException {
        AtomicInteger scans=new AtomicInteger();
        try{new GameDataImporter(root.resolve("game")).importSource(source(scans),GameDataImporter.ImportKind.BASE_CLIENT,GameDataImporter.NO_PROGRESS,GameDataImporter.NEVER_CANCELLED);throw new AssertionError();}
        catch(IOException expected){check(expected.getMessage().equals("TEST_ONLY_ADMITTED"),"Importer admitted only after known cleanup");}
        check(scans.get()==1,"Exactly one source inventory after cleanup");
        try(ClientLaunchSetup.Lease lease=ClientLaunchSetup.claim(root)){lease.require(root);}
    }
    private static void gracefulFailureThenExplicitForce()throws Exception {
        Path root=Files.createTempDirectory("esteria-game-owner-force-").toRealPath();Files.createDirectory(root.resolve("game"));
        Backend backend=new Backend();OwnedProcess child=null;GameSession.Handle owner=null;
        try {
            Files.writeString(root.resolve("game/retained"),"TEST_ONLY_IMPORTED_DATA");
            owner=owner(root,GameSession.claim(root));child=start(backend,root);set(owner,"process",child);set(owner,"state",GameSession.State.CLIENT_STARTED);
            ClientPresentationSession display=presentation(root,child);set(owner,"presentation",display);Path authority=root.resolve("session/io/Xauthority");
            ServiceOperationGuard operation=(ServiceOperationGuard)field(owner,"operations");
            GameSession.StartupCancellation retainedServerCancellation=new GameSession.StartupCancellation(operation::isStopRequested);
            check(!retainedServerCancellation.isCancelled(),"Real lower-service predicate begins linked to outer startup cancellation");retainedServerCancellation.handOff();
            try{owner.requestForceStop();throw new AssertionError("Force policy cannot precede graceful attempt");}catch(IOException expected){ }
            // Automatic display cleanup cannot tear down a dependent client, even
            // if an unrelated presentation component previously failed.
            try{display.close(Duration.ZERO);throw new AssertionError("Live game client lost its presentation bindings");}catch(IOException expected){ }
            check(!display.isClosed()&&Files.exists(authority)&&backend.stops.get()==0,"Presentation refuses force/IPC release for live client");
            try{owner.close(Duration.ZERO);throw new AssertionError("Unavailable input cannot acknowledge normal client shutdown");}catch(IOException expected){ }
            check(owner.needsForceStop()&&!owner.wasForced()&&backend.stops.get()==0&&child.isAlive(),"Graceful failure never automatically forces the exact client");
            check(operation.isStopRequested()&&!retainedServerCancellation.isCancelled(),"Outer graceful stop cannot reach the retained world/auth cancellation predicate while client still lives");
            blocked(root);check(owners().get(root)==owner&&Files.exists(authority),"All exact owner/binding identities retained");
            owner.requestForceStop();check(owner.recoveryRequired()&&!owner.wasForced(),"Policy selection marks recovery without fabricating actual forced execution");
            try{owner.close(Duration.ZERO);throw new AssertionError("Delayed actual native cleanup cannot release game leases");}catch(IOException expected){ }
            check(backend.terminating.await(1,TimeUnit.SECONDS)&&child.isAlive()&&owner.state()!=GameSession.State.CLOSED,"Actual owner still executing delayed native cleanup after bounded caller timeout");
            blocked(root);check(Files.exists(authority),"Force timeout retains display and data");
            backend.release.countDown();settle(child);
            try{owner.close(Duration.ofSeconds(1));}catch(IOException expected){check(owner.failure()!=null,"Original shutdown failures remain diagnostic");}
            check(owner.state()==GameSession.State.CLOSED&&!owners().containsKey(root)&&owner.wasForced()&&owner.recoveryRequired()&&!owner.clientExitAcknowledged(),"Confirmed forced reap releases all ownership and never claims normal exit/save");
            check(display.isClosed()&&!Files.exists(authority),"Display teardown happens only after the client is dead");admitted(root);
            check(Files.readString(root.resolve("game/retained")).equals("TEST_ONLY_IMPORTED_DATA"),"Imported data is unchanged");
        }finally{backend.release.countDown();if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }if(owner!=null&&owner.state()!=GameSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }remove(root);}
    }
    private static void naturalExit()throws Exception {
        Path root=Files.createTempDirectory("esteria-game-owner-exit-").toRealPath();Files.createDirectory(root.resolve("game"));Backend backend=new Backend();GameSession.Handle owner=null;OwnedProcess child=null;
        try {
            AtomicInteger notifications=new AtomicInteger();
            owner=owner(root,GameSession.claim(root),new GameSession.Events(){public void frameSize(int width,int height){throw new AssertionError();}
                public void failed(String code){throw new AssertionError("Natural client exit should notify the central owner separately");}
                public void clientExited(int code,boolean forced){check(code==0&&!forced,"Callback reports actual process result");notifications.incrementAndGet();}});
            child=start(backend,root);set(owner,"process",child);set(owner,"presentation",presentation(root,child));
            backend.status.set(0);settle(child);
            Method monitor=GameSession.Handle.class.getDeclaredMethod("monitor");monitor.setAccessible(true);monitor.invoke(owner);
            check(notifications.get()==1&&owner.state()!=GameSession.State.CLOSED,"Lifecycle monitor notifies, leaving a single central worker responsible for close");blocked(root);
            owner.close(Duration.ofSeconds(1));
            check(owner.state()==GameSession.State.CLOSED&&owner.clientExitAcknowledged()&&!owner.recoveryRequired()&&!owner.wasForced()&&backend.stops.get()==0,"Natural exit0 is recorded without a force operation or an invented save qualification");admitted(root);
        }finally{backend.release.countDown();if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }if(owner!=null&&owner.state()!=GameSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }remove(root);}
    }
    private static void prelaunch()throws Exception {
        Path root=Files.createTempDirectory("esteria-game-owner-prelaunch-").toRealPath();Files.createDirectory(root.resolve("game"));GameSession.Handle owner=null;Thread worker=null;
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);AtomicReference<Throwable> failure=new AtomicReference<>();
        try {
            owner=owner(root,GameSession.claim(root));ServiceOperationGuard guard=(ServiceOperationGuard)field(owner,"operations");
            worker=new Thread(()->{try{guard.run(()->{entered.countDown();try{release.await();}catch(InterruptedException error){throw new IOException(error);}return null;});}catch(Throwable error){failure.set(error);}});worker.start();
            check(entered.await(2,TimeUnit.SECONDS),"Actual launch operation guard acquired");
            try{owner.close(Duration.ZERO);throw new AssertionError("Prelaunch owner lost its leases before start reached safe boundary");}catch(IOException expected){ }
            check(guard.isStopRequested()&&owners().get(root)==owner,"Bounded stop publishes cancellation without stealing native launch authority");blocked(root);
            release.countDown();worker.join(2000);check(!worker.isAlive()&&failure.get()==null,"Operation returned at safe boundary");owner.close(Duration.ofSeconds(1));admitted(root);
        }finally{release.countDown();if(worker!=null)worker.join(2000);if(owner!=null&&owner.state()!=GameSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }remove(root);}
    }
    private static void typedViewLease()throws Exception {
        Path root=Files.createTempDirectory("esteria-client-view-lease-").toRealPath();Files.createDirectory(root.resolve("game"));
        try {
            ClientLaunchSetup.Lease lease=ClientLaunchSetup.claim(root);
            check(ClientLaunchSetup.prepareStoredUnderOwnedLease(root,root,null,null,lease,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED)==null,"Absent game import remains absent under retained typed lease");
            lease.require(root);try{ClientLaunchSetup.prepareStored(root,root,null,null,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);throw new AssertionError("Convenience path bypassed active view lease");}catch(IOException expected){ }
            try{lease.require(root.resolve("other"));throw new AssertionError("Typed lease accepted a different root");}catch(IOException expected){ }
            lease.close();try{ClientLaunchSetup.prepareStoredUnderOwnedLease(root,root,null,null,lease,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);throw new AssertionError("Closed typed lease remained an authority");}catch(IOException expected){ }
            check(ClientLaunchSetup.prepareStored(root,root,null,null,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED)==null,"Compatibility preparation still acquires/releases its own stopped-client lock");
        }finally{remove(root);}
    }
    private static void preservedForeignHandoff()throws Exception {
        Path root=Files.createTempDirectory("esteria-game-handoff-recovery-").toRealPath();Files.createDirectory(root.resolve("game"));GameSession.Handle owner=null;
        char[] username="EST0123456789ABCD".toCharArray(),password="ABCDEFGHJKLMNPQR".toCharArray();
        try {
            owner=owner(root,GameSession.claim(root));Path view=Files.createDirectory(root.resolve("view"));String generation="a".repeat(64);
            Files.writeString(view.resolve(".owner"),"esteria-client-launch-v1\n"+generation+"\n");Files.write(view.resolve("WowClient64.exe"),new byte[]{0});
            Constructor<ClientLaunchView.Result> constructor=ClientLaunchView.Result.class.getDeclaredConstructor(Path.class,String.class,int.class,boolean.class,boolean.class);constructor.setAccessible(true);
            ClientLaunchView.Result prepared=constructor.newInstance(view,generation,0,true,true);
            LocalAccountHandoff handoff=LocalAccountHandoff.create(prepared,username,password);set(owner,"handoff",handoff);
            Path path=view.resolve(LocalAccountHandoff.FILENAME);byte[] changed=Files.readAllBytes(path);changed[0]^=1;Files.write(path,changed);
            try{owner.close(Duration.ofSeconds(1));throw new AssertionError("Foreign handoff must remain an explicit failure");}catch(IOException expected){ }
            check(owner.state()==GameSession.State.CLOSED&&owner.handoffRecoveryRequired()&&owner.recoveryRequired()&&!owner.needsForceStop()&&!owners().containsKey(root),"Known stopped dependencies release playing ownership while retaining a precise manual-handoff recovery diagnostic");
            check(Arrays.equals(changed,Files.readAllBytes(path)),"Changed handoff bytes are preserved without quarantine or deletion");admitted(root);
            try{LocalAccountHandoff.create(prepared,username,password);throw new AssertionError("Same view reused a preserved foreign handoff");}catch(IOException expected){ }
            Arrays.fill(changed,(byte)0);
        }finally{Arrays.fill(username,'\0');Arrays.fill(password,'\0');if(owner!=null&&owner.state()!=GameSession.State.CLOSED)try{owner.close(Duration.ofSeconds(1));}catch(IOException ignored){ }remove(root);}
    }
    private static void persistentShutdownBudgets()throws Exception {
        Path root=Files.createTempDirectory("esteria-game-shutdown-budget-").toRealPath();Files.createDirectory(root.resolve("game"));
        GameSession.Handle owner=null;OwnedProcess engine=null;Backend backend=new Backend();ServerDatabaseService.Handle database=null;LocalServerSession.Handle servers=null;
        try {
            owner=owner(root,GameSession.claim(root));Path work=Files.createDirectory(root.resolve("dbwork"));
            ExclusiveFileLease dbLock=ExclusiveFileLease.acquire(work.resolve("database.lock"),"TEST_ONLY_BUSY");
            engine=start(backend,root);
            Constructor<ServerDatabaseService.Handle> dbConstructor=ServerDatabaseService.Handle.class.getDeclaredConstructor(OwnedProcess.class,ExclusiveFileLease.class,Path.class,String.class,String.class,Path.class,Path.class,FreshServerInstallations.Workspace.class);dbConstructor.setAccessible(true);
            database=dbConstructor.newInstance(engine,dbLock,root.resolve("fixture-db-session"),"a".repeat(32),"8.0.46",root,work,null);set(owner,"database",database);
            ExclusiveFileLease serverLock=ExclusiveFileLease.acquire(work.resolve("server.lock"),"TEST_ONLY_BUSY");
            Constructor<LocalServerSession.Handle> serverConstructor=LocalServerSession.Handle.class.getDeclaredConstructor(Context.class,Path.class,Path.class,ServerRuntimeSetup.class,ServerProgramsSetup.class,ServerContentSetup.class,FreshServerInstallations.Active.class,ServerDatabaseService.Handle.class,ServerDataBinding.class,LocalServerSession.Events.class,ExclusiveFileLease.class);serverConstructor.setAccessible(true);
            servers=serverConstructor.newInstance(null,root,work,null,null,null,null,database,null,null,serverLock);set(owner,"servers",servers);
            try{owner.close(Duration.ofSeconds(9));throw new AssertionError("Insufficient world stop budget should preserve original services");}catch(IOException expected){ }
            check(servers.state()==LocalServerSession.State.ALLOCATED&&serverLock.isValid()&&dbLock.isValid()&&backend.stops.get()==0,"World shutdown is not initiated with less than10seconds; live database remains untouched");blocked(root);
            servers.close(Duration.ofSeconds(30));
            try{owner.close(Duration.ofSeconds(4));throw new AssertionError("Spent close budget cannot select immediate database force");}catch(IOException expected){ }
            check(engine.isAlive()&&dbLock.isValid()&&backend.stops.get()==0,"Database stop is not initiated with less than5seconds");blocked(root);
            backend.status.set(0);settle(engine);
            try{owner.close(Duration.ofSeconds(30));}catch(IOException expected){ }
            check(owner.state()==GameSession.State.CLOSED&&!dbLock.isValid()&&backend.stops.get()==0&&owner.recoveryRequired(),"Known dead fixture engine releases actual lease; missing genuine SQL stop receipt remains an explicit recovery failure");admitted(root);
        }finally{backend.release.countDown();if(engine!=null&&engine.isAlive())try{engine.stop(Duration.ZERO);}catch(IOException ignored){ }if(servers!=null&&servers.state()!=LocalServerSession.State.CLOSED)try{servers.close(Duration.ofSeconds(30));}catch(IOException ignored){ }if(database!=null)try{database.stop(Duration.ofSeconds(1));}catch(IOException ignored){ }if(owner!=null&&owner.state()!=GameSession.State.CLOSED)try{owner.close(Duration.ofSeconds(30));}catch(IOException ignored){ }remove(root);}
    }
    private static void startupCancellationHandoff()throws Exception {
        java.util.concurrent.atomic.AtomicBoolean source=new java.util.concurrent.atomic.AtomicBoolean();
        GameSession.StartupCancellation cancellation=new GameSession.StartupCancellation(source::get);
        check(!cancellation.isCancelled(),"Startup cancellation initially clear");source.set(true);check(cancellation.isCancelled(),"Actual startup cancellation reaches the lower service");source.set(false);
        try{cancellation.handOff();throw new AssertionError("Observed startup cancellation cannot be erased by handoff");}catch(RuntimeWork.CancelledException expected){ }
        check(!cancellation.isCancelled(),"Irreversible disarm leaves subsequent lower-service lifetime control with its ordered owner");
        CountDownLatch entered=new CountDownLatch(1),release=new CountDownLatch(1);AtomicReference<Throwable> failure=new AtomicReference<>();
        GameSession.StartupCancellation racing=new GameSession.StartupCancellation(()->{entered.countDown();try{release.await();}catch(InterruptedException error){Thread.currentThread().interrupt();}return true;});
        Thread reader=new Thread(racing::isCancelled);reader.start();check(entered.await(2,TimeUnit.SECONDS),"In-flight cancellation evaluation actually entered");
        Thread handoff=new Thread(()->{try{racing.handOff();failure.set(new AssertionError("In-flight observed cancel cannot be lost"));}catch(RuntimeWork.CancelledException expected){ }});handoff.start();
        check(handoff.isAlive(),"Handoff drains the actual in-flight synchronized predicate");release.countDown();reader.join(2000);handoff.join(2000);
        check(!reader.isAlive()&&!handoff.isAlive()&&failure.get()==null&&!racing.isCancelled(),"No pending check crosses a successful client handoff boundary");
    }
    private static void sourceCloseSequenceAndShaderSelection()throws Exception {
        List<String> events=new ArrayList<>();InputSink input=new InputSink(){
            public void releaseAll(){events.add("release");}
            public void keySequence(int[] keysyms,boolean[] down){events.add(Arrays.toString(keysyms));events.add(Arrays.toString(down));}
            public void key(int key,boolean down){throw new AssertionError("Atomic sequence required");}
            public void pointer(int x,int y,int mask){throw new AssertionError();}public void relativeMotion(int x,int y){throw new AssertionError();}public void buttons(int mask){throw new AssertionError();}
        };
        Method close=ClientPresentationSession.class.getDeclaredMethod("sendClientClose",InputSink.class);close.setAccessible(true);close.invoke(null,input);
        check(events.equals(List.of("release","[65513, 65473, 65473, 65513]","[true, true, false, false]")),"Source-supported Alt+F4 is one atomic sequence after releaseAll");
        Path root=Files.createTempDirectory("esteria-shader-selection-").toRealPath();
        try {
            Path game=Files.createDirectory(root.resolve("game")),tools=Files.createDirectory(root.resolve("tools")),work=Files.createDirectory(root.resolve("work")),helpers=Files.createDirectory(root.resolve("helpers"));
            Files.writeString(game.resolve("current"),"a".repeat(64)+"\n");Path generations=Files.createDirectory(game.resolve("generations"));Path imported=Files.createDirectory(Files.createDirectory(generations.resolve("a".repeat(64))).resolve("data"));Path data=Files.createDirectory(imported.resolve("Data"));
            Files.write(data.resolve("common.MPQ"),new byte[]{0});Path enUS=Files.createDirectory(data.resolve("enUS"));Files.write(enUS.resolve("locale-enUS.MPQ"),new byte[]{0});
            ShaderRunPlan plan=new ShaderRunPlan(game,tools,work,helpers,"b".repeat(40),"enUS");
            Constructor<ShaderSetup.Result> constructor=ShaderSetup.Result.class.getDeclaredConstructor(ShaderRunPlan.class,String.class,Path.class,Path.class,int.class,long.class,boolean.class);constructor.setAccessible(true);
            ShaderSetup.Result original=constructor.newInstance(plan,"c".repeat(64),root.resolve("shaders"),root.resolve("logs"),4,123L,false);
            ShaderSetup.Result same=constructor.newInstance(plan,"c".repeat(64),root.resolve("shaders"),root.resolve("other-log"),4,123L,false);
            ShaderSetup.requireSameSelection(same,original);
            for(ShaderSetup.Result changed:List.of(constructor.newInstance(plan,"d".repeat(64),root.resolve("shaders"),root,4,123L,false),constructor.newInstance(plan,"c".repeat(64),root.resolve("changed"),root,4,123L,false),constructor.newInstance(plan,"c".repeat(64),root.resolve("shaders"),root,5,123L,false)))
                try{ShaderSetup.requireSameSelection(changed,original);throw new AssertionError("Stale shader selection was accepted");}catch(IOException expected){ }
        }finally{remove(root);}
    }
    /** A Java FileLock can remain valid after an unrelated close has released
     * the kernel POSIX lock. Only a separate JVM establishes real exclusion. */
    private static void externalLease(Path path,boolean busy)throws Exception {
        Process child=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
            "-Xmx32m","-cp",System.getProperty("java.class.path"),GameSessionOwnerTests.class.getName(),
            "--probe-lease",path.toString()).redirectOutput(ProcessBuilder.Redirect.DISCARD)
            .redirectError(ProcessBuilder.Redirect.DISCARD).start();
        try {
            check(child.waitFor(8,TimeUnit.SECONDS),"Independent lock claimant must finish within eight seconds");
            check(child.exitValue()==(busy?73:0),"Cross-JVM kernel exclusion must survive duplicate refusals and release after close (expected "+(busy?73:0)+", observed "+child.exitValue()+")");
        } finally {
            if(child.isAlive())child.destroyForcibly();
            check(child.waitFor(3,TimeUnit.SECONDS),"Independent lock claimant must be reaped");
        }
    }
    private static void crossProcessDuplicateRefusal()throws Exception {
        Path root=Files.createTempDirectory("esteria-app-posix-lease-").toRealPath();Files.createDirectory(root.resolve("game"));
        Path work=Files.createDirectory(root.resolve("data-work")),other=Files.createDirectory(root.resolve("other-work"));
        Path imported=root.resolve("game/import.lock"),view=root.resolve("state/client-work/.client-launch-setup.lock"),setup=work.resolve(".android-server-data-setup.lock");
        try {
            try(GameSession.Leases owner=GameSession.claim(root)) {
                for(int index=0;index<16;index++) {
                    blocked(root);
                    try{GameSession.claim(root);throw new AssertionError("Duplicate game owner was admitted");}catch(IOException expected){ }
                    try{ServerDataSetup.claim(other,root.resolve("game"));throw new AssertionError("Data setup acquired playing import");}catch(IOException expected){ }
                }
                externalLease(imported,true);externalLease(view,true);
                externalLease(other.resolve(".android-server-data-setup.lock"),false);
            }
            externalLease(imported,false);externalLease(view,false);
            try(ServerDataSetup.Leases owner=ServerDataSetup.claim(work,root.resolve("game"))) {
                for(int index=0;index<16;index++) {
                    try{ServerDataSetup.claim(work,root.resolve("game"));throw new AssertionError("Duplicate data owner was admitted");}catch(IOException expected){ }
                    try{GameSession.claim(root);throw new AssertionError("Game owner acquired setup import");}catch(IOException expected){ }
                }
                externalLease(imported,true);externalLease(setup,true);
            }
            externalLease(imported,false);externalLease(setup,false);
        } finally {remove(root);}
    }
    private static void settle(OwnedProcess child)throws Exception {long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(2);check(!child.isAlive(),"Known creating process owner completed actual cleanup");}
    private static void remove(Path root)throws IOException {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    public static void main(String[] arguments)throws Exception {
        if(arguments.length==2&&arguments[0].equals("--probe-lease")) {
            try(ExclusiveFileLease lease=ExclusiveFileLease.acquire(Path.of(arguments[1]),"TEST_ONLY_BUSY")){System.exit(0);}
            catch(IOException busy){if("TEST_ONLY_BUSY".equals(busy.getMessage()))System.exit(73);throw busy;}
        }
        crossProcessDuplicateRefusal();gracefulFailureThenExplicitForce();naturalExit();prelaunch();typedViewLease();preservedForeignHandoff();persistentShutdownBudgets();startupCancellationHandoff();sourceCloseSequenceAndShaderSelection();
        System.out.println("Game owner passed9 host groups: cross-JVM duplicate/refusal/release, real owners/import+view locks, explicit-force/reap/bindings, source close sequence and shader stale guards; no native/SQL/Android/gameplay run");
    }
}
