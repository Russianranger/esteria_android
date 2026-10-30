package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.List;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Debug-profile-only, real Android x64 MySQL execution. Never selects a production runtime. */
@RunWith(AndroidJUnit4.class)
public final class MySqlExecutionTest {
    private static byte[] read(InputStream input,int limit)throws IOException {
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
        while((count=input.read(buffer))!=-1){if(bytes.size()+count>limit)throw new IOException("Probe metadata exceeds bound");bytes.write(buffer,0,count);}
        return bytes.toByteArray();
    }
    private static byte[] asset(Context context,String name,int limit)throws IOException {
        try(InputStream input=context.getAssets().open(name)){return read(input,limit);}
    }
    private static String hash(byte[] bytes)throws Exception {
        StringBuilder value=new StringBuilder();for(byte item:MessageDigest.getInstance("SHA-256").digest(bytes))value.append(String.format(java.util.Locale.ROOT,"%02x",item&255));return value.toString();
    }
    private static String fileHash(Path path)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] buffer=new byte[65536];
        try(InputStream input=Files.newInputStream(path)){int count;while((count=input.read(buffer))!=-1)digest.update(buffer,0,count);}
        StringBuilder value=new StringBuilder();for(byte item:digest.digest())value.append(String.format(java.util.Locale.ROOT,"%02x",item&255));return value.toString();
    }
    private static Path directory(Path path)throws IOException {
        Files.createDirectory(path,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));return path;
    }
    private static void copy(Path target,byte[] bytes)throws IOException {
        Files.write(target,bytes,StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rw-------"));
    }
    private static JSONObject json(Path file)throws Exception {
        assertTrue(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS));
        try(InputStream input=Files.newInputStream(file)){return new JSONObject(new String(read(input,16384),StandardCharsets.UTF_8));}
    }
    private static RuntimePackagePlan plan(JSONObject proof,byte[] raw)throws Exception {
        assertEquals(1,proof.getInt("formatVersion"));assertEquals("android-13-x86-64-mysql-probe-build-only",proof.getString("scope"));
        assertEquals("x86_64",proof.getString("architecture"));assertEquals("mysql-probe-x86-64",proof.getString("packageKey"));
        for(String name:Arrays.asList("androidMysqlQualified","productionAdapterQualified","arm64Qualified","serverSchemasQualified","gameplayQualified"))assertFalse(proof.getBoolean(name));
        JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits"),required=proof.getJSONObject("requiredFiles");
        assertEquals("mysql-probe/mysql-x86-64.archive",archive.getString("assetPath"));assertEquals("mysql-x86-64.tar.gz",archive.getString("file"));
        Map<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
        for(Iterator<String> names=required.keys();names.hasNext();){String name=names.next();JSONObject pin=required.getJSONObject(name);
            int machine=pin.optInt("elfMachine",0);assertTrue(machine==0||machine==62);
            files.put(name,new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"),pin.getString("sha256"),machine,0));}
        for(String binary:Arrays.asList("usr/bin/python3.12","usr/bin/mysql","usr/sbin/mysqld"))assertEquals(62,files.get(binary).elfMachine);
        return new RuntimePackagePlan("mysql-probe-x86-64",hash(raw),archive.getString("file"),archive.getLong("bytes"),archive.getString("sha256"),
                proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),
                bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes")),files);
    }
    private static InputStream openArchive(Context context,long offset)throws IOException {
        AssetFileDescriptor descriptor=context.getAssets().openFd("mysql-probe/mysql-x86-64.archive");
        InputStream input=null;
        try{input=descriptor.createInputStream();long left=offset;while(left>0){long count=input.skip(left);if(count>0)left-=count;else if(input.read()<0)throw new IOException("Probe archive resume beyond end");else left--;}return input;}
        catch(IOException|RuntimeException error){if(input!=null)input.close();else descriptor.close();throw error;}
    }
    private static void execute(Path nativeRoot,Path rootfs,Path work,Path sessions,String phase,String helper,String[] arguments)throws Exception {
        Path session=directory(sessions.resolve(phase)),temporary=directory(session.resolve("tmp")),logs=directory(session.resolve("logs"));
        Map<String,String> environment=new HashMap<>();environment.put("PROOT_LOADER",nativeRoot.resolve("libproot_probe_loader.so").toString());
        environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
        java.util.List<String> command=new java.util.ArrayList<>(Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),"-b","/dev","-b","/proc",
                "-b",work+":/work","-b",temporary+":/tmp","-w","/work","/usr/bin/env","-i","HOME=/work/home","PATH=/usr/sbin:/usr/bin:/sbin:/bin",
                "TMPDIR=/tmp","LANG=C.UTF-8","/usr/bin/python3","-B","-s","-E","/work/helpers/"+helper));
        command.addAll(Arrays.asList(arguments));
        OwnedProcess child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(nativeRoot.resolve("libproot_probe.so"),command,environment,work,
                logs.resolve("stdout.log"),logs.resolve("stderr.log")),null);
        try {
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(12);
            while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(100);
            assertFalse("Owned MySQL probe deadline",child.isAlive());assertNull(child.failure());
            assertEquals("Actual guest process exit for "+phase,0,child.exitCode());assertFalse(child.wasForced());assertEquals(0,child.diagnostics()[4]);
        } finally {
            try {if(child.isAlive())child.stop(Duration.ZERO);}
            finally {
                Path engine=work.resolve("state/logs");
                if(Files.isDirectory(engine,LinkOption.NOFOLLOW_LINKS))try(java.nio.file.DirectoryStream<Path> files=Files.newDirectoryStream(engine,"*.log")) {
                    int count=0;
                    for(Path file:files) {
                        assertTrue(++count<=16);assertTrue(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS));
                        byte[] bytes;try(InputStream input=Files.newInputStream(file)){bytes=read(input,65536);}
                        String redacted=new String(bytes,StandardCharsets.UTF_8).replaceAll("(?i)[a-f0-9]{64}","[redacted-generated-secret]");
                        copy(logs.resolve("engine-"+file.getFileName()),redacted.getBytes(StandardCharsets.UTF_8));
                    }
                }
            }
        }
    }
    private static void noReadiness(JSONObject report,String operation,String version,String uuid)throws Exception {
        assertEquals(1,report.getInt("formatVersion"));assertEquals("database-prepared-no-readiness-claim",report.getString("scope"));
        assertEquals(operation,report.getString("operation"));assertEquals(version,report.getString("version"));assertEquals(uuid,report.getString("uuid"));
        assertEquals("/work/state/database",report.getString("datadir"));
        for(String flag:Arrays.asList("persistentServiceStarted","liveServiceStateVerified","liveSqlAuthenticated","bootstrapPopulatedApplicationSchemas"))assertFalse(report.getBoolean(flag));
    }
    private static void sqlResult(JSONObject report,String operation,String version,String uuid)throws Exception {
        assertEquals(1,report.getInt("formatVersion"));assertEquals("android-mysql-owned-fixture-sql",report.getString("scope"));
        assertEquals(operation,report.getString("operation"));assertEquals(version,report.getString("version"));assertEquals(uuid,report.getString("uuid"));
        assertEquals("/work/state/database",report.getString("datadir"));
        for(String flag:Arrays.asList("rootSqlAuthenticated","applicationSqlAuthenticated","socketOnly","instanceIdentityVerified","persistentMarkerVerified","credentialsPreserved","cleanShutdown"))assertTrue(report.getBoolean(flag));
        assertEquals(operation.equals("verify"),report.getBoolean("restoredAfterRestart"));
        for(String flag:Arrays.asList("productionAdapterQualified","arm64Qualified","serverSchemasQualified","worldserverQualified","gameplayQualified"))assertFalse(report.getBoolean(flag));
    }
    @Test public void actualMysqlInitializesAuthenticatesAndRestarts()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(BuildConfig.DEBUG);assertTrue(BuildConfig.MYSQL_PROBE_PACKAGED);assertFalse(BuildConfig.PROOT_PACKAGED);assertFalse(BuildConfig.SERVER_RUNTIME_PACKAGED);
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        byte[] raw=asset(context,"mysql-probe/provider.json",65536);JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));RuntimePackagePlan plan=plan(proof,raw);
        Path nativeRoot=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        JSONObject proot=new JSONObject(new String(asset(context,"proot-probe/build-evidence.json",65536),StandardCharsets.UTF_8));
        for(String name:Arrays.asList("libproot_probe.so","libproot_probe_loader.so")) {
            Path file=nativeRoot.resolve(name);JSONObject pin=proot.getJSONObject("nativeFiles").getJSONObject(name);
            assertTrue(Files.isExecutable(file));assertEquals(pin.getLong("bytes"),Files.size(file));assertEquals(pin.getString("sha256"),fileHash(file));
        }
        Path root=directory(context.getFilesDir().toPath().toRealPath().resolve("mysql-probe-session"));
        Path work=directory(root.resolve("work")),sessions=directory(root.resolve("sessions"));
        directory(work.resolve("home"));directory(work.resolve("state"));directory(work.resolve("setup-results"));directory(work.resolve("probe-results"));Path helpers=directory(work.resolve("helpers"));
        assertTrue("Physical socket path must fit Linux UNIX address",work.resolve("state/run/bootstrap.sock").toString().getBytes(StandardCharsets.UTF_8).length<=100);
        copy(work.resolve(".mysql-probe-owner"),(hash(raw)+"\n").getBytes(StandardCharsets.US_ASCII));
        JSONObject helperManifest=new JSONObject(new String(asset(context,"database-setup/manifest.json",16384),StandardCharsets.UTF_8)).getJSONObject("files");
        assertEquals(2,helperManifest.length());JSONObject inputs=proof.getJSONObject("sourceInputs");
        for(String name:Arrays.asList("mysql_bootstrap.py","android_database_setup.py")) {
            byte[] bytes=asset(context,"database-setup/"+name,131072);JSONObject pin=helperManifest.getJSONObject(name);
            assertEquals(pin.getLong("bytes"),bytes.length);assertEquals(pin.getString("sha256"),hash(bytes));
            assertEquals(inputs.getJSONObject("runtime/"+name).getString("sha256"),hash(bytes));copy(helpers.resolve(name),bytes);
        }
        byte[] guest=asset(context,"mysql-probe/guest_check.py",65536);assertEquals(inputs.getJSONObject("runtime/mysql-probe/guest_check.py").getString("sha256"),hash(guest));copy(helpers.resolve("guest_check.py"),guest);
        Path archive=new EmbeddedArchiveCache(root.resolve("cache")).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,
                offset->openArchive(context,offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller installer=new RuntimeInstaller(root.resolve("runtime"));RuntimeInstaller.Result installed=installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        Path rootfs=installer.resolveCurrent(plan);assertNotNull(rootfs);String version=proof.getString("expectedMysqlSqlVersion");
        String first=UUID.randomUUID().toString().replace("-","");execute(nativeRoot,rootfs,work,sessions,"initialize","android_database_setup.py",new String[]{"--expected-version",version,"--operation-id",first});
        JSONObject initialized=json(work.resolve("setup-results/"+first+".json"));String uuid=initialized.getString("uuid");assertTrue(uuid.matches("[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}"));noReadiness(initialized,"initialized",version,uuid);
        String seeded=UUID.randomUUID().toString().replace("-","");
        execute(nativeRoot,rootfs,work,sessions,"seed","guest_check.py",new String[]{"--operation","seed","--expected-version",version,"--operation-id",seeded});
        sqlResult(json(work.resolve("probe-results/"+seeded+".json")),"seed",version,uuid);
        String repeated=UUID.randomUUID().toString().replace("-","");execute(nativeRoot,rootfs,work,sessions,"repeat","android_database_setup.py",new String[]{"--expected-version",version,"--operation-id",repeated});
        noReadiness(json(work.resolve("setup-results/"+repeated+".json")),"already-initialized",version,uuid);
        // Prove the repeated wrapper preserved both row and credentials, not merely its receipt.
        String verified=UUID.randomUUID().toString().replace("-","");
        execute(nativeRoot,rootfs,work,sessions,"verify","guest_check.py",new String[]{"--operation","verify","--expected-version",version,"--operation-id",verified});
        sqlResult(json(work.resolve("probe-results/"+verified+".json")),"verify",version,uuid);
        assertEquals(rootfs,installer.resolveCurrent(plan));
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-mysql-bootstrap-and-restart")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",33).put("targetSdk",35).put("abi","x86_64")
                .put("mysqlVersion",version).put("runtimeProviderSha256",hash(raw)).put("runtimeArchiveSha256",plan.archiveSha256).put("runtimeGeneration",installed.generation)
                .put("prootBuildEvidence",proot).put("guestLaunches",4).put("exactBootstrapHelpersVerified",true).put("runtimeInstalledByProductionInstaller",true)
                .put("databaseInitialized",true).put("rootSqlAuthenticated",true).put("applicationSqlAuthenticated",true).put("socketOnly",true)
                .put("instanceIdentityVerified",true).put("persistentMarkerRestored",true).put("credentialsPreserved",true).put("cleanShutdown",true).put("repeatBootstrapPreserved",true)
                .put("productionAdapterQualified",false).put("arm64Qualified",false).put("serverSchemasQualified",false).put("worldserverQualified",false).put("gameplayQualified",false);
        copy(root.getParent().resolve("mysql-probe-qualification.json"),receipt.toString(2).getBytes(StandardCharsets.UTF_8));
    }

    @Test public void actualJavaServiceAdapterOwnsReadinessShutdownAndRestart()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(BuildConfig.DEBUG);assertTrue(BuildConfig.MYSQL_PROBE_PACKAGED);
        assertFalse(BuildConfig.PROOT_PACKAGED);assertFalse(BuildConfig.SERVER_RUNTIME_PACKAGED);
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        Path appRoot=context.getFilesDir().getCanonicalFile().toPath();
        // A separately owned fresh fixture never adopts the earlier bootstrap test or a player's saves.
        Path root=directory(appRoot.resolve("mysql-service-probe-session"));
        Path stateRoot=GuestHelperAssets.directory(appRoot,"state");
        Path work=directory(stateRoot.resolve("server-work")),sessions=directory(root.resolve("sessions"));
        directory(work.resolve("home"));directory(work.resolve("state"));directory(work.resolve("setup-results"));
        directory(work.resolve("probe-results"));Path helpers=directory(work.resolve("helpers"));
        byte[] raw=asset(context,"mysql-probe/provider.json",65536);
        JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
        RuntimePackagePlan plan=plan(proof,raw);String version=proof.getString("expectedMysqlSqlVersion");
        JSONObject inputs=proof.getJSONObject("sourceInputs");
        for(String family:Arrays.asList("database-setup","database-service")) {
            JSONObject manifest=new JSONObject(new String(asset(context,family+"/manifest.json",16384),StandardCharsets.UTF_8)).getJSONObject("files");
            assertEquals(2,manifest.length());
            for(String name:family.equals("database-setup")?Arrays.asList("mysql_bootstrap.py","android_database_setup.py"):
                    Arrays.asList("mysql_bootstrap.py","mysql_service.py")) {
                byte[] bytes=asset(context,family+"/"+name,131072);JSONObject pin=manifest.getJSONObject(name);
                assertEquals(pin.getLong("bytes"),bytes.length);assertEquals(pin.getString("sha256"),hash(bytes));
                assertEquals(inputs.getJSONObject("runtime/"+name).getString("sha256"),hash(bytes));
                if(family.equals("database-setup"))copy(helpers.resolve(name),bytes);
            }
        }
        byte[] guest=asset(context,"mysql-probe/guest_check.py",65536);
        assertEquals(inputs.getJSONObject("runtime/mysql-probe/guest_check.py").getString("sha256"),hash(guest));
        copy(helpers.resolve("guest_check.py"),guest);
        copy(work.resolve(".mysql-probe-owner"),(hash(raw)+"\n").getBytes(StandardCharsets.US_ASCII));
        Path nativeRoot=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        JSONObject proot=new JSONObject(new String(asset(context,"proot-probe/build-evidence.json",65536),StandardCharsets.UTF_8));
        for(String name:Arrays.asList("libproot_probe.so","libproot_probe_loader.so")) {
            Path file=nativeRoot.resolve(name);JSONObject pin=proot.getJSONObject("nativeFiles").getJSONObject(name);
            assertTrue(Files.isExecutable(file));assertEquals(pin.getLong("bytes"),Files.size(file));assertEquals(pin.getString("sha256"),fileHash(file));
        }
        Path archive=new EmbeddedArchiveCache(root.resolve("cache")).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,
                offset->openArchive(context,offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller installer=new RuntimeInstaller(root.resolve("runtime"));
        RuntimeInstaller.Result installed=installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        Path rootfs=installer.resolveCurrent(plan);assertNotNull(rootfs);
        String initial=UUID.randomUUID().toString().replace("-","");
        execute(nativeRoot,rootfs,work,sessions,"initialize","android_database_setup.py",new String[]{"--expected-version",version,"--operation-id",initial});
        JSONObject initialized=json(work.resolve("setup-results/"+initial+".json"));String uuid=initialized.getString("uuid");
        noReadiness(initialized,"initialized",version,uuid);
        String seed=UUID.randomUUID().toString().replace("-","");
        execute(nativeRoot,rootfs,work,sessions,"seed","guest_check.py",new String[]{"--operation","seed","--expected-version",version,"--operation-id",seed});
        sqlResult(json(work.resolve("probe-results/"+seed+".json")),"seed",version,uuid);
        Map<String,String> retained=new TreeMap<>();
        for(String name:Arrays.asList("database-bootstrap.json","accounts/database-secret","accounts/database-root-secret",".android-mysql-probe-marker.json"))
            retained.put(name,fileHash(work.resolve("state/"+name)));
        AtomicInteger launches=new AtomicInteger();
        ServerDatabaseService.InstalledRuntime runtime=new ServerDatabaseService.InstalledRuntime(){
            @Override public Path current()throws IOException{return installer.resolveCurrent(plan);}
            @Override public String expectedMysqlVersion(){return version;}
            @Override public OwnedProcess launch(Path persistent,Path session,List<String> command,OwnedProcess.GracefulInputStop shutdown)throws IOException {
                assertEquals(work,persistent);assertEquals(rootfs,current());
                Path temporary=directory(session.resolve("tmp")),logs=directory(session.resolve("logs"));
                // Same argument builder, actual JNI owner and pipe as production; only the verified x64 tracer differs.
                OwnedProcess.Specification base=ProotLaunch.create(nativeRoot.resolve("libproot_probe.so"),
                        nativeRoot.resolve("libproot_probe_loader.so"),rootfs,persistent,temporary,logs,command,Collections.emptyMap());
                OwnedProcess.Specification interactive=new OwnedProcess.Specification(base.executable,base.arguments,base.environment,
                        base.cwd,base.stdout,base.stderr,true);
                OwnedProcess child=OwnedProcess.startInteractive(new NativeProcessBridge(),interactive,shutdown);
                launches.incrementAndGet();return child;
            }
        };
        for(int cycle=0;cycle<2;cycle++) {
            ServerDatabaseService.Handle child=ServerDatabaseService.startInstalled(context,appRoot,runtime);
            try {
                ServerDatabaseService.awaitReady(child,System.nanoTime()+TimeUnit.SECONDS.toNanos(150),new AtomicBoolean(false));
                assertEquals(uuid,child.instanceUuid());assertTrue(child.isAlive());
                ServerDatabaseService.Handle duplicate=null;
                try {duplicate=ServerDatabaseService.startInstalled(context,appRoot,runtime);fail("Duplicate Java database lease must be rejected");}
                catch(IOException expected){assertTrue(child.isAlive());}
                finally {if(duplicate!=null)duplicate.stop(Duration.ZERO);}
                assertEquals(cycle+1,launches.get());
                child.stop(Duration.ofSeconds(30));assertFalse(child.isAlive());assertEquals(0,child.exitCode());
                JSONObject stopped=json(child.privateSessionDirectory().resolve("stopped.json"));
                assertTrue(stopped.getBoolean("engineStarted")&&stopped.getBoolean("readyBeforeStop")&&stopped.getBoolean("cleanEngineExit"));
                assertEquals(uuid,stopped.getString("uuid"));assertEquals("command",stopped.getString("stopReason"));
            } finally {
                try {child.stop(Duration.ofSeconds(30));}
                finally {serviceDiagnostics(appRoot,root,child,cycle);}
            }
            try(FileChannel lease=FileChannel.open(work.resolve(".android-database-setup.lock"),StandardOpenOption.WRITE);
                    FileLock released=lease.tryLock()) {assertNotNull("Completed service must release the setup/session lease",released);}
            for(Map.Entry<String,String> item:retained.entrySet())
                assertTrue("Credential, bootstrap and marker identities remain private and unchanged",item.getValue().equals(fileHash(work.resolve("state/"+item.getKey()))));
            String verified=UUID.randomUUID().toString().replace("-","");
            execute(nativeRoot,rootfs,work,sessions,"verify-"+cycle,"guest_check.py",new String[]{"--operation","verify","--expected-version",version,"--operation-id",verified});
            sqlResult(json(work.resolve("probe-results/"+verified+".json")),"verify",version,uuid);
        }
        assertEquals(2,launches.get());assertEquals(rootfs,installer.resolveCurrent(plan));
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-java-mysql-service-lifecycle")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",33).put("targetSdk",35).put("abi","x86_64")
                .put("mysqlVersion",version).put("runtimeProviderSha256",hash(raw)).put("runtimeArchiveSha256",plan.archiveSha256).put("runtimeGeneration",installed.generation)
                .put("prootBuildEvidence",proot).put("serviceLaunches",2).put("verificationGuestLaunches",4).put("duplicateStartAttempts",2)
                .put("exactServiceHelpersVerified",true).put("verifiedX64RuntimeOnly",true).put("realJavaAdapterExecuted",true)
                .put("ownedLoopbackSqlReady",true).put("duplicateLeaseRejected",true).put("explicitShutdownAcknowledged",true)
                .put("leaseReleasedAfterStop",true).put("sameInstanceRestarted",true).put("markerRestoredAfterEachStop",true).put("credentialsPreserved",true)
                .put("productionAdapterQualified",false).put("arm64Qualified",false).put("serverSchemasQualified",false).put("worldserverQualified",false).put("gameplayQualified",false);
        copy(appRoot.resolve("mysql-service-probe-qualification.json"),receipt.toString(2).getBytes(StandardCharsets.UTF_8));
    }

    private static void serviceDiagnostics(Path appRoot,Path fixture,ServerDatabaseService.Handle child,int cycle)throws Exception {
        Path destination=directory(fixture.resolve("sessions/service-"+cycle)),logs=directory(destination.resolve("logs"));
        String operation=child.privateSessionDirectory().getFileName().toString();assertTrue(operation.matches("[a-f0-9]{32}"));
        Map<String,Path> sources=new TreeMap<>();
        for(String stream:Arrays.asList("stdout","stderr"))sources.put(stream+".log",appRoot.resolve("state/database-service-operations/"+operation+"/logs/"+stream+".log"));
        sources.put("engine-private.log",child.privateSessionDirectory().resolve("engine-private.log"));
        for(Map.Entry<String,Path> item:sources.entrySet())if(Files.isRegularFile(item.getValue(),LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes;try(InputStream input=Files.newInputStream(item.getValue())){bytes=read(input,65536);}
            String redacted=new String(bytes,StandardCharsets.UTF_8).replaceAll("(?i)[a-f0-9]{64}","[redacted-generated-secret]");
            copy(logs.resolve(item.getKey()),redacted.getBytes(StandardCharsets.UTF_8));
        }
    }
}
