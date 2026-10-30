// SPDX-License-Identifier: GPL-3.0-only
package io.github.russianranger.esteria.runtime;

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
import android.util.Log;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

/** Debug-profile-only remote owner; no path, program or environment is caller-selected. */
public final class ProbeOwnerService extends Service {
    private HandlerThread worker;
    private Handler handler;
    private Messenger messenger;
    private OwnedProcess child;
    private boolean begun;

    @Override public void onCreate() {
        super.onCreate();
        if(!BuildConfig.DEBUG||Build.VERSION.SDK_INT!=33||!Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"))
            throw new IllegalStateException("Disposable Android13 x64 debug probe required");
        worker=new HandlerThread("esteria-probe-service");worker.start();
        handler=new Handler(worker.getLooper(),this::receive);messenger=new Messenger(handler);
    }
    @Override public IBinder onBind(Intent intent) { return messenger.getBinder(); }
    private boolean receive(Message request) {
        if(request.sendingUid!=Process.myUid()||request.replyTo==null)return true;
        Bundle result=new Bundle();
        try {
            if(request.what==1){result.putInt("pid",Process.myPid());result.putLong("startTicks",startTicks());}
            else if(request.what==2){
                if(begun)throw new IllegalStateException("Probe service already started");begun=true;
                Path root=getFilesDir().toPath().toRealPath().resolve("proot-probe-session");
                Path session=directory(root.resolve("owner-process-death/service"));
                Path work=directory(session.resolve("work")),temporary=directory(session.resolve("tmp")),logs=directory(session.resolve("logs"));
                Path natives=Paths.get(getApplicationInfo().nativeLibraryDir);
                Map<String,String> environment=new HashMap<>();
                environment.put("PROOT_LOADER",natives.resolve("libproot_probe_loader.so").toString());
                environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
                child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(natives.resolve("libproot_probe.so"),
                    Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",root.resolve("rootfs").toString(),"-b","/dev","-b","/proc",
                        "-b",work+":/work","-b",temporary+":/tmp","-w","/work","/probe-owner","/work","forced"),
                    environment,work,logs.resolve("stdout.log"),logs.resolve("stderr.log")),null);
                result.putBoolean("started",child.isAlive());
            }else throw new IllegalArgumentException("Unknown probe service message");
        }catch(Exception failure){
            result.putString("error",failure.getClass().getSimpleName()+": "+failure.getMessage());cleanup();
        }
        Message response=Message.obtain(null,request.what);response.setData(result);
        try{request.replyTo.send(response);}catch(RemoteException disconnected){cleanup();}
        return true;
    }
    private static Path directory(Path path)throws Exception {
        Files.createDirectory(path);Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rwx------"));return path;
    }
    private static long startTicks()throws Exception {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        try(InputStream input=Files.newInputStream(Paths.get("/proc/self/stat"))){
            byte[] buffer=new byte[1024];int count;
            while((count=input.read(buffer))!=-1){if(bytes.size()+count>4096)throw new IllegalStateException("Oversized service identity");bytes.write(buffer,0,count);}
        }
        String value=new String(bytes.toByteArray(),StandardCharsets.US_ASCII);int end=value.lastIndexOf(')');
        if(end<0)throw new IllegalStateException("Invalid service identity");
        String[] fields=value.substring(end+2).trim().split("\\s+");
        if(fields.length<20)throw new IllegalStateException("Incomplete service identity");
        long ticks=Long.parseLong(fields[19]);if(ticks<=0)throw new IllegalStateException("Invalid service start time");return ticks;
    }
    private void cleanup() {
        if(child!=null&&child.isAlive())try{child.stop(Duration.ZERO);}catch(Exception forced){
            if(child.isAlive())Log.e("EsteriaProbe","Remote test child cleanup failed",forced);
        }
    }
    @Override public void onDestroy() {
        handler.post(this::cleanup);worker.quitSafely();super.onDestroy();
    }
}
