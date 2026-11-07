package io.github.russianranger.esteria.core.runtime.process;

import io.github.russianranger.esteria.core.importer.ContentPackageLayout;
import io.github.russianranger.esteria.core.content.ContentProfile;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.Locale;

/** Fixed command for a stopped, serialized data operation. The caller supplies
 * installed APK helpers and a verified, composed source-matched tool provider.
 * The Python helper rechecks actual files, source identities and capabilities.
 */
public final class ServerDataRunPlan {
    // The installed bytes select the guest executable; this single reviewed, output-compatible
    // reader preserves the immutable v10–v15 generation, including interrupted phase staging.
    private static final String REVIEWED_READER = "06ede7399445e1aace7566a0c584d6fba2c005703393afd2f7ba0fd9e5c4fe29";
    private static final String OUTPUT_RECIPE = "c911baddd7c49fa21fa4a3bc022d75c69fa66daddde3a6970129cf652dad18ff";
    public final Path game,tools,work;
    public final String importGeneration,helperGeneration,recipeGeneration,toolSelectionSha256,locale;
    public final int threads;
    public final ContentPackageLayout.ServerManifest serverDataPackage;
    public final List<String> arguments;
    public final List<ProotLaunch.Mount> mounts;
    public ServerDataRunPlan(Path game,Path tools,Path work,String helperGeneration,String toolSelectionSha256,
            String locale,int threads)throws IOException {
        this.game=directory(game);this.tools=directory(tools);this.work=directory(work);
        for(Path[] pair:new Path[][]{{game,tools},{game,work},{tools,work}})
            if(pair[0].startsWith(pair[1])||pair[1].startsWith(pair[0]))throw new IOException("Data inputs, tools and work must be separate");
        if(helperGeneration==null||!helperGeneration.matches("[0-9a-f]{64}")||toolSelectionSha256==null||
                !toolSelectionSha256.matches("[0-9a-f]{64}"))throw new IOException("Pinned helper and tool selection identities required");
        if(!Arrays.asList("deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU").contains(locale))
            throw new IOException("Choose an explicit supported data locale");
        if(threads<1||threads>2)throw new IOException("One or two data extraction workers required");
        this.helperGeneration=helperGeneration;
        recipeGeneration=REVIEWED_READER.equals(helperGeneration)?OUTPUT_RECIPE:helperGeneration;
        this.toolSelectionSha256=toolSelectionSha256;this.locale=locale;this.threads=threads;
        importGeneration=ShaderRunPlan.current(game);
        directory(game.resolve("generations"));directory(game.resolve("generations").resolve(importGeneration));
        directory(game.resolve("generations").resolve(importGeneration).resolve("data"));
        serverDataPackage=ContentPackageLayout.inspectServerManifest(game.resolve("generations").resolve(importGeneration).resolve("data"));
        Path helpers=directory(directory(work.resolve("data-helpers")).resolve(helperGeneration));
        for(String name:Arrays.asList("server_data_generation.py","server_data_preflight.py","shader_generation.py",
                "extractor_order.py","owned_process_group.py","world_io.py")) {
            Path file=helpers.resolve(name);
            if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)<=0||Files.size(file)>131072)
                throw new IOException("Complete installed data helper closure required");
        }
        if(REVIEWED_READER.equals(helperGeneration)) {
            Path reader=helpers.resolve("server-data-reader.sha256");
            if(!Files.isRegularFile(reader,LinkOption.NOFOLLOW_LINKS)||Files.size(reader)!=65)
                throw new IOException("Reviewed data reader identity required");
        }
        requireSelection();
        arguments=Collections.unmodifiableList(Arrays.asList("/usr/bin/python3","-B","-s","-E",
            "/work/data-helpers/"+helperGeneration+"/server_data_generation.py","--store","/work/server-data",
            "--game","/esteria-data","--generation",importGeneration,"--tools","/esteria-server-extractors",
            "--selection","/work/data-tools-selection.json","--locale",locale,"--threads",Integer.toString(threads),
            "--content-profile",ContentProfile.ID,"--android-low-memory",
            "--installed-data-reader",helperGeneration,"--data-recipe",recipeGeneration));
        mounts=Collections.unmodifiableList(Arrays.asList(new ProotLaunch.Mount(game,"/esteria-data"),
            new ProotLaunch.Mount(tools,"/esteria-server-extractors")));
    }
    public void requireInputsUnchanged()throws IOException {
        if(!importGeneration.equals(ShaderRunPlan.current(game)))throw new IOException("Import changed during data preparation; outputs retained");
        if(!java.util.Objects.equals(serverDataPackage,ContentPackageLayout.inspectServerManifest(
                game.resolve("generations").resolve(importGeneration).resolve("data"))))
            throw new IOException("Matched server package selection changed during preparation");
        directory(tools);requireSelection();
    }
    private void requireSelection()throws IOException {
        Path path=work.resolve("data-tools-selection.json");
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.size(path)<=0||Files.size(path)>65536)
            throw new IOException("Bounded private data tool selection required");
        byte[] bytes;
        try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);var output=new java.io.ByteArrayOutputStream()) {
            byte[] block=new byte[4096];
            for(int count;(count=input.read(block))!=-1;) {
                if(output.size()+count>65536)throw new IOException("Data tool selection grew beyond bound");
                output.write(block,0,count);
            }
            bytes=output.toByteArray();
        }
        try {
            StringBuilder hash=new StringBuilder(64);
            for(byte value:MessageDigest.getInstance("SHA-256").digest(bytes))hash.append(String.format(Locale.ROOT,"%02x",value&255));
            if(!toolSelectionSha256.equals(hash.toString()))throw new IOException("Data tool selection identity changed");
        }catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
    private static Path directory(Path path)throws IOException {
        if(path==null||!path.isAbsolute()||!path.normalize().equals(path)||!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||
                !path.toRealPath().equals(path))throw new IOException("Data paths must be canonical owned directories");
        return path;
    }
}
