package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Bundle;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.Comparator;
import java.util.Iterator;
import org.json.JSONArray;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Production Python receipts consumed by the actual Android Java code.
 * Native extractors/compiler are replaced only in the fixture producer; no
 * owner assets, navigation generation, rendering or gameplay is qualified. */
@RunWith(AndroidJUnit4.class)
public final class PythonReceiptBindingTest {
    private static final String ASSETS="python-receipts/";
    private interface Action {void run()throws Exception;}
    private static void refuses(Action action)throws Exception {try{action.run();fail("Invalid receipt accepted");}catch(IOException expected){ }}
    private static Context target(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    private static byte[] asset(String name)throws Exception {
        try(var in=InstrumentationRegistry.getInstrumentation().getContext().getAssets().open(ASSETS+name)) {
            byte[] bytes=in.readAllBytes();assertTrue(bytes.length<1<<20);return bytes;
        }
    }
    private static JSONObject metadata()throws Exception {return new JSONObject(new String(asset("fixture.json"),StandardCharsets.UTF_8));}
    private static String hash(byte[] bytes)throws Exception {
        StringBuilder out=new StringBuilder(64);
        for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));
        return out.toString();
    }
    private static void write(Path path,String value)throws Exception {Files.write(path,value.getBytes(StandardCharsets.UTF_8));}
    private static void remove(Path path)throws Exception {try(var files=Files.walk(path)){for(Path item:(Iterable<Path>)files.sorted(Comparator.reverseOrder())::iterator)Files.delete(item);}}
    private static Path copy(String kind,JSONObject fixture)throws Exception {
        Path root=Files.createTempDirectory(target().getFilesDir().getCanonicalFile().toPath(),"python-"+kind+"-").toRealPath();
        Files.createDirectory(root.resolve("tools"));
        JSONObject files=fixture.getJSONObject("files");
        for(Iterator<String> names=files.keys();names.hasNext();) {
            String name=names.next();if(!name.startsWith(kind+"/"))continue;
            String relative=name.substring(kind.length()+1);assertFalse(relative.contains(".."));
            byte[] bytes=asset(name);JSONObject pin=files.getJSONObject(name);
            assertEquals(pin.getLong("bytes"),bytes.length);assertEquals(pin.getString("sha256"),hash(bytes));
            Path output=root.resolve(relative);assertTrue(output.normalize().startsWith(root));
            Files.createDirectories(output.getParent());Files.write(output,bytes);
        }
        return root;
    }
    private static void report(String name,JSONObject info,int refused)throws Exception {
        observation(new JSONObject().put("scope","android13-x64-production-python-receipt-fixture")
            .put("case",name).put("generation",info.getString("generation")).put("producer","production-python")
            .put("consumer","production-android-java").put("matchingPythonHashMutantsRejected",refused)
            .put("ownerGameData",false).put("nativeToolExecution",false).put("thorQualified",false).put("gameplayQualified",false));
    }
    private static void observation(JSONObject value) {
        Bundle status=new Bundle();status.putString("stream","PYTHON_RECEIPT_OBSERVATION="+value+"\n");
        InstrumentationRegistry.getInstrumentation().sendStatus(2,status);
    }

    @Test public void pythonDataGenerationAcceptedAndMutationsRejected()throws Exception {
        JSONObject fixture=metadata(),info=fixture.getJSONObject("data");Path root=copy("data",fixture);
        try {
            Path game=root.resolve("game"),tools=root.resolve("tools"),work=root.resolve("work");
            String helper=ServerDataAssets.install(target(),work);assertEquals(info.getString("helperGeneration"),helper);
            assertEquals(BuildConfig.CLIENT_REVISION,info.getString("clientRevision"));
            ServerDataRunPlan plan=new ServerDataRunPlan(game,tools,work,helper,info.getString("toolSelectionSha256"),"enUS",1);
            Path store=work.resolve("server-data"),selected=store.resolve("generations").resolve(info.getString("generation"));
            Path receipt=selected.resolve("receipt.json"),world=selected.resolve("data/mmaps/000.mmap");
            byte[] original=Files.readAllBytes(receipt),worldBytes=Files.readAllBytes(world);var stamp=Files.getLastModifiedTime(world);
            ServerDataBinding binding=ServerDataBinding.inspect(plan,info.getString("serverRevision"));
            assertEquals(info.getString("generation"),binding.generation);binding.requireUnchanged();
            ServerDataBinding.inspect(plan,info.getString("serverRevision")).requireUnchanged();
            assertArrayEquals(original,Files.readAllBytes(receipt));assertArrayEquals(worldBytes,Files.readAllBytes(world));assertEquals(stamp,Files.getLastModifiedTime(world));
            JSONArray mutants=new JSONArray(new String(asset("data-mutants.json"),StandardCharsets.UTF_8));
            for(int index=0;index<mutants.length();index++) {
                JSONObject mutant=mutants.getJSONObject(index),changed=new JSONObject(new String(original,StandardCharsets.UTF_8));
                String key=mutant.getString("generation");Path moved=selected.resolveSibling(key);
                changed.put("inputs",mutant.getJSONObject("inputs")).put("generation",key);
                Files.move(selected,moved);write(store.resolve("current"),key+"\n");write(moved.resolve("receipt.json"),changed.toString());
                try {refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));}
                finally {Files.move(moved,selected);Files.write(receipt,original);write(store.resolve("current"),info.getString("generation")+"\n");}
            }
            JSONObject changed=new JSONObject(new String(original,StandardCharsets.UTF_8));
            changed.put("worldQualified",true);write(receipt,changed.toString());refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));
            changed.put("worldQualified",false).getJSONObject("preflight").put("checks_passed",false);write(receipt,changed.toString());
            refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));
            Files.write(receipt,original);
            Path imported=game.resolve("generations").resolve(fixture.getString("importGeneration")).resolve("journal.tsv");
            byte[] journal=Files.readAllBytes(imported);write(imported,"CHANGED_IMPORT_METADATA\n");
            refuses(binding::requireUnchanged);refuses(()->ServerDataBinding.inspect(plan,info.getString("serverRevision")));Files.write(imported,journal);
            binding.requireUnchanged();assertArrayEquals(worldBytes,Files.readAllBytes(world));assertEquals(stamp,Files.getLastModifiedTime(world));
            assertFalse(Files.exists(work.resolve("server-sessions")));assertFalse(Files.exists(work.resolve("state/server-setup-complete.json")));
            report("pythonDataGenerationAcceptedAndMutationsRejected",info,mutants.length());
        }finally {remove(root);}
    }

    @Test public void pythonShaderGenerationAcceptedAndMutationsRejected()throws Exception {
        JSONObject fixture=metadata(),info=fixture.getJSONObject("shader");Path root=copy("shader",fixture);
        try {
            Path game=root.resolve("game"),tools=root.resolve("tools"),work=root.resolve("work");
            Path helpers=StockClientSetup.installHelpers(target(),target().getFilesDir().getCanonicalFile().toPath());
            ShaderRunPlan plan=new ShaderRunPlan(game,tools,work,helpers,info.getString("clientRevision"),"enUS");
            Path store=work.resolve("shaders"),selected=store.resolve("generations").resolve(info.getString("generation")),receipt=selected.resolve("receipt.json");
            byte[] original=Files.readAllBytes(receipt);Path output=selected.resolve("shaders/manifest.txt");byte[] retained=Files.readAllBytes(output);var stamp=Files.getLastModifiedTime(output);
            ShaderSetup.Result result=ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false);
            assertEquals(info.getString("generation"),result.generation);assertEquals(4,result.outputFiles);
            // Metadata selection does not carry an integrity lease into the
            // next session. Exercise that production full-verification mode
            // against equal-length corruption, additions and cancellation.
            ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false,true);
            byte[] changedPayload=retained.clone();changedPayload[0]^=1;Files.write(output,changedPayload);
            ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false);
            refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false,true));
            Files.write(output,retained);Files.setLastModifiedTime(output,stamp);
            Path extra=selected.resolve("shaders/unexpected.spv");write(extra,"UNEXPECTED");
            refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false,true));Files.delete(extra);
            java.util.concurrent.atomic.AtomicInteger checks=new java.util.concurrent.atomic.AtomicInteger();
            try {
                ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false,true,()->checks.incrementAndGet()>3);
                fail("Full verification must observe cancellation");
            } catch(io.github.russianranger.esteria.core.runtime.install.RuntimeWork.CancelledException expected) {
                assertTrue(checks.get()>3);
            }
            ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false,true);
            JSONArray mutants=new JSONArray(new String(asset("shader-mutants.json"),StandardCharsets.UTF_8));
            for(int index=0;index<mutants.length();index++) {
                JSONObject mutant=mutants.getJSONObject(index),changed=new JSONObject(new String(original,StandardCharsets.UTF_8));
                String key=mutant.getString("generation");Path moved=selected.resolveSibling(key);
                changed.put("inputs",mutant.getJSONObject("inputs")).put("generation",key);
                Files.move(selected,moved);write(store.resolve("current"),key+"\n");write(moved.resolve("receipt.json"),changed.toString());
                try {refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));}
                finally {Files.move(moved,selected);Files.write(receipt,original);write(store.resolve("current"),info.getString("generation")+"\n");}
            }
            JSONObject changed=new JSONObject(new String(original,StandardCharsets.UTF_8));
            changed.put("androidQualified",true);write(receipt,changed.toString());refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));Files.write(receipt,original);
            changed.put("androidQualified",false).put("formatVersion","1");write(receipt,changed.toString());
            refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));Files.write(receipt,original);
            byte[] wrapper=Files.readAllBytes(helpers.resolve("stock_shader_translate.py"));
            try {write(helpers.resolve("stock_shader_translate.py"),"CHANGED_SYNTHETIC_WRAPPER");refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));}
            finally {Files.write(helpers.resolve("stock_shader_translate.py"),wrapper);}
            write(game.resolve("current"),"6".repeat(64)+"\n");refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));
            write(game.resolve("current"),fixture.getString("importGeneration")+"\n");
            Path imported=game.resolve("generations").resolve(fixture.getString("importGeneration")).resolve("journal.tsv");byte[] journal=Files.readAllBytes(imported);
            write(imported,"CHANGED_IMPORT_METADATA\n");refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));Files.write(imported,journal);
            Path moved=root.resolve("retained-manifest");Files.move(output,moved);Files.createSymbolicLink(output,moved);
            refuses(()->ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false));Files.delete(output);Files.move(moved,output);
            ShaderSetup.validatePrepared(plan,info.getString("toolManifestSha256"),root,false);
            assertArrayEquals(retained,Files.readAllBytes(output));assertEquals(stamp,Files.getLastModifiedTime(output));
            exerciseV12ShaderReuse(plan,info,store);
            report("pythonShaderGenerationAcceptedAndMutationsRejected",info,mutants.length());
        }finally {remove(root);}
    }

    private static void exerciseV12ShaderReuse(ShaderRunPlan plan,JSONObject info,Path store)throws Exception {
        String manifest=info.getString("toolManifestSha256"),previous=info.getString("previousGeneration");
        assertNull(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null));
        Path pointer=store.resolve("current"),generation=store.resolve("generations").resolve(previous);
        Path payload=generation.resolve("shaders/manifest.txt"),receipt=generation.resolve("receipt.json");
        byte[] original=Files.readAllBytes(payload),before=Files.readAllBytes(receipt);
        var mtime=Files.getLastModifiedTime(payload);
        write(pointer,previous+"\n");
        assertEquals(previous,ShaderSetup.validatePrepared(plan,manifest,null,false).generation);
        assertEquals(previous,ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null).generation);
        assertNull(ShaderSetup.verifyCompatibleCompleted(plan,"0".repeat(64),null,null));
        byte[] corrupt=original.clone();corrupt[0]^=1;
        Files.write(payload,corrupt);
        assertNull(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null));
        refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false,true));
        Files.write(payload,original);Files.setLastModifiedTime(payload,mtime);
        Path adapter=plan.helpers.resolve("stock_shader_translate.py");
        byte[] installed=Files.readAllBytes(adapter);
        try {
            write(adapter,"future-adapter-with-unreviewed-semantics");
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false));
            assertNull(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null));
        }finally {Files.write(adapter,installed);}
        java.util.concurrent.atomic.AtomicInteger polls=new java.util.concurrent.atomic.AtomicInteger();
        try {
            ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,()->polls.incrementAndGet()>3);
            fail("Cancellation during v12 verification was lost");
        }catch(io.github.russianranger.esteria.core.runtime.install.RuntimeWork.CancelledException expected){
            assertTrue(polls.get()>3);
        }
        assertEquals(previous,ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null).generation);
        assertEquals(previous+"\n",Files.readString(pointer));assertArrayEquals(before,Files.readAllBytes(receipt));
        assertArrayEquals(original,Files.readAllBytes(payload));assertEquals(mtime,Files.getLastModifiedTime(payload));
    }

    @Test public void pythonCanonicalVectorsMatchExactly()throws Exception {
        assertEquals("\"a\\/b\"",JSONObject.quote("a/b"));
        JSONArray vectors=new JSONArray(new String(asset("codec-vectors.json"),StandardCharsets.UTF_8));
        for(int index=0;index<vectors.length();index++) {
            JSONObject vector=vectors.getJSONObject(index);String actual=PythonReceiptJson.canonical(vector.getJSONObject("value"));
            assertEquals(vector.getString("canonical"),actual);assertEquals(vector.getString("sha256"),hash((actual+"\n").getBytes(StandardCharsets.US_ASCII)));
        }
        for(Object value:new Object[]{new JSONArray(),JSONObject.NULL,Double.valueOf(1.25)})refuses(()->PythonReceiptJson.canonical(new JSONObject().put("unsupported",value)));
        refuses(()->PythonReceiptJson.canonical(new JSONObject().put("boolean",true),false));
        observation(new JSONObject().put("scope","android13-x64-production-python-receipt-fixture")
            .put("case","pythonCanonicalVectorsMatchExactly").put("vectors",vectors.length()).put("literalSlash",true)
            .put("asciiUnicodeEscapes",true).put("pythonCodepointKeyOrder",true).put("strictValueTypes",true)
            .put("ownerGameData",false).put("nativeToolExecution",false).put("thorQualified",false).put("gameplayQualified",false));
    }
}
