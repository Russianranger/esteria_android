package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.runtime.install.ClientLaunchView;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;

/** Prepares a stopped client's writable view; this neither starts Wine nor admits gameplay. */
public final class ClientLaunchSetup {
    private ClientLaunchSetup() { }
    public static final class Prepared {
        public final Path work, importedData;
        public final ClientLaunchView.Plan plan;
        public final ClientLaunchView.Result view;
        private Prepared(Path work, Path data, ClientLaunchView.Plan plan, ClientLaunchView.Result view) {
            this.work=work; importedData=data; this.plan=plan; this.view=view;
        }
    }
    /** Null means client assets have not been imported; installed binaries remain available. */
    public static Prepared prepare(Context context, Path root, ClientRuntimeSetup client,
            RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        if (!root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Client view root differs from private application storage");
        Path data=new GameDataImporter(root.resolve("game")).resolveCurrent();
        if (data==null) return null;
        Path binaries=client.current();
        if (binaries==null) throw new IOException("Prepare the reconstructed client before its launch view");
        String importedGeneration=data.getParent().getFileName().toString();
        ClientLaunchView.Plan plan=new ClientLaunchView.Plan(binaries,client.packagePlan(),data,importedGeneration);
        Path work=root.resolve("state/client-work"), current=root;
        for (Path part:root.relativize(work)) {
            current=current.resolve(part);
            if (!Files.exists(current,LinkOption.NOFOLLOW_LINKS))
                Files.createDirectory(current,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            if (!Files.isDirectory(current,LinkOption.NOFOLLOW_LINKS)||!current.toRealPath().equals(current))
                throw new IOException("Client work directory must be a private canonical directory");
        }
        ClientLaunchView.Result view=new ClientLaunchView(work).prepare(plan,progress,cancelled);
        return new Prepared(work,data,plan,view);
    }
}
