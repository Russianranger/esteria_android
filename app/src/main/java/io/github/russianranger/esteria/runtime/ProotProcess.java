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
import java.util.Collections;

/** Component adapter for internal qualification. No launcher action uses this yet.
 * Starting a process does not establish display/audio/service or gameplay readiness.
 */
public final class ProotProcess {
    private ProotProcess() { }
    public static OwnedProcess start(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            OwnedProcess.GracefulStop gracefulStop) throws IOException {
        return start(context,installer,plan,work,session,guestCommand,guestEnvironment,Collections.emptyList(),gracefulStop);
    }
    public static OwnedProcess start(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,OwnedProcess.GracefulStop gracefulStop) throws IOException {
        return OwnedProcess.start(new NativeProcessBridge(),specification(context,installer,plan,work,session,
            guestCommand,guestEnvironment,mounts,null),gracefulStop);
    }
    public static OwnedProcess startPresentation(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,ProotLaunch.PresentationBindings presentation) throws IOException {
        if (presentation==null) throw new IOException("Explicit presentation IPC bindings required");
        return OwnedProcess.start(new NativeProcessBridge(),specification(context,installer,plan,work,session,
            guestCommand,guestEnvironment,mounts,presentation),null);
    }
    /** Explicit console pipe; the callback must send a source-supported command and check delivery. */
    public static OwnedProcess startInteractive(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,OwnedProcess.GracefulInputStop gracefulStop) throws IOException {
        OwnedProcess.Specification base=specification(context,installer,plan,work,session,guestCommand,guestEnvironment,mounts,null);
        OwnedProcess.Specification interactive=new OwnedProcess.Specification(base.executable,base.arguments,base.environment,
            base.cwd,base.stdout,base.stderr,true);
        return OwnedProcess.startInteractive(new NativeProcessBridge(),interactive,gracefulStop);
    }
    private static OwnedProcess.Specification specification(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,ProotLaunch.PresentationBindings presentation) throws IOException {
        InstalledProot payload=InstalledProot.inspect(context);
        Path rootfs=installer.resolveCurrent(plan);
        if (rootfs==null) throw new IOException("The pinned runtime generation is not prepared");
        Path privateRoot=context.getFilesDir().getCanonicalFile().toPath();
        rootfs=privatePath(privateRoot,rootfs); work=privatePath(privateRoot,work); session=privatePath(privateRoot,session);
        if (mounts == null) throw new IOException("Runtime provider mounts are missing");
        for (ProotLaunch.Mount mount : mounts) {
            if (mount == null) throw new IOException("Runtime provider mount is missing");
            privatePath(privateRoot,mount.source);
        }
        if (presentation!=null) {
            privatePath(privateRoot,presentation.endpoints); privatePath(privateRoot,presentation.x11);
        }
        if (session.startsWith(rootfs) || rootfs.startsWith(session) || session.startsWith(work) || work.startsWith(session))
            throw new IOException("Process session must be separate from runtime and persistent state");
        Path temporary=session.resolve("tmp"),logs=session.resolve("logs");
        // Session must be freshly created by the caller, avoiding stale sockets/logs.
        try (var entries=Files.list(session)) { if (entries.findAny().isPresent()) throw new IOException("Process session is not empty"); }
        Files.createDirectory(temporary,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.createDirectory(logs,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Path home=work.resolve("home");
        if (!Files.exists(home)) Files.createDirectory(home,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        privatePath(privateRoot,home);
        return ProotLaunch.create(payload.tracer.toPath(),payload.loader.toPath(),rootfs,
            work,temporary,logs,guestCommand,guestEnvironment,mounts,presentation);
    }
    private static Path privatePath(Path privateRoot,Path path) throws IOException {
        Path canonical=path.toRealPath();
        if (!canonical.startsWith(privateRoot) || canonical.equals(privateRoot) || !Files.isDirectory(canonical) ||
                !canonical.equals(path.toAbsolutePath().normalize())) throw new IOException("Runtime process paths must be private canonical directories");
        return canonical;
    }
}
