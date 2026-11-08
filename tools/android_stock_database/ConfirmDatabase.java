package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.File;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Calls the installed APK as its package UID. Only a fresh, named QA store is writable. */
public final class ConfirmDatabase {
    public static void main(String[] args) throws Exception {
        if(args.length!=1 || !(args[0].equals("cold") || args[0].equals("warm")))
            throw new IllegalArgumentException("cold or warm required");
        if(Looper.myLooper()==null) Looper.prepareMainLooper();
        Class<?> thread=Class.forName("android.app.ActivityThread");
        Object activity=thread.getMethod("systemMain").invoke(null);
        Context system=(Context)thread.getMethod("getSystemContext").invoke(activity);
        Context pkg=system.createPackageContext("io.github.russianranger.esteria.stock",0);
        if(android.os.Process.myUid()!=pkg.getApplicationInfo().uid)throw new IllegalStateException("Package UID required");
        Path root=pkg.getFilesDir().getCanonicalFile().toPath().resolve("qa-signed-stock-database");
        Context context=new ContextWrapper(pkg) {
            @Override public Context getApplicationContext(){return this;}
            @Override public File getFilesDir(){return root.toFile();}
        };
        System.load(pkg.getApplicationInfo().nativeLibraryDir+"/libesteria_process.so");
        FutureTask<Void> job=new FutureTask<>(()->{
            boolean cold=args[0].equals("cold");
            if(cold)Files.createDirectory(root,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            ServerRuntimeSetup server=new ServerRuntimeSetup(context,root);
            long start=System.nanoTime();
            java.util.HashSet<String> reported=new java.util.HashSet<>();
            RuntimeWork.Progress progress=(phase,path,done,total)->{
                if(reported.add(phase))System.out.println("ANDROID_DB_PHASE "+phase+" "+(System.nanoTime()-start)/1_000_000);
            };
            RuntimeInstaller.Result provider=server.prepare(progress,RuntimeWork.NEVER_CANCELLED);
            long installed=System.nanoTime();
            if(cold==provider.alreadyInstalled || (cold ? provider.copiedBytes<=0 : provider.copiedBytes!=0))
                throw new IllegalStateException("Unexpected provider reuse");
            ServerDatabaseSetup.Result result=ServerDatabaseSetup.prepare(context,root,server,progress,RuntimeWork.NEVER_CANCELLED);
            long prepared=System.nanoTime();
            if(!(cold ? "initialized" : "already-initialized").equals(result.operation))
                throw new IllegalStateException("Unexpected bootstrap operation");
            System.out.println("ANDROID_DB_PHASE database-prepared "+(prepared-start)/1_000_000);
            ServerDatabaseService.Handle handle=ServerDatabaseService.start(context,root,server);
            long ready;
            try {
                ServerDatabaseService.awaitReady(handle,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),new AtomicBoolean(false));
                ready=System.nanoTime();
                if(!result.instanceUuid.equals(handle.instanceUuid()))
                    throw new IllegalStateException("Owned SQL service identity mismatch");
            } finally {
                handle.stop(Duration.ofSeconds(30));
            }
            if(handle.isAlive() || handle.exitCode()!=0)throw new IllegalStateException("SQL service did not close cleanly");
            long stopped=System.nanoTime();
            System.out.println("ANDROID_DB_RESULT "+new JSONObject().put("mode",args[0])
                    .put("operation",result.operation).put("instanceUuid",result.instanceUuid)
                    .put("providerGeneration",provider.generation).put("providerCopiedBytes",provider.copiedBytes)
                    .put("version",result.version).put("providerMs",(installed-start)/1_000_000)
                    .put("bootstrapMs",(prepared-installed)/1_000_000).put("nativeStartupMs",(ready-prepared)/1_000_000)
                    .put("cleanShutdownMs",(stopped-ready)/1_000_000).put("sameAuthenticatedInstance",true)
                    .put("closed",true));
            return null;
        });
        new Thread(job,"qa-signed-database").start();
        try { job.get(); }
        catch(java.util.concurrent.ExecutionException failure){
            System.err.println("ANDROID_DB_EXCEPTION "+failure.getCause().getClass().getName());
            throw failure;
        }
    }
}
