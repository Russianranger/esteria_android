package io.github.russianranger.esteria.runtime;

import android.content.Context;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/** Small source-bound Python helpers, installed only from this APK's assets. */
final class GuestHelperAssets {
    private GuestHelperAssets() { }
    static Path directory(Path root,String relative) throws IOException {
        if (!root.isAbsolute() || !root.toRealPath().equals(root) || !Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Helper storage must be a private canonical directory");
        Path target=root;
        for(String part:relative.split("/")) {
            if(!part.matches("[A-Za-z0-9_.-]+") || part.equals(".") || part.equals(".."))
                throw new IOException("Invalid helper directory component");
            target=target.resolve(part);
            if(!Files.exists(target,LinkOption.NOFOLLOW_LINKS))
                Files.createDirectory(target,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            if(!Files.isDirectory(target,LinkOption.NOFOLLOW_LINKS) || !target.toRealPath().equals(target))
                throw new IOException("Helper directory contains a link or non-directory");
        }
        return target;
    }
    static String install(Context context,String assetPrefix,Path generations,Set<String> expected) throws IOException {
        if(!assetPrefix.matches("[a-z-]+") || expected.isEmpty() || expected.size()>16)
            throw new IOException("Invalid bundled helper set");
        byte[] manifest=asset(context,assetPrefix+"/manifest.json",16384);
        String generation=sha256(manifest);
        Path directory=directory(generations,generation);
        exactClosure(directory,expected);
        try {
            JSONObject descriptor=new JSONObject(new String(manifest,StandardCharsets.UTF_8));
            JSONObject files=descriptor.getJSONObject("files");
            Set<String> names=new HashSet<>();files.keys().forEachRemaining(names::add);
            if(descriptor.getInt("formatVersion")!=1 || !names.equals(expected))
                throw new IOException("Unexpected helper manifest");
            for(String name:expected) {
                if(!name.matches("[a-z_]+\\.py"))throw new IOException("Invalid helper filename");
                JSONObject pin=files.getJSONObject(name);
                byte[] bytes=asset(context,assetPrefix+"/"+name,131072);
                String digest=sha256(bytes);
                if(pin.getInt("bytes")!=bytes.length || !digest.equals(pin.getString("sha256")))
                    throw new IOException("Bundled helper identity differs");
                Path destination=directory.resolve(name);
                if(Files.exists(destination,LinkOption.NOFOLLOW_LINKS)) {
                    if(!Files.isRegularFile(destination,LinkOption.NOFOLLOW_LINKS) || Files.size(destination)!=bytes.length ||
                            !digest.equals(sha256(Files.readAllBytes(destination))))
                        throw new IOException("Prepared helper changed; existing files retained");
                    continue;
                }
                Path pending=Files.createTempFile(directory,".helper-",".tmp",
                        PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
                try {
                    Files.write(pending,bytes);
                    try(FileChannel file=FileChannel.open(pending,StandardOpenOption.WRITE)){file.force(true);}
                    Files.move(pending,destination,StandardCopyOption.ATOMIC_MOVE);
                } finally {Files.deleteIfExists(pending);}
            }
            try(FileChannel folder=FileChannel.open(directory,StandardOpenOption.READ)){folder.force(true);}
            exactClosure(directory,expected);
            return generation;
        } catch(JSONException error){throw new IOException("Invalid bundled helper metadata",error);}
    }
    private static void exactClosure(Path directory,Set<String> expected) throws IOException {
        // Python's script directory is importable. Reject extra modules/native
        // extensions and caches even when every expected helper still matches.
        // Interrupted writes can leave only these nonimportable private temp files.
        try(var files=Files.newDirectoryStream(directory)) {
            for(Path path:files) {
                String name=path.getFileName().toString();
                if((!expected.contains(name) && !name.matches("\\.helper-[0-9]+\\.tmp")) ||
                        !Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))
                    throw new IOException("Unexpected importable file in helper generation; original retained");
            }
        }
    }
    private static byte[] asset(Context context,String path,int maximum) throws IOException {
        try(InputStream input=context.getAssets().open(path);ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];
            for(int count;(count=input.read(buffer))!=-1;) {
                if(output.size()+count>maximum)throw new IOException("Bundled helper exceeds size bound");
                output.write(buffer,0,count);
            }
            return output.toByteArray();
        }
    }
    private static String sha256(byte[] bytes) throws IOException {
        try {
            StringBuilder result=new StringBuilder(64);
            for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))result.append(String.format(Locale.ROOT,"%02x",value&255));
            return result.toString();
        } catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
}
