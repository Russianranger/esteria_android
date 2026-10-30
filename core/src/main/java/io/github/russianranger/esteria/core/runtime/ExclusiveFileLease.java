package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.channels.FileLock;
import java.nio.channels.OverlappingFileLockException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/** Private fixed-name process lease. Reserve the canonical name before opening
 * its file: on POSIX, closing even a competing descriptor can release every
 * process lock on that inode. Callers must never unlink a live lease file. */
public final class ExclusiveFileLease implements AutoCloseable {
    private static final Map<Path,Object> OWNERS=new ConcurrentHashMap<>();
    private final Path path;
    private final Object reservation;
    private final FileChannel channel;
    private final FileLock lock;
    private boolean closed;

    private ExclusiveFileLease(Path path,Object reservation,FileChannel channel,FileLock lock) {
        this.path=path;this.reservation=reservation;this.channel=channel;this.lock=lock;
    }

    public static ExclusiveFileLease acquire(Path file,String busyMessage)throws IOException {
        if(file==null||busyMessage==null||busyMessage.isEmpty())throw new IllegalArgumentException("Lease path and refusal message required");
        Path path=file.toAbsolutePath().normalize(),parent=path.getParent();
        if(parent==null||!parent.equals(parent.toRealPath()))throw new IOException("Lease requires a canonical private parent");
        Object reservation=new Object();
        if(OWNERS.putIfAbsent(path,reservation)!=null)throw new IOException(busyMessage);
        FileChannel channel=null;FileLock lock=null;
        try {
            if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)) {
                if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.equals(path.toRealPath()))
                    throw new IOException("Lease file must be a canonical regular file");
                // A second name for the same inode defeats path admission.
                try {
                    if(((Number)Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS)).longValue()!=1)
                        throw new IOException("Lease file must have one private name");
                }catch(UnsupportedOperationException unsupported) {
                    // Non-POSIX providers do not have the POSIX close semantics.
                    if(Files.getFileStore(parent).supportsFileAttributeView("posix"))
                        throw new IOException("Private lease link count unavailable",unsupported);
                }
            }
            channel=FileChannel.open(path,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS);
            try{lock=channel.tryLock();}catch(OverlappingFileLockException busy){throw new IOException(busyMessage,busy);}
            if(lock==null)throw new IOException(busyMessage);
            return new ExclusiveFileLease(path,reservation,channel,lock);
        }catch(IOException|RuntimeException|Error failure) {
            try{if(lock!=null)lock.release();}catch(IOException close){failure.addSuppressed(close);}
            try{if(channel!=null)channel.close();}catch(IOException close){failure.addSuppressed(close);}
            if(channel==null||!channel.isOpen())OWNERS.remove(path,reservation);
            throw failure;
        }
    }

    public synchronized boolean isValid(){return !closed&&channel.isOpen()&&lock.isValid();}

    @Override public synchronized void close()throws IOException {
        if(closed)return;
        IOException failure=null;
        try{if(lock.isValid())lock.release();}catch(IOException error){failure=error;}
        try{channel.close();}catch(IOException error){if(failure==null)failure=error;else failure.addSuppressed(error);}
        // Keep admission reserved if a provider has not actually closed the FD.
        if(!channel.isOpen()){closed=true;OWNERS.remove(path,reservation);}
        else if(failure==null)failure=new IOException("Lease descriptor remains open");
        if(failure!=null)throw failure;
    }
}
