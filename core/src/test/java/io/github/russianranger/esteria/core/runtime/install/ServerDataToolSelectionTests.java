package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.TreeMap;

/** Canonical metadata interoperability only; no actual tool/source qualification. */
public final class ServerDataToolSelectionTests {
    interface Action{void run()throws Exception;}
    static void rejects(Action action)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError("Invalid tool selection accepted");}
    public static void main(String[] args)throws Exception {
        TreeMap<String,RuntimePackagePlan.RequiredFile> files=new TreeMap<>();
        for(String name:ServerDataToolSelection.FILES)files.put(name,new RuntimePackagePlan.RequiredFile(64,"a".repeat(64),name.startsWith("bin/")?183:0,0));
        files.put("etc/mmaps-config.yaml",new RuntimePackagePlan.RequiredFile(7888,ServerDataToolSelection.CONFIG_SHA256,0,0));
        var receipt=files.get("provenance/ordered-source-receipt.json");
        ServerDataToolSelection selection=new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,files,receipt);
        byte[] expected=Files.readAllBytes(Path.of(args[0]));
        if(!java.util.Arrays.equals(expected,selection.bytes())||!RuntimeFiles.hashText(new String(expected,StandardCharsets.UTF_8)).equals(selection.sha256))
            throw new AssertionError("Java selection differs from Python canonical JSON fixture");
        byte[] copy=selection.bytes();copy[0]=0;if(selection.bytes()[0]!='{')throw new AssertionError("Selection bytes were mutable");
        var bad=new TreeMap<>(files);bad.remove("bin/map_extractor");rejects(()->new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,bad,receipt));
        rejects(()->new ServerDataToolSelection("b".repeat(40),ServerDataToolSelection.SERVER_REVISION,files,receipt));
        var changed=new TreeMap<>(files);changed.put("etc/mmaps-config.yaml",new RuntimePackagePlan.RequiredFile(7888,"b".repeat(64),0,0));
        rejects(()->new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,changed,receipt));
        var other=new RuntimePackagePlan.RequiredFile(64,"b".repeat(64),0,0);
        rejects(()->new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,files,other));
        var wrongAbi=new TreeMap<>(files);wrongAbi.put("bin/map_extractor",new RuntimePackagePlan.RequiredFile(64,"a".repeat(64),62,0));
        rejects(()->new ServerDataToolSelection(ServerDataToolSelection.CLIENT_REVISION,ServerDataToolSelection.SERVER_REVISION,wrongAbi,receipt));
        System.out.println("Data tool selection matches Python canonical bytes; source/ABI/configuration/closure guards passed; no tool execution claimed");
    }
}
