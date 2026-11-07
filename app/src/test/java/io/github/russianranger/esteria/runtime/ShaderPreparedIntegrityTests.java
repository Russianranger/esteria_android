package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import org.json.JSONObject;

/** Production Android shader consumer with unchanged Android13 JSON sources.
 * Python-generated receipts and synthetic compiler outputs, never GPU evidence. */
public final class ShaderPreparedIntegrityTests {
    private interface Action {void run()throws Exception;}
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private static void refuses(Action action)throws Exception {
        try{action.run();throw new AssertionError("Corrupt completed shaders were admitted");}catch(IOException expected){ }
    }
    public static void main(String[] arguments)throws Exception {
        Path assets=Path.of(arguments[0]),sources=Path.of(arguments[1]);
        Path root=Files.createTempDirectory("esteria-shader-integrity-").toRealPath();
        try {
            Path fixture=assets.resolve("shader");
            try(var paths=Files.walk(fixture)) {
                for(Path source:(Iterable<Path>)paths::iterator) {
                    Path target=root.resolve(fixture.relativize(source));
                    if(Files.isDirectory(source))Files.createDirectories(target);
                    else Files.copy(source,target);
                }
            }
            Path tools=Files.createDirectory(root.resolve("tools")),helpers=Files.createDirectory(root.resolve("helpers"));
            for(String name:new String[]{"stock_content_inspection.py","stock_shader_generation.py","stock_shader_translate.py",
                    "shader_generation.py","extractor_order.py","server_data_preflight.py","world_io.py"})
                Files.copy(sources.resolve(name),helpers.resolve(name));
            JSONObject info=new JSONObject(Files.readString(assets.resolve("fixture.json"))).getJSONObject("shader");
            ShaderRunPlan plan=new ShaderRunPlan(root.resolve("game"),tools,root.resolve("work"),helpers,info.getString("clientRevision"),"enUS");
            String manifest=info.getString("toolManifestSha256");
            ShaderSetup.Result selected=ShaderSetup.validatePrepared(plan,manifest,null,false);
            check(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null)==null,"Current recipe uses its normal audit");
            String previous=info.getString("previousGeneration");
            Path current=plan.work.resolve("shaders/current");
            Files.writeString(current,previous+"\n");
            ShaderSetup.Result legacy=ShaderSetup.validatePrepared(plan,manifest,null,false);
            check(legacy.generation.equals(previous),"Normal Start selects the original v12 key");
            check(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null).generation.equals(previous),"Full audit reuses the old output");
            check(ShaderSetup.verifyCompatibleCompleted(plan,"0".repeat(64),null,null)==null,"Different provider cannot reuse v12 output");
            byte[] before=Files.readAllBytes(legacy.shaders.resolveSibling("receipt.json"));
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{
                if(path.startsWith(legacy.shaders))throw new RuntimeWork.CancelledException();
            })){
                try{ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null);throw new AssertionError("Cancelled audit returned a selection");}
                catch(RuntimeWork.CancelledException expected){ }
            }
            check(Files.readString(current).equals(previous+"\n"),"Interrupted audit must preserve current");
            check(java.util.Arrays.equals(before,Files.readAllBytes(legacy.shaders.resolveSibling("receipt.json"))),"Interrupted audit must preserve the original receipt");
            check(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null).generation.equals(previous),"Interrupted v12 verification can reenter");
            Path donor=legacy.shaders.resolve("manifest.txt");byte[] good=Files.readAllBytes(donor),bad=good.clone();bad[0]^=1;
            Files.write(donor,bad);
            check(ShaderSetup.verifyCompatibleCompleted(plan,manifest,null,null)==null,"Corrupt v12 payload must not bypass translation");
            Files.write(donor,good);
            Files.writeString(current,selected.generation+"\n");
            Path output=selected.shaders.resolve("manifest.txt");byte[] original=Files.readAllBytes(output);
            var timestamp=Files.getLastModifiedTime(output);
            for(int launch=0;launch<3;launch++) {
                AtomicLong bytes=new AtomicLong();
                try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{if(path.startsWith(selected.shaders))bytes.addAndGet(count);})) {
                    ShaderSetup.validatePrepared(plan,manifest,null,false,true,()->false);
                }
                check(bytes.get()==selected.outputBytes,"Each new session verifies each selected shader payload byte once");
            }
            byte[] changed=original.clone();changed[0]^=1;Files.write(output,changed);Files.setLastModifiedTime(output,timestamp);
            ShaderSetup.validatePrepared(plan,manifest,null,false);
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false,true));
            Files.write(output,original);Files.setLastModifiedTime(output,timestamp);
            Path extra=selected.shaders.resolve("unexpected.spv");Files.writeString(extra,"EXTRA");
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false,true));Files.delete(extra);
            Path extraDirectory=Files.createDirectory(selected.shaders.resolve("unexpected"));
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false,true));Files.delete(extraDirectory);
            Path moved=root.resolve("retained-manifest");Files.move(output,moved);
            refuses(()->ShaderSetup.validatePrepared(plan,manifest,null,false,true));Files.move(moved,output);
            AtomicBoolean stop=new AtomicBoolean();AtomicLong reads=new AtomicLong();
            try(RuntimeReadPolicy.Scope scope=RuntimeReadPolicy.install((path,offset,count)->{
                if(path.startsWith(selected.shaders)){reads.addAndGet(count);stop.set(true);}
            })) {
                try{ShaderSetup.validatePrepared(plan,manifest,null,false,true,stop::get);throw new AssertionError("Cancellation must stop verification at a chunk boundary");}
                catch(RuntimeWork.CancelledException expected){check(reads.get()>0,"Cancellation was triggered during actual payload verification");}
            }
            ShaderSetup.validatePrepared(plan,manifest,null,false,true);
            check(java.util.Arrays.equals(original,Files.readAllBytes(output)),"All validation failures preserve original output after fixture restoration");
            check(Files.getLastModifiedTime(output).equals(timestamp),"Validation never rewrites prepared output");
            System.out.println("Shader prepared integrity passed: three fresh byte-verification admissions, same-size/mtime-preserved mutation, addition, deletion and in-flight cancellation; production Java consumer/Python fixture, no Android or GPU execution");
        } finally {
            try(var paths=Files.walk(root)){for(Path path:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(path);}
        }
    }
}
