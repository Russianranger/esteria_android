// SPDX-License-Identifier: GPL-3.0-only
package io.github.russianranger.esteria.runtime;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;
import android.os.Process;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.TimeUnit;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONObject;
import static org.junit.Assert.*;

/** Real Android remote-process cleanup; does not attribute OS cleanup to PDEATHSIG. */
final class RemoteOwnerDeathProbe {
    private static final String SERVICE="io.github.russianranger.esteria.runtime.ProbeOwnerService";
    private static final String ARMED="\u0001\u0001\u0001";
    private static final class Link implements ServiceConnection,AutoCloseable {
        final HandlerThread reader=new HandlerThread("esteria-owner-probe-replies");
        final ArrayBlockingQueue<IBinder> connections=new ArrayBlockingQueue<>(1);
        final ArrayBlockingQueue<Message> replies=new ArrayBlockingQueue<>(2);
        final Context context;
        final Messenger incoming;
        boolean bound;
        Link(Context context) {
            this.context=context;reader.start();
            incoming=new Messenger(new Handler(reader.getLooper(),message->{
                if(message.sendingUid==Process.myUid())replies.offer(Message.obtain(message));return true;
            }));
        }
        Messenger bind()throws Exception {
            Intent intent=new Intent().setClassName(context,SERVICE);
            bound=context.bindService(intent,this,Context.BIND_AUTO_CREATE);
            assertTrue("Probe-only remote service must exist",bound);
            IBinder remote=connections.poll(8,TimeUnit.SECONDS);assertNotNull("Remote service bound",remote);return new Messenger(remote);
        }
        Bundle call(Messenger remote,int what)throws Exception {
            Message request=Message.obtain(null,what);request.replyTo=incoming;remote.send(request);
            Message response=replies.poll(8,TimeUnit.SECONDS);assertNotNull("Remote service reply",response);
            assertEquals(what,response.what);Bundle value=response.getData();assertNull(value.getString("error"));response.recycle();return value;
        }
        @Override public void onServiceConnected(ComponentName name,IBinder service) { if(SERVICE.equals(name.getClassName()))connections.offer(service); }
        @Override public void onServiceDisconnected(ComponentName name) { /* Pidfd observes the exact original process. */ }
        @Override public void close()throws InterruptedException {
            try{if(bound)context.unbindService(this);}
            finally{reader.quitSafely();reader.join(1000);assertFalse("Probe reply thread stopped",reader.isAlive());}
        }
    }
    private static final class Chain {
        long tracer;
        final List<Long> guests=new ArrayList<>();
    }
    private static Path directory(Path path)throws IOException {
        Files.createDirectory(path);Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rwx------"));return path;
    }
    private static String read(Path path)throws IOException {
        ByteArrayOutputStream output=new ByteArrayOutputStream();
        try(InputStream input=Files.newInputStream(path)){byte[] buffer=new byte[4096];int count;
            while((count=input.read(buffer))!=-1){if(output.size()+count>65536)throw new IOException("Oversized owner probe log");output.write(buffer,0,count);}}
        return new String(output.toByteArray(),StandardCharsets.UTF_8);
    }
    private static Chain capture(Path session,Path tracer,Path loader,Path guest,List<Long> watched)throws Exception {
        Path stdout=session.resolve("logs/stdout.log"),armed=session.resolve("work/armed");
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);String handshake="";
        while(System.nanoTime()<deadline){
            if(Files.exists(stdout))handshake=read(stdout);
            if(handshake.chars().filter(ch->ch=='\n').count()==3&&Files.exists(armed)&&ARMED.equals(read(armed)))break;
            Thread.sleep(10);
        }
        assertEquals("Three remote-chain identities",3,handshake.split("\n").length);
        assertEquals("All remote-chain guests in CPU-only wait",ARMED,read(armed));
        Pattern pattern=Pattern.compile("^ESTERIA_PROOT_OWNER_PID ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*)$",Pattern.MULTILINE);
        Matcher match=pattern.matcher(handshake);Chain chain=new Chain();HashSet<Integer> pids=new HashSet<>();int tracerPid=0;long tracerTicks=0;
        while(match.find()){
            int pid=Integer.parseInt(match.group(1)),reportedTracer=Integer.parseInt(match.group(3));
            long ticks=Long.parseLong(match.group(2)),reportedTicks=Long.parseLong(match.group(4));
            assertEquals(pid,Integer.parseInt(match.group(5)));assertNotEquals(pid,reportedTracer);
            if(tracerPid==0){tracerPid=reportedTracer;tracerTicks=reportedTicks;
                chain.tracer=ProbeProcessHandles.watch(tracerPid,tracerTicks,0,tracer.toString(),"");watched.add(chain.tracer);}
            assertEquals(tracerPid,reportedTracer);assertEquals(tracerTicks,reportedTicks);assertTrue(pids.add(pid));
            long handle=ProbeProcessHandles.watch(pid,ticks,tracerPid,loader.toString(),guest.toString());
            watched.add(handle);chain.guests.add(handle);
        }
        assertEquals(3,chain.guests.size());return chain;
    }
    private static void alive(Chain chain)throws IOException {
        assertFalse("Control tracer remains alive",ProbeProcessHandles.exited(chain.tracer,0));
        for(long handle:chain.guests)assertFalse("Detached tracee remains alive",ProbeProcessHandles.exited(handle,200));
    }
    static JSONObject run(Context context,Path root,Path tracer,Path loader)throws Exception {
        android.content.pm.ServiceInfo service=context.getPackageManager().getServiceInfo(new ComponentName(context.getPackageName(),SERVICE),0);
        assertFalse("Remote probe service is never exported",service.exported);
        assertEquals(context.getPackageName()+":prootOwnerProbe",service.processName);
        assertEquals(Process.myUid(),service.applicationInfo.uid);
        // Starts before either chain, so no30-second fixture alarm can prove cleanup.
        long started=System.nanoTime();Path session=directory(root.resolve("owner-process-death"));
        Path controlRoot=directory(session.resolve("control"));Path work=directory(controlRoot.resolve("work"));
        Path temporary=directory(controlRoot.resolve("tmp")),logs=directory(controlRoot.resolve("logs"));
        Map<String,String> environment=new HashMap<>();environment.put("PROOT_LOADER",loader.toString());
        environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
        OwnedProcess control=null;List<Long> watched=new ArrayList<>();
        try(Link link=new Link(context)){
            Messenger remote=link.bind();Bundle owner=link.call(remote,1);
            int ownerPid=owner.getInt("pid");assertNotEquals(Process.myPid(),ownerPid);
            String androidExecutable=Files.readSymbolicLink(Paths.get("/proc/self/exe")).toString();
            long ownerHandle=ProbeProcessHandles.watch(ownerPid,owner.getLong("startTicks"),0,androidExecutable,"");watched.add(ownerHandle);
            assertTrue("Real remote child started",link.call(remote,2).getBoolean("started"));
            Chain protectedChain=capture(session.resolve("service"),tracer,loader,root.resolve("rootfs/probe-owner"),watched);
            control=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(tracer,
                Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",root.resolve("rootfs").toString(),"-b","/dev","-b","/proc",
                    "-b",work+":/work","-b",temporary+":/tmp","-w","/work","/probe-owner","/work","forced"),
                environment,work,logs.resolve("stdout.log"),logs.resolve("stderr.log")),null);
            Chain controlChain=capture(controlRoot,tracer,loader,root.resolve("rootfs/probe-owner"),watched);
            assertEquals(9,watched.size());alive(protectedChain);alive(controlChain);
            assertTrue("Owner-death intervention budget",System.nanoTime()-started<TimeUnit.SECONDS.toNanos(25));
            ProbeProcessHandles.kill(ownerHandle);
            assertTrue("Verified remote owner exited",ProbeProcessHandles.exited(ownerHandle,5000));
            assertTrue("Remote owner's tracer exited",ProbeProcessHandles.exited(protectedChain.tracer,5000));
            for(long handle:protectedChain.guests)assertTrue("Remote owner's detached tracee exited",ProbeProcessHandles.exited(handle,5000));
            alive(controlChain);assertTrue("Surviving instrumentation still owns control",control.isAlive());
            long elapsed=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-started);
            assertTrue("Alarms cannot establish remote-owner cleanup",elapsed<25000);
            return new JSONObject().put("androidOwnerProcessDeathQualified",true).put("ownerDeathObservationMillis",elapsed)
                .put("ownerDeathVerifiedHandles",9).put("ownerDeathControlSurvivors",3).put("ownerDeathProtectedSurvivors",0)
                .put("ownerDeathControlTracerSurvived",true).put("ownerDeathProtectedTracerExited",true)
                .put("isolatedParentDeathSignalQualified",false);
        }finally{
            IOException cleanup=null;
            // Signal only retained descriptors. The first is the service identity;
            // Android may also have recreated an idle service after Binder death.
            for(long handle:watched)try{ProbeProcessHandles.kill(handle);if(!ProbeProcessHandles.exited(handle,5000))throw new IOException("Remote probe cleanup timed out");}
                catch(IOException error){if(cleanup==null)cleanup=error;else cleanup.addSuppressed(error);}
                finally{try{ProbeProcessHandles.close(handle);}catch(IOException error){if(cleanup==null)cleanup=error;else cleanup.addSuppressed(error);}}
            if(control!=null&&control.isAlive())try{control.stop(Duration.ZERO);}catch(IOException forced){if(control.isAlive()){if(cleanup==null)cleanup=forced;else cleanup.addSuppressed(forced);}}
            if(cleanup!=null)throw cleanup;
        }
    }
}
