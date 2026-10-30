package io.github.russianranger.esteria.presentation;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import org.json.JSONException;
import org.json.JSONObject;

/** Checks the existing source-pinned X11/loader closure before executing it.
 * RuntimeInstaller already pins the archive; this also detects modified installed
 * X11 dependencies. It is not a same-UID filesystem security boundary.
 */
final class PresentationRuntimeChecks {
    private PresentationRuntimeChecks() { }
    static String verify(Context context,Path root,String wineArchive) throws IOException {
        byte[] raw;
        try(InputStream in=context.getAssets().open("x11-runtime.lock.json")) {
            ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buffer=new byte[8192];int count;
            while((count=in.read(buffer))!=-1) { if(out.size()+count>65536)throw new IOException("X11 source lock is oversized");out.write(buffer,0,count); }
            raw=out.toByteArray();
        }
        try {
            JSONObject lock=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(lock.getInt("formatVersion")!=1 || !lock.getString("scope").equals("pinned-wine-rootfs-x11-static-library-closure") ||
                    !lock.getString("runtimeArchiveSha256").equals(wineArchive) || !lock.getBoolean("preloadFileAbsent") ||
                    lock.getBoolean("androidQualified") || lock.getBoolean("inputQualified")) throw new IOException("Unexpected X11 runtime lock");
            JSONObject binaries=lock.getJSONObject("components"),configuration=lock.getJSONObject("loaderConfiguration"),links=lock.getJSONObject("symlinks");
            if(binaries.length()!=49 || configuration.length()!=4 || links.length()!=44)throw new IOException("Incomplete X11 runtime closure");
            long total=0;
            for(JSONObject group:new JSONObject[]{binaries,configuration})for(Iterator<String> it=group.keys();it.hasNext();) {
                String name=it.next();JSONObject expected=group.getJSONObject(name);long bytes=expected.getLong("bytes");
                if(bytes<1 || bytes>(32L<<20) || (total+=bytes)>(64L<<20))throw new IOException("X11 closure exceeds verified bounds");
                Path path=child(root,name);
                if(Files.isSymbolicLink(path)||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)!=bytes||
                        !path.toRealPath().startsWith(root))throw new IOException("X11 runtime file differs");
                MessageDigest digest=digest();long actual=0;
                try(InputStream in=Files.newInputStream(path)) { byte[] buffer=new byte[65536];int count;
                    while((count=in.read(buffer))!=-1) { actual+=count;if(actual>bytes)throw new IOException("X11 runtime file grew");digest.update(buffer,0,count); }
                }
                if(actual!=bytes||!hex(digest.digest()).equals(expected.getString("sha256")))throw new IOException("X11 runtime file identity differs");
            }
            for(Iterator<String> it=links.keys();it.hasNext();) {
                String name=it.next(),target=links.getString(name);Path link=child(root,name);
                // The current pinned archive has relative normalized targets;
                // RuntimeInstaller emits that same confined relative form.
                if(target.startsWith("/")||!Files.isSymbolicLink(link)||!Files.readSymbolicLink(link).toString().equals(target)||
                        !link.toRealPath().startsWith(root))throw new IOException("X11 runtime library alias differs");
            }
            if(Files.exists(root.resolve("etc/ld.so.preload"),LinkOption.NOFOLLOW_LINKS))throw new IOException("Unexpected global runtime preload");
            return hex(digest().digest(raw));
        }catch(JSONException|IllegalArgumentException error){throw new IOException("Invalid X11 source lock",error);}
    }
    private static Path child(Path root,String name)throws IOException {
        Path child=root.resolve(name).normalize();
        if(name.startsWith("/")||name.indexOf('\\')>=0||!child.startsWith(root)||child.equals(root)||!root.relativize(child).toString().equals(name))
            throw new IOException("Invalid X11 runtime path");
        return child;
    }
    private static MessageDigest digest(){try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException impossible){throw new AssertionError(impossible);}}
    private static String hex(byte[] bytes){StringBuilder text=new StringBuilder();for(byte b:bytes)text.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return text.toString();}
}
