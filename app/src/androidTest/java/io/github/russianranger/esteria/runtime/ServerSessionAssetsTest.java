package io.github.russianranger.esteria.runtime;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Comparator;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** APK/private metadata only. Synthetic files are not usable game data, tools,
 * source qualification or an authorization to execute a server session. */
@RunWith(AndroidJUnit4.class)
public final class ServerSessionAssetsTest {
    @Test public void completeSessionHelperClosureInstallsAndReusesExactBytes()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"session-helper-test-");
        try {
            Path generations=GuestHelperAssets.directory(root,"generations");
            String generation=GuestHelperAssets.install(context,"server-session",generations,LocalServerSession.HELPERS);
            Path installed=generations.resolve(generation),retained=installed.resolve("local-server.json");
            FileTime stamp=FileTime.fromMillis(12345000);Files.setLastModifiedTime(retained,stamp);
            for(String name:LocalServerSession.HELPERS)try(var input=context.getAssets().open("server-session/"+name)) {
                assertArrayEquals(input.readAllBytes(),Files.readAllBytes(installed.resolve(name)));
            }
            assertEquals(generation,GuestHelperAssets.install(context,"server-session",generations,LocalServerSession.HELPERS));
            assertEquals(stamp,Files.getLastModifiedTime(retained));
            try(var files=Files.walk(installed)){assertEquals(LocalServerSession.HELPERS.size(),files.filter(Files::isRegularFile).count());}
        }finally{remove(root);}
    }
    @Test public void privateDataMetadataBindingRejectsChangedAncestryAndQualificationClaims()throws Exception {
        // Positive generations/receipts come from the production Python helper,
        // not this consumer's JSON formatting routine.
        new PythonReceiptBindingTest().pythonDataGenerationAcceptedAndMutationsRejected();
    }
    private static void remove(Path root)throws Exception {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
}
