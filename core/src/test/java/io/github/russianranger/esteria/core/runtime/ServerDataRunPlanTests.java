package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.List;

/** Filesystem/command guards only; executes no Python, PRoot or extractor. */
public final class ServerDataRunPlanTests {
    interface Action{void run()throws Exception;}
    static void rejects(Action action)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError("Unsafe data plan accepted");}
    public static void main(String[] arguments)throws Exception {
        Path root=Files.createTempDirectory("esteria-data-plan-").toRealPath();
        try {
            Path game=Files.createDirectory(root.resolve("game data")),tools=Files.createDirectory(root.resolve("tools")),work=Files.createDirectory(root.resolve("work"));
            String generation="1".repeat(64),helpers="2".repeat(64);
            Files.createDirectories(game.resolve("generations/"+generation+"/data"));Files.writeString(game.resolve("current"),generation+"\n");
            Path helperRoot=Files.createDirectories(work.resolve("data-helpers/"+helpers));
            for(String name:List.of("server_data_generation.py","server_data_preflight.py","shader_generation.py","extractor_order.py","owned_process_group.py","world_io.py"))
                Files.writeString(helperRoot.resolve(name),"# unexecuted synthetic helper fixture\n");
            byte[] selection="{}\n".getBytes(java.nio.charset.StandardCharsets.UTF_8);Files.write(work.resolve("data-tools-selection.json"),selection);
            StringBuilder pin=new StringBuilder();for(byte value:MessageDigest.getInstance("SHA-256").digest(selection))pin.append(String.format("%02x",value&255));
            ServerDataRunPlan plan=new ServerDataRunPlan(game,tools,work,helpers,pin.toString(),"enUS",1);
            if(!plan.arguments.equals(List.of("/usr/bin/python3","-B","-s","-E","/work/data-helpers/"+helpers+"/server_data_generation.py",
                "--store","/work/server-data","--game","/esteria-data","--generation",generation,"--tools","/esteria-server-extractors",
                "--selection","/work/data-tools-selection.json","--locale","enUS","--threads","1","--content-profile","stock-3.3.5a","--android-low-memory")))throw new AssertionError("Fixed data command changed");
            if(!plan.mounts.get(0).source.equals(game)||!plan.mounts.get(1).source.equals(tools))throw new AssertionError("Complete import ancestry and separate selected tools required");
            plan.requireInputsUnchanged();Files.writeString(work.resolve("data-tools-selection.json"),"[]\n");rejects(plan::requireInputsUnchanged);
            Files.write(work.resolve("data-tools-selection.json"),selection);Files.writeString(game.resolve("current"),"3".repeat(64)+"\n");rejects(plan::requireInputsUnchanged);
            Files.writeString(game.resolve("current"),generation+"\n");
            Path namespace=Files.createDirectory(game.resolve("generations/"+generation+"/data/EsteriaServerData"));
            String manifest="format=1\nscope=esteria-user-supplied-server-data\nserverRevision=f35f04d01689f034778e3474b3c820092f51e461\nclientBuild=12340\nmode=overlay\nprovenance=user-supplied-format-checked\nclientProviderOrderSha256=none\n";
            Files.writeString(namespace.resolve("manifest.properties"),manifest);
            rejects(plan::requireInputsUnchanged);
            ServerDataRunPlan supplied=new ServerDataRunPlan(game,tools,work,helpers,pin.toString(),"enUS",1);
            if(supplied.serverDataPackage==null||!supplied.serverDataPackage.mode.equals("overlay")||
                    supplied.serverDataPackage.manifestBytes!=manifest.length())throw new AssertionError("Typed supplied package binding missing");
            supplied.requireInputsUnchanged();
            Files.writeString(namespace.resolve("manifest.properties"),manifest.replace("mode=overlay","mode=complete"));
            rejects(supplied::requireInputsUnchanged);
            Files.delete(namespace.resolve("manifest.properties"));Files.delete(namespace);
            rejects(()->new ServerDataRunPlan(game,tools,work,helpers,pin.toString(),"../enUS",1));
            rejects(()->new ServerDataRunPlan(game,tools,work,helpers,pin.toString(),"enUS",3));
            rejects(()->new ServerDataRunPlan(game,work,work,helpers,pin.toString(),"enUS",1));
            rejects(()->new ServerDataRunPlan(game,tools,work,"../helper",pin.toString(),"enUS",1));
            Path alias=Files.createSymbolicLink(root.resolve("alias"),game);rejects(()->new ServerDataRunPlan(alias,tools,work,helpers,pin.toString(),"enUS",1));
            Files.delete(helperRoot.resolve("extractor_order.py"));rejects(()->new ServerDataRunPlan(game,tools,work,helpers,pin.toString(),"enUS",1));
        }finally {try(var paths=Files.walk(root)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
        System.out.println("Data command/source-metadata/import-change/path guards passed; no extraction execution claimed");
    }
}
