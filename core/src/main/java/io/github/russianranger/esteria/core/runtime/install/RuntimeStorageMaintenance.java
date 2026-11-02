package io.github.russianranger.esteria.core.runtime.install;

import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.TreeMap;

/** Idle-only maintenance of replaceable installer output. Import, world data,
 * database workspaces, Wine prefixes and saves are outside this fixed allowlist.
 * Byte counts are logical regular-file bytes, not an allocation guarantee for
 * compressed files, sparse files or shared hardlinks. */
public final class RuntimeStorageMaintenance {
    private static final Set<String> PACKAGES=Set.of("wine-arm64","server-arm64","server-programs-arm64",
        "server-content-arm64","server-extractors-arm64","server-data-tools-arm64","guest-bridges-arm64",
        "client-arm64","shader-tools-arm64","turnip-arm64");
    private static final String TRASH="cleanup-trash", MARKER="maintenance-owner";
    private static final int MAX_CANDIDATES=512, MAX_ENTRIES=500000, MAX_DEPTH=128, MAX_DIRECTORY_ENTRIES=100000;
    private static final long MAX_DIRECTORY_NAME_BYTES=8L<<20, MAX_BYTES=1L<<40;

    @FunctionalInterface public interface Guard {void requireIdle() throws IOException;}

    public static final class Report {
        public final long reclaimableBytes,removedBytes;
        public final int obsoleteGenerations,cachedArchives,unknownItemsPreserved,removedItems;
        private Report(State state) {
            reclaimableBytes=state.reclaimableBytes;removedBytes=state.removedBytes;
            obsoleteGenerations=state.obsoleteGenerations;cachedArchives=state.cachedArchives;
            unknownItemsPreserved=state.unknownItemsPreserved;removedItems=state.removedItems;
        }
    }

    private RuntimeStorageMaintenance(){ }

    public static Report scan(Path root,Map<String,String> expectedGenerations,Guard guard,
            RuntimeWork.Cancellation cancelled)throws IOException {
        return run(root,expectedGenerations,guard,cancelled,null,false);
    }

    public static Report trim(Path root,Map<String,String> expectedGenerations,Guard guard,
            RuntimeWork.Cancellation cancelled,RuntimeWork.Progress progress)throws IOException {
        return run(root,expectedGenerations,guard,cancelled,progress,true);
    }

    private static Report run(Path root,Map<String,String> expected,Guard guard,
            RuntimeWork.Cancellation cancelled,RuntimeWork.Progress progress,boolean remove)throws IOException {
        RuntimeFiles.require(root!=null&&guard!=null&&expected!=null,"Maintenance needs a private root and idle guard");
        RuntimeFiles.require(root.isAbsolute()&&root.equals(root.normalize()),"Maintenance requires a canonical absolute root");
        directory(root);
        RuntimeFiles.require(root.equals(root.toRealPath()),"Maintenance requires canonical application storage");
        TreeMap<String,String> pins=new TreeMap<>();
        for(Map.Entry<String,String> pin:expected.entrySet()) {
            RuntimeFiles.require(PACKAGES.contains(pin.getKey()),"Unsupported runtime maintenance package");
            RuntimeFiles.hashPin(pin.getValue());pins.put(pin.getKey(),pin.getValue());
        }
        State state=new State(root,pins,guard,cancelled,progress);
        List<ExclusiveFileLease> leases=new ArrayList<>();
        Throwable primary=null;
        try {
            state.check();leases.add(ExclusiveFileLease.acquire(root.resolve(".runtime-maintenance.lock"),"Storage maintenance is already active"));
            // Acquire every installer/cache lease before selecting any output.
            List<Path> stores=new ArrayList<>();
            for(String key:new java.util.TreeSet<>(PACKAGES)) {
                addExisting(stores,root.resolve("runtimes").resolve(key));
                if(!key.equals("wine-arm64"))addExisting(stores,root.resolve("runtime-embedded-cache").resolve(key));
            }
            addExisting(stores,root.resolve("runtime-downloads"));Collections.sort(stores);
            for(Path store:stores){state.check();directory(store);leases.add(ExclusiveFileLease.acquire(store.resolve(".lock"),"Runtime or archive cache is in use"));}
            for(String key:new java.util.TreeSet<>(PACKAGES))state.runtime(key);
            for(Candidate candidate:state.candidates) {
                state.check();state.reclaimableBytes=add(state.reclaimableBytes,state.count(candidate.path,0));
            }
            if(remove)for(Candidate candidate:state.candidates)state.remove(candidate);
            return new Report(state);
        }catch(IOException|RuntimeException|Error failure){primary=failure;throw failure;
        }finally {
            IOException failure=null;
            for(int i=leases.size()-1;i>=0;i--)try{leases.get(i).close();}catch(IOException close){if(failure==null)failure=close;else failure.addSuppressed(close);}
            if(failure!=null){if(primary!=null)primary.addSuppressed(failure);else throw failure;}
        }
    }

    private static void addExisting(List<Path> stores,Path path)throws IOException {
        if(Files.exists(path,LinkOption.NOFOLLOW_LINKS)){directory(path);stores.add(path);}
    }
    private static void directory(Path path)throws IOException {
        Path at=path.toAbsolutePath().normalize();
        while(at!=null){RuntimeFiles.require(Files.isDirectory(at,LinkOption.NOFOLLOW_LINKS),"Maintenance directory has a link or file ancestor");at=at.getParent();}
    }
    private static long add(long first,long more)throws IOException {
        RuntimeFiles.require(more>=0&&more<=MAX_BYTES-first,"Maintenance byte inventory exceeds its bound");return first+more;
    }
    private static boolean hash(String text){return text!=null&&text.matches("[0-9a-f]{64}");}
    private static BasicFileAttributes attributes(Path path)throws IOException {
        directory(path.getParent());return Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
    }
    private static void unchanged(Path path,BasicFileAttributes expected)throws IOException {
        BasicFileAttributes now=attributes(path);
        RuntimeFiles.require(now.isDirectory()==expected.isDirectory()&&now.isRegularFile()==expected.isRegularFile()&&
            now.isSymbolicLink()==expected.isSymbolicLink()&&java.util.Objects.equals(now.fileKey(),expected.fileKey())&&
            (!now.isRegularFile()||(now.size()==expected.size()&&now.lastModifiedTime().equals(expected.lastModifiedTime()))),
            "Maintenance candidate changed; retry storage scan");
    }
    private static boolean owned(Path path,String generation,boolean complete)throws IOException {
        if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS))return false;
        Path owner=path.resolve("owner");
        if(!Files.isRegularFile(owner,LinkOption.NOFOLLOW_LINKS)||
            !RuntimeFiles.smallText(owner,256).equals("esteria-runtime-stage-v1\n"+generation+"\n"))return false;
        return !complete||(Files.isDirectory(path.resolve("rootfs"),LinkOption.NOFOLLOW_LINKS)&&completion(path,generation)!=null);
    }
    private static String completion(Path path,String generation)throws IOException {
        Path file=path.resolve("complete");
        if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS))return null;
        Properties properties=new Properties();
        try{properties.load(new java.io.StringReader(RuntimeFiles.smallText(file,2048)));}
        catch(IllegalArgumentException invalid){return null;}
        if(!"1".equals(properties.getProperty("format"))||!generation.equals(properties.getProperty("generation"))||
            !hash(properties.getProperty("sourcePin"))||!hash(properties.getProperty("archiveSha256"))||
            !"false".equals(properties.getProperty("gameplayQualified")))return null;
        return properties.getProperty("archiveSha256");
    }
    private static String trashOwner(String kind,String generation){return "esteria-runtime-maintenance-v1\n"+kind+"\n"+generation+"\n";}

    private static final class Candidate {
        final Path path,store;final String generation,kind;final boolean trash,cache;
        final BasicFileAttributes identity;
        Candidate(Path path,Path store,String generation,String kind,boolean trash,boolean cache)throws IOException {
            this.path=path;this.store=store;this.generation=generation;this.kind=kind;this.trash=trash;this.cache=cache;identity=attributes(path);
        }
    }
    private static final class State {
        final Path root;final Map<String,String> expected;final Guard guard;
        final RuntimeWork.Cancellation cancelled;final RuntimeWork.Progress progress;
        final List<Candidate> candidates=new ArrayList<>();
        long reclaimableBytes,removedBytes;int obsoleteGenerations,cachedArchives,unknownItemsPreserved,removedItems,entries,deletedEntries;
        State(Path root,Map<String,String> expected,Guard guard,RuntimeWork.Cancellation cancelled,RuntimeWork.Progress progress) {
            this.root=root;this.expected=expected;this.guard=guard;this.cancelled=cancelled;this.progress=progress;
        }
        void check()throws IOException {guard.requireIdle();RuntimeWork.check(cancelled);}
        void visit()throws IOException {check();RuntimeFiles.require(++entries<=MAX_ENTRIES,"Maintenance file inventory exceeds its bound");}
        List<Path> children(Path path)throws IOException {
            check();directory(path);List<Path> result=new ArrayList<>();long bytes=0;
            try(DirectoryStream<Path> members=Files.newDirectoryStream(path)) {
                for(Path member:members) {
                    check();RuntimeFiles.require(result.size()<MAX_DIRECTORY_ENTRIES,"Maintenance directory inventory exceeds its bound");
                    bytes+=member.getFileName().toString().length()*2L+128;
                    RuntimeFiles.require(bytes<=MAX_DIRECTORY_NAME_BYTES,"Maintenance directory names exceed their memory budget");result.add(member);
                }
            }
            Collections.sort(result);return result;
        }
        void candidate(Candidate item)throws IOException {
            RuntimeFiles.require(candidates.size()<MAX_CANDIDATES,"Too many obsolete runtime objects; no cleanup performed");candidates.add(item);
        }
        void runtime(String key)throws IOException {
            Path store=root.resolve("runtimes").resolve(key);
            if(!Files.exists(store,LinkOption.NOFOLLOW_LINKS))return;
            directory(store);String current=null;
            Path pointer=store.resolve("current");
            if(Files.exists(pointer,LinkOption.NOFOLLOW_LINKS)) {
                String text=RuntimeFiles.smallText(pointer,65);
                RuntimeFiles.require(text.matches("[0-9a-f]{64}\\n"),"Invalid active runtime pointer; storage preserved");current=text.substring(0,64);
            }
            // Interrupted deletes remain in a separate owned trash namespace.
            Path trash=store.resolve(TRASH);
            if(Files.exists(trash,LinkOption.NOFOLLOW_LINKS))for(Path path:children(trash)) {
                String name=path.getFileName().toString();int split=name.indexOf('-');
                if(split<0){unknownItemsPreserved++;continue;}
                String kind=name.substring(0,split),generation=name.substring(split+1);
                Path marker=path.resolve(MARKER);
                if(!Set.of("generations","staging").contains(kind)||!hash(generation)||
                    !Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)||!Files.isRegularFile(marker,LinkOption.NOFOLLOW_LINKS)||
                    !RuntimeFiles.smallText(marker,256).equals(trashOwner(kind,generation))) {unknownItemsPreserved++;continue;}
                candidate(new Candidate(path,store,generation,kind,true,false));obsoleteGenerations++;
            }
            for(String kind:List.of("generations","staging")) {
                Path parent=store.resolve(kind);if(!Files.exists(parent,LinkOption.NOFOLLOW_LINKS))continue;
                for(Path path:children(parent)) {
                    String generation=path.getFileName().toString();
                    if(generation.equals(current)||generation.equals(expected.get(key)))continue;
                    if(!hash(generation)||!owned(path,generation,kind.equals("generations"))) {unknownItemsPreserved++;continue;}
                    candidate(new Candidate(path,store,generation,kind,false,false));obsoleteGenerations++;
                }
            }
            // Only a completed selected installation makes compressed copies
            // redundant. Repeat setup uses this installed-generation fast path.
            if(current!=null&&current.equals(expected.get(key))&&owned(store.resolve("generations").resolve(current),current,true)) {
                Path cache=key.equals("wine-arm64")?root.resolve("runtime-downloads"):
                    root.resolve("runtime-embedded-cache").resolve(key);
                if(Files.exists(cache,LinkOption.NOFOLLOW_LINKS))cache(cache,key.equals("wine-arm64"));
            }
        }
        void cache(Path cache,boolean downloaded)throws IOException {
            for(Path owner:children(cache)) {
                String name=owner.getFileName().toString();
                if(!name.matches("[0-9a-f]{64}\\.owner"))continue;
                String id=name.substring(0,64),pin;
                if(!Files.isRegularFile(owner,LinkOption.NOFOLLOW_LINKS)){unknownItemsPreserved++;continue;}
                pin=RuntimeFiles.smallText(owner,1024);String[] lines=pin.split("\\n",-1);long bytes;
                try {
                    if(lines.length!=5||!lines[4].isEmpty()||!lines[0].equals(downloaded?"esteria-download-v1":"esteria-embedded-archive-v1")||
                        !lines[1].matches("[A-Za-z0-9._-]{1,128}")||Set.of(".","..").contains(lines[1])||!hash(lines[3])||
                        !RuntimeFiles.hashText(pin).equals(id))throw new IllegalArgumentException();
                    bytes=Long.parseLong(lines[2]);if(bytes<=0||bytes>(8L<<30))throw new IllegalArgumentException();
                }catch(IllegalArgumentException invalid){unknownItemsPreserved++;continue;}
                List<Path> group=new ArrayList<>();boolean valid=true;
                for(String suffix:List.of(".archive",".partial",".verified")) {
                    Path file=cache.resolve(id+suffix);if(!Files.exists(file,LinkOption.NOFOLLOW_LINKS))continue;
                    if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)){valid=false;break;}
                    long size=Files.size(file);
                    if((suffix.equals(".archive")&&size!=bytes)||(suffix.equals(".partial")&&size>bytes)){valid=false;break;}
                    if(suffix.equals(".verified")) {
                        String proof=RuntimeFiles.smallText(file,1100);
                        if(!proof.startsWith(pin)||!proof.substring(pin.length()).matches("[0-9]{1,19}\\n")){valid=false;break;}
                    }
                    group.add(file);
                }
                if(!valid){unknownItemsPreserved++;continue;}
                // Keep the owner until last, including after cancellation.
                group.add(owner);for(Path file:group)candidate(new Candidate(file,cache,id,"cache",false,true));cachedArchives++;
            }
        }
        long count(Path path,int depth)throws IOException {
            visit();RuntimeFiles.require(depth<=MAX_DEPTH,"Maintenance tree depth exceeds its bound");BasicFileAttributes info=attributes(path);
            if(info.isRegularFile())return info.size();
            if(info.isSymbolicLink())return 0;
            RuntimeFiles.require(info.isDirectory(),"Unexpected special file in obsolete runtime; preserved");
            long bytes=0;int members=0;
            // Stream the recursive inventory instead of retaining every child
            // path at every depth. Only bounded top-level lists are sorted.
            try(DirectoryStream<Path> children=Files.newDirectoryStream(path)) {
                for(Path child:children){RuntimeFiles.require(++members<=MAX_DIRECTORY_ENTRIES,"Maintenance directory inventory exceeds its bound");bytes=add(bytes,count(child,depth+1));}
            }
            return bytes;
        }
        void remove(Candidate candidate)throws IOException {
            check();unchanged(candidate.path,candidate.identity);
            if(candidate.cache){delete(candidate.path,0);removedItems++;return;}
            Path at=candidate.path;
            String markerText=trashOwner(candidate.kind,candidate.generation);
            if(!candidate.trash) {
                Path pointer=candidate.store.resolve("current");
                if(Files.exists(pointer,LinkOption.NOFOLLOW_LINKS))
                    RuntimeFiles.require(!RuntimeFiles.smallText(pointer,65).equals(candidate.generation+"\n"),"Runtime became active; cleanup stopped");
                RuntimeFiles.require(owned(at,candidate.generation,candidate.kind.equals("generations")),"Runtime ownership changed; cleanup stopped");
                Path marker=at.resolve(MARKER);
                if(Files.exists(marker,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(marker,256).equals(markerText),"Obsolete runtime cleanup marker differs");
                else RuntimeFiles.atomicText(marker,markerText,RuntimeFiles.sync(at));
                Path trash=RuntimeFiles.directory(candidate.store.resolve(TRASH));
                Path destination=trash.resolve(candidate.kind+"-"+candidate.generation);
                RuntimeFiles.require(!Files.exists(destination,LinkOption.NOFOLLOW_LINKS),"Earlier obsolete runtime cleanup remains; retry trim");
                check();Files.move(at,destination,StandardCopyOption.ATOMIC_MOVE);at=destination;
                RuntimeFiles.sync(trash);RuntimeFiles.sync(candidate.path.getParent());
            }
            Path marker=at.resolve(MARKER);
            RuntimeFiles.require(RuntimeFiles.smallText(marker,256).equals(markerText),"Obsolete runtime cleanup marker changed");
            for(Path child:children(at))if(!child.getFileName().toString().equals(MARKER))delete(child,0);
            check();Files.delete(marker);Files.delete(at);removedItems++;
            if(progress!=null)progress.update("trim-runtime-storage",candidate.store.getFileName().toString(),removedBytes,reclaimableBytes);
        }
        void delete(Path path,int depth)throws IOException {
            check();RuntimeFiles.require(depth<=MAX_DEPTH,"Maintenance delete depth exceeds its bound");BasicFileAttributes info=attributes(path);
            RuntimeFiles.require(++deletedEntries<=MAX_ENTRIES,"Maintenance delete inventory exceeds its bound");
            if(info.isDirectory())try(DirectoryStream<Path> children=Files.newDirectoryStream(path)) {
                int members=0;for(Path child:children){RuntimeFiles.require(++members<=MAX_DIRECTORY_ENTRIES,"Maintenance delete directory exceeds its bound");delete(child,depth+1);}
            }
            else RuntimeFiles.require(info.isRegularFile()||info.isSymbolicLink(),"Unexpected special file in obsolete runtime");
            check();unchanged(path,info);Files.delete(path);
            if(info.isRegularFile())removedBytes=add(removedBytes,info.size());
        }
    }
}
