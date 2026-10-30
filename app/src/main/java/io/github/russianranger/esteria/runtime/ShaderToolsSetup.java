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

/** Immutable source-backed shader tools. Installation alone executes no compiler. */
public final class ShaderToolsSetup {
    private static final String ARCHIVE="shader-tools/shader-tools-arm64.archive";
    private final AssetManager assets;
    private final Path store,cache;
    private final RuntimePackagePlan plan;
    private final String revision,wineArchive,manifestHash;
    private final long freshFreeBytes;
    public ShaderToolsSetup(Context context,Path privateRoot)throws IOException {
        if(!BuildConfig.SHADER_TOOLS_PACKAGED)throw new IOException("This build has no bundled shader tools");
        if(!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Shader tools require private canonical application storage");
        assets=context.getApplicationContext().getAssets();
        byte[] raw=asset("shader-tools/provider.json",65536);
        try {
            JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(proof.getInt("formatVersion")!=1||!"android-shader-tools-install-only".equals(proof.getString("scope"))||
               !"shader-tools-arm64".equals(proof.getString("packageKey"))||!proof.getBoolean("archiveVerified")||
               !proof.getBoolean("elfAbiInspected")||!proof.getBoolean("nativeCompilerFixtureQualified")||
               proof.getBoolean("androidRuntimeQualified")||proof.getBoolean("gameAssetShadersQualified")||
               proof.getBoolean("gameplayQualified")||!BuildConfig.SHADER_TOOLS_PIN.equals(proof.getString("inputLockSha256")))
                throw new IOException("Shader provider scope or source pin differs");
            revision=proof.getString("clientRevision");wineArchive=proof.getString("requiredWineArchiveSha256");
            manifestHash=proof.getString("toolManifestSha256");
            if(!revision.equals(BuildConfig.SHADER_TOOLS_REVISION)||!revision.matches("[0-9a-f]{40}")||
               !wineArchive.matches("[0-9a-f]{64}")||!manifestHash.matches("[0-9a-f]{64}")||
               !guestMount().equals(proof.getString("guestMount")))throw new IOException("Invalid shader provider identities");
            JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits"),required=proof.getJSONObject("requiredFiles");
            if(!ARCHIVE.equals(archive.getString("assetPath"))||!"shader-tools-arm64.tar.gz".equals(archive.getString("file")))
                throw new IOException("Invalid shader provider archive path");
            Map<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
            for(Iterator<String> names=required.keys();names.hasNext();) {
                String name=names.next();JSONObject pin=required.getJSONObject(name);
                files.put(name,new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"),pin.getString("sha256"),pin.optInt("elfMachine",0),0));
            }
            RuntimePackagePlan.RequiredFile compiler=files.get("tools/bin/glslangValidator"),manifest=files.get("tools/shader-tools.json");
            if(compiler==null||compiler.elfMachine!=183||manifest==null||!manifestHash.equals(manifest.sha256)||
               !files.containsKey("helpers/shader_generation.py")||!files.containsKey("provenance/bundle.json"))
                throw new IOException("Missing source-backed shader components");
            RuntimePackagePlan.Limits limits=new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),
                bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes"));
            plan=new RuntimePackagePlan("shader-tools-arm64",hash(raw),archive.getString("file"),archive.getLong("bytes"),
                archive.getString("sha256"),proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),limits,files);
            freshFreeBytes=proof.getLong("freshSetupFreeBytes");
            if(plan.expectedEntries!=files.size()||freshFreeBytes!=plan.archiveBytes+plan.expectedFileBytes+limits.maxMetadataBytes+(64L<<20))
                throw new IOException("Invalid shader storage reserve");
            byte[] receipt=asset("shader-tools/bundle.json",65536);
            if(!hash(receipt).equals(proof.getString("bundleReceiptSha256"))||
               !hash(receipt).equals(files.get("provenance/bundle.json").sha256))throw new IOException("Shader build receipt differs");
            JSONObject bundled=new JSONObject(new String(receipt,StandardCharsets.UTF_8));
            if(!revision.equals(bundled.getString("clientRevision"))||!wineArchive.equals(bundled.getString("wineRuntimeArchiveSha256")))
                throw new IOException("Shader compiler Wine ABI/source pin differs");
            store=privateRoot.resolve("runtimes/shader-tools-arm64");cache=privateRoot.resolve("runtime-embedded-cache/shader-tools-arm64");
            try(AssetFileDescriptor descriptor=assets.openFd(ARCHIVE)) {
                if(descriptor.getLength()!=plan.archiveBytes)throw new IOException("Shader archive is not stored as pinned APK bytes");
            }
        }catch(JSONException|IllegalArgumentException error){throw new IOException("Invalid bundled shader tools",error);}
    }
    public RuntimeInstaller.Result prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeInstaller installer=installer();
        if(installer.resolveCurrent(plan)!=null)return installer.install(cache.resolve("unused-completed-generation"),plan,progress,cancelled);
        Path archive=new EmbeddedArchiveCache(cache).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,this::openArchive,progress,cancelled);
        if(!Files.exists(store.resolve("staging").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS)&&
           !Files.exists(store.resolve("generations").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS)&&
           store.toFile().getUsableSpace()<freshFreeBytes-plan.archiveBytes)throw new IOException("Insufficient storage for shader tools");
        return installer.install(archive,plan,progress,cancelled);
    }
    public RuntimeInstaller installer()throws IOException{return new RuntimeInstaller(store);}
    public RuntimePackagePlan packagePlan(){return plan;}
    public Path current()throws IOException{return installer().resolveCurrent(plan);}
    public String generation(){return plan.generation;}
    public String revision(){return revision;}
    public String toolManifestSha256(){return manifestHash;}
    public String archiveSha256(){return plan.archiveSha256;}
    public static String guestMount(){return "/esteria-shader-tools";}
    public void requireWineArchive(String archive)throws IOException {
        if(!wineArchive.equals(archive))throw new IOException("Shader tools require a different pinned Wine runtime");
    }
    private InputStream openArchive(long offset)throws IOException {
        AssetFileDescriptor descriptor=assets.openFd(ARCHIVE);InputStream stream=null;
        try {
            if(offset<0||offset>plan.archiveBytes||descriptor.getLength()!=plan.archiveBytes)throw new IOException("Invalid shader archive resume offset");
            stream=descriptor.createInputStream();long remaining=offset;
            while(remaining>0){long count=stream.skip(remaining);if(count>0)remaining-=count;else if(stream.read()<0)throw new IOException("Truncated shader archive");else remaining--;}
            return stream;
        }catch(IOException|RuntimeException error){if(stream!=null)stream.close();else descriptor.close();throw error;}
    }
    private byte[] asset(String name,int maximum)throws IOException {
        try(InputStream input=assets.open(name);ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=input.read(buffer))!=-1;){
                if(output.size()+count>maximum)throw new IOException("Shader metadata exceeds bound");output.write(buffer,0,count);}
            return output.toByteArray();
        }
    }
    private static String hash(byte[] bytes)throws IOException {
        try{StringBuilder out=new StringBuilder(64);for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))
                out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();}
        catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
}
