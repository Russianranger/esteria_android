package io.github.russianranger.esteria.core.runtime.process;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** Fixed guest paths for a stopped, serialized shader setup operation.
 * The guest helper independently checks completed import ancestry and tool bytes.
 */
public final class ShaderRunPlan {
    public static final String TOOL_MOUNT="/esteria-shader-tools";
    public final Path game,tools,work;
    public final String importGeneration,clientRevision,locale;
    public final List<String> arguments;
    public final List<ProotLaunch.Mount> mounts;
    public ShaderRunPlan(Path game,Path tools,Path work,String clientRevision,String locale)throws IOException {
        this.game=directory(game);this.tools=directory(tools);this.work=directory(work);
        for(Path[] pair:new Path[][]{{game,tools},{game,work},{tools,work}})
            if(pair[0].startsWith(pair[1])||pair[1].startsWith(pair[0]))throw new IOException("Shader inputs, tools and work must be separate");
        if(clientRevision==null||!clientRevision.matches("[0-9a-f]{40}"))throw new IOException("Shader tools require a full source revision");
        if(!Arrays.asList("enUS","enGB","koKR","frFR","deDE","zhCN","zhTW","esES","esMX","ruRU").contains(locale))
            throw new IOException("Choose an explicit supported shader locale");
        this.clientRevision=clientRevision;this.locale=locale;importGeneration=current(game);
        directory(game.resolve("generations"));directory(game.resolve("generations").resolve(importGeneration));
        directory(game.resolve("generations").resolve(importGeneration).resolve("data"));
        arguments=Collections.unmodifiableList(Arrays.asList("/usr/bin/python3","-B","-s","-E",
            TOOL_MOUNT+"/helpers/shader_generation.py","--store","/work/shaders","--game","/esteria-data",
            "--generation",importGeneration,"--tools",TOOL_MOUNT+"/tools","--client-revision",clientRevision,"--locale",locale));
        mounts=Collections.unmodifiableList(Arrays.asList(new ProotLaunch.Mount(game,"/esteria-data"),
            new ProotLaunch.Mount(tools,TOOL_MOUNT)));
    }
    public void requireCurrentImport()throws IOException {
        if(!importGeneration.equals(current(game)))throw new IOException("Import changed during shader setup; prepared outputs are retained");
    }
    public static String current(Path game)throws IOException {
        directory(game);Path file=game.resolve("current");
        if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)!=65)
            throw new IOException("Complete current client import is required for shaders");
        byte[] raw=new byte[66];int count=0;
        try(var input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) {
            while(count<raw.length){int n=input.read(raw,count,raw.length-count);if(n<0)break;count+=n;}
        }
        String value=new String(raw,0,count,StandardCharsets.US_ASCII);
        if(!value.matches("[0-9a-f]{64}\\n"))throw new IOException("Invalid current import identity");
        return value.substring(0,64);
    }
    private static Path directory(Path path)throws IOException {
        if(path==null||!path.isAbsolute()||!path.normalize().equals(path)||!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||
            !path.toRealPath().equals(path))throw new IOException("Shader paths must be canonical owned directories");
        return path;
    }
}
