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
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real reconstructed Windows x64 diagnostics through Wine in an isolated emulator profile. */
@RunWith(AndroidJUnit4.class)
public final class WineExecutionTest {
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
        assertEquals(1,proof.getInt("formatVersion"));assertEquals("android-x86-64-wine-client-probe-build-only",proof.getString("scope"));
        assertEquals("x86_64",proof.getString("architecture"));assertEquals("wine-probe-x86-64",proof.getString("packageKey"));
        for(String flag:Arrays.asList("androidRuntimeQualified","arm64Qualified","gameplayQualified"))assertFalse(proof.getBoolean(flag));
        JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits"),required=proof.getJSONObject("requiredFiles");
        assertEquals("wine-probe/wine-x86-64.archive",archive.getString("assetPath"));assertEquals("wine-x86-64.tar.gz",archive.getString("file"));
        Map<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
        for(Iterator<String> names=required.keys();names.hasNext();){String name=names.next();JSONObject pin=required.getJSONObject(name);
            int elf=pin.optInt("elfMachine",0),pe=pin.has("peMachine")?Integer.decode(pin.getString("peMachine")):0;
            assertTrue(elf==0||elf==62);assertTrue(pe==0||pe==0x8664);
            files.put(name,new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"),pin.getString("sha256"),elf,pe));}
        for(String name:Arrays.asList("opt/wine/bin/wine","opt/wine/bin/wineserver","usr/bin/python3.11"))assertEquals(62,files.get(name).elfMachine);
        return new RuntimePackagePlan("wine-probe-x86-64",hash(raw),archive.getString("file"),archive.getLong("bytes"),archive.getString("sha256"),
                proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),
                bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes")),files);
    }
    private static InputStream archive(Context context,long offset)throws IOException {
        AssetFileDescriptor descriptor=context.getAssets().openFd("wine-probe/wine-x86-64.archive");InputStream input=null;
        try{input=descriptor.createInputStream();long left=offset;while(left>0){long count=input.skip(left);if(count>0)left-=count;
            else if(input.read()<0)throw new IOException("Wine archive resume beyond end");else left--;}return input;}
        catch(IOException|RuntimeException error){if(input!=null)input.close();else descriptor.close();throw error;}
    }
    private static void payload(Context context,Path work,JSONObject files)throws Exception {
        assertTrue(files.length()<=256);int count=0;
        for(Iterator<String> names=files.keys();names.hasNext();){String name=names.next();
            if(!name.startsWith("client/")&&!name.startsWith("helpers/"))continue;
            assertTrue(name.matches("(?:client|helpers)/[A-Za-z0-9_.-]{1,100}"));JSONObject pin=files.getJSONObject(name);
            long size=pin.getLong("bytes"),limit=name.endsWith(".exe")||name.endsWith(".dll")?64L*1024*1024:2L*1024*1024;
            assertTrue(size>0&&size<=limit);Path target=work.resolve(name);long copied=0;byte[] buffer=new byte[65536];
            try(InputStream input=context.getAssets().open("wine-probe/"+name);java.io.OutputStream output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)){
                int length;while((length=input.read(buffer))!=-1){copied+=length;assertTrue(copied<=size);output.write(buffer,0,length);}}
            Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rw-------"));assertEquals(size,copied);assertEquals(pin.getString("sha256"),fileHash(target));count++;
        }
        assertEquals(8,count); // two images, manifest/limits, guest script and three source validators
    }
    private static void execute(Path natives,Path rootfs,Path work,Path sessions,String phase)throws Exception {
        Path session=directory(sessions.resolve(phase)),temporary=directory(session.resolve("tmp")),logs=directory(session.resolve("logs"));
        Map<String,String> environment=new HashMap<>();environment.put("PROOT_LOADER",natives.resolve("libproot_probe_loader.so").toString());
        environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
        java.util.List<String> command=Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),"-b","/dev","-b","/proc",
                "-b",work+":/work","-b",temporary+":/tmp","-w","/work","/usr/bin/env","-i","HOME=/work/home","PATH=/usr/bin:/bin",
                "TMPDIR=/tmp","LANG=C.UTF-8","/usr/bin/python3","-B","-s","-E","/work/helpers/guest_check.py","--phase",phase);
        OwnedProcess child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(natives.resolve("libproot_probe.so"),command,environment,work,
                logs.resolve("stdout.log"),logs.resolve("stderr.log")),null);
        try {
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(5);
            while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(100);
            assertFalse("Owned Wine phase deadline: "+phase,child.isAlive());assertNull(child.failure());
            assertEquals("Actual Wine guest exit: "+phase,0,child.exitCode());assertFalse(child.wasForced());
            long[] diagnostics=child.diagnostics();assertEquals(0,diagnostics[4]);
            assertEquals("stdout fully retained",diagnostics[0],diagnostics[1]);assertEquals("stderr fully retained",diagnostics[2],diagnostics[3]);
        } finally {if(child.isAlive())child.stop(Duration.ZERO);}
    }
    private static void diagnostic(JSONObject report,String phase)throws Exception {
        assertEquals(1,report.getInt("formatVersion"));assertEquals("owned-reconstructed-client-diagnostic-only",report.getString("scope"));
        assertEquals(phase,report.getString("phase"));assertTrue(report.getBoolean("wineserverStoppedNormally"));
        for(String flag:Arrays.asList("commonMainStarted","assetsLoaded","arm64Qualified","gameplayQualified"))assertFalse(report.getBoolean(flag));
        assertTrue(report.getString("clientReceiptSha256").matches("[a-f0-9]{64}"));JSONObject checked=report.getJSONObject("clientReceipt");
        assertEquals("x64",checked.getString("architecture"));assertEquals(12340,checked.getInt("protocolBuild"));
        assertFalse(checked.getBoolean("commonMainStarted"));assertFalse(checked.getBoolean("assetsLoaded"));
        JSONObject checks=checked.getJSONObject("checks");assertTrue(checks.length()>0);
        for(Iterator<String> names=checks.keys();names.hasNext();)assertTrue(checks.getBoolean(names.next()));
    }
    @Test public void actualReconstructedClientRunsThroughWine()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(BuildConfig.DEBUG);assertTrue(BuildConfig.WINE_PROBE_PACKAGED);assertFalse(BuildConfig.MYSQL_PROBE_PACKAGED);
        assertFalse(BuildConfig.PROOT_PACKAGED);assertFalse(BuildConfig.SERVER_RUNTIME_PACKAGED);assertFalse(BuildConfig.CLIENT_RUNTIME_PACKAGED);
        assertFalse(BuildConfig.GUEST_BRIDGES_PACKAGED);assertFalse(BuildConfig.SHADER_TOOLS_PACKAGED);
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        byte[] raw=asset(context,"wine-probe/provider.json",65536);JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));RuntimePackagePlan plan=plan(proof,raw);
        Path natives=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        JSONObject proot=new JSONObject(new String(asset(context,"proot-probe/build-evidence.json",65536),StandardCharsets.UTF_8));
        for(String name:Arrays.asList("libproot_probe.so","libproot_probe_loader.so")){
            Path file=natives.resolve(name);JSONObject pin=proot.getJSONObject("nativeFiles").getJSONObject(name);
            assertTrue(Files.isExecutable(file));assertEquals(pin.getLong("bytes"),Files.size(file));assertEquals(pin.getString("sha256"),fileHash(file));}
        Path root=directory(context.getFilesDir().toPath().toRealPath().resolve("wine-probe-session"));
        Path work=directory(root.resolve("work")),sessions=directory(root.resolve("sessions"));
        for(String name:Arrays.asList("home","client","helpers","results"))directory(work.resolve(name));
        copy(work.resolve(".wine-probe-owner"),(hash(raw)+"\n").getBytes(StandardCharsets.US_ASCII));payload(context,work,proof.getJSONObject("files"));
        Path archive=new EmbeddedArchiveCache(root.resolve("cache")).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,
                offset->archive(context,offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        RuntimeInstaller installer=new RuntimeInstaller(root.resolve("runtime"));RuntimeInstaller.Result installed=installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        Path rootfs=installer.resolveCurrent(plan);assertNotNull(rootfs);execute(natives,rootfs,work,sessions,"prefix");
        JSONObject prefix=json(work.resolve("results/prefix.json"));assertEquals("wine-prefix-initialized-only",prefix.getString("scope"));assertTrue(prefix.getBoolean("prefixInitialized"));
        for(String flag:Arrays.asList("reconstructedClientExecuted","commonMainStarted","gameplayQualified"))assertFalse(prefix.getBoolean(flag));
        JSONObject checks=new JSONObject();
        for(String phase:Arrays.asList("entry","offline","loopback")){
            execute(natives,rootfs,work,sessions,phase);JSONObject result=json(work.resolve("results/"+phase+".json"));diagnostic(result,phase);checks.put(phase,result);}
        assertEquals(rootfs,installer.resolveCurrent(plan));
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-wine-reconstructed-client-diagnostics")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",33).put("targetSdk",35).put("abi","x86_64")
                .put("wineVersion",proof.getString("wineVersion")).put("runtimeProviderSha256",hash(raw)).put("runtimeArchiveSha256",plan.archiveSha256).put("runtimeGeneration",installed.generation)
                .put("clientRevision",proof.getJSONObject("clientInput").getString("sourceRevision"))
                .put("clientArtifactSha256",proof.getJSONObject("clientInput").getJSONObject("artifact").getString("sha256"))
                .put("prootBuildEvidence",proot).put("guestLaunches",4).put("runtimeInstalledByProductionInstaller",true).put("exactClientPayloadVerified",true)
                .put("prefixInitialized",true).put("normalPhaseExits",true).put("clientChecks",checks)
                .put("arm64Qualified",false).put("graphicsQualified",false).put("audioQualified",false).put("authenticationQualified",false)
                .put("commonMainStarted",false).put("assetsLoaded",false).put("gameplayQualified",false);
        copy(root.getParent().resolve("wine-probe-qualification.json"),receipt.toString(2).getBytes(StandardCharsets.UTF_8));
    }
}
