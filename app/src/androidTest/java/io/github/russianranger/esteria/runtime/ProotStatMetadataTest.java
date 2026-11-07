package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Build;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.FileTime;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Isolated real guest metadata qualification; never enables a production cache. */
@RunWith(AndroidJUnit4.class)
public final class ProotStatMetadataTest {
    private static final String GENERATION="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    private static final String PRIMARY="/work/server-data/generations/"+GENERATION;
    private static final String[] FIELDS={"dev","ino","mode","uid","gid","nlink","size","mtimeNs","ctimeNs"};
    private static final String[] VIEWS={"work","data","rawWork","rawData"};
    private static final String[] FINAL={"generation","dataRoot","receipt","regular","directory","symlink","ancestor","ancestorLeaf"};
    private static final String[] ROOTFS={"probe","probe-owner","probe-plugin.so","lib/x86_64-linux-gnu/libc.so.6","lib64/ld-linux-x86-64.so.2"};
    private static byte[] bounded(InputStream incoming,int maximum)throws IOException {
        ByteArrayOutputStream output=new ByteArrayOutputStream();byte[] block=new byte[65536];
        for(int count;(count=incoming.read(block))!=-1;){if(output.size()+count>maximum)throw new IOException("Stat fixture byte bound");output.write(block,0,count);}
        return output.toByteArray();
    }
    private static byte[] asset(Context context,String name,int maximum)throws IOException {
        try(InputStream input=context.getAssets().open(name)){return bounded(input,maximum);}
    }
    private static String hash(Path file)throws Exception {
        MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] block=new byte[65536];
        try(InputStream input=Files.newInputStream(file)){for(int count;(count=input.read(block))!=-1;)digest.update(block,0,count);}
        StringBuilder out=new StringBuilder(64);for(byte value:digest.digest())out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();
    }
    private static void identity(Path file,JSONObject pin)throws Exception {
        assertEquals(pin.getLong("bytes"),Files.size(file));assertEquals(pin.getString("sha256"),hash(file));
    }
    private static Path directory(Path file)throws IOException {
        Files.createDirectory(file);Files.setPosixFilePermissions(file,PosixFilePermissions.fromString("rwx------"));return file;
    }
    private static void copy(Context context,String source,Path target,JSONObject pin)throws Exception {
        assertTrue(pin.getLong("bytes")>0&&pin.getLong("bytes")<=16L*1024*1024);Files.createDirectories(target.getParent());
        try(InputStream input=context.getAssets().open(source);OutputStream output=Files.newOutputStream(target,StandardOpenOption.CREATE_NEW)) {
            byte[] block=new byte[65536];long total=0;
            for(int count;(count=input.read(block))!=-1;){total+=count;assertTrue(total<=pin.getLong("bytes"));output.write(block,0,count);}
            assertEquals(pin.getLong("bytes"),total);
        }
        Files.setPosixFilePermissions(target,PosixFilePermissions.fromString("rwx------"));identity(target,pin);
    }
    private static Set<String> keys(JSONObject value) {Set<String> result=new HashSet<>();value.keys().forEachRemaining(result::add);return result;}
    private static void equalTuples(JSONObject first,JSONObject second)throws Exception {
        assertEquals(new HashSet<>(Arrays.asList(FIELDS)),keys(first));assertEquals(keys(first),keys(second));
        for(String field:FIELDS){assertTrue(first.get(field) instanceof String);assertTrue(first.getString(field).matches("0|[1-9][0-9]{0,19}"));assertEquals(field,first.getString(field),second.getString(field));}
    }
    private static JSONObject views(JSONObject observation)throws Exception {
        assertEquals(new HashSet<>(Arrays.asList(VIEWS)),keys(observation));
        JSONObject first=observation.getJSONObject("work");for(String view:VIEWS)equalTuples(first,observation.getJSONObject(view));return first;
    }
    private static JSONObject readReport(Path file)throws Exception {
        try(InputStream incoming=Files.newInputStream(file)){return new JSONObject(new String(bounded(incoming,65536),StandardCharsets.UTF_8));}
    }
    /** Exercise the Java filesystem provider used by PreparedDataCachePin.
     * Guest stat success cannot establish these Android NIO capabilities. */
    private static JSONObject javaMetadata(Path root)throws Exception {
        Path directory=directory(root.resolve("java-metadata")),file=directory.resolve("regular");
        Files.write(file,"AAAAAAAA".getBytes(StandardCharsets.US_ASCII),StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(file,PosixFilePermissions.fromString("rw-------"));
        assertEquals("rwx------",PosixFilePermissions.toString(Files.getPosixFilePermissions(directory,LinkOption.NOFOLLOW_LINKS)));
        assertEquals("rw-------",PosixFilePermissions.toString(Files.getPosixFilePermissions(file,LinkOption.NOFOLLOW_LINKS)));
        BasicFileAttributes first=Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        assertTrue(first.isRegularFile());assertEquals(8,first.size());assertNotNull("Android NIO fileKey is required",first.fileKey());
        assertEquals(first.fileKey(),Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).fileKey());
        Object links=Files.getAttribute(file,"unix:nlink",LinkOption.NOFOLLOW_LINKS);
        assertTrue("Android NIO unix:nlink must be numeric",links instanceof Number);assertEquals(1,((Number)links).longValue());
        FileTime fixed=FileTime.from(1700000000123456789L,TimeUnit.NANOSECONDS);
        Files.setLastModifiedTime(file,fixed);
        assertEquals(fixed,Files.getLastModifiedTime(file,LinkOption.NOFOLLOW_LINKS));
        Object before=Files.getAttribute(file,"unix:ctime",LinkOption.NOFOLLOW_LINKS);
        assertTrue("Android NIO unix:ctime must be a FileTime",before instanceof FileTime);
        Thread.sleep(2);Files.write(file,"BBBBBBBB".getBytes(StandardCharsets.US_ASCII));Files.setLastModifiedTime(file,fixed);
        assertEquals(8,Files.size(file));assertEquals(fixed,Files.getLastModifiedTime(file,LinkOption.NOFOLLOW_LINKS));
        assertNotEquals("A same-size restored-mtime edit must expose changed ctime",before,Files.getAttribute(file,"unix:ctime",LinkOption.NOFOLLOW_LINKS));
        assertEquals(first.fileKey(),Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).fileKey());
        Path replacement=directory.resolve("replacement");Files.write(replacement,Files.readAllBytes(file),StandardOpenOption.CREATE_NEW);
        Files.setPosixFilePermissions(replacement,PosixFilePermissions.fromString("rw-------"));Files.setLastModifiedTime(replacement,fixed);
        Files.move(replacement,file,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
        assertEquals(fixed,Files.getLastModifiedTime(file,LinkOption.NOFOLLOW_LINKS));
        assertNotEquals("Same-content replacement must expose a new fileKey",first.fileKey(),Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).fileKey());
        Path symbolic=directory.resolve("symbolic");Files.createSymbolicLink(symbolic,file);
        assertTrue(Files.readAttributes(symbolic,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS).isSymbolicLink());
        boolean refused=false;try(InputStream ignored=Files.newInputStream(symbolic,LinkOption.NOFOLLOW_LINKS)){ }
        catch(IOException expected){refused=true;}assertTrue("Java NIO must reject a no-follow symlink open",refused);
        return new JSONObject().put("scope","android-java-nio-private-cache-metadata")
            .put("fileKeyAvailable",true).put("fileKeyStable",true).put("unixLinkCount",1)
            .put("privateFileAndDirectoryPermissions",true).put("nanosecondMtimePreserved",true)
            .put("sameSizeRestoredMtimeChangedCtime",true).put("replacementChangedFileKey",true)
            .put("noFollowSymlinkOpenRejected",true).put("productionCacheEnabled",false);
    }
    @Test public void statTuplesSurviveAliasesAndExposeMutations()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext(),testContext=InstrumentationRegistry.getInstrumentation().getContext();
        assertEquals(33,Build.VERSION.SDK_INT);assertEquals(35,context.getApplicationInfo().targetSdkVersion);
        assertTrue(BuildConfig.DEBUG);assertTrue(BuildConfig.SOURCE_REVISION.matches("[0-9a-f]{40}"));
        assertTrue(Arrays.asList(Build.SUPPORTED_ABIS).contains("x86_64"));assertFalse(BuildConfig.PROOT_PACKAGED);
        JSONObject build=new JSONObject(new String(asset(context,"proot-probe/build-evidence.json",65536),StandardCharsets.UTF_8));
        JSONObject statBuild=new JSONObject(new String(asset(testContext,"proot-stat-probe/build-evidence.json",128*1024),StandardCharsets.UTF_8));
        assertEquals("android-x86_64-glibc-stat-fixture-build-only",statBuild.getString("scope"));
        assertEquals(BuildConfig.SOURCE_REVISION,statBuild.getString("sourceRevision"));assertTrue(statBuild.getBoolean("sourceSnapshotExact"));
        Path nativeRoot=java.nio.file.Paths.get(context.getApplicationInfo().nativeLibraryDir);
        Path tracer=nativeRoot.resolve("libproot_probe.so"),loader=nativeRoot.resolve("libproot_probe_loader.so");
        identity(tracer,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe.so"));
        identity(loader,build.getJSONObject("nativeFiles").getJSONObject("libproot_probe_loader.so"));
        Path root=directory(context.getFilesDir().toPath().toRealPath().resolve("proot-stat-session"));
        Path rootfs=directory(root.resolve("rootfs")),work=directory(root.resolve("work"));
        Path temporary=directory(root.resolve("tmp")),logs=directory(root.resolve("logs"));
        for(String name:ROOTFS)copy(context,"proot-probe/rootfs/"+name,rootfs.resolve(name),build.getJSONObject("rootfsFiles").getJSONObject(name));
        copy(testContext,"proot-stat-probe/probe-stat",rootfs.resolve("probe-stat"),statBuild.getJSONObject("fixture"));
        Path generations=work.resolve("server-data/generations");Files.createDirectories(generations);
        Path generation=directory(generations.resolve(GENERATION));directory(generation.resolve("data"));
        JSONObject mutation=null,relaunch=null;JSONArray exits=new JSONArray(),forced=new JSONArray(),remaining=new JSONArray();
        for(String mode:Arrays.asList("mutate","verify")) {
            Path run=directory(logs.resolve(mode));Map<String,String> environment=new HashMap<>();
            environment.put("PROOT_LOADER",loader.toString());environment.put("PROOT_NO_SECCOMP","1");
            environment.put("PROOT_TMP_DIR",temporary.toString());environment.put("PATH","/system/bin");
            OwnedProcess child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(tracer,
                Arrays.asList("--kill-on-exit","--sysvipc","-0","-r",rootfs.toString(),"-b","/dev","-b","/proc",
                    "-b",work+":/work","-b",generation+":/esteria-data!","-b",temporary+":/tmp","-w","/work",
                    "/probe-stat",mode,PRIMARY,"/esteria-data"),environment,work,run.resolve("stdout.log"),run.resolve("stderr.log")),null);
            try {
                long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(35);
                while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(10);
                assertFalse("Real PRoot child must exit and reap",child.isAlive());assertNull(child.failure());assertFalse(child.wasForced());
                assertEquals(0,child.exitCode());assertEquals(0,child.diagnostics()[4]);
                exits.put(child.exitCode());forced.put(child.wasForced());remaining.put(child.diagnostics()[4]);
                JSONObject value=readReport(run.resolve("stdout.log"));assertEquals(mode,value.getString("mode"));
                assertEquals("linux-glibc-stat-alias-mutation-fixture",value.getString("scope"));
                assertTrue(value.getBoolean("metadataVisibleMutationsOnly"));assertFalse(value.getBoolean("unchangedMetadataCorruptionDetectionClaimed"));
                JSONObject observations=value.getJSONObject("observations");for(String name:keys(observations))views(observations.getJSONObject(name));
                JSONObject snapshot=value.getJSONObject("finalSnapshot");assertEquals(new HashSet<>(Arrays.asList(FINAL)),keys(snapshot));
                for(String name:FINAL)views(snapshot.getJSONObject(name));
                if(mode.equals("mutate"))mutation=value;else relaunch=value;
            } finally {if(child.isAlive())child.stop(Duration.ZERO);}
        }
        assertNotNull(mutation);assertNotNull(relaunch);
        JSONObject javaNio=javaMetadata(root);
        for(String name:FINAL)for(String view:VIEWS)equalTuples(mutation.getJSONObject("finalSnapshot").getJSONObject(name).getJSONObject(view),
            relaunch.getJSONObject("finalSnapshot").getJSONObject(name).getJSONObject(view));
        assertArrayEquals("Same-content replacement remains exact", "BBBBBBBB".getBytes(StandardCharsets.US_ASCII),Files.readAllBytes(generation.resolve("data/regular.bin")));
        // A leaf lstat alone follows ancestor links. Verify the required no-follow
        // directory-open rejection independently on Android as well as in C.
        java.io.FileDescriptor real=Os.open(generation.resolve("data").toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW,0);Os.close(real);
        boolean rejected=false;
        try {java.io.FileDescriptor bad=Os.open(generation.resolve("data/ancestor").toString(),OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW,0);Os.close(bad);}
        catch(ErrnoException expected){rejected=expected.errno==OsConstants.ELOOP||expected.errno==OsConstants.ENOTDIR;}
        assertTrue("No-follow ancestor open must reject the link",rejected);
        JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","android-13-x86_64-proot-stat-metadata-visible-mutations")
            .put("sourceRevision",BuildConfig.SOURCE_REVISION).put("fingerprint",Build.FINGERPRINT).put("api",Build.VERSION.SDK_INT)
            .put("targetSdk",context.getApplicationInfo().targetSdkVersion).put("abi","x86_64").put("guestLaunches",2)
            .put("aliases",new JSONObject().put("work",PRIMARY).put("data","/esteria-data"))
            .put("buildEvidence",build).put("statBuildEvidence",statBuild).put("mutation",mutation).put("relaunch",relaunch)
            .put("javaNioMetadata",javaNio)
            .put("childExitCodes",exits).put("forcedChildren",forced).put("remainingNativeMembers",remaining)
            .put("noFollowAncestorOpenRejected",rejected).put("productionCacheEnabled",false).put("arm64Qualified",false)
            .put("hardwareQualified",false).put("unchangedMetadataCorruptionDetectionClaimed",false).put("gameplayQualified",false);
        byte[] bytes=receipt.toString(2).getBytes(StandardCharsets.UTF_8);assertTrue(bytes.length<=256*1024);
        Files.write(context.getFilesDir().toPath().resolve("proot-stat-qualification.json"),bytes,StandardOpenOption.CREATE_NEW);
    }
}
