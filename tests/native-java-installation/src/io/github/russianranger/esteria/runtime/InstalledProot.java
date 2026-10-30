package io.github.russianranger.esteria.runtime;

import android.content.Context;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Map;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/** Qualification-only Linux payload locator, compiled instead of the Android
 * APK locator. ProotProcess, ProotLaunch, JNI ownership, PRoot and SQL remain
 * real implementations. This class cannot establish Android/Bionic execution.
 */
public final class InstalledProot {
    private static final int MAX_RECEIPT=64*1024,MAX_PAYLOAD=16*1024*1024;
    private static final String SOURCE="492043660b1370e1910c8b8ca2b93be1f637f4929034f575591f14e67e015243";
    private static final String EXITKILL="509160bd6ec3663d525fa0e795a7bb45b8ccc283a6de8e1398e8cd6624fe86de";
    private static final Map<String,String> COMPONENTS=Map.of(
        "proot-source.tar.gz","d43ad342bb2e8f4d2afe6119b5ec3a1d8bb912d5897e2db7d2ddf928548c1c84",
        "talloc-2.4.3.tar.gz","dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd",
        "build-proot.sh","7ddcee055714f27c2a53fea816c8d43171efc54b655771e979735a30ba343319",
        "native/proot-sysvipc.patch","e8e3cb956bdb8b1bcbdf72a23b67ad86fc33fa51430f3a1ee37e1a053f5f0330",
        "native/proot-acceleration.patch","46ab8e6f80260044bccbd831e22a7fc3a376e45ef945772cac790485ab70306f");

    public final File tracer,loader;
    /** The native qualification receipt identity, never an Android source lock. */
    public final String sourceLockSha256;
    private InstalledProot(Path tracer,Path loader,String receiptSha256) {
        this.tracer=tracer.toFile();this.loader=loader.toFile();sourceLockSha256=receiptSha256;
    }

    public static InstalledProot inspect(Context context)throws IOException {
        if(context==null||!"Linux".equals(System.getProperty("os.name"))||
                !Set.of("aarch64","arm64").contains(System.getProperty("os.arch","")))
            throw new IOException("Native Linux ARM64 qualification context required");
        Path directory=canonicalProperty("esteria.native.proot.dir",true);
        Path receipt=canonicalProperty("esteria.native.proot.receipt",false);
        if(!directory.equals(receipt.getParent())||!receipt.getFileName().toString().equals("ownership-evidence.json"))
            throw new IOException("Exact native PRoot ownership receipt required");
        byte[] raw=bounded(receipt,MAX_RECEIPT);
        try {
            JSONObject proof=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(proof.getInt("formatVersion")!=1||!"native-linux-proot-ownership".equals(proof.getString("scope"))||
                    !Set.of("aarch64","arm64").contains(proof.getString("machine"))||
                    !"native ELF64 only".equals(proof.getString("linuxGuestScope"))||proof.getInt("buildJobs")!=1||
                    !SOURCE.equals(proof.getString("sourceArchiveSha256"))||!EXITKILL.equals(proof.getString("ownershipPatchSha256"))||
                    !proof.getBoolean("linuxTracerDeathOwnershipQualified")||proof.getBoolean("androidBridgeExecuted")||
                    proof.getBoolean("androidRuntimeQualified")||proof.getBoolean("gameLoginQualified")||proof.getInt("normalTreeExit")!=0)
                throw new IOException("Native PRoot ownership proof scope differs");
            JSONObject components=proof.getJSONObject("sourceComponents");
            if(!components.keySet().equals(COMPONENTS.keySet()))throw new IOException("Native PRoot source component set differs");
            for(Map.Entry<String,String> component:COMPONENTS.entrySet())
                if(!component.getValue().equals(components.getString(component.getKey())))
                    throw new IOException("Native PRoot source component identity differs");
            JSONObject fixed=proof.getJSONObject("fixed"),baseline=proof.getJSONObject("baseline");
            if(fixed.getInt("detachedSessionLeaders")!=2||fixed.getInt("tracees")!=3||fixed.getInt("terminatedAfterTracerKill")!=3||
                    baseline.getInt("detachedSessionLeaders")!=2||baseline.getInt("tracees")!=3||baseline.getInt("terminatedAfterTracerKill")!=0)
                throw new IOException("Native PRoot ownership execution proof is incomplete");
            Path tracer=payload(directory,"proot-owned",proof.getString("ownedProotSha256"),false);
            Path loader=payload(directory,"loader",proof.getString("loaderSha256"),true);
            return new InstalledProot(tracer,loader,sha256(raw));
        }catch(JSONException error){throw new IOException("Invalid native PRoot qualification receipt",error);}
    }

    private static Path canonicalProperty(String key,boolean directory)throws IOException {
        String value=System.getProperty(key);
        if(value==null||value.isEmpty())throw new IOException("Explicit native PRoot qualification properties required");
        Path path;
        try{path=Path.of(value);}catch(RuntimeException invalid){throw new IOException("Invalid native qualification path",invalid);}
        if(!path.isAbsolute()||!path.normalize().equals(path)||!path.equals(path.toRealPath())||
                (directory?!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS):!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)))
            throw new IOException("Canonical plain native qualification path required");
        return path;
    }
    private static Path payload(Path directory,String name,String expected,boolean loader)throws IOException {
        Path path=directory.resolve(name);
        if(!expected.matches("[a-f0-9]{64}")||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||
                !path.equals(path.toRealPath())||!Files.isExecutable(path))throw new IOException("Invalid native PRoot qualification payload");
        long size=Files.size(path);
        if(size<64||size>MAX_PAYLOAD)throw new IOException("Native PRoot payload exceeds bound");
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] header=input.readNBytes(64);int type=header.length==64?(header[16]&255)|((header[17]&255)<<8):-1;
            if(header.length!=64||header[0]!=0x7f||header[1]!='E'||header[2]!='L'||header[3]!='F'||header[4]!=2||header[5]!=1||
                    header[6]!=1||(header[18]&255)!=183||header[19]!=0||(loader?type!=2:type!=2&&type!=3))
                throw new IOException("Native ARM64 PRoot payload ELF format differs");
            MessageDigest digest=MessageDigest.getInstance("SHA-256");digest.update(header);long count=header.length;
            byte[] buffer=new byte[65536];
            for(int read;(read=input.read(buffer))!=-1;) {
                count+=read;if(count>size)throw new IOException("Native PRoot payload changed during verification");
                digest.update(buffer,0,read);
            }
            if(count!=size||Files.size(path)!=size||!hex(digest.digest()).equals(expected))
                throw new IOException("Native ARM64 PRoot payload identity differs");
        }catch(NoSuchAlgorithmException unavailable){throw new IOException("SHA256 unavailable",unavailable);}
        return path;
    }
    private static byte[] bounded(Path path,int limit)throws IOException {
        long size=Files.size(path);
        if(size<=0||size>limit)throw new IOException("Native qualification file exceeds bound");
        try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes=input.readNBytes(limit+1);
            if(bytes.length!=size||bytes.length>limit||Files.size(path)!=size)throw new IOException("Native qualification file changed or exceeded bound");
            return bytes;
        }
    }
    private static String sha256(byte[] bytes)throws IOException {
        try {return hex(MessageDigest.getInstance("SHA-256").digest(bytes));
        }catch(NoSuchAlgorithmException unavailable){throw new IOException("SHA256 unavailable",unavailable);}
    }
    private static String hex(byte[] bytes){StringBuilder value=new StringBuilder(64);
        for(byte part:bytes)value.append(String.format(java.util.Locale.ROOT,"%02x",part&255));
        return value.toString();}
}
