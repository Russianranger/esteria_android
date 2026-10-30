package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import org.json.JSONException;
import org.json.JSONObject;
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
import java.util.Map;
import java.util.TreeMap;

/** Installs the source-matched reconstructed PE files, separately from imported game data. */
public final class ClientRuntimeSetup {
    private static final String ARCHIVE = "client-runtime/client-arm64.archive";
    private final AssetManager assets;
    private final Path store, cache;
    private final RuntimePackagePlan plan;
    private final String revision, buildId, wineArchive;
    private final long freshFreeBytes;

    public ClientRuntimeSetup(Context context, Path privateRoot) throws IOException {
        assets = context.getApplicationContext().getAssets();
        byte[] raw = asset("client-runtime/provider.json");
        try {
            JSONObject proof = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (proof.getInt("formatVersion") != 1 || !"android-reconstructed-client-install-only".equals(proof.getString("scope")) ||
                    !"client-arm64".equals(proof.getString("packageKey")) || !proof.getBoolean("archiveVerified") ||
                    !proof.getBoolean("peHeadersAndDirectImportsVerified") || proof.getBoolean("androidRuntimeQualified") ||
                    proof.getBoolean("gameInitializationQualified") || proof.getBoolean("gameLoginQualified"))
                throw new IOException("Unexpected reconstructed client provider scope");
            revision = proof.getString("sourceRevision"); buildId = proof.getString("buildId");
            if (!revision.equals(BuildConfig.CLIENT_REVISION) || !buildId.matches("[A-Za-z0-9._-]{1,96}") ||
                    !hash(asset("sources.lock.json")).equals(proof.getString("sourceLockSha256")))
                throw new IOException("Reconstructed client does not match this application source lock");
            JSONObject protocol = proof.getJSONObject("protocol");
            if (protocol.length() != 4 || protocol.getInt("build") != 12340 || protocol.getInt("container_slots") != 254 ||
                    protocol.getInt("quest_slots") != 25 || protocol.getInt("max_class_id") != 32)
                throw new IOException("Reconstructed client protocol does not match the selected server");
            wineArchive = proof.getString("requiredWineArchiveSha256");
            if (!wineArchive.matches("[0-9a-f]{64}") ||
                    !wineArchive.equals(proof.getJSONObject("requiredWineRuntime").getString("archiveSha256")))
                throw new IOException("Invalid reconstructed client Wine identity");
            JSONObject archive = proof.getJSONObject("archive"), bounds = proof.getJSONObject("limits");
            if (!ARCHIVE.equals(archive.getString("assetPath"))) throw new IOException("Invalid client archive path");
            Map<String, RuntimePackagePlan.RequiredFile> files = new TreeMap<>();
            JSONObject required = proof.getJSONObject("requiredFiles");
            for (Iterator<String> keys = required.keys(); keys.hasNext();) {
                String name = keys.next(); JSONObject pin = required.getJSONObject(name);
                int pe = pin.has("peMachine") ? Integer.decode(pin.getString("peMachine")) : 0;
                files.put(name, new RuntimePackagePlan.RequiredFile(pin.getLong("bytes"), pin.getString("sha256"), 0, pe));
            }
            for (String name : new String[]{"bin/WowClient64.exe", "bin/XvidDecoder.dll"})
                if (!files.containsKey(name) || files.get(name).peMachine != 0xaa64)
                    throw new IOException("Missing reconstructed ARM64 client binary pin");
            for (String name : new String[]{"client-runtime.json", "metadata/client-build.json", "metadata/limits.json", "metadata/sources.lock.json"})
                if (!files.containsKey(name)) throw new IOException("Missing client provenance: " + name);
            if (!files.get("metadata/sources.lock.json").sha256.equals(proof.getString("sourceLockSha256")))
                throw new IOException("Installed client source provenance differs");
            RuntimePackagePlan.Limits limits = new RuntimePackagePlan.Limits(bounds.getInt("entries"), bounds.getLong("memberBytes"),
                    bounds.getLong("fileBytes"), bounds.getInt("pathBytes"), bounds.getLong("metadataBytes"));
            plan = new RuntimePackagePlan("client-arm64", hash(raw), "client-arm64.tar.gz", archive.getLong("bytes"),
                    archive.getString("sha256"), proof.getLong("archiveEntries"), proof.getLong("archiveFileBytes"), limits, files);
            freshFreeBytes = proof.getLong("freshSetupFreeBytes");
            if (plan.expectedEntries != files.size() || proof.getLong("maximumHardLinkCopies") != 0 ||
                    proof.getLong("maximumHardLinkCopyBytes") != 0 || proof.getLong("maximumPhysicalFileBytes") != plan.expectedFileBytes ||
                    freshFreeBytes != plan.archiveBytes + plan.expectedFileBytes + limits.maxMetadataBytes + (64L << 20))
                throw new IOException("Invalid client inventory or storage reserve");
            store = privateRoot.resolve("runtimes/client-arm64");
            cache = privateRoot.resolve("runtime-embedded-cache/client-arm64");
            try (AssetFileDescriptor descriptor = assets.openFd(ARCHIVE)) {
                if (descriptor.getLength() != plan.archiveBytes) throw new IOException("Bundled client archive size differs");
            }
        } catch (JSONException | IllegalArgumentException error) { throw new IOException("Invalid reconstructed client provider", error); }
    }

    public RuntimeInstaller.Result prepare(RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        RuntimeInstaller installer = new RuntimeInstaller(store);
        if (installer.resolveCurrent(plan) != null)
            return installer.install(cache.resolve("unused-completed-generation"), plan, progress, cancelled);
        Path archive = new EmbeddedArchiveCache(cache).obtain(plan.archiveName, plan.archiveBytes, plan.archiveSha256,
                this::openArchive, progress, cancelled);
        if (!Files.exists(store.resolve("staging").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(store.resolve("generations").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                store.toFile().getUsableSpace() < freshFreeBytes - plan.archiveBytes)
            throw new IOException("Insufficient storage for reconstructed client files");
        return installer.install(archive, plan, progress, cancelled);
    }
    public Path current() throws IOException { return new RuntimeInstaller(store).resolveCurrent(plan); }
    public RuntimePackagePlan packagePlan() { return plan; }
    public String generation() { return plan.generation; }
    public String archiveSha256() { return plan.archiveSha256; }
    public String sourceRevision() { return revision; }
    public String buildId() { return buildId; }
    public void requireWineArchive(String actual) throws IOException {
        if (!wineArchive.equals(actual)) throw new IOException("Reconstructed client requires a different pinned Wine runtime");
    }
    private InputStream openArchive(long offset) throws IOException {
        AssetFileDescriptor descriptor = assets.openFd(ARCHIVE);
        InputStream input = null;
        try {
            if (offset < 0 || offset > plan.archiveBytes || descriptor.getLength() != plan.archiveBytes)
                throw new IOException("Invalid reconstructed client archive offset");
            input = descriptor.createInputStream();
            long remaining = offset;
            while (remaining > 0) {
                long skipped = input.skip(remaining);
                if (skipped > 0) remaining -= skipped;
                else if (input.read() < 0) throw new IOException("Client archive ended before resume offset");
                else remaining--;
            }
            return input;
        } catch (IOException | RuntimeException error) {
            if (input != null) input.close(); else descriptor.close();
            throw error;
        }
    }
    private byte[] asset(String name) throws IOException {
        try (InputStream input = assets.open(name); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > 128 * 1024) throw new IOException("Client metadata exceeds limit");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
    private static String hash(byte[] bytes) throws IOException {
        try {
            StringBuilder value = new StringBuilder(64);
            for (byte part : MessageDigest.getInstance("SHA-256").digest(bytes))
                value.append(String.format(java.util.Locale.ROOT, "%02x", part & 255));
            return value.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
