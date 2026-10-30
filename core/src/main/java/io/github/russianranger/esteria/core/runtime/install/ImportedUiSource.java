package io.github.russianranger.esteria.core.runtime.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;

/** Exact Interface hashes resolved through completed GameDataImporter overlay ancestry.
 * Completion and journals are trusted private importer records, not signatures or content qualification.
 */
public final class ImportedUiSource {
    public final String importGeneration, inventoryId;
    public final int files;
    public final long bytes;
    final Path interfaceRoot,dataRoot;
    final SortedMap<String,UiFiles.Entry> inventory;
    final String inventoryText, provenance;
    private final Map<Path,String> metadata;
    private final Map<Path,Long> metadataSizes=new HashMap<>();
    private ImportedUiSource(String imported,Path data,Path source,SortedMap<String,UiFiles.Entry> entries,String provenance,Map<Path,String> metadata)throws IOException {
        importGeneration=imported;dataRoot=data;interfaceRoot=source;inventory=Collections.unmodifiableSortedMap(new TreeMap<>(entries));
        inventoryText=UiFiles.encode(entries);inventoryId=RuntimeFiles.hashText(inventoryText);files=entries.size();bytes=UiFiles.total(entries);
        this.provenance=provenance;this.metadata=Collections.unmodifiableMap(new LinkedHashMap<>(metadata));
        long total=0;
        for(Path path:metadata.keySet()) {
            RuntimeFiles.plain(path);long size=Files.size(path);total+=size;
            RuntimeFiles.require(size<=32L<<20&&total<=(64L<<20)+(128L<<10),"Import metadata grew beyond bounded provenance");metadataSizes.put(path,size);
        }
    }
    public static ImportedUiSource fromImportStore(Path store,String generation,RuntimeWork.Cancellation cancelled)throws IOException {
        UiFiles.directory(store);RuntimeFiles.hashPin(generation);Path generations=UiFiles.directory(store.resolve("generations"));
        List<Path> chain=new ArrayList<>();Set<String> seen=new HashSet<>();Map<Path,String> identities=new LinkedHashMap<>();long metadataBytes=0;
        String id=generation;
        while(id!=null) {
            RuntimeWork.check(cancelled);RuntimeFiles.require(chain.size()<32&&seen.add(id),"Import overlay ancestry cycle/depth bound exceeded");
            Path at=UiFiles.directory(generations.resolve(id));UiFiles.directory(at.resolve("data"));
            Path complete=at.resolve("complete");String text=RuntimeFiles.smallText(complete,2048);Map<String,String> values=properties(text);
            RuntimeFiles.require("1".equals(values.get("format"))&&"12340".equals(values.get("clientBuild"))&&id.equals(values.get("request")),"Import completion does not bind this build/generation");
            RuntimeFiles.hashPin(values.get("source"));identities.put(complete,RuntimeFiles.hashText(text));chain.add(at);
            Path journal=at.resolve("journal.tsv");RuntimeFiles.plain(journal);long size=Files.size(journal);
            metadataBytes+=size;RuntimeFiles.require(size<=32L<<20&&metadataBytes<=64L<<20,"Import ancestry journal metadata exceeds64MiB bound");
            identities.put(journal,RuntimeFiles.hashFile(journal,size,cancelled));
            Path parent=at.resolve("base-ready");
            if(Files.exists(parent,LinkOption.NOFOLLOW_LINKS)) {
                String raw=RuntimeFiles.smallText(parent,66);String previous=raw.trim();RuntimeFiles.hashPin(previous);
                RuntimeFiles.require(raw.equals(previous+"\n"),"Invalid import parent receipt");identities.put(parent,RuntimeFiles.hashText(raw));id=previous;
            } else id=null;
        }
        SortedMap<String,UiFiles.Entry> hashes=new TreeMap<>();Collections.reverse(chain);
        for(Path at:chain)readJournal(at.resolve("journal.tsv"),hashes,cancelled);
        Path data=generations.resolve(generation).resolve("data"),ui=null;Set<String> roots=new HashSet<>();int count=0;
        try(DirectoryStream<Path> paths=Files.newDirectoryStream(data)) {
            for(Path path:paths) {
                RuntimeWork.check(cancelled);RuntimeFiles.require(++count<=UiFiles.MAX_FILES,"Imported root inventory exceeds UI bound");
                String name=path.getFileName().toString(),lower=name.toLowerCase(Locale.ROOT);
                RuntimeFiles.require(roots.add(lower),"Case-colliding import root entries");
                BasicFileAttributes attributes=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
                RuntimeFiles.require(!attributes.isSymbolicLink()&&(attributes.isDirectory()||attributes.isRegularFile()),"Imported root contains link/special file");
                if(lower.equals("interface"))ui=UiFiles.directory(path);
            }
        }
        SortedMap<String,UiFiles.Entry> selected=new TreeMap<>();
        if(ui!=null)UiFiles.walk(ui,cancelled,(relative,path,attributes)->{
            UiFiles.Entry expected=hashes.get(relative.toLowerCase(Locale.ROOT));
            RuntimeFiles.require(expected!=null&&expected.bytes==attributes.size(),"Loose UI file has no matching completed import hash");selected.put(relative,expected);
        });
        StringBuilder provenance=new StringBuilder("esteria-ui-source-v1\nimport=").append(generation).append('\n');
        for(Map.Entry<Path,String> row:identities.entrySet())provenance.append(generations.relativize(row.getKey())).append('\t').append(row.getValue()).append('\n');
        ImportedUiSource result=new ImportedUiSource(generation,data,ui,selected,provenance.toString(),identities);result.verifyMetadata(cancelled);return result;
    }
    void verifyMetadata(RuntimeWork.Cancellation cancelled)throws IOException {
        for(Map.Entry<Path,String> row:metadata.entrySet())RuntimeFiles.require(RuntimeFiles.hashFile(row.getKey(),metadataSizes.get(row.getKey()),cancelled).equals(row.getValue()),"Import provenance changed during UI preparation");
    }
    void verifySource(RuntimeWork.Cancellation cancelled)throws IOException {
        verifyMetadata(cancelled);Set<String> found=new HashSet<>();
        if(interfaceRoot!=null)UiFiles.walk(interfaceRoot,cancelled,(name,path,attributes)->{
            UiFiles.Entry expected=inventory.get(name);
            RuntimeFiles.require(expected!=null&&RuntimeFiles.hashFile(path,expected.bytes,cancelled).equals(expected.sha256),"Imported UI bytes differ from immutable source inventory");found.add(name);
        });
        RuntimeFiles.require(found.equals(inventory.keySet()),"Imported UI file inventory changed");
    }
    private static Map<String,String> properties(String text)throws IOException {
        Map<String,String> result=new HashMap<>();RuntimeFiles.require(text.endsWith("\n"),"Incomplete import completion receipt");
        for(String line:text.split("\n")) {
            int split=line.indexOf('=');RuntimeFiles.require(split>0&&result.put(line.substring(0,split),line.substring(split+1))==null,"Invalid import completion field");
        }return result;
    }
    private static void readJournal(Path path,Map<String,UiFiles.Entry> output,RuntimeWork.Cancellation cancelled)throws IOException {
        try(BufferedReader input=Files.newBufferedReader(path,StandardCharsets.UTF_8)) {
            for(String line;(line=line(input))!=null;) {
                RuntimeWork.check(cancelled);String[] row=line.split("\t",-1);
                // The importer intentionally isolates incomplete old records with a
                // leading newline. Ignore those records, but require a valid hash
                // for every currently present Interface file before using it.
                if(row.length!=4||!row[3].matches("[0-9a-f]{64}"))continue;
                String name;long size,modified;
                try{name=new String(Base64.getDecoder().decode(row[0]),StandardCharsets.UTF_8);size=Long.parseLong(row[1]);modified=Long.parseLong(row[2]);}
                catch(IllegalArgumentException invalid){continue;}
                if(!name.toLowerCase(Locale.ROOT).startsWith("interface/"))continue;
                String relative=UiFiles.safe(name.substring("Interface/".length()));
                RuntimeFiles.require(modified>=0,"Invalid imported UI journal timestamp");
                output.put(relative.toLowerCase(Locale.ROOT),new UiFiles.Entry(size,row[3]));
                RuntimeFiles.require(output.size()<=UiFiles.MAX_FILES,"Inherited UI journal inventory exceeds bound");
            }
        }
    }
    private static String line(Reader input)throws IOException {
        StringBuilder line=new StringBuilder();int value;
        while((value=input.read())!=-1) {
            if(value=='\n')return line.toString();RuntimeFiles.require(line.length()<2048,"Import journal record exceeds bound");line.append((char)value);
        }return null;
    }
}
