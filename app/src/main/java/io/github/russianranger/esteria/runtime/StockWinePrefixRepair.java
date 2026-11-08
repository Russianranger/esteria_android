package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.StockWinePrefix;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.presentation.ClientPresentationSession;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

/** The named client-runtime action can recover a verified interrupted stock prefix
 * independently of client import, shader preparation, SQL or a game session. */
public final class StockWinePrefixRepair {
    private StockWinePrefixRepair() { }

    // Keep the exact lease and presentation strongly reachable across a native
    // reap failure. Each cleanup attempt returns within its own stop budget.
    private static final ConcurrentHashMap<Path,Owner> OWNERS=new ConcurrentHashMap<>();
    private static final class Owner {
        final ClientLaunchSetup.Lease work;
        ClientPresentationSession presentation;
        boolean operating=true;
        Owner(ClientLaunchSetup.Lease work) {this.work=work;}
        void closePresentation()throws IOException {
            if(presentation==null)return;
            try {presentation.close(Duration.ofSeconds(5));}
            finally {if(presentation.isClosed())presentation=null;}
        }
        void releaseIfStopped(Path root)throws IOException {
            if(presentation==null) {
                work.close();
                OWNERS.remove(root,this);
            }
        }
    }

    public static void retryPendingCleanup(Path root)throws IOException {
        Owner owner=OWNERS.get(root);
        if(owner==null)return;
        synchronized(owner) {
            if(owner.operating)throw new IOException("Client runtime repair is still owned");
            IOException previous=owner.presentation==null?null:owner.presentation.cleanupFailure();
            int previousSecondary=previous==null?0:previous.getSuppressed().length;
            try {owner.closePresentation();}
            catch(IOException failure) {
                // The prior attempt already reported its failure. Presentation retains
                // that same exception even when a later attempt finishes successfully.
                if(owner.presentation!=null || failure!=previous || failure.getSuppressed().length!=previousSecondary)
                    throw failure;
            } finally {owner.releaseIfStopped(root);}
        }
    }

    /** False delegates ordinary absent/complete cases to the existing client-runtime repair. */
    public static boolean runIfRequired(Context context,Path root,RuntimeWork.Progress progress,
            RuntimeWork.Cancellation cancelled)throws IOException {
        if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Wine prefix repair requires a worker");
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Canonical app storage required");
        if(!"stock-3.3.5a".equals(BuildConfig.CONTENT_PROFILE))return false;
        retryPendingCleanup(root);
        RuntimeSetup wine=new RuntimeSetup(context,root);
        Path runtime=wine.current();
        if(runtime==null)return false;
        ClientLaunchSetup.Lease work=ClientLaunchSetup.claim(root);
        Owner held=new Owner(work);
        if(OWNERS.putIfAbsent(root,held)!=null) {
            work.close();
            throw new IOException("Previous Wine prefix repair still requires cleanup");
        }
        Throwable failure=null;
        try {
            StockWinePrefix prefix=StockWinePrefix.inspect(work.work,runtime,wine.archiveSha256());
            if(prefix.status()==StockWinePrefix.Status.UNRECOGNIZED)
                throw new IOException("Wine prefix does not match the supported interrupted installation. Existing files were preserved.");
            if(!prefix.requiresRepair())return false;
            if(cancelled.isCancelled())throw new RuntimeWork.CancelledException();
            if(prefix.status()==StockWinePrefix.Status.RESUME && prefix.finishVerifiedIfComplete(work.workLease()))return true;
            ClientPresentationSession.Prepared prepared=ClientPresentationSession.Prepared.inspect(context,work.work);
            if(!runtime.equals(wine.current()) || !prepared.wineArchiveSha256.equals(wine.archiveSha256()))
                throw new IOException("Selected Wine runtime changed before prefix repair");
            held.presentation=ClientPresentationSession.begin(context,prepared,null);
            Throwable primary=null;
            try {
                held.presentation.updateStockWinePrefix(work.workLease(),progress,cancelled);
            } catch(IOException|RuntimeException|Error error) {
                primary=error;
                throw error;
            } finally {
                try { held.closePresentation(); }
                catch(IOException cleanup) {if(primary!=null)primary.addSuppressed(cleanup);else throw cleanup;}
            }
            if(cancelled.isCancelled())throw new RuntimeWork.CancelledException();
            if(!runtime.equals(wine.current()))throw new IOException("Selected Wine runtime changed during prefix repair");
            progress.update("client-prefix-verify","",0,-1);
            prefix.finishRepair(work.workLease());
            return true;
        } catch(IOException|RuntimeException|Error error) {
            failure=error;
            throw error;
        } finally {
            synchronized(held) {
                held.operating=false;
                try {held.releaseIfStopped(root);}
                catch(IOException cleanup){if(failure!=null)failure.addSuppressed(cleanup);else throw cleanup;}
            }
        }
    }
}
