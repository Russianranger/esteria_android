package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual Android x86_64 ptrace/loader/glibc probe; never enabled by ordinary builds. */
@RunWith(AndroidJUnit4.class)
public final class ProotExecutionTest {
    private static final String[] MEMBERS={"probe","probe-plugin.so","lib/x86_64-linux-gnu/libc.so.6","lib64/ld-linux-x86-64.so.2"};
    private static String hex(byte[] data) {
        StringBuilder value=new StringBuilder(); for(byte item:data)value.append(String.format(java.util.Locale.ROOT,"%02x",item&255)); return value.toString();
    }
    private static String hash(Path path) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256"); byte[] buffer=new byte[65536];
        try(InputStream input=Files.newInputStream(path)){int count;while((count=input.read(buffer))!=-1)digest.update(buffer,0,count);}
        return hex(digest.digest());
    }
    private static byte[] bounded(InputStream input,int limit) throws IOException {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] buffer=new byte[4096];int count;
        while((count=input.read(buffer))!=-1){if(output.size()+count>limit)throw new IOException("Oversized probe metadata");output.write(buffer,0,count);}
        return output.toByteArray();
    }
    private static String read(Path path) throws IOException {
        try(InputStream input=Files.newInputStream(path)){return new String(bounded(input,65536),StandardCharsets.UTF_8);}
    }
    private static Path directory(Path path) throws IOException {
        Files.createDirectory(path);Files.setPosixFilePermissions(path,PosixFilePermissions.fromString("rwx------"));return path;
    }
    private static void assertIdentity(Path path,JSONObject pin) throws Exception {
        assertEquals(pin.getLong("bytes"),Files.size(path));assertEquals(pin.getString("sha256"),hash(path));
    }
    private static void await(OwnedProcess child) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(40);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(10);
        if(child.isAlive()){try{child.stop(Duration.ZERO);}finally{fail("Guest did not finish before deadline");}}
        assertNull(child.failure());assertEquals("Real guest process exit",0,child.exitCode());assertEquals(0,child.diagnostics()[4]);
    }
    @Test public void privateGlibcExecutesThroughApkLoader() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        assertFalse("Production ARM64 provider must stay separate",BuildConfig.PROOT_PACKAGED);
        Path nativeRoot=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        Path tracer=nativeRoot.resolve("libproot_probe.so"),loader=nativeRoot.resolve("libproot_probe_loader.so");
        assertTrue("Probe payload mandatory; missing is failure",Files.isExecutable(tracer)&&Files.isExecutable(loader));
        JSONObject build;
        try(InputStream input=context.getAssets().open("proot-probe/build-evidence.json")){
            build=new JSONObject(new String(bounded(input,65536),StandardCharsets.UTF_8));
        }
        assertEquals("android-13-x86_64-proot-glibc-probe-build-only",build.getString("scope"));
        assertIdentity(tracer,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe.so"));
        assertIdentity(loader,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe_loader.so"));
        JSONObject files=build.getJSONObject("rootfsFiles");assertEquals(MEMBERS.length,files.length());
        Path root=directory(context.getFilesDir().toPath().toRealPath().resolve("proot-probe-session"));
        Path rootfs=directory(root.resolve("rootfs")),work=directory(root.resolve("work"));
        Path temporary=directory(root.resolve("tmp")),logs=directory(root.resolve("logs"));
        for(String member:MEMBERS){
            JSONObject pin=files.getJSONObject(member);long expected=pin.getLong("bytes");assertTrue(expected>0&&expected<=16*1024*1024);
            Path target=rootfs.resolve(member);Files.createDirectories(target.getParent());
            try(InputStream input=context.getAssets().open("proot-probe/rootfs/"+member);
                OutputStream output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)){
                byte[] buffer=new byte[65536];long copied=0;int count;
                while((count=input.read(buffer))!=-1){copied+=count;assertTrue(copied<=expected);output.write(buffer,0,count);}
                assertEquals(expected,copied);
            }
            Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rwx------"));assertIdentity(target,pin);
        }
        // The same Bionic tracer is executable from the installed APK, but its
        // private copy must fail direct exec under current app-data policy. Using
        // Bionic avoids confusing a missing Linux ELF interpreter with rejection.
        Path control=root.resolve("private-tracer");Files.copy(tracer,control);
        Files.setPosixFilePermissions(control,PosixFilePermissions.fromString("rwx------"));assertEquals(hash(tracer),hash(control));
        NativeProcessBridge backend=new NativeProcessBridge();
        OwnedProcess unexpected=null;
        try {
            unexpected=OwnedProcess.start(backend,new OwnedProcess.Specification(control,Collections.singletonList("--version"),
                Collections.singletonMap("PATH","/system/bin"),work,logs.resolve("direct-out"),logs.resolve("direct-err")),null);
        } catch(IOException rejected) { /* Expected negative control; positive execution follows. */ }
        if(unexpected!=null){try{if(unexpected.isAlive())unexpected.stop(Duration.ZERO);}finally{fail("Direct private Bionic exec unexpectedly started");}}
        Map<String,String> environment=new HashMap<>();environment.put("PROOT_LOADER",loader.toString());
        environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
        for(String mode:Arrays.asList("write","verify")){
            Path run=directory(logs.resolve(mode));
            OwnedProcess child=OwnedProcess.start(backend,new OwnedProcess.Specification(tracer,
                Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),"-b","/dev","-b","/proc",
                    "-b",work+":/work","-b",temporary+":/tmp","-w","/work","/probe","/work","/probe-plugin.so","2.36",mode),
                environment,work,run.resolve("stdout.log"),run.resolve("stderr.log")),null);
            try { await(child); }
            finally { if(child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException forced){ /* Original assertion remains failure. */ } }
            String expected="ESTERIA_ANDROID_GLIBC_PROBE glibc=2.36 dlopen=1 tls=1 fork=1 exec=1 loopback=1 persistence="+mode+" childExit=17\n";
            assertEquals("Actual guest marker and counts",expected,read(run.resolve("stdout.log")));
            assertEquals(expected.getBytes(StandardCharsets.UTF_8).length,child.diagnostics()[0]);
            assertEquals("esteria-local-runtime-persistence\n",read(work.resolve("persistent-probe.txt")));
        }
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-proot-glibc-execution")
            .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",Build.VERSION.SDK_INT)
            .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("abi","x86_64").put("glibcVersion","2.36")
            .put("guestLaunches",2).put("guestChildExit",17).put("buildEvidence",build)
            .put("androidProotExecuted",true).put("privateElfLoaderExecuted",true).put("directPrivateBionicExecRejected",true)
            .put("dynamicLibraryAndTlsVerified",true).put("forkExecLoopbackVerified",true).put("relaunchPersistenceVerified",true)
            .put("arm64GuestExecuted",false).put("appDeathQualified",false).put("wineQualified",false).put("gameplayQualified",false);
        Files.write(root.getParent().resolve("proot-probe-qualification.json"),receipt.toString(2).getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        // The disposable harness exports bounded logs before stopping this app.
    }
}
