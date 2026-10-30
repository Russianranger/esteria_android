package io.github.russianranger.esteria.runtime;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Comparator;
import java.util.Set;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual nested APK source resources/private files; never executes SQL. */
@RunWith(AndroidJUnit4.class)
public final class ServerSchemaAssetsTest {
    private static final Set<String> HELPERS=Set.of("android_server_schema_setup.py","mysql_bootstrap.py","mysql_service.py",
        "server_content.py","server_schema_setup.py","server_schema_baseline.py","server_schema_adaptations.py",
        "server/appearance-schema-v1.sql","server/appearance-schema.lock.json");
    private Context context;
    private Path root,generations;
    @Before public void fixture() throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"schema-helper-test-");
        generations=GuestHelperAssets.directory(root,"generations");
    }
    @After public void cleanup() throws Exception {
        if(root!=null)try(var paths=Files.walk(root)) {
            for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);
        }
    }
    private Path install() throws Exception {
        return generations.resolve(GuestHelperAssets.install(context,"server-schema",generations,HELPERS));
    }
    @Test public void nestedOriginalSourcesInstallAndResumeWithoutRewriting() throws Exception {
        Path generation=install();Path sql=generation.resolve("server/appearance-schema-v1.sql");
        FileTime retained=FileTime.fromMillis(12345000);Files.setLastModifiedTime(sql,retained);
        Files.delete(generation.resolve("server/appearance-schema.lock.json"));
        assertEquals(generation,install());assertEquals(retained,Files.getLastModifiedTime(sql));
        for(String name:HELPERS) {
            try(var source=context.getAssets().open("server-schema/"+name)) {
                assertArrayEquals(source.readAllBytes(),Files.readAllBytes(generation.resolve(name)));
            }
        }
    }
    @Test public void unexpectedNestedModuleIsPreservedAndRefused() throws Exception {
        Path generation=install(),foreign=generation.resolve("server/json.py");
        Files.write(foreign,new byte[]{1,2,3});
        try{install();fail("Extra nested Python must not enter the import generation");}
        catch(java.io.IOException expected){assertArrayEquals(new byte[]{1,2,3},Files.readAllBytes(foreign));}
    }
    @Test public void linkedResourceDirectoryIsPreservedAndRefused() throws Exception {
        Path generation=install(),server=generation.resolve("server"),retained=root.resolve("original-server");
        Files.move(server,retained);Files.createSymbolicLink(server,retained);
        byte[] original=Files.readAllBytes(retained.resolve("appearance-schema-v1.sql"));
        try{install();fail("Linked helper resource directory must be refused");}
        catch(java.io.IOException expected){assertTrue(Files.isSymbolicLink(server));assertArrayEquals(original,Files.readAllBytes(retained.resolve("appearance-schema-v1.sql")));}
    }
}
