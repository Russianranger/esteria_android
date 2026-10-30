package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.*;

/** Mutable executable view; absolute symbolic links are guest paths and must never be followed on the host.
 * Call only while the client is stopped. PRoot bindings are conventions, not a same-UID security boundary.
 */
public final class ClientLaunchView {
    private static final String OWNER="esteria-client-launch-v1\n", STATE_OWNER="esteria-client-state-v1\n";
    private static final int MAX_ENTRIES=8192, MAX_DEPTH=32;
    private static final String[] BINARIES={"WowClient64.exe","XvidDecoder.dll"};
    private static final String[] STATE={"WTF","Cache","Logs","Screenshots"};
    private static final String LOCAL_REALM="SET realmList \"127.0.0.1:3724\"\nSET realmListbn \"\"\nSET portal \"\"\nSET serverAlert \"\"\n";
    private static final Set<String> LOCALES=new HashSet<>(Arrays.asList("enus","engb","kokr","frfr","dede","zhcn","zhtw","eses","esmx","ruru"));
    private final Path work, launches, stages, state;
    private final boolean sync;

    public static final class Plan {
        public final String clientGeneration, importedGeneration, generation;
        public final List<String> deferredLooseTrees;
        private final Path clientRoot, importedRoot;
        private final ClientUiStore.Selection ui;
        private final Map<String,RuntimePackagePlan.RequiredFile> binaries=new TreeMap<>();
        private final SortedMap<String,String> links=new TreeMap<>();
        private final SortedSet<String> directories=new TreeSet<>(), configuration=new TreeSet<>();
        public Plan(Path clientRoot, RuntimePackagePlan client, Path importedRoot, String importedGeneration) throws IOException {
            this(clientRoot,client,importedRoot,importedGeneration,null);
        }
        public Plan(Path clientRoot, RuntimePackagePlan client, Path importedRoot, String importedGeneration,ClientUiStore.Selection ui) throws IOException {
            this.ui=ui;
            this.clientRoot=existingDirectory(clientRoot);this.importedRoot=existingDirectory(importedRoot);
            RuntimeFiles.require(client.packageId.equals("client-arm64"),"Expected reconstructed ARM64 client provider");
            RuntimeFiles.hashPin(importedGeneration);this.importedGeneration=importedGeneration;clientGeneration=client.generation;
            for(String name:BINARIES) {
                RuntimePackagePlan.RequiredFile pin=client.required.get("bin/"+name);
                RuntimeFiles.require(pin!=null&&pin.peMachine==0xaa64&&pin.elfMachine==0&&pin.bytes>=88,"Missing ARM64 client companion pin");
                binaries.put(name,pin);RuntimeFiles.plain(this.clientRoot.resolve("bin/"+name));
            }
            Map<String,Path> rootEntries=new TreeMap<>();
            try(DirectoryStream<Path> entries=Files.newDirectoryStream(this.importedRoot)) {
                int count=0;
                for(Path path:entries) {
                    RuntimeFiles.require(++count<=MAX_ENTRIES,"Imported root inventory exceeds launch-view bound");
                    String name=path.getFileName().toString();safeRelative(name);
                    BasicFileAttributes attributes=Files.readAttributes(path,BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
                    RuntimeFiles.require(!attributes.isSymbolicLink()&&(attributes.isDirectory()||attributes.isRegularFile()),"Imported root contains a link or special file");
                    RuntimeFiles.require(rootEntries.put(name.toLowerCase(Locale.ROOT),path)==null,"Imported root has case-colliding paths");
                }
            }
            List<String> deferred=new ArrayList<>();
            if(rootEntries.containsKey("interface")) {
                existingDirectory(rootEntries.get("interface"));if(ui==null)deferred.add("Interface");
            }
            deferredLooseTrees=Collections.unmodifiableList(new ArrayList<>(deferred));
            Set<String> folded=new HashSet<>();final int[] count={0};
            for(String tree:Arrays.asList("Data","Fonts")) {
            Path sourceTree=rootEntries.get(tree.toLowerCase(Locale.ROOT));
            if(tree.equals("Fonts")&&sourceTree==null)continue;
            Path data=existingDirectory(sourceTree);directories.add(tree);
            Files.walkFileTree(data,EnumSet.noneOf(FileVisitOption.class),MAX_DEPTH,new SimpleFileVisitor<Path>() {
                private String checked(Path path,BasicFileAttributes attrs)throws IOException {
                    if(path.equals(data))return tree;
                    RuntimeFiles.require(++count[0]<=MAX_ENTRIES,"Imported data inventory exceeds launch-view bound");
                    String relative=data.relativize(path).toString();safeRelative(relative);
                    String name=tree+"/"+relative;
                    RuntimeFiles.require(folded.add(name.toLowerCase(Locale.ROOT)),"Imported data has case-colliding paths");
                    RuntimeFiles.require(!attrs.isSymbolicLink()&&(attrs.isDirectory()||attrs.isRegularFile()),"Imported data contains a link or special file");
                    return name;
                }
                public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attrs)throws IOException {
                    String name=checked(path,attrs);directories.add(name);return FileVisitResult.CONTINUE;
                }
                public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException {
                    String name=checked(path,attrs);
                    RuntimeFiles.require(attrs.isRegularFile(),"Imported data depth exceeds launch-view bound");
                    if(!tree.equals("Data")||!realmFile(path.getFileName().toString()))links.put(name,"/esteria-data/"+data.getFileName()+"/"+data.relativize(path));
                    return FileVisitResult.CONTINUE;
                }
            });
            }
            configuration.add("realmlist.wtf");configuration.add("realmlistbn.wtf");
            for(String directory:directories) {
                String[] parts=directory.split("/");
                if(parts.length==2&&parts[0].equals("Data")&&LOCALES.contains(parts[1].toLowerCase(Locale.ROOT))) {
                    configuration.add(directory+"/realmlist.wtf");configuration.add(directory+"/realmlistbn.wtf");
                }
            }
            for(Path path:rootEntries.values()) {
                String name=path.getFileName().toString();
                if(name.matches("(?i)Esteria[A-Za-z0-9_.-]*\\.bin")) {
                    RuntimeFiles.plain(path);
                    RuntimeFiles.require(folded.add(name.toLowerCase(Locale.ROOT)),"Imported catalog case collision");
                    links.put(name,"/esteria-data/"+name);
                }
            }
            for(String name:STATE)links.put(name,"/work/client-state/"+name);
            if(ui!=null) {
                ui.verifySource(this.importedRoot,importedGeneration,RuntimeWork.NEVER_CANCELLED);
                links.put("Interface",ui.guestPath());
            }
            // The reconstructed desktop I/O still uses MAX_PATH buffers. Include
            // the full fixed guest/Windows executable directory in this bound.
            for(Collection<String> paths:Arrays.asList(directories,links.keySet(),configuration))
                for(String name:paths)RuntimeFiles.require(80+name.length()<260,"Launch view exceeds Windows MAX_PATH");
            StringBuilder id=new StringBuilder(OWNER).append(clientGeneration).append('\n').append(importedGeneration).append('\n').append(LOCAL_REALM);
            for(String directory:directories)id.append("d\t").append(directory).append('\n');
            for(Map.Entry<String,String> link:links.entrySet())id.append("l\t").append(link.getKey()).append('\t').append(link.getValue()).append('\n');
            generation=RuntimeFiles.hashText(id.toString());
        }
        public String guestDirectory(){return "/work/launch/"+generation;}
        public String windowsExecutable(){return "Z:"+guestDirectory().replace('/','\\')+"\\WowClient64.exe";}
        public void requireSupportedLooseContent()throws IOException {
            RuntimeFiles.require(deferredLooseTrees.isEmpty(),"Loose Interface content requires a preserving writable-copy policy before gameplay launch");
        }
        public List<String> arguments()throws IOException {
            requireSupportedLooseContent();
            if(ui!=null)ui.verifySource(importedRoot,importedGeneration,RuntimeWork.NEVER_CANCELLED);
            return Collections.unmodifiableList(Arrays.asList("-datadir","Z:"+guestDirectory().replace('/','\\'),"-vulkan"));
        }
        public Map<String,String> environment(){return Collections.singletonMap("GX_VULKAN_SHADERS","Z:\\esteria-shaders");}
    }
    public static final class Result {
        public final Path directory;public final String generation;public final int reusedExecutables;public final boolean alreadyPrepared,directorySyncSupported;
        Result(Path directory,String generation,int reused,boolean prepared,boolean sync){this.directory=directory;this.generation=generation;reusedExecutables=reused;alreadyPrepared=prepared;directorySyncSupported=sync;}
    }
    public ClientLaunchView(Path work)throws IOException {
        this.work=existingDirectory(work);
        launches=ownedDirectory(work.resolve("launch"),OWNER);stages=ownedDirectory(work.resolve("launch-staging"),OWNER);
        state=ownedDirectory(work.resolve("client-state"),STATE_OWNER);
        for(String name:STATE)RuntimeFiles.directory(state.resolve(name));
        sync=RuntimeFiles.sync(launches)&&RuntimeFiles.sync(stages)&&RuntimeFiles.sync(state);
    }
    public Result prepare(Plan plan,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
        RuntimeFiles.require(!overlap(work,plan.clientRoot)&&!overlap(work,plan.importedRoot)&&!overlap(plan.clientRoot,plan.importedRoot),"Client providers/imported data must be separate from mutable work");
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(launches)) {
            RuntimeWork.check(cancellation);validateState();
            if(plan.ui!=null)plan.ui.verify(work,plan.importedRoot,plan.importedGeneration,cancellation);
            Path target=launches.resolve(plan.generation),stage=stages.resolve(plan.generation);
            if(Files.exists(target,LinkOption.NOFOLLOW_LINKS)) {validateView(target,plan,cancellation);return new Result(target,plan.generation,2,true,sync);}
            stage=ownedDirectory(stage,OWNER+plan.generation+"\n");
            int reused=0;
            for(String name:BINARIES) {
                RuntimeWork.check(cancellation);Path copied=stage.resolve(name);
                if(Files.exists(copied,LinkOption.NOFOLLOW_LINKS)) {verifyPe(copied,plan.binaries.get(name),name,cancellation);reused++;}
                else copyPe(plan.clientRoot.resolve("bin/"+name),copied,plan.binaries.get(name),name,progress,cancellation);
            }
            for(String name:plan.directories)RuntimeFiles.directory(stage.resolve(name));
            for(Map.Entry<String,String> link:plan.links.entrySet()) {
                RuntimeWork.check(cancellation);Path destination=stage.resolve(link.getKey());RuntimeFiles.directory(destination.getParent());
                Path guest=Paths.get(link.getValue());
                if(Files.exists(destination,LinkOption.NOFOLLOW_LINKS))requireLink(destination,guest);
                else Files.createSymbolicLink(destination,guest);
            }
            for(String name:plan.configuration) {
                Path config=stage.resolve(name);
                if(Files.exists(config,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(config,1024).equals(LOCAL_REALM),"Owned local realm configuration changed; preserved");
                else RuntimeFiles.atomicText(config,LOCAL_REALM,sync);
            }
            validateView(stage,plan,cancellation);RuntimeWork.check(cancellation);
            RuntimeFiles.require(!Files.exists(target,LinkOption.NOFOLLOW_LINKS),"Launch generation appeared concurrently");
            if(sync)syncTreeDirectories(stage);
            Files.move(stage,target,StandardCopyOption.ATOMIC_MOVE);
            RuntimeFiles.require(!sync||(RuntimeFiles.sync(launches)&&RuntimeFiles.sync(stages)),"Launch publication directory sync failed");
            progress.update("client-view-prepared",plan.generation,2,2);
            return new Result(target,plan.generation,reused,false,sync);
        }
    }
    private void validateState()throws IOException {
        RuntimeFiles.require(RuntimeFiles.smallText(state.resolve(".owner"),128).equals(STATE_OWNER),"Client state ownership changed");
        for(String name:STATE)existingDirectory(state.resolve(name));
    }
    private static void validateView(Path view,Plan plan,RuntimeWork.Cancellation cancellation)throws IOException {
        existingDirectory(view);RuntimeFiles.require(RuntimeFiles.smallText(view.resolve(".owner"),256).equals(OWNER+plan.generation+"\n"),"Launch view ownership differs");
        RuntimeFiles.require(!Files.exists(view.resolve("EsteriaOff.txt"),LinkOption.NOFOLLOW_LINKS),"EsteriaOff.txt is not allowed in the managed launch view");
        for(String name:BINARIES)verifyPe(view.resolve(name),plan.binaries.get(name),name,cancellation);
        for(String name:plan.directories)existingDirectory(view.resolve(name));
        for(Map.Entry<String,String> link:plan.links.entrySet())requireLink(view.resolve(link.getKey()),Paths.get(link.getValue()));
        for(String name:plan.configuration)RuntimeFiles.require(RuntimeFiles.smallText(view.resolve(name),1024).equals(LOCAL_REALM),"Local realm configuration changed; preserved");
        final int[] count={0};final Set<String> folded=new HashSet<>();
        Files.walkFileTree(view,EnumSet.noneOf(FileVisitOption.class),MAX_DEPTH+4,new SimpleFileVisitor<Path>() {
            public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attributes)throws IOException {
                RuntimeWork.check(cancellation);RuntimeFiles.require(++count[0]<=MAX_ENTRIES+128,"Launch view inventory exceeds bound");
                RuntimeFiles.require(folded.add(view.relativize(path).toString().toLowerCase(Locale.ROOT)),"Case-colliding launch view paths");return FileVisitResult.CONTINUE;
            }
            public FileVisitResult visitFile(Path path,BasicFileAttributes attributes)throws IOException {
                RuntimeWork.check(cancellation);RuntimeFiles.require(++count[0]<=MAX_ENTRIES+128,"Launch view inventory exceeds bound");
                String relative=view.relativize(path).toString();
                RuntimeFiles.require(folded.add(relative.toLowerCase(Locale.ROOT)),"Case-colliding launch view paths");
                RuntimeFiles.require(!realmFile(path.getFileName().toString())||plan.configuration.contains(relative),"Unmanaged realm configuration in launch view");
                RuntimeFiles.require(!relative.equalsIgnoreCase("EsteriaOff.txt")&&!relative.endsWith(".partial"),"Unexpected disabled-feature marker or incomplete copy in view");
                if(attributes.isSymbolicLink())RuntimeFiles.require(plan.links.containsKey(relative),"Unexpected host link in launch view");
                else RuntimeFiles.require(attributes.isRegularFile(),"Unexpected launch view file type");
                return FileVisitResult.CONTINUE;
            }
        });
    }
    private static void copyPe(Path source,Path output,RuntimePackagePlan.RequiredFile pin,String name,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
        RuntimeFiles.plain(source);RuntimeFiles.require(Files.size(source)==pin.bytes,"Client source size differs");
        Path partial=output.resolveSibling("."+name+".partial");
        if(Files.exists(partial,LinkOption.NOFOLLOW_LINKS))privateRegular(partial);
        long resume=Files.exists(partial,LinkOption.NOFOLLOW_LINKS)?Files.size(partial):0;
        RuntimeFiles.require(resume<=pin.bytes,"Owned executable partial is oversized; preserved");
        MessageDigest hash=RuntimeFiles.digest();byte[] buffer=new byte[RuntimeFiles.BUFFER],old=new byte[RuntimeFiles.BUFFER];long total=0;
        try(InputStream input=Files.newInputStream(source,LinkOption.NOFOLLOW_LINKS);
            FileChannel saved=FileChannel.open(partial,StandardOpenOption.CREATE,StandardOpenOption.READ,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
            RuntimeFiles.privateMode(partial,false,false);
            for(int amount;(amount=input.read(buffer))!=-1;) {
                RuntimeWork.check(cancellation);RuntimeFiles.require(total+amount<=pin.bytes,"Client source grew");hash.update(buffer,0,amount);
                int prefix=(int)Math.min(amount,Math.max(0,resume-total));
                if(prefix>0) {
                    ByteBuffer prior=ByteBuffer.wrap(old,0,prefix);while(prior.hasRemaining())RuntimeFiles.require(saved.read(prior)>0,"Client partial was truncated");
                    for(int i=0;i<prefix;i++)RuntimeFiles.require(old[i]==buffer[i],"Client partial differs; preserved");
                }
                ByteBuffer remainder=ByteBuffer.wrap(buffer,prefix,amount-prefix);while(remainder.hasRemaining())saved.write(remainder);
                total+=amount;progress.update("client-view-copy",name,total,pin.bytes);
            }
            RuntimeFiles.require(total==pin.bytes&&RuntimeFiles.hex(hash.digest()).equals(pin.sha256),"Client source hash differs");saved.force(true);
        }
        verifyPe(partial,pin,name,cancellation);Files.move(partial,output,StandardCopyOption.ATOMIC_MOVE);
    }
    private static void verifyPe(Path file,RuntimePackagePlan.RequiredFile pin,String name,RuntimeWork.Cancellation cancellation)throws IOException {
        privateRegular(file);RuntimeFiles.require(RuntimeFiles.hashFile(file,pin.bytes,cancellation).equals(pin.sha256),"Copied client executable hash differs");
        try(FileChannel channel=FileChannel.open(file,StandardOpenOption.READ,LinkOption.NOFOLLOW_LINKS)) {
            ByteBuffer dos=ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);while(dos.hasRemaining())RuntimeFiles.require(channel.read(dos)>0,"Truncated DOS header");
            RuntimeFiles.require(dos.getShort(0)==0x5a4d,"Missing PE DOS signature");long offset=Integer.toUnsignedLong(dos.getInt(60));
            RuntimeFiles.require(offset>=64&&offset<=pin.bytes-26,"Invalid PE header position");channel.position(offset);
            ByteBuffer pe=ByteBuffer.allocate(26).order(ByteOrder.LITTLE_ENDIAN);while(pe.hasRemaining())RuntimeFiles.require(channel.read(pe)>0,"Truncated PE header");
            int flags=Short.toUnsignedInt(pe.getShort(22));
            RuntimeFiles.require(pe.getInt(0)==0x4550&&Short.toUnsignedInt(pe.getShort(4))==0xaa64&&Short.toUnsignedInt(pe.getShort(24))==0x20b&&
                (flags&2)!=0&&((flags&0x2000)!=0)==name.endsWith(".dll"),"Client companion PE architecture/type differs");
        }
    }
    private static void privateRegular(Path path)throws IOException {
        RuntimeFiles.plain(path);
        try{RuntimeFiles.require(((Number)Files.getAttribute(path,"unix:nlink",LinkOption.NOFOLLOW_LINKS)).longValue()==1,"Shared executable file rejected");}
        catch(UnsupportedOperationException unsupported){/* Android may not expose unix:nlink; private copies are never linked by this class. */}
    }
    private static Path ownedDirectory(Path path,String owner)throws IOException {
        Path dir=RuntimeFiles.directory(path),marker=dir.resolve(".owner");
        if(Files.exists(marker,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(marker,256).equals(owner),"Directory ownership differs; preserved");
        else {
            try(DirectoryStream<Path> members=Files.newDirectoryStream(dir)){RuntimeFiles.require(!members.iterator().hasNext(),"Unowned launch/state directory preserved");}
            RuntimeFiles.atomicText(marker,owner,RuntimeFiles.sync(dir));
        }
        return dir;
    }
    private static Path existingDirectory(Path path)throws IOException {
        RuntimeFiles.require(path!=null&&path.isAbsolute()&&path.normalize().equals(path)&&Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS)&&path.toRealPath().equals(path),"Expected canonical existing client directory");return path;
    }
    private static void requireLink(Path path,Path target)throws IOException {
        RuntimeFiles.require(Files.isSymbolicLink(path)&&Files.readSymbolicLink(path).equals(target),"Managed guest link changed; preserved");
    }
    private static boolean overlap(Path a,Path b){return a.startsWith(b)||b.startsWith(a);}
    private static boolean realmFile(String name){return name.equalsIgnoreCase("realmlist.wtf")||name.equalsIgnoreCase("realmlistbn.wtf");}
    private static void safeRelative(String path)throws IOException {
        RuntimeFiles.require(path.length()<=240,"Imported path exceeds client Windows path bound");
        for(String part:path.split("/",-1)) {
            RuntimeFiles.require(!part.isEmpty()&&!part.equals(".")&&!part.equals("..")&&!part.endsWith(".")&&!part.endsWith(" ")&&part.matches("[A-Za-z0-9_. ()@+-]+"),"Unsupported imported Windows filename");
            String base=part.split("\\.",2)[0].toUpperCase(Locale.ROOT);
            RuntimeFiles.require(!base.matches("CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]"),"Reserved Windows filename in imported data");
        }
    }
    private static void syncTreeDirectories(Path root)throws IOException {
        Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
            public FileVisitResult postVisitDirectory(Path path,IOException error)throws IOException {
                if(error!=null)throw error;RuntimeFiles.require(RuntimeFiles.sync(path),"Launch directory sync failed");return FileVisitResult.CONTINUE;
            }
        });
    }
}
