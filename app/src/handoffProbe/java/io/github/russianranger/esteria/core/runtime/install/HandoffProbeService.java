package io.github.russianranger.esteria.core.runtime.install;

import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Message;
import android.os.Messenger;
import android.os.Process;
import android.os.RemoteException;
import io.github.russianranger.esteria.BuildConfig;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.json.JSONObject;

/** Only the explicit x64 debug profile contains this unexported service. It
 * accepts fixed commands/case numbers, never a PID, path or executable. */
@android.annotation.TargetApi(33)
public final class HandoffProbeService extends Service {
    private static final String GENERATION="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private static final String UNKNOWN=".esteria-local-login-data-00000000000000000000000000000000.pending";
    private static final String[] PHASES={"created","written","proof-synced","synced","consumed"};
    private final String instance=UUID.randomUUID().toString();
    private HandlerThread worker;
    private Messenger messenger;
    private LocalAccountHandoff held;
    private boolean used;
    private JSONObject build;
    @Override public void onCreate() {
        super.onCreate();
        try {
            if(!BuildConfig.DEBUG||!BuildConfig.HANDOFF_EMULATOR_TEST||Build.VERSION.SDK_INT!=33||
                    !Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64")||!BuildConfig.SOURCE_REVISION.matches("[a-f0-9]{40}")||
                    !android.app.Application.getProcessName().equals(BuildConfig.APPLICATION_ID+":handoffProbe"))
                throw new IOException("handoff-probe-context-refused");
            try(var input=getAssets().open("handoff-probe/build-evidence.json");var output=new ByteArrayOutputStream()) {
                byte[] block=new byte[4096];for(int got;(got=input.read(block))!=-1;){if(output.size()+got>65536)throw new IOException("handoff-probe-build-bound");output.write(block,0,got);}
                build=new JSONObject(output.toString(StandardCharsets.UTF_8.name()));
            }
            if(!build.getBoolean("sourceSnapshotExact")||!build.getString("sourceRevision").equals(BuildConfig.SOURCE_REVISION)||
                    !build.getString("scope").equals("android-x64-handoff-fixture-build-only"))throw new IOException("handoff-probe-source-refused");
        }catch(Exception failure){throw new IllegalStateException("handoff-probe-admission-failed",failure);}
        worker=new HandlerThread("esteria-handoff-probe");worker.start();messenger=new Messenger(new Handler(worker.getLooper(),this::receive));
    }
    @Override public IBinder onBind(Intent intent){return messenger.getBinder();}
    private boolean receive(Message request) {
        if(request.sendingUid!=Process.myUid()||request.replyTo==null)return true;
        Bundle response=new Bundle();
        try {
            if(request.arg2!=0||request.obj!=null||(request.peekData()!=null&&!request.peekData().isEmpty()))throw new IOException("handoff-probe-extra-authority-refused");
            if(request.what==1)response.putString("instance",instance);
            else if(request.what==2) {
                if(used||request.arg1<0||request.arg1>=5)throw new IOException("handoff-probe-crash-case-refused");used=true;
                Path directory=caseDirectory(request.arg1);String phase=PHASES[request.arg1];
                try(LocalAccountHandoff owner=create(directory,reached->{if(reached.equals(phase))crash(directory,phase);})) {
                    if(phase.equals("consumed")){Files.delete(directory.resolve(LocalAccountHandoff.FILENAME));crash(directory,phase);}
                }
                throw new IOException("handoff-probe-crash-boundary-not-reached");
            }else if(request.what==3)response.putString("result",recover(request.arg1).toString());
            else if(request.what==4) {
                if(used||request.arg1!=0)throw new IOException("handoff-probe-hold-case-refused");used=true;
                Path directory=caseDirectory(0);held=create(directory,phase->{});
                boolean refused=false;try(LocalAccountHandoff unexpected=create(directory,phase->{})){}
                catch(IOException expected){refused=true;}
                if(!refused)throw new IOException("handoff-probe-local-reentry-admitted");
                response.putBoolean("sameJvmDuplicateRefused",true);
            }else if(request.what==5) {
                if(request.arg1!=0||held==null)throw new IOException("handoff-probe-release-case-refused");
                held.close();held=null;Path directory=caseDirectory(0);
                response.putBoolean("released",!Files.exists(directory.resolve(LocalAccountHandoff.FILENAME),LinkOption.NOFOLLOW_LINKS)&&
                        !Files.exists(directory.resolve(LocalHandoffRecovery.OWNER),LinkOption.NOFOLLOW_LINKS));
            }else throw new IOException("handoff-probe-command-refused");
        }catch(Exception failure){response.putString("error","handoff-probe-"+failure.getClass().getSimpleName());}
        Message answer=Message.obtain(null,request.what);answer.setData(response);
        try{request.replyTo.send(answer);}catch(RemoteException disconnected){closeHeld();}
        return true;
    }
    private Path caseDirectory(int index)throws Exception {
        if(index<0||index>=5)throw new IOException("handoff-probe-case-refused");
        Path root=getFilesDir().getCanonicalFile().toPath().resolve("handoff-recovery-probe");
        if(!root.equals(root.toRealPath())||!RuntimeFiles.smallText(root.resolve(".scope"),256).equals("esteria-handoff-probe-v1\n"+BuildConfig.SOURCE_REVISION+"\n"))
            throw new IOException("handoff-probe-root-refused");
        Path directory=root.resolve("case-"+index);
        if(!directory.equals(directory.toRealPath()))throw new IOException("handoff-probe-case-refused");return directory;
    }
    private static LocalAccountHandoff create(Path directory,LocalAccountHandoff.CreationCheck check)throws IOException {
        char[] user="EST0123456789ABCD".toCharArray(),password="ABCDEFGHJKLMNPQR".toCharArray();
        try{return LocalAccountHandoff.create(new ClientLaunchView.Result(directory,GENERATION,0,true,true),user,password,check);}
        finally{Arrays.fill(user,'\0');Arrays.fill(password,'\0');}
    }
    private void crash(Path directory,String phase)throws IOException {
        try {
            byte[] raw=new JSONObject().put("phase",phase).put("instance",instance).put("sourceRevision",BuildConfig.SOURCE_REVISION).toString().getBytes(StandardCharsets.UTF_8);
            try(FileChannel output=FileChannel.open(directory.resolve("reached.json"),java.util.EnumSet.of(StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE),
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")))) {
                ByteBuffer bytes=ByteBuffer.wrap(raw);while(bytes.hasRemaining())output.write(bytes);output.force(true);
            }
            if(!RuntimeFiles.sync(directory))throw new IOException("handoff-probe-marker-sync-failed");
            Process.killProcess(Process.myPid());throw new IOException("handoff-probe-self-kill-returned");
        }catch(org.json.JSONException failure){throw new IOException("handoff-probe-marker-invalid",failure);}
    }
    private JSONObject recover(int index)throws Exception {
        if(index<0||index>=5||held!=null)throw new IOException("handoff-probe-recovery-case-refused");
        Path directory=caseDirectory(index);JSONObject marker=new JSONObject(RuntimeFiles.smallText(directory.resolve("reached.json"),1024));
        if(!marker.getString("phase").equals(PHASES[index])||marker.getString("instance").equals(instance)||
                !marker.getString("sourceRevision").equals(BuildConfig.SOURCE_REVISION))throw new IOException("handoff-probe-old-instance-required");
        boolean before=Files.exists(directory.resolve(LocalAccountHandoff.FILENAME),LinkOption.NOFOLLOW_LINKS),
                proof=Files.exists(directory.resolve(LocalHandoffRecovery.OWNER),LinkOption.NOFOLLOW_LINKS);
        boolean known=before==(index==3)&&proof==(index>=2);if(!known)throw new IOException("handoff-probe-known-state-differs");
        Map<String,String> retained=new LinkedHashMap<>();
        try(var paths=Files.list(directory)) {
            Path[] children=paths.toArray(Path[]::new);if(children.length>64)throw new IOException("handoff-probe-inventory-bound");
            for(Path path:children)if(path.getFileName().toString().equals(UNKNOWN)||(index<2&&path.getFileName().toString().endsWith(".pending"))) {
                if(Files.isSymbolicLink(path)||Files.size(path)>1024)throw new IOException("handoff-probe-retained-file-invalid");
                retained.put(path.getFileName().toString(),RuntimeFiles.hashFile(path,Files.size(path),RuntimeWork.NEVER_CANCELLED));
            }
        }
        try(LocalAccountHandoff owner=create(directory,phase->{})) {
            if(Files.size(directory.resolve(LocalAccountHandoff.FILENAME))!=57)throw new IOException("handoff-probe-recovery-record-invalid");
        }
        for(var entry:retained.entrySet()) {
            Path path=directory.resolve(entry.getKey());if(!RuntimeFiles.hashFile(path,Files.size(path),RuntimeWork.NEVER_CANCELLED).equals(entry.getValue()))throw new IOException("handoff-probe-retained-file-changed");
        }
        boolean siblings=RuntimeFiles.smallText(directory.resolve("WTF/Config.wtf"),128).equals("PRESERVED_TEST_SETTINGS")&&
                RuntimeFiles.smallText(directory.resolve("account-save-sibling"),128).equals("PRESERVED_TEST_ACCOUNT_SAVE")&&
                RuntimeFiles.smallText(directory.resolve(UNKNOWN),128).equals("UNRECOGNIZED_STAGE_PRESERVED");
        if(!siblings)throw new IOException("handoff-probe-sibling-changed");
        return new JSONObject().put("phase",PHASES[index]).put("recovered",true).put("clientRecordBefore",before).put("ownerReceiptBefore",proof)
                .put("knownStateMatched",true).put("unknownStagesPreserved",true).put("siblingsPreserved",true)
                .put("recordAbsentAfterClose",!Files.exists(directory.resolve(LocalAccountHandoff.FILENAME),LinkOption.NOFOLLOW_LINKS))
                .put("receiptAbsentAfterClose",!Files.exists(directory.resolve(LocalHandoffRecovery.OWNER),LinkOption.NOFOLLOW_LINKS));
    }
    private void closeHeld(){if(held!=null)try{held.close();held=null;}catch(IOException preserved){/* Fixed private fixture only; qualifier retains failure then force-stops its fresh package. */}}
    @Override public void onDestroy(){if(worker!=null){new Handler(worker.getLooper()).post(this::closeHeld);worker.quitSafely();}super.onDestroy();}
}
