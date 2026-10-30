package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.json.JSONArray;

/** Real production Java coordinator, Linux PRoot/JNI and real source-bound SQL.
 * Only Context/assets and the Linux payload locator replace Android facilities.
 * No essential process, SQL, state, result or promotion is mocked/injected. */
public final class NativeJavaInstallation {
    private static final String SCOPE="native-arm64-java-owned-installation-promotion-and-restart";
    private static String phase="refuse-unverified-environment";
    private static void require(boolean condition,String reason)throws IOException {if(!condition)throw new IOException(reason);}
    private static void failure(JSONObject result,Throwable error) {
        JSONArray frames=new JSONArray(),causes=new JSONArray();int count=0;
        for(StackTraceElement frame:error.getStackTrace()) {
            if(count>=16)break;String type=frame.getClassName(),method=frame.getMethodName();
            if(type.matches("[A-Za-z_][A-Za-z0-9_.$]{0,191}")&&method.matches("[A-Za-z_$<>][A-Za-z0-9_$<>]{0,127}")&&frame.getLineNumber()>0) {
                frames.put(new JSONObject().put("class",type).put("method",method).put("line",frame.getLineNumber()));count++;
            }
        }
        java.util.Set<Throwable> seen=Collections.newSetFromMap(new java.util.IdentityHashMap<>());
        Throwable cause=error;while(cause!=null&&causes.length()<8&&seen.add(cause)) {
            String type=cause.getClass().getName();if(type.matches("[A-Za-z_][A-Za-z0-9_.$]{0,191}"))causes.put(type);cause=cause.getCause();
        }
        result.put("failureType",error.getClass().getSimpleName()).put("failureJavaFrames",frames).put("failureCauseClasses",causes);
    }
    private static String sha(byte[] bytes)throws Exception {return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
    private static String hash(Path path)throws Exception {
        require(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)&&path.equals(path.toRealPath()),"Plain private comparison file required");
        MessageDigest digest=MessageDigest.getInstance("SHA-256");try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] block=new byte[65536];for(int count;(count=input.read(block))!=-1;)digest.update(block,0,count);
        }return java.util.HexFormat.of().formatHex(digest.digest());
    }
    private static Map<String,String> privateIdentities(Path work)throws Exception {
        Map<String,String> result=new TreeMap<>();
        for(String name:List.of("database-bootstrap.json",".server-schema-initialization.json",".server-compiled-updater.json",
                ".server-playerbots-schema.json",".server-playerbots-finish.json","server-installation-staged.json",
                "server-installation-verified.json","server-setup-complete.json","accounts/local-player.json",
                "accounts/database-secret","accounts/database-root-secret"))result.put(name,hash(work.resolve("state").resolve(name)));
        return result; // Remains in memory; no private identity/bytes are exported.
    }
    private static ServerDatabaseService.Handle database(ServerInstallationSetup.Handle owner)throws Exception {
        // Read-only access to the actual retained live owner for a separate SQL
        // observation. Never write coordinator state/results or inject a handle.
        Field field=ServerInstallationSetup.Handle.class.getDeclaredField("database");field.setAccessible(true);
        Object result=field.get(owner);require(result instanceof ServerDatabaseService.Handle,"Actual coordinator database owner required");
        return (ServerDatabaseService.Handle)result;
    }
    private static JSONObject observe(Context context,Path root,ServerRuntimeSetup runtime,ServerDatabaseService.Handle service)throws Exception {
        return service.withReadyLease(runtime.current(),(serviceOperation,version,uuid)->{
            try {
                Path work=service.privateWorkDirectory();Path qualification=GuestHelperAssets.directory(work,"qualification");
                GuestHelperAssets.directory(work,"qualification-results");
                byte[] script;try(InputStream input=context.getAssets().open("qualification/restart_probe.py")){script=input.readNBytes(32769);}
                require(script.length>0&&script.length<=32768,"Bounded exact qualification SQL probe required");
                Path probe=qualification.resolve("restart_probe.py");
                if(Files.exists(probe,LinkOption.NOFOLLOW_LINKS))require(hash(probe).equals(sha(script)),"Existing SQL probe changed");
                else Files.write(probe,script,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
                byte[] helperManifest;try(InputStream input=context.getAssets().open("server-installation/manifest.json")){helperManifest=input.readNBytes(16385);}
                require(helperManifest.length<=16384,"Bounded production helper manifest required");String generation=sha(helperManifest);
                String operation=UUID.randomUUID().toString().replace("-","");
                Path session=GuestHelperAssets.directory(root,"state/java-installation-sql-observations").resolve(operation);Files.createDirectory(session);
                OwnedProcess process=ProotProcess.start(context,runtime.installer(),runtime.packagePlan(),work,session,
                    List.of("/usr/bin/python3","-B","-s","-E","/work/qualification/restart_probe.py","--helper-generation",generation,
                        "--operation",operation,"--version",version,"--uuid",uuid),Collections.emptyMap(),null);
                long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(5);
                try {
                    while(process.isAlive()&&System.nanoTime()<deadline)Thread.sleep(50);
                    require(!process.isAlive()&&!process.wasForced()&&process.failure()==null&&process.exitCode()==0,"Actual SQL observation failed");
                }finally{if(process.isAlive())process.stop(Duration.ZERO);}
                Path result=work.resolve("qualification-results/"+operation+".json");
                require(Files.isRegularFile(result,LinkOption.NOFOLLOW_LINKS)&&result.equals(result.toRealPath())&&Files.size(result)<=16384,"Bounded actual SQL comparison required");
                JSONObject observed=new JSONObject(Files.readString(result));
                require(observed.getInt("formatVersion")==1&&"private-native-java-installation-sql-comparison".equals(observed.getString("scope"))&&
                    uuid.equals(observed.getString("mysqlUuid"))&&observed.getString("coreAndAccountRowsSha256").matches("[a-f0-9]{64}")&&
                    observed.getBoolean("ownedAccountAndRealmVerified")&&observed.getBoolean("playerbotsJournalMatchesLiveSql")&&
                    observed.getInt("playerbotsTableCount")>0&&observed.getInt("playerbotsUpdateCount")>0,"Actual SQL comparison scope differs");
                return observed;
            }catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new IOException("SQL comparison interrupted",interrupted);}
            catch(IOException error){throw error;}catch(Exception error){throw new IOException("SQL comparison failed",error);}
        });
    }
    private static void close(ServerInstallationSetup.Handle owner)throws Exception {
        if(owner==null)return;long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(2);IOException failure=null;
        while(owner.state()!=ServerInstallationSetup.State.CLOSED&&System.nanoTime()<deadline) {
            try{owner.close(Duration.ofSeconds(30));}catch(IOException error){failure=error;}
        }
        require(owner.state()==ServerInstallationSetup.State.CLOSED,"Installation cleanup remains owned");
        if(failure!=null)throw failure;
    }
    public static void main(String[] args)throws Exception {
        if(args.length!=3)throw new IllegalArgumentException("canonical-assets new-private-root new-public-result required");
        Path assets=Path.of(args[0]),root=Path.of(args[1]),output=Path.of(args[2]);
        require("Linux".equals(System.getProperty("os.name"))&&"aarch64".equals(System.getProperty("os.arch")),"Native Linux ARM64 required");
        require(root.isAbsolute()&&!Files.exists(root,LinkOption.NOFOLLOW_LINKS)&&output.isAbsolute()&&!Files.exists(output,LinkOption.NOFOLLOW_LINKS),"New explicit qualification paths required");
        require(root.getParent().equals(root.getParent().toRealPath())&&output.getParent().equals(output.getParent().toRealPath()),"Canonical qualification parents required");
        Files.createDirectory(root);root=root.toRealPath();
        Context context=new Context(root.toFile(),new AssetManager(assets));
        JSONObject result=new JSONObject().put("formatVersion",1).put("scope",SCOPE).put("integrationRevision",BuildConfig.SOURCE_REVISION)
            .put("qualificationSucceeded",false).put("javaCoordinatorExecuted",false).put("actualSqlExecuted",false)
            .put("slotPromoted",false).put("androidRuntimeQualified",false).put("androidApiExecuted",false)
            .put("androidBionicProotLocatorExecuted",false).put("productionProotProcessExecuted",false)
            .put("worldserverExecuted",false).put("authserverExecuted",false).put("serverDataQualified",false)
            .put("characterPersistenceQualified",false).put("playerbotsAiQualified",false).put("gameplayQualified",false);
        ServerInstallationSetup.Handle owner=null;ServerDatabaseService.Handle restarted=null;
        try {
            phase="install-exact-production-providers";
            InstalledProot.inspect(context);
            ServerRuntimeSetup runtime=new ServerRuntimeSetup(context,root);runtime.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            ServerProgramsSetup programs=new ServerProgramsSetup(context,root);programs.prepare(runtime.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            ServerContentSetup content=new ServerContentSetup(context,root);content.prepare(runtime.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            // An empty, explicitly unavailable data namespace is sufficient for
            // SQL/configuration. No replacement map/DBC/header is fabricated.
            Path data=GuestHelperAssets.directory(root,"unavailable-game-data");GuestHelperAssets.directory(data,"data");
            require(ServerInstallationSetup.completedOrNull(context,root,runtime,programs,content)==null,"Fresh qualification unexpectedly has an active database");
            phase="real-java-fresh-core-sql";result.put("javaCoordinatorExecuted",true).put("sqlExecutionAttempted",true);
            owner=ServerInstallationSetup.beginFresh(context,root,runtime,programs,content,data,1L<<30);
            owner.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            require(owner.state()==ServerInstallationSetup.State.STAGED_PENDING_PLAYERBOTS,"Actual core setup failed");
            result.put("actualSqlExecuted",true).put("productionProotProcessExecuted",true);
            phase="real-java-four-schema-finish";owner.finishPlayerbots(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            require(owner.state()==ServerInstallationSetup.State.SCHEMAS_VERIFIED,"Actual fourth schema finish failed");
            JSONObject before=observe(context,root,runtime,database(owner));
            phase="real-java-clean-stop-and-promotion";
            FreshServerInstallations.Active active=owner.stopAndPromote(Duration.ofSeconds(30));
            require(owner.state()==ServerInstallationSetup.State.PROMOTED,"Real coordinator did not promote");
            result.put("slotPromoted",true);
            Path work=active.directoryFor(root);Map<String,String> identities=privateIdentities(work);
            FreshServerInstallations.Active loaded=ServerInstallationSetup.completed(context,root,runtime,programs,content);
            require(active.slotId.equals(loaded.slotId)&&active.mysqlUuid.equals(loaded.mysqlUuid)&&active.proofSha256.equals(loaded.proofSha256),"Promotion readback changed");
            close(owner);owner=null;
            phase="active-save-reinitialization-refusal";boolean refused=false;ServerInstallationSetup.Handle unexpected=null;
            try{unexpected=ServerInstallationSetup.beginFresh(context,root,runtime,programs,content,data,1L<<30);}
            catch(IOException expected){refused="An active database is already present; fresh initialization refused".equals(expected.getMessage());}
            if(unexpected!=null){close(unexpected);throw new IOException("Fresh setup accepted an active database");}
            require(refused&&identities.equals(privateIdentities(work)),"Active database fresh reseeding was not refused");
            phase="restart-actual-promoted-mysql";
            restarted=ServerDatabaseService.startActive(context,root,runtime,loaded);
            ServerDatabaseService.awaitReady(restarted,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),()->false);
            require(active.mysqlUuid.equals(restarted.instanceUuid()),"Restart changed the SQL UUID");
            JSONObject after=observe(context,root,runtime,restarted);
            require(ServerSourceSelection.sameJson(before,after)&&identities.equals(privateIdentities(work)),"Restart changed actual account/core/bot SQL or private journals");
            phase="second-actual-clean-stop";restarted.stop(Duration.ofSeconds(30));require(!restarted.isAlive(),"Restarted service remains live");restarted=null;
            loaded=ServerInstallationSetup.completed(context,root,runtime,programs,content);
            require(active.proofSha256.equals(loaded.proofSha256)&&identities.equals(privateIdentities(work)),"Completed readback changed after clean restart");
            result.put("qualificationSucceeded",true).put("slotPromoted",true).put("activeSlotId",active.slotId)
                .put("mysqlUuid",active.mysqlUuid).put("mysqlVersion",runtime.expectedMysqlVersion())
                .put("runtimeArchiveSha256",runtime.archiveSha256()).put("programsArchiveSha256",programs.archiveSha256())
                .put("contentReceiptSha256",content.receiptSha256()).put("sourceLockSha256",content.sourceLockSha256())
                .put("completeReceiptSha256",active.setupReceiptSha256).put("promotionProofSha256",active.proofSha256)
                .put("completedSelectionReadBack",true).put("activeFreshInitializationRefused",true)
                .put("restartedSameLiveSqlUuid",true).put("actualCoreAccountRealmAndBotSqlPreserved",true)
                .put("privateJournalsAndCredentialsPreserved",true).put("twoCleanDatabaseStopsVerified",true)
                .put("playerbotsTableCount",after.getInt("playerbotsTableCount")).put("playerbotsUpdateCount",after.getInt("playerbotsUpdateCount"));
            phase="complete";
        }catch(Throwable error){failure(result,error);throw error;}
        finally {
            try{if(restarted!=null)restarted.stop(Duration.ofSeconds(30));}finally{try{close(owner);}finally{
                result.put("phase",phase);Files.writeString(output,result.toString(2)+"\n",StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
            }}
        }
        System.out.println("Actual native ARM64 Java coordinator, four-schema SQL, clean promotion, owned restart and persistence comparison passed");
    }
}
