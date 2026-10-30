package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.BuildConfig;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/** Locates verified APK-installed process payloads. It does not launch a runtime. */
public final class InstalledProot {
    public final File tracer;
    public final File loader;
    public final String sourceLockSha256;

    private InstalledProot(File tracer, File loader, String sourceLockSha256) {
        this.tracer = tracer;
        this.loader = loader;
        this.sourceLockSha256 = sourceLockSha256;
    }

    public static InstalledProot inspect(Context context) throws IOException {
        if (!BuildConfig.PROOT_PACKAGED) throw new IOException("This build has no packaged PRoot runtime bridge");
        try {
            JSONObject proof;
            try (InputStream input = context.getAssets().open("proot/build-evidence.json")) {
                proof = new JSONObject(new String(readBounded(input, 65536), java.nio.charset.StandardCharsets.UTF_8));
            }
            if (proof.getInt("formatVersion") != 1 || !proof.getBoolean("androidBridgeBuilt") ||
                    proof.getBoolean("androidBridgeExecuted") || proof.getBoolean("androidRuntimeQualified") ||
                    !"android-arm64-proot-build-only".equals(proof.getString("scope"))) {
                throw new IOException("Unexpected PRoot build evidence");
            }
            File directory = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalFile();
            File tracer = verify(directory, "libproot.so", proof.getJSONObject("payloads"));
            File loader = verify(directory, "libproot-loader.so", proof.getJSONObject("payloads"));
            return new InstalledProot(tracer, loader, proof.getString("sourceLockSha256"));
        } catch (org.json.JSONException | NoSuchAlgorithmException exception) {
            throw new IOException("Invalid packaged PRoot metadata", exception);
        }
    }

    private static File verify(File directory, String name, JSONObject payloads)
            throws IOException, org.json.JSONException, NoSuchAlgorithmException {
        File path = new File(directory, name).getCanonicalFile();
        JSONObject expected = payloads.getJSONObject(name);
        long size = expected.getLong("bytes");
        if (!directory.equals(path.getParentFile()) || !path.isFile() || !path.canExecute() ||
                size <= 0 || size > 16 * 1024 * 1024 || path.length() != size) {
            throw new IOException("Missing or invalid APK-installed native payload: " + name);
        }
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        long total = 0;
        byte[] buffer = new byte[65536];
        try (InputStream input = new FileInputStream(path)) {
            int count;
            while ((count = input.read(buffer)) != -1) {
                total += count;
                if (total > size) throw new IOException("Native payload changed during verification");
                digest.update(buffer, 0, count);
            }
        }
        StringBuilder actual = new StringBuilder(64);
        for (byte value : digest.digest()) actual.append(String.format(java.util.Locale.ROOT, "%02x", value & 255));
        if (total != size || !actual.toString().equals(expected.getString("sha256"))) {
            throw new IOException("APK-installed native payload hash differs: " + name);
        }
        return path;
    }

    private static byte[] readBounded(InputStream input, int maximum) throws IOException {
        ByteArrayOutputStream result = new ByteArrayOutputStream();
        byte[] buffer = new byte[4096];
        int count;
        while ((count = input.read(buffer)) != -1) {
            if (result.size() + count > maximum) throw new IOException("Oversized native metadata");
            result.write(buffer, 0, count);
        }
        return result.toByteArray();
    }
}
