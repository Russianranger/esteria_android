package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;

/** Transactional storage for fresh server setup. Mutable work paths never move;
 * publishing an active pointer is the only promotion operation. This class checks
 * storage/proof binding, not SQL or gameplay; its caller verifies real receipts. */
public final class FreshServerInstallations {
    private static final Set<String> SOURCE_KEYS=Set.of("sourceLock","runtimeArchive","programsArchive","contentReceipt","compiledModules");
    private static final Set<String> FLAGS=Set.of("baselineComplete","compiledUpdaterComplete","coreLedgersVerified",
        "sameRevisionReentryVerified","localRealmVerified","localAccountVerified","playerbotsSchemaVerified","cleanEngineStopped");
    interface Checkpoint {void reached(String phase) throws IOException;}
    private final Checkpoint checkpoint;
    private final Path root,metadata,workspaces,legacy;
    public FreshServerInstallations(Path applicationRoot) throws IOException {this(applicationRoot,phase->{ });}
    FreshServerInstallations(Path applicationRoot,Checkpoint checkpoint) throws IOException {
        this.checkpoint=checkpoint;
        RuntimeFiles.require(applicationRoot.isAbsolute() && applicationRoot.equals(applicationRoot.toRealPath()) &&
            Files.isDirectory(applicationRoot,LinkOption.NOFOLLOW_LINKS),"Canonical private application storage required");
        root=applicationRoot;metadata=RuntimeFiles.directory(root.resolve("state/server-installations"));
        // Short physical paths are necessary for MySQL's Android UNIX socket.
        workspaces=RuntimeFiles.directory(root.resolve("db"));legacy=root.resolve("state/server-work");
    }
    public static final class Selection {
        private final Map<String,String> values;
        public final String identity;
        public Selection(Map<String,String> hashes) throws IOException {
            RuntimeFiles.require(hashes!=null && hashes.keySet().equals(SOURCE_KEYS),"Exact fresh server source selection required");
            TreeMap<String,String> copy=new TreeMap<>(hashes);
            for(String hash:copy.values())RuntimeFiles.hashPin(hash);
            values=Collections.unmodifiableMap(copy);identity=RuntimeFiles.hashText(encode(copy));
        }
        public Map<String,String> hashes(){return values;}
    }
    /** Receipt fields are produced by a separately qualified coordinator, not
     * inferred from a baseline import or a successful process exit. */
    public static final class PromotionProof {
        private final Map<String,String> values;
        public final String identity;
        public PromotionProof(Selection selection,String mysqlUuid,String mysqlVersion,String serviceOperation,
                String bootstrapReceipt,String stoppedReceipt,String setupReceipt,Map<String,Boolean> completed) throws IOException {
            RuntimeFiles.require(completed!=null && completed.keySet().equals(FLAGS) &&
                completed.values().stream().allMatch(Boolean.TRUE::equals),"Complete source/module/account/realm/bots and clean-stop proof required");
            RuntimeFiles.require(mysqlUuid!=null && mysqlUuid.matches("[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}") &&
                mysqlVersion!=null && mysqlVersion.matches("[0-9]+\\.[0-9]+\\.[0-9]+") &&
                serviceOperation!=null && serviceOperation.matches("[a-f0-9]{32}"),"Invalid fresh database identity");
            for(String hash:Arrays.asList(bootstrapReceipt,stoppedReceipt,setupReceipt))RuntimeFiles.hashPin(hash);
            TreeMap<String,String> proof=new TreeMap<>(selection.values);
            proof.put("mysqlUuid",mysqlUuid);proof.put("mysqlVersion",mysqlVersion);proof.put("serviceOperation",serviceOperation);
            proof.put("bootstrapReceipt",bootstrapReceipt);proof.put("stoppedReceipt",stoppedReceipt);proof.put("setupReceipt",setupReceipt);
            for(String flag:FLAGS)proof.put(flag,"true");
            values=Collections.unmodifiableMap(proof);identity=RuntimeFiles.hashText(encode(proof));
        }
        private PromotionProof(Map<String,String> proof) throws IOException {
            Set<String> expected=new HashSet<>(SOURCE_KEYS);expected.addAll(FLAGS);
            expected.addAll(Set.of("mysqlUuid","mysqlVersion","serviceOperation","bootstrapReceipt","stoppedReceipt","setupReceipt"));
            RuntimeFiles.require(proof.keySet().equals(expected),"Invalid complete setup proof fields");
            Map<String,String> hashes=new TreeMap<>();for(String key:SOURCE_KEYS)hashes.put(key,proof.get(key));
            Map<String,Boolean> flags=new TreeMap<>();for(String key:FLAGS)flags.put(key,"true".equals(proof.get(key)));
            PromotionProof checked=new PromotionProof(new Selection(hashes),proof.get("mysqlUuid"),proof.get("mysqlVersion"),
                proof.get("serviceOperation"),proof.get("bootstrapReceipt"),proof.get("stoppedReceipt"),proof.get("setupReceipt"),flags);
            values=checked.values;identity=checked.identity;
        }
    }
    public static final class Active {
        public final String slotId,mysqlUuid,proofSha256,runtimeArchiveSha256;
        public final Path work;
        private final Path applicationRoot;
        private Active(Path root,String slot,Path work,PromotionProof proof){applicationRoot=root;slotId=slot;this.work=work;mysqlUuid=proof.values.get("mysqlUuid");proofSha256=proof.identity;runtimeArchiveSha256=proof.values.get("runtimeArchive");}
        public Path directoryFor(Path root) throws IOException {
            RuntimeFiles.require(applicationRoot.equals(root) && work.equals(work.toRealPath()) &&
                Files.isDirectory(work,LinkOption.NOFOLLOW_LINKS),"Active workspace belongs to another application or changed");
            return work;
        }
    }
    /** Returns/reconstructs a complete promotion only; never adopts legacy or
     * partial databases. A different source selection preserves and rejects it. */
    public Active active(Selection expected) throws IOException {
        try(RuntimeFiles.Lock lock=RuntimeFiles.lock(metadata)){return recoverActive(expected);}
    }
    public Attempt begin(Selection selection,long requiredFreeBytes) throws IOException {
        RuntimeFiles.require(requiredFreeBytes>0 && requiredFreeBytes<=(32L<<30),"Measured fresh setup reserve required");
        RuntimeFiles.Lock lock=RuntimeFiles.lock(metadata);
        try {
            RuntimeFiles.require(!Files.exists(legacy,LinkOption.NOFOLLOW_LINKS),"Legacy server state preserved; explicit migration is required");
            RuntimeFiles.require(recoverActive(selection)==null,"An active database is already present; fresh initialization refused");
            RuntimeFiles.require(workspaces.toFile().getUsableSpace()>=requiredFreeBytes,"Insufficient storage for a fresh server installation; retained data was not removed");
            Path staging=metadata.resolve("staging");
            if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS)) {
                String abandoned=readPointer(staging);Map<String,String> old=record(abandoned);
                RuntimeFiles.require(old.get("phase").equals("allocated") || old.get("phase").equals("abandoned"),"Unexpected prior setup phase preserved");
                old.put("phase","abandoned");old.put("reason","interrupted");writeRecord(abandoned,old);
                removePointer(staging);
            }
            String id;Path work;
            do {id=UUID.randomUUID().toString().replace("-","").substring(0,16);work=workspaces.resolve(id);}
            while(Files.exists(work,LinkOption.NOFOLLOW_LINKS));
            Files.createDirectory(work);RuntimeFiles.privateMode(work,true,false);
            RuntimeFiles.require(RuntimeFiles.sync(workspaces),"Fresh workspace allocation sync failed");
            String operation=UUID.randomUUID().toString().replace("-","");
            Map<String,String> record=new TreeMap<>();record.put("format","1");record.put("slot",id);record.put("operation",operation);
            record.put("selection",selection.identity);record.put("phase","allocated");record.put("reason","none");record.put("proof","none");
            writeRecord(id,record);RuntimeFiles.atomicText(staging,id+"\n",true);checkpoint.reached("allocated");
            return new Attempt(lock,id,operation,selection,work);
        } catch(IOException|RuntimeException error){lock.close();throw error;}
    }
    public final class Attempt implements AutoCloseable {
        public final String slotId,operationId;
        public final Selection selection;
        private final Path work;
        private final RuntimeFiles.Lock lock;
        private int users;
        private boolean finished,closed;
        private Attempt(RuntimeFiles.Lock lock,String slot,String operation,Selection selection,Path work) {
            this.lock=lock;slotId=slot;operationId=operation;this.selection=selection;this.work=work;
        }
        /** Typed ownership of the one fixed work directory. Retain this token
         * for every setup child/service and release only when its process exits. */
        public synchronized Workspace retainWorkspace() throws IOException {
            check();users++;return new Workspace(this,work);
        }
        private Path applicationRoot(){return root;}
        private void check() throws IOException {
            RuntimeFiles.require(!closed && !finished && lock.lock.isValid(),"Fresh setup attempt is no longer owned");
            RuntimeFiles.require(work.equals(work.toRealPath()) && Files.isDirectory(work,LinkOption.NOFOLLOW_LINKS),"Fresh workspace changed");
        }
        public synchronized void abandon(String reason) throws IOException {
            check();RuntimeFiles.require(users==0,"Owned setup processes must stop before abandoning their workspace");
            RuntimeFiles.require(Set.of("cancelled","failed","interrupted").contains(reason),"Invalid setup abandonment reason");
            Map<String,String> record=record(slotId);
            RuntimeFiles.require(record.get("phase").equals("allocated"),"A complete promotion must be recovered, never abandoned");
            record.put("phase","abandoned");record.put("reason",reason);writeRecord(slotId,record);
            requireStaging(slotId);removePointer(metadata.resolve("staging"));finished=true;
        }
        public synchronized Active promote(PromotionProof proof) throws IOException {
            check();RuntimeFiles.require(users==0,"Owned setup processes must stop before promotion");
            requireSelection(proof,selection);verifyReceipts(work,proof);requireStaging(slotId);
            RuntimeFiles.require(!Files.exists(metadata.resolve("active"),LinkOption.NOFOLLOW_LINKS) &&
                !Files.exists(legacy,LinkOption.NOFOLLOW_LINKS),"Existing database state preserved; promotion refused");
            RuntimeFiles.atomicText(metadata.resolve(slotId+".proof"),encode(proof.values),true);checkpoint.reached("proof-written");
            Map<String,String> record=record(slotId);record.put("phase","ready");record.put("proof",proof.identity);writeRecord(slotId,record);checkpoint.reached("ready-written");
            Active active=publish(slotId,record,proof);finished=true;return active;
        }
        @Override public synchronized void close() throws IOException {
            if(closed)return;
            RuntimeFiles.require(users==0,"Fresh setup still owns live processes; workspace lease retained");
            if(!finished) {
                Map<String,String> record=record(slotId);
                if(Set.of("ready","active").contains(record.get("phase"))) {
                    // Promotion may have become visible before fsync reported
                    // failure. Preserve both records for exact recovery.
                } else if(record.get("phase").equals("abandoned")) {
                    Path staging=metadata.resolve("staging");
                    if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS)){requireStaging(slotId);removePointer(staging);}
                } else abandon("interrupted");
            }
            closed=true;lock.close();
        }
    }
    /** Cannot be constructed from an arbitrary path. */
    public static final class Workspace implements AutoCloseable {
        private final Attempt attempt;
        private final Path directory;
        private boolean closed;
        private Workspace(Attempt attempt,Path directory){this.attempt=attempt;this.directory=directory;}
        public synchronized Path directory() throws IOException {
            RuntimeFiles.require(!closed,"Fresh workspace token was released");
            synchronized(attempt){attempt.check();return directory;}
        }
        public synchronized void requireRuntimeArchive(String archiveSha256) throws IOException {
            RuntimeFiles.require(!closed,"Fresh workspace token was released");
            synchronized(attempt) {
                attempt.check();
                RuntimeFiles.require(attempt.selection.values.get("runtimeArchive").equals(archiveSha256),
                    "Fresh installation requires its selected server runtime archive");
            }
        }
        public synchronized Path directoryFor(Path applicationRoot) throws IOException {
            RuntimeFiles.require(attempt.applicationRoot().equals(applicationRoot),"Fresh workspace belongs to another application root");
            return directory();
        }
        @Override public synchronized void close() {
            if(!closed){synchronized(attempt){attempt.users--;}closed=true;}
        }
    }
    private Active recoverActive(Selection expected) throws IOException {
        Path active=metadata.resolve("active"),staging=metadata.resolve("staging");
        String id=null;
        if(Files.exists(active,LinkOption.NOFOLLOW_LINKS))id=readPointer(active);
        else if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS)) {
            String candidate=readPointer(staging);Map<String,String> record=record(candidate);
            if(record.get("phase").equals("ready"))id=candidate;
        }
        if(id==null)return null;
        RuntimeFiles.require(!Files.exists(legacy,LinkOption.NOFOLLOW_LINKS),"Legacy and slotted state both retained; explicit resolution required");
        Map<String,String> record=record(id);PromotionProof proof=new PromotionProof(decode(metadata.resolve(id+".proof"),16384));
        requireSelection(proof,expected);
        RuntimeFiles.require(record.get("selection").equals(expected.identity) && record.get("proof").equals(proof.identity) &&
            Set.of("ready","active").contains(record.get("phase")),"Active setup binding differs");
        Path work=existingWork(id);verifyReceipts(work,proof);
        if(record.get("phase").equals("active") && !Files.exists(staging,LinkOption.NOFOLLOW_LINKS))
            return new Active(root,id,work,proof);
        return publish(id,record,proof);
    }
    private Active publish(String id,Map<String,String> record,PromotionProof proof) throws IOException {
        Path current=metadata.resolve("active"),staging=metadata.resolve("staging");
        if(Files.exists(current,LinkOption.NOFOLLOW_LINKS))
            RuntimeFiles.require(readPointer(current).equals(id),"Another active installation is preserved");
        if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS))requireStaging(id);
        RuntimeFiles.atomicText(metadata.resolve("active"),id+"\n",true);checkpoint.reached("active-pointer-written");
        record.put("phase","active");record.put("reason","completed");writeRecord(id,record);
        if(Files.exists(staging,LinkOption.NOFOLLOW_LINKS))removePointer(staging);
        return new Active(root,id,existingWork(id),proof);
    }
    private Path existingWork(String id) throws IOException {
        Path work=workspaces.resolve(id);
        RuntimeFiles.require(Files.isDirectory(work,LinkOption.NOFOLLOW_LINKS) && work.equals(work.toRealPath()),"Installation workspace changed");
        return work;
    }
    private static void requireSelection(PromotionProof proof,Selection expected) throws IOException {
        for(String key:SOURCE_KEYS)RuntimeFiles.require(expected.values.get(key).equals(proof.values.get(key)),"Complete setup source selection differs");
    }
    private static void verifyReceipts(Path work,PromotionProof proof) throws IOException {
        Map<String,String> paths=Map.of("bootstrapReceipt","state/database-bootstrap.json","setupReceipt","state/server-setup-complete.json",
            "stoppedReceipt","mysql-sessions/"+proof.values.get("serviceOperation")+"/stopped.json");
        for(Map.Entry<String,String> row:paths.entrySet()) {
            Path path=work.resolve(row.getValue());RuntimeFiles.plain(path);
            RuntimeFiles.require(Files.size(path)>0 && Files.size(path)<=128*1024 &&
                RuntimeFiles.hashFile(path,Files.size(path),RuntimeWork.NEVER_CANCELLED).equals(proof.values.get(row.getKey())),"Complete setup receipt changed");
        }
    }
    private Map<String,String> record(String id) throws IOException {
        RuntimeFiles.require(id.matches("[a-f0-9]{16}"),"Invalid fresh slot identity");
        Map<String,String> result=decode(metadata.resolve(id+".journal"),4096);
        RuntimeFiles.require(result.keySet().equals(Set.of("format","slot","operation","selection","phase","reason","proof")) &&
            result.get("format").equals("1") && result.get("slot").equals(id) && result.get("operation").matches("[a-f0-9]{32}") &&
            result.get("selection").matches("[a-f0-9]{64}") && Set.of("allocated","abandoned","ready","active").contains(result.get("phase")) &&
            Set.of("none","cancelled","failed","interrupted","completed").contains(result.get("reason")) &&
            (result.get("proof").equals("none") || result.get("proof").matches("[a-f0-9]{64}")),"Invalid fresh setup journal");
        return result;
    }
    private void writeRecord(String id,Map<String,String> record) throws IOException {RuntimeFiles.atomicText(metadata.resolve(id+".journal"),encode(record),true);}
    private String readPointer(Path path) throws IOException {
        String value=RuntimeFiles.smallText(path,64);RuntimeFiles.require(value.matches("[a-f0-9]{16}\\n"),"Invalid installation pointer");return value.trim();
    }
    private void requireStaging(String id) throws IOException {RuntimeFiles.require(readPointer(metadata.resolve("staging")).equals(id),"Fresh setup ownership pointer changed");}
    private void removePointer(Path path) throws IOException {Files.delete(path);RuntimeFiles.require(RuntimeFiles.sync(metadata),"Installation pointer removal sync failed");}
    private static Map<String,String> decode(Path path,int bound) throws IOException {
        String value=RuntimeFiles.smallText(path,bound);Map<String,String> result=new TreeMap<>();
        for(String line:value.split("\n",-1)) {
            if(line.isEmpty())continue;String[] pair=line.split("=",-1);
            RuntimeFiles.require(pair.length==2 && pair[0].matches("[A-Za-z][A-Za-z0-9]*") && pair[1].matches("[A-Za-z0-9.-]+") &&
                result.put(pair[0],pair[1])==null,"Invalid or duplicate installation metadata");
        }
        RuntimeFiles.require(encode(result).equals(value),"Noncanonical installation metadata");return result;
    }
    private static String encode(Map<String,String> values) {
        StringBuilder text=new StringBuilder();new TreeMap<>(values).forEach((key,value)->text.append(key).append('=').append(value).append('\n'));return text.toString();
    }
}
