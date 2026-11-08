package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.HashSet;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Disposable fresh installed package. All SQL, native processes, receipts and leases belong to the signed APK. */
public final class ConfirmDatabase {
    private static long elapsed(long start) { return (System.nanoTime()-start)/1_000_000; }

    private static JSONObject run(Context context, Path root, boolean cold) throws Exception {
        Path data=root.resolve("qa-server-data-directory");
        if(cold) Files.createDirectory(data);
        if(!Files.isDirectory(data) || !data.equals(data.toRealPath()))
            throw new IllegalStateException("Disjoint QA schema config directory required");
        ServerRuntimeSetup server=new ServerRuntimeSetup(context,root);
        ServerProgramsSetup programs=new ServerProgramsSetup(context,root);
        ServerContentSetup content=new ServerContentSetup(context,root);
        long start=System.nanoTime();
        HashSet<String> reported=new HashSet<>();
        RuntimeWork.Progress progress=(phase,path,done,total)->{
            if(reported.add(phase)) System.out.println("ANDROID_DB_PHASE "+phase+" "+elapsed(start));
        };
        RuntimeInstaller.Result runtime=server.prepare(progress,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller.Result executables=programs.prepare(server.archiveSha256(),progress,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller.Result sql=content.prepare(server.archiveSha256(),progress,RuntimeWork.NEVER_CANCELLED);
        long copied=runtime.copiedBytes+executables.copiedBytes+sql.copiedBytes;
        if(cold==(runtime.alreadyInstalled || executables.alreadyInstalled || sql.alreadyInstalled) ||
           (cold ? copied<=0 : copied!=0)) throw new IllegalStateException("Unexpected provider reuse");
        long providers=elapsed(start);
        FreshServerInstallations.Active active;
        if(cold) {
            if(ServerInstallationSetup.completedOrNull(context,root,server,programs,content)!=null)
                throw new IllegalStateException("Fresh installed package already has active DB");
            try(ServerInstallationSetup.Handle setup=ServerInstallationSetup.beginFresh(
                    context,root,server,programs,content,data,4L<<30)) {
                Path socket=root.resolve("db").resolve(setup.slotId()).resolve("state/run/bootstrap.sock");
                System.out.println("ANDROID_DB_SOCKET_BYTES "+socket.toString().getBytes(StandardCharsets.UTF_8).length);
                setup.prepare(progress,RuntimeWork.NEVER_CANCELLED);
                setup.finishPlayerbots(progress,RuntimeWork.NEVER_CANCELLED);
                active=setup.stopAndPromote(Duration.ofSeconds(30));
            }
        } else {
            active=ServerInstallationSetup.completed(context,root,server,programs,content);
        }
        long prepared=elapsed(start);
        System.out.println("ANDROID_DB_PHASE promoted-slot-selected "+prepared);
        ServerDatabaseService.Handle database=ServerDatabaseService.startActive(context,root,server,active);
        long ready;
        try {
            ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),new AtomicBoolean(false));
            ready=elapsed(start);
            if(!active.mysqlUuid.equals(database.instanceUuid())) throw new IllegalStateException("Owned SQL service identity differs");
        } finally {
            database.stop(Duration.ofSeconds(30));
        }
        if(database.isAlive() || database.exitCode()!=0) throw new IllegalStateException("SQL service did not close cleanly");
        return new JSONObject().put("mode",cold?"cold":"warm").put("instanceUuid",active.mysqlUuid)
            .put("slotId",active.slotId).put("promotionProof",active.proofSha256).put("setupReceipt",active.setupReceiptSha256)
            .put("providerGeneration",runtime.generation).put("programsGeneration",executables.generation)
            .put("contentGeneration",sql.generation).put("providerCopiedBytes",copied)
            .put("version",server.expectedMysqlVersion()).put("providerMs",providers)
            .put("schemaSetupOrSelectionMs",prepared-providers).put("activeNativeStartupMs",ready-prepared)
            .put("cleanShutdownMs",elapsed(start)-ready).put("sameAuthenticatedInstance",true).put("closed",true);
    }

    public static void main(String[] args) throws Exception {
        if(args.length!=1 || !(args[0].equals("cold") || args[0].equals("warm"))) throw new IllegalArgumentException();
        if(Looper.myLooper()==null) Looper.prepareMainLooper();
        Class<?> thread=Class.forName("android.app.ActivityThread");
        Object instance=thread.getMethod("systemMain").invoke(null);
        Context system=(Context)thread.getMethod("getSystemContext").invoke(instance);
        Context pkg=system.createPackageContext("io.github.russianranger.esteria.stock",0);
        if(android.os.Process.myUid()!=pkg.getApplicationInfo().uid) throw new IllegalStateException("Installed package UID required");
        Context context=new ContextWrapper(pkg) {
            @Override public Context getApplicationContext() {return this;}
        };
        System.load(pkg.getApplicationInfo().nativeLibraryDir+"/libesteria_process.so");
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        FutureTask<JSONObject> operation=new FutureTask<>(()->run(context,root,args[0].equals("cold")));
        new Thread(operation,"qa-signed-slot-owner").start();
        try {System.out.println("ANDROID_DB_RESULT "+operation.get());}
        catch(java.util.concurrent.ExecutionException failure) {
            System.err.println("ANDROID_DB_EXCEPTION "+failure.getCause().getClass().getName());
            throw failure;
        }
    }
}
