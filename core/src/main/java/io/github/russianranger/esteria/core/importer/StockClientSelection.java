package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;

/** App-owned stock projection. The imported source generation is never edited.
 * Only a content-audited path+SHA can exclude an MPQ; standard Blizzard patches
 * cannot be removed. The usual importer supplies bounded streaming/resume and
 * atomic activation. This is selection, never runtime compatibility proof. */
public final class StockClientSelection {
    private StockClientSelection() { }
    public static Path apply(GameDataImporter importer, Path source, String generation,
            Map<String,String> confirmedExclusions, String reportSha256,
            GameDataImporter.ProgressListener progress, GameDataImporter.Cancellation cancellation) throws IOException {
        if(importer==null||source==null||generation==null||confirmedExclusions==null||!generation.matches("[0-9a-f]{64}")||
                reportSha256==null||!reportSha256.matches("[0-9a-f]{64}"))throw new IOException("Bounded stock selection identity required");
        if(!source.equals(importer.resolveCurrent())||!source.getParent().getFileName().toString().equals(generation))
            throw new IOException("Stock audit no longer selects the current imported client");
        SortedMap<String,String> exclusions=new TreeMap<>();
        for(Map.Entry<String,String> entry:confirmedExclusions.entrySet()) {
            String name=entry.getKey();String folded=name.toLowerCase(Locale.ROOT);
            if(!safe(name)||!folded.startsWith("data/")||!folded.endsWith(".mpq")||
                    entry.getValue()==null||!entry.getValue().matches("[0-9a-f]{64}")||
                    ordinaryArchivePath(name)||exclusions.put(name,entry.getValue())!=null)
                throw new IOException("Stock selection cannot exclude an essential or unaudited archive: "+name);
            Path archive=source.resolve(name);
            plain(archive);
            if(!entry.getValue().equals(hash(archive,cancellation)))throw new IOException("Optional overlay changed after stock audit: "+name);
        }
        SelectionSource input=new SelectionSource(importer,source,generation,exclusions,reportSha256);
        List<GameDataImporter.InputEntry> files=input.snapshot(cancellation);
        // Avoid an unnecessary second client copy when the imported source is
        // already the exact stock selection. Repeated setup does not hash MPQs.
        if(!input.removed) { input.verifySnapshot(files);return source; }
        return importer.importSource(input,GameDataImporter.ImportKind.BASE_CLIENT,progress,cancellation).gameDirectory;
    }
    private static boolean ordinaryArchivePath(String name) {
        String folded=name.toLowerCase(Locale.ROOT);
        if(folded.matches("data/(common(?:-[23])?|expansion|lichking|patch(?:-[23])?)\\.mpq"))return true;
        for(String locale:Arrays.asList("dede","engb","enus","eses","frfr","kokr","zhcn","zhtw","encn","entw","esmx","ruru"))
            if(folded.matches("data/"+locale+"/(?:locale-|speech-|expansion-locale-|lichking-locale-|expansion-speech-|lichking-speech-|patch-)"+locale+"(?:-[23])?\\.mpq"))return true;
        return false;
    }
    private static boolean retained(String name,Map<String,String> exclusions) {
        String folded=name.toLowerCase(Locale.ROOT);
        // These known loose overrides and custom namespaces are deliberately
        // outside this profile. Ordinary ignored installer/account files need
        // no second copy: ClientLaunchView never exposes them to the engine.
        if(folded.equals("interface")||folded.startsWith("interface/")||
                folded.equals("fonts")||folded.startsWith("fonts/")||
                folded.equals("esteriaserverdata")||folded.startsWith("esteriaserverdata/")||
                folded.matches("esteria[a-z0-9_.-]*\\.bin"))return false;
        for(String prefix:Arrays.asList("data/retail","data/forever","data/esteriaretail","data/esteriaforever"))
            if(folded.equals(prefix)||folded.startsWith(prefix+"/"))return false;
        for(String excluded:exclusions.keySet())if(name.equalsIgnoreCase(excluded))return false;
        return true;
    }
    private static boolean safe(String name) {
        if(name==null||name.isEmpty()||name.length()>1024||name.startsWith("/")||name.indexOf('\\')>=0)return false;
        for(String part:name.split("/",-1))if(part.isEmpty()||part.equals(".")||part.equals(".."))return false;
        return true;
    }
    private static final class SelectionSource implements GameDataImporter.InputSource {
        final GameDataImporter importer;final Path source;final String generation,report;final SortedMap<String,String> exclusions;
        List<GameDataImporter.InputEntry> selected;boolean removed;
        SelectionSource(GameDataImporter importer,Path source,String generation,SortedMap<String,String> exclusions,String report) {
            this.importer=importer;this.source=source;this.generation=generation;this.exclusions=exclusions;this.report=report;
        }
        public String identity(){return "stock-3.3.5a-selection-v1\n"+generation+"\n"+report;}
        public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation)throws IOException {
            if(!source.equals(importer.resolveCurrent()))throw new IOException("Imported client changed before stock selection");
            if(selected!=null)return selected;
            GameDataImporter.MetadataBudget budget=new GameDataImporter.MetadataBudget();
            List<GameDataImporter.InputEntry> rows=new ArrayList<>();Set<String> seen=new HashSet<>();
            Files.walkFileTree(source,new SimpleFileVisitor<Path>() {
                public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attrs)throws IOException {
                    check(cancellation);if(attrs.isSymbolicLink()||!path.toRealPath().equals(path))throw new IOException("Linked stock selection directory");
                    String name=source.relativize(path).toString().replace('\\','/');
                    budget.add(name,"",true);
                    if(!name.isEmpty()&&!retained(name,exclusions)){removed=true;return FileVisitResult.SKIP_SUBTREE;}
                    return FileVisitResult.CONTINUE;
                }
                public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException {
                    check(cancellation);plain(path);String name=source.relativize(path).toString().replace('\\','/');
                    if(!safe(name)||!seen.add(name.toLowerCase(Locale.ROOT)))throw new IOException("Ambiguous stock source path");
                    budget.add(name,name,false);
                    if(retained(name,exclusions))rows.add(new GameDataImporter.InputEntry(name,name,attrs.size(),attrs.lastModifiedTime().toMillis()));
                    else removed=true;
                    return FileVisitResult.CONTINUE;
                }
            });
            rows.sort(Comparator.comparing(row->row.relativePath));selected=Collections.unmodifiableList(rows);return selected;
        }
        public InputStream open(GameDataImporter.InputEntry entry)throws IOException {verifyUnchanged(entry);return Files.newInputStream(source.resolve(entry.id),LinkOption.NOFOLLOW_LINKS);}
        public void verifyUnchanged(GameDataImporter.InputEntry entry)throws IOException {
            Path path=source.resolve(entry.id);plain(path);BasicFileAttributes now=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
            if(now.size()!=entry.size||now.lastModifiedTime().toMillis()!=entry.modifiedMillis)throw new IOException("Stock source changed: "+entry.relativePath);
        }
        public void verifySnapshot(List<GameDataImporter.InputEntry> snapshot)throws IOException {
            if(!source.equals(importer.resolveCurrent()))throw new IOException("Import changed during stock selection; original source is retained");
            for(GameDataImporter.InputEntry row:snapshot)verifyUnchanged(row);
        }
    }
    private static void plain(Path path)throws IOException {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||!path.equals(path.toRealPath()))throw new IOException("Ordinary immutable stock source required");
    }
    private static void check(GameDataImporter.Cancellation cancellation)throws IOException {
        if(cancellation.isCancelled()||Thread.currentThread().isInterrupted())throw new GameDataImporter.ImportCancelledException();
    }
    private static String hash(Path path,GameDataImporter.Cancellation cancellation)throws IOException {
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");byte[] block=new byte[128<<10];long bytes=0;BasicFileAttributes before=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
            try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){for(int count;(count=input.read(block))!=-1;){check(cancellation);digest.update(block,0,count);bytes+=count;}}
            BasicFileAttributes after=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
            if(bytes!=before.size()||before.size()!=after.size()||!before.lastModifiedTime().equals(after.lastModifiedTime()))throw new IOException("Optional stock source changed while validating selection");
            StringBuilder result=new StringBuilder();for(byte value:digest.digest())result.append(String.format(Locale.ROOT,"%02x",value&255));return result.toString();
        }catch(NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
}
