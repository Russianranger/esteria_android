package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import org.json.JSONArray;
import org.json.JSONObject;

/** Actual production binding + exact Android 13 parser on a host JVM. */
public final class ReceiptBindingHarness {
    private interface Action {void run()throws Exception;}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static void refuses(Action action)throws Exception {try{action.run();throw new AssertionError("Invalid binding accepted");}catch(IOException expected){ }}
    private static JSONObject read(Path path)throws Exception {return new JSONObject(Files.readString(path));}
    private static String hash(String value)throws Exception {StringBuilder out=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)))out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();}
    public static void main(String[] args)throws Exception {
        Path fixture=Path.of(args[1]).toRealPath();
        if(args[0].equals("codec")) {
            check(JSONObject.quote("a/b").equals("\"a\\/b\""),"Pinned Android slash escaping was not executed");
            JSONArray vectors=new JSONArray(Files.readString(fixture.resolve("codec-vectors.json")));
            for(int n=0;n<vectors.length();n++) {
                JSONObject row=vectors.getJSONObject(n);String actual=PythonReceiptJson.canonical(row.getJSONObject("value"));
                check(actual.equals(row.getString("canonical")),"Python canonical bytes differ at vector "+n);
                check(hash(actual+"\n").equals(row.getString("sha256")),"Python hash differs at vector "+n);
            }
            for(Object value:new Object[]{new JSONArray(),JSONObject.NULL,Double.valueOf(1.25)})refuses(()->PythonReceiptJson.canonical(new JSONObject().put("bad",value)));
            refuses(()->PythonReceiptJson.canonical(new JSONObject().put("bool",true),false));
            System.out.println("{\"vectorsPassed\":"+vectors.length()+",\"android13QuoteExecuted\":true,\"strictValueTypes\":true}");
            return;
        }
        JSONObject metadata=read(fixture.resolve("fixture.json")),info=metadata.getJSONObject("data");Path root=fixture.resolve("data");
        Path work=root.resolve("work"),game=root.resolve("game"),tools=root.resolve("tools");Files.createDirectories(tools);
        ServerDataRunPlan plan=new ServerDataRunPlan(game,tools,work,info.getString("helperGeneration"),info.getString("toolSelectionSha256"),"enUS",1);
        Path store=work.resolve("server-data"),selected=store.resolve("generations").resolve(info.getString("generation")),receipt=selected.resolve("receipt.json");
        byte[] original=Files.readAllBytes(receipt);Path world=selected.resolve("data/mmaps/000.mmap");var stamp=Files.getLastModifiedTime(world);
        ServerDataBinding bound=ServerDataBinding.inspect(plan,info.getString("serverRevision"));bound.requireUnchanged();
        check(bound.generation.equals(info.getString("generation")),"Actual Python generation not accepted");
        JSONArray mutants=new JSONArray(Files.readString(fixture.resolve("data-mutants.json")));
        for(int n=0;n<mutants.length();n++) {
            JSONObject row=mutants.getJSONObject(n),changed=new JSONObject(new String(original,StandardCharsets.UTF_8));
            String key=row.getString("generation");Path moved=selected.resolveSibling(key);changed.put("inputs",row.getJSONObject("inputs")).put("generation",key);
            Files.move(selected,moved);Files.writeString(store.resolve("current"),key+"\n");Files.writeString(moved.resolve("receipt.json"),changed.toString());
            try {refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));}
            finally {Files.move(moved,selected);Files.write(receipt,original);Files.writeString(store.resolve("current"),info.getString("generation")+"\n");}
        }
        JSONObject changed=new JSONObject(new String(original,StandardCharsets.UTF_8));changed.getJSONObject("preflight").put("checks_passed",false);
        Files.writeString(receipt,changed.toString());refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));Files.write(receipt,original);
        Path journal=game.resolve("generations").resolve(metadata.getString("importGeneration")).resolve("journal.tsv");byte[] retained=Files.readAllBytes(journal);
        Files.writeString(journal,"CHANGED\n");refuses(bound::requireUnchanged);Files.write(journal,retained);bound.requireUnchanged();
        check(stamp.equals(Files.getLastModifiedTime(world)),"Consumer rewrote completed world data");
        System.out.println("{\"pythonGenerationAccepted\":true,\"matchingHashMutantsRejected\":"+mutants.length()+",\"completedDataUnchanged\":true,\"generation\":\""+bound.generation+"\"}");
    }
}
