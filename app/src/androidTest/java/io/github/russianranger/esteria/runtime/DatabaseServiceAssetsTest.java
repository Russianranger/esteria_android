package io.github.russianranger.esteria.runtime;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashSet;
import java.util.Set;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real APK assets and Android private storage only; does not execute Python/MySQL. */
@RunWith(AndroidJUnit4.class)
public final class DatabaseServiceAssetsTest {
    private static final Set<String> HELPERS=new HashSet<>(Arrays.asList("mysql_bootstrap.py","mysql_service.py"));
    private Context context;
    private Path root,generations;

    @Before public void preparePrivateFixture() throws Exception {
        context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"database-helper-test-");
        generations=GuestHelperAssets.directory(root,"generations");
    }

    @After public void removeOnlyOwnedFixture() throws Exception {
        if(root==null)return;
        // Files.walk does not follow symbolic links; all targets are owned by this fixture.
        try(var paths=Files.walk(root)) {
            for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);
        }
    }

    private Path install() throws IOException {
        String generation=GuestHelperAssets.install(context,"database-service",generations,HELPERS);
        assertTrue("Manifest identity is the immutable generation",generation.matches("[0-9a-f]{64}"));
        return generations.resolve(generation);
    }

    private byte[] bundled(String name) throws IOException {
        try(InputStream input=context.getAssets().open("database-service/"+name);
                ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];
            for(int count;(count=input.read(buffer))!=-1;)output.write(buffer,0,count);
            return output.toByteArray();
        }
    }

    private void expectRejected() throws Exception {
        try {install();fail("Changed or unapproved helper storage must be rejected");}
        catch(IOException expected) { /* The original files are checked by each caller. */ }
    }

    @Test public void actualBundledHelpersInstallAndRepeatWithoutRewriting() throws Exception {
        Path generation=install();
        Path bootstrap=generation.resolve("mysql_bootstrap.py");
        FileTime retained=FileTime.fromMillis(12345000);
        Files.setLastModifiedTime(bootstrap,retained);
        for(String name:HELPERS)assertArrayEquals(bundled(name),Files.readAllBytes(generation.resolve(name)));
        assertEquals(generation,install());
        assertEquals("Existing matching source must be reused",retained,Files.getLastModifiedTime(bootstrap));
        try(var files=Files.list(generation)) {assertEquals(2,files.count());}
    }

    @Test public void changedExistingHelperIsPreservedAndRefused() throws Exception {
        Path generation=install(),service=generation.resolve("mysql_service.py");
        byte[] changed=Files.readAllBytes(service);assertTrue(changed.length>0);changed[0]^=1;
        Files.write(service,changed);
        expectRejected();
        assertArrayEquals("A failed verification must not repair/replace an existing file",changed,Files.readAllBytes(service));
        assertArrayEquals(bundled("mysql_bootstrap.py"),Files.readAllBytes(generation.resolve("mysql_bootstrap.py")));
    }

    @Test public void partialGenerationResumesAndRetainsHarmlessInterruptedWrite() throws Exception {
        Path generation=install(),bootstrap=generation.resolve("mysql_bootstrap.py");
        FileTime retained=FileTime.fromMillis(12345000);Files.setLastModifiedTime(bootstrap,retained);
        Files.delete(generation.resolve("mysql_service.py"));
        Path interrupted=generation.resolve(".helper-123456.tmp");
        byte[] partial="private incomplete write".getBytes(StandardCharsets.US_ASCII);Files.write(interrupted,partial);
        assertEquals(generation,install());
        assertArrayEquals(bundled("mysql_service.py"),Files.readAllBytes(generation.resolve("mysql_service.py")));
        assertEquals(retained,Files.getLastModifiedTime(bootstrap));
        assertArrayEquals("Interrupted temporary bytes remain available for diagnosis",partial,Files.readAllBytes(interrupted));
    }

    @Test public void extraModulesNativeExtensionsAndCachesCannotEnterImportPath() throws Exception {
        Path generation=install();
        for(String name:Arrays.asList("json.py","mysql_bootstrap.so","unexpected.txt",".helper-notnumeric.tmp","__pycache__")) {
            Path foreign=generation.resolve(name);
            if(name.equals("__pycache__"))Files.createDirectory(foreign);
            else Files.write(foreign,new byte[]{1,2,3});
            expectRejected();
            assertTrue("Unapproved data is preserved on rejection",Files.exists(foreign,LinkOption.NOFOLLOW_LINKS));
            assertArrayEquals(bundled("mysql_service.py"),Files.readAllBytes(generation.resolve("mysql_service.py")));
            Files.delete(foreign);
        }
    }

    @Test public void expectedHelperSymlinkNeverReplacesOrWritesItsTarget() throws Exception {
        Path generation=install(),helper=generation.resolve("mysql_service.py"),target=root.resolve("retained-source");
        byte[] original=bundled("mysql_service.py");Files.write(target,original);
        Files.delete(helper);Files.createSymbolicLink(helper,target);
        expectRejected();
        assertTrue(Files.isSymbolicLink(helper));assertArrayEquals(original,Files.readAllBytes(target));
    }

    @Test public void temporarySymlinkDoesNotBypassClosure() throws Exception {
        Path generation=install(),target=root.resolve("retained-private-file"),link=generation.resolve(".helper-123456.tmp");
        byte[] original="retained".getBytes(StandardCharsets.US_ASCII);Files.write(target,original);
        Files.createSymbolicLink(link,target);
        expectRejected();
        assertTrue(Files.isSymbolicLink(link));assertArrayEquals(original,Files.readAllBytes(target));
    }
}
