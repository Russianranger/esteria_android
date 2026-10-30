package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.json.JSONException;
import org.json.JSONObject;

/** Test-APK-only typed selection. Its private constructor accepts no caller
 * path, pin or flag. Public ARM provider constructors remain unchanged. */
final class InstallationX64Inputs implements ServerInstallationSetup.InstalledInputs {
    private static final String PREFIX="installation-probe/";
    private static final Set<String> HELPERS=Set.of("android_server_installation_setup.py","android_server_schema_setup.py",
        "mysql_bootstrap.py","mysql_service.py","server_content.py","server_schema_setup.py","server_schema_baseline.py",
        "server_schema_adaptations.py","server_update_setup.py","server_updater.py","server_playerbots_setup.py","owned_process_group.py","server_config.py",
        "provision_local_realm.py","provision_local_account.py","server/appearance-schema-v1.sql","server/appearance-schema.lock.json",
        "local-server.json","installation_x64_entry.py","installation-x64-inputs.json");
    private final Context context;
    private final Path root;
    private final JSONObject descriptor,content,programs;
    private final String descriptorHash;
    private final RuntimePackagePlan runtimePlan,programsPlan,contentPlan;
    private final RuntimeInstaller runtimeInstaller,programsInstaller,contentInstaller;
    private final ProotProcess.QualificationPayload payload;
    private Path receipt;
    private final ServerDatabaseService.InstallationRuntime runtime;

    static InstallationX64Inputs install(Context context)throws IOException {
        InstallationX64Inputs selected=new InstallationX64Inputs(context);
        selected.prepare(selected.runtimeInstaller,selected.runtimePlan,"mysql-probe/mysql-x86-64.archive");
        selected.prepare(selected.programsInstaller,selected.programsPlan,PREFIX+"programs.archive");
        selected.prepare(selected.contentInstaller,selected.contentPlan,PREFIX+"content.archive");
        try {
            JSONObject pin=selected.content.getJSONObject("receipt");
            selected.receipt=new EmbeddedArchiveCache(selected.root.resolve("runtime-embedded-cache/installation-content-receipt"))
                .obtain("content-receipt.json",pin.getLong("bytes"),pin.getString("sha256"),
                    offset->selected.open(PREFIX+"content-receipt.json",offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        }catch(JSONException invalid){throw new IOException("Invalid selected content receipt",invalid);}
        selected.requireCurrentSelection();return selected;
    }
    private InstallationX64Inputs(Context supplied)throws IOException {
        require(BuildConfig.DEBUG&&BuildConfig.SERVER_INSTALLATION_PROBE_PACKAGED&&BuildConfig.MYSQL_PROBE_PACKAGED&&
            !BuildConfig.PROOT_PACKAGED&&!BuildConfig.SERVER_RUNTIME_PACKAGED&&
            !BuildConfig.SERVER_PROGRAMS_PACKAGED&&!BuildConfig.SERVER_CONTENT_PACKAGED&&Build.VERSION.SDK_INT==33&&
            Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"),"Separate measured Android13 x64 debug fixture required");
        context=supplied.getApplicationContext();root=context.getFilesDir().getCanonicalFile().toPath();
        byte[] raw=asset(PREFIX+"provider.json",128<<10);descriptorHash=hash(raw);
        require(descriptorHash.equals(BuildConfig.SERVER_INSTALLATION_PROBE_PIN),"Fixture descriptor differs from compiled selection");
        try {
            descriptor=json(raw);require(descriptor.getInt("formatVersion")==1&&
                "android-x86-64-server-installation-probe-only".equals(descriptor.getString("scope")),"Unexpected fixture scope");
            for(String flag:List.of("sqlExecuted","androidRuntimeQualified","productionArm64ProviderQualified","fourSchemaCoordinatorQualified",
                    "worldserverQualified","playerbotsAiQualified","gameplayQualified","slotPromoted","serverDataQualified"))require(!descriptor.getBoolean(flag),"Fixture input overclaims execution");
            verifyAssets();payload=ProotProcess.qualificationPayload(context);
            byte[] mysql=asset("mysql-probe/provider.json",128<<10);pinned(mysql,descriptor.getJSONObject("mysqlProvider"));
            JSONObject runtimeProof=json(mysql);require("android-13-x86-64-mysql-probe-build-only".equals(runtimeProof.getString("scope"))&&
                "x86_64".equals(runtimeProof.getString("architecture")),"Original x64 MySQL provider required");
            runtimePlan=plan(runtimeProof,mysql,"mysql-probe-x86-64","file");
            for(String name:List.of("usr/bin/python3.12","usr/bin/mysql","usr/sbin/mysqld"))
                require(runtimePlan.required.containsKey(name)&&runtimePlan.required.get(name).elfMachine==62,"Actual x64 runtime ELF required");
            byte[] programRaw=asset(PREFIX+"programs.json",2<<20);pinned(programRaw,descriptor.getJSONObject("programsDescriptor"));programs=json(programRaw);
            require("android-x64-installation-programs-only".equals(programs.getString("scope")),"Fixture-only programs required");
            programsPlan=plan(programs,programRaw,"installation-tools-x86-64","archiveFile");
            for(String name:List.of("bin/dbimport.elf","helpers/playerbots-schema.elf","libexec/ld-linux-x86-64.so.2"))
                require(programsPlan.required.containsKey(name)&&programsPlan.required.get(name).elfMachine==62,"Actual source-built x64 setup ELF required");
            require(!programsPlan.required.containsKey("bin/authserver")&&!programsPlan.required.containsKey("bin/worldserver"),"Setup fixture cannot grant world execution");
            byte[] contentRaw=asset(PREFIX+"content-provider.json",128<<10);pinned(contentRaw,descriptor.getJSONObject("contentDescriptor"));content=json(contentRaw);
            require("android-server-content-install-only".equals(content.getString("scope"))&&content.getBoolean("luaDisabled")&&
                !content.getBoolean("elfIncluded"),"Original architecture-neutral SQL content required");
            contentPlan=plan(content,contentRaw,"installation-content-original","file");
            require(contentPlan.required.keySet().equals(Set.of("metadata/content-manifest.json","metadata/compiled-modules.json",
                "metadata/lua-map.json","metadata/package-plan.json")),"Original full SQL metadata required");
            runtimeInstaller=new RuntimeInstaller(root.resolve("runtimes/installation-mysql-x64"));
            programsInstaller=new RuntimeInstaller(root.resolve("runtimes/installation-tools-x64"));
            contentInstaller=new RuntimeInstaller(root.resolve("runtimes/installation-content-original"));
            runtime=new ServerDatabaseService.InstallationRuntime(){
                public Path current()throws IOException{return runtimeInstaller.resolveCurrent(runtimePlan);}
                public String expectedMysqlVersion(){try{return descriptor.getString("mysqlVersion");}catch(JSONException invalid){throw new IllegalStateException(invalid);}}
                public String archiveSha256(){return runtimePlan.archiveSha256;}
                public OwnedProcess launch(Path work,Path session,List<String> command,List<ProotLaunch.Mount> mounts)throws IOException {
                    return ProotProcess.startQualified(context,payload,runtimeInstaller,runtimePlan,work,session,command,Collections.emptyMap(),mounts);
                }
                public OwnedProcess launch(Path work,Path session,List<String> command,OwnedProcess.GracefulInputStop shutdown)throws IOException {
                    return ProotProcess.startInteractiveQualified(context,payload,runtimeInstaller,runtimePlan,work,session,command,
                        Collections.emptyMap(),Collections.emptyList(),shutdown);
                }
            };
        }catch(JSONException|IllegalArgumentException invalid){throw new IOException("Invalid fixed installation fixture",invalid);}
    }
    private void prepare(RuntimeInstaller installer,RuntimePackagePlan plan,String asset)throws IOException {
        if(installer.resolveCurrent(plan)!=null)return;
        Path archive=new EmbeddedArchiveCache(root.resolve("runtime-embedded-cache/"+plan.packageId)).obtain(plan.archiveName,
            plan.archiveBytes,plan.archiveSha256,offset->open(asset,offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
        installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
    }
    private InputStream open(String name,long offset)throws IOException {
        if(offset<0)throw new IOException("Negative archive resume offset");
        InputStream input=context.getAssets().open(name);
        try{while(offset>0){long skipped=input.skip(offset);if(skipped>0)offset-=skipped;else if(input.read()<0)throw new IOException("Archive resume exceeds asset");else offset--;}return input;}
        catch(IOException|RuntimeException error){input.close();throw error;}
    }
    public ServerDatabaseService.InstallationRuntime runtime(){return runtime;}
    public void requireCurrentSelection()throws IOException {
        require(descriptorHash.equals(hash(asset(PREFIX+"provider.json",128<<10))),"Fixed fixture descriptor changed");
        verifyAssets();ProotProcess.qualificationPayload(context);
        require(runtime.current()!=null&&programsDirectory()!=null&&contentDirectory()!=null&&receipt!=null,"Install all exact fixture inputs first");
        try {
            pinnedFile(receipt,content.getJSONObject("receipt"));
            JSONObject proof=json(asset(PREFIX+"native-sql-qualification.json",256<<10));
            require(ServerSourceSelection.sameJson(proof.getJSONObject("source"),content.getJSONObject("serverSource"))&&
                proof.getString("sourceLockSha256").equals(sourceLockSha256())&&
                ServerSourceSelection.sameJson(proof.getJSONObject("compiledModules"),compiledModulesIdentity()),"Runtime and original content source differ");
            for(var pair:Map.of("provenance/server-build.json","contentOriginBuild","provenance/server-modules.json","compiledModules",
                    "provenance/playerbots-helper-build.json","actualX64BuildReceipt","provenance/playerbots-native-sql.json","nativeSqlReceipt").entrySet()) {
                JSONObject wanted=pair.getValue().equals("nativeSqlReceipt")?descriptor.getJSONObject("nativeSqlReceipt"):proof.getJSONObject(pair.getValue());
                require(ServerSourceSelection.sameJson(pin(programsPlan,pair.getKey()),wanted),"Measured setup provenance differs");
            }
            JSONObject generated=json(asset("installation-probe-helpers/installation-x64-inputs.json",16384));
            require(generated.getInt("formatVersion")==1&&"android-x64-installation-fixed-inputs".equals(generated.getString("scope"))&&
                ServerSourceSelection.sameJson(generated.getJSONObject("closure"),pin(programsPlan,"provenance/x64-closure.json")),"Fixed guest closure differs");
        }catch(JSONException invalid){throw new IOException("Invalid setup provenance",invalid);}
    }
    public Path programsDirectory()throws IOException{return programsInstaller.resolveCurrent(programsPlan);}
    public RuntimePackagePlan programsPlan(){return programsPlan;}
    public String programsArchiveSha256(){return programsPlan.archiveSha256;}
    public Path contentDirectory()throws IOException{return contentInstaller.resolveCurrent(contentPlan);}
    public Path contentReceiptPath()throws IOException{if(receipt==null)throw new IOException("Content receipt not installed");return receipt;}
    public String contentReceiptSha256(){try{return content.getJSONObject("receipt").getString("sha256");}catch(JSONException invalid){throw new IllegalStateException(invalid);}}
    public String sourceLockSha256(){try{return content.getJSONObject("serverBuildSourceLock").getString("sha256");}catch(JSONException invalid){throw new IllegalStateException(invalid);}}
    public JSONObject serverSource()throws IOException{try{return new JSONObject(content.getJSONObject("serverSource").toString());}catch(JSONException invalid){throw new IOException(invalid);}}
    public JSONObject compiledModulesIdentity()throws IOException{try{return new JSONObject(content.getJSONObject("compiledModules").toString());}catch(JSONException invalid){throw new IOException(invalid);}}
    public JSONObject measuredPlayerbotsSelection()throws IOException {
        requireCurrentSelection();try{return new JSONObject().put("executable",pin(programsPlan,"helpers/playerbots-schema"))
            .put("buildReceipt",pin(programsPlan,"provenance/playerbots-helper-build.json"))
            .put("nativeReceipt",pin(programsPlan,"provenance/playerbots-native-sql.json"));}catch(JSONException invalid){throw new IOException(invalid);}
    }
    public ServerInstallationSetup.HelperSelection helpers()throws IOException {
        return new ServerInstallationSetup.HelperSelection("installation-probe-helpers",HELPERS,"installation_x64_entry.py");
    }
    private void verifyAssets()throws IOException {
        try {
            JSONObject helperRows=descriptor.getJSONObject("helpers");Set<String> helperNames=new HashSet<>();helperRows.keys().forEachRemaining(helperNames::add);
            require(helperNames.equals(HELPERS),"Fixed source-owned helper set differs");
            JSONObject selected=descriptor.getJSONObject("packagedFiles");require(selected.length()>0&&selected.length()<=64,"Fixture asset inventory bound");
            for(Iterator<String> names=selected.keys();names.hasNext();) {
                String name=names.next();require(name.startsWith("assets/installation-probe/")||name.startsWith("assets/installation-probe-helpers/"),"Fixture asset namespace differs");
                require(!name.contains("..")&&!name.contains("\\"),"Invalid fixture asset path");
                JSONObject wanted=selected.getJSONObject(name);try(InputStream input=context.getAssets().open(name.substring(7))) {
                    MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] block=new byte[65536];long total=0;
                    for(int count;(count=input.read(block))!=-1;){total+=count;require(total<=wanted.getLong("bytes"),"Fixture asset grew");digest.update(block,0,count);}
                    require(total==wanted.getLong("bytes")&&hex(digest.digest()).equals(wanted.getString("sha256")),"Fixture asset bytes changed");
                }
            }
            for(String name:HELPERS)pinned(asset("installation-probe-helpers/"+name,131072),helperRows.getJSONObject(name));
        }catch(JSONException|NoSuchAlgorithmException invalid){throw new IOException("Invalid fixed asset inventory",invalid);}
    }
    private static RuntimePackagePlan plan(JSONObject proof,byte[] raw,String id,String archiveNameField)throws IOException,JSONException {
        JSONObject archive=proof.getJSONObject("archive"),bounds=proof.getJSONObject("limits"),required=proof.getJSONObject("requiredFiles");
        Map<String,RuntimePackagePlan.RequiredFile> selected=new TreeMap<>();
        for(Iterator<String> names=required.keys();names.hasNext();){String name=names.next();JSONObject row=required.getJSONObject(name);int machine=row.optInt("elfMachine",0);
            require(machine==0||machine==62,"Fixture cannot admit non-x64 ELF");selected.put(name,new RuntimePackagePlan.RequiredFile(row.getLong("bytes"),row.getString("sha256"),machine,0));}
        String archiveName=archiveNameField.equals("archiveFile")?proof.getString(archiveNameField):archive.getString(archiveNameField);
        return new RuntimePackagePlan(id,hash(raw),archiveName,archive.getLong("bytes"),archive.getString("sha256"),proof.getLong("archiveEntries"),proof.getLong("archiveFileBytes"),
            new RuntimePackagePlan.Limits(bounds.getInt("entries"),bounds.getLong("memberBytes"),bounds.getLong("fileBytes"),bounds.getInt("pathBytes"),bounds.getLong("metadataBytes")),selected);
    }
    private byte[] asset(String name,int bound)throws IOException {try(InputStream input=context.getAssets().open(name)){return bounded(input,bound);}}
    static byte[] bounded(InputStream input,int bound)throws IOException {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] block=new byte[4096];for(int count;(count=input.read(block))!=-1;){require(output.size()+count<=bound,"Fixture metadata bound exceeded");output.write(block,0,count);}return output.toByteArray();
    }
    static JSONObject json(byte[] raw)throws IOException {try{return new JSONObject(new String(raw,StandardCharsets.UTF_8));}catch(JSONException invalid){throw new IOException(invalid);}}
    static String hash(byte[] raw){try{return hex(MessageDigest.getInstance("SHA-256").digest(raw));}catch(NoSuchAlgorithmException impossible){throw new AssertionError(impossible);}}
    private static String hex(byte[] bytes){StringBuilder text=new StringBuilder();for(byte item:bytes)text.append(String.format(java.util.Locale.ROOT,"%02x",item&255));return text.toString();}
    private static void pinned(byte[] raw,JSONObject wanted)throws IOException,JSONException {require(raw.length==wanted.getLong("bytes")&&hash(raw).equals(wanted.getString("sha256")),"Fixture metadata pin differs");}
    private static void pinnedFile(Path path,JSONObject wanted)throws IOException,JSONException {
        require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&path.toRealPath().equals(path),"Private plain receipt required");
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){pinned(bounded(input,16<<20),wanted);}
    }
    private static JSONObject pin(RuntimePackagePlan plan,String name)throws IOException,JSONException {
        RuntimePackagePlan.RequiredFile row=plan.required.get(name);require(row!=null,"Required fixture provenance missing");return new JSONObject().put("bytes",row.bytes).put("sha256",row.sha256);
    }
    private static void require(boolean ok,String reason)throws IOException {if(!ok)throw new IOException(reason);}
}
