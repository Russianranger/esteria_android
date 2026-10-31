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
            Path game=Files.createDirectory(root.resolve("game data")),tools=Files.createDirectory(root.resolve("tools")),work=Files.createDirectory(root.resolve("work")),helpers=Files.createDirectory(root.resolve("helpers"));
            String generation="1".repeat(64),revision="2".repeat(40);
            Path imported=Files.createDirectories(game.resolve("generations/"+generation+"/data"));
            Path data=Files.createDirectory(imported.resolve("dAtA")),english=Files.createDirectory(data.resolve("ENus"));
            Files.write(data.resolve("common.MPQ"),new byte[]{0});Files.write(english.resolve("LOCALE-enUS.MPQ"),new byte[]{0});
            Files.writeString(game.resolve("current"),generation+"\n");
            ShaderRunPlan plan=new ShaderRunPlan(game,tools,work,helpers,revision,"enUS");
            if(!plan.arguments.equals(List.of("/usr/bin/python3","-B","-s","-E","/esteria-stock-client/stock_shader_generation.py",
                "--store","/work/shaders","--game","/esteria-data","--generation",generation,"--tools","/esteria-shader-tools/tools",
                "--client-revision",revision,"--locale","enUS","--content-profile","stock-3.3.5a")))throw new AssertionError("Pinned command changed");
            if(!plan.mounts.get(0).source.equals(game)||!plan.mounts.get(1).source.equals(tools)||!plan.mounts.get(2).source.equals(helpers))throw new AssertionError("Whole import ancestry and separate tools must be bound");
            if(!plan.requestedLocale.equals("enUS")||!plan.locale.equals("enUS"))throw new AssertionError("Requested and effective locale differ unexpectedly");
            ShaderRunPlan fallback=new ShaderRunPlan(game,tools,work,helpers,revision,"deDE");
            if(!fallback.requestedLocale.equals("deDE")||!fallback.locale.equals("enUS")||!fallback.arguments.get(fallback.arguments.indexOf("--locale")+1).equals("enUS"))
                throw new AssertionError("Unavailable requested locale must pass the actual client fallback to the pinned translator");
            fallback.requireCurrentImport();
            Path german=Files.createDirectory(data.resolve("deDE"));Files.createDirectory(german.resolve("locale-deDE.MPQ"));
            if(!new ShaderRunPlan(game,tools,work,helpers,revision,"deDE").locale.equals("enUS"))throw new AssertionError("A folder is not an available locale archive");
            Files.delete(german.resolve("locale-deDE.MPQ"));Files.write(german.resolve("locale-deDE.MPQ"),new byte[]{0});
            rejects(fallback::requireCurrentImport);
            if(!new ShaderRunPlan(game,tools,work,helpers,revision,"deDE").locale.equals("deDE"))throw new AssertionError("Available requested locale must win");
            Files.delete(german.resolve("locale-deDE.MPQ"));Files.delete(german);
            Path russian=Files.createDirectory(data.resolve("ruRU"));Files.write(russian.resolve("locale-ruRU.MPQ"),new byte[]{0});
            if(!new ShaderRunPlan(game,tools,work,helpers,revision,"ruRU").locale.equals("ruRU"))throw new AssertionError("Available Russian locale must retain its provider stack");
            Path china=Files.createDirectory(data.resolve("enCN"));Files.write(china.resolve("locale-enCN.MPQ"),new byte[]{0});
            rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enCN"));
            Files.delete(china.resolve("locale-enCN.MPQ"));Files.delete(china);
            Path aliasLocale=Files.createSymbolicLink(data.resolve("enus"),english);rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enUS"));Files.delete(aliasLocale);
            Files.move(english.resolve("LOCALE-enUS.MPQ"),root.resolve("locale-source"));Files.createSymbolicLink(english.resolve("LOCALE-enUS.MPQ"),root.resolve("locale-source"));
            rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enUS"));Files.delete(english.resolve("LOCALE-enUS.MPQ"));Files.move(root.resolve("locale-source"),english.resolve("LOCALE-enUS.MPQ"));
            Files.delete(russian.resolve("locale-ruRU.MPQ"));Files.delete(russian);
            Files.move(english.resolve("LOCALE-enUS.MPQ"),root.resolve("locale-source"));rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enUS"));Files.move(root.resolve("locale-source"),english.resolve("LOCALE-enUS.MPQ"));
            plan.requireCurrentImport();Files.writeString(game.resolve("current"),"3".repeat(64)+"\n");rejects(plan::requireCurrentImport);
            Files.writeString(game.resolve("current"),generation+"\n");
            rejects(()->new ShaderRunPlan(game,tools,work,helpers,"short","enUS"));rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"../enUS"));rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,null));
            rejects(()->new ShaderRunPlan(game,tools,game,helpers,revision,"enUS"));
            Path link=Files.createSymbolicLink(root.resolve("alias"),game);rejects(()->new ShaderRunPlan(link,tools,work,helpers,revision,"enUS"));
            Files.delete(game.resolve("current"));Files.createSymbolicLink(game.resolve("current"),root.resolve("elsewhere"));
            rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enUS"));Files.delete(game.resolve("current"));
            Files.writeString(game.resolve("current"),generation+"\nextra");rejects(()->new ShaderRunPlan(game,tools,work,helpers,revision,"enUS"));
        }finally {try(var paths=Files.walk(root)){for(Path p:(Iterable<Path>)paths.sorted(java.util.Comparator.reverseOrder())::iterator)Files.delete(p);}}
        System.out.println("PASS: requested/effective client locale fallback, packed command, unsupported/no-locale/case/link refusals and import/path guards; names-only synthetic fixtures, no guest execution claimed");
    }
}
