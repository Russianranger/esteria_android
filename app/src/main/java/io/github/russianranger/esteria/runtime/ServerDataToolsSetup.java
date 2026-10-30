package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.install.ServerDataToolSelection;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Installs a distinct, source-qualified ordered2 plus original2 tool generation.
 * Neither installation nor native CLI checks establish conversion or world readiness. */
public final class ServerDataToolsSetup {
    private static final String ASSET="server-data-tools/server-data-tools.archive";
    private static final String ARCHIVE="server-data-tools-runtime-arm64.tar.gz";
    private static final Set<String> PROGRAMS=Set.of("map_extractor","vmap4_extractor","vmap4_assembler","mmaps_generator");
    private final AssetManager assets;
    private final RuntimePackagePlan plan;
    private final ServerDataToolSelection selection;
    private final Path store,cache;
    private final String dependencyArchive;
    private final long freshFreeBytes;

    public ServerDataToolsSetup(Context context,Path root)throws IOException {
        if(!BuildConfig.SERVER_DATA_TOOLS_PACKAGED)throw new IOException("This build has no sealed composed data-tools provider");
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical data-tools storage required");
        assets=context.getApplicationContext().getAssets();
        try {
            JSONObject proof=new JSONObject(new String(asset("server-data-tools/provider.json",131072),StandardCharsets.UTF_8));
            if(proof.getInt("formatVersion")!=1 || !"android-server-data-tools-install-only".equals(proof.getString("scope")) ||
                    !"server-data-tools-arm64".equals(proof.getString("packageKey")) ||
                    !BuildConfig.SERVER_DATA_TOOLS_PIN.equals(proof.getString("inputLockSha256")) ||
                    !guestMount().equals(proof.getString("guestMount")))throw new IOException("Composed data-tools package selection differs");
            for(String flag:Set.of("archiveVerified","elfAbiInspected","sourceCompanionRequired","sourceCompanionVerified",
                    "nativeArgumentConfigQualified","originalNoticesPreserved"))flag(proof,flag,true);
            for(String flag:Set.of("clientMpqConversionQualified","customEsteriaDataLoadOrderQualified","androidRuntimeQualified",
                    "gameLoginQualified","gameplayQualified"))flag(proof,flag,false);
            String source=ServerSourceSelection.verify(asset("sources.lock.json",65536),proof);
            if(!ServerDataToolSelection.CLIENT_REVISION.equals(proof.getString("clientRevision")) ||
                    !ServerDataToolSelection.SERVER_REVISION.equals(proof.getString("serverRevision")))throw new IOException("Data tool source revisions differ");
            dependencyArchive=proof.getString("requiredServerRuntimeArchiveSha256");hash(dependencyArchive);
            JSONObject ordered=proof.getJSONObject("actualOrderedSourceQualification");
            for(String name:Set.of("archive","receipt","nativeBuild","dependencyObservation"))identity(ordered.getJSONObject(name));
            JSONObject original=proof.getJSONObject("originalServerSourceQualification");
            for(String name:Set.of("archive","receipt","qualification"))identity(original.getJSONObject(name));
            identity(proof.getJSONObject("nativeCliReceipt"));identity(proof.getJSONObject("packageReceipt"));
            JSONArray names=proof.getJSONArray("programNames");Set<String> selected=new java.util.HashSet<>();
            for(int i=0;i<names.length();i++)if(!selected.add(names.getString(i)))throw new IOException("Duplicate data tool role");
            if(!selected.equals(PROGRAMS))throw new IOException("Complete four-tool data selection required");
            JSONObject files=proof.getJSONObject("requiredFiles");Map<String,RuntimePackagePlan.RequiredFile> required=new TreeMap<>();
            int notices=0;
            for(var keys=files.keys();keys.hasNext();) {
                String name=keys.next();JSONObject item=files.getJSONObject(name);identity(item);
                int machine=PROGRAMS.stream().anyMatch(p->name.equals("bin/"+p))?183:0;
                if(name.startsWith("notices/"))notices++;
                required.put(name,new RuntimePackagePlan.RequiredFile(item.getLong("bytes"),item.getString("sha256"),machine,0));
            }
            if(notices<66)throw new IOException("Original server notices are incomplete");
            JSONObject pairs=proof.getJSONObject("programPairs");
            if(pairs.length()!=4)throw new IOException("Paired data tool debug identities differ");
            for(String name:PROGRAMS) {
                JSONObject pair=pairs.getJSONObject(name);
                for(String role:Set.of("original","stripped","debug"))identity(pair.getJSONObject(role));
                pinned(required,"bin/"+name,pair.getJSONObject("stripped"));
            }
            JSONObject configuration=proof.getJSONObject("configuration");identity(configuration);
            if(!"etc/mmaps-config.yaml".equals(configuration.getString("installedPath")))throw new IOException("Data configuration path differs");
            pinned(required,"etc/mmaps-config.yaml",configuration);
            pinned(required,"provenance/ordered-source-receipt.json",ordered.getJSONObject("receipt"));
            JSONObject tools=proof.getJSONObject("toolSelection"),toolFiles=tools.getJSONObject("files");
            if(tools.length()!=5 || tools.getInt("formatVersion")!=1 || toolFiles.length()!=6)throw new IOException("Data tool selection shape differs");
            Map<String,RuntimePackagePlan.RequiredFile> selectedFiles=new TreeMap<>();
            for(var keys=toolFiles.keys();keys.hasNext();) {
                String name=keys.next();JSONObject item=toolFiles.getJSONObject(name);identity(item);
                pinned(required,name,item);selectedFiles.put(name,required.get(name));
            }
            pinned(required,"provenance/ordered-source-receipt.json",tools.getJSONObject("orderedSourceReceipt"));
            selection=new ServerDataToolSelection(tools.getString("clientRevision"),tools.getString("serverRevision"),selectedFiles,
                required.get("provenance/ordered-source-receipt.json"));
            JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits");
            if(!ASSET.equals(archive.getString("assetPath")) || !ARCHIVE.equals(archive.getString("file")))throw new IOException("Data tool archive path differs");
            RuntimePackagePlan.Limits limits=new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),
                bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes"));
            plan=new RuntimePackagePlan("server-data-tools-arm64",source,ARCHIVE,archive.getLong("bytes"),archive.getString("sha256"),
                proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),limits,required);
            freshFreeBytes=proof.getLong("freshSetupFreeBytes");
            if(plan.expectedEntries!=required.size() || freshFreeBytes!=plan.archiveBytes+plan.expectedFileBytes+limits.maxMetadataBytes+(64L<<20))
                throw new IOException("Data tool archive inventory/reserve differs");
            store=root.resolve("runtimes/server-data-tools-arm64");cache=root.resolve("runtime-embedded-cache/server-data-tools-arm64");
            try(AssetFileDescriptor descriptor=assets.openFd(ASSET)) {
                if(descriptor.getLength()!=plan.archiveBytes)throw new IOException("Data tool archive is not stored as pinned APK bytes");
            }
        }catch(JSONException|IllegalArgumentException error){throw new IOException("Invalid sealed data-tools provider metadata",error);}
    }

    public RuntimeInstaller.Result prepare(String dependency,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        requireServerRuntimeArchive(dependency);RuntimeInstaller installer=installer();
        if(installer.resolveCurrent(plan)!=null)return installer.install(cache.resolve("unused-completed-generation"),plan,progress,cancelled);
        Path archive=new EmbeddedArchiveCache(cache).obtain(plan.archiveName,plan.archiveBytes,plan.archiveSha256,this::openArchive,progress,cancelled);
        if(!Files.exists(store.resolve("staging").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(store.resolve("generations").resolve(plan.generation),LinkOption.NOFOLLOW_LINKS) &&
                store.toFile().getUsableSpace()<freshFreeBytes-plan.archiveBytes)throw new IOException("Insufficient storage for data tools");
        return installer.install(archive,plan,progress,cancelled);
    }
    public RuntimeInstaller installer()throws IOException{return new RuntimeInstaller(store);}
    public RuntimePackagePlan packagePlan(){return plan;}
    public Path current()throws IOException{return installer().resolveCurrent(plan);}
    public ServerDataToolSelection selection(){return selection;}
    public String archiveSha256(){return plan.archiveSha256;}
    public String sourceLockSha256(){return plan.sourcePinSha256;}
    public static String guestMount(){return "/esteria-server-extractors";}
    public void requireServerRuntimeArchive(String actual)throws IOException {
        if(!dependencyArchive.equals(actual))throw new IOException("Data tools require another Ubuntu dependency generation");
    }
    private InputStream openArchive(long offset)throws IOException {
        AssetFileDescriptor descriptor=assets.openFd(ASSET);InputStream stream=null;
        try {
            if(offset<0||offset>plan.archiveBytes||descriptor.getLength()!=plan.archiveBytes)throw new IOException("Invalid data tool archive resume offset");
            stream=descriptor.createInputStream();long remaining=offset;
            while(remaining>0){long n=stream.skip(remaining);if(n>0)remaining-=n;else if(stream.read()<0)throw new IOException("Truncated data tool archive");else remaining--;}
            return stream;
        }catch(IOException|RuntimeException error){if(stream!=null)stream.close();else descriptor.close();throw error;}
    }
    private byte[] asset(String name,int maximum)throws IOException {
        try(InputStream input=assets.open(name);ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];for(int count;(count=input.read(buffer))!=-1;){if(output.size()+count>maximum)throw new IOException("Data tool metadata exceeds bound");output.write(buffer,0,count);}return output.toByteArray();
        }
    }
    private static void flag(JSONObject object,String name,boolean expected)throws JSONException,IOException {
        if(!(object.get(name) instanceof Boolean)||object.getBoolean(name)!=expected)throw new IOException("Invalid data tool qualification scope");
    }
    private static void hash(String value)throws IOException{if(!value.matches("[0-9a-f]{64}"))throw new IOException("Invalid data tool digest");}
    private static void identity(JSONObject object)throws JSONException,IOException {
        Object bytes=object.get("bytes");if(!(bytes instanceof Integer||bytes instanceof Long)||object.getLong("bytes")<=0||object.getLong("bytes")>(4L<<30))throw new IOException("Invalid data tool identity");hash(object.getString("sha256"));
    }
    private static void pinned(Map<String,RuntimePackagePlan.RequiredFile> files,String name,JSONObject identity)throws JSONException,IOException {
        RuntimePackagePlan.RequiredFile file=files.get(name);if(file==null||file.bytes!=identity.getLong("bytes")||!file.sha256.equals(identity.getString("sha256")))throw new IOException("Data tool provenance/pair identity differs");
    }
}
