package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;
import java.util.Map;

/** Component adapter for internal qualification. No launcher action uses this yet.
 * Starting a process does not establish display/audio/service or gameplay readiness.
 */
public final class ProotProcess {
    private ProotProcess() { }
    public static OwnedProcess start(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            OwnedProcess.GracefulStop gracefulStop) throws IOException {
        InstalledProot payload=InstalledProot.inspect(context);
        Path rootfs=installer.resolveCurrent(plan);
        if (rootfs==null) throw new IOException("The pinned runtime generation is not prepared");
        Path privateRoot=context.getFilesDir().getCanonicalFile().toPath();
        rootfs=privatePath(privateRoot,rootfs); work=privatePath(privateRoot,work); session=privatePath(privateRoot,session);
        if (session.startsWith(rootfs) || rootfs.startsWith(session) || session.equals(work) || work.startsWith(session))
            throw new IOException("Process session must be separate from runtime and persistent state");
        Path temporary=session.resolve("tmp"),logs=session.resolve("logs");
        // Session must be freshly created by the caller, avoiding stale sockets/logs.
        try (var entries=Files.list(session)) { if (entries.findAny().isPresent()) throw new IOException("Process session is not empty"); }
        Files.createDirectory(temporary,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.createDirectory(logs,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Path home=work.resolve("home");
        if (!Files.exists(home)) Files.createDirectory(home,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        privatePath(privateRoot,home);
        OwnedProcess.Specification spec=ProotLaunch.create(payload.tracer.toPath(),payload.loader.toPath(),rootfs,
            work,temporary,logs,guestCommand,guestEnvironment);
        return OwnedProcess.start(new NativeProcessBridge(),spec,gracefulStop);
    }
    private static Path privatePath(Path privateRoot,Path path) throws IOException {
        Path canonical=path.toRealPath();
        if (!canonical.startsWith(privateRoot) || canonical.equals(privateRoot) || !Files.isDirectory(canonical) ||
                !canonical.equals(path.toAbsolutePath().normalize())) throw new IOException("Runtime process paths must be private canonical directories");
        return canonical;
    }
}
