package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.Collections;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Bounded metadata for fixed owned log roles. Never reads log contents,
 * credentials, configuration or arbitrary caller-selected filesystem paths.
 * Revalidate immediately before export; metadata is not a future-open lease. */
public final class SupportLogSelection {
    public static final int MAX_NAMES=32,MAX_ENCODED_BYTES=64*1024,MAX_RELATIVE_PATH=1024;
    private static final String HEADER="Esteria owned support logs v1";
    private static final String PREFERENCE_HEADER="Esteria owned support logs b64 v2:";
    private static final String OP="[a-f0-9]{32}",SLOT="[a-f0-9]{16}";
    private static final Set<String> PRIVATE_COMPONENTS=Set.of("accounts","config","wtf","client-state","home","prefix",
        "game","runtimes","engine-private.log","handoffs","xauthority","local-player.json","database-secret","esteria-local-login.bin");
    private static final Pattern DATABASE=Pattern.compile("game\\.database\\.(stdout|stderr)\\.log");
    private static final Pattern SERVER_HELPER=Pattern.compile("game\\.server\\.helper\\.(stdout|stderr)\\.log");
    private static final Pattern SERVER=Pattern.compile("game\\.server\\.(authserver|worldserver)\\.log");
    private static final Pattern PRESENTATION=Pattern.compile("game\\.presentation\\.(xserver|frame|input|client)\\.(stdout|stderr)\\.log");
    private static final Pattern SETUP=Pattern.compile("setup\\.(data|shader|stock|installation|turnip)\\.(stdout|stderr)\\.log");
    private SupportLogSelection(){ }
    /** Single-line transport avoids Android XML indentation on newline-terminated strings. */
    public static String encodePreference(Path canonicalAppRoot,Map<String,Path> fixedOwnedLogPaths)throws IOException {
        String value=PREFERENCE_HEADER+java.util.Base64.getEncoder().encodeToString(encode(canonicalAppRoot,fixedOwnedLogPaths).getBytes(java.nio.charset.StandardCharsets.US_ASCII));
        if(value.length()>MAX_ENCODED_BYTES)throw new IOException("Owned diagnostic selection exceeds its preference bound");
        return value;
    }
    public static Recovery recoverPreference(Path canonicalAppRoot,String stored)throws IOException {
        root(canonicalAppRoot);
        if(stored==null||stored.length()>MAX_ENCODED_BYTES)return new Recovery(Map.of(),1,"preference-bound");
        if(stored.startsWith(PREFERENCE_HEADER)){
            String payload=stored.substring(PREFERENCE_HEADER.length());
            try{
                byte[] decoded=java.util.Base64.getDecoder().decode(payload);
                if(decoded.length>MAX_ENCODED_BYTES||!java.util.Base64.getEncoder().encodeToString(decoded).equals(payload))return new Recovery(Map.of(),1,"preference-encoding");
                for(byte value:decoded)if(value<0)return new Recovery(Map.of(),1,"preference-encoding");
                return recover(canonicalAppRoot,new String(decoded,java.nio.charset.StandardCharsets.US_ASCII));
            }catch(IllegalArgumentException malformed){return new Recovery(Map.of(),1,"preference-encoding");}
        }
        // Remove only outer ASCII spaces after the final legacy record newline.
        // Roles, records and paths retain their exact strict validation.
        int end=stored.length();while(end>0&&stored.charAt(end-1)==' ')end--;
        if(end<stored.length()&&end>0&&stored.charAt(end-1)=='\n')stored=stored.substring(0,end);
        return recover(canonicalAppRoot,stored);
    }
    /** Recovery never widens the allowlist. Each surviving role passes the exact strict validator. */
    public static final class Recovery {
        public final Map<String,Path> logs;
        public final int rejected;
        public final String reason;
        private Recovery(Map<String,Path> logs,int rejected,String reason){this.logs=Collections.unmodifiableMap(new TreeMap<>(logs));this.rejected=rejected;this.reason=reason;}
    }
    public static Recovery recover(Path canonicalAppRoot,String encoded)throws IOException {
        root(canonicalAppRoot);
        if(encoded==null||encoded.length()>MAX_ENCODED_BYTES)return new Recovery(Map.of(),1,"selection-bound");
        if(encoded.isEmpty())return new Recovery(Map.of(),0,"");
        String[] lines=encoded.split("\n",-1);
        if(lines.length<2||lines.length>MAX_NAMES+2||!HEADER.equals(lines[0])||!lines[lines.length-1].isEmpty())
            return new Recovery(Map.of(),1,"selection-format");
        TreeMap<String,Path> result=new TreeMap<>();Set<String> seen=new java.util.HashSet<>();int rejected=0;String reason="";
        for(int index=1;index<lines.length-1;index++){
            String line=lines[index];int tab=line.indexOf('\t');String name=tab>0?line.substring(0,tab):"";
            try{
                if(tab<=0||tab!=line.lastIndexOf('\t'))throw new IOException("record-format");
                for(int i=0;i<line.length();i++)if(line.charAt(i)>127||(line.charAt(i)<32&&line.charAt(i)!='\t'))throw new IOException("record-encoding");
                Path path=validate(canonicalAppRoot,name,line.substring(tab+1));
                if(!seen.add(name)){result.remove(name);throw new IOException("duplicate-role");}
                result.put(name,path);
            }catch(IOException|RuntimeException invalid){rejected++;if(reason.isEmpty())reason=reason(invalid);}
        }
        return new Recovery(result,rejected,reason);
    }
    public static Recovery recover(Path canonicalAppRoot,Map<String,Path> fixedOwnedLogPaths)throws IOException {
        root(canonicalAppRoot);
        if(fixedOwnedLogPaths==null||fixedOwnedLogPaths.size()>MAX_NAMES)return new Recovery(Map.of(),1,"selection-bound");
        TreeMap<String,Path> result=new TreeMap<>();int rejected=0;String reason="";
        for(Map.Entry<String,Path> entry:fixedOwnedLogPaths.entrySet())try{
            encode(canonicalAppRoot,Map.of(entry.getKey(),entry.getValue()));result.put(entry.getKey(),entry.getValue());
        }catch(IOException|RuntimeException invalid){rejected++;if(reason.isEmpty())reason=reason(invalid);}
        return new Recovery(result,rejected,reason);
    }
    private static String reason(Throwable failure){
        // Only the validator's fixed error vocabulary is exposed, never a provider/path exception message.
        String text=failure.getMessage();
        if(text!=null&&Set.of("record-format","record-encoding","duplicate-role","Invalid owned diagnostic path or role",
                "Private diagnostic paths are excluded","Unsupported owned diagnostic role or path",
                "Owned diagnostic path contains a link or unexpected file type","Owned diagnostic path must be canonical and app-relative").contains(text))return text;
        return "validation-"+failure.getClass().getSimpleName();
    }

    /** Stable ASCII metadata only. Missing logs are retained for later startup
     * or rotation. The map and its paths are never expanded into a directory scan. */
    public static String encode(Path canonicalAppRoot,Map<String,Path> fixedOwnedLogPaths)throws IOException {
        root(canonicalAppRoot);
        if(fixedOwnedLogPaths==null||fixedOwnedLogPaths.size()>MAX_NAMES)throw new IOException("Too many owned diagnostic logs");
        TreeMap<String,Path> sorted=new TreeMap<>();
        for(Map.Entry<String,Path> entry:fixedOwnedLogPaths.entrySet()) {
            String name=entry.getKey();Path path=entry.getValue();
            if(name==null||path==null||!path.isAbsolute()||!path.normalize().equals(path)||!path.startsWith(canonicalAppRoot)||path.equals(canonicalAppRoot))
                throw new IOException("Owned diagnostic path must be canonical and app-relative");
            String relative=canonicalAppRoot.relativize(path).toString();
            validate(canonicalAppRoot,name,relative);
            if(sorted.put(name,path)!=null)throw new IOException("Duplicate owned diagnostic log role");
        }
        StringBuilder result=new StringBuilder(HEADER).append('\n');
        for(Map.Entry<String,Path> entry:sorted.entrySet()) {
            result.append(entry.getKey()).append('\t').append(canonicalAppRoot.relativize(entry.getValue())).append('\n');
            if(result.length()>MAX_ENCODED_BYTES)throw new IOException("Owned diagnostic selection exceeds its bound");
        }
        return result.toString();
    }

    /** Empty preference means no saved selection. Every other value requires
     * the exact versioned format and is validated again against current metadata. */
    public static Map<String,Path> decode(Path canonicalAppRoot,String encoded)throws IOException {
        root(canonicalAppRoot);
        if(encoded==null||encoded.length()>MAX_ENCODED_BYTES)throw new IOException("Owned diagnostic selection exceeds its bound");
        if(encoded.isEmpty())return Collections.emptyMap();
        for(int index=0;index<encoded.length();index++) {
            char value=encoded.charAt(index);
            if(value>127||(value<32&&value!='\n'&&value!='\t'))throw new IOException("Invalid owned diagnostic metadata encoding");
        }
        String[] lines=encoded.split("\n",-1);
        if(lines.length<2||lines.length>MAX_NAMES+2||!HEADER.equals(lines[0])||!lines[lines.length-1].isEmpty())
            throw new IOException("Invalid owned diagnostic selection format");
        TreeMap<String,Path> result=new TreeMap<>();
        for(int index=1;index<lines.length-1;index++) {
            String line=lines[index];int tab=line.indexOf('\t');
            if(tab<=0||tab!=line.lastIndexOf('\t'))throw new IOException("Invalid owned diagnostic selection record");
            String name=line.substring(0,tab),relative=line.substring(tab+1);
            Path path=validate(canonicalAppRoot,name,relative);
            if(result.put(name,path)!=null)throw new IOException("Duplicate owned diagnostic log role");
        }
        return Collections.unmodifiableMap(result);
    }

    private static Path validate(Path root,String name,String relative)throws IOException {
        if(name==null||name.length()>84||relative.isEmpty()||relative.length()>MAX_RELATIVE_PATH||relative.startsWith("/")||relative.indexOf('\\')>=0||
                !relative.matches("[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"))throw new IOException("Invalid owned diagnostic path or role");
        for(String component:relative.split("/")) {
            String folded=component.toLowerCase(Locale.ROOT);
            if(component.equals(".")||component.equals("..")||PRIVATE_COMPONENTS.contains(folded)||folded.endsWith(".json"))
                throw new IOException("Private diagnostic paths are excluded");
        }
        String expected=null;Matcher match=DATABASE.matcher(name);
        if(match.matches())expected="state/database-service-operations/"+OP+"/logs/"+match.group(1)+"\\.log";
        if(expected==null&&(match=SERVER_HELPER.matcher(name)).matches())expected="state/server-session-runtime-operations/"+OP+"/logs/"+match.group(1)+"\\.log";
        if(expected==null&&(match=SERVER.matcher(name)).matches())expected="db/"+SLOT+"/server-sessions/"+OP+"/"+match.group(1)+"\\.log";
        if(expected==null&&(match=PRESENTATION.matcher(name)).matches())expected="s/"+SLOT+"/"+match.group(1)+"/logs/"+match.group(2)+"\\.log";
        if(expected==null&&(match=SETUP.matcher(name)).matches()) {
            String directory=match.group(1).equals("data")?"server-data-operations":match.group(1).equals("shader")?"shader-operations":
                match.group(1).equals("stock")?"stock-client-operations":match.group(1).equals("turnip")?"turnip-probe-operations":"server-installation-processes";
            expected="state/"+directory+"/"+OP+"/logs/"+match.group(2)+"\\.log";
        }
        if(expected==null||!relative.matches(expected))throw new IOException("Unsupported owned diagnostic role or path");
        Path path=root.resolve(relative);
        if(!path.normalize().equals(path)||!path.startsWith(root))throw new IOException("Diagnostic selection escapes private storage");
        Path current=root;int part=0,total=path.getNameCount()-root.getNameCount();
        for(Path component:root.relativize(path)) {
            current=current.resolve(component);part++;
            BasicFileAttributes attributes;
            try{attributes=Files.readAttributes(current,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);}
            catch(NoSuchFileException missing){continue;}
            if(attributes.isSymbolicLink()||(part<total?!attributes.isDirectory():!attributes.isRegularFile()))
                throw new IOException("Owned diagnostic path contains a link or unexpected file type");
        }
        return path;
    }
    private static void root(Path root)throws IOException {
        if(root==null||!root.isAbsolute()||!root.normalize().equals(root)||!Files.isDirectory(root,LinkOption.NOFOLLOW_LINKS)||!root.equals(root.toRealPath()))
            throw new IOException("Canonical private application root required for diagnostic selection");
    }
}
