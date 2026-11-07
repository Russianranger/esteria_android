package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.ServerStartupTiming;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.json.JSONObject;

/** Host execution of the production status consumer with actual Android JSON sources. */
public final class ServerStartupStatusTests {
    private static ServerStartupTiming timing(){return new ServerStartupTiming(0,"a".repeat(32),"b".repeat(64),"c".repeat(64));}
    private static void rejected(JSONObject value)throws Exception {
        try{ServerStartupStatus.accept(value,timing(),10);throw new AssertionError("Invalid status accepted");}
        catch(IOException expected){ }
    }
    public static void main(String[] args)throws Exception {
        String text=Files.readString(Path.of(args[0]));JSONObject value=new JSONObject(text);
        if(!ServerStartupStatus.accept(value,timing(),10))throw new AssertionError("Python receipt not accepted");
        for(String name:new String[]{"formatVersion","sequence","elapsedMs","nativeElapsedMs"}) {
            JSONObject changed=new JSONObject(text);changed.put(name,changed.get(name).toString());rejected(changed);
            changed=new JSONObject(text);changed.put(name,true);rejected(changed);
        }
        for(String name:new String[]{"operationId","sourceLockSha256","activeProofSha256","scope"}) {
            JSONObject changed=new JSONObject(text);changed.put(name,"other");rejected(changed);
        }
        JSONObject changed=new JSONObject(text);changed.put("gameplayQualified",true);rejected(changed);
        changed=new JSONObject(text);changed.remove("scope");rejected(changed);
        System.out.println("PASS: Python startup receipt consumed by production Android JSON consumer");
    }
}
