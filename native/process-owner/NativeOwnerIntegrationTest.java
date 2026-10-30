package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/** Real Linux JVM/JNI child tests. Shell scripts are test fixtures only. */
public final class NativeOwnerIntegrationTest {
    static void check(boolean condition,String message) { if (!condition) throw new AssertionError(message); }
    static OwnedProcess.Specification spec(Path path,List<String> arguments) throws IOException {
        Files.createDirectories(path);
        return new OwnedProcess.Specification(Path.of("/bin/sh"),arguments,Map.of("PATH","/usr/bin:/bin"),
            path,path.resolve("out"),path.resolve("err"));
    }
    static void done(OwnedProcess process) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(10);
        while (process.isAlive() && System.nanoTime()<deadline) Thread.sleep(5);
        check(!process.isAlive(),"Owned process did not complete");
    }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory("esteria-jni-🌍-").toRealPath();
        try {
            NativeProcessBridge backend=new NativeProcessBridge();
            OwnedProcess exit=OwnedProcess.start(backend,spec(root.resolve("utf8"),List.of("-c","printf '%s' \"$1\"; exit 7","test","🌍 café")),null);
            done(exit); check(exit.exitCode()==7 && exit.failure()==null,"nonzero exit status lost");
            check(Files.readString(root.resolve("utf8/out")).equals("🌍 café"),"JNI UTF-8 corrupted");
            check(exit.diagnostics()[0]==10 && exit.diagnostics()[1]==10,"log byte accounting differs");
            System.out.println("PASS JNI UTF-8, actual exit and byte accounting");

            Path graceful=root.resolve("graceful");
            AtomicReference<OwnedProcess> launched=new AtomicReference<>();
            Thread starter=new Thread(()->{
                try { launched.set(OwnedProcess.start(backend,spec(graceful,List.of("-c","while [ ! -f stop ]; do sleep .01; done; printf saved > saved")),
                        ()->Files.writeString(graceful.resolve("stop"),"stop"))); }
                catch (IOException e) { throw new AssertionError(e); }
            });
            starter.start(); starter.join(5000); check(!starter.isAlive() && launched.get()!=null,"launch did not return");
            Thread.sleep(150); check(launched.get().isAlive(),"child died with short-lived launch caller thread");
            launched.get().stop(Duration.ofSeconds(2));
            check(!launched.get().wasForced() && launched.get().exitCode()==0 && Files.readString(graceful.resolve("saved")).equals("saved"),"graceful fixture did not save");
            launched.get().stop(Duration.ZERO);
            System.out.println("PASS creator-thread lifetime, real graceful request and idempotent stop");

            OwnedProcess stubborn=OwnedProcess.start(backend,spec(root.resolve("forced"),List.of("-c","trap '' TERM; exec sleep 30")),()->{});
            try { stubborn.stop(Duration.ofMillis(80)); throw new AssertionError("forced shutdown reported success"); } catch (IOException expected) { }
            check(!stubborn.isAlive() && stubborn.wasForced(),"forced cleanup missing");
            System.out.println("PASS timeout force-stop is observable");

            OwnedProcess failing=OwnedProcess.start(backend,spec(root.resolve("failure"),List.of("-c","exec sleep 30")),()->{throw new IOException("request failed");});
            try { failing.stop(Duration.ofSeconds(2)); throw new AssertionError("failed shutdown reported success"); } catch (IOException expected) { }
            check(!failing.isAlive() && failing.wasForced(),"failed-request cleanup missing");
            System.out.println("PASS failed request cleanup");

            OwnedProcess loud=OwnedProcess.start(backend,spec(root.resolve("loud"),List.of("-c","head -c 10000000 /dev/zero; head -c 10000000 /dev/zero >&2")),null);
            done(loud); long[] data=loud.diagnostics();
            check(loud.failure()==null && loud.exitCode()==0 && data[0]==10000000 && data[2]==10000000 &&
                data[1]==8*1024*1024 && data[3]==8*1024*1024 && data[4]==0,"bounded pipes blocked or lost accounting");
            System.out.println("PASS both real log pipes drain past independent 8 MiB bounds");

            try {
                OwnedProcess.Specification missing=new OwnedProcess.Specification(Path.of("/missing/executable"),List.of(),Map.of(),root,root.resolve("missing-out"),root.resolve("missing-err"));
                OwnedProcess.start(backend,missing,null); throw new AssertionError("missing executable launched");
            } catch (IOException expected) { }
            System.out.println("PASS exec failure before handle publication");

            CountDownLatch created=new CountDownLatch(1); AtomicLong childHandle=new AtomicLong(); AtomicBoolean cancelled=new AtomicBoolean();
            OwnedProcess.Backend delayed=new OwnedProcess.Backend() {
                public long start(OwnedProcess.Specification item) throws IOException {
                    long handle=backend.start(item); childHandle.set(handle); created.countDown();
                    try { Thread.sleep(100); } catch (InterruptedException e) { throw new IOException(e); }
                    return handle;
                }
                public int waitFor(long handle,long timeout) throws IOException { return backend.waitFor(handle,timeout); }
                public int terminate(long handle) throws IOException { return backend.terminate(handle); }
                public long[] diagnostics(long handle) throws IOException { return backend.diagnostics(handle); }
            };
            Thread launching=new Thread(()->{
                try { OwnedProcess.start(delayed,spec(root.resolve("cancel"),List.of("-c","exec sleep 30")),null); }
                catch (IOException expected) { cancelled.set(Thread.currentThread().isInterrupted()); }
            });
            launching.start(); check(created.await(2,TimeUnit.SECONDS),"native child not created"); launching.interrupt(); launching.join(6000);
            check(!launching.isAlive() && cancelled.get() && backend.waitFor(childHandle.get(),0)!=OwnedProcess.RUNNING,"interrupted caller abandoned child");
            System.out.println("PASS launch interruption waits for real native cleanup and restores interrupt");

            Path fs=Files.createDirectory(root.resolve("rootfs")),work=Files.createDirectory(root.resolve("work")),tmp=Files.createDirectory(root.resolve("tmp")),logs=Files.createDirectory(root.resolve("logs"));
            Path executable=Path.of("/bin/true").toRealPath();
            var command=ProotLaunch.create(executable,executable,fs,work,tmp,logs,List.of("/opt/wine/bin/wine","a b;literal"),Map.of("WINEPREFIX","/work/prefix"));
            check(command.arguments.contains("--kill-on-exit") && command.arguments.contains("a b;literal") &&
                command.environment.size()==4 && command.arguments.contains("WINEPREFIX=/work/prefix"),"unsafe command/environment construction");
            Path inside=Files.createDirectory(fs.resolve("mutable"));
            try { ProotLaunch.create(executable,executable,fs,inside,tmp,logs,List.of("/bin/true"),Map.of()); throw new AssertionError("mutable runtime state accepted"); }
            catch (IOException expected) { }
            Path linked=root.resolve("alias"); Files.createSymbolicLink(linked,work);
            try { ProotLaunch.create(executable,executable,fs,linked,tmp,logs,List.of("/bin/true"),Map.of()); throw new AssertionError("symlink process directory accepted"); }
            catch (IOException expected) { }
            System.out.println("PASS PRoot argv, explicit environment and persistent/runtime separation");
            check(NativeOwnerInputTests.run(backend,root)==4,"Input groups incomplete");
            System.out.println("Native JVM integration: 12 groups passed; Linux host only, not Android or guest execution");
        } finally {
            try (var paths=Files.walk(root)) { for (Path path:paths.sorted(java.util.Comparator.reverseOrder()).toList()) Files.delete(path); }
        }
    }
}
