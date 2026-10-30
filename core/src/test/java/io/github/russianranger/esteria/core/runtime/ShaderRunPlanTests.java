package io.github.russianranger.esteria.core.runtime;
import io.github.russianranger.esteria.core.runtime.process.ShaderRunPlan;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

public final class ShaderRunPlanTests {
    interface Action {void run()throws Exception;}
    static void rejects(Action action)throws Exception {try{action.run();}catch(IOException expected){return;}throw new AssertionError("Invalid shader request accepted");}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("esteria-shader-plan-").toRealPath();
        try {
            Path game=Files.createDirectory(root.resolve("game data")),tools=Files.createDirectory(root.resolve("tools")),work=Files.createDirectory(root.resolve("work"));
            String generation="1".repeat(64),revision="2".repeat(40);
            Files.createDirectories(game.resolve("generations/"+generation+"/data"));Files.writeString(game.resolve("current"),generation+"\n");
            ShaderRunPlan plan=new ShaderRunPlan(game,tools,work,revision,"enUS");
            if(!plan.arguments.equals(List.of("/usr/bin/python3","-B","-s","-E","/esteria-shader-tools/helpers/shader_generation.py",
                "--store","/work/shaders","--game","/esteria-data","--generation",generation,"--tools","/esteria-shader-tools/tools",
                "--client-revision",revision,"--locale","enUS")))throw new AssertionError("Pinned command changed");
            if(!plan.mounts.get(0).source.equals(game)||!plan.mounts.get(1).source.equals(tools))throw new AssertionError("Whole import ancestry and separate tools must be bound");
            plan.requireCurrentImport();Files.writeString(game.resolve("current"),"3".repeat(64)+"\n");rejects(plan::requireCurrentImport);
            Files.writeString(game.resolve("current"),generation+"\n");
            rejects(()->new ShaderRunPlan(game,tools,work,"short","enUS"));rejects(()->new ShaderRunPlan(game,tools,work,revision,"../enUS"));
            rejects(()->new ShaderRunPlan(game,tools,game,revision,"enUS"));
            Path link=Files.createSymbolicLink(root.resolve("alias"),game);rejects(()->new ShaderRunPlan(link,tools,work,revision,"enUS"));
            Files.delete(game.resolve("current"));Files.createSymbolicLink(game.resolve("current"),root.resolve("elsewhere"));
            rejects(()->new ShaderRunPlan(game,tools,work,revision,"enUS"));Files.delete(game.resolve("current"));
            Files.writeString(game.resolve("current"),generation+"\nextra");rejects(()->new ShaderRunPlan(game,tools,work,revision,"enUS"));
        }finally {try(var paths=Files.walk(root)){for(Path p:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator)Files.delete(p);}}
        System.out.println("PASS: shader command, import change and disjoint path guards; no guest execution claimed");
    }
}
