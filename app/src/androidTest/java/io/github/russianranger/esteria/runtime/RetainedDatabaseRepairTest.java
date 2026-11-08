package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.util.Log;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import static org.junit.Assume.assumeTrue;

/** Run each phase in a separate process on one disposable, offline Android installation. */
@RunWith(AndroidJUnit4.class)
public final class RetainedDatabaseRepairTest {
    private static final String TAG="EsteriaDatabaseQA";

    @Test public void retainedInstallation() throws Exception {
        String phase=InstrumentationRegistry.getArguments().getString("disposableDatabasePhase", "");
        assumeTrue(Set.of("seed","repair","cold").contains(phase));
        runPhase(InstrumentationRegistry.getInstrumentation().getTargetContext(),phase);
    }

    public static void runPhase(Context context,String phase) throws Exception {
        Path root=context.getFilesDir().getCanonicalFile().toPath();
        Path marker=root.resolve("retained-database-test-owner"),data=marker.resolve("empty-data");
        ServerRuntimeSetup runtime=new ServerRuntimeSetup(context,root);
        ServerProgramsSetup programs=new ServerProgramsSetup(context,root);
        ServerContentSetup content=new ServerContentSetup(context,root);
        long start=System.nanoTime();
        if(phase.equals("seed")) {
            assertFalse(Files.exists(root.resolve("db")));
            assertFalse(Files.exists(root.resolve("runtimes")));
            Files.createDirectory(marker);
            Files.createDirectory(data);
            long copied=runtime.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            copied+=programs.prepare(runtime.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            copied+=content.prepare(runtime.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            assertTrue(copied>0);
            Log.i(TAG,"seed generation="+content.generation()+" providerCopiedBytes="+copied);
            return;
        }
        assertTrue(Files.isDirectory(data));
        assertNotNull(content.current());
        if(phase.equals("repair")) {
            assertNull(ServerInstallationSetup.completedOrNull(context,root,runtime,programs,content));
            Path receipt=content.receiptPath();
            byte[] original=Files.readAllBytes(receipt);
            FileTime time=Files.getLastModifiedTime(receipt);
            byte[] changed=original.clone();
            changed[changed.length/2]^=1;
            Files.write(receipt,changed);
            Files.setLastModifiedTime(receipt,time);
            try(ServerInstallationSetup.Handle unwanted=ServerInstallationSetup.beginFresh(context,root,runtime,programs,content,data,1L<<30)) {
                fail("Modified receipt allocated a database slot");
            } catch(IOException expected) {assertTrue(expected.toString(),expected.getMessage().contains("receipt"));}
            if(Files.exists(root.resolve("db"))) {
                try(var slots=Files.list(root.resolve("db"))) {assertEquals(0,slots.count());}
            }
            Files.delete(receipt); // Only the deliberately damaged receipt in this test's disposable setup.
            assertArrayEquals(original,Files.readAllBytes(new ServerContentSetup(context,root).receiptPath()));
            Set<String> phases=new HashSet<>();
            try(ServerInstallationSetup.Handle owner=ServerInstallationSetup.beginFresh(context,root,runtime,programs,
                    new ServerContentSetup(context,root),data,1L<<30)) {
                RuntimeWork.Progress progress=(event,path,n,total)->{
                    if(phases.add(event))Log.i(TAG,"phase="+event+" ms="+elapsed(start));
                };
                owner.prepare(progress,RuntimeWork.NEVER_CANCELLED);
                owner.finishPlayerbots(progress,RuntimeWork.NEVER_CANCELLED);
                FreshServerInstallations.Active active=owner.stopAndPromote(Duration.ofSeconds(30));
                assertTrue(phases.containsAll(Set.of("database-initializing","database-prepared","installation-core-started","installation-playerbots-started")));
                Files.write(marker.resolve("identity"),identity(root,active),StandardOpenOption.CREATE_NEW);
                Log.i(TAG,"promoted slot="+active.slotId+" uuid="+active.mysqlUuid+" ms="+elapsed(start));
            }
            return;
        }
        FreshServerInstallations.Active active=ServerInstallationSetup.completed(context,root,runtime,programs,content);
        assertArrayEquals(Files.readAllBytes(marker.resolve("identity")),identity(root,active));
        ServerDatabaseService.Handle service=ServerDatabaseService.startActive(context,root,runtime,active);
        try {
            ServerDatabaseService.awaitReady(service,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),RuntimeWork.NEVER_CANCELLED);
            assertEquals(active.mysqlUuid,service.instanceUuid());
        } finally {service.stop(Duration.ofSeconds(30));}
        assertFalse(service.isAlive());
        assertArrayEquals(Files.readAllBytes(marker.resolve("identity")),identity(root,active));
        Log.i(TAG,"cold same slot="+active.slotId+" uuid="+active.mysqlUuid+" account verified and MySQL stopped ms="+elapsed(start));
    }

    private static byte[] identity(Path root,FreshServerInstallations.Active active) throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");
        for(String value:Arrays.asList(active.slotId,active.mysqlUuid,active.proofSha256,active.setupReceiptSha256))
            digest.update(value.getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        return digest.digest(Files.readAllBytes(active.directoryFor(root).resolve("state/accounts/local-player.json")));
    }
    private static long elapsed(long start){return TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start);}
}
