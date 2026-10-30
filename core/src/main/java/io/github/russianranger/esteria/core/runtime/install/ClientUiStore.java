package io.github.russianranger.esteria.core.runtime.install;

import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;

/** Persistent writable loose Interface trees keyed by exact source content, never by client build.
 * No automatic merge/deletion. All prepare/assess/activate operations require a stopped client.
 */
public final class ClientUiStore {
    private static final String OWNER="esteria-client-ui-v1\n";
    private final Path work,store,generations,stages;
    private final boolean sync;
    public static final class Candidate {
        public final String inventoryId,importGeneration;
        public final Path interfaceDirectory;
        public final boolean reused;
        private final String provenanceSha256;
        Candidate(ImportedUiSource source,Path directory,boolean reused){inventoryId=source.inventoryId;importGeneration=source.importGeneration;interfaceDirectory=directory;this.reused=reused;provenanceSha256=RuntimeFiles.hashText(source.provenance);}
    }
    /** An active, owned tree bound to one imported generation; only this store can issue it. */
    public static final class Selection {
        public final String inventoryId,importGeneration;
        public final Path interfaceDirectory;
        private final ClientUiStore owner;
        private final ImportedUiSource source;
        private Selection(ClientUiStore owner,ImportedUiSource source) {
            this.owner=owner;this.source=source;inventoryId=source.inventoryId;importGeneration=source.importGeneration;
            interfaceDirectory=owner.generations.resolve(inventoryId).resolve("Interface");
        }
        String guestPath(){return "/work/client-state/UI/generations/"+inventoryId+"/Interface";}
        void verifySource(Path imported,String generation,RuntimeWork.Cancellation cancelled)throws IOException {verify(owner.work,imported,generation,cancelled);}
        void verify(Path work,Path imported,String generation,RuntimeWork.Cancellation cancelled)throws IOException {
            RuntimeFiles.require(owner.work.equals(work)&&source.dataRoot.equals(imported)&&importGeneration.equals(generation),"UI selection belongs to another work/import generation");
            owner.verifySelection(source,cancelled);
        }
    }
    public static final class Change {
        public final String path,kind;
        Change(String path,String kind){this.path=path;this.kind=kind;}
    }
    public static final class Assessment {
        public final String digest,previousInventory,candidateInventory;
        public final List<Change> previousMutations,candidateMutations,sourceChanges,conflicts;
        public final boolean requiresReview;
        Assessment(String previous,String next,List<Change> oldChanges,List<Change> newChanges,List<Change> sources,List<Change> conflicts,String oldSnapshot,String newSnapshot) {
            previousInventory=previous;candidateInventory=next;
            previousMutations=Collections.unmodifiableList(oldChanges);candidateMutations=Collections.unmodifiableList(newChanges);
            sourceChanges=Collections.unmodifiableList(sources);this.conflicts=Collections.unmodifiableList(conflicts);
            requiresReview=!Objects.equals(previous,next)&&(!oldChanges.isEmpty()||!newChanges.isEmpty());
            digest=RuntimeFiles.hashText("esteria-ui-assessment-v1\n"+(previous==null?"none":previous)+"\n"+next+"\n"+oldSnapshot+"\n"+newSnapshot+"\n");
        }
    }
    public ClientUiStore(Path work)throws IOException {
        this.work=UiFiles.directory(work);
        Path state=UiFiles.owned(work.resolve("client-state"),"esteria-client-state-v1\n");
        store=UiFiles.owned(state.resolve("UI"),OWNER);generations=RuntimeFiles.directory(store.resolve("generations"));stages=RuntimeFiles.directory(store.resolve("staging"));
        sync=RuntimeFiles.sync(store)&&RuntimeFiles.sync(generations)&&RuntimeFiles.sync(stages);
    }
    public Candidate prepare(ImportedUiSource source,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeFiles.require(!source.dataRoot.startsWith(work)&&!work.startsWith(source.dataRoot),"Immutable imported UI must be separate from mutable work");
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(store)) {
            RuntimeWork.check(cancelled);source.verifyMetadata(cancelled);
            Path target=generations.resolve(source.inventoryId);
            if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) {
                validateGeneration(source.inventoryId,cancelled);
                Path provenance=target.resolve("provenance/"+source.importGeneration);
                if(!Files.exists(provenance,LinkOption.NOFOLLOW_LINKS)) {source.verifySource(cancelled);recordProvenance(target,source);}
                else RuntimeFiles.require(RuntimeFiles.smallText(provenance,16384).equals(source.provenance),"Import UI provenance changed; preserved");
                return new Candidate(source,target.resolve("Interface"),true);
            }
            Path stage=UiFiles.owned(stages.resolve(source.inventoryId),OWNER+source.inventoryId+"\n");
            Path baseline=stage.resolve("inventory.tsv");
            if(Files.exists(baseline,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(baseline,UiFiles.MAX_METADATA).equals(source.inventoryText),"Staged UI baseline changed; preserved");
            else RuntimeFiles.atomicText(baseline,source.inventoryText,sync);
            Path ui=RuntimeFiles.directory(stage.resolve("Interface")),partial=RuntimeFiles.directory(stage.resolve("partial"));
            long remaining=0;
            for(Map.Entry<String,UiFiles.Entry> item:source.inventory.entrySet()) {
                Path copied=ui.resolve(item.getKey());
                if(!Files.exists(copied,LinkOption.NOFOLLOW_LINKS)) {
                    Path prior=partial.resolve(RuntimeFiles.hashText(item.getKey()));long present=0;
                    if(Files.exists(prior,LinkOption.NOFOLLOW_LINKS)){UiFiles.privateFile(prior);present=Files.size(prior);}
                    RuntimeFiles.require(present<=item.getValue().bytes,"Owned UI partial is oversized; preserved");remaining+=item.getValue().bytes-present;
                }
            }
            RuntimeFiles.require(store.toFile().getUsableSpace()>=remaining+(64L<<20),"Insufficient storage for preserved writable UI generation");
            for(Map.Entry<String,UiFiles.Entry> item:source.inventory.entrySet()) {
                RuntimeWork.check(cancelled);String name=item.getKey();UiFiles.Entry pin=item.getValue();Path destination=ui.resolve(name);
                RuntimeFiles.directory(destination.getParent());
                if(Files.exists(destination,LinkOption.NOFOLLOW_LINKS)) {
                    UiFiles.privateFile(destination);RuntimeFiles.require(RuntimeFiles.hashFile(destination,pin.bytes,cancelled).equals(pin.sha256),"Staged UI copy changed; preserved");
                } else copy(source.interfaceRoot.resolve(name),destination,partial.resolve(RuntimeFiles.hashText(name)),pin,name,progress,cancelled);
            }
            RuntimeFiles.require(UiFiles.snapshot(ui,cancelled).equals(source.inventory),"Staged UI tree differs from its immutable baseline");
            try(DirectoryStream<Path> leftovers=Files.newDirectoryStream(partial)){RuntimeFiles.require(!leftovers.iterator().hasNext(),"Unexpected UI partial files preserved");}
            source.verifyMetadata(cancelled);recordProvenance(stage,source);RuntimeWork.check(cancelled);
            UiFiles.syncTree(stage,sync);RuntimeFiles.require(!Files.exists(target,LinkOption.NOFOLLOW_LINKS),"UI generation appeared concurrently");
            Files.move(stage,target,StandardCopyOption.ATOMIC_MOVE);
            RuntimeFiles.require(!sync||(RuntimeFiles.sync(generations)&&RuntimeFiles.sync(stages)),"UI publication sync failed");
            progress.update("client-ui-prepared",source.inventoryId,source.bytes,source.bytes);
            return new Candidate(source,target.resolve("Interface"),false);
        }
    }
    public Assessment assess(Candidate candidate,RuntimeWork.Cancellation cancelled)throws IOException {
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(store)){return assessLocked(candidate,cancelled);}
    }
    /** The accepted digest must come from the exact reviewable assessment; stale reports never activate.
     * acceptDivergence is an explicit caller decision, not an inferred approval or automatic merge.
     */
    public Path activate(Candidate candidate,String acceptedDigest,boolean acceptDivergence,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeFiles.hashPin(acceptedDigest);
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(store)) {
            Assessment current=assessLocked(candidate,cancelled);
            RuntimeFiles.require(current.digest.equals(acceptedDigest),"UI changed since assessment; activation requires a fresh report");
            RuntimeFiles.require(!current.requiresReview||acceptDivergence,"UI mutations/update conflicts require explicit reviewed activation");
            RuntimeWork.check(cancelled);RuntimeFiles.atomicText(store.resolve("current"),candidate.inventoryId+"\n",sync);
            return candidate.interfaceDirectory;
        }
    }
    public Path current(RuntimeWork.Cancellation cancelled)throws IOException {
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(store)) {
            String id=currentId();if(id==null)return null;validateGeneration(id,cancelled);return generations.resolve(id).resolve("Interface");
        }
    }
    public Selection selectedFor(ImportedUiSource source,RuntimeWork.Cancellation cancelled)throws IOException {
        verifySelection(source,cancelled);return new Selection(this,source);
    }
    private void verifySelection(ImportedUiSource source,RuntimeWork.Cancellation cancelled)throws IOException {
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(store)) {
            RuntimeFiles.require(source.inventoryId.equals(currentId()),"Requested UI source is not the active reviewed generation");
            source.verifyMetadata(cancelled);validateGeneration(source.inventoryId,cancelled);
            Path provenance=generations.resolve(source.inventoryId).resolve("provenance/"+source.importGeneration);
            RuntimeFiles.require(RuntimeFiles.smallText(provenance,16384).equals(source.provenance),"UI import provenance missing or changed");
        }
    }
    private Assessment assessLocked(Candidate candidate,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeFiles.require(candidate!=null&&candidate.interfaceDirectory.equals(generations.resolve(candidate.inventoryId).resolve("Interface")),"UI candidate belongs to another store");
        String provenance=RuntimeFiles.smallText(generations.resolve(candidate.inventoryId).resolve("provenance/"+candidate.importGeneration),16384);
        RuntimeFiles.require(RuntimeFiles.hashText(provenance).equals(candidate.provenanceSha256),"UI candidate provenance changed; activation blocked");
        SortedMap<String,UiFiles.Entry> next=validateGeneration(candidate.inventoryId,cancelled),nextLive=UiFiles.snapshot(candidate.interfaceDirectory,cancelled);
        String previous=currentId();SortedMap<String,UiFiles.Entry> old=new TreeMap<>(),oldLive=new TreeMap<>();
        if(previous!=null) {old=validateGeneration(previous,cancelled);oldLive=previous.equals(candidate.inventoryId)?nextLive:UiFiles.snapshot(generations.resolve(previous).resolve("Interface"),cancelled);}
        List<Change> oldChanges=changes(old,oldLive),newChanges=changes(next,nextLive),sourceChanges=changes(old,next),conflicts=new ArrayList<>();
        Map<String,UiFiles.Entry> oldFold=fold(old),liveFold=fold(oldLive),nextFold=fold(next);
        for(Change change:oldChanges) {
            String key=change.path.toLowerCase(Locale.ROOT);
            if(!Objects.equals(oldFold.get(key),nextFold.get(key))&&!Objects.equals(liveFold.get(key),nextFold.get(key)))conflicts.add(new Change(change.path,"source-and-local-change"));
        }
        return new Assessment(previous,candidate.inventoryId,oldChanges,newChanges,sourceChanges,conflicts,
            RuntimeFiles.hashText(UiFiles.encode(oldLive)),RuntimeFiles.hashText(UiFiles.encode(nextLive)));
    }
    private SortedMap<String,UiFiles.Entry> validateGeneration(String id,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeFiles.hashPin(id);Path root=UiFiles.directory(generations.resolve(id));
        RuntimeFiles.require(RuntimeFiles.smallText(root.resolve(".owner"),256).equals(OWNER+id+"\n"),"UI generation ownership differs");
        String baseline=RuntimeFiles.smallText(root.resolve("inventory.tsv"),UiFiles.MAX_METADATA);
        RuntimeFiles.require(RuntimeFiles.hashText(baseline).equals(id),"Immutable UI baseline changed; preserved");
        SortedMap<String,UiFiles.Entry> entries=UiFiles.decode(baseline);
        UiFiles.walk(root.resolve("Interface"),cancelled,(name,path,attrs)->UiFiles.privateFile(path));
        return entries;
    }
    private String currentId()throws IOException {
        Path pointer=store.resolve("current");if(!Files.exists(pointer,LinkOption.NOFOLLOW_LINKS))return null;
        String raw=RuntimeFiles.smallText(pointer,65),id=raw.trim();RuntimeFiles.hashPin(id);RuntimeFiles.require(raw.equals(id+"\n"),"Invalid UI active pointer");return id;
    }
    private void recordProvenance(Path root,ImportedUiSource source)throws IOException {
        RuntimeFiles.directory(root.resolve("provenance"));Path target=root.resolve("provenance/"+source.importGeneration);
        if(Files.exists(target,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(target,16384).equals(source.provenance),"UI source provenance changed; preserved");
        else RuntimeFiles.atomicText(target,source.provenance,sync);
    }
    private static Map<String,UiFiles.Entry> fold(Map<String,UiFiles.Entry> input){Map<String,UiFiles.Entry> result=new TreeMap<>();for(Map.Entry<String,UiFiles.Entry> row:input.entrySet())result.put(row.getKey().toLowerCase(Locale.ROOT),row.getValue());return result;}
    private static List<Change> changes(Map<String,UiFiles.Entry> baseline,Map<String,UiFiles.Entry> current) {
        Map<String,UiFiles.Entry> a=fold(baseline),b=fold(current);Map<String,String> aNames=new HashMap<>(),bNames=new HashMap<>();
        for(String name:baseline.keySet())aNames.put(name.toLowerCase(Locale.ROOT),name);
        for(String name:current.keySet())bNames.put(name.toLowerCase(Locale.ROOT),name);
        Set<String> names=new TreeSet<>(a.keySet());names.addAll(b.keySet());List<Change> result=new ArrayList<>();
        for(String name:names)if(!Objects.equals(a.get(name),b.get(name))||!Objects.equals(aNames.get(name),bNames.get(name))) {
            String kind=!a.containsKey(name)?"added":!b.containsKey(name)?"deleted":Objects.equals(a.get(name),b.get(name))?"case-renamed":"modified";
            result.add(new Change(bNames.containsKey(name)?bNames.get(name):aNames.get(name),kind));
        }
        return result;
    }
    private static void copy(Path source,Path target,Path partial,UiFiles.Entry pin,String relative,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancelled)throws IOException {
        RuntimeFiles.plain(source);RuntimeFiles.require(Files.size(source)==pin.bytes,"Imported UI source size differs");
        if(Files.exists(partial,LinkOption.NOFOLLOW_LINKS))UiFiles.privateFile(partial);
        long resume=Files.exists(partial,LinkOption.NOFOLLOW_LINKS)?Files.size(partial):0,total=0;
        RuntimeFiles.require(resume<=pin.bytes,"Owned UI partial is oversized; preserved");MessageDigest hash=RuntimeFiles.digest();byte[] buffer=new byte[RuntimeFiles.BUFFER],old=new byte[RuntimeFiles.BUFFER];
        try(InputStream input=Files.newInputStream(source,LinkOption.NOFOLLOW_LINKS);FileChannel output=FileChannel.open(partial,StandardOpenOption.CREATE,StandardOpenOption.READ,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            RuntimeFiles.privateMode(partial,false,false);
            for(int count;(count=input.read(buffer))!=-1;) {
                RuntimeWork.check(cancelled);RuntimeFiles.require(total+count<=pin.bytes,"Imported UI source grew");hash.update(buffer,0,count);
                int prefix=(int)Math.min(count,Math.max(0,resume-total));
                if(prefix>0) {ByteBuffer existing=ByteBuffer.wrap(old,0,prefix);while(existing.hasRemaining())RuntimeFiles.require(output.read(existing)>0,"Owned UI partial was truncated");for(int i=0;i<prefix;i++)RuntimeFiles.require(old[i]==buffer[i],"Owned UI partial differs; preserved");}
                ByteBuffer remainder=ByteBuffer.wrap(buffer,prefix,count-prefix);while(remainder.hasRemaining())output.write(remainder);
                total+=count;progress.update("client-ui-copy",relative,total,pin.bytes);
            }
            RuntimeFiles.require(total==pin.bytes&&RuntimeFiles.hex(hash.digest()).equals(pin.sha256),"Imported UI source hash differs");output.force(true);
        }
        RuntimeFiles.require(RuntimeFiles.hashFile(partial,pin.bytes,cancelled).equals(pin.sha256),"UI copy readback differs");
        Files.move(partial,target,StandardCopyOption.ATOMIC_MOVE);
    }
}
