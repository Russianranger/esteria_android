package io.github.russianranger.esteria.core.runtime.process;

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
    public final Path game,tools,work;
    public final String importGeneration,helperGeneration,toolSelectionSha256,locale;
    public final int threads;
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
        this.helperGeneration=helperGeneration;this.toolSelectionSha256=toolSelectionSha256;this.locale=locale;this.threads=threads;
        importGeneration=ShaderRunPlan.current(game);
        directory(game.resolve("generations"));directory(game.resolve("generations").resolve(importGeneration));
        directory(game.resolve("generations").resolve(importGeneration).resolve("data"));
        Path helpers=directory(directory(work.resolve("data-helpers")).resolve(helperGeneration));
        for(String name:Arrays.asList("server_data_generation.py","server_data_preflight.py","shader_generation.py",
                "extractor_order.py","owned_process_group.py")) {
            Path file=helpers.resolve(name);
            if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)<=0||Files.size(file)>131072)
                throw new IOException("Complete installed data helper closure required");
        }
        requireSelection();
        arguments=Collections.unmodifiableList(Arrays.asList("/usr/bin/python3","-B","-s","-E",
            "/work/data-helpers/"+helperGeneration+"/server_data_generation.py","--store","/work/server-data",
            "--game","/esteria-data","--generation",importGeneration,"--tools","/esteria-server-extractors",
            "--selection","/work/data-tools-selection.json","--locale",locale,"--threads",Integer.toString(threads)));
        mounts=Collections.unmodifiableList(Arrays.asList(new ProotLaunch.Mount(game,"/esteria-data"),
            new ProotLaunch.Mount(tools,"/esteria-server-extractors")));
    }
    public void requireInputsUnchanged()throws IOException {
        if(!importGeneration.equals(ShaderRunPlan.current(game)))throw new IOException("Import changed during data preparation; outputs retained");
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
