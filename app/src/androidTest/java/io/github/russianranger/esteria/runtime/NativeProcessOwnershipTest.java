package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.WorldConsoleShutdown;
import java.io.File;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Duration;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Executes installed JNI + system shell on Android; no guest, PRoot or game. */
@RunWith(AndroidJUnit4.class)
public final class NativeProcessOwnershipTest {
    private static OwnedProcess.Specification spec(Path path,String script,String... extra) throws IOException {
        Files.createDirectory(path);
        java.util.ArrayList<String> args=new java.util.ArrayList<>(Arrays.asList("-c",script,"fixture"));
        args.addAll(Arrays.asList(extra));
        return new OwnedProcess.Specification(new File("/system/bin/sh").toPath(),args,
            Collections.singletonMap("PATH","/system/bin"),path,path.resolve("stdout.log"),path.resolve("stderr.log"));
    }
    private static void complete(OwnedProcess child) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(15);
        while (child.isAlive() && System.nanoTime()<deadline) Thread.sleep(10);
        if (child.isAlive()) { try { child.stop(Duration.ZERO); } finally { fail("Owned process did not exit"); } }
    }
    private static OwnedProcess.Specification interactive(Path path,String script) throws IOException {
        OwnedProcess.Specification base=spec(path,script);
        return new OwnedProcess.Specification(base.executable,base.arguments,base.environment,base.cwd,base.stdout,base.stderr,true);
    }
    private static String read(Path path) throws IOException { return new String(Files.readAllBytes(path),StandardCharsets.UTF_8); }
    private static void write(Path path,String value) throws IOException { Files.write(path,value.getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW); }

    @Test public void nativeOwnerContracts() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertEquals("Android13 qualification job required",33,Build.VERSION.SDK_INT);
        assertEquals("Keep current target execution policy",35,context.getApplicationInfo().targetSdkVersion);
        assertTrue("x86_64 emulator qualification only",Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));
        assertTrue("Native owner is mandatory; missing payload is not a skipped pass",
            new File(context.getApplicationInfo().nativeLibraryDir,"libesteria_process.so").isFile());
        assertFalse("This job must not imply ARM64 PRoot execution",BuildConfig.PROOT_PACKAGED);
        Path root=Files.createTempDirectory(context.getFilesDir().toPath(),"native-owner-🌍-");
        NativeProcessBridge backend=new NativeProcessBridge();
        java.util.ArrayList<OwnedProcess> owned=new java.util.ArrayList<>();
        try {
            OwnedProcess exit=OwnedProcess.start(backend,spec(root.resolve("utf8"),"printf '%s' \"$1\"; exit 7","🌍 café"),null); owned.add(exit);
            complete(exit); assertEquals(7,exit.exitCode()); assertNull(exit.failure());
            assertEquals("🌍 café",read(root.resolve("utf8/stdout.log"))); assertEquals(10,exit.diagnostics()[0]);

            Path graceful=root.resolve("graceful"); AtomicReference<OwnedProcess> created=new AtomicReference<>();
            AtomicReference<Exception> startupFailure=new AtomicReference<>();
            Thread caller=new Thread(()->{
                try { created.set(OwnedProcess.start(backend,spec(graceful,"while [ ! -f stop ]; do sleep .01; done; printf saved > saved"),()->write(graceful.resolve("stop"),"stop"))); }
                catch (Exception error) { startupFailure.set(error); }
            });
            caller.start(); caller.join(5000); assertFalse("Launch caller must finish",caller.isAlive()); assertNull(startupFailure.get());
            OwnedProcess saving=created.get(); assertNotNull(saving); owned.add(saving);
            Thread.sleep(150); assertTrue("Native owner must outlive launch caller thread",saving.isAlive());
            saving.stop(Duration.ofSeconds(3)); assertFalse(saving.wasForced()); assertEquals(0,saving.exitCode());
            assertEquals("saved",read(graceful.resolve("saved"))); saving.stop(Duration.ZERO);

            OwnedProcess forced=OwnedProcess.start(backend,spec(root.resolve("forced"),"trap '' TERM; exec sleep 30"),()->{}); owned.add(forced);
            try { forced.stop(Duration.ofMillis(150)); fail("Signal termination must remain a shutdown failure"); } catch (IOException expected) { }
            assertFalse(forced.isAlive()); assertTrue(forced.wasForced());

            OwnedProcess failed=OwnedProcess.start(backend,spec(root.resolve("failed-request"),"exec sleep 30"),()->{throw new IOException("Fixture request failure");}); owned.add(failed);
            try { failed.stop(Duration.ofSeconds(3)); fail("Failed save request must not report success"); } catch (IOException expected) { }
            assertFalse(failed.isAlive()); assertTrue(failed.wasForced());

            OwnedProcess loud=OwnedProcess.start(backend,spec(root.resolve("bounded-pipes"),"head -c 9000000 /dev/zero; head -c 9000000 /dev/zero >&2"),null); owned.add(loud);
            complete(loud); assertEquals(0,loud.exitCode()); assertNull(loud.failure());
            assertArrayEquals(new long[]{9000000,8388608,9000000,8388608,0},loud.diagnostics());
            assertEquals(8388608,Files.size(root.resolve("bounded-pipes/stdout.log")));
            assertEquals(8388608,Files.size(root.resolve("bounded-pipes/stderr.log")));

            try {
                OwnedProcess.start(backend,new OwnedProcess.Specification(new File("/system/bin/esteria-missing-fixture").toPath(),Collections.emptyList(),Collections.emptyMap(),
                    root,root.resolve("missing-out"),root.resolve("missing-err")),null);
                fail("Missing executable must fail before handle publication");
            } catch (IOException expected) { }

            Path echoPath=root.resolve("interactive-echo");
            OwnedProcess echo=OwnedProcess.startInteractive(backend,interactive(echoPath,"cat"),null);owned.add(echo);
            byte[] binary=new byte[257];for(int i=0;i<binary.length;i++)binary[i]=(byte)i;
            assertTrue(echo.writeInput(binary,Duration.ofMillis(200)));echo.closeInput();complete(echo);
            assertEquals(0,echo.exitCode());assertNull(echo.failure());
            assertArrayEquals(binary,Files.readAllBytes(echoPath.resolve("stdout.log")));
            try {echo.writeInput(binary,Duration.ZERO);fail("Exited console input must be closed");}catch(IOException expected) { }

            Path pressurePath=root.resolve("interactive-pressure");
            OwnedProcess pressure=OwnedProcess.startInteractive(backend,interactive(pressurePath,"while [ ! -f drain ]; do sleep .01; done; cat"),null);owned.add(pressure);
            byte[] block=new byte[4096];Arrays.fill(block,(byte)'b');int accepted=0;
            while(accepted<1024*1024&&pressure.writeInput(block,Duration.ZERO))accepted+=block.length;
            assertTrue("Expected real pipe backpressure",accepted>0&&accepted<1024*1024);
            byte[] rejected=new byte[4096];Arrays.fill(rejected,(byte)'r');long began=System.nanoTime();
            assertFalse(pressure.writeInput(rejected,Duration.ofMillis(80)));
            assertTrue("Pipe timeout must be bounded",System.nanoTime()-began<TimeUnit.SECONDS.toNanos(2));
            AtomicReference<Throwable> writerResult=new AtomicReference<>();
            Thread writer=new Thread(()->{try {pressure.writeInput(rejected,Duration.ofSeconds(1));writerResult.set(new AssertionError("Closed writer returned normally"));}catch(Throwable error){writerResult.set(error);}});
            writer.start();Thread.sleep(50);pressure.closeInput();writer.join(2000);
            assertFalse("Closing input must cancel pending write",writer.isAlive());assertTrue(writerResult.get() instanceof IOException);
            write(pressurePath.resolve("drain"),"go");complete(pressure);assertEquals(0,pressure.exitCode());assertNull(pressure.failure());
            byte[] expectedBytes=new byte[accepted];Arrays.fill(expectedBytes,(byte)'b');
            assertArrayEquals("Timed out commands must queue no partial bytes",expectedBytes,Files.readAllBytes(pressurePath.resolve("stdout.log")));
            Path brokenPath=root.resolve("interactive-broken");
            OwnedProcess broken=OwnedProcess.startInteractive(backend,interactive(brokenPath,"exec 0<&-; printf ready; exec sleep 30"),null);owned.add(broken);
            long ready=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            while(Files.size(brokenPath.resolve("stdout.log"))<5&&System.nanoTime()<ready)Thread.sleep(10);
            assertEquals("ready",read(brokenPath.resolve("stdout.log")));
            try {broken.writeInput(binary,Duration.ofMillis(100));fail("Closed reader must refuse input without fatal SIGPIPE");}catch(IOException expected) { }
            try {broken.stop(Duration.ZERO);}catch(IOException expected) { }
            assertFalse(broken.isAlive());

            Path commandPath=root.resolve("interactive-command");
            OwnedProcess command=OwnedProcess.startInteractive(backend,interactive(commandPath,
                "IFS= read -r command; [ \"$command\" = 'server shutdown 1' ] || exit 9; printf command-received > receipt"),new WorldConsoleShutdown());owned.add(command);
            command.stop(Duration.ofSeconds(3));assertFalse(command.wasForced());assertEquals(0,command.exitCode());assertNull(command.failure());
            assertEquals("command-received",read(commandPath.resolve("receipt")));
            assertEquals(0,Files.size(commandPath.resolve("stdout.log")));assertEquals(0,Files.size(commandPath.resolve("stderr.log")));

            JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-native-owner-system-shell")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("api",Build.VERSION.SDK_INT).put("targetSdk",context.getApplicationInfo().targetSdkVersion)
                .put("fingerprint",Build.FINGERPRINT).put("abi","x86_64").put("groupsPassed",9).put("nativeOwnerExecuted",true)
                .put("unicodeAndExitVerified",true).put("creatorThreadLifetimeVerified",true).put("gracefulFixtureVerified",true)
                .put("forcedAndFailedRequestVisible",true).put("bothPipeBoundsVerified",true).put("failedExecRejected",true)
                .put("interactiveBinaryEofVerified",true).put("interactiveBackpressureAndCloseVerified",true)
                .put("interactiveEpipeVerified",true).put("consoleCommandFixtureVerified",true)
                .put("logReadBytesPerPipe",9000000).put("logStoredBytesPerPipe",8388608)
                .put("worldShutdownQualified",false).put("characterPersistenceQualified",false)
                .put("appDeathQualified",false).put("arm64GuestExecuted",false).put("androidProotExecuted",false).put("gameplayQualified",false);
            write(context.getFilesDir().toPath().resolve("native-owner-qualification.json"),receipt.toString(2));
        } finally {
            for (OwnedProcess child:owned) if (child.isAlive()) try { child.stop(Duration.ZERO); } catch (IOException cleanup) { /* Failure remains visible in test output. */ }
            try (java.util.stream.Stream<Path> paths=Files.walk(root)) {
                for (Path path:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator) Files.delete(path);
            }
        }
    }
}
