package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import org.json.JSONException;
import org.json.JSONObject;

/** Optional immutable driver; preparation does not load it or select a GPU. */
public final class TurnipSetup {
    private static final String ARCHIVE="turnip/turnip-arm64.archive";
    private final AssetManager assets;
    private final Path store,cache;
    private final RuntimePackagePlan plan;
    private final String wineArchive;
    private final long freshFreeBytes;
    public TurnipSetup(Context context,Path privateRoot)throws IOException {
        if(!BuildConfig.TURNIP_PACKAGED)throw new IOException("This build has no optional Turnip provider");
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Turnip setup requires private canonical application storage");
        assets=context.getApplicationContext().getAssets();byte[] raw=asset("turnip/provider.json",65536);
        try {
            JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(proof.getInt("formatVersion")!=1||!"android-turnip-kgsl-install-only".equals(proof.getString("scope"))||
                !"turnip-arm64".equals(proof.getString("packageKey"))||!proof.getBoolean("archiveVerified")||
                !proof.getBoolean("elfAbiInspected")||!proof.getBoolean("nativeNoGpuQualified")||
                !proof.getBoolean("sourceCompanionRequired")||proof.getBoolean("hardwareQualified")||
                proof.getBoolean("androidRuntimeQualified")||proof.getBoolean("x11PresentationQualified")||proof.getBoolean("gameplayQualified")||
                !BuildConfig.TURNIP_PIN.equals(proof.getString("inputLockSha256"))||
                !BuildConfig.TURNIP_REVISION.equals(proof.getString("integrationRevision")))
                throw new IOException("Turnip provider scope or source pin differs");
            wineArchive=proof.getString("requiredWineArchiveSha256");
            if(!wineArchive.matches("[0-9a-f]{64}")||!guestMount().equals(proof.getString("guestMount"))||
                !icdPath().equals(proof.getString("icdPath")))throw new IOException("Invalid Turnip paths or Wine identity");
            JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits"),required=proof.getJSONObject("requiredFiles");
            if(!ARCHIVE.equals(archive.getString("assetPath"))||!"turnip-arm64.tar.gz".equals(archive.getString("file")))
                throw new IOException("Invalid Turnip archive path");
            Map<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
            for(Iterator<String> names=required.keys();names.hasNext();) {
                String name=names.next();JSONObject pin=required.getJSONObject(name);
                files.put(name,new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"),pin.getString("sha256"),pin.optInt("elfMachine",0),0));
            }
            for(String name:new String[]{"lib/libvulkan_freedreno.so","bin/esteria-turnip-probe"})
                if(!files.containsKey(name)||files.get(name).elfMachine!=183)throw new IOException("Missing measured ARM64 Turnip component");
            for(String name:new String[]{"etc/turnip-icd.json","provenance/no-gpu-check.json","provenance/no-gpu-probe.json",
                    "provenance/build-recipe/sources.lock.json","provenance/source-manifest.json","notices/MESA-LICENSE.rst"})
                if(!files.containsKey(name))throw new IOException("Missing Turnip source or evidence component");
            RuntimePackagePlan.RequiredFile build=files.get("provenance/turnip-build.json");
            if(build==null||!build.sha256.equals(proof.getString("buildReceiptSha256")))throw new IOException("Turnip build receipt differs");
            RuntimePackagePlan.Limits limits=new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),
                bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes"));
            plan=new RuntimePackagePlan("turnip-arm64",hash(raw),archive.getString("file"),archive.getLong("bytes"),archive.getString("sha256"),
                proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),limits,files);
            freshFreeBytes=proof.getLong("freshSetupFreeBytes");
            if(plan.expectedEntries!=files.size()||freshFreeBytes!=plan.archiveBytes+plan.expectedFileBytes+limits.maxMetadataBytes+(64L<<20))
                throw new IOException("Invalid Turnip storage reserve");
            store=privateRoot.resolve("runtimes/turnip-arm64");cache=privateRoot.resolve("runtime-embedded-cache/turnip-arm64");
            try(AssetFileDescriptor descriptor=assets.openFd(ARCHIVE)) {
                if(descriptor.getLength()!=plan.archiveBytes)throw new IOException("Turnip archive is not stored as pinned APK bytes");
            }
        }catch(JSONException|IllegalArgumentException error){throw new IOException("Invalid Turnip provider metadata",error);}
    }
    public RuntimeInstaller.Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeInstaller installer=new RuntimeInstaller(store);
        if(installer.resolveCurrent(plan)!=null)return installer.install(cache.resolve("unused-completed-generation"),plan,progress,cancelled);
        Path archive=new EmbeddedArchiveCache(cache).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,this::openArchive,progress,cancelled);
        if(!Files.exists(store.resolve("staging").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS)&&
            !Files.exists(store.resolve("generations").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS)&&
            store.toFile().getUsableSpace()<freshFreeBytes-plan.archiveBytes)throw new IOException("Insufficient storage for Turnip runtime");
        return installer.install(archive,plan,progress,cancelled);
    }
    public Path current()throws IOException{return new RuntimeInstaller(store).resolveCurrent(plan);}
    public String generation(){return plan.generation;}
    public String archiveSha256(){return plan.archiveSha256;}
    public RuntimePackagePlan packagePlan(){return plan;}
    public static String guestMount(){return "/esteria-turnip";}
    public static String icdPath(){return "/esteria-turnip/etc/turnip-icd.json";}
    public void requireWineArchive(String actual)throws IOException {
        if(!wineArchive.equals(actual))throw new IOException("Turnip requires a different pinned Wine runtime");
    }
    /** Explicit opt-in contract; does not launch a probe or prove hardware works.
     * Callers retain the standard Wine library path and add the separate mount.
     * These variables are intended for the sanitized /usr/bin/env -i guest only.
     */
    public Map<String,String> selectedEnvironment(String actualWineArchive)throws IOException {
        requireWineArchive(actualWineArchive);if(current()==null)throw new IOException("Turnip generation is not prepared");
        return Map.of("VK_DRIVER_FILES",icdPath(),"VK_ICD_FILENAMES",icdPath(),"MESA_VK_WSI_DEBUG","sw",
            "VK_LAYER_PATH",guestMount()+"/no-layers","VK_IMPLICIT_LAYER_PATH",guestMount()+"/no-layers",
            "VK_LOADER_LAYERS_DISABLE","~all~");
    }
    private InputStream openArchive(long offset)throws IOException {
        AssetFileDescriptor descriptor=assets.openFd(ARCHIVE);InputStream stream=null;
        try {
            if(offset<0||offset>plan.archiveBytes||descriptor.getLength()!=plan.archiveBytes)throw new IOException("Invalid Turnip archive resume offset");
            stream=descriptor.createInputStream();long remaining=offset;
            while(remaining>0){long count=stream.skip(remaining);if(count>0)remaining-=count;else if(stream.read()<0)throw new IOException("Truncated Turnip archive");else remaining--;}
            return stream;
        }catch(IOException|RuntimeException error){if(stream!=null)stream.close();else descriptor.close();throw error;}
    }
    private byte[] asset(String name,int maximum)throws IOException {
        try(InputStream input=assets.open(name);ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=input.read(buffer))!=-1;){if(out.size()+count>maximum)throw new IOException("Turnip metadata exceeds bound");out.write(buffer,0,count);}return out.toByteArray();
        }
    }
    private static String hash(byte[] raw)throws IOException {
        try{StringBuilder text=new StringBuilder(64);for(byte b:MessageDigest.getInstance("SHA-256").digest(raw))text.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return text.toString();}
        catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
}
