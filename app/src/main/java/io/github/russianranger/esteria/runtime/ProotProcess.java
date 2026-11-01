package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.io.InputStream;
import java.io.ByteArrayOutputStream;
import java.util.List;
import java.util.Map;
import java.util.Collections;
import org.json.JSONObject;
import org.json.JSONException;

/** Component adapter for internal qualification. No launcher action uses this yet.
 * Starting a process does not establish display/audio/service or gameplay readiness.
 */
public final class ProotProcess {
    private ProotProcess() { }
    /** Capability minted only from this debug APK's fixed, compiled provider
     * pin and original measured native payloads. It contains no caller path. */
    static final class QualificationPayload {
        private final Context application;
        private QualificationPayload(Context application){this.application=application;}
    }
    private static final class Payload {
        final Path tracer,loader;
        Payload(Path tracer,Path loader){this.tracer=tracer;this.loader=loader;}
    }
    static QualificationPayload qualificationPayload(Context context)throws IOException {
        requireQualificationProfile();
        if(context==null)throw new IOException("Qualification application context is required");
        Context application=context.getApplicationContext();inspectQualification(application);
        return new QualificationPayload(application);
    }
    static OwnedProcess startQualified(Context context,QualificationPayload payload,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> command,Map<String,String> environment,List<ProotLaunch.Mount> mounts)throws IOException {
        if(payload==null)throw new IOException("Measured qualification payload capability is required");
        return OwnedProcess.start(new NativeProcessBridge(),specification(context,installer,plan,work,session,command,environment,mounts,null,payload),null);
    }
    static OwnedProcess startInteractiveQualified(Context context,QualificationPayload payload,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> command,Map<String,String> environment,List<ProotLaunch.Mount> mounts,
            OwnedProcess.GracefulInputStop shutdown)throws IOException {
        if(payload==null)throw new IOException("Measured qualification payload capability is required");
        OwnedProcess.Specification base=specification(context,installer,plan,work,session,command,environment,mounts,null,payload);
        return OwnedProcess.startInteractive(new NativeProcessBridge(),new OwnedProcess.Specification(base.executable,base.arguments,
            base.environment,base.cwd,base.stdout,base.stderr,true),shutdown);
    }
    public static OwnedProcess start(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            OwnedProcess.GracefulStop gracefulStop) throws IOException {
        return start(context,installer,plan,work,session,guestCommand,guestEnvironment,Collections.emptyList(),gracefulStop);
    }
    public static OwnedProcess start(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,OwnedProcess.GracefulStop gracefulStop) throws IOException {
        return OwnedProcess.start(new NativeProcessBridge(),specification(context,installer,plan,work,session,
            guestCommand,guestEnvironment,mounts,null),gracefulStop);
    }
    /** Verify providers/paths before a caller starts a child-only deadline.
     * This creates the same immutable specification without launching it. */
    static OwnedProcess.Specification prepare(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts)throws IOException {
        return specification(context,installer,plan,work,session,guestCommand,guestEnvironment,mounts,null);
    }
    public static OwnedProcess startPresentation(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,ProotLaunch.PresentationBindings presentation) throws IOException {
        if (presentation==null) throw new IOException("Explicit presentation IPC bindings required");
        return OwnedProcess.start(new NativeProcessBridge(),specification(context,installer,plan,work,session,
            guestCommand,guestEnvironment,mounts,presentation),null);
    }
    /** Explicit console pipe; the callback must send a source-supported command and check delivery. */
    public static OwnedProcess startInteractive(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,OwnedProcess.GracefulInputStop gracefulStop) throws IOException {
        OwnedProcess.Specification base=specification(context,installer,plan,work,session,guestCommand,guestEnvironment,mounts,null);
        OwnedProcess.Specification interactive=new OwnedProcess.Specification(base.executable,base.arguments,base.environment,
            base.cwd,base.stdout,base.stderr,true);
        return OwnedProcess.startInteractive(new NativeProcessBridge(),interactive,gracefulStop);
    }
    private static OwnedProcess.Specification specification(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,ProotLaunch.PresentationBindings presentation) throws IOException {
        return specification(context,installer,plan,work,session,guestCommand,guestEnvironment,mounts,presentation,null);
    }
    private static OwnedProcess.Specification specification(Context context,RuntimeInstaller installer,RuntimePackagePlan plan,
            Path work,Path session,List<String> guestCommand,Map<String,String> guestEnvironment,
            List<ProotLaunch.Mount> mounts,ProotLaunch.PresentationBindings presentation,QualificationPayload qualification)throws IOException {
        Payload payload;
        if(qualification==null){InstalledProot installed=InstalledProot.inspect(context);payload=new Payload(installed.tracer.toPath(),installed.loader.toPath());}
        else {
            if(qualification.application!=context.getApplicationContext())throw new IOException("Qualification payload belongs to another application");
            payload=inspectQualification(qualification.application);
        }
        Path rootfs=installer.resolveCurrent(plan);
        if (rootfs==null) throw new IOException("The pinned runtime generation is not prepared");
        Path privateRoot=context.getFilesDir().getCanonicalFile().toPath();
        rootfs=privatePath(privateRoot,rootfs); work=privatePath(privateRoot,work); session=privatePath(privateRoot,session);
        if (mounts == null) throw new IOException("Runtime provider mounts are missing");
        for (ProotLaunch.Mount mount : mounts) {
            if (mount == null) throw new IOException("Runtime provider mount is missing");
            privatePath(privateRoot,mount.source);
        }
        if (presentation!=null) {
            privatePath(privateRoot,presentation.endpoints); privatePath(privateRoot,presentation.x11);
        }
        if (session.startsWith(rootfs) || rootfs.startsWith(session) || session.startsWith(work) || work.startsWith(session))
            throw new IOException("Process session must be separate from runtime and persistent state");
        Path temporary=session.resolve("tmp"),logs=session.resolve("logs");
        // Session must be freshly created by the caller, avoiding stale sockets/logs.
        try (var entries=Files.list(session)) { if (entries.findAny().isPresent()) throw new IOException("Process session is not empty"); }
        Files.createDirectory(temporary,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Files.createDirectory(logs,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        Path home=work.resolve("home");
        if (!Files.exists(home)) Files.createDirectory(home,PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        privatePath(privateRoot,home);
        return ProotLaunch.create(payload.tracer,payload.loader,rootfs,
            work,temporary,logs,guestCommand,guestEnvironment,mounts,presentation);
    }
    private static Payload inspectQualification(Context context)throws IOException {
        requireQualificationProfile();
        if(context==null)throw new IOException("Qualification application context is required");
        try {
            return qualificationBody(context);
        }catch(JSONException error){throw new IOException("Invalid qualification payload metadata",error);}
    }
    private static void requireQualificationProfile()throws IOException {
        if(!BuildConfig.DEBUG||!BuildConfig.SERVER_INSTALLATION_PROBE_PACKAGED||!BuildConfig.SERVER_INSTALLATION_PROBE_PIN.matches("[a-f0-9]{64}"))
            throw new IOException("Measured debug installation payload is unavailable");
    }
    private static Payload qualificationBody(Context context)throws IOException,JSONException {
            byte[] raw=asset(context,"installation-probe/provider.json",128<<10);
            if(!hash(raw).equals(BuildConfig.SERVER_INSTALLATION_PROBE_PIN))throw new IOException("Qualification provider differs from the compiled pin");
            JSONObject provider=new JSONObject(new String(raw,StandardCharsets.UTF_8));
            if(provider.getInt("formatVersion")!=1||!"android-x86-64-server-installation-probe-only".equals(provider.getString("scope")))
                throw new IOException("Unexpected installation qualification profile");
            byte[] sql=asset(context,"installation-probe/native-sql-qualification.json",256<<10);
            pinned(sql,provider.getJSONObject("nativeSqlReceipt"));JSONObject qualified=new JSONObject(new String(sql,StandardCharsets.UTF_8));
            if(!"disposable-native-x64-measured-setup-four-schema-sql".equals(qualified.getString("scope"))||!"complete".equals(qualified.getString("phase")))
                throw new IOException("Native x64 SQL qualification is required");
            for(String field:List.of("qualificationSucceeded","selectedX64ToolsSqlQualified","capturedLoaderAndLibraryCompatibilityQualified",
                    "actualCoreCompositionCompleted","completedJournalReentryWithoutExecution","actualLoaderReentryVerified",
                    "restartPersistenceVerified","fixtureProbeRemoved","exactSourceUpdateLedgerVerified","finalFourSchemaProductVerification",
                    "coreSchemasLedgersCredentialsAccountPreserved","cleanShutdownVerified"))flag(qualified,field,true);
            for(String field:List.of("androidRuntimeQualified","productionArm64ProviderQualified","fourSchemaCoordinatorQualified",
                    "worldserverQualified","playerbotsAiQualified","gameplayQualified","slotPromoted","serverDataQualified",
                    "originalArm64ReceiptReusedForX64Qualification"))flag(qualified,field,false);
            JSONObject proot=provider.getJSONObject("proot");
            byte[] evidence=asset(context,"proot-probe/build-evidence.json",65536);pinned(evidence,proot.getJSONObject("buildEvidence"));
            JSONObject build=new JSONObject(new String(evidence,StandardCharsets.UTF_8));
            if(build.getInt("formatVersion")!=1||!"android-13-x86_64-proot-glibc-probe-build-only".equals(build.getString("scope"))||
                    !"28.2.13676358".equals(build.getString("ndkVersion"))||
                    !proot.getString("sourceLockSha256").matches("[a-f0-9]{64}")||
                    !proot.getString("sourceLockSha256").equals(build.getString("prootSourceLockSha256")))
                throw new IOException("Qualification PRoot source profile differs");
            for(String field:List.of("androidProotExecuted","arm64GuestExecuted","gameplayQualified"))flag(build,field,false);
            Path directory=Paths.get(context.getApplicationInfo().nativeLibraryDir).toRealPath();
            Path tracer=qualifiedNative(directory,"libproot_probe.so",proot.getJSONObject("nativeFiles"),build.getJSONObject("nativeFiles"),3);
            Path loader=qualifiedNative(directory,"libproot_probe_loader.so",proot.getJSONObject("nativeFiles"),build.getJSONObject("nativeFiles"),2);
            return new Payload(tracer,loader);
    }
    private static Path qualifiedNative(Path directory,String name,JSONObject selected,JSONObject original,int kind)throws IOException,JSONException {
        Path file=directory.resolve(name);JSONObject pin=selected.getJSONObject(name),built=original.getJSONObject(name);
        if(pin.getLong("bytes")!=built.getLong("bytes")||!pin.getString("sha256").equals(built.getString("sha256"))||
                !Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||!file.equals(file.toRealPath())||!Files.isExecutable(file))
            throw new IOException("Qualification native payload differs");
        BasicFileAttributes before=Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        long maximum=pin.getLong("bytes");if(maximum<64||maximum>(16L<<20)||before.size()!=maximum)throw new IOException("Qualification native payload size differs");
        MessageDigest digest=digest();long total=0;byte[] header=new byte[20];
        try(InputStream input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) {
            int offset=0;while(offset<header.length){int got=input.read(header,offset,header.length-offset);if(got<=0)throw new IOException("Qualification native ELF header is absent");offset+=got;}
            if(header[0]!=0x7f||header[1]!='E'||header[2]!='L'||header[3]!='F'||header[4]!=2||header[5]!=1||header[6]!=1||
                    (header[16]&255)!=kind||header[17]!=0||header[18]!=62||header[19]!=0)
                throw new IOException("Qualification native payload is not the measured x64 ELF role");
            digest.update(header);total=header.length;byte[] block=new byte[65536];
            for(int got;(got=input.read(block))!=-1;){total+=got;if(total>maximum)throw new IOException("Qualification native payload grew");digest.update(block,0,got);}
        }
        BasicFileAttributes after=Files.readAttributes(file,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(total!=maximum||!pin.getString("sha256").equals(hex(digest.digest()))||before.fileKey()==null||!before.fileKey().equals(after.fileKey())||
                before.size()!=after.size()||!before.lastModifiedTime().equals(after.lastModifiedTime()))
            throw new IOException("Qualification native payload changed during inspection");
        return file;
    }
    private static byte[] asset(Context context,String name,int maximum)throws IOException {
        try(InputStream input=context.getAssets().open(name);ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] block=new byte[4096];for(int got;(got=input.read(block))!=-1;){if(output.size()+got>maximum)throw new IOException("Qualification metadata exceeds bound");output.write(block,0,got);}return output.toByteArray();
        }
    }
    private static void pinned(byte[] raw,JSONObject pin)throws IOException,JSONException {
        if(raw.length!=pin.getLong("bytes")||!hash(raw).equals(pin.getString("sha256")))throw new IOException("Qualification receipt differs from its exact pin");
    }
    private static void flag(JSONObject value,String name,boolean expected)throws IOException,JSONException {
        if(!Boolean.valueOf(expected).equals(value.get(name)))throw new IOException("Unexpected qualification claim: "+name);
    }
    private static MessageDigest digest()throws IOException {try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException error){throw new IOException("SHA-256 unavailable",error);}}
    private static String hash(byte[] raw)throws IOException{return hex(digest().digest(raw));}
    private static String hex(byte[] raw){StringBuilder value=new StringBuilder(64);for(byte octet:raw)value.append(String.format(java.util.Locale.ROOT,"%02x",octet&255));return value.toString();}
    private static Path privatePath(Path privateRoot,Path path) throws IOException {
        Path canonical=path.toRealPath();
        if (!canonical.startsWith(privateRoot) || canonical.equals(privateRoot) || !Files.isDirectory(canonical) ||
                !canonical.equals(path.toAbsolutePath().normalize())) throw new IOException("Runtime process paths must be private canonical directories");
        return canonical;
    }
}
