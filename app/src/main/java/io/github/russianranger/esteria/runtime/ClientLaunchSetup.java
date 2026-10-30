package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.runtime.install.ClientLaunchView;
import io.github.russianranger.esteria.core.runtime.install.ClientUiStore;
import io.github.russianranger.esteria.core.runtime.install.ImportedUiSource;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.file.StandardOpenOption;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.List;

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
    /** Immutable, bounded text for the exact review decision; contains no addon contents. */
    public static final class UiReview {
        public final String digest, text;
        public final int conflicts, currentChanges, candidateChanges;
        private UiReview(ClientUiStore.Assessment assessment, boolean stale) {
            digest=assessment.digest; conflicts=assessment.conflicts.size();
            currentChanges=assessment.previousMutations.size(); candidateChanges=assessment.candidateMutations.size();
            StringBuilder result=new StringBuilder(stale
                    ? "The UI files changed after the previous review. Review this updated report before choosing again.\n\n"
                    : "Imported UI files differ from your retained writable version.\n\n");
            describe(result,"Changes in current UI",assessment.previousMutations);
            describe(result,"Changes in previously prepared imported UI",assessment.candidateMutations);
            describe(result,"Changes supplied by the import",assessment.sourceChanges);
            result.append("Conflicting paths: ").append(conflicts).append('\n');
            paths(result,assessment.conflicts);
            result.append("\nUse imported UI version selects the separate prepared tree, including any changes already made in that tree. Your current tree and saved variables are retained. Changes are not merged. Keep current UI leaves the new content waiting for review. Gameplay remains unavailable in this build.");
            text=result.toString();
        }
        private static void describe(StringBuilder result,String title,List<ClientUiStore.Change> changes) {
            int modified=0,added=0,deleted=0,renamed=0;
            for (ClientUiStore.Change change:changes) {
                switch(change.kind) {
                    case "modified": modified++; break;
                    case "added": added++; break;
                    case "deleted": deleted++; break;
                    case "case-renamed": renamed++; break;
                    default: throw new IllegalArgumentException("Unknown UI change kind");
                }
            }
            result.append(title).append(": ").append(modified).append(" modified, ").append(added)
                    .append(" added, ").append(deleted).append(" deleted, ").append(renamed).append(" renamed\n");
            paths(result,changes);
        }
        private static void paths(StringBuilder result,List<ClientUiStore.Change> changes) {
            int count=Math.min(4,changes.size());
            for (int i=0;i<count;i++) {
                ClientUiStore.Change item=changes.get(i);
                result.append("  ").append(item.kind).append(": ").append(item.path).append('\n');
            }
            if(changes.size()>count) result.append("  … and ").append(changes.size()-count).append(" more\n");
        }
    }
    public static final class ReviewRequired extends IOException {
        private static final long serialVersionUID=1L;
        public final UiReview review;
        private ReviewRequired(ClientUiStore.Assessment assessment,boolean stale) {
            super(stale ? "UI files changed; review the updated report" : "Imported UI changes need review");
            review=new UiReview(assessment,stale);
        }
    }
    /** Null means client assets have not been imported; installed binaries remain available.
     * Caller must serialize imports and keep the client stopped throughout this operation.
     */
    public static Prepared prepare(Context context, Path root, ClientRuntimeSetup client,
            RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        return prepare(context,root,client,null,progress,cancelled);
    }
    /** acceptedAssessment is the exact digest displayed by the launcher, never an implicit approval.
     * Activation rechecks the live UI trees under the store lock; stale choices cannot change its pointer.
     */
    public static Prepared prepare(Context context, Path root, ClientRuntimeSetup client,String acceptedAssessment,
            RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        if (!root.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Client view root differs from private application storage");
        Path binaries=client.current();
        if (binaries==null) throw new IOException("Prepare the reconstructed client before its launch view");
        return prepareStored(root,binaries,client.packagePlan(),acceptedAssessment,progress,cancelled);
    }
    /** Exclusive writable-view lease. Only the runtime package can create it;
     * the playing owner holds it until every client/presentation child is reaped. */
    static final class Lease implements AutoCloseable {
        final Path root,work;
        private final FileChannel channel;
        private final FileLock lock;
        private boolean closed;
        private Lease(Path root,Path work,FileChannel channel,FileLock lock) {
            this.root=root;this.work=work;this.channel=channel;this.lock=lock;
        }
        void require(Path expected)throws IOException {
            if(closed||!lock.isValid()||!root.equals(expected))throw new IOException("Owned client view lease is unavailable");
        }
        @Override public void close()throws IOException {
            if(closed)return;try{lock.release();}finally{channel.close();closed=true;}
        }
    }
    static Lease claim(Path root)throws IOException {
        if (!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS)||!root.toRealPath().equals(root))
            throw new IOException("Client view root must be canonical private storage");
        Path work=root.resolve("state/client-work"),current=root;
        for(Path part:root.relativize(work)) {
            current=current.resolve(part);
            if(!Files.exists(current,LinkOption.NOFOLLOW_LINKS))Files.createDirectory(current,
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            if(!Files.isDirectory(current,LinkOption.NOFOLLOW_LINKS)||!current.toRealPath().equals(current))
                throw new IOException("Client work directory must be a private canonical directory");
        }
        Path lockPath=work.resolve(".client-launch-setup.lock");
        if(Files.exists(lockPath,LinkOption.NOFOLLOW_LINKS)&&!Files.isRegularFile(lockPath,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid client setup operation lock");
        FileChannel channel=FileChannel.open(lockPath,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
        FileLock lock=null;
        try {
            Files.setPosixFilePermissions(lockPath,PosixFilePermissions.fromString("rw-------"));
            try{lock=channel.tryLock();}catch(java.nio.channels.OverlappingFileLockException busy){throw new IOException("Client view is already owned",busy);}
            if(lock==null)throw new IOException("Client view is already owned");
            return new Lease(root,work,channel,lock);
        }catch(IOException|RuntimeException error){try{if(lock!=null)lock.release();}finally{channel.close();}throw error;}
    }
    static Prepared prepareUnderOwnedLease(Context context,Path root,ClientRuntimeSetup client,Lease lease,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical client storage required");
        Path binaries=client.current();if(binaries==null)throw new IOException("Prepare the reconstructed client first");
        return prepareStoredUnderOwnedLease(root,binaries,client.packagePlan(),null,lease,progress,cancelled);
    }
    // Kept independent of Android services so real persistence/review behavior can be host-tested.
    static Prepared prepareStored(Path root,Path binaries,RuntimePackagePlan client,String acceptedAssessment,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        try(Lease lease=claim(root)) {
            return prepareStoredUnderOwnedLease(root,binaries,client,acceptedAssessment,lease,progress,cancelled);
        }
    }
    static Prepared prepareStoredUnderOwnedLease(Path root,Path binaries,RuntimePackagePlan client,String acceptedAssessment,Lease lease,
            RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        lease.require(root);
        if(acceptedAssessment!=null&&!acceptedAssessment.matches("[a-f0-9]{64}"))throw new IOException("Invalid UI review decision");
        RuntimeWork.Progress updates=progress==null?RuntimeWork.NONE:progress;
        RuntimeWork.Cancellation stop=cancelled==null?RuntimeWork.NEVER_CANCELLED:cancelled;
        Path work=lease.work;
        if(stop.isCancelled()||Thread.currentThread().isInterrupted())throw new RuntimeWork.CancelledException();
        GameDataImporter importer=new GameDataImporter(root.resolve("game"));
        Path data=importer.resolveCurrent();
        if(data==null) {
            if(acceptedAssessment!=null)throw new IOException("Imported data changed; prepare the runtime again before reviewing UI");
            return null;
        }
        String importedGeneration=data.getParent().getFileName().toString();
        ImportedUiSource source=ImportedUiSource.fromImportStore(root.resolve("game"),importedGeneration,stop);
        ClientUiStore ui=new ClientUiStore(work);
        ClientUiStore.Candidate candidate=ui.prepare(source,updates,stop);
        // Repeated preparation of the active inventory preserves mutations without a full UI hash.
        // New source inventories and explicit review choices require a bounded live assessment.
        if(acceptedAssessment!=null||!candidate.interfaceDirectory.equals(ui.current(stop))) {
            updates.update("client-ui-assessing","",0,-1);
            ClientUiStore.Assessment assessment=ui.assess(candidate,stop);
            if(acceptedAssessment!=null&&!acceptedAssessment.equals(assessment.digest))
                throw new ReviewRequired(assessment,true);
            if(acceptedAssessment==null&&assessment.requiresReview)throw new ReviewRequired(assessment,false);
            ui.activate(candidate,assessment.digest,acceptedAssessment!=null,stop);
        }
        if(!data.equals(importer.resolveCurrent()))throw new IOException("Imported data changed while preparing the view; retry after the import finishes");
        ClientLaunchView.Plan plan=new ClientLaunchView.Plan(binaries,client,data,importedGeneration,ui.selectedFor(source,stop));
        ClientLaunchView.Result view=new ClientLaunchView(work).prepare(plan,updates,stop);
        return new Prepared(work,data,plan,view);
    }
}
