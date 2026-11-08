package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;

import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.util.Arrays;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.UUID;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HashSet;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Disposable fresh installed package. All SQL, native processes, receipts and leases belong to the signed APK. */
public final class ConfirmLegacy {
    private static long elapsed(long start) { return (System.nanoTime()-start)/1_000_000; }

    private static final String SOURCE = "fa3e74b7f332fef0f212e954a0de18f685ead8bd";
    private static final String PE = "fa19dd59c49dc68eda4f81d0aa52b633b9b21fb4d986d34a8285604260936317";

    private static void verifyFile(Path path, RuntimePackagePlan.RequiredFile expected) throws IOException {
        if (!path.equals(path.toRealPath()) || Files.size(path) != expected.bytes || expected.peMachine != 0xaa64)
            throw new IOException("Selected ARM64 PE file differs");
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try (java.io.InputStream in=Files.newInputStream(path)) {
                byte[] block=new byte[65536];
                for (int n; (n=in.read(block))!=-1;) digest.update(block,0,n);
            }
            StringBuilder hash=new StringBuilder();
            for(byte b:digest.digest()) hash.append(String.format(java.util.Locale.ROOT,"%02x",b & 255));
            if (!hash.toString().equals(expected.sha256)) throw new IOException("ARM64 PE digest differs");
        } catch(NoSuchAlgorithmException error) { throw new IOException(error); }
    }

    private static OwnedProcess wineGuest(Context context,Path root,Path work,RuntimeSetup wine,String mode) throws IOException {
        Path sessions=Files.createDirectories(root.resolve("s"),java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")));
        Path owner=Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","").substring(0,16)));
        Path processSession=Files.createDirectory(owner.resolve("client"));
        return ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/grunt_wine.py",mode),
                wine.wineEnvironment(io.github.russianranger.esteria.core.presentation.X11SessionPlan.environment(77)),null);
    }

    private static void pause() throws IOException {
        try { Thread.sleep(100); }
        catch(InterruptedException e) { Thread.currentThread().interrupt(); throw new IOException("Grunt observation interrupted",e); }
    }

    private static void requireExit(OwnedProcess child) throws IOException {
        if(child.isAlive() || child.exitCode()!=0 || child.wasForced() || child.failure()!=null)
            throw new IOException("Signed Android child failed or exceeded its phase budget");
    }

    private static void prepareClient(Context context, Path root, Path work, RuntimeSetup wine, boolean cold) throws IOException {
        ClientRuntimeSetup client=new ClientRuntimeSetup(context,root);
        client.requireWineArchive(wine.archiveSha256());
        if(!SOURCE.equals(client.sourceRevision()) || !PE.equals(client.packagePlan().required.get("bin/WowClient64.exe").sha256))
            throw new IOException("Unexpected signed client source");
        RuntimeInstaller.Result wineFiles=wine.installer().install(Paths.get("/esteria-qa/input/wine.tar.gz"),
                wine.packagePlan(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller.Result clientFiles=client.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        if(cold ? (wineFiles.alreadyInstalled || clientFiles.alreadyInstalled) :
                (!wineFiles.alreadyInstalled || !clientFiles.alreadyInstalled || wineFiles.copiedBytes+clientFiles.copiedBytes!=0))
            throw new IOException("Unexpected Wine or reconstructed client admission");
        if(cold) {
            Files.createDirectories(work.getParent());
            Files.createDirectory(work,java.nio.file.attribute.PosixFilePermissions.asFileAttribute(java.nio.file.attribute.PosixFilePermissions.fromString("rwx------")));
            Files.createDirectory(work.resolve("bin"));
            for (String source:Arrays.asList("grunt_wine.py","fingerprint.py","safe_registry.py","wine_prefix.py","wine_windows.py","prefix_helper_observer.py"))
                Files.copy(Paths.get("/esteria-qa/input/"+source),work.resolve(source));
        }
        for (String name:Arrays.asList("bin/WowClient64.exe","bin/XvidDecoder.dll")) {
            if (cold) Files.copy(clientFiles.rootfs.resolve(name),work.resolve(name));
            verifyFile(work.resolve(name),client.packagePlan().required.get(name));
        }

    }


    private static JSONObject run(Context context,Path root,String mode) throws Exception {
        if(!mode.equals("interrupt"))throw new IllegalArgumentException();
        RuntimeSetup wine=new RuntimeSetup(context,root);
        Path work=root.resolve("qa-original/state/client-work");
        prepareClient(context,root,work,wine,true);
        GuestBridgeSetup bridges=new GuestBridgeSetup(context,root);
        bridges.requireWineArchive(wine.archiveSha256());bridges.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        OwnedProcess child=wineGuest(context,root,work,wine,mode);
        try{long end=System.nanoTime()+TimeUnit.MINUTES.toNanos(3);
            while(child.isAlive()&&System.nanoTime()<end)pause();
            requireExit(child);
        }finally{if(child.isAlive())child.stop(Duration.ofSeconds(15));}
        return new JSONObject().put("control",mode).put("versionCode",16).put("ownerClosed",true)
              .put("wineArchive",wine.archiveSha256()).put("verifiedPE",PE);
    }
    public static void main(String[] args) throws Exception {
        if(args.length!=1 || !Arrays.asList("reference","interrupt","reentry","clone","cancel","update","finish","noop","audit","warm","unknown").contains(args[0])) throw new IllegalArgumentException();
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
        FutureTask<JSONObject> operation=new FutureTask<>(()->run(context,root,args[0]));
        new Thread(operation,"qa-signed-slot-owner").start();
        try {System.out.println("ANDROID_DB_RESULT "+operation.get());}
        catch(java.util.concurrent.ExecutionException failure) {
            System.err.println("ANDROID_DB_EXCEPTION "+failure.getCause().getClass().getName());
            throw failure;
        }
    }
}
