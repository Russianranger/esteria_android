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

/** Actual APK/private-file closure only; executes no Python helper or extractor. */
@RunWith(AndroidJUnit4.class)
public final class ServerDataAssetsTest {
    @Test public void completeDataHelperClosureInstallsAndReusesExactBytes()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"data-helper-test-");
        try {
            String generation=ServerDataAssets.install(context,root);
            Path installed=root.resolve("data-helpers").resolve(generation);
            Path retained=installed.resolve("server_data_generation.py");
            FileTime stamp=FileTime.fromMillis(12345000);Files.setLastModifiedTime(retained,stamp);
            for(String name:ServerDataAssets.HELPERS)try(var input=context.getAssets().open("server-data/"+name)) {
                assertArrayEquals(input.readAllBytes(),Files.readAllBytes(installed.resolve(name)));
            }
            assertEquals(generation,ServerDataAssets.install(context,root));
            assertEquals(stamp,Files.getLastModifiedTime(retained));
            try(var files=Files.walk(installed)){assertEquals(6,files.filter(Files::isRegularFile).count());}
        }finally {
            try(var paths=Files.walk(root)) {
                for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);
            }
        }
    }
}
