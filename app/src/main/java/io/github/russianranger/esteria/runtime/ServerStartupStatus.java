package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.ServerStartupTiming;
import java.io.IOException;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONException;
import org.json.JSONObject;

/** Production consumer for the guest's bounded diagnostic receipt, never readiness. */
final class ServerStartupStatus {
    private ServerStartupStatus(){ }
    static boolean accept(JSONObject value,ServerStartupTiming timing,long now)throws IOException {
        try {
            Set<String> keys=new HashSet<>();value.keys().forEachRemaining(keys::add);
            if(!keys.equals(Set.of("formatVersion","scope","operationId","sourceLockSha256","activeProofSha256",
                    "sequence","phase","process","readiness","elapsedMs","nativeElapsedMs","failureType"))||
                    integer(value,"formatVersion")!=1||!"owned-local-server-startup-status".equals(value.get("scope")))
                throw new IOException("Invalid server startup phase receipt");
            return timing.observe(now,value.getString("operationId"),value.getString("sourceLockSha256"),
                value.getString("activeProofSha256"),integer(value,"sequence"),value.getString("phase"),
                value.getString("process"),value.getString("readiness"),integer(value,"elapsedMs"),
                integer(value,"nativeElapsedMs"),value.getString("failureType"));
        }catch(JSONException error){throw new IOException("Invalid server startup phase receipt",error);}
    }
    static boolean acceptRead(JSONObject value,ServerStartupTiming timing,long now,String operation,String receipt,
            ServerStartupTiming.ReadStage stage)throws IOException {
        try {
            if(value.length()!=6||!operation.equals(value.getString("operationId"))||
                    !receipt.equals(value.getString("receiptSha256"))||!stage.id.equals(value.getString("role")))
                throw new IOException("Admission read operation/receipt/role differs");
            return timing.readProgress(now,stage,integer(value,"readBytes"),integer(value,"normalBytesPerSecond"),
                integer(value,"lowestBytesPerSecond"));
        }catch(JSONException error){throw new IOException("Invalid admission read receipt",error);}
    }
    private static long integer(JSONObject value,String key)throws JSONException,IOException {
        Object item=value.get(key);
        if(!(item instanceof Integer)&&!(item instanceof Long))throw new IOException("Integer server startup timing required");
        return ((Number)item).longValue();
    }
}
