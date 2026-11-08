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
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HashSet;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.json.JSONObject;

/** Disposable fresh installed package. All SQL, native processes, receipts and leases belong to the signed APK. */
public final class ConfirmDatabase {
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
        Path processSession=Files.createDirectory(root.resolve("qa-wine-process-"+mode));
        return ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/grunt_wine.py",mode),
                wine.wineEnvironment(),null);
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
            Files.createDirectory(work);
            Files.createDirectory(work.resolve("bin"));
            Files.copy(Paths.get("/esteria-qa/input/grunt_wine.py"),work.resolve("grunt_wine.py"));
        }
        for (String name:Arrays.asList("bin/WowClient64.exe","bin/XvidDecoder.dll")) {
            if (cold) Files.copy(clientFiles.rootfs.resolve(name),work.resolve(name));
            verifyFile(work.resolve(name),client.packagePlan().required.get(name));
        }
        if(cold) {
            OwnedProcess bootstrap=wineGuest(context,root,work,wine,"bootstrap");
            try {
                long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(11);
                while(bootstrap.isAlive() && System.nanoTime()<deadline) pause();
                requireExit(bootstrap);
                if(!Files.isRegularFile(work.resolve("bootstrap/exited"))) throw new IOException("Wine prefix not proven");
            } finally {
                if(bootstrap.isAlive()) bootstrap.stop(Duration.ofSeconds(15));
            }
        }
    }

    private static String auth(Context context,Path root,ServerRuntimeSetup server,ServerProgramsSetup programs,
            FreshServerInstallations.Active active,ServerDatabaseService.Handle database,RuntimeSetup wine,boolean cold) throws IOException {
        Path work=active.directoryFor(root);
        String mode=cold?"cold":"warm";
        String generation=GuestHelperAssets.install(context,"server-session",GuestHelperAssets.directory(work,"qa-auth-helpers"),LocalServerSession.HELPERS);
        Path observer=Files.createDirectory(work.resolve("qa-auth-"+mode));
        for(String source:Arrays.asList("auth_phase.py","client_auth_contract.py","prepare_runtime.py","world_probe.py","stock_world_observation.py"))
            Files.copy(new java.io.File("/esteria-qa/input/"+source).toPath(),observer.resolve(source));
        Path processSession=Files.createDirectory(root.resolve("qa-auth-process-"+mode));
        RuntimePackagePlan.RequiredFile pin=programs.packagePlan().required.get("bin/authserver");
        RuntimePackagePlan.RequiredFile world=programs.packagePlan().required.get("bin/worldserver");
        if(pin==null || pin.elfMachine!=183 || world==null || world.elfMachine!=183) throw new IOException("Selected packaged ARM64 authserver required");
        return database.withReadyLease(server.current(),(operation,version,uuid)->{
            OwnedProcess child=ServerDatabaseService.installedRuntime(context,server).launch(work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/qa-auth-"+mode+"/auth_phase.py",generation,
                    mode,operation,version,uuid,active.setupReceiptSha256,pin.sha256,Long.toString(pin.bytes),world.sha256,Long.toString(world.bytes)),
                Arrays.asList(new ProotLaunch.Mount(programs.current(),ServerProgramsSetup.guestMount()),
                        new ProotLaunch.Mount(root.resolve("qa-server-data-directory"),"/esteria-data")));
            OwnedProcess grunt=null;
            try {
                grunt=wineGuest(context,root,work.resolve("qa-grunt"),wine,mode);
                long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(6);
                while((child.isAlive() || grunt.isAlive()) && System.nanoTime()<deadline) {
                    if(!child.isAlive()) requireExit(child);
                    if(!grunt.isAlive()) requireExit(grunt);
                    pause();
                }
                requireExit(child);
                requireExit(grunt);
                Path result=observer.resolve("verified.json");
                if(Files.size(result)>4096) throw new IOException("Unexpected auth observation size");
                return new String(Files.readAllBytes(result),StandardCharsets.UTF_8);
            } finally {
                try { if(grunt!=null && grunt.isAlive()) grunt.stop(Duration.ofSeconds(15)); }
                finally { if(child.isAlive()) child.stop(Duration.ofSeconds(15)); }
            }
        });
    }

    private static JSONObject run(Context context, Path root, boolean cold) throws Exception {
        Path data=root.resolve("qa-server-data-directory");
        if(cold) Files.createDirectory(data);
        if(!Files.isDirectory(data) || !data.equals(data.toRealPath()))
            throw new IllegalStateException("Disjoint QA schema config directory required");
        RuntimeSetup wine=new RuntimeSetup(context,root);
        if(cold) prepareClient(context,root,root.resolve("qa-grunt"),wine,true);
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
        Path peer=active.directoryFor(root).resolve("qa-grunt");
        if(cold) Files.move(root.resolve("qa-grunt"),peer,StandardCopyOption.ATOMIC_MOVE);
        else prepareClient(context,root,peer,wine,false);
        long prepared=elapsed(start);
        System.out.println("ANDROID_DB_PHASE promoted-slot-selected "+prepared);
        ServerDatabaseService.Handle database=ServerDatabaseService.startActive(context,root,server,active);
        long ready;
        String authReport;
        long authenticated;
        try {
            ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),new AtomicBoolean(false));
            ready=elapsed(start);
            if(!active.mysqlUuid.equals(database.instanceUuid())) throw new IllegalStateException("Owned SQL service identity differs");
            authReport=auth(context,root,server,programs,active,database,wine,cold);
            authenticated=elapsed(start);
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
            .put("reconstructedClientSha256",PE).put("sourceRevision",SOURCE).put("wineArchive",wine.archiveSha256())
            .put("auth",new JSONObject(authReport)).put("cleanShutdownMs",elapsed(start)-authenticated).put("sameAuthenticatedInstance",true).put("closed",true);
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
