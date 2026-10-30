package io.github.russianranger.esteria.runtime;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Comparator;
import java.util.Set;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Actual18-file APK/private-file closure; executes no helper, SQL or server. */
@RunWith(AndroidJUnit4.class)
public final class ServerInstallationAssetsTest {
    @Test public void completeInstallationHelperClosureInstallsAndReusesExactBytes() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"installation-helper-test-");
        Set<String> helpers=Set.of("android_server_installation_setup.py","android_server_schema_setup.py","mysql_bootstrap.py",
            "mysql_service.py","server_content.py","server_schema_setup.py","server_schema_baseline.py","server_schema_adaptations.py",
            "server_update_setup.py","server_updater.py","server_playerbots_setup.py","owned_process_group.py","server_config.py","provision_local_realm.py",
            "provision_local_account.py","server/appearance-schema-v1.sql","server/appearance-schema.lock.json","local-server.json");
        try {
            Path generations=GuestHelperAssets.directory(root,"generations");
            String generation=GuestHelperAssets.install(context,"server-installation",generations,helpers);
            Path installed=generations.resolve(generation),retained=installed.resolve("local-server.json");
            FileTime stamp=FileTime.fromMillis(12345000);Files.setLastModifiedTime(retained,stamp);
            for(String name:helpers)try(var input=context.getAssets().open("server-installation/"+name)) {
                assertArrayEquals(input.readAllBytes(),Files.readAllBytes(installed.resolve(name)));
            }
            assertEquals(generation,GuestHelperAssets.install(context,"server-installation",generations,helpers));
            assertEquals(stamp,Files.getLastModifiedTime(retained));
            try(var files=Files.walk(installed)){assertEquals(18,files.filter(Files::isRegularFile).count());}
        } finally {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
    }
}
