package io.github.russianranger.esteria.core.runtime.install;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Filesystem/update qualification only; no ARM64 guest or game execution. */
@RunWith(AndroidJUnit4.class)
public final class RuntimeInstallationInstrumentedTest {
    private static Context context() {
        return InstrumentationRegistry.getInstrumentation().getTargetContext();
    }
    private static Path updateRoot() throws java.io.IOException {
        // Resolve Android's trusted /data/user/0 alias before strict no-link checks,
        // just as SessionService does for the real application storage root.
        return context().getFilesDir().toPath().toRealPath().resolve("instrumentation-update-contract");
    }
    @Test public void runtimeContracts() throws Exception {
        Path root = Files.createTempDirectory(context().getCacheDir().toPath(), "runtime-contracts-");
        try {
            RuntimeInstallerTests.main(new String[]{root.toString()});
        } finally {
            try (java.util.stream.Stream<Path> paths = Files.walk(root)) {
                for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator)
                    Files.delete(path);
            }
        }
    }
    @Test public void seedBeforeUpdate() throws Exception {
        assertEquals("CI starts with the first build", 1, context().getPackageManager().getPackageInfo(context().getPackageName(), 0).versionCode);
        Path root = updateRoot();
        assertFalse("Never seed over an existing probe", Files.exists(root));
        Files.createDirectory(root);
        List<RuntimeInstallerTests.Member> members = RuntimeInstallerTests.base();
        Path archive = RuntimeInstallerTests.tar(root, members);
        RuntimePackagePlan plan = RuntimeInstallerTests.plan(archive, members);
        RuntimeInstaller.Result installed = RuntimeInstallerTests.install(
                new RuntimeInstaller(root.resolve("store")), archive, plan);
        Files.write(root.resolve("archive-name"), archive.getFileName().toString().getBytes(StandardCharsets.UTF_8));
        Files.write(root.resolve("expected-generation"), installed.generation.getBytes(StandardCharsets.UTF_8));
        Files.write(root.resolve("character-save-sentinel"), "persistent-private-state".getBytes(StandardCharsets.UTF_8));
    }
    @Test public void verifyAfterUpdate() throws Exception {
        assertEquals("CI must install a newer version without uninstalling", 2, context().getPackageManager().getPackageInfo(context().getPackageName(), 0).versionCode);
        Path root = updateRoot();
        String name = new String(Files.readAllBytes(root.resolve("archive-name")), StandardCharsets.UTF_8);
        assertTrue("Probe archive must remain a direct file", name.matches("archive-[A-Za-z0-9-]+\\.tar\\.gz"));
        Path archive = root.resolve(name);
        RuntimePackagePlan plan = RuntimeInstallerTests.plan(archive, RuntimeInstallerTests.base());
        assertEquals(new String(Files.readAllBytes(root.resolve("expected-generation")), StandardCharsets.UTF_8), plan.generation);
        RuntimeInstaller installer = new RuntimeInstaller(root.resolve("store"));
        Path active = installer.resolveCurrent(plan);
        assertNotNull("Activated runtime pointer survived APK update", active);
        RuntimeInstaller.Result result = RuntimeInstallerTests.install(installer, archive, plan);
        assertTrue(result.alreadyInstalled);
        assertEquals(0, result.copiedBytes);
        assertTrue(Files.isSameFile(active.resolve("tool-hard"), active.resolve("usr/bin/tool")) || result.hardLinkCopies == 1);
        assertArrayEquals(Files.readAllBytes(active.resolve("tool-hard")), Files.readAllBytes(active.resolve("usr/bin/tool")));
        assertEquals("persistent-private-state", new String(Files.readAllBytes(root.resolve("character-save-sentinel")), StandardCharsets.UTF_8));
    }
}
