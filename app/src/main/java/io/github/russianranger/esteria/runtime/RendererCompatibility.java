package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/** Keeps a reviewed executable-only update separate from the prepared content identity. */
final class RendererCompatibility {
    private static final String BASE_ARCHIVE = "5997af5a94a1151e708cf80fa9931e4055a887598e01c9cf21e6b3af0d438759";
    private static final String BASE_EXECUTABLE = "06557024cfaa974d02482eb98fedc186bc6b323ca730178347e153105343e12a";
    private static final Set<String> HASH_FIELDS = Set.of("preparedSourceLockSha256", "previousClientArchiveSha256",
            "previousExecutableSha256", "executableSourceLockSha256", "sourceDiffSha256", "clientArchiveSha256",
            "executableSha256", "requiredWineArchiveSha256", "shaderToolsArchiveSha256", "shaderToolManifestSha256");
    final String preparedRevision;
    final String shaderManifest;

    private RendererCompatibility(String preparedRevision, String shaderManifest) {
        this.preparedRevision = preparedRevision;
        this.shaderManifest = shaderManifest;
    }

    static RendererCompatibility select(String baseRevision, String baseLock, String profile, JSONObject client,
            String approvedHash, byte[] descriptor, JSONObject shaderTools) throws IOException, JSONException {
        if (approvedHash.isEmpty()) {
            if (descriptor != null || !baseRevision.equals(client.get("sourceRevision"))
                    || !baseLock.equals(client.get("sourceLockSha256")))
                throw new IOException("Reconstructed client does not match the application source lock");
            return new RendererCompatibility(baseRevision, null);
        }
        if (!"stock-3.3.5a".equals(profile) || descriptor == null || shaderTools == null
                || !ClientRuntimeSetup.hash(descriptor).equals(approvedHash))
            throw new IOException("Missing or changed stock renderer compatibility descriptor");
        JSONObject pair = new JSONObject(new String(descriptor, StandardCharsets.UTF_8));
        if (pair.length() != HASH_FIELDS.size() + 4 || !Integer.valueOf(1).equals(pair.get("formatVersion"))
                || !"stock-renderer-and-archive-read".equals(pair.get("scope")))
            throw new IOException("Invalid stock renderer compatibility scope");
        for (String field : HASH_FIELDS) {
            Object hash = pair.get(field);
            if (!(hash instanceof String) || !((String) hash).matches("[0-9a-f]{64}"))
                throw new IOException("Invalid renderer compatibility hash " + field);
        }
        Object executable = client.get("sourceRevision");
        if (!(executable instanceof String) || !((String) executable).matches("[0-9a-f]{40}")
                || baseRevision.equals(executable) || !executable.equals(pair.get("executableRevision"))
                || !baseRevision.equals(pair.get("preparedClientRevision"))
                || !baseLock.equals(pair.get("preparedSourceLockSha256"))
                || !BASE_ARCHIVE.equals(pair.get("previousClientArchiveSha256"))
                || !BASE_EXECUTABLE.equals(pair.get("previousExecutableSha256")))
            throw new IOException("Unexpected source revision or donor for stock renderer");
        if (baseLock.equals(pair.get("executableSourceLockSha256"))
                || BASE_ARCHIVE.equals(pair.get("clientArchiveSha256"))
                || BASE_EXECUTABLE.equals(pair.get("executableSha256"))
                || !pair.get("executableSourceLockSha256").equals(client.get("sourceLockSha256"))
                || !pair.get("clientArchiveSha256").equals(client.getJSONObject("archive").get("sha256"))
                || !pair.get("executableSha256").equals(client.getJSONObject("requiredFiles").getJSONObject("bin/WowClient64.exe").get("sha256"))
                || !pair.get("requiredWineArchiveSha256").equals(client.get("requiredWineArchiveSha256")))
            throw new IOException("Stock renderer executable, provider archive or Wine binding changed");
        if (!baseRevision.equals(shaderTools.get("clientRevision"))
                || !pair.get("shaderToolsArchiveSha256").equals(shaderTools.getJSONObject("archive").get("sha256"))
                || !pair.get("shaderToolManifestSha256").equals(shaderTools.get("toolManifestSha256"))
                || !pair.get("requiredWineArchiveSha256").equals(shaderTools.get("requiredWineArchiveSha256")))
            throw new IOException("Stock renderer requires its reviewed shader provider and manifest");
        return new RendererCompatibility(baseRevision, pair.getString("shaderToolManifestSha256"));
    }

    void requirePreparedShaders(String receiptRevision, String receiptManifest) throws IOException {
        if (!preparedRevision.equals(receiptRevision) || (shaderManifest != null && !shaderManifest.equals(receiptManifest)))
            throw new IOException("Prepared shaders do not match this reconstructed client");
    }
}
