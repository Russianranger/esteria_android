package io.github.russianranger.esteria.runtime;

import android.util.JsonReader;
import android.util.JsonToken;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.TreeSet;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** Read-only binding of completed data metadata to its current import/provider.
 * This establishes no source-build, map coverage or world qualification. The
 * guest must independently verify every prepared data byte before server launch.
 */
public final class ServerDataBinding {
    public final String generation;
    public final Path directory;
    private final ServerDataRunPlan plan;
    private final String inputsJson,receiptJson;
    private ServerDataBinding(ServerDataRunPlan plan,Path directory,String generation,JSONObject inputs,JSONObject receipt)throws IOException {
        this.plan=plan;this.directory=directory;this.generation=generation;
        inputsJson=inputs.toString();receiptJson=receipt.toString();
    }
    /** Deliberately package-private. Only a future source-qualified composed
     * tool/setup owner may attach this inspector to its verified provider.
     * A caller-pinned launch plan is not public source qualification authority. */
    static ServerDataBinding inspect(ServerDataRunPlan plan,String verifiedServerRevision)throws IOException {
        plan.requireInputsUnchanged();
        Path store=directory(plan.work.resolve("server-data"));
        String generation=ascii(store.resolve("current"),65);
        if(!generation.matches("[0-9a-f]{64}\\n"))throw new IOException("Invalid completed server data pointer");
        generation=generation.substring(0,64);
        Path selected=directory(directory(store.resolve("generations")).resolve(generation));
        directory(selected.resolve("data"));
        try {
            Parsed receipt=parseReceipt(selected.resolve("receipt.json"));JSONObject value=receipt.value;
            keys(value,"formatVersion","scope","generation","inputs","files","providerOrder","preflight","worldQualified","androidQualified","gameplayQualified");
            if(integer(value,"formatVersion")!=1||!"local-server-data-format-checked-not-world-qualified".equals(value.get("scope"))||
                    !generation.equals(value.get("generation"))||!Boolean.FALSE.equals(value.get("worldQualified"))||
                    !Boolean.FALSE.equals(value.get("androidQualified"))||!Boolean.FALSE.equals(value.get("gameplayQualified"))||
                    !Boolean.TRUE.equals(value.getJSONObject("preflight").get("checks_passed")))
                throw new IOException("Prepared server data scope differs");
            JSONObject inputs=value.getJSONObject("inputs");
            keys(inputs,"formatVersion","importGeneration","clientRevision","serverRevision","locale","threads","importMetadata","toolSelectionSha256");
            if(integer(inputs,"formatVersion")!=1||!BuildConfig.CLIENT_REVISION.equals(inputs.get("clientRevision"))||
                    !verifiedServerRevision.equals(inputs.get("serverRevision"))||!plan.importGeneration.equals(inputs.get("importGeneration"))||
                    !plan.locale.equals(inputs.get("locale"))||integer(inputs,"threads")!=plan.threads||
                    !hash((canonical(inputs)+"\n").getBytes(StandardCharsets.UTF_8)).equals(generation))
                throw new IOException("Prepared data source/import selection differs");
            JSONObject selection=new JSONObject(new String(read(plan.work.resolve("data-tools-selection.json"),65536),StandardCharsets.UTF_8));
            if(!verifiedServerRevision.equals(selection.get("serverRevision"))||!BuildConfig.CLIENT_REVISION.equals(selection.get("clientRevision"))||
                    !hash((canonical(selection)+"\n").getBytes(StandardCharsets.UTF_8)).equals(inputs.get("toolSelectionSha256")))
                throw new IOException("Prepared data tool selection differs");
            if(!canonical(importMetadata(plan.game,plan.importGeneration)).equals(canonical(inputs.getJSONObject("importMetadata"))))
                throw new IOException("Prepared data import ancestry changed");
            JSONObject provider=value.getJSONObject("providerOrder");keys(provider,"effectiveLocale","manifest","wire");
            pin(provider.getJSONObject("manifest"),16L<<20);pin(provider.getJSONObject("wire"),16L<<20);
            if(!canonical(identity(selected.resolve("order.json"),16L<<20)).equals(canonical(provider.getJSONObject("manifest")))||
                    !canonical(identity(selected.resolve("order.tsv"),16L<<20)).equals(canonical(provider.getJSONObject("wire"))))
                throw new IOException("Prepared provider order metadata changed");
            plan.requireInputsUnchanged();
            return new ServerDataBinding(plan,selected,generation,inputs,receipt.identity);
        }catch(JSONException error){throw new IOException("Invalid completed server data metadata",error);}
    }
    public void requireUnchanged()throws IOException {
        plan.requireInputsUnchanged();
        if(!ascii(plan.work.resolve("server-data/current"),65).equals(generation+"\n"))throw new IOException("Prepared data selection changed");
        try{if(!canonical(identity(directory.resolve("receipt.json"),64L<<20)).equals(canonical(receiptIdentity()))||
                !canonical(importMetadata(plan.game,plan.importGeneration)).equals(canonical(inputs().getJSONObject("importMetadata"))))
            throw new IOException("Prepared data receipt or import ancestry changed");}
        catch(JSONException error){throw new IOException("Invalid retained server data binding",error);}
    }
    JSONObject inputs()throws IOException {return object(inputsJson);}
    JSONObject receiptIdentity()throws IOException {return object(receiptJson);}
    private static JSONObject object(String value)throws IOException {try{return new JSONObject(value);}catch(JSONException error){throw new IOException("Invalid retained data metadata",error);}}
    private static final class Parsed {
        final JSONObject value,identity;
        Parsed(JSONObject value,JSONObject identity){this.value=value;this.identity=identity;}
    }
    /** Stream the potentially large inventory instead of materializing it in
     * the Android heap. The guest performs its actual file hash comparison. */
    private static Parsed parseReceipt(Path path)throws IOException,JSONException {
        file(path);BasicFileAttributes before=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(before.size()>64L<<20)throw new IOException("Prepared data receipt exceeds bound");
        MessageDigest digest=digest();JSONObject result=new JSONObject();Set<String> names=new HashSet<>();
        try(DigestInputStream input=new DigestInputStream(new BoundedInput(Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS),64L<<20),digest);
                JsonReader reader=new JsonReader(new InputStreamReader(input,StandardCharsets.UTF_8))) {
            reader.setLenient(false);reader.beginObject();
            while(reader.hasNext()) {
                String name=reader.nextName();if(!names.add(name)||names.size()>10)throw new IOException("Duplicate/unexpected data receipt field");
                if(name.equals("files")) {
                    int count=0;reader.beginObject();String previous=null;
                    // Producer emits canonical sorted names; ordering enforces
                    // uniqueness with constant memory even for300,000 files.
                    while(reader.hasNext()) {
                        String relative=reader.nextName();
                        if(!relative.matches("[ -~]{1,1024}")||relative.startsWith("/")||relative.contains("\\")||relative.contains(":")||
                                relative.contains("//")||relative.equals(".")||relative.equals("..")||relative.startsWith("../")||relative.endsWith("/..")||
                                relative.contains("/../")||relative.contains("/./")||relative.startsWith("./")||relative.endsWith("/.")||
                                (previous!=null&&previous.compareTo(relative)>=0)||++count>300000)throw new IOException("Invalid streamed data inventory");
                        previous=relative;pin((JSONObject)json(reader,0),16L<<30);
                    }
                    reader.endObject();if(count==0)throw new IOException("Empty prepared data inventory");result.put(name,JSONObject.NULL);
                } else result.put(name,json(reader,0));
            }
            reader.endObject();if(reader.peek()!=JsonToken.END_DOCUMENT)throw new IOException("Trailing prepared data metadata");
        }
        BasicFileAttributes after=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(before.size()!=after.size()||!before.lastModifiedTime().equals(after.lastModifiedTime())||
                (before.fileKey()!=null&&!before.fileKey().equals(after.fileKey())))throw new IOException("Prepared data metadata changed while reading");
        return new Parsed(result,new JSONObject().put("bytes",before.size()).put("sha256",hex(digest.digest())));
    }
    private static final class BoundedInput extends java.io.FilterInputStream {
        private final long maximum;private long count;
        BoundedInput(java.io.InputStream input,long maximum){super(input);this.maximum=maximum;}
        private void consumed(int bytes)throws IOException{if(bytes>0&&(count+=bytes)>maximum)throw new IOException("Data receipt grew beyond bound");}
        @Override public int read()throws IOException{int value=in.read();consumed(value<0?0:1);return value;}
        @Override public int read(byte[] bytes,int offset,int length)throws IOException{int got=in.read(bytes,offset,length);consumed(got);return got;}
    }
    private static Object json(JsonReader reader,int depth)throws IOException,JSONException {
        if(depth>8)throw new IOException("Data metadata depth exceeds bound");
        switch(reader.peek()) {
            case BEGIN_OBJECT: {
                JSONObject value=new JSONObject();reader.beginObject();int count=0;
                while(reader.hasNext()){String key=reader.nextName();if(key.length()>1024||value.has(key)||++count>512)throw new IOException("Data metadata fields exceed bound");value.put(key,json(reader,depth+1));}
                reader.endObject();return value;
            }
            case BEGIN_ARRAY: {
                JSONArray values=new JSONArray();reader.beginArray();
                while(reader.hasNext()){if(values.length()>=512)throw new IOException("Data metadata array exceeds bound");values.put(json(reader,depth+1));}
                reader.endArray();return values;
            }
            case STRING: {String value=reader.nextString();if(value.length()>4096)throw new IOException("Data metadata string exceeds bound");return value;}
            case NUMBER:return reader.nextLong();
            case BOOLEAN:return reader.nextBoolean();
            case NULL:reader.nextNull();return JSONObject.NULL;
            default:throw new IOException("Unexpected data metadata token");
        }
    }
    private static JSONObject importMetadata(Path game,String generation)throws IOException,JSONException {
        JSONObject records=new JSONObject();Set<String> seen=new HashSet<>();String at=generation;long total=0;
        while(at!=null) {
            if(!seen.add(at)||seen.size()>32)throw new IOException("Import ancestry cycle/depth exceeds bound");
            Path root=directory(directory(game.resolve("generations")).resolve(at));directory(root.resolve("data"));
            byte[] complete=read(root.resolve("complete"),2048);java.util.Map<String,String> fields=new java.util.HashMap<>();
            String text=new String(complete,StandardCharsets.UTF_8);if(!text.endsWith("\n"))throw new IOException("Incomplete import receipt");
            for(String line:text.split("\n")) {int equal=line.indexOf('=');if(equal<=0||fields.put(line.substring(0,equal),line.substring(equal+1))!=null)throw new IOException("Invalid import completion fields");}
            if(!"1".equals(fields.get("format"))||!"12340".equals(fields.get("clientBuild"))||!at.equals(fields.get("request"))||
                    fields.get("source")==null||!fields.get("source").matches("[0-9a-f]{64}"))throw new IOException("Import does not bind build12340");
            records.put(at+"/complete",identity(root.resolve("complete"),2048));
            JSONObject journal=identity(root.resolve("journal.tsv"),32L<<20);total+=journal.getLong("bytes");
            if(total>64L<<20)throw new IOException("Import metadata exceeds64MiB");records.put(at+"/journal.tsv",journal);
            Path parent=root.resolve("base-ready");
            if(Files.exists(parent,LinkOption.NOFOLLOW_LINKS)) {
                String raw=ascii(parent,65);if(!raw.matches("[0-9a-f]{64}\\n"))throw new IOException("Invalid import ancestor");
                records.put(at+"/base-ready",identity(parent,65));at=raw.substring(0,64);
            } else at=null;
        }
        return records;
    }
    static String canonical(JSONObject value)throws IOException,JSONException {
        TreeSet<String> names=new TreeSet<>();value.keys().forEachRemaining(names::add);StringBuilder out=new StringBuilder("{");
        for(String name:names){if(out.length()>1)out.append(',');out.append(JSONObject.quote(name)).append(':');Object item=value.get(name);
            if(item instanceof JSONObject)out.append(canonical((JSONObject)item));
            else if(item instanceof String)out.append(JSONObject.quote((String)item));
            else if(item instanceof Boolean||item instanceof Integer||item instanceof Long)out.append(item);
            else throw new IOException("Unsupported canonical data input value");}
        return out.append('}').toString();
    }
    private static long integer(JSONObject value,String name)throws JSONException,IOException {Object item=value.get(name);if(!(item instanceof Integer)&&!(item instanceof Long))throw new IOException("Data metadata integer type differs");return ((Number)item).longValue();}
    private static void keys(JSONObject value,String... expected)throws IOException {Set<String> actual=new HashSet<>();value.keys().forEachRemaining(actual::add);if(!actual.equals(Set.of(expected)))throw new IOException("Data metadata field set differs");}
    private static void pin(JSONObject value,long maximum)throws IOException,JSONException {keys(value,"bytes","sha256");long bytes=integer(value,"bytes");if(bytes<0||bytes>maximum||!(value.get("sha256") instanceof String)||!value.getString("sha256").matches("[0-9a-f]{64}"))throw new IOException("Invalid data metadata identity");}
    private static JSONObject identity(Path path,long maximum)throws IOException,JSONException {file(path);MessageDigest digest=digest();long size=Files.size(path),count=0;if(size>maximum)throw new IOException("Data metadata exceeds bound");try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){byte[] block=new byte[65536];for(int got;(got=input.read(block))!=-1;){count+=got;if(count>maximum)throw new IOException("Data metadata grew beyond bound");digest.update(block,0,got);}}if(count!=size)throw new IOException("Data metadata size changed");return new JSONObject().put("bytes",size).put("sha256",hex(digest.digest()));}
    private static byte[] read(Path path,int maximum)throws IOException {file(path);if(Files.size(path)>maximum)throw new IOException("Data metadata exceeds bound");try(var input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS);var out=new ByteArrayOutputStream()){byte[] block=new byte[4096];for(int got;(got=input.read(block))!=-1;){if(out.size()+got>maximum)throw new IOException("Data metadata grew beyond bound");out.write(block,0,got);}return out.toByteArray();}}
    private static String ascii(Path path,int maximum)throws IOException {return new String(read(path,maximum),StandardCharsets.US_ASCII);}
    private static Path directory(Path path)throws IOException {if(!path.isAbsolute()||!path.equals(path.toRealPath())||!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS))throw new IOException("Canonical private data directory required");return path;}
    private static void file(Path path)throws IOException {if(!path.isAbsolute()||!path.equals(path.toRealPath())||!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))throw new IOException("Canonical data metadata file required");}
    private static MessageDigest digest()throws IOException {try{return MessageDigest.getInstance("SHA-256");}catch(NoSuchAlgorithmException error){throw new IOException(error);}}
    private static String hash(byte[] bytes)throws IOException {return hex(digest().digest(bytes));}
    private static String hex(byte[] bytes){StringBuilder out=new StringBuilder(64);for(byte value:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();}
}
