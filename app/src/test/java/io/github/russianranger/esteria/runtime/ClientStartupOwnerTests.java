package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.LocalAccountHandoff;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Real lease/owner behavior with a delayed backend; no native/client/frame proof. */
public final class ClientStartupOwnerTests {
    private static void check(boolean value,String text){if(!value)throw new AssertionError(text);}
    private static void set(Object object,String name,Object value)throws Exception {
        Field field=object.getClass().getDeclaredField(name);field.setAccessible(true);field.set(object,value);
    }
    @SuppressWarnings("unchecked") private static Map<Path,ClientStartupSession> owners()throws Exception {
        Field field=ClientStartupSession.class.getDeclaredField("OWNERS");field.setAccessible(true);
        return (Map<Path,ClientStartupSession>)field.get(null);
    }
    private static ClientStartupSession owner(Path root)throws Exception {
        Constructor<ClientStartupSession> constructor=ClientStartupSession.class.getDeclaredConstructor(Context.class,Path.class,
            RuntimeSetup.class,ClientRuntimeSetup.class,GuestBridgeSetup.class,ShaderToolsSetup.class,ShaderSetup.Result.class,
            TurnipSetup.class,ClientPresentationSession.Events.class,GameSession.Leases.class);
        constructor.setAccessible(true);
        ClientStartupSession owner=constructor.newInstance(null,root,null,null,null,null,null,null,null,GameSession.claim(root));
        owners().put(root,owner);return owner;
    }
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch release=new CountDownLatch(1),terminating=new CountDownLatch(1);
        public long start(OwnedProcess.Specification specification){return 1;}
        public int waitFor(long handle,long timeout)throws IOException {
            try{Thread.sleep(2);}catch(InterruptedException error){throw new IOException(error);}return OwnedProcess.RUNNING;
        }
        public int terminate(long handle)throws IOException {
            terminating.countDown();try{if(!release.await(40,TimeUnit.SECONDS))throw new IOException("TEST_ONLY_TIMEOUT");}
            catch(InterruptedException error){throw new IOException(error);}return 143;
        }
        public long[] diagnostics(long handle){return new long[5];}
    }
    private static void retainedCancellation()throws Exception {
        Path root=Files.createTempDirectory("esteria-title-owner-").toRealPath();Files.createDirectory(root.resolve("game"));
        Backend backend=new Backend();ClientStartupSession owner=null;OwnedProcess child=null;
        try {
            Path retained=root.resolve("game/retained-import");Files.writeString(retained,"TEST_ONLY_INPUT");
            owner=owner(root);
            child=OwnedProcess.start(backend,new OwnedProcess.Specification(root.resolve("fixture"),List.of(),Map.of(),root,
                root.resolve("stdout"),root.resolve("stderr")),null);
            set(owner,"process",child);set(owner,"state",ClientStartupSession.State.CLIENT_STARTED);
            try{owner.close(Duration.ZERO);throw new AssertionError("Pending cleanup was marked complete");}catch(IOException expected){ }
            check(backend.terminating.getCount()==0&&child.isAlive(),"Real owned termination requested; delayed backend is still live");
            check(owners().get(root)==owner&&owner.state()==ClientStartupSession.State.STOPPING,"Live owner retained after timeout");
            try{GameSession.claim(root);throw new AssertionError("Production session admitted during title cleanup");}catch(IOException expected){ }
            backend.release.countDown();long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(2);
            check(!child.isAlive(),"Owned process has been reaped");
            try{ClientStartupSession.retryPendingCleanup(root,Duration.ofSeconds(1));}catch(IOException expected){ }
            check(owner.state()==ClientStartupSession.State.CLOSED&&!owners().containsKey(root),"Final cleanup releases registry");
            try(GameSession.Leases ignored=GameSession.claim(root)){ }
            check(Files.readString(retained).equals("TEST_ONLY_INPUT"),"Cancellation preserves imported bytes");
        } finally {
            backend.release.countDown();if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException ignored){ }
            if(owner!=null&&owner.state()!=ClientStartupSession.State.CLOSED)try{owner.close(Duration.ZERO);}catch(IOException ignored){ }
            remove(root);
        }
    }
    private static void launchArguments()throws Exception {
        Path root=Files.createTempDirectory("esteria-title-arguments-");
        Method method=ClientPresentationSession.class.getDeclaredMethod("clientModeArguments",List.class,Path.class,boolean.class);
        method.setAccessible(true);List<String> local=List.of("--local-offline","--local-login");
        try {
            check(method.invoke(null,local,root,false).equals(List.of("--local-offline")),"Title mode keeps offline and omits autologin");
            check(method.invoke(null,local,root,true).equals(local),"Production mode retains original login arguments");
            Path handoff=root.resolve(LocalAccountHandoff.FILENAME);Files.writeString(handoff,"TEST_ONLY_PRIVATE_RECORD");
            try{method.invoke(null,local,root,false);throw new AssertionError("Title mode accepted retained credentials");}
            catch(InvocationTargetException expected){check(expected.getCause() instanceof IOException,"Typed handoff refusal");}
            check(Files.readString(handoff).equals("TEST_ONLY_PRIVATE_RECORD"),"Retained handoff preserved");
            try{method.invoke(null,List.of("--local-login"),root,true);throw new AssertionError("Unqualified mode accepted");}
            catch(InvocationTargetException expected){check(expected.getCause() instanceof IOException,"Capability disagreement refused");}
        } finally {remove(root);}
    }
    private static void remove(Path root)throws Exception {
        try(var paths=Files.walk(root)){for(Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(path);}
    }
    public static void main(String[] args)throws Exception {
        launchArguments();retainedCancellation();
        System.out.println("Client startup owner: argument isolation and retained cancellation passed (host fixtures only)");
    }
}
