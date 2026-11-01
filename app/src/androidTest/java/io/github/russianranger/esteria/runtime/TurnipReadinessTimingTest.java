package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.importer.ImportIoGovernor;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.TurnipAdmissionReadFixture;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.TurnipProbeContract;
import java.io.IOException;
import java.io.OutputStream;
import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Production Handle timing/cleanup with real Android JNI children. Input bytes,
 * shell commands and JSON receipts are synthetic fixtures; no PRoot, Vulkan,
 * driver, owner assets or hardware qualification is performed. */
@RunWith(AndroidJUnit4.class)
public final class TurnipReadinessTimingTest {
    private static final long BUDGET_NANOS=TimeUnit.MILLISECONDS.toNanos(TurnipProbeContract.TIMEOUT_MILLIS);
    private static Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    private static void remove(Path root)throws Exception{
        try(var paths=Files.walk(root)){for(Path p:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(p);}
    }
    private static Field field(Class<?> type,String name)throws Exception{
        Field value=type.getDeclaredField(name);value.setAccessible(true);return value;
    }
    @SuppressWarnings("unchecked") private static Map<Path,TurnipReadinessProbe.Handle> owners()throws Exception{
        return (Map<Path,TurnipReadinessProbe.Handle>)field(TurnipReadinessProbe.class,"OWNERS").get(null);
    }
    private static TurnipReadinessProbe.Handle owner(Path root)throws Exception{
        Files.createDirectories(root);root=root.toRealPath();
        Path wine=Files.createDirectories(root.resolve("runtimes/wine")),driver=Files.createDirectories(root.resolve("runtimes/driver"));
        Path work=Files.createDirectories(root.resolve("state/turnip-probe-work/"+"a".repeat(32)));
        Path session=Files.createDirectories(root.resolve("state/turnip-probe-operations/"+"a".repeat(32)));
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(root.resolve("owner.lock"),"TEST_ONLY_TURNIP_BUSY");
        Constructor<TurnipReadinessProbe.Handle> constructor=TurnipReadinessProbe.Handle.class.getDeclaredConstructor(Context.class,Path.class,
            RuntimeSetup.class,TurnipSetup.class,Path.class,Path.class,Path.class,Path.class,ExclusiveFileLease.class);
        constructor.setAccessible(true);
        TurnipReadinessProbe.Handle result=constructor.newInstance(context().getApplicationContext(),root,null,null,wine,driver,work,session,lease);
        owners().put(root,result);return result;
    }
    private static OwnedProcess.Specification command(Path root,String script)throws IOException{
        Path work=Files.createDirectory(root.resolve("child"));
        return new OwnedProcess.Specification(Paths.get("/system/bin/sh"),List.of("-c",script),Map.of("PATH","/system/bin"),
            work,work.resolve("stdout.log"),work.resolve("stderr.log"));
    }
    private static OwnedProcess start(OwnedProcess.Specification spec)throws IOException{
        return OwnedProcess.start(new NativeProcessBridge(),spec,null);
    }
    private static void complete(OwnedProcess process)throws Exception{
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
        while(process.isAlive()&&System.nanoTime()<deadline)Thread.sleep(10);
        assertFalse("Actual fixture child must have exited",process.isAlive());assertNull(process.failure());
    }
    private static void leaseRetained(Path root,TurnipReadinessProbe.Handle owner)throws Exception{
        assertEquals(TurnipReadinessProbe.State.FAILED,owner.state());
        assertSame(owner,TurnipReadinessProbe.pendingCleanup(root));
        try(ExclusiveFileLease stolen=ExclusiveFileLease.acquire(root.resolve("owner.lock"),"TEST_ONLY_TURNIP_BUSY")){
            fail("Failed timing owner released its lease before close");
        }catch(IOException expected){assertEquals("TEST_ONLY_TURNIP_BUSY",expected.getMessage());}
    }
    private static String hex(byte[] bytes){StringBuilder value=new StringBuilder();for(byte b:bytes)value.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return value.toString();}
    private static String input(Path file)throws Exception{
        MessageDigest expected=MessageDigest.getInstance("SHA-256");byte[] block=new byte[128<<10];
        try(OutputStream out=Files.newOutputStream(file)){for(int i=0;i<384;i++){out.write(block);expected.update(block);}}
        return hex(expected.digest());
    }
    private static JSONObject receipt()throws Exception{
        return new JSONObject().put("formatVersion",2).put("scope","linux-arm64-turnip-kgsl-component-probe")
            .put("icdLoaded",true).put("noKgslHostVerified",false).put("turnip740ShaderReadbackQualified",true)
            .put("directIcdNoDevicesVerified",false).put("loaderEnumerationResult",0).put("pixelsVerified",4096)
            .put("vendorId",0x5143).put("deviceId",740).put("deviceName","TEST_ONLY Turnip Adreno740 receipt fixture")
            .put("x11PresentationQualified",false).put("androidQualified",false).put("gameplayQualified",false);
    }
    private static void refuseReceipt(Method read,Path path)throws Exception{
        try{read.invoke(null,path);fail("Altered synthetic component receipt was accepted");}
        catch(InvocationTargetException expected){assertTrue(expected.getCause() instanceof IOException);}
    }
    @Test public void governedAdmissionDoesNotSpendChildWindowAndFailuresKeepOwnership()throws Exception{
        assertEquals(33,Build.VERSION.SDK_INT);
        Path root=Files.createTempDirectory(context().getFilesDir().toPath(),"turnip-timing-").toRealPath();
        java.util.ArrayList<TurnipReadinessProbe.Handle> retained=new java.util.ArrayList<>();
        java.util.ArrayList<OwnedProcess> children=new java.util.ArrayList<>();
        long admissionMillis=0,childMillis=0;
        try{
            Path slow=Files.createDirectory(root.resolve("slow")),source=slow.resolve("provider.bin");String expected=input(source);
            TurnipReadinessProbe.Handle owner=owner(slow);retained.add(owner);
            AtomicLong observed=new AtomicLong(),admissionNanos=new AtomicLong();
            ImportIoGovernor governor=new ImportIoGovernor(8L<<20,2L<<20,()->0,(p,o,n)->{});
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{observed.addAndGet(count);governor.read(count,()->false);})){
                childMillis=owner.runPrepared(()->{
                    long began=System.nanoTime();
                    assertEquals(expected,TurnipAdmissionReadFixture.hash(source,48L<<20,RuntimeWork.NEVER_CANCELLED));
                    admissionNanos.set(System.nanoTime()-began);
                    return command(slow,"exit 0");
                },spec->{OwnedProcess child=start(spec);children.add(child);return child;},System::nanoTime,RuntimeWork.NEVER_CANCELLED);
            }
            admissionMillis=TimeUnit.NANOSECONDS.toMillis(admissionNanos.get());
            assertTrue("Real 48MiB paced verification must exceed the five-second child budget",admissionNanos.get()>BUDGET_NANOS);
            assertEquals(48L<<20,observed.get());assertTrue(childMillis<TurnipProbeContract.TIMEOUT_MILLIS);
            assertEquals(0,children.get(children.size()-1).exitCode());owner.close(Duration.ZERO);

            Path cancelledRoot=Files.createDirectory(root.resolve("cancelled"));owner=owner(cancelledRoot);retained.add(owner);
            AtomicBoolean cancelled=new AtomicBoolean();AtomicInteger launches=new AtomicInteger();
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{cancelled.set(true);throw new RuntimeWork.CancelledException();})){
                try{
                    owner.runPrepared(()->{TurnipAdmissionReadFixture.hash(source,48L<<20,RuntimeWork.NEVER_CANCELLED);return command(cancelledRoot,"exit 0");},spec->{launches.incrementAndGet();return start(spec);},System::nanoTime,cancelled::get);
                    fail("Cancellation during admission launched a child");
                }catch(RuntimeWork.CancelledException expectedCancellation){}
            }
            assertEquals(0,launches.get());leaseRetained(cancelledRoot,owner);owner.close(Duration.ZERO);

            Path tamperedRoot=Files.createDirectory(root.resolve("tampered"));owner=owner(tamperedRoot);retained.add(owner);
            try(java.io.RandomAccessFile changed=new java.io.RandomAccessFile(source.toFile(),"rw")){changed.write(1);}
            AtomicInteger tamperedLaunches=new AtomicInteger();
            try{
                owner.runPrepared(()->{
                    if(!expected.equals(TurnipAdmissionReadFixture.hash(source,48L<<20,RuntimeWork.NEVER_CANCELLED)))throw new IOException("TEST_ONLY_PROVIDER_PIN_CHANGED");
                    return command(tamperedRoot,"exit 0");
                },spec->{tamperedLaunches.incrementAndGet();return start(spec);},System::nanoTime,RuntimeWork.NEVER_CANCELLED);
                fail("Changed provider bytes launched a child");
            }catch(IOException expectedFailure){assertEquals("TEST_ONLY_PROVIDER_PIN_CHANGED",expectedFailure.getMessage());}
            assertEquals(0,tamperedLaunches.get());leaseRetained(tamperedRoot,owner);owner.close(Duration.ZERO);

            Path hungRoot=Files.createDirectory(root.resolve("hung"));owner=owner(hungRoot);retained.add(owner);
            AtomicReference<OwnedProcess> hung=new AtomicReference<>();AtomicInteger ticks=new AtomicInteger();
            try{
                owner.runPrepared(()->command(hungRoot,"exec sleep 30"),spec->{OwnedProcess child=start(spec);hung.set(child);children.add(child);return child;},
                    ()->ticks.getAndIncrement()==0?0:BUDGET_NANOS,RuntimeWork.NEVER_CANCELLED);
                fail("Hung native child exceeded its finite budget");
            }catch(IOException expectedTimeout){assertTrue(expectedTimeout.getMessage().contains("exceeded"));}
            assertNotNull(hung.get());assertFalse("Timed-out native child must be reaped",hung.get().isAlive());
            leaseRetained(hungRoot,owner);owner.close(Duration.ZERO);

            Path launchRoot=Files.createDirectory(root.resolve("late-launch"));owner=owner(launchRoot);retained.add(owner);
            AtomicLong launchClock=new AtomicLong();AtomicReference<OwnedProcess> lateLaunch=new AtomicReference<>();
            try{
                owner.runPrepared(()->command(launchRoot,"exec sleep 30"),spec->{OwnedProcess child=start(spec);lateLaunch.set(child);children.add(child);launchClock.set(BUDGET_NANOS);return child;},launchClock::get,RuntimeWork.NEVER_CANCELLED);
                fail("Over-budget native launch was accepted");
            }catch(IOException expectedTimeout){assertTrue(expectedTimeout.getMessage().contains("exceeded"));}
            assertFalse(lateLaunch.get().isAlive());leaseRetained(launchRoot,owner);owner.close(Duration.ZERO);

            Path resultRoot=Files.createDirectory(root.resolve("late-result"));owner=owner(resultRoot);retained.add(owner);
            AtomicLong resultClock=new AtomicLong();AtomicReference<OwnedProcess> lateResult=new AtomicReference<>();
            try{
                owner.runPrepared(()->command(resultRoot,"exit 0"),spec->{OwnedProcess child=start(spec);lateResult.set(child);children.add(child);try{complete(child);}catch(Exception failure){throw new IOException(failure);}resultClock.set(BUDGET_NANOS+1);return child;},resultClock::get,RuntimeWork.NEVER_CANCELLED);
                fail("Over-budget completed result was accepted");
            }catch(IOException expectedTimeout){assertTrue(expectedTimeout.getMessage().contains("not accepted"));}
            assertFalse(lateResult.get().isAlive());assertEquals(0,lateResult.get().exitCode());leaseRetained(resultRoot,owner);owner.close(Duration.ZERO);

            Method read=TurnipReadinessProbe.class.getDeclaredMethod("readReceipt",Path.class);read.setAccessible(true);
            Path receipt=root.resolve("synthetic-receipt.json");Files.write(receipt,receipt().toString().getBytes(StandardCharsets.UTF_8));
            assertTrue(read.invoke(null,receipt) instanceof TurnipProbeContract.Receipt);
            Files.write(receipt,receipt().put("pixelsVerified",4095).toString().getBytes(StandardCharsets.UTF_8));refuseReceipt(read,receipt);
            Files.write(receipt,receipt().put("noKgslHostVerified",true).toString().getBytes(StandardCharsets.UTF_8));refuseReceipt(read,receipt);
            System.out.println("TURNIP_TIMING_FIXTURE="+new JSONObject().put("scope","android13-owned-turnip-timing-fixture-no-gpu")
                .put("governedAdmissionMillis",admissionMillis).put("childMillis",childMillis).put("governedBytes",48L<<20)
                .put("nativeFixtureChildExecuted",true).put("hungChildReaped",true).put("launchBudgetEnforced",true)
                .put("lateCompletedResultRejected",true).put("prelaunchCancellationVerified",true).put("providerAndReceiptMutationRejected",true)
                .put("gpuExecuted",false).put("androidArm64Qualified",false).put("thorQualified",false).put("gameplayQualified",false));
        }finally{
            for(OwnedProcess child:children)if(child.isAlive())try{child.terminateAuxiliary();}catch(IOException cleanup){}
            for(TurnipReadinessProbe.Handle owner:retained)if(owner.state()!=TurnipReadinessProbe.State.CLOSED)owner.close(Duration.ZERO);
            remove(root);
        }
    }
}
