package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.PixelFormat;
import android.media.Image;
import android.media.ImageReader;
import android.os.Bundle;
import android.os.SystemClock;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

/** Explicit internal runner only; uses existing private real content/shaders.
 * The default component/emulator suite skips this. Images are evidence to
 * inspect, not automatically accepted title/login/CommonMain qualification.
 * No import, download, extraction, database start or source substitution.
 */
@RunWith(AndroidJUnit4.class)
public final class RealClientStartupCaptureTest {
    @Test public void capturesRealClientForInspection()throws Exception {
        Bundle args=InstrumentationRegistry.getArguments();
        assumeTrue("Explicit real-client capture was not selected",
            "true".equals(args.getString("esteria.realClientCapture")));
        assumeTrue("Full ARM64 provider build is unavailable",BuildConfig.CLIENT_RUNTIME_PACKAGED&&
            BuildConfig.GUEST_BRIDGES_PACKAGED&&BuildConfig.SHADER_TOOLS_PACKAGED&&BuildConfig.TURNIP_PACKAGED);
        assumeTrue("ARM64 device/runner is unavailable","arm64-v8a".equals(android.os.Build.SUPPORTED_ABIS[0]));
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        assumeTrue("Existing prepared game store is unavailable",Files.isDirectory(root.resolve("game")));
        assumeTrue("Prepared shader receipt is unavailable",Files.isRegularFile(root.resolve("state/shader-work/shaders/current")));
        Path output=Files.createTempDirectory(root,"real-client-capture-",
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        RuntimeSetup wine=new RuntimeSetup(context,root);
        ClientRuntimeSetup client=new ClientRuntimeSetup(context,root);
        GuestBridgeSetup bridges=new GuestBridgeSetup(context,root);
        ShaderToolsSetup tools=new ShaderToolsSetup(context,root);
        TurnipSetup turnip=new TurnipSetup(context,root);
        ShaderSetup.Result selected;
        try(ExclusiveFileLease imported=ExclusiveFileLease.acquire(root.resolve("game/import.lock"),"Import is active");
            ShaderSetup.Handle setup=ShaderSetup.begin(context,root,wine,tools,args.getString("esteria.locale","enUS"))) {
            selected=setup.selectPrepared(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        }
        AtomicReference<String> failure=new AtomicReference<>();
        ClientStartupSession owner=ClientStartupSession.begin(context,root,wine,client,bridges,tools,selected,turnip,
            new io.github.russianranger.esteria.presentation.ClientPresentationSession.Events(){
                public void frameSize(int width,int height){ }
                public void failed(String reason){failure.compareAndSet(null,reason);}
            });
        JSONObject observation=new JSONObject().put("scope","real-client-capture-awaiting-inspection")
            .put("commonMainQualified",false).put("contentReadsQualified",false)
            .put("shaderLoadsQualified",false).put("titleFrameQualified",false).put("gameplayQualified",false);
        JSONArray captures=new JSONArray();long started=SystemClock.elapsedRealtime();
        Exception pending=null;
        try(ImageReader frames=ImageReader.newInstance(1280,720,PixelFormat.RGBA_8888,2)) {
            owner.start(RuntimeWork.NONE,()->Thread.currentThread().isInterrupted()||SystemClock.elapsedRealtime()-started>=300000);
            observation.put("selection",new JSONObject(owner.selection()));
            owner.presentation().surface().attach(frames.getSurface());
            // Bound the experiment after admission. Keep exact production resolution.
            long captureStart=SystemClock.elapsedRealtime();int[] seconds={5,15,30};int next=0;
            while(next<seconds.length&&SystemClock.elapsedRealtime()-captureStart<45000) {
                if(failure.get()!=null)throw new IOException("Presentation failed: "+failure.get());
                if(!owner.isClientAlive())throw new IOException("Reconstructed client exited before capture completed");
                try(Image image=frames.acquireLatestImage()) {
                    if(image!=null&&SystemClock.elapsedRealtime()-captureStart>=seconds[next]*1000L) {
                        Path file=output.resolve("frame-"+seconds[next]+"s.png");save(image,file);
                        captures.put(new JSONObject().put("file",file.getFileName().toString())
                            .put("elapsedMs",SystemClock.elapsedRealtime()-captureStart).put("sha256",hash(file)));
                        next++;
                    }
                }
                Thread.sleep(50);
            }
            if(next!=3)throw new IOException("Capture transport did not supply three frames; no title success inferred");
            owner.presentation().surface().detach();
        }catch(Exception error){pending=error;throw error;}
        finally {
            try{owner.close(Duration.ofSeconds(30));}
            catch(Exception cleanup){if(pending!=null)pending.addSuppressed(cleanup);else pending=cleanup;}
            observation.put("elapsedMs",SystemClock.elapsedRealtime()-started).put("captures",captures)
                .put("closed",owner.state()==ClientStartupSession.State.CLOSED).put("forcedCleanup",owner.wasForced())
                .put("executionFailure",pending==null?JSONObject.NULL:pending.getClass().getSimpleName());
            JSONObject logs=new JSONObject();
            for(var entry:owner.diagnosticLogs().entrySet())logs.put(entry.getKey(),root.relativize(entry.getValue()).toString());
            observation.put("diagnosticLogs",logs);
            Files.write(output.resolve("observation.json"),observation.toString(2).getBytes(java.nio.charset.StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
            Bundle status=new Bundle();status.putString("stream","REAL_CLIENT_CAPTURE="+output.getFileName()+"\n");
            InstrumentationRegistry.getInstrumentation().sendStatus(2,status);
        }
        if(pending!=null)throw pending;
    }
    private static void save(Image image,Path path)throws IOException {
        Image.Plane plane=image.getPlanes()[0];int stride=plane.getRowStride(),pixel=plane.getPixelStride();
        if(pixel!=4||image.getWidth()!=1280||image.getHeight()!=720||stride<pixel*image.getWidth())
            throw new IOException("Unexpected real-client frame layout");
        // The final row need not include trailing stride padding in ImageReader.
        java.nio.ByteBuffer source=plane.getBuffer().duplicate(),pixels=java.nio.ByteBuffer.allocateDirect(1280*720*4);
        byte[] row=new byte[1280*4];
        for(int y=0;y<720;y++) {
            if((long)y*stride+row.length>source.limit())throw new IOException("Truncated real-client frame");
            source.position(y*stride);source.get(row);pixels.put(row);
        }
        pixels.flip();Bitmap bitmap=Bitmap.createBitmap(1280,720,Bitmap.Config.ARGB_8888);
        try {
            bitmap.copyPixelsFromBuffer(pixels);
            try(var stream=Files.newOutputStream(path,StandardOpenOption.CREATE_NEW)) {
                if(!bitmap.compress(Bitmap.CompressFormat.PNG,100,stream))throw new IOException("Frame encoding failed");
            }
        }finally{bitmap.recycle();}
    }
    private static String hash(Path file)throws Exception {
        var digest=java.security.MessageDigest.getInstance("SHA-256");
        try(var input=Files.newInputStream(file)){byte[] buffer=new byte[65536];for(int n;(n=input.read(buffer))!=-1;)digest.update(buffer,0,n);}
        StringBuilder result=new StringBuilder();for(byte value:digest.digest())result.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return result.toString();
    }
}
