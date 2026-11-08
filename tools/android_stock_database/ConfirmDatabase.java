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
import java.util.Collections;
import java.util.Map;
import java.util.TreeMap;
import java.security.SecureRandom;
import io.github.russianranger.esteria.core.presentation.X11SessionPlan;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
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

    private static Map<String,String> signedClientEnvironment() throws IOException {
        try {
            String profile=(String)Class.forName("io.github.russianranger.esteria.BuildConfig").getField("CONTENT_PROFILE").get(null);
            if(!"stock-3.3.5a".equals(profile)) throw new IOException("Signed stock profile required");
            java.lang.reflect.Method select=ClientPresentationSession.class.getDeclaredMethod("clientEnvironment",
                    Map.class,Map.class,String.class,boolean.class);
            select.setAccessible(true);
            // Grunt has no imported graphical view. The production X11 plan and selected APK
            // profile own its loader and synchronization settings.
            Object result=select.invoke(null,X11SessionPlan.environment(77),Collections.emptyMap(),profile,true);
            if(!(result instanceof Map)) throw new IOException("Missing installed client environment");
            Map<String,String> selected=new TreeMap<>();
            for(Map.Entry<?,?> e:((Map<?,?>)result).entrySet()) {
                if(!(e.getKey() instanceof String) || !(e.getValue() instanceof String))
                    throw new IOException("Unexpected installed client environment");
                selected.put((String)e.getKey(),(String)e.getValue());
            }
            return selected;
        } catch(ReflectiveOperationException e) { throw new IOException("Installed stock client environment selection failed",e); }
    }

    /** Evaluate the installed v17 classifier. The v16 seed has no corresponding production class. */
    private static String installedPrefixState(Path work,RuntimeSetup wine) throws Exception {
        Class<?> type=Class.forName("io.github.russianranger.esteria.core.runtime.StockWinePrefix");
        Object result=type.getMethod("inspect",Path.class,Path.class,String.class)
                .invoke(null,work,wine.current(),wine.archiveSha256());
        Object status=type.getMethod("status").invoke(result);
        if(!(status instanceof Enum<?>)) throw new IOException("Unrecognized installed Wine classification");
        String value=((Enum<?>)status).name();
        if(!Arrays.asList("ABSENT","NO_REPAIR","INCOMPLETE","RESUME","UNRECOGNIZED").contains(value))
            throw new IOException("Unexpected installed Wine prefix state");
        return value;
    }

    private static Path newWineOwner(Path root) throws IOException {
        Path sessions=Files.createDirectories(root.resolve("s"));
        return Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","").substring(0,16)));
    }

    /** Passive observation from the installed application's UID. Keep only lengths and reviewed path shapes. */
    private static final class WineSocketWitness {
        final Path temp;
        final String shape;
        final String mode;
        int candidateBytes=-1, configuredBytes=-1, socketBytes=-1, mappedSocketBytes=-1;
        boolean observedTemp;
        WineSocketWitness(Path root,Path owner,String leaf,String mode) {
            this.temp=owner.resolve(leaf).resolve("tmp");
            this.mode=mode;
            String parent=root.toString();
            this.shape=parent+"/s/<16hex>/"+leaf+"/tmp";
        }
        void report() {
            System.out.println("ANDROID_WINE_SOCKET "+mode+" "+shape+" "+observedTemp+" "
                    +configuredBytes+" "+candidateBytes+" "+socketBytes+" "+mappedSocketBytes);
        }
        void sample() throws IOException {
            if((socketBytes>=0 && mappedSocketBytes>=0) || !Files.isDirectory(temp,java.nio.file.LinkOption.NOFOLLOW_LINKS)) return;
            if(!observedTemp) {
                if(!temp.toRealPath().equals(temp)) throw new IOException("Unexpected indirect Wine temp parent");
                configuredBytes=temp.toString().getBytes(StandardCharsets.UTF_8).length;
                observedTemp=true;report();
            }
            // PRoot binds overlong logical sockets to a generated path in its own private
            // temp dir. Other PRoot files share the shape: require the actual kernel inode type.
            if(mappedSocketBytes<0) {
                try(java.nio.file.DirectoryStream<Path> mapped=Files.newDirectoryStream(temp,"proot-*")) {
                    for(Path endpoint:mapped) {
                        if(!endpoint.getFileName().toString().matches("proot-[0-9]+-[a-zA-Z0-9]{6}")) continue;
                        try {
                            if(android.system.OsConstants.S_ISSOCK(android.system.Os.lstat(endpoint.toString()).st_mode)) {
                                mappedSocketBytes=endpoint.toString().getBytes(StandardCharsets.UTF_8).length;
                                report();break;
                            }
                        } catch(android.system.ErrnoException e) {
                            if(e.errno!=android.system.OsConstants.ENOENT) throw new IOException("PRoot socket inspection failed",e);
                        }
                    }
                }
            }
            if(socketBytes>=0) return;
            try(java.nio.file.DirectoryStream<Path> users=Files.newDirectoryStream(temp,".wine-*")) {
                for(Path user:users) {
                    if(!user.getFileName().toString().matches("[.]wine-[0-9]+") ||
                       !Files.isDirectory(user,java.nio.file.LinkOption.NOFOLLOW_LINKS)) continue;
                    try(java.nio.file.DirectoryStream<Path> servers=Files.newDirectoryStream(user,"server-*")) {
                        for(Path dir:servers) {
                            if(!dir.getFileName().toString().matches("server-[0-9a-f]+-[0-9a-f]+") ||
                               !Files.isDirectory(dir,java.nio.file.LinkOption.NOFOLLOW_LINKS)) continue;
                            Path socket=dir.resolve("socket");
                            int length=socket.toString().getBytes(StandardCharsets.UTF_8).length;
                            if(length!=candidateBytes) {candidateBytes=length;report();}
                            try {
                                if(android.system.OsConstants.S_ISSOCK(android.system.Os.lstat(socket.toString()).st_mode)) {
                                    socketBytes=length;report();return;
                                }
                            } catch(android.system.ErrnoException e) {
                                if(e.errno!=android.system.OsConstants.ENOENT) throw new IOException("Wine endpoint inspection failed",e);
                            }
                        }
                    } catch(java.nio.file.NoSuchFileException disappearing) { /* Wine closed the parent between reads. */ }
                }
            }
        }
    }

    private static OwnedProcess wineGuest(Context context,Path owner,Path work,RuntimeSetup wine,String mode) throws IOException {
        Path processSession=Files.createDirectory(owner.resolve("client"));
        Path endpoints=Files.createDirectory(owner.resolve("io"));
        Path x11=Files.createDirectory(owner.resolve("x11"));
        byte[] cookie=new byte[16];
        new SecureRandom().nextBytes(cookie);
        Files.write(endpoints.resolve("Xauthority"),X11SessionPlan.authority(77,cookie),java.nio.file.StandardOpenOption.CREATE_NEW,java.nio.file.StandardOpenOption.WRITE);
        return ProotProcess.startPresentation(context,wine.installer(),wine.packagePlan(),work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/grunt_wine.py",mode),
                wine.wineEnvironment(signedClientEnvironment()),Collections.emptyList(),
                new ProotLaunch.PresentationBindings(endpoints,x11));
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
            for (String source:Arrays.asList("grunt_wine.py","wine_prefix.py","wine_windows.py"))
                Files.copy(Paths.get("/esteria-qa/input/"+source),work.resolve(source));
        }
        for (String name:Arrays.asList("bin/WowClient64.exe","bin/XvidDecoder.dll")) {
            if (cold) Files.copy(clientFiles.rootfs.resolve(name),work.resolve(name));
            verifyFile(work.resolve(name),client.packagePlan().required.get(name));
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
            Path wineOwner=newWineOwner(root);
            WineSocketWitness witness=new WineSocketWitness(root,wineOwner,"client",mode);
            OwnedProcess child=ServerDatabaseService.installedRuntime(context,server).launch(work,processSession,
                Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/qa-auth-"+mode+"/auth_phase.py",generation,
                    mode,operation,version,uuid,active.setupReceiptSha256,pin.sha256,Long.toString(pin.bytes),world.sha256,Long.toString(world.bytes)),
                Arrays.asList(new ProotLaunch.Mount(programs.current(),ServerProgramsSetup.guestMount()),
                        new ProotLaunch.Mount(root.resolve("qa-server-data-directory"),"/esteria-data"),
                        new ProotLaunch.Mount(root.resolve("state/client-work"),"/esteria-client")));
            OwnedProcess grunt=null;
            try {
                grunt=wineGuest(context,wineOwner,root.resolve("state/client-work"),wine,mode);
                long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(cold ? 20 : 6);
                while((child.isAlive() || grunt.isAlive()) && System.nanoTime()<deadline) {
                    witness.sample();
                    if(!child.isAlive()) requireExit(child);
                    if(!grunt.isAlive()) requireExit(grunt);
                    pause();
                }
                witness.sample();
                witness.report();
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

    private static String hashSmall(Path path) throws Exception {
        if(!path.equals(path.toRealPath()) || !Files.isRegularFile(path) || Files.size(path)>(2L<<20))
            throw new IOException("Invalid private update fixture");
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
        StringBuilder result=new StringBuilder();
        for(byte b:hash) result.append(String.format(java.util.Locale.ROOT,"%02x",b & 255));
        return result.toString();
    }

    private static void checkRetainedOperatorFiles(Path root,Path state,boolean seed) throws Exception {
        Path marker=root.resolve("qa-pm-marker");
        Path proof=root.resolve("qa-pm-private-state.json");
        if(seed) {
            byte[] value=new byte[32];
            new SecureRandom().nextBytes(value);
            Files.write(marker,value,java.nio.file.StandardOpenOption.CREATE_NEW,java.nio.file.StandardOpenOption.WRITE);
        }
        JSONObject setup=new JSONObject(new String(Files.readAllBytes(state.resolve("server-setup-complete.json")),StandardCharsets.UTF_8));
        String generation=setup.getString("configGeneration");
        if(!generation.matches("[a-f0-9]{64}")) throw new IOException("Invalid retained config identity");
        Map<String,String> actual=new TreeMap<>();
        actual.put("marker",hashSmall(marker));
        for(String path:Arrays.asList("accounts/local-player.json","config/generations/"+generation+"/authserver.conf",
                    "config/generations/"+generation+"/worldserver.conf"))
            actual.put(path,hashSmall(state.resolve(path)));
        if(seed) {
            Files.write(proof,new JSONObject(actual).toString().getBytes(StandardCharsets.UTF_8),
                    java.nio.file.StandardOpenOption.CREATE_NEW,java.nio.file.StandardOpenOption.WRITE);
        } else {
            JSONObject saved=new JSONObject(new String(Files.readAllBytes(proof),StandardCharsets.UTF_8));
            if(saved.length()!=actual.size()) throw new IOException("Private retention markers changed");
            for(Map.Entry<String,String> item:actual.entrySet())
                if(!item.getValue().equals(saved.getString(item.getKey()))) throw new IOException("Retained configuration/intent changed");
        }
    }

    private static JSONObject run(Context context, Path root, String mode) throws Exception {
        boolean seed=mode.equals("seed16"),cold=mode.equals("cold");
        android.content.pm.PackageInfo installed=context.getPackageManager().getPackageInfo(context.getPackageName(),0);
        if(installed.getLongVersionCode()!=(seed?16:17)) throw new IOException("Unexpected installed app version");
        Path data=root.resolve("qa-server-data-directory");
        if(seed) Files.createDirectory(data);
        if(!Files.isDirectory(data) || !data.equals(data.toRealPath()))
            throw new IllegalStateException("Disjoint QA schema config directory required");
        RuntimeSetup wine=new RuntimeSetup(context,root);
        Path clientWork=root.resolve("state/client-work");
        if(!seed) prepareClient(context,root,clientWork,wine,cold);
        String prefixBefore=seed?"unobserved-v16-seed":installedPrefixState(clientWork,wine);
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
        if(seed ? (runtime.alreadyInstalled || executables.alreadyInstalled || sql.alreadyInstalled || copied<=0) :
            (!runtime.alreadyInstalled || !executables.alreadyInstalled || !sql.alreadyInstalled || copied!=0)) throw new IllegalStateException("Unexpected provider reuse");
        long providers=elapsed(start);
        FreshServerInstallations.Active active;
        if(seed) {
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
        String authReport;
        long authenticated;
        try {
            ServerDatabaseService.awaitReady(database,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),new AtomicBoolean(false));
            ready=elapsed(start);
            if(!active.mysqlUuid.equals(database.instanceUuid())) throw new IllegalStateException("Owned SQL service identity differs");
            authReport=seed ? "{}" : auth(context,root,server,programs,active,database,wine,cold);
            authenticated=elapsed(start);
        } finally {
            database.stop(Duration.ofSeconds(30));
        }
        if(database.isAlive() || database.exitCode()!=0) throw new IllegalStateException("SQL service did not close cleanly");
        String prefixAfter=seed?"unobserved-v16-seed":installedPrefixState(clientWork,wine);
        checkRetainedOperatorFiles(root,active.directoryFor(root).resolve("state"),seed);
        return new JSONObject().put("mode",mode).put("appUid",android.os.Process.myUid())
            .put("firstInstallTime",installed.firstInstallTime).put("versionCode",installed.getLongVersionCode())
            .put("stockPrefixBefore",prefixBefore).put("stockPrefixAfter",prefixAfter)
            .put("markerConfigAccountPersisted",!seed).put("instanceUuid",active.mysqlUuid)
            .put("slotId",active.slotId).put("promotionProof",active.proofSha256).put("setupReceipt",active.setupReceiptSha256)
            .put("providerGeneration",runtime.generation).put("programsGeneration",executables.generation)
            .put("contentGeneration",sql.generation).put("providerCopiedBytes",copied)
            .put("version",server.expectedMysqlVersion()).put("providerMs",providers)
            .put("schemaSetupOrSelectionMs",prepared-providers).put("activeNativeStartupMs",ready-prepared)
            .put("reconstructedClientSha256",PE).put("sourceRevision",SOURCE).put("wineArchive",wine.archiveSha256())
            .put("auth",new JSONObject(authReport)).put("cleanShutdownMs",elapsed(start)-authenticated).put("sameAuthenticatedInstance",true).put("closed",true);
    }

    public static void main(String[] args) throws Exception {
        if(args.length!=1 || !(args[0].equals("cold") || args[0].equals("warm") || args[0].equals("seed16"))) throw new IllegalArgumentException();
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
