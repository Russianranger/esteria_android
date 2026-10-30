package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.FileNotFoundException;
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

/** Optional verified APK server dependencies. Installation starts no services or database. */
public final class ServerRuntimeSetup {
    private static final String DESCRIPTOR = "server-runtime/provider.json";
    private final AssetManager assets;
    private final String assetPath;
    private final Path store, cache;
    private final RuntimePackagePlan plan;
    private final long freshFreeBytes;
    private final String mysqlVersion;

    public ServerRuntimeSetup(Context context, Path privateRoot) throws IOException {
        assets = context.getApplicationContext().getAssets();
        byte[] raw;
        try { raw = readAsset(assets, DESCRIPTOR, 65536); }
        catch (FileNotFoundException missing) { throw new IOException("This build has no bundled server runtime provider", missing); }
        try {
            JSONObject proof = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (proof.getInt("formatVersion") != 1 || !"android-server-runtime-install-only".equals(proof.getString("scope")) ||
                    !"server-arm64".equals(proof.getString("packageKey")) || !proof.getBoolean("archiveVerified") ||
                    !proof.getBoolean("elfHeaderMachineValidated") || proof.getBoolean("androidRuntimeQualified") ||
                    proof.getBoolean("serverIncluded") || proof.getBoolean("gameLoginQualified"))
                throw new IOException("Unexpected server runtime provider scope");
            JSONObject archive = proof.getJSONObject("archive"), bounds = proof.getJSONObject("limits");
            assetPath = archive.getString("assetPath");
            if (!"server-runtime/server-runtime-arm64.archive".equals(assetPath) ||
                    !"server-runtime-arm64.tar.gz".equals(archive.getString("file")))
                throw new IOException("Invalid embedded server archive path");
            Map<String, RuntimePackagePlan.RequiredFile> files = new TreeMap<>();
            JSONObject required = proof.getJSONObject("requiredFiles");
            for (Iterator<String> keys = required.keys(); keys.hasNext();) {
                String path = keys.next(); JSONObject item = required.getJSONObject(path);
                files.put(path, new RuntimePackagePlan.RequiredFile(item.getLong("bytes"), item.getString("sha256"), item.optInt("elfMachine", 0), 0));
            }
            RuntimePackagePlan.Limits limits = new RuntimePackagePlan.Limits(bounds.getInt("entries"), bounds.getLong("memberBytes"),
                    bounds.getLong("fileBytes"), bounds.getInt("pathBytes"), bounds.getLong("metadataBytes"));
            plan = new RuntimePackagePlan("server-arm64", sha256(raw), archive.getString("file"), archive.getLong("bytes"),
                    archive.getString("sha256"), proof.getLong("archiveEntries"), proof.getLong("archiveFileBytes"), limits, files);
            long copies = proof.getLong("maximumHardLinkCopyBytes"), physical = proof.getLong("maximumPhysicalFileBytes");
            freshFreeBytes = proof.getLong("freshSetupFreeBytes");
            if (copies < 0 || copies > limits.maxFileBytes - plan.expectedFileBytes ||
                    physical != plan.expectedFileBytes + copies || physical > limits.maxFileBytes ||
                    freshFreeBytes != plan.archiveBytes + physical + limits.maxMetadataBytes + (64L << 20))
                throw new IOException("Invalid server hardlink-copy storage reserve");
            byte[] metadata = readAsset(assets, "server-runtime/server-runtime.json", 65536);
            if (!sha256(metadata).equals(proof.getString("runtimeMetadataSha256")) ||
                    !sha256(readAsset(assets, "server-runtime/sources.lock.json", 65536)).equals(proof.getString("sourceLockSha256")) ||
                    !sha256(readAsset(assets, "server-runtime/package-receipt.json", 65536)).equals(proof.getString("packageReceiptSha256")))
                throw new IOException("Bundled server metadata identity differs");
            JSONObject measured = new JSONObject(new String(metadata, StandardCharsets.UTF_8));
            mysqlVersion = measured.getString("expectedMysqlSqlVersion");
            if (!mysqlVersion.matches("8\\.0\\.[0-9]+[A-Za-z0-9.+~_-]*")) throw new IOException("Invalid measured MySQL version");
            store = privateRoot.resolve("runtimes/server-arm64");
            cache = privateRoot.resolve("runtime-embedded-cache/server-arm64");
            // openFd fails for compressed APK assets; do not silently accept an
            // expensive decompression/resume path when the provider hook is absent.
            try (AssetFileDescriptor file = assets.openFd(assetPath)) {
                if (file.getLength() != plan.archiveBytes) throw new IOException("Bundled server archive size differs");
            }
        } catch (JSONException | IllegalArgumentException error) { throw new IOException("Invalid server runtime provider metadata", error); }
    }

    public RuntimeInstaller.Result prepare(RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled) throws IOException {
        RuntimeInstaller installer = new RuntimeInstaller(store);
        Path current = installer.resolveCurrent(plan);
        // RuntimeInstaller returns a verified completed generation before opening
        // its archive, so repeated setup needs no asset copy or full archive hash.
        if (current != null) return installer.install(cache.resolve("unused-completed-generation"), plan, progress, cancelled);
        Path archive = new EmbeddedArchiveCache(cache).obtain(plan.archiveName, plan.archiveBytes, plan.archiveSha256,
                this::openArchive, progress, cancelled);
        // The cache already occupies its archive bytes. Counting them again here
        // would prevent a cancelled first setup from resuming on nearly full storage.
        if (!Files.exists(store.resolve("staging").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(store.resolve("generations").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                store.toFile().getUsableSpace() < freshFreeBytes - plan.archiveBytes)
            throw new IOException("Insufficient storage for bundled server runtime and verified hardlink copies");
        return installer.install(archive, plan, progress, cancelled);
    }
    public Path current() throws IOException { return new RuntimeInstaller(store).resolveCurrent(plan); }
    public String generation() { return plan.generation; }
    public String archiveSha256() { return plan.archiveSha256; }
    public String expectedMysqlVersion() { return mysqlVersion; }
    public RuntimePackagePlan packagePlan() { return plan; }
    public RuntimeInstaller installer() throws IOException { return new RuntimeInstaller(store); }
    public long freshSetupFreeBytes() { return freshFreeBytes; }

    private InputStream openArchive(long offset) throws IOException {
        AssetFileDescriptor descriptor = assets.openFd(assetPath);
        InputStream stream = null;
        try {
            if (offset < 0 || offset > plan.archiveBytes || descriptor.getLength() != plan.archiveBytes)
                throw new IOException("Invalid bundled archive resume offset");
            stream = descriptor.createInputStream();
            long remaining = offset;
            while (remaining > 0) {
                long skipped = stream.skip(remaining);
                if (skipped > 0) remaining -= skipped;
                else if (stream.read() < 0) throw new IOException("Bundled archive ended before resume offset");
                else remaining--;
            }
            return stream; // AssetFileDescriptor.AutoCloseInputStream owns the descriptor.
        } catch (IOException | RuntimeException error) {
            if (stream != null) stream.close(); else descriptor.close();
            throw error;
        }
    }
    private static byte[] readAsset(AssetManager assets, String path, int maximum) throws IOException {
        try (InputStream input = assets.open(path); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > maximum) throw new IOException("Bundled server metadata exceeds limit");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
    private static String sha256(byte[] bytes) throws IOException {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(bytes);
            StringBuilder out = new StringBuilder(64);
            for (byte value : digest) out.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return out.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
