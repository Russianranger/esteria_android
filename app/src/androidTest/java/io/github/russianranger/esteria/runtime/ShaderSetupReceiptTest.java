package io.github.russianranger.esteria.runtime;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.TreeMap;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Synthetic receipt/path guards only. No shader compiler or guest is executed. */
@RunWith(AndroidJUnit4.class)
public final class ShaderSetupReceiptTest {
    interface Action{void run()throws Exception;}
    static void refuses(Action action)throws Exception {try{action.run();}catch(IOException expected){return;}fail("Changed shader receipt accepted");}
    static String hash(byte[] bytes)throws Exception {StringBuilder out=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();}
    static void write(Path file,String value)throws IOException {Files.write(file,value.getBytes(StandardCharsets.UTF_8));}
    static JSONObject pin(byte[] bytes)throws Exception{return new JSONObject().put("bytes",bytes.length).put("sha256",hash(bytes));}
    static String canonical(JSONObject value)throws Exception {
        TreeMap<String,Object> sorted=new TreeMap<>();value.keys().forEachRemaining(k->{try{sorted.put(k,value.get(k));}catch(Exception e){throw new AssertionError(e);}});
        StringBuilder out=new StringBuilder("{");for(var item:sorted.entrySet()) {
            if(out.length()>1)out.append(',');out.append(JSONObject.quote(item.getKey())).append(':');
            Object v=item.getValue();out.append(v instanceof JSONObject?canonical((JSONObject)v):v instanceof String?JSONObject.quote((String)v):v.toString());
        }return out.append('}').toString();
    }
    @Test public void exactReceiptAndCurrentInputRequired()throws Exception {
        Path base=Files.createTempDirectory(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir().toPath(),"shader-receipt-").toRealPath();
        try {
            Path game=Files.createDirectory(base.resolve("game")),tools=Files.createDirectory(base.resolve("tools")),work=Files.createDirectory(base.resolve("work")),helpers=Files.createDirectory(base.resolve("helpers"));
            String imported="1".repeat(64),revision="2".repeat(40),manifest="3".repeat(64);
            Path data=Files.createDirectories(game.resolve("generations/"+imported+"/data"));
            write(game.resolve("current"),imported+"\n");
            byte[] complete="explicit synthetic metadata".getBytes(StandardCharsets.UTF_8),journal="synthetic journal".getBytes(StandardCharsets.UTF_8);
            Files.write(data.getParent().resolve("complete"),complete);Files.write(data.getParent().resolve("journal.tsv"),journal);
            JSONObject metadata=new JSONObject().put(imported+"/complete",pin(complete)).put(imported+"/journal.tsv",pin(journal));
            byte[] helper="synthetic APK helper".getBytes(StandardCharsets.UTF_8);Files.write(helpers.resolve("stock_shader_generation.py"),helper);
            JSONObject inputs=new JSONObject().put("formatVersion",1).put("contentProfile","stock-3.3.5a").put("importGeneration",imported).put("clientRevision",revision)
                .put("locale","enUS").put("importMetadata",metadata).put("toolManifestSha256",manifest).put("preparationHelperSha256",hash(helper));
            String generation=hash((canonical(inputs)+"\n").getBytes(StandardCharsets.UTF_8));
            Path output=Files.createDirectories(work.resolve("shaders/generations/"+generation+"/shaders"));
            JSONObject outputs=new JSONObject();
            for(String name:new String[]{"manifest.txt","index.txt","vertex/"+"4".repeat(32)+".spv","pixel/"+"5".repeat(32)+".spv"}) {
                Path file=output.resolve(name);Files.createDirectories(file.getParent());byte[] bytes=("synthetic:"+name).getBytes(StandardCharsets.UTF_8);Files.write(file,bytes);outputs.put(name,pin(bytes));
            }
            JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","local-generated-shaders-not-render-qualified")
                .put("generation",generation).put("inputs",inputs).put("outputs",outputs).put("graphicsQualified",false)
                .put("androidQualified",false).put("gameplayQualified",false);
            Path receiptFile=output.getParent().resolve("receipt.json");write(receiptFile,receipt.toString());
            write(work.resolve("shaders/current"),generation+"\n");
            ShaderRunPlan plan=new ShaderRunPlan(game,tools,work,helpers,revision,"enUS");
            ShaderSetup.Result result=ShaderSetup.validatePrepared(plan,manifest,base,false);
            assertEquals(4,result.outputFiles);assertEquals(generation,result.generation);assertEquals(output,result.shaders);
            receipt.put("androidQualified",true);write(receiptFile,receipt.toString());refuses(()->ShaderSetup.validatePrepared(plan,manifest,base,false));
            receipt.put("androidQualified",false).put("formatVersion","1");write(receiptFile,receipt.toString());refuses(()->ShaderSetup.validatePrepared(plan,manifest,base,false));
            receipt.put("formatVersion",1);write(receiptFile,receipt.toString());
            write(data.getParent().resolve("journal.tsv"),"changed journal!");refuses(()->ShaderSetup.validatePrepared(plan,manifest,base,false));Files.write(data.getParent().resolve("journal.tsv"),journal);
            write(game.resolve("current"),"6".repeat(64)+"\n");refuses(()->ShaderSetup.validatePrepared(plan,manifest,base,false));write(game.resolve("current"),imported+"\n");
            Path target=output.resolve("manifest.txt"),kept=base.resolve("kept");Files.move(target,kept);Files.createSymbolicLink(target,kept);
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,base,false));assertTrue(Files.isRegularFile(kept));
        }finally {try(var paths=Files.walk(base)){for(Path path:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator)Files.delete(path);}}
    }
}
