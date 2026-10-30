package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/** Canonical, versioned selection shared with server_data_generation.py.
 * Construction checks identities; only a source-verified provider may attest
 * where these bytes originated. It never makes a source qualification claim.
 */
public final class ServerDataToolSelection {
    public static final String CLIENT_REVISION="471ee42faadf4a97a1d0a86989cf1452621f2dc5";
    public static final String SERVER_REVISION="f35f04d01689f034778e3474b3c820092f51e461";
    public static final String CONFIG_SHA256="324479ef3821a0f9ef0c3f2d6b42c011eba1c31148eeaccd6bed3250c3d9c306";
    public static final Set<String> FILES=Set.of("bin/map_extractor","bin/vmap4_extractor","bin/vmap4_assembler",
        "bin/mmaps_generator","etc/mmaps-config.yaml","provenance/ordered-source-receipt.json");
    public final Map<String,RuntimePackagePlan.RequiredFile> files;
    public final String sha256;
    private final byte[] encoded;

    public ServerDataToolSelection(String client,String server,Map<String,RuntimePackagePlan.RequiredFile> files,
            RuntimePackagePlan.RequiredFile orderedReceipt)throws IOException {
        RuntimeFiles.require(CLIENT_REVISION.equals(client)&&SERVER_REVISION.equals(server),"Unsupported data tool source revisions");
        RuntimeFiles.require(files!=null&&files.keySet().equals(FILES)&&orderedReceipt!=null,"Exact six-file data tool selection required");
        TreeMap<String,RuntimePackagePlan.RequiredFile> copy=new TreeMap<>(files);
        for(var entry:copy.entrySet()) {
            RuntimePackagePlan.RequiredFile pin=entry.getValue();
            RuntimeFiles.require(pin!=null&&pin.bytes>0&&pin.bytes<=(16L<<30),"Invalid data tool file size");RuntimeFiles.hashPin(pin.sha256);
            RuntimeFiles.require(pin.peMachine==0&&pin.elfMachine==(entry.getKey().startsWith("bin/")?183:0),"Data tool file ABI differs");
        }
        RuntimePackagePlan.RequiredFile config=copy.get("etc/mmaps-config.yaml"),receipt=copy.get("provenance/ordered-source-receipt.json");
        RuntimeFiles.require(config.bytes==7888&&CONFIG_SHA256.equals(config.sha256),"Original relative data configuration required");
        RuntimeFiles.require(receipt.bytes==orderedReceipt.bytes&&receipt.sha256.equals(orderedReceipt.sha256),"Ordered source receipt identity differs");
        this.files=Collections.unmodifiableMap(copy);
        // Every key is from FILES, both revisions and digests are fixed hex,
        // and sizes are positive integers. This exactly matches Python's sorted
        // compact JSON plus newline without general JSON/string interpolation.
        StringBuilder text=new StringBuilder("{\"clientRevision\":\"").append(client).append("\",\"files\":{");
        boolean comma=false;
        for(var entry:copy.entrySet()) {
            if(comma)text.append(',');comma=true;
            text.append('"').append(entry.getKey()).append("\":");identity(text,entry.getValue());
        }
        text.append("},\"formatVersion\":1,\"orderedSourceReceipt\":");identity(text,receipt);
        text.append(",\"serverRevision\":\"").append(server).append("\"}\n");
        encoded=text.toString().getBytes(StandardCharsets.UTF_8);sha256=RuntimeFiles.hashText(text.toString());
    }
    private static void identity(StringBuilder text,RuntimePackagePlan.RequiredFile pin) {
        text.append("{\"bytes\":").append(pin.bytes).append(",\"sha256\":\"").append(pin.sha256).append("\"}");
    }
    public byte[] bytes(){return encoded.clone();}
}
