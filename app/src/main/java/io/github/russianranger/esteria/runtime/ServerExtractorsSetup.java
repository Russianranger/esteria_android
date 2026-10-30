package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Optional immutable extractors; installation performs no client-data conversion. */
public final class ServerExtractorsSetup {
    public enum Tool {
        MAP_EXTRACTOR("map_extractor"), MMAPS_GENERATOR("mmaps_generator"),
        VMAP_ASSEMBLER("vmap4_assembler"), VMAP_EXTRACTOR("vmap4_extractor");
        private final String name;
        Tool(String name) { this.name = name; }
    }
    private static final String ARCHIVE = "server-extractors/server-extractors.archive";
    private final AssetManager assets;
    private final Path store, cache;
    private final RuntimePackagePlan plan;
    private final String dependencyArchive;
    private final long freshFreeBytes;

    public ServerExtractorsSetup(Context context, Path privateRoot) throws IOException {
        if (!BuildConfig.SERVER_EXTRACTORS_PACKAGED) throw new IOException("This build has no sealed server extractors provider");
        if (!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Server extractors require private canonical application storage");
        assets = context.getApplicationContext().getAssets();
        byte[] raw = asset("server-extractors/provider.json", 128 << 10);
        try {
            JSONObject proof = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (proof.getInt("formatVersion") != 1 || !"android-server-extractors-install-only".equals(proof.getString("scope")) ||
                    !"server-extractors-arm64".equals(proof.getString("packageKey")) || !proof.getBoolean("archiveVerified") ||
                    !proof.getBoolean("elfAbiInspected") || !proof.getBoolean("sourceCompanionRequired") ||
                    !proof.getBoolean("sourceCompanionVerified") || !proof.getBoolean("nativeArgumentConfigQualified") ||
                    proof.getBoolean("clientMpqConversionQualified") || proof.getBoolean("customEsteriaDataLoadOrderQualified") ||
                    proof.getBoolean("androidRuntimeQualified") || proof.getBoolean("gameLoginQualified") || proof.getBoolean("gameplayQualified") ||
                    !BuildConfig.SERVER_EXTRACTORS_PIN.equals(proof.getString("inputLockSha256")) ||
                    !BuildConfig.SERVER_EXTRACTORS_REVISION.equals(proof.getString("serverRevision")) ||
                    !hash(asset("sources.lock.json", 65536)).equals(proof.getString("appSourceLockSha256")) ||
                    !guestMount().equals(proof.getString("guestMount")))
                throw new IOException("Server extractors scope, source or companion pin differs");
            dependencyArchive = proof.getString("requiredServerRuntimeArchiveSha256");
            if (!dependencyArchive.matches("[0-9a-f]{64}")) throw new IOException("Invalid server dependency identity");
            for (String identity : new String[]{"originalBuild", "originalModules", "debugArchive", "nativeCliReceipt", "packagingPin", "packageReceipt"})
                requireIdentity(proof.getJSONObject(identity));
            JSONObject source = proof.getJSONObject("sourceQualification");
            for (String identity : new String[]{"archive", "receipt", "qualification"}) requireIdentity(source.getJSONObject(identity));
            Set<String> expectedPrograms = Set.of("map_extractor", "mmaps_generator", "vmap4_assembler", "vmap4_extractor");
            Set<String> names = new HashSet<>(); JSONArray selected = proof.getJSONArray("programNames");
            for (int i = 0; i < selected.length(); i++)
                if (!names.add(selected.getString(i))) throw new IOException("Duplicate server extractor name");
            if (!names.equals(expectedPrograms)) throw new IOException("Unexpected server extractor selection");
            JSONObject archive = proof.getJSONObject("archive"), bounds = proof.getJSONObject("limits"), required = proof.getJSONObject("requiredFiles");
            if (!ARCHIVE.equals(archive.getString("assetPath")) || !"server-extractors-runtime-arm64.tar.gz".equals(archive.getString("file")))
                throw new IOException("Invalid server extractors archive path");
            Map<String, RuntimePackagePlan.RequiredFile> files = new TreeMap<>();
            int noticeFiles = 0;
            for (Iterator<String> paths = required.keys(); paths.hasNext();) {
                String name = paths.next(); JSONObject pin = required.getJSONObject(name);
                int machine = pin.optInt("elfMachine", 0);
                if (name.startsWith("bin/") ? !expectedPrograms.contains(name.substring(4)) || machine != 183 : machine != 0)
                    throw new IOException("Unexpected executable in server extractors package");
                if (name.startsWith("notices/")) noticeFiles++;
                files.put(name, new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"), pin.getString("sha256"), machine, 0));
            }
            JSONObject pairs = proof.getJSONObject("programPairs");
            for (String name : expectedPrograms) {
                RuntimePackagePlan.RequiredFile program = files.get("bin/" + name); JSONObject pair = pairs.getJSONObject(name);
                for (String identity : new String[]{"original", "stripped", "debug"}) requireIdentity(pair.getJSONObject(identity));
                JSONObject stripped = pair.getJSONObject("stripped");
                if (program == null || program.bytes != stripped.getLong("bytes") || !program.sha256.equals(stripped.getString("sha256"))) throw new IOException("Server extractor and paired debug identity differ");
            }
            requirePinned(files, "provenance/server-build.json", proof.getJSONObject("originalBuild"));
            requirePinned(files, "provenance/server-modules.json", proof.getJSONObject("originalModules"));
            if (!files.containsKey("provenance/server-extractors-derivative.json") || !files.containsKey("provenance/sources.lock.json") ||
                    !files.get("provenance/sources.lock.json").sha256.equals(proof.getString("appSourceLockSha256")) ||
                    noticeFiles != proof.getInt("originalNoticeFiles") || noticeFiles != 66 || files.size() != 76)
                throw new IOException("Server source provenance or original notices are incomplete");
            JSONObject configuration = proof.getJSONObject("configuration");
            requireIdentity(configuration);
            if (!"bin/mmaps-config.yaml".equals(configuration.getString("originalPath")) ||
                    !"etc/mmaps-config.yaml".equals(configuration.getString("installedPath")))
                throw new IOException("Unexpected extractor configuration path");
            requirePinned(files, "etc/mmaps-config.yaml", configuration);
            requirePinned(files, "provenance/extractors-packaging.lock.json", proof.getJSONObject("packagingPin"));
            RuntimePackagePlan.Limits limits = new RuntimePackagePlan.Limits(bounds.getInt("entries"), bounds.getLong("memberBytes"),
                    bounds.getLong("fileBytes"), bounds.getInt("pathBytes"), bounds.getLong("metadataBytes"));
            plan = new RuntimePackagePlan("server-extractors-arm64", hash(raw), archive.getString("file"), archive.getLong("bytes"),
                    archive.getString("sha256"), proof.getLong("archiveEntries"), proof.getLong("archiveFileBytes"), limits, files);
            freshFreeBytes = proof.getLong("freshSetupFreeBytes");
            if (plan.expectedEntries != files.size() || freshFreeBytes != plan.archiveBytes + plan.expectedFileBytes + limits.maxMetadataBytes + (64L << 20))
                throw new IOException("Invalid server extractors storage reserve");
            store = privateRoot.resolve("runtimes/server-extractors-arm64");
            cache = privateRoot.resolve("runtime-embedded-cache/server-extractors-arm64");
            try (AssetFileDescriptor descriptor = assets.openFd(ARCHIVE)) {
                if (descriptor.getLength() != plan.archiveBytes) throw new IOException("Server extractors archive is not stored as pinned APK bytes");
            }
        } catch (JSONException | IllegalArgumentException error) { throw new IOException("Invalid server extractors provider metadata", error); }
    }

    public RuntimeInstaller.Result prepare(String actualServerRuntimeArchive, RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        requireServerRuntimeArchive(actualServerRuntimeArchive);
        RuntimeInstaller installer = installer();
        if (installer.resolveCurrent(plan) != null)
            return installer.install(cache.resolve("unused-completed-generation"), plan, progress, cancelled);
        Path archive = new EmbeddedArchiveCache(cache).obtain(plan.archiveName, plan.archiveBytes, plan.archiveSha256, this::openArchive, progress, cancelled);
        if (!Files.exists(store.resolve("staging").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(store.resolve("generations").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                store.toFile().getUsableSpace() < freshFreeBytes - plan.archiveBytes)
            throw new IOException("Insufficient storage for server extractors");
        return installer.install(archive, plan, progress, cancelled);
    }
    public RuntimeInstaller installer() throws IOException { return new RuntimeInstaller(store); }
    public RuntimePackagePlan packagePlan() { return plan; }
    public Path current() throws IOException { return installer().resolveCurrent(plan); }
    public String generation() { return plan.generation; }
    public String archiveSha256() { return plan.archiveSha256; }
    public static String guestMount() { return "/esteria-server-extractors"; }
    public static String toolPath(Tool program) {
        if (program == null) throw new IllegalArgumentException("A known server extractor is required");
        return guestMount() + "/bin/" + program.name;
    }
    public static String configurationPath() { return guestMount() + "/etc/mmaps-config.yaml"; }
    public static boolean customDataLoadOrderQualified() { return false; }
    public void requireServerRuntimeArchive(String actual) throws IOException {
        if (!dependencyArchive.equals(actual)) throw new IOException("Server extractors require a different pinned Ubuntu server runtime");
    }
    private InputStream openArchive(long offset) throws IOException {
        AssetFileDescriptor descriptor = assets.openFd(ARCHIVE); InputStream stream = null;
        try {
            if (offset < 0 || offset > plan.archiveBytes || descriptor.getLength() != plan.archiveBytes)
                throw new IOException("Invalid server extractors archive resume offset");
            stream = descriptor.createInputStream(); long remaining = offset;
            while (remaining > 0) {
                long count = stream.skip(remaining);
                if (count > 0) remaining -= count;
                else if (stream.read() < 0) throw new IOException("Truncated server extractors archive");
                else remaining--;
            }
            return stream;
        } catch (IOException | RuntimeException error) { if (stream != null) stream.close(); else descriptor.close(); throw error; }
    }
    private byte[] asset(String name, int maximum) throws IOException {
        try (InputStream input = assets.open(name); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > maximum) throw new IOException("Server extractors metadata exceeds bound");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
    private static void requireIdentity(JSONObject pin) throws JSONException, IOException {
        if (pin.getLong("bytes") <= 0 || pin.getLong("bytes") > (4L << 30) || !pin.getString("sha256").matches("[0-9a-f]{64}"))
            throw new IOException("Invalid server extractor companion identity");
    }
    private static void requirePinned(Map<String, RuntimePackagePlan.RequiredFile> files, String name, JSONObject pin) throws JSONException, IOException {
        RuntimePackagePlan.RequiredFile file = files.get(name);
        if (file == null || file.bytes != pin.getLong("bytes") || !file.sha256.equals(pin.getString("sha256")))
            throw new IOException("Server extractor original receipt differs");
    }
    private static String hash(byte[] bytes) throws IOException {
        try {
            StringBuilder output = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes))
                output.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return output.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
