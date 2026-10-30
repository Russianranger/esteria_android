package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Test-only strong ownership. A failed observation cleanup must precede SQL
 * shutdown and keep every owner plus the fixture lease reachable for retry. */
final class InstallationX64Lifetime implements AutoCloseable {
    interface Cleanup {void close()throws IOException;}
    interface Start {OwnedProcess start()throws IOException;}
    private static final Map<Path,InstallationX64Lifetime> OWNERS=new ConcurrentHashMap<>();
    private final Path root;
    private final ExclusiveFileLease lease;
    private OwnedProcess observer;
    private Cleanup database,installation;
    private boolean closed;
    private InstallationX64Lifetime(Path root,ExclusiveFileLease lease){this.root=root;this.lease=lease;}
    static synchronized InstallationX64Lifetime acquire(Path root)throws IOException {
        if(OWNERS.containsKey(root))throw new IOException("Previous installation fixture cleanup remains owned");
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(root.resolve(".installation-x64-fixture.lock"),"Installation fixture is already active");
        InstallationX64Lifetime owner=new InstallationX64Lifetime(root,lease);OWNERS.put(root,owner);return owner;
    }
    synchronized void installation(Cleanup cleanup)throws IOException {
        if(closed||installation!=null||cleanup==null)throw new IOException("Installation cleanup is already retained");installation=cleanup;
    }
    synchronized void database(Cleanup cleanup)throws IOException {
        if(closed||database!=null||cleanup==null)throw new IOException("Restarted database cleanup is already retained");database=cleanup;
    }
    synchronized OwnedProcess observe(Start start)throws IOException {
        if(closed||observer!=null||start==null)throw new IOException("Previous SQL observation remains owned");
        observer=start.start();if(observer==null)throw new IOException("Actual observation process owner required");return observer;
    }
    synchronized void finishObservation()throws IOException {
        if(observer==null)return;
        OwnedProcess child=observer;
        try {if(child.isAlive())child.stop(Duration.ZERO);}
        finally {if(!child.isAlive())observer=null;}
        if(child.isAlive())throw new IOException("SQL observation cleanup remains owned");
    }
    @Override public synchronized void close()throws IOException {
        if(closed)return;
        IOException failure=null;
        try{finishObservation();}catch(IOException error){if(observer!=null)throw error;failure=error;}
        // These callbacks are cleared only after successful cleanup. A timeout
        // leaves the actual captured handle and every later owner retained.
        try {
            if(database!=null){database.close();database=null;}
            if(installation!=null){installation.close();installation=null;}
            lease.close();closed=true;OWNERS.remove(root,this);
        }catch(IOException error){if(failure!=null)error.addSuppressed(failure);throw error;}
        if(failure!=null)throw failure;
    }
    static synchronized boolean retained(Path root){return OWNERS.containsKey(root);}
}
