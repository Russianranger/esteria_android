package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.runtime.install.DownloadCache;
import io.github.russianranger.esteria.core.runtime.install.RuntimeInstaller;
import io.github.russianranger.esteria.core.runtime.install.RuntimePackagePlan;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import java.util.TreeSet;

/** Explicit, source-pinned client runtime setup. Preparing files never starts a guest. */
public final class RuntimeSetup {
    private final RuntimePackagePlan plan;
    private final URI download;
    private final Path store;
    private final Path cache;

    public RuntimeSetup(Context context, Path privateRoot) throws IOException {
        try {
            JSONObject lock = new JSONObject(readLock(context));
            if (lock.getInt("formatVersion") != 1) throw new IOException("Unsupported runtime source lock");
            JSONObject profile = lock.getJSONObject("androidInstallation");
            String key = profile.getString("packageKey");
            if (!"wine-arm64".equals(key) || profile.getInt("formatVersion") != 1)
                throw new IOException("Unsupported client runtime installation profile");
            JSONObject selected = lock.getJSONObject("packages").getJSONObject(key);
            JSONObject archive = selected.getJSONObject("archive");
            JSONObject bounds = selected.getJSONObject("limits");
            Map<String, RuntimePackagePlan.RequiredFile> required = new TreeMap<>();
            addFiles(required, selected.getJSONObject("components"));
            addFiles(required, profile.getJSONObject("requiredMetadata"));
            RuntimePackagePlan.Limits limits = new RuntimePackagePlan.Limits(bounds.getInt("entries"),
                    bounds.getLong("memberBytes"), bounds.getLong("fileBytes"), bounds.getInt("pathBytes"),
                    profile.getLong("metadataBytes"));
            JSONObject identity = new JSONObject().put("package", selected).put("installation", profile);
            plan = new RuntimePackagePlan(key, sha256(canonical(identity)), archive.getString("file"),
                    archive.getLong("bytes"), archive.getString("sha256"), selected.getLong("archiveEntries"),
                    selected.getLong("archiveFileBytes"), limits, required);
            download = new URI(archive.getString("url"));
            if (!"https".equals(download.getScheme()) || download.getHost() == null ||
                    download.getUserInfo() != null || download.getFragment() != null)
                throw new IOException("Runtime download must use a pinned HTTPS URL");
            store = privateRoot.resolve("runtimes").resolve(key);
            cache = privateRoot.resolve("runtime-downloads");
        } catch (JSONException | URISyntaxException | IllegalArgumentException exception) {
            throw new IOException("Invalid runtime installation metadata", exception);
        }
    }

    public RuntimeInstaller.Result prepare(RuntimeWork.Progress progress, RuntimeWork.Cancellation cancelled)
            throws IOException {
        RuntimeInstaller installer = new RuntimeInstaller(store);
        // A verified active generation is sufficient for repeat/offline setup.
        // RuntimeInstaller returns it before opening the archive; do not hash or
        // redownload 613 MB just to add an independently packaged bridge update.
        if (installer.resolveCurrent(plan) != null)
            return installer.install(cache.resolve("unused-completed-generation"), plan, progress, cancelled);
        Path archive = new DownloadCache(cache).obtain(download, plan.archiveName, plan.archiveBytes,
                plan.archiveSha256, progress, cancelled);
        return installer.install(archive, plan, progress, cancelled);
    }

    public Path current() throws IOException { return new RuntimeInstaller(store).resolveCurrent(plan); }
    public String generation() { return plan.generation; }
    public String archiveSha256() { return plan.archiveSha256; }
    public String sourcePinSha256() { return plan.sourcePinSha256; }

    private static void addFiles(Map<String, RuntimePackagePlan.RequiredFile> files, JSONObject source)
            throws JSONException, IOException {
        for (Iterator<String> keys = source.keys(); keys.hasNext();) {
            String name = keys.next();
            JSONObject file = source.getJSONObject(name);
            int elf = file.optInt("elfMachine", 0);
            int pe = file.has("peMachine") ? Integer.decode(file.getString("peMachine")) : 0;
            RuntimePackagePlan.RequiredFile requirement = new RuntimePackagePlan.RequiredFile(
                    file.getLong("bytes"), file.getString("sha256"), elf, pe);
            if (files.put(name, requirement) != null) throw new IOException("Duplicate runtime component pin");
        }
    }

    private static String readLock(Context context) throws IOException {
        try (InputStream input = context.getAssets().open("runtime-sources.lock.json");
             ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[4096];
            for (int count; (count = input.read(buffer)) != -1;) {
                if (output.size() + count > 128 * 1024) throw new IOException("Runtime source lock exceeds limit");
                output.write(buffer, 0, count);
            }
            return new String(output.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    /** Ignore object insertion order and unrelated server/graphics lock fields. */
    private static String canonical(Object value) throws JSONException, IOException {
        if (value instanceof JSONObject) {
            JSONObject object = (JSONObject) value;
            TreeSet<String> names = new TreeSet<>();
            for (Iterator<String> keys = object.keys(); keys.hasNext();) names.add(keys.next());
            StringBuilder result = new StringBuilder("{");
            boolean first = true;
            for (String name : names) {
                if (!first) result.append(',');
                first = false;
                result.append(JSONObject.quote(name)).append(':').append(canonical(object.get(name)));
            }
            return result.append('}').toString();
        }
        if (value instanceof JSONArray) {
            JSONArray array = (JSONArray) value;
            StringBuilder result = new StringBuilder("[");
            for (int index = 0; index < array.length(); index++) {
                if (index != 0) result.append(',');
                result.append(canonical(array.get(index)));
            }
            return result.append(']').toString();
        }
        if (value == JSONObject.NULL) return "null";
        if (value instanceof String) return JSONObject.quote((String) value);
        if (value instanceof Number) return JSONObject.numberToString((Number) value);
        if (value instanceof Boolean) return value.toString();
        throw new IOException("Unsupported runtime lock value");
    }

    private static String sha256(String text) throws IOException {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(64);
            for (byte value : digest) result.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new IOException("SHA-256 unavailable", impossible); }
    }
}
