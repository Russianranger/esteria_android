package android.content.res;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** Reads only preverified qualification assets; never emulates an APK runtime. */
public final class AssetManager {
    private final Path root;
    public AssetManager(Path root)throws IOException {
        if(!root.isAbsolute()||!root.equals(root.toRealPath())||!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Canonical qualification asset directory required");
        this.root=root;
    }
    private Path file(String name)throws IOException {
        if(name==null||name.length()>256||!name.matches("[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"))
            throw new IOException("Invalid qualification asset name");
        for(String part:name.split("/"))if(part.equals(".")||part.equals(".."))throw new IOException("Invalid asset component");
        Path path=root.resolve(name);
        if(!path.equals(path.normalize())||!path.startsWith(root)||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.equals(path.toRealPath()))
            throw new java.io.FileNotFoundException("Missing plain qualification asset");
        return path;
    }
    public InputStream open(String name)throws IOException{return Files.newInputStream(file(name),LinkOption.NOFOLLOW_LINKS);}
    public AssetFileDescriptor openFd(String name)throws IOException{return new AssetFileDescriptor(file(name));}
}
