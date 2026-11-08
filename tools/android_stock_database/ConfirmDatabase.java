package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.StockWinePrefix;
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
        Path sessions=Files.createDirectories(root.resolve("s"));
        Path owner=Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","").substring(0,16)));
        Path processSession=Files.createDirectory(owner.resolve("client"));
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
            Files.createDirectories(work.getParent());
            Files.createDirectory(work);
            Files.createDirectory(work.resolve("bin"));
            for (String source:Arrays.asList("grunt_wine.py","fingerprint.py","safe_registry.py","wine_prefix.py","wine_windows.py","prefix_helper_observer.py"))
                Files.copy(Paths.get("/esteria-qa/input/"+source),work.resolve(source));
        }
        for (String name:Arrays.asList("bin/WowClient64.exe","bin/XvidDecoder.dll")) {
            if (cold) Files.copy(clientFiles.rootfs.resolve(name),work.resolve(name));
            verifyFile(work.resolve(name),client.packagePlan().required.get(name));
        }

    }

    private static void installTools(Path work,Path source) throws IOException {
        Files.createDirectories(work.resolve("bin"));
        for(String name:Arrays.asList("grunt_wine.py","fingerprint.py","safe_registry.py","wine_prefix.py","wine_windows.py","prefix_helper_observer.py","bin/WowClient64.exe","bin/XvidDecoder.dll"))
            Files.copy(source.resolve(name),work.resolve(name));
    }
    private static boolean runningWineboot() {
        java.io.File[] list=new java.io.File("/proc").listFiles();
        if(list==null)return false;
        for(java.io.File item:list){
            if(!item.getName().matches("[0-9]+"))continue;
            try(java.io.InputStream in=Files.newInputStream(item.toPath().resolve("cmdline"))){
                byte[] data=new byte[500];int read=in.read(data);if(read<=0)continue;
                String a=new String(data,0,read,StandardCharsets.ISO_8859_1).toLowerCase(java.util.Locale.ROOT);
                int zero=a.indexOf('\0');String first=zero<0?a:a.substring(0,zero);
                if(first.contains("wineboot.exe") && !first.contains("/bin/sh"))return true;
            }catch(IOException|SecurityException ignored){ }
        }
        return false;
    }
    private static final class VerifyCut extends RuntimeException { }
    private static JSONObject run(Context context,Path root,String mode) throws Exception {
        RuntimeSetup wine=new RuntimeSetup(context,root);
        Path canonical=root.resolve("state/client-work"),original=root.resolve("qa-original/state/client-work");
        boolean initial=mode.equals("reference")||mode.equals("interrupt");
        Path work=mode.equals("interrupt")||mode.equals("reentry")?original:canonical;
        if(mode.equals("clone"))installTools(work,original);
        prepareClient(context,root,work,wine,initial);
        if(initial){GuestBridgeSetup bridges=new GuestBridgeSetup(context,root);bridges.requireWineArchive(wine.archiveSha256());bridges.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);}
        Path runtime=wine.current();
        JSONObject result=new JSONObject().put("control",mode).put("wineArchive",wine.archiveSha256()).put("clientRevision",SOURCE).put("verifiedPE",PE);
        StockWinePrefix before=StockWinePrefix.inspect(work,runtime,wine.archiveSha256());
        result.put("before",before.status().toString());
        result.put("changedSource",StockWinePrefix.inspect(work,runtime,"0000000000000000000000000000000000000000000000000000000000000000").status().toString());
        Path foreign=Files.createDirectories(root.resolve("qa-negative/home/.wine/drive_c/windows/system32"));
        result.put("foreign",StockWinePrefix.inspect(root.resolve("qa-negative"),runtime,wine.archiveSha256()).status().toString());
        if(mode.equals("unknown")){
            Path retained=root.resolve("qa-observer-healthy-prefix"),source=work.resolve("home/.wine");
            Files.move(source,retained,java.nio.file.StandardCopyOption.ATOMIC_MOVE);
            try{
                Files.createDirectory(source);
                Path marker=source.resolve("unrelated-existing-owner");
                byte[] prior="unrelated-private-qa-prefix".getBytes(StandardCharsets.US_ASCII);
                Files.write(marker,prior,java.nio.file.StandardOpenOption.CREATE_NEW);
                java.nio.file.attribute.FileTime stamp=Files.getLastModifiedTime(marker); long inode=((Number)Files.getAttribute(marker,"unix:ino")).longValue();
                java.util.List<String> phases=new java.util.ArrayList<>();
                boolean did=StockWinePrefixRepair.runIfRequired(context,root,(phase,path,done,total)->phases.add(phase),RuntimeWork.NEVER_CANCELLED);
                result.put("handlerReturn",did).put("phases",new org.json.JSONArray(phases));
                result.put("preservedUnknownMarker",Files.getLastModifiedTime(marker).equals(stamp) && inode==((Number)Files.getAttribute(marker,"unix:ino")).longValue() && java.util.Arrays.equals(prior,Files.readAllBytes(marker)));
                try(java.util.stream.Stream<Path> siblings=Files.list(source)){result.put("unknownFileCount",siblings.count());}
                result.put("unknownPending",Files.exists(work.resolve(".stock-wine-prefix-repair-v1.pending")));
                Files.delete(marker);
                Files.delete(source);
            }finally{
                if(Files.notExists(source))Files.move(retained,source,java.nio.file.StandardCopyOption.ATOMIC_MOVE);
            }
        }else if(Arrays.asList("cancel","update","finish","noop").contains(mode)){
            final long[] registered={0};final boolean[] live={false},busy={false};
            java.util.List<String> phases=new java.util.ArrayList<>();
            try{
                boolean did=StockWinePrefixRepair.runIfRequired(context,root,(phase,path,done,total)->{
                    if(!phases.contains(phase))phases.add(phase);
                    if(phase.equals("client-prefix-wineboot")){
                        registered[0]=System.nanoTime();
                        try(ClientLaunchSetup.Lease unexpected=ClientLaunchSetup.claim(root)){throw new IllegalStateException("Competing prefix owner acquired");}
                        catch(IOException expected){busy[0]=true;}
                    }
                    if(mode.equals("update") && phase.equals("client-prefix-verify"))throw new VerifyCut();
                },()->{
                    if(!mode.equals("cancel")||registered[0]==0)return false;
                    if(System.nanoTime()-registered[0]<300_000_000L)return false;
                    if(runningWineboot())live[0]=true;
                    return live[0];
                });
                result.put("handlerReturn",did);
            }catch(RuntimeWork.CancelledException expected){result.put("nativeCancelled",true);}
            catch(VerifyCut cut){result.put("cutAfterGuestExitBeforePendingRetired",true);}
            catch(IOException failure){
                // All strings in these internally-invoked paths originate in static production handlers. Never export arbitrary native output.
                String message=String.valueOf(failure.getMessage());
                result.put("ioFailure",failure.getClass().getSimpleName());
                for(String token:Arrays.asList("supported interrupted","prefix repair","timed out","presentation","Wine update","client-work lease","changed"))
                    if(message.contains(token))result.accumulate("errorKinds",token);
                java.util.List<String> stack=new java.util.ArrayList<>();
                for(StackTraceElement frame:failure.getStackTrace())if(frame.getClassName().startsWith("io.github.russianranger.esteria"))stack.add(frame.getClassName()+":"+frame.getLineNumber());
                result.put("errorStack",new org.json.JSONArray(stack));
            }
            result.put("phases",new org.json.JSONArray(phases)).put("liveWinebootBeforeCancel",live[0]).put("competingLeaseDenied",busy[0]);
            StockWinePrefixRepair.retryPendingCleanup(root);
        }else{
            OwnedProcess child;
            if(mode.equals("clone") || mode.equals("audit")){
                Path sessions=Files.createDirectories(root.resolve("s"));Path owner=Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","").substring(0,16)));
                child=ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,Files.createDirectory(owner.resolve("client")),
                    Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/prefix_helper_observer.py",mode),wine.wineEnvironment(),
                    Arrays.asList(new ProotLaunch.Mount(original,"/qa-prefix-original")),null);
            }else child=wineGuest(context,root,work,wine,mode);
            try{long end=System.nanoTime()+TimeUnit.MINUTES.toNanos(6);while(child.isAlive()&&System.nanoTime()<end)pause();requireExit(child);}
            finally{if(child.isAlive())child.stop(Duration.ofSeconds(15));}
        }
        result.put("after",StockWinePrefix.inspect(work,runtime,wine.archiveSha256()).status().toString());
        result.put("candidateGateDetails",ConfirmPrefixTrace.inspect(work,runtime,wine.archiveSha256()));
        Path pending=work.resolve(".stock-wine-prefix-repair-v1.pending");
        result.put("pending",Files.isRegularFile(pending)).put("ownerClosed",true);
        Path q=work.resolve("qa-original-check.json");
        if(Files.isRegularFile(q))result.put("copy",new JSONObject(new String(Files.readAllBytes(q),StandardCharsets.UTF_8)));
        return result;
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
