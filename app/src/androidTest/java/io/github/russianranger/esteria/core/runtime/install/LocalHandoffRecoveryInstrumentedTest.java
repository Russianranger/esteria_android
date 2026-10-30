package io.github.russianranger.esteria.core.runtime.install;

import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;
import android.os.Process;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import java.io.ByteArrayOutputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.UUID;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Assume;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual Android remote-owner death and private-file recovery, not a client,
 * runtime, database or gameplay fixture. Ordinary APKs contain no probe service. */
@RunWith(AndroidJUnit4.class)
@android.annotation.TargetApi(33)
public final class LocalHandoffRecoveryInstrumentedTest {
    private static final String SERVICE="io.github.russianranger.esteria.core.runtime.install.HandoffProbeService";
    private static final String GENERATION="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private static final String UNKNOWN=".esteria-local-login-data-00000000000000000000000000000000.pending";
    private static final String[] PHASES={"created","written","proof-synced","synced","consumed"};
    private static final class Link implements ServiceConnection,AutoCloseable {
        final Context context;final HandlerThread worker=new HandlerThread("handoff-probe-replies");
        final ArrayBlockingQueue<IBinder> binders=new ArrayBlockingQueue<>(1);
        final ArrayBlockingQueue<Message> replies=new ArrayBlockingQueue<>(2);
        final Messenger incoming;boolean bound;IBinder binder;
        Link(Context context) {
            this.context=context;worker.start();
            incoming=new Messenger(new Handler(worker.getLooper(),message->{
                if(message.sendingUid==Process.myUid())replies.offer(Message.obtain(message));return true;
            }));
        }
        Messenger bind()throws Exception {
            bound=context.bindService(new Intent().setClassName(context,SERVICE),this,Context.BIND_AUTO_CREATE);
            assertTrue("Private debug service binds",bound);binder=binders.poll(8,TimeUnit.SECONDS);assertNotNull("Remote binder available",binder);return new Messenger(binder);
        }
        void send(Messenger remote,int command,int index)throws Exception {
            Message message=Message.obtain(null,command);message.arg1=index;message.replyTo=incoming;remote.send(message);
        }
        Bundle call(Messenger remote,int command,int index)throws Exception {
            send(remote,command,index);Message answer=replies.poll(8,TimeUnit.SECONDS);assertNotNull("Remote response",answer);
            assertEquals(command,answer.what);Bundle data=answer.getData();assertNull("Fixed remote failure token",data.getString("error"));answer.recycle();return data;
        }
        public void onServiceConnected(ComponentName name,IBinder service){if(SERVICE.equals(name.getClassName()))binders.offer(service);}
        public void onServiceDisconnected(ComponentName name){}
        public void close()throws Exception {
            try{if(bound)context.unbindService(this);}
            finally{worker.quitSafely();worker.join(1000);assertFalse("Reply thread stops",worker.isAlive());}
        }
    }
    private static void write(Path path,String text)throws Exception{write(path,text.getBytes(StandardCharsets.UTF_8));}
    private static void write(Path path,byte[] raw)throws Exception {
        try(FileChannel output=FileChannel.open(path,java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
            ByteBuffer bytes=ByteBuffer.wrap(raw);while(bytes.hasRemaining())output.write(bytes);output.force(true);
        }
    }
    private static Path directory(Path path)throws Exception {
        return Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }
    private static String instance(Bundle result) {
        String value=result.getString("instance");assertNotNull(value);assertEquals(UUID.fromString(value).toString(),value);return value;
    }
    private static JSONObject build(Context context)throws Exception {
        try(var input=context.getAssets().open("handoff-probe/build-evidence.json");var bytes=new ByteArrayOutputStream()) {
            byte[] block=new byte[4096];for(int got;(got=input.read(block))!=-1;){assertTrue(bytes.size()+got<=65536);bytes.write(block,0,got);}
            JSONObject value=new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            assertTrue(value.getBoolean("sourceSnapshotExact"));assertEquals(BuildConfig.SOURCE_REVISION,value.getString("sourceRevision"));return value;
        }
    }
    private static LocalAccountHandoff create(Path directory)throws Exception {
        char[] user="EST0123456789ABCD".toCharArray(),password="ABCDEFGHJKLMNPQR".toCharArray();
        try{return LocalAccountHandoff.create(new ClientLaunchView.Result(directory,GENERATION,0,true,true),user,password);}
        finally{Arrays.fill(user,'\0');Arrays.fill(password,'\0');}
    }
    private static void siblings(Path directory)throws Exception {
        assertEquals("PRESERVED_TEST_SETTINGS",RuntimeFiles.smallText(directory.resolve("WTF/Config.wtf"),128));
        assertEquals("PRESERVED_TEST_ACCOUNT_SAVE",RuntimeFiles.smallText(directory.resolve("account-save-sibling"),128));
        assertEquals("UNRECOGNIZED_STAGE_PRESERVED",RuntimeFiles.smallText(directory.resolve(UNKNOWN),128));
    }
    @Test public void remoteOwnerDeathRecoversOnlyKnownHandoffs()throws Exception {
        Assume.assumeTrue(BuildConfig.HANDOFF_EMULATOR_TEST);
        assertTrue(BuildConfig.DEBUG);assertEquals(33,Build.VERSION.SDK_INT);assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();JSONObject evidence=build(context);
        var service=context.getPackageManager().getServiceInfo(new ComponentName(context.getPackageName(),SERVICE),0);
        assertFalse("Probe service never exported",service.exported);assertEquals(context.getPackageName()+":handoffProbe",service.processName);
        assertNotEquals("The fixture may kill only its separate service process",android.app.Application.getProcessName(),service.processName);
        assertEquals(Process.myUid(),service.applicationInfo.uid);
        Path privateFiles=context.getFilesDir().getCanonicalFile().toPath();
        try(var children=Files.newDirectoryStream(privateFiles)){assertFalse("Previous application files are refused",children.iterator().hasNext());}
        Path root=directory(privateFiles.resolve("handoff-recovery-probe"));
        write(root.resolve(".scope"),"esteria-handoff-probe-v1\n"+BuildConfig.SOURCE_REVISION+"\n");
        for(int index=0;index<5;index++) {
            Path path=directory(root.resolve("case-"+index));write(path.resolve(".owner"),"esteria-client-launch-v1\n"+GENERATION+"\n");
            write(path.resolve("WowClient64.exe"),new byte[]{77,90});directory(path.resolve("WTF"));write(path.resolve("WTF/Config.wtf"),"PRESERVED_TEST_SETTINGS");
            write(path.resolve("account-save-sibling"),"PRESERVED_TEST_ACCOUNT_SAVE");write(path.resolve(UNKNOWN),"UNRECOGNIZED_STAGE_PRESERVED");
        }
        JSONArray cases=new JSONArray();
        for(int index=0;index<5;index++) {
            String previous;
            try(Link old=new Link(context)) {
                Messenger remote=old.bind();previous=instance(old.call(remote,1,0));CountDownLatch dead=new CountDownLatch(1);
                old.binder.linkToDeath(dead::countDown,0);old.send(remote,2,index);
                assertTrue("Actual remote process death observed",dead.await(8,TimeUnit.SECONDS));
            }
            try(Link next=new Link(context)) {
                Messenger remote=next.bind();String current=instance(next.call(remote,1,0));assertNotEquals(previous,current);
                JSONObject result=new JSONObject(next.call(remote,3,index).getString("result"));assertEquals(PHASES[index],result.getString("phase"));
                assertEquals(index==3,result.getBoolean("clientRecordBefore"));assertEquals(index>=2,result.getBoolean("ownerReceiptBefore"));
                for(String key:new String[]{"recovered","knownStateMatched","unknownStagesPreserved","siblingsPreserved","recordAbsentAfterClose","receiptAbsentAfterClose"})assertTrue(key,result.getBoolean(key));
                result.put("binderDeathObserved",true).put("ownerInstanceChanged",true);cases.put(result);
            }
        }
        JSONObject active=new JSONObject();Path first=root.resolve("case-0");
        try(Link link=new Link(context)) {
            Messenger remote=link.bind();assertTrue(link.call(remote,4,0).getBoolean("sameJvmDuplicateRefused"));
            byte[] record=Files.readAllBytes(first.resolve(LocalAccountHandoff.FILENAME));boolean refused=false;
            try(LocalAccountHandoff unexpected=create(first)){}
            catch(java.io.IOException expected){refused=true;}
            assertTrue("Another process cannot recover an active handoff",refused);
            assertArrayEquals(record,Files.readAllBytes(first.resolve(LocalAccountHandoff.FILENAME)));Arrays.fill(record,(byte)0);
            assertTrue(link.call(remote,5,0).getBoolean("released"));
            try(LocalAccountHandoff acquired=create(first)){assertEquals(57,Files.size(first.resolve(LocalAccountHandoff.FILENAME)));}
            siblings(first);active.put("sameJvmDuplicateRefused",true).put("crossProcessRefused",true).put("recordUnchanged",true)
                    .put("released",true).put("relaunchAfterRelease",true).put("siblingsPreserved",true);
        }
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-local-handoff-remote-owner-process-death")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",Build.VERSION.SDK_INT)
                .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("abi","x86_64").put("buildEvidence",evidence)
                .put("cases",cases).put("activeOwner",active).put("remoteOwnerProcessesKilled",5).put("remoteOwnerProcessesRecreated",5)
                .put("syntheticClientExecutableNotRun",true).put("productionAppProcessRestartQualified",false).put("physicalDeviceQualified",false)
                .put("clientExecuted",false).put("sqlExecuted",false).put("arm64Qualified",false).put("gameplayQualified",false);
        write(context.getFilesDir().getCanonicalFile().toPath().resolve("handoff-recovery-qualification.json"),receipt.toString().getBytes(StandardCharsets.UTF_8));
    }
}
