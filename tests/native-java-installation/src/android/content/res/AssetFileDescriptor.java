package android.content.res;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** File-backed asset metadata. Returned streams own their real descriptors. */
public final class AssetFileDescriptor implements AutoCloseable {
    private final Path path;
    AssetFileDescriptor(Path path){this.path=path;}
    public long getLength()throws IOException{return Files.size(path);}
    public InputStream createInputStream()throws IOException{return Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);}
    @Override public void close(){/* This metadata wrapper holds no descriptor. */}
}
