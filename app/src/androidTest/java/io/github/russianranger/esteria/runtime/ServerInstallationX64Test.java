package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
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
import java.time.Duration;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

/** A separately pinned, new Android13 x64 coordinator/SQL qualification only.
 * No source check, build or native SQL receipt makes this Android test pass. */
@RunWith(AndroidJUnit4.class)
public final class ServerInstallationX64Test {
    private static String privateHash(Path file)throws IOException {
        assertTrue(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS));assertEquals(file,file.toRealPath());
        try(InputStream input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) {
            return InstallationX64Inputs.hash(InstallationX64Inputs.bounded(input,128<<10));
        }
    }
    private static Map<String,String> privateIdentities(Path work)throws IOException {
        Map<String,String> result=new TreeMap<>();
        for(String name:List.of("database-bootstrap.json",".server-schema-initialization.json",".server-compiled-updater.json",
                ".server-playerbots-schema.json",".server-playerbots-finish.json","server-installation-staged.json",
                "server-installation-verified.json","server-setup-complete.json","accounts/local-player.json",
                "accounts/database-secret","accounts/database-root-secret"))result.put(name,privateHash(work.resolve("state").resolve(name)));
        return result; // Never serialize private journal/credential identities.
    }
    private static ServerDatabaseService.Handle ownedDatabase(ServerInstallationSetup.Handle owner)throws Exception {
        // Read the existing actual owner for an independent SQL observation;
        // never inject a result, handle, phase or promotion proof.
        Field field=ServerInstallationSetup.Handle.class.getDeclaredField("database");field.setAccessible(true);
        Object value=field.get(owner);assertTrue(value instanceof ServerDatabaseService.Handle);return (ServerDatabaseService.Handle)value;
    }
    private static JSONObject observe(Context context,Path root,InstallationX64Inputs inputs,ServerDatabaseService.Handle service,InstallationX64Lifetime lifetime)throws Exception {
        return service.withReadyLease(inputs.runtime().current(),(serviceOperation,version,uuid)->{
            try {
                Path work=service.privateWorkDirectory();Path qualification=GuestHelperAssets.directory(work,"qualification");
                GuestHelperAssets.directory(work,"qualification-results");
                byte[] script;try(InputStream input=context.getAssets().open("installation-probe/restart_probe.py")) {
                    script=InstallationX64Inputs.bounded(input,32768);
                }
                Path probe=qualification.resolve("restart_probe.py");
                if(Files.exists(probe,LinkOption.NOFOLLOW_LINKS))assertEquals(InstallationX64Inputs.hash(script),privateHash(probe));
                else Files.write(probe,script,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);
                byte[] helperManifest;try(InputStream input=context.getAssets().open("installation-probe-helpers/manifest.json")) {
                    helperManifest=InstallationX64Inputs.bounded(input,16384);
                }
                String operation=UUID.randomUUID().toString().replace("-","");
                Path session=GuestHelperAssets.directory(root,"state/installation-x64-sql-observations").resolve(operation);Files.createDirectory(session);
                OwnedProcess child=lifetime.observe(()->inputs.runtime().launch(work,session,List.of("/usr/bin/python3","-B","-s","-E","/work/qualification/restart_probe.py",
                    "--helper-generation",InstallationX64Inputs.hash(helperManifest),"--operation",operation,"--version",version,"--uuid",uuid),Collections.emptyList()));
                try {
                    long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(5);
                    while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(50);
                    if(child.isAlive()||child.wasForced()||child.failure()!=null||child.exitCode()!=0)throw new IOException("Actual SQL observation failed; private state retained");
                }finally{lifetime.finishObservation();}
                Path file=work.resolve("qualification-results/"+operation+".json");
                assertTrue(Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS));assertEquals(file,file.toRealPath());
                JSONObject observed;try(InputStream input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) {
                    observed=InstallationX64Inputs.json(InstallationX64Inputs.bounded(input,16384));
                }
                assertEquals(1,observed.getInt("formatVersion"));assertEquals("private-native-java-installation-sql-comparison",observed.getString("scope"));
                assertEquals(uuid,observed.getString("mysqlUuid"));assertTrue(observed.getString("coreAndAccountRowsSha256").matches("[a-f0-9]{64}"));
                assertTrue(observed.getBoolean("ownedAccountAndRealmVerified"));assertTrue(observed.getBoolean("playerbotsJournalMatchesLiveSql"));
                assertTrue(observed.getInt("playerbotsTableCount")>0);assertTrue(observed.getInt("playerbotsUpdateCount")>0);return observed;
            }catch(InterruptedException interrupted){Thread.currentThread().interrupt();throw new IOException("SQL observation interrupted",interrupted);}
            catch(IOException error){throw error;}catch(Exception error){throw new IOException("SQL observation failed",error);}
        });
    }
    private static void close(ServerInstallationSetup.Handle owner)throws IOException {
        if(owner==null)return;long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(2);IOException failure=null;
        while(owner.state()!=ServerInstallationSetup.State.CLOSED&&System.nanoTime()<deadline) {
            try{owner.close(Duration.ofSeconds(30));}catch(IOException error){failure=error;}
        }
        if(owner.state()!=ServerInstallationSetup.State.CLOSED)throw new IOException("Installation cleanup remains owned",failure);
        if(failure!=null)throw failure;
    }
    @Test public void actualAndroidCoordinatorInitializesFourSchemasPromotesAndRestarts()throws Exception {
        assumeTrue(BuildConfig.SERVER_INSTALLATION_PROBE_PACKAGED);
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(BuildConfig.DEBUG);assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        // Do not adopt the standalone MySQL fixture, a prior coordinator run or
        // a player's active/legacy saves. This class requires fresh app data.
        for(String name:List.of("db","state/server-work","installation-x64-qualification.json"))
            assertFalse("Fresh app data required for this disposable SQL fixture",Files.exists(root.resolve(name),LinkOption.NOFOLLOW_LINKS));
        InstallationX64Lifetime lifetime=InstallationX64Lifetime.acquire(root);
        try {
            InstallationX64Inputs inputs=InstallationX64Inputs.install(context);
            Path data=GuestHelperAssets.directory(root,"unavailable-installation-game-data");GuestHelperAssets.directory(data,"data");
            assertNull(ServerInstallationSetup.completedInstalledOrNull(context,root,inputs));
            ServerInstallationSetup.Handle owner=null;ServerDatabaseService.Handle restarted=null;String phase="fresh-core-sql";
            JSONObject result=new JSONObject().put("formatVersion",1).put("scope","android13-x64-owned-four-schema-installation-and-restart")
                .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("providerSha256",BuildConfig.SERVER_INSTALLATION_PROBE_PIN)
                .put("api",Build.VERSION.SDK_INT).put("abi","x86_64").put("qualificationSucceeded",false)
                .put("productionArm64ProviderQualified",false).put("thorQualified",false).put("authserverExecuted",false)
                .put("worldserverExecuted",false).put("serverDataQualified",false).put("characterPersistenceQualified",false)
                .put("playerbotsAiQualified",false).put("gameplayQualified",false);
            try {
                owner=ServerInstallationSetup.beginInstalled(context,root,inputs,data,1L<<30);
                ServerInstallationSetup.Handle retainedInstallation=owner;lifetime.installation(()->close(retainedInstallation));
                owner.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);assertEquals(ServerInstallationSetup.State.STAGED_PENDING_PLAYERBOTS,owner.state());
                phase="actual-fourth-schema";owner.finishPlayerbots(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
                assertEquals(ServerInstallationSetup.State.SCHEMAS_VERIFIED,owner.state());JSONObject before=observe(context,root,inputs,ownedDatabase(owner),lifetime);
                phase="clean-stop-promotion";FreshServerInstallations.Active active=owner.stopAndPromote(Duration.ofSeconds(30));
                assertEquals(ServerInstallationSetup.State.PROMOTED,owner.state());Path work=active.directoryFor(root);Map<String,String> identities=privateIdentities(work);
                FreshServerInstallations.Active loaded=ServerInstallationSetup.completedInstalledOrNull(context,root,inputs);assertNotNull(loaded);
                assertEquals(active.slotId,loaded.slotId);assertEquals(active.mysqlUuid,loaded.mysqlUuid);assertEquals(active.proofSha256,loaded.proofSha256);
                close(owner);owner=null;phase="refuse-active-reinitialization";
                ServerInstallationSetup.Handle unexpected=null;boolean refused=false;
                try{unexpected=ServerInstallationSetup.beginInstalled(context,root,inputs,data,1L<<30);}
                catch(IOException expected){refused="An active database is already present; fresh initialization refused".equals(expected.getMessage());}
                if(unexpected!=null){close(unexpected);fail("Active database was accepted for reinitialization");}
                assertTrue(refused);assertTrue("Private journals or credentials changed",identities.equals(privateIdentities(work)));phase="restart-same-instance";
                restarted=ServerDatabaseService.startActiveInstalled(context,root,inputs.runtime(),loaded);
                ServerDatabaseService.Handle retainedDatabase=restarted;lifetime.database(()->retainedDatabase.stop(Duration.ofSeconds(30)));
                ServerDatabaseService.awaitReady(restarted,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),()->false);
                assertEquals(active.mysqlUuid,restarted.instanceUuid());JSONObject after=observe(context,root,inputs,restarted,lifetime);
                assertTrue(ServerSourceSelection.sameJson(before,after));assertTrue("Private journals or credentials changed",identities.equals(privateIdentities(work)));
                phase="second-clean-stop";restarted.stop(Duration.ofSeconds(30));assertFalse(restarted.isAlive());restarted=null;
                assertEquals(active.proofSha256,ServerInstallationSetup.completedInstalledOrNull(context,root,inputs).proofSha256);
                assertTrue("Private journals or credentials changed",identities.equals(privateIdentities(work)));
                result.put("qualificationSucceeded",true).put("androidJavaCoordinatorExecuted",true).put("actualFourSchemaSqlExecuted",true)
                    .put("sourceBoundGuestHelpersExecuted",true).put("ordinaryNativeOwnerExecuted",true).put("androidBionicProotLocatorExecuted",true)
                    .put("slotPromoted",true).put("completedSelectionReadBack",true).put("activeFreshInitializationRefused",true)
                    .put("restartedSameLiveSqlUuid",true).put("actualCoreAccountRealmAndBotSqlPreserved",true)
                    .put("privateJournalsAndCredentialsPreserved",true).put("twoCleanDatabaseStopsVerified",true)
                    .put("mysqlUuid",active.mysqlUuid).put("mysqlVersion",inputs.runtime().expectedMysqlVersion())
                    .put("runtimeArchiveSha256",inputs.runtime().archiveSha256()).put("programsArchiveSha256",inputs.programsArchiveSha256())
                    .put("contentReceiptSha256",inputs.contentReceiptSha256()).put("sourceLockSha256",inputs.sourceLockSha256())
                    .put("playerbotsTableCount",after.getInt("playerbotsTableCount")).put("playerbotsUpdateCount",after.getInt("playerbotsUpdateCount"));
                phase="complete";
            }catch(Throwable failure){result.put("failureType",failure.getClass().getSimpleName());throw failure;}
            finally {
                try{lifetime.close();}
                catch(Throwable cleanup){result.put("qualificationSucceeded",false).put("cleanupFailureType",cleanup.getClass().getSimpleName());throw cleanup;}
                finally {
                    result.put("phase",phase);Files.write(root.resolve("installation-x64-qualification.json"),(result.toString(2)+"\n").getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
                }
            }
        }finally{lifetime.close();}
    }
}
