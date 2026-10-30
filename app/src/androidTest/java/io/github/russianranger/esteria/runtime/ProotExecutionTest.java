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
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual Android x86_64 ptrace/loader/glibc probe; never enabled by ordinary builds. */
@RunWith(AndroidJUnit4.class)
public final class ProotExecutionTest {
    private static final String[] MEMBERS={"probe","probe-owner","probe-plugin.so","lib/x86_64-linux-gnu/libc.so.6","lib64/ld-linux-x86-64.so.2"};
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
        await(child,0);
    }
    private static void await(OwnedProcess child,int expectedExit) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(40);
        while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(10);
        if(child.isAlive()){try{child.stop(Duration.ZERO);}finally{fail("Guest did not finish before deadline");}}
        assertNull(child.failure());assertEquals("Real guest process exit",expectedExit,child.exitCode());assertEquals(0,child.diagnostics()[4]);
    }
    private static OwnedProcess.Specification ownershipSpec(Path tracer,Path loader,Path rootfs,Path work,Path temporary,Path logs,String mode) {
        Map<String,String> environment=new HashMap<>();environment.put("PROOT_LOADER",loader.toString());
        environment.put("PROOT_NO_SECCOMP","1");environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
        return new OwnedProcess.Specification(tracer,Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),
            "-b","/dev","-b","/proc","-b",work+":/work","-b",temporary+":/tmp","-w","/work","/probe-owner","/work",mode),
            environment,work,logs.resolve("stdout.log"),logs.resolve("stderr.log"));
    }
    private static long ownershipCase(NativeProcessBridge backend,Path tracer,Path loader,Path rootfs,Path root,String name,boolean patched,boolean graceful) throws Exception {
        // Begin before process creation, earlier than every guest alarm. A late
        // observation must never turn the fixture's own timeout into EXITKILL proof.
        long caseStarted=System.nanoTime();
        Path session=directory(root.resolve(name));Path work=directory(session.resolve("work"));
        Path temporary=directory(session.resolve("tmp")),logs=directory(session.resolve("logs"));
        OwnedProcess child=OwnedProcess.start(backend,ownershipSpec(tracer,loader,rootfs,work,temporary,logs,graceful?"graceful":"forced"),
            graceful?()->Files.write(work.resolve("stop"),new byte[]{1},StandardOpenOption.CREATE_NEW):null);
        List<Long> watched=new ArrayList<>();List<Integer> pids=new ArrayList<>();long tracerHandle=0;
        try {
            Pattern pattern=Pattern.compile("^ESTERIA_PROOT_OWNER_PID ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*) ([1-9][0-9]*)$",Pattern.MULTILINE);
            String handshake="";long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
            while(System.nanoTime()<deadline){handshake=read(logs.resolve("stdout.log"));if(handshake.chars().filter(ch->ch=='\n').count()==3)break;
                assertTrue("Ownership guest ended before handshake",child.isAlive());Thread.sleep(10);}
            assertEquals("Three bounded identity records",3,handshake.split("\n").length);
            Matcher matcher=pattern.matcher(handshake);int tracerPid=0;long tracerTicks=0;
            while(matcher.find()){
                int pid=Integer.parseInt(matcher.group(1)),reportedTracer=Integer.parseInt(matcher.group(3));
                long ticks=Long.parseLong(matcher.group(2)),reportedTracerTicks=Long.parseLong(matcher.group(4));
                assertEquals("Every tracee must detach from the tracer's process group",pid,Integer.parseInt(matcher.group(5)));
                if(tracerPid==0){tracerPid=reportedTracer;tracerTicks=reportedTracerTicks;tracerHandle=ProbeProcessHandles.watch(tracerPid,tracerTicks,0,tracer.toString(),"");}
                assertEquals(tracerPid,reportedTracer);assertEquals(tracerTicks,reportedTracerTicks);assertNotEquals(tracerPid,pid);
                pids.add(pid);watched.add(ProbeProcessHandles.watch(pid,ticks,tracerPid,loader.toString(),rootfs.resolve("probe-owner").toString()));
            }
            assertEquals(3,watched.size());assertEquals(3,new HashSet<>(pids).size());
            if(!graceful){
                Path armed=work.resolve("armed");String expected="\u0001\u0001\u0001";
                while(System.nanoTime()<deadline){
                    if(Files.exists(armed)&&expected.equals(read(armed)))break;
                    assertTrue("Ownership guest ended before CPU-only wait",child.isAlive());Thread.sleep(10);
                }
                assertEquals("All tracees passed their final syscall before intervention",expected,read(armed));
            }
            for(long handle:watched)assertFalse("Tracee must be alive before the intervention",ProbeProcessHandles.exited(handle,0));
            if(graceful){
                child.stop(Duration.ofSeconds(5));assertFalse(child.wasForced());assertEquals(0,child.exitCode());assertNull(child.failure());
                for(int pid:pids)assertEquals("graceful-persisted\n",read(work.resolve("saved-"+pid)));
                for(long handle:watched)assertTrue("Graceful guest exited",ProbeProcessHandles.exited(handle,1000));
                Path verifyLogs=directory(session.resolve("verify"));
                OwnedProcess verify=OwnedProcess.start(backend,ownershipSpec(tracer,loader,rootfs,work,temporary,verifyLogs,"verify"),null);
                try{await(verify);assertEquals("ESTERIA_PROOT_OWNER_SAVE_VERIFY 3\n",read(verifyLogs.resolve("stdout.log")));}
                finally{if(verify.isAlive())try{verify.stop(Duration.ZERO);}catch(IOException ignored){ /* Original assertion fails. */ }}
            }else{
                assertTrue("Ownership intervention exceeded causal observation budget",System.nanoTime()-caseStarted<TimeUnit.SECONDS.toNanos(25));
                ProbeProcessHandles.kill(tracerHandle);assertTrue("Only verified tracer was killed",ProbeProcessHandles.exited(tracerHandle,5000));
                await(child,137);
                for(long handle:watched)assertEquals(patched?"EXITKILL must terminate every detached tracee":"Unpatched control must retain every detached tracee",
                    patched,ProbeProcessHandles.exited(handle,patched?5000:200));
                assertTrue("Guest alarms cannot establish tracer-death qualification",System.nanoTime()-caseStarted<TimeUnit.SECONDS.toNanos(25));
            }
            return TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-caseStarted);
        }finally{
            IOException cleanup=null;
            for(long handle:watched)try{ProbeProcessHandles.kill(handle);if(!ProbeProcessHandles.exited(handle,5000))throw new IOException("Verified guest cleanup timed out");}
                catch(IOException failure){if(cleanup==null)cleanup=failure;else cleanup.addSuppressed(failure);}
                finally{try{ProbeProcessHandles.close(handle);}catch(IOException failure){if(cleanup==null)cleanup=failure;else cleanup.addSuppressed(failure);}}
            if(tracerHandle!=0)try{ProbeProcessHandles.kill(tracerHandle);if(!ProbeProcessHandles.exited(tracerHandle,5000))throw new IOException("Verified tracer cleanup timed out");}
                catch(IOException failure){if(cleanup==null)cleanup=failure;else cleanup.addSuppressed(failure);}
                finally{try{ProbeProcessHandles.close(tracerHandle);}catch(IOException failure){if(cleanup==null)cleanup=failure;else cleanup.addSuppressed(failure);}}
            if(child.isAlive())try{child.stop(Duration.ZERO);}catch(IOException expectedForced){ /* Failure cleanup; never establishes a pass. */ }
            if(cleanup!=null)throw cleanup;
        }
    }
    @Test public void privateGlibcExecutesThroughApkLoader() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        assertTrue("Unpatched control exists only in debug qualification APKs",BuildConfig.DEBUG);
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        assertFalse("Production ARM64 provider must stay separate",BuildConfig.PROOT_PACKAGED);
        Path nativeRoot=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        Path tracer=nativeRoot.resolve("libproot_probe.so"),loader=nativeRoot.resolve("libproot_probe_loader.so");
        Path controlTracer=nativeRoot.resolve("libproot_probe_control.so");
        assertTrue("Probe payload mandatory; missing is failure",Files.isExecutable(tracer)&&Files.isExecutable(loader));
        JSONObject build;
        try(InputStream input=context.getAssets().open("proot-probe/build-evidence.json")){
            build=new JSONObject(new String(bounded(input,65536),StandardCharsets.UTF_8));
        }
        assertEquals("android-13-x86_64-proot-glibc-probe-build-only",build.getString("scope"));
        assertIdentity(tracer,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe.so"));
        assertIdentity(loader,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe_loader.so"));
        assertIdentity(controlTracer,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe_control.so"));
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
            String expected="ESTERIA_ANDROID_RENAME_PROBE legacy=1 atomicReplace=1 oldDescriptor=1 missingSourceErrno=1 symlink=1 cwd=1 persistence="+mode+"\n"
                +"ESTERIA_ANDROID_GLIBC_PROBE glibc=2.36 dlopen=1 tls=1 fork=1 exec=1 loopback=1 persistence="+mode+" childExit=17\n";
            assertEquals("Actual guest marker and counts",expected,read(run.resolve("stdout.log")));
            assertEquals(expected.getBytes(StandardCharsets.UTF_8).length,child.diagnostics()[0]);
            assertEquals("esteria-local-runtime-persistence\n",read(work.resolve("persistent-probe.txt")));
        }
        long controlMillis=ownershipCase(backend,controlTracer,loader,rootfs,root,"ownership-control",false,false);
        long patchedMillis=ownershipCase(backend,tracer,loader,rootfs,root,"ownership-patched",true,false);
        ownershipCase(backend,tracer,loader,rootfs,root,"ownership-graceful",true,true);
        JSONObject ownerDeath=RemoteOwnerDeathProbe.run(context,root,tracer,loader);
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-proot-glibc-execution")
            .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",Build.VERSION.SDK_INT)
            .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("abi","x86_64").put("glibcVersion","2.36")
            .put("guestLaunches",8).put("guestChildExit",17).put("buildEvidence",build)
            .put("legacyRenameReplacementVerified",true).put("renamePersistenceVerified",true)
            .put("androidProotExecuted",true).put("privateElfLoaderExecuted",true).put("directPrivateBionicExecRejected",true)
            .put("dynamicLibraryAndTlsVerified",true).put("forkExecLoopbackVerified",true).put("relaunchPersistenceVerified",true)
            .put("androidTracerDeathQualified",true).put("pidfdIdentityVerified",true).put("controlSurvivors",3).put("patchedSurvivors",0)
            .put("userSpaceWaitArmed",true)
            .put("detachedTraceesPerCase",3).put("gracefulGuestStopVerified",true).put("gracefulSavedFilesRestored",3)
            .put("controlObservationMillis",controlMillis).put("patchedObservationMillis",patchedMillis)
            .put("arm64GuestExecuted",false).put("appDeathQualified",false).put("wineQualified",false).put("gameplayQualified",false);
        for(java.util.Iterator<String> keys=ownerDeath.keys();keys.hasNext();){String key=keys.next();receipt.put(key,ownerDeath.get(key));}
        Files.write(root.getParent().resolve("proot-probe-qualification.json"),receipt.toString(2).getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        // The disposable harness exports bounded logs before stopping this app.
    }
}
