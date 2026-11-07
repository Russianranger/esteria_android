package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import org.json.JSONException;
import org.json.JSONObject;

/** Tests a hypothetical renderer-only pair against a real selected shader receipt.
 * The test descriptor and its synthetic PE hashes never enter the main APK. */
final class RendererCompatibilityTests {
    private static final String OLD_ARCHIVE = "5997af5a94a1151e708cf80fa9931e4055a887598e01c9cf21e6b3af0d438759";
    private static final String OLD_PE = "06557024cfaa974d02482eb98fedc186bc6b323ca730178347e153105343e12a";

    private interface Check { void run() throws Exception; }
    private static void rejects(Check check) throws Exception {
        try { check.run(); } catch (IOException | JSONException expected) { return; }
        throw new AssertionError("Unreviewed renderer pairing passed");
    }

    static void run(ShaderSetup.Result receipt) throws Exception {
        String oldRevision=receipt.clientRevision, newRevision="7".repeat(40), oldLock="a".repeat(64), newLock="b".repeat(64);
        String archive="1".repeat(64), pe="2".repeat(64), shaderArchive="4".repeat(64), wine="5".repeat(64);
        JSONObject legacy=new JSONObject().put("sourceRevision",oldRevision).put("sourceLockSha256",oldLock);
        RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",legacy,"",null,null)
                .requirePreparedShaders(oldRevision,receipt.toolManifestSha256);
        JSONObject client=new JSONObject().put("sourceRevision",newRevision).put("sourceLockSha256",newLock)
                .put("requiredWineArchiveSha256",wine).put("archive",new JSONObject().put("sha256",archive))
                .put("requiredFiles",new JSONObject().put("bin/WowClient64.exe",new JSONObject().put("sha256",pe)));
        JSONObject tools=new JSONObject().put("clientRevision",oldRevision).put("toolManifestSha256",receipt.toolManifestSha256)
                .put("requiredWineArchiveSha256",wine).put("archive",new JSONObject().put("sha256",shaderArchive));
        JSONObject pair=new JSONObject().put("formatVersion",1).put("scope","stock-renderer-only")
                .put("preparedClientRevision",oldRevision).put("preparedSourceLockSha256",oldLock)
                .put("previousClientArchiveSha256",OLD_ARCHIVE).put("previousExecutableSha256",OLD_PE)
                .put("executableRevision",newRevision).put("executableSourceLockSha256",newLock)
                .put("sourceDiffSha256","d".repeat(64)).put("clientArchiveSha256",archive).put("executableSha256",pe)
                .put("requiredWineArchiveSha256",wine).put("shaderToolsArchiveSha256",shaderArchive)
                .put("shaderToolManifestSha256",receipt.toolManifestSha256);
        byte[] descriptor=pair.toString().getBytes(StandardCharsets.UTF_8);
        String pin=ClientRuntimeSetup.hash(descriptor);
        RendererCompatibility verified=RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,pin,descriptor,tools);
        verified.requirePreparedShaders(receipt.clientRevision,receipt.toolManifestSha256);
        rejects(()->verified.requirePreparedShaders(newRevision,receipt.toolManifestSha256));
        rejects(()->verified.requirePreparedShaders(oldRevision,"0".repeat(64)));
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,"",null,null));
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",legacy,"",descriptor,tools));
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"esteria-custom",client,pin,descriptor,tools));
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,pin,null,tools));
        for (var keys=pair.keys();keys.hasNext();) {
            String key=keys.next();
            JSONObject changed=new JSONObject(pair.toString()).put(key,"0".repeat(64));
            byte[] raw=changed.toString().getBytes(StandardCharsets.UTF_8);
            rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,pin,raw,tools));
            // Source-diff bytes are reviewed by the source build and authenticated by the APK asset pin.
            if (!key.equals("sourceDiffSha256"))
                rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,ClientRuntimeSetup.hash(raw),raw,tools));
        }
        JSONObject restamped=new JSONObject(client.toString());
        restamped.getJSONObject("requiredFiles").getJSONObject("bin/WowClient64.exe").put("sha256",OLD_PE);
        byte[] wrongPe=new JSONObject(pair.toString()).put("executableSha256",OLD_PE).toString().getBytes(StandardCharsets.UTF_8);
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",restamped,ClientRuntimeSetup.hash(wrongPe),wrongPe,tools));
        byte[] extra=pair.put("unexpected",1).toString().getBytes(StandardCharsets.UTF_8);
        rejects(()->RendererCompatibility.select(oldRevision,oldLock,"stock-3.3.5a",client,ClientRuntimeSetup.hash(extra),extra,tools));
    }
}
