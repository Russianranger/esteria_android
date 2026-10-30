package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.content.res.AssetManager;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.install.EmbeddedArchiveCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
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
import java.util.TreeMap;
import org.json.JSONException;
import org.json.JSONArray;
import org.json.JSONObject;

/** Original SQL/configuration sources, separate from programs and mutable saves.
 * The phone-side content verifier checks the full file inventory before SQL use.
 */
public final class ServerContentSetup {
    private static final String ARCHIVE = "server-content/server-content.archive";
    private static final Set<String> METADATA = Set.of("metadata/content-manifest.json",
            "metadata/compiled-modules.json", "metadata/lua-map.json", "metadata/package-plan.json");
    private final AssetManager assets;
    private final Path store, cache;
    private final RuntimePackagePlan plan;
    private final byte[] receipt;
    private final String receiptHash, sourceLockHash, dependencyHash, sourceJson, compiledJson;
    private final long freshFreeBytes;
    private Path preparedReceipt;

    public ServerContentSetup(Context context, Path privateRoot) throws IOException {
        if (!BuildConfig.SERVER_CONTENT_PACKAGED) throw new IOException("This build has no bundled server content");
        if (!privateRoot.equals(context.getFilesDir().getCanonicalFile().toPath()))
            throw new IOException("Server content requires private canonical application storage");
        assets = context.getApplicationContext().getAssets();
        byte[] raw = asset("server-content/provider.json", 128 << 10);
        try {
            JSONObject proof = new JSONObject(new String(raw, StandardCharsets.UTF_8));
            if (proof.getInt("formatVersion") != 1 || !"android-server-content-install-only".equals(proof.getString("scope")) ||
                    !"server-content-arm64".equals(proof.getString("packageKey")) || !proof.getBoolean("archiveVerified") ||
                    !proof.getBoolean("luaDisabled") || proof.getBoolean("androidRuntimeQualified") || proof.getBoolean("gameplayQualified") ||
                    !BuildConfig.SERVER_CONTENT_PIN.equals(proof.getString("inputLockSha256")))
                throw new IOException("Server content scope or provider pin differs");
            sourceLockHash = proof.getString("appSourceLockSha256");
            byte[] lock = asset("sources.lock.json", 65536);
            if (!hash(lock).equals(sourceLockHash)) throw new IOException("Server content source lock differs from this application");
            JSONObject server = proof.getJSONObject("serverSource");
            if (!sameJson(server, new JSONObject(new String(lock, StandardCharsets.UTF_8))
                    .getJSONObject("sources").getJSONObject("server")))
                throw new IOException("Server content source selection differs");
            sourceJson = server.toString();
            JSONObject compiled = proof.getJSONObject("compiledModules");
            identity(compiled, 65536); compiledJson = compiled.toString();
            dependencyHash = proof.getString("requiredServerRuntimeArchiveSha256");
            if (!dependencyHash.matches("[0-9a-f]{64}")) throw new IOException("Invalid server content dependency pin");
            JSONObject receiptPin = proof.getJSONObject("receipt"); identity(receiptPin, 16 << 20);
            receipt = asset("server-content/package-receipt.json", 16 << 20);
            receiptHash = receiptPin.getString("sha256");
            if (receipt.length != receiptPin.getLong("bytes") || !hash(receipt).equals(receiptHash))
                throw new IOException("Bundled server content receipt differs");
            JSONObject archive = proof.getJSONObject("archive"), bounds = proof.getJSONObject("limits");
            if (!ARCHIVE.equals(archive.getString("assetPath")) || !"server-content.tar.gz".equals(archive.getString("file")))
                throw new IOException("Invalid server content archive path");
            JSONObject required = proof.getJSONObject("requiredFiles");
            Map<String, RuntimePackagePlan.RequiredFile> files = new TreeMap<>();
            var names = required.keys();
            while (names.hasNext()) {
                String name = names.next(); JSONObject file = required.getJSONObject(name); identity(file, 16 << 20);
                files.put(name, new RuntimePackagePlan.RequiredFile(file.getLong("bytes"), file.getString("sha256"), 0, 0));
            }
            if (!files.keySet().equals(METADATA) ||
                    files.get("metadata/compiled-modules.json").bytes != compiled.getLong("bytes") ||
                    !files.get("metadata/compiled-modules.json").sha256.equals(compiled.getString("sha256")))
                throw new IOException("Server content metadata or compiled module pins differ");
            RuntimePackagePlan.Limits limits = new RuntimePackagePlan.Limits(bounds.getInt("entries"), bounds.getLong("memberBytes"),
                    bounds.getLong("fileBytes"), bounds.getInt("pathBytes"), bounds.getLong("metadataBytes"));
            plan = new RuntimePackagePlan("server-content-arm64", hash(raw), archive.getString("file"), archive.getLong("bytes"),
                    archive.getString("sha256"), proof.getLong("archiveEntries"), proof.getLong("archiveFileBytes"), limits, files);
            freshFreeBytes = proof.getLong("freshSetupFreeBytes");
            if (freshFreeBytes != plan.archiveBytes + plan.expectedFileBytes + limits.maxMetadataBytes + receipt.length + (64L << 20))
                throw new IOException("Invalid server content storage reserve");
            store = privateRoot.resolve("runtimes/server-content-arm64");
            cache = privateRoot.resolve("runtime-embedded-cache/server-content-arm64");
            try (AssetFileDescriptor file = assets.openFd(ARCHIVE)) {
                if (file.getLength() != plan.archiveBytes) throw new IOException("Server content archive is not stored as pinned APK bytes");
            }
        } catch (JSONException | IllegalArgumentException error) { throw new IOException("Invalid server content metadata", error); }
    }

    public RuntimeInstaller.Result prepare(String actualDependencyArchive, RuntimeWork.Progress progress,
            RuntimeWork.Cancellation cancelled) throws IOException {
        requireServerRuntimeArchive(actualDependencyArchive);
        EmbeddedArchiveCache embedded = new EmbeddedArchiveCache(cache);
        // Keep the outer receipt beside the generation: it is the authority for,
        // and intentionally not an extra member of, the original source archive.
        preparedReceipt = embedded.obtain("package-receipt.json", receipt.length, receiptHash, offset -> {
            if (offset < 0 || offset > receipt.length) throw new IOException("Invalid server receipt resume offset");
            return new ByteArrayInputStream(receipt, (int) offset, receipt.length - (int) offset);
        }, progress, cancelled);
        RuntimeInstaller installer = installer();
        if (installer.resolveCurrent(plan) != null)
            return installer.install(cache.resolve("unused-completed-generation"), plan, progress, cancelled);
        Path archive = embedded.obtain(plan.archiveName, plan.archiveBytes, plan.archiveSha256, this::openArchive, progress, cancelled);
        if (!Files.exists(store.resolve("staging").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(store.resolve("generations").resolve(plan.generation), LinkOption.NOFOLLOW_LINKS) &&
                store.toFile().getUsableSpace() < freshFreeBytes - plan.archiveBytes - receipt.length)
            throw new IOException("Insufficient storage for server content");
        return installer.install(archive, plan, progress, cancelled);
    }
    public RuntimeInstaller installer() throws IOException { return new RuntimeInstaller(store); }
    public RuntimePackagePlan packagePlan() { return plan; }
    public Path current() throws IOException { return installer().resolveCurrent(plan); }
    public String generation() { return plan.generation; }
    public String archiveSha256() { return plan.archiveSha256; }
    public void requireServerRuntimeArchive(String actual) throws IOException {
        if (!dependencyHash.equals(actual)) throw new IOException("Server content requires a different Ubuntu dependency runtime");
    }
    public String receiptSha256() { return receiptHash; }
    public String sourceLockSha256() { return sourceLockHash; }
    public JSONObject serverSource() throws IOException { return object(sourceJson); }
    public JSONObject compiledModulesIdentity() throws IOException { return object(compiledJson); }
    public Path receiptPath() throws IOException {
        if (preparedReceipt == null) throw new IOException("Server content receipt has not been prepared");
        return preparedReceipt;
    }
    public static String guestMount() { return "/esteria-server-content"; }
    private static JSONObject object(String json) throws IOException {
        try { return new JSONObject(json); } catch (JSONException impossible) { throw new IOException("Invalid retained server selection", impossible); }
    }
    private static boolean sameJson(Object left, Object right) throws JSONException {
        if (left instanceof JSONObject && right instanceof JSONObject) {
            JSONObject a = (JSONObject) left, b = (JSONObject) right;
            if (a.length() != b.length()) return false;
            var names = a.keys();
            while (names.hasNext()) { String name = names.next(); if (!b.has(name) || !sameJson(a.get(name), b.get(name))) return false; }
            return true;
        }
        if (left instanceof JSONArray && right instanceof JSONArray) {
            JSONArray a = (JSONArray) left, b = (JSONArray) right;
            if (a.length() != b.length()) return false;
            for (int i = 0; i < a.length(); i++) if (!sameJson(a.get(i), b.get(i))) return false;
            return true;
        }
        return left.equals(right);
    }
    private InputStream openArchive(long offset) throws IOException {
        AssetFileDescriptor descriptor = assets.openFd(ARCHIVE); InputStream stream = null;
        try {
            if (offset < 0 || offset > plan.archiveBytes || descriptor.getLength() != plan.archiveBytes)
                throw new IOException("Invalid server content resume offset");
            stream = descriptor.createInputStream(); long remaining = offset;
            while (remaining > 0) {
                long count = stream.skip(remaining);
                if (count > 0) remaining -= count;
                else if (stream.read() < 0) throw new IOException("Truncated server content archive");
                else remaining--;
            }
            return stream;
        } catch (IOException | RuntimeException error) { if (stream != null) stream.close(); else descriptor.close(); throw error; }
    }
    private byte[] asset(String name, int maximum) throws IOException {
        try (InputStream input = assets.open(name); ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > maximum) throw new IOException("Server content metadata exceeds bound");
                output.write(buffer, 0, count);
            }
            return output.toByteArray();
        }
    }
    private static void identity(JSONObject pin, long maximum) throws JSONException, IOException {
        if (pin.getLong("bytes") <= 0 || pin.getLong("bytes") > maximum || !pin.getString("sha256").matches("[0-9a-f]{64}"))
            throw new IOException("Invalid server content identity");
    }
    private static String hash(byte[] bytes) throws IOException {
        try {
            StringBuilder result = new StringBuilder(64);
            for (byte value : MessageDigest.getInstance("SHA-256").digest(bytes))
                result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
