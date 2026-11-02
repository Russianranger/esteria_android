package io.github.russianranger.esteria;

import android.Manifest;
import android.app.Activity;
import android.app.Instrumentation;
import android.content.ComponentCallbacks2;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Build;
import android.widget.Spinner;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.runtime.install.PreparationSpeed;
import io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy;
import io.github.russianranger.esteria.core.runtime.install.RuntimeStorageMaintenance;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.Callable;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real launcher widgets, Android diagnostics and app-private filesystem fixtures.
 * No owner data, PRoot, extractor, GPU, low-memory kill or gameplay runs here. */
@RunWith(AndroidJUnit4.class)
@SuppressWarnings("deprecation")
public final class PreparationControlsTest {
    private final Instrumentation instrumentation=InstrumentationRegistry.getInstrumentation();
    private final Context context=instrumentation.getTargetContext();
    private static final String A="a".repeat(64),B="b".repeat(64),C="c".repeat(64),D="d".repeat(64);

    private <T> T ui(Callable<T> call) {
        AtomicReference<T> result=new AtomicReference<>();AtomicReference<Throwable> failure=new AtomicReference<>();
        instrumentation.runOnMainSync(()->{try{result.set(call.call());}catch(Throwable error){failure.set(error);}});
        if(failure.get()!=null)throw new AssertionError("Android preparation UI assertion failed",failure.get());
        return result.get();
    }
    private void waitFor(Callable<Boolean> condition,String reason)throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(8);
        while(!condition.call()&&System.nanoTime()<deadline)Thread.sleep(20);
        assertTrue(reason,condition.call());
    }
    private void observation(String method,Map<String,Object> details)throws Exception {
        JSONObject result=new JSONObject(details);result.put("case",method);
        result.put("scope","android13-x64-preparation-controls-fixture");
        result.put("ownerGameData",false);result.put("thorQualified",false);result.put("gameplayQualified",false);
        Bundle bundle=new Bundle();bundle.putString("stream","PREPARATION_CONTROLS="+result+"\n");
        instrumentation.sendStatus(2,bundle);
    }
    private Activity open() {
        return instrumentation.startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
    }
    private void close(Activity activity)throws Exception {
        if(activity!=null){ui(()->{activity.finish();return null;});waitFor(()->ui(activity::isDestroyed),"Launcher must finish before reopening");}
    }
    @Test public void selectedSpeedSurvivesActivityRecreationWithoutStartingPreparation()throws Exception {
        assertEquals(33,Build.VERSION.SDK_INT);
        instrumentation.getUiAutomation().grantRuntimePermission(context.getPackageName(),Manifest.permission.POST_NOTIFICATIONS);
        SharedPreferences preferences=context.getSharedPreferences("preparation",Context.MODE_PRIVATE);
        boolean existed=preferences.contains("speed");String saved=preferences.getString("speed",null);
        SharedPreferences session=context.getSharedPreferences("session",Context.MODE_PRIVATE);
        String operationBefore=session.getString("operation","");
        Activity activity=null;
        try {
            assertTrue(preferences.edit().remove("speed").commit());
            activity=open();final Activity initial=activity;
            Spinner spinner=ui(()->initial.findViewById(R.id.preparation_speed));
            assertNotNull("Preparation controls must be available even without providers in the emulator APK",spinner);
            assertEquals(3,ui(()->spinner.getAdapter().getCount()).intValue());
            assertEquals(PreparationSpeed.DEFAULT.label,ui(()->spinner.getSelectedItem()));
            for(PreparationSpeed speed:PreparationSpeed.values()) {
                ui(()->{spinner.setSelection(speed.ordinal());return null;});
                waitFor(()->speed.id.equals(preferences.getString("speed",null)),"Selected speed must reach durable launcher preferences");
            }
            close(activity);activity=null;
            activity=open();final Activity reopened=activity;
            assertEquals(PreparationSpeed.FAST.label,ui(()->((Spinner)reopened.findViewById(R.id.preparation_speed)).getSelectedItem()));
            assertEquals("Changing or reopening speed controls must not start another operation",operationBefore,session.getString("operation",""));
            observation("selectedSpeedSurvivesActivityRecreationWithoutStartingPreparation",Map.of(
                "visibleLevels",3,"defaultSpeed",PreparationSpeed.DEFAULT.id,"reopenedSpeed",PreparationSpeed.FAST.id,
                "operationUnchanged",true,"rates",Map.of("gentle",8L<<20,"balanced",32L<<20,"fast",64L<<20)));
        }finally {
            close(activity);
            SharedPreferences.Editor restore=preferences.edit();if(existed)restore.putString("speed",saved);else restore.remove("speed");
            assertTrue(restore.commit());
        }
    }
    @Test public void criticalTrimBacksOffWithHeadroomAndActualLowMemoryStillPauses()throws Exception {
        int critical=ImportIoController.trimPressure(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
        assertEquals(2,critical);
        assertEquals(1,ImportIoController.preparationPressureLevel(10L<<30,256L<<20,false,32L<<20,256L<<20,critical));
        assertEquals("Imports retain their existing conservative policy",2,
            ImportIoController.pressureLevel(10L<<30,256L<<20,false,32L<<20,256L<<20,critical));
        assertEquals(2,ImportIoController.preparationPressureLevel(128L<<20,256L<<20,false,32L<<20,256L<<20,critical));
        assertEquals(2,ImportIoController.preparationPressureLevel(10L<<30,256L<<20,true,32L<<20,256L<<20,critical));
        assertEquals(2,ImportIoController.preparationPressureLevel(10L<<30,256L<<20,false,240L<<20,256L<<20,critical));
        assertEquals(2,ImportIoController.preparationPressureLevel(-1,256L<<20,false,32L<<20,256L<<20,critical));
        Path root=Files.createTempDirectory(context.getCacheDir().getCanonicalFile().toPath(),"preparation-pressure-");
        try {
            Path receipt=root.resolve("preparation.properties");WorldPreparationDiagnostics diagnostics=new WorldPreparationDiagnostics(receipt);
            diagnostics.begin(SessionService.PREPARE_WORLD);
            ImportIoController controller=new ImportIoController(context,diagnostics,"Preparation",PreparationSpeed.BALANCED);
            controller.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);assertEquals(2,controller.recentTrimPressure());
            controller.recordFinal();Map<String,String> facts=new WorldPreparationDiagnostics(receipt).facts();
            assertEquals(Long.toString(32L<<20),facts.get("preparation.last.ioNormalBytesPerSecond"));
            assertEquals(Long.toString(2L<<20),facts.get("preparation.last.ioPressureBytesPerSecond"));
            assertEquals(Integer.toString(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL),facts.get("preparation.last.ioTrimLevel"));
            assertTrue(Long.parseLong(facts.get("preparation.last.ioMemoryAvailableBytes"))>0);
            observation("criticalTrimBacksOffWithHeadroomAndActualLowMemoryStillPauses",Map.of(
                "healthyCriticalTrimLevel",1,"realLowMemoryLevel",2,"unknownMemoryCriticalTrimLevel",2,
                "actualTrimRecorded",true,"selectedNormalBytesPerSecond",32L<<20,"pressureBytesPerSecond",2L<<20));
        }finally{remove(root);}
    }
    @Test public void workerPolicyScopeCarriesOnlySelectedSpeed()throws Exception {
        Map<String,String> input=Map.of("FIXTURE","preserved");AtomicReference<Map<String,String>> other=new AtomicReference<>();
        assertSame(input,RuntimeReadPolicy.preparationEnvironment(input));
        try(RuntimeReadPolicy.Scope selected=RuntimeReadPolicy.install((p,o,n)->{},PreparationSpeed.FAST)) {
            Map<String,String> output=RuntimeReadPolicy.preparationEnvironment(input);
            assertEquals("fast",output.get(PreparationSpeed.ENVIRONMENT_KEY));assertEquals("preserved",output.get("FIXTURE"));
            assertFalse("The original child environment stays unchanged",input.containsKey(PreparationSpeed.ENVIRONMENT_KEY));
            Thread worker=new Thread(()->other.set(RuntimeReadPolicy.preparationEnvironment(input)));worker.start();worker.join(1500);
            assertFalse(worker.isAlive());assertSame("An unrelated worker inherits no selected preparation policy",input,other.get());
            try(RuntimeReadPolicy.Scope nested=RuntimeReadPolicy.install((p,o,n)->{},PreparationSpeed.GENTLE)) {
                assertEquals("gentle",RuntimeReadPolicy.preparationEnvironment(input).get(PreparationSpeed.ENVIRONMENT_KEY));
            }
            assertEquals("fast",RuntimeReadPolicy.preparationEnvironment(input).get(PreparationSpeed.ENVIRONMENT_KEY));
        }
        assertSame("Closing the operation removes its selected child environment",input,RuntimeReadPolicy.preparationEnvironment(input));
        observation("workerPolicyScopeCarriesOnlySelectedSpeed",Map.of("workerScoped",true,"nestedSelectionRestored",true,
            "unrelatedWorkerUnaffected",true,"inputEnvironmentUnchanged",true,"afterCloseUnselected",true));
    }
    private static Path generation(Path runtime,String container,String generation,String bytes)throws Exception {
        Path at=Files.createDirectories(runtime.resolve(container).resolve(generation));Files.createDirectory(at.resolve("rootfs"));
        write(at.resolve("owner"),"esteria-runtime-stage-v1\n"+generation+"\n");
        write(at.resolve("complete"),"format=1\ngeneration="+generation+"\nsourcePin="+D+
            "\narchiveSha256="+D+"\ngameplayQualified=false\n");
        write(at.resolve("rootfs/payload.bin"),bytes);return at;
    }
    @Test public void storagePreviewAndTrimPreserveCurrentImportsSavesAndWorldWork()throws Exception {
        Path root=Files.createTempDirectory(context.getCacheDir().getCanonicalFile().toPath(),"preparation-storage-");
        Path outside=Files.createTempDirectory(context.getCacheDir().getCanonicalFile().toPath(),"preparation-outside-");
        try {
            Path runtime=Files.createDirectories(root.resolve("runtimes/wine-arm64"));
            Path current=generation(runtime,"generations",A,"current"),expected=generation(runtime,"generations",B,"expected");
            Path old=generation(runtime,"generations",C,"obsolete");
            write(runtime.resolve("current"),A+"\n");
            Path unknown=Files.createDirectories(runtime.resolve("generations").resolve(D));write(unknown.resolve("unknown"),"keep");
            Path imported=Files.createDirectories(root.resolve("game/generations/current/data")).resolve("fixture.mpq");write(imported,"import");
            Path database=Files.createDirectories(root.resolve("server-db/live")).resolve("sentinel");write(database,"save");
            Path world=Files.createDirectories(root.resolve("server-data-work/staging/current/navigation-in-progress/data/mmaps")).resolve("fixture.mmtile");write(world,"partial-owned-work");
            Path outsideFile=outside.resolve("untouched");write(outsideFile,"outside");Files.createSymbolicLink(old.resolve("rootfs/external-link"),outsideFile);
            Map<String,String> expectedGenerations=Map.of("wine-arm64",B);AtomicBoolean idle=new AtomicBoolean(true);
            RuntimeStorageMaintenance.Guard guard=()->{if(!idle.get())throw new IOException("Fixture operation is busy");};
            RuntimeStorageMaintenance.Report preview=RuntimeStorageMaintenance.scan(root,expectedGenerations,guard,()->false);
            assertTrue(preview.reclaimableBytes>0);assertEquals(1,preview.obsoleteGenerations);assertTrue(Files.exists(old));
            idle.set(false);
            try{RuntimeStorageMaintenance.trim(root,expectedGenerations,guard,()->false,(p,n,c,t)->{});fail("Busy app storage cannot be trimmed");}
            catch(IOException expectedBusy){assertTrue(Files.exists(old));}
            idle.set(true);
            RuntimeStorageMaintenance.Report trimmed=RuntimeStorageMaintenance.trim(root,expectedGenerations,guard,()->false,(p,n,c,t)->{});
            assertEquals(preview.reclaimableBytes,trimmed.removedBytes);assertFalse(Files.exists(old,LinkOption.NOFOLLOW_LINKS));
            assertEquals("current",read(current.resolve("rootfs/payload.bin")));assertEquals("expected",read(expected.resolve("rootfs/payload.bin")));
            assertEquals("keep",read(unknown.resolve("unknown")));assertEquals("import",read(imported));
            assertEquals("save",read(database));assertEquals("partial-owned-work",read(world));assertEquals("outside",read(outsideFile));
            RuntimeStorageMaintenance.Report after=RuntimeStorageMaintenance.scan(root,expectedGenerations,guard,()->false);assertEquals(0,after.reclaimableBytes);
            observation("storagePreviewAndTrimPreserveCurrentImportsSavesAndWorldWork",Map.of(
                "previewBytes",preview.reclaimableBytes,"removedBytes",trimmed.removedBytes,"afterReclaimableBytes",after.reclaimableBytes,
                "currentAndExpectedPreserved",true,"importSavesAndPartialWorldPreserved",true,"outsideSymlinkTargetPreserved",true,"busyRefused",true));
        }finally{remove(root);remove(outside);}
    }
    private static void write(Path path,String text)throws Exception {Files.write(path,text.getBytes(StandardCharsets.UTF_8));}
    private static String read(Path path)throws Exception {return new String(Files.readAllBytes(path),StandardCharsets.UTF_8);}
    private static void remove(Path root)throws Exception {
        if(!Files.exists(root,LinkOption.NOFOLLOW_LINKS))return;
        if(Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))try(java.nio.file.DirectoryStream<Path> children=Files.newDirectoryStream(root)){for(Path child:children)remove(child);}
        Files.delete(root);
    }
}
