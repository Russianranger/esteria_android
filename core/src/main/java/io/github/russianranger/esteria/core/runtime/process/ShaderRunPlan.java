package io.github.russianranger.esteria.core.runtime.process;

import io.github.russianranger.esteria.core.content.ContentProfile;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.nio.file.DirectoryStream;

/** Fixed guest paths for a stopped, serialized shader setup operation.
 * The guest helper independently checks completed import ancestry and tool bytes.
 */
public final class ShaderRunPlan {
    public static final String TOOL_MOUNT="/esteria-shader-tools";
    public static final String HELPER_MOUNT="/esteria-stock-client";
    // Client471 Client.cpp::g_localeNames/CheckAvailableLocales order. The
    // pinned translator supports ten locales; enCN/enTW cannot be invented.
    private static final List<String> CLIENT_LOCALES=List.of("deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU");
    private static final List<String> SHADER_LOCALES=List.of("enUS","enGB","koKR","frFR","deDE","zhCN","zhTW","esES","esMX","ruRU");
    public final Path game,tools,work,helpers;
    public final String importGeneration,clientRevision,requestedLocale,locale;
    public final List<String> arguments;
    public final List<ProotLaunch.Mount> mounts;
    public ShaderRunPlan(Path game,Path tools,Path work,Path helpers,String clientRevision,String locale)throws IOException {
        this.game=directory(game);this.tools=directory(tools);this.work=directory(work);this.helpers=directory(helpers);
        for(Path[] pair:new Path[][]{{game,tools},{game,work},{tools,work},{game,helpers},{tools,helpers},{work,helpers}})
            if(pair[0].startsWith(pair[1])||pair[1].startsWith(pair[0]))throw new IOException("Shader inputs, tools and work must be separate");
        if(clientRevision==null||!clientRevision.matches("[0-9a-f]{40}"))throw new IOException("Shader tools require a full source revision");
        if(locale==null||!CLIENT_LOCALES.contains(locale))throw new IOException("Choose an explicit supported client locale");
        this.clientRevision=clientRevision;this.requestedLocale=locale;importGeneration=current(game);
        directory(game.resolve("generations"));directory(game.resolve("generations").resolve(importGeneration));
        Path imported=directory(game.resolve("generations").resolve(importGeneration).resolve("data"));
        this.locale=effectiveLocale(imported,requestedLocale);
        arguments=Collections.unmodifiableList(Arrays.asList("/usr/bin/python3","-B","-s","-E",
            HELPER_MOUNT+"/stock_shader_generation.py","--store","/work/shaders","--game","/esteria-data",
            "--generation",importGeneration,"--tools",TOOL_MOUNT+"/tools","--client-revision",clientRevision,"--locale",this.locale,
            "--content-profile",ContentProfile.ID,"--android-low-memory"));
        mounts=Collections.unmodifiableList(Arrays.asList(new ProotLaunch.Mount(game,"/esteria-data"),
            new ProotLaunch.Mount(tools,TOOL_MOUNT),new ProotLaunch.Mount(helpers,HELPER_MOUNT)));
    }
    public void requireCurrentImport()throws IOException {
        if(!importGeneration.equals(current(game)))throw new IOException("Import changed during shader setup; prepared outputs are retained");
        Path imported=directory(game.resolve("generations").resolve(importGeneration).resolve("data"));
        if(!locale.equals(effectiveLocale(imported,requestedLocale)))
            throw new IOException("Effective client locale changed during shader setup; prepared outputs are retained");
    }
    private static String effectiveLocale(Path imported,String requested)throws IOException {
        Path data=child(imported,"Data");
        if(data==null)throw new IOException("Classical client Data directory is required for shader setup");
        directory(data);Path common=child(data,"common.MPQ");
        if(common==null||!ordinaryFile(common))throw new IOException("Classical client common.MPQ is required for shader setup");
        int start=CLIENT_LOCALES.indexOf(requested);
        for(int offset=0;offset<CLIENT_LOCALES.size();offset++) {
            String candidate=CLIENT_LOCALES.get((start+offset)%CLIENT_LOCALES.size());
            Path localized=child(data,candidate);if(localized==null)continue;
            if(Files.isSymbolicLink(localized))throw new IOException("Linked client locale directory is unsupported");
            if(!Files.isDirectory(localized,LinkOption.NOFOLLOW_LINKS))continue;
            directory(localized);Path archive=child(localized,"locale-"+candidate+".MPQ");
            if(archive==null)continue;
            if(Files.isSymbolicLink(archive))throw new IOException("Linked client locale archive is unsupported");
            if(!ordinaryFile(archive))continue;
            if(!SHADER_LOCALES.contains(candidate))
                throw new IOException("Effective client locale "+candidate+" is unsupported by the pinned shader translator");
            return candidate;
        }
        throw new IOException("No available classical client locale archive was found; shader setup cannot use root-only providers");
    }
    /** Name-only bounded lookup follows the client reader's Windows casing;
     * imported MPQ bytes remain unopened and under the caller's import lease. */
    private static Path child(Path parent,String name)throws IOException {
        Path selected=null;int count=0;
        try(DirectoryStream<Path> children=Files.newDirectoryStream(parent)) {
            for(Path path:children) {
                if(++count>200_000)throw new IOException("Client provider directory exceeds its entry bound");
                if(path.getFileName().toString().equalsIgnoreCase(name)) {
                    if(selected!=null)throw new IOException("Case-colliding client locale/provider path");
                    selected=path;
                }
            }
        }
        return selected;
    }
    private static boolean ordinaryFile(Path file)throws IOException {
        return Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)&&file.equals(file.toRealPath());
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
