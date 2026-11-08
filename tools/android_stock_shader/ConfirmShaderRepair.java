package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.system.Os;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Iterator;
import java.util.Map;
import java.util.TreeMap;
import org.json.JSONObject;

/** Operates on the fresh private qualification actor only, using the installed APK for admission and repair. */
final class ConfirmShaderRepair {
    private static final RuntimeWork.Progress QUIET = RuntimeWork.NONE;

    private static void require(boolean ok, String reason) {
        if (!ok) throw new IllegalStateException(reason);
    }

    private static String digest(Path path) throws Exception {
        require(Files.size(path) <= (16L << 20), "unbounded QA metadata");
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path));
        StringBuilder result = new StringBuilder(64);
        for (byte value : hash) result.append(String.format(java.util.Locale.ROOT,"%02x",value & 255));
        return result.toString();
    }

    private static String text(Path path) throws Exception {
        require(Files.size(path) <= (16L << 20), "unbounded QA text");
        return new String(Files.readAllBytes(path), StandardCharsets.UTF_8);
    }

    private static long inode(Path path) throws Exception {
        return Os.stat(path.toString()).st_ino;
    }

    private static Map<String,String> retained(Path root, Path store, String key, String importKey) throws Exception {
        Map<String,String> identities = new TreeMap<>();
        for (String name : new String[]{"game/current","game/generations/"+importKey+"/complete",
                "game/generations/"+importKey+"/journal.tsv","runtimes/wine-arm64/current",
                "runtimes/shader-tools-arm64/current"}) {
            Path path = root.resolve(name);
            identities.put(name, inode(path) + "/" + digest(path));
        }
        try (var entries = Files.newDirectoryStream(store.resolve("generations"))) {
            for (Path candidate : entries) {
                if (!candidate.getFileName().toString().equals(key)) {
                    identities.put(candidate.getFileName().toString(), inode(candidate) + "/" + digest(candidate.resolve("receipt.json")));
                }
            }
        }
        return identities;
    }

    private static ShaderSetup.Result named(Context context, Path root, RuntimeSetup wine, ShaderToolsSetup tools,
            String key, String action) throws Exception {
        LocalWorldSetup.Handle owner = LocalWorldSetup.beginShaderRepair(context,root,wine,tools,"enUS");
        ShaderSetup.Result result;
        try (LocalWorldSetup.Handle acquired = owner) {
            result = acquired.repairShaders(QUIET, RuntimeWork.NEVER_CANCELLED);
            Path log = acquired.diagnosticLogs().get("setup.shader.stdout.log");
            require(log != null && Arrays.asList(text(log).split("\n")).contains("Shader repair "+action+" generation="+key),
                    "guest repair did not select the expected action");
            require(result.generation.equals(key) && result.outputFiles == 4742, "repair output selection changed");
        }
        require(owner.state()==LocalWorldSetup.State.CLOSED,"named repair owner did not close");
        return result;
    }

    private static void admit(Context context, Path root, RuntimeSetup wine, ShaderToolsSetup tools,
            ShaderSetup.Result selected) throws Exception {
        try (GameSession.Leases ignored = GameSession.claim(root)) {
            ShaderSetup.requireCurrent(context,root,wine,tools,selected,QUIET,RuntimeWork.NEVER_CANCELLED);
        }
    }

    private static Map<String,String> runtimePins(Path receipt) throws Exception {
        JSONObject outputs = new JSONObject(text(receipt)).getJSONObject("outputs");
        Map<String,String> result = new TreeMap<>();
        for (Iterator<String> names=outputs.keys();names.hasNext();) {
            String name=names.next();
            // glslang writes a new absolute staging pathname in each diagnostic .spvasm.
            if (!name.endsWith(".spvasm")) result.put(name,outputs.getJSONObject(name).getString("sha256"));
        }
        require(result.size()==3162,"runtime output inventory differs");
        return result;
    }

    static void historical(Context context, Path root, String importKey, boolean old) throws Exception {
        require(root.toRealPath().equals(root) && root.endsWith("qa-signed-stock-shaders"), "isolated actor required");
        require(text(root.resolve("game/current")).equals(importKey+"\n"), "import changed");
        Path store = root.resolve("state/shader-work/shaders");
        require(!Files.exists(store.resolve("current")), "unpublished shader store required");
        RuntimeSetup wine = new RuntimeSetup(context, root);
        ShaderToolsSetup tools = new ShaderToolsSetup(context, root);
        tools.requireWineArchive(wine.archiveSha256());
        long started = System.nanoTime();
        JSONObject report = new JSONObject().put("importGeneration", importKey);
        if (old) {
            try (GameSession.Leases ignored = GameSession.claim(root)) {
                var wr = wine.prepare(QUIET, RuntimeWork.NEVER_CANCELLED);
                var sr = tools.prepare(QUIET, RuntimeWork.NEVER_CANCELLED);
                require(!wr.alreadyInstalled && !sr.alreadyInstalled,"previous APK must prepare original providers");
                ShaderSetup.Handle owner = ShaderSetup.begin(context, root, wine, tools, "enUS");
                try (ShaderSetup.Handle owned = owner) {
                    try {
                        owned.prepare(QUIET, RuntimeWork.NEVER_CANCELLED);
                        throw new IllegalStateException("Original v13 failure did not reproduce");
                    } catch (IOException expected) {
                        Path log = owned.diagnosticLogs().get("setup.shader.stderr.log");
                        require(log != null, "missing original translator log");
                        String failure = text(log);
                        require(failure.contains("worker=shader-translator; exitStatus=2") &&
                                failure.contains("strict setup refuses 10 undecodable or mismatched-stage record(s): Terrain1w:0, Terrain1w:1, Terrain1w:2, Terrain1w:3, Terrain1w:4, Terrain1w:5, Terrain1w_1:0, Terrain1w_2:0"),
                                "original error differs from physical support export");
                    }
                }
                require(!owner.processAlive() && owner.state()==ShaderSetup.State.CLOSED && !Files.exists(store.resolve("current")),
                        "failed generator published or leaked its owner");
                report.put("mode","legacy").put("failedLegacyPermutations",10).put("workerExit",2)
                        .put("noCurrentPointer",true).put("wineGeneration",wr.generation)
                        .put("toolGeneration",sr.generation);
            }
        } else {
            LocalWorldSetup.Handle owner = LocalWorldSetup.beginShaderRepair(context,root,wine,tools,"enUS");
            ShaderSetup.Result result;
            try (LocalWorldSetup.Handle owned = owner) {
                result = owned.repairShaders(QUIET, RuntimeWork.NEVER_CANCELLED);
                require(result.outputFiles == 4742 && result.importGeneration.equals(importKey), "different repair selection");
                Path log = owned.diagnosticLogs().get("setup.shader.stdout.log");
                require(log != null && Arrays.asList(text(log).split("\n")).contains("Shader repair published-replacement generation="+result.generation),
                        "named repair did not publish its completed replacement");
            }
            require(owner.state()==LocalWorldSetup.State.CLOSED,"repair owner still active");
            admit(context,root,wine,tools,result);
            String generation = result.generation;
            Path done=store.resolve("generations").resolve(generation);
            String generated=text(done.resolve("setup.log"));
            require(generated.contains("1578 selected: validated 1578") && generated.contains("2 generated, validated 2"),
                    "complete stock modules were not generated");
            report.put("mode","recovered").put("generation",generation).put("outputFiles",result.outputFiles)
                    .put("outputBytes",result.outputBytes).put("newValidatedModules",1580)
                    .put("verifiedRuntimeHashes",runtimePins(done.resolve("receipt.json")).size())
                    .put("receiptSha256",digest(done.resolve("receipt.json"))).put("namedRepairPublished",true)
                    .put("freshSessionAdmission",true);
        }
        report.put("elapsedMs",(System.nanoTime()-started)/1_000_000).put("closed",true);
        System.out.println("ANDROID_HISTORICAL_SHADER_RESULT "+report);
    }

    static void exercise(Context context, Path root, String expectedImport) throws Exception {
        long start = System.nanoTime();
        require(root.toRealPath().equals(root) && root.endsWith("qa-signed-stock-shaders"),"isolated current private actor required");
        RuntimeSetup wine = new RuntimeSetup(context,root);
        ShaderToolsSetup tools = new ShaderToolsSetup(context,root);
        Path store = root.resolve("state/shader-work/shaders");
        Path pointer = store.resolve("current");
        String key = text(pointer).trim();
        require(key.matches("[0-9a-f]{64}") && text(root.resolve("game/current")).equals(expectedImport+"\n"),"unbound input selection");
        Path generation = store.resolve("generations").resolve(key);
        Path receipt = generation.resolve("receipt.json");
        String beforeReceipt = digest(receipt);
        Map<String,String> original = runtimePins(receipt);
        Map<String,String> before = retained(root,store,key,expectedImport);
        long originalInode = inode(generation);
        require(!Files.exists(store.resolve("repair")),"fresh actor already contains repair work");

        Files.delete(pointer);
        ShaderSetup.Result pointerResult = named(context,root,wine,tools,key,"verified-existing");
        require(text(pointer).equals(key+"\n") && inode(generation)==originalInode
                && digest(receipt).equals(beforeReceipt) && !Files.exists(store.resolve("repair")),"pointer repair repeated payload work");
        long pointerMs = (System.nanoTime()-start)/1_000_000;
        long pointerInode=inode(pointer);
        long damageStarted = System.nanoTime();
        String name = original.keySet().stream().filter(n -> n.startsWith("pixel/") && n.endsWith(".spv")).findFirst().get();
        Path sample = pointerResult.shaders.resolve(name);
        long oldSize = Files.size(sample), oldInode=inode(sample);
        require(oldSize > 24 && digest(sample).equals(original.get(name)), "original module bound receipt required");
        FileTime oldTime = Files.getLastModifiedTime(sample);
        try (FileChannel stream = FileChannel.open(sample,StandardOpenOption.READ,StandardOpenOption.WRITE)) {
            ByteBuffer byteAt=ByteBuffer.allocate(1);
            require(stream.read(byteAt,20)==1,"cannot read fixture bit");
            byteAt.array()[0]^=1;
            byteAt.rewind();
            require(stream.write(byteAt,20)==1,"cannot inject fixture bit");
            stream.force(true);
        }
        Files.setLastModifiedTime(sample,oldTime);
        FileTime newTime=Files.getLastModifiedTime(sample);
        require(oldSize==Files.size(sample) && oldInode==inode(sample) && oldTime.toMillis()==newTime.toMillis(),
                "fixture size, inode or Java mtime changed");
        require(!digest(sample).equals(original.get(name)),"bit flip had no effect");
        try {
            admit(context,root,wine,tools,pointerResult);
            throw new IllegalStateException("damaged module incorrectly admitted");
        } catch (IOException expected) {
            require(expected.getMessage().startsWith("Prepared shader output bytes changed: "+name),
                    "full admission failed for another reason");
        }
        ShaderSetup.Result rebuilt = named(context,root,wine,tools,key,"published-replacement");
        admit(context,root,wine,tools,rebuilt);
        require(inode(generation)!=originalInode && inode(pointer)==pointerInode && digest(sample).equals(original.get(name))
                && runtimePins(receipt).equals(original),"rebuilt runtime bytes differ");
        ArrayList<Path> backups = new ArrayList<>();
        try (var entries=Files.newDirectoryStream(store.resolve("repair"),"replaced-"+key+"-*")) {
            for (Path entry : entries) backups.add(entry);
        }
        require(backups.size()==1 && inode(backups.get(0))==originalInode && inode(backups.get(0).resolve("shaders").resolve(name))==oldInode,
                "rejected original was not retained");
        String compiler = text(generation.resolve("setup.log"));
        require(compiler.contains("1578 selected: validated 1578") && compiler.contains("2 generated, validated 2"),
                "new native translator did not validate all modules");
        long rebuildMs = (System.nanoTime()-damageStarted)/1_000_000;
        String afterReceipt = digest(receipt);
        long rebuiltInode = inode(generation);
        long warmStart = System.nanoTime();
        ShaderSetup.Result same = named(context,root,wine,tools,key,"verified-existing");
        require(inode(generation)==rebuiltInode && afterReceipt.equals(digest(receipt)) && inode(pointer)==pointerInode
                && retained(root,store,key,expectedImport).equals(before),"warm repair touched the selected or unrelated work");
        JSONObject report = new JSONObject().put("generation",key).put("importGeneration",expectedImport)
                .put("initialReceipt",beforeReceipt).put("repairedReceipt",afterReceipt)
                .put("pointerRestored",true).put("pointerRecompiled",false).put("damagedRejectedByFullAdmission",true)
                .put("sameSizeAndInodeAtInjection",true).put("javaMillisecondMtimePreserved",true)
                .put("javaExactMtimePreserved",oldTime.equals(newTime)).put("nativeRebuiltModulesValidated",1580)
                .put("runtimeFileDigestsPreserved",original.size()).put("files",same.outputFiles)
                .put("fullSessionReceiptAdmitted",true).put("previousRejectedGenerationRetained",true)
                .put("sourceAndProviderPointersUnchanged",true).put("warmRecompiled",false).put("ownersClosed",true)
                .put("pointerMs",pointerMs).put("rebuildAndAdmissionMs",rebuildMs)
                .put("warmMs",(System.nanoTime()-warmStart)/1_000_000);
        System.out.println("ANDROID_SHADER_REPAIR_RESULT "+report);
    }
}
