package io.github.russianranger.esteria.core.runtime.install;

import java.io.ByteArrayOutputStream;
import java.security.DigestInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.zip.GZIPInputStream;

/** Streaming, resumable GNU tar installation. Published roots are immutable data. */
public final class RuntimeInstaller {
    public static final class Result {
        public final Path rootfs;
        public final String generation;
        public final int reusedFiles;
        public final long copiedBytes;
        public final boolean alreadyInstalled,directorySyncSupported;
        Result(Path rootfs,String generation,int reusedFiles,long copiedBytes,boolean alreadyInstalled,boolean sync){this.rootfs=rootfs;this.generation=generation;this.reusedFiles=reusedFiles;this.copiedBytes=copiedBytes;this.alreadyInstalled=alreadyInstalled;this.directorySyncSupported=sync;}
    }
    private final Path root;
    public final boolean directorySyncSupported;
    public RuntimeInstaller(Path root) throws IOException {
        this.root=RuntimeFiles.directory(root);RuntimeFiles.directory(this.root.resolve("generations"));RuntimeFiles.directory(this.root.resolve("staging"));
        directorySyncSupported=RuntimeFiles.sync(this.root);
    }
    public Path resolveCurrent(RuntimePackagePlan plan) throws IOException {
        Path pointer=root.resolve("current");if(!Files.exists(pointer,LinkOption.NOFOLLOW_LINKS))return null;
        String id=RuntimeFiles.smallText(pointer,65).trim();RuntimeFiles.hashPin(id);
        if(!id.equals(plan.generation))return null;
        Path generation=root.resolve("generations").resolve(id);complete(generation,plan);return generation.resolve("rootfs");
    }
    public Result install(Path archive,RuntimePackagePlan plan,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation) throws IOException {
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(root)) {
            RuntimeWork.check(cancellation);
            Path generation=root.resolve("generations").resolve(plan.generation);
            if(Files.exists(generation,LinkOption.NOFOLLOW_LINKS)) {
                int files=complete(generation,plan);RuntimeWork.check(cancellation);activate(plan);progress.update("runtime-cached",plan.packageId,plan.expectedFileBytes,plan.expectedFileBytes);
                return new Result(generation.resolve("rootfs"),plan.generation,files,0,true,directorySyncSupported);
            }
            RuntimeFiles.plain(archive);RuntimeFiles.require(Files.size(archive)==plan.archiveBytes,"Runtime archive length differs from pin");
            Path staging=root.resolve("staging").resolve(plan.generation);RuntimeFiles.directory(staging);
            Path owner=staging.resolve("owner");String identity="esteria-runtime-stage-v1\n"+plan.generation+"\n";
            if(Files.exists(owner,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(RuntimeFiles.smallText(owner,256).equals(identity),"Runtime stage ownership differs");
            else {
                try(java.nio.file.DirectoryStream<Path> members=Files.newDirectoryStream(staging)){RuntimeFiles.require(!members.iterator().hasNext(),"Unowned runtime stage preserved");}
                RuntimeFiles.atomicText(owner,identity,directorySyncSupported);
            }
            if(Files.exists(staging.resolve("complete"),LinkOption.NOFOLLOW_LINKS)) {
                int files=complete(staging,plan);RuntimeWork.check(cancellation);promote(staging,generation,plan);
                return new Result(generation.resolve("rootfs"),plan.generation,files,0,true,directorySyncSupported);
            }
            Path rootfs=RuntimeFiles.directory(staging.resolve("rootfs")),tmp=RuntimeFiles.directory(staging.resolve("temporary"));
            Budget budget=new Budget(plan.limits.maxMetadataBytes);
            Path journal=staging.resolve("journal.tsv");Map<String,Saved> saved=readJournal(journal,budget,plan);
            RuntimeFiles.require(root.toFile().getUsableSpace()>=remainingBytes(saved,rootfs,plan)+(64L<<20),"Insufficient storage for staged runtime");
            State state=new State(plan,budget,rootfs,tmp,journal,saved,progress,cancellation);
            MessageDigest compressedHash=RuntimeFiles.digest();
            try(InputStream file=Files.newInputStream(archive,LinkOption.NOFOLLOW_LINKS);
                Counted compressed=new Counted(file,plan.archiveBytes,cancellation);
                DigestInputStream hashed=new DigestInputStream(compressed,compressedHash);
                GZIPInputStream gzip=new GZIPInputStream(hashed,RuntimeFiles.BUFFER)) {
                Tar tar=new Tar(gzip,plan,cancellation);
                Header header;while((header=tar.next())!=null)state.member(tar,header);
                // Drain raw bytes too: digest identity covers any compressed tail.
                byte[] tail=new byte[RuntimeFiles.BUFFER];while(hashed.read(tail)!=-1)RuntimeWork.check(cancellation);
                RuntimeFiles.require(compressed.count==plan.archiveBytes&&RuntimeFiles.hex(compressedHash.digest()).equals(plan.archiveSha256),"Runtime archive hash differs from pin");
            }
            RuntimeFiles.require(state.count==plan.expectedEntries&&state.bytes==plan.expectedFileBytes,"Runtime archive inventory differs from pin");
            RuntimeFiles.require(state.found.equals(plan.required.keySet()),"Required runtime components are missing");
            state.inventoryClosure();state.links();verifyRequired(rootfs,plan,cancellation);RuntimeWork.check(cancellation);
            if(directorySyncSupported) {
                for(String parent:state.parents)RuntimeFiles.require(RuntimeFiles.sync(rootfs.resolve(parent)),"Runtime directory sync failed");
                for(Map.Entry<String,Entry> entry:state.entries.entrySet())if(entry.getValue().kind=='d')RuntimeFiles.require(RuntimeFiles.sync(rootfs.resolve(entry.getKey())),"Runtime directory sync failed");
                RuntimeFiles.require(RuntimeFiles.sync(rootfs),"Runtime root sync failed");
            }
            RuntimeFiles.atomicText(staging.resolve("complete"),"format=1\ngeneration="+plan.generation+"\nsourcePin="+plan.sourcePinSha256+"\narchiveSha256="+plan.archiveSha256+"\nentries="+state.count+"\nfileBytes="+state.bytes+"\nfiles="+state.files+"\ndirectorySync="+directorySyncSupported+"\ngameplayQualified=false\n",directorySyncSupported);
            promote(staging,generation,plan);progress.update("runtime-prepared",plan.packageId,state.bytes,plan.expectedFileBytes);
            return new Result(generation.resolve("rootfs"),plan.generation,state.reused,state.copied,false,directorySyncSupported);
        }
    }
    private void activate(RuntimePackagePlan plan)throws IOException{RuntimeFiles.atomicText(root.resolve("current"),plan.generation+"\n",directorySyncSupported);}
    private void promote(Path staging,Path generation,RuntimePackagePlan plan)throws IOException{
        Files.move(staging,generation,StandardCopyOption.ATOMIC_MOVE);
        RuntimeFiles.require(!directorySyncSupported||RuntimeFiles.sync(generation.getParent()),"Runtime generation sync failed");activate(plan);
    }
    private int complete(Path generation,RuntimePackagePlan plan)throws IOException{
        RuntimeFiles.require(Files.isDirectory(generation,LinkOption.NOFOLLOW_LINKS)&&Files.isDirectory(generation.resolve("rootfs"),LinkOption.NOFOLLOW_LINKS),"Runtime generation is incomplete");
        Properties receipt=new Properties();receipt.load(new java.io.StringReader(RuntimeFiles.smallText(generation.resolve("complete"),2048)));
        RuntimeFiles.require("1".equals(receipt.getProperty("format"))&&plan.generation.equals(receipt.getProperty("generation"))&&plan.sourcePinSha256.equals(receipt.getProperty("sourcePin"))&&plan.archiveSha256.equals(receipt.getProperty("archiveSha256"))&&Long.toString(plan.expectedEntries).equals(receipt.getProperty("entries"))&&Long.toString(plan.expectedFileBytes).equals(receipt.getProperty("fileBytes"))&&"false".equals(receipt.getProperty("gameplayQualified")),"Runtime completion receipt differs");
        int files;try{files=Integer.parseInt(receipt.getProperty("files","-1"));}catch(NumberFormatException invalid){throw new IOException("Invalid runtime receipt",invalid);}
        RuntimeFiles.require(files>=plan.required.size()&&files<=plan.expectedEntries,"Invalid runtime file count");
        verifyRequired(generation.resolve("rootfs"),plan,RuntimeWork.NEVER_CANCELLED);
        return files;
    }
    private static void verifyRequired(Path rootfs,RuntimePackagePlan plan,RuntimeWork.Cancellation cancellation)throws IOException{
        for(Map.Entry<String,RuntimePackagePlan.RequiredFile> item:plan.required.entrySet()){
            Path path=rootfs.resolve(item.getKey());RuntimePackagePlan.RequiredFile pin=item.getValue();
            RuntimeFiles.require(RuntimeFiles.hashFile(path,pin.bytes,cancellation).equals(pin.sha256),"Prepared runtime component hash changed: "+item.getKey());
            byte[] head=new byte[(int)Math.min(4096,pin.bytes)];
            try(InputStream input=Files.newInputStream(path,LinkOption.NOFOLLOW_LINKS)){int used=0;while(used<head.length){int count=input.read(head,used,head.length-used);RuntimeFiles.require(count>0,"Prepared component truncated");used+=count;}}
            inspect(head,pin);
        }
    }
    private static long remainingBytes(Map<String,Saved> saved,Path rootfs,RuntimePackagePlan plan)throws IOException{
        long retained=0;for(Map.Entry<String,Saved> entry:saved.entrySet())if(reusable(rootfs.resolve(entry.getKey()),entry.getValue(),entry.getValue().size))retained+=entry.getValue().size;
        return Math.max(0,plan.expectedFileBytes-retained);
    }
    private static final class Budget {
        final long maximum;long used;Budget(long maximum){this.maximum=maximum;}
        void add(long amount)throws IOException{RuntimeFiles.require(amount>=0&&amount<=maximum-used,"Runtime metadata exceeds bounded memory budget");used+=amount;}
    }
    private static final class Saved {final long size,modified;final String hash;Saved(long size,long modified,String hash){this.size=size;this.modified=modified;this.hash=hash;}}
    private static Map<String,Saved> readJournal(Path journal,Budget budget,RuntimePackagePlan plan)throws IOException{
        Map<String,Saved> result=new HashMap<>();if(!Files.exists(journal,LinkOption.NOFOLLOW_LINKS))return result;
        RuntimeFiles.plain(journal);RuntimeFiles.require(Files.size(journal)<=plan.limits.maxMetadataBytes*2,"Runtime resume journal is oversized");
        try(InputStream input=Files.newInputStream(journal,LinkOption.NOFOLLOW_LINKS)){
            ByteArrayOutputStream line=new ByteArrayOutputStream();int value;long position=0,completeBytes=0;
            while((value=input.read())!=-1){
                position++;
                if(value!='\n'){RuntimeFiles.require(line.size()<8192,"Runtime journal line is oversized");line.write(value);continue;}
                completeBytes=position;
                String[] cols=new String(line.toByteArray(),StandardCharsets.UTF_8).split("\t",-1);line.reset();
                RuntimeFiles.require(cols.length==4,"Invalid runtime resume record");
                try{
                    String name=RuntimeFiles.memberPath(utf8(Base64.getDecoder().decode(cols[0])),plan.limits.maxPathBytes);
                    long size=Long.parseLong(cols[1]),modified=Long.parseLong(cols[3]);RuntimeFiles.hashPin(cols[2]);
                    RuntimeFiles.require(size>=0&&size<=plan.limits.maxMemberBytes&&modified>=0,"Invalid runtime resume identity");
                    if(!result.containsKey(name)){budget.add(384L+name.length()*4L);RuntimeFiles.require(result.size()<plan.limits.maxEntries,"Runtime journal entry limit");}
                    result.put(name,new Saved(size,modified,cols[2]));
                }catch(IllegalArgumentException invalid){throw new IOException("Invalid runtime resume record",invalid);}
            }
            // Remove a torn final append before new complete records are appended.
            if(position!=completeBytes)try(FileChannel channel=FileChannel.open(journal,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)){channel.truncate(completeBytes);channel.force(true);}
        }
        return result;
    }
    private static boolean reusable(Path target,Saved saved,long size)throws IOException{
        if(saved==null||saved.size!=size||!Files.isRegularFile(target,LinkOption.NOFOLLOW_LINKS))return false;
        RuntimeFiles.plain(target);return Files.size(target)==size&&Files.getLastModifiedTime(target,LinkOption.NOFOLLOW_LINKS).toMillis()==saved.modified;
    }
    private static final class Entry {final char kind;final String target;final boolean hard;Entry(char kind,String target,boolean hard){this.kind=kind;this.target=target;this.hard=hard;}}
    private final class State {
        final RuntimePackagePlan plan;final Budget budget;final Path rootfs,tmp,journal;final Map<String,Saved> saved;
        final RuntimeWork.Progress progress;final RuntimeWork.Cancellation cancel;
        final Map<String,Entry> entries=new HashMap<>();final Set<String> parents=new HashSet<>(),found=new HashSet<>();
        final byte[] buffer=new byte[RuntimeFiles.BUFFER];
        long count,bytes,copied;int files,reused;
        State(RuntimePackagePlan plan,Budget budget,Path rootfs,Path tmp,Path journal,Map<String,Saved> saved,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancel){this.plan=plan;this.budget=budget;this.rootfs=rootfs;this.tmp=tmp;this.journal=journal;this.saved=saved;this.progress=progress;this.cancel=cancel;}
        void member(Tar tar,Header header)throws IOException{
            RuntimeWork.check(cancel);count++;RuntimeFiles.require(count<=plan.limits.maxEntries,"Too many runtime entries");
            char kind=header.type=='5'?'d':header.type=='1'||header.type=='2'?'l':'f';
            if(header.name.equals(".")||header.name.equals("./")){RuntimeFiles.require(kind=='d'&&header.size==0&&!entries.containsKey(""),"Invalid runtime root entry");entries.put("",new Entry('d',null,false));return;}
            String name=RuntimeFiles.memberPath(header.name,plan.limits.maxPathBytes);
            RuntimeFiles.require(!entries.containsKey(name),"Duplicate runtime member");budget.add(384L+name.length()*4L+header.link.length()*2L);
            for(int slash=name.lastIndexOf('/');slash>=0;slash=name.lastIndexOf('/',slash-1)){
                String parent=name.substring(0,slash);Entry previous=entries.get(parent);RuntimeFiles.require(previous==null||previous.kind=='d',"Runtime member lies beneath a link or file");
                if(parents.add(parent))budget.add(128L+parent.length()*2L);
            }
            RuntimeFiles.require(kind=='d'||!parents.contains(name),"Runtime member replaces an implicit directory");
            RuntimeFiles.require(header.size<=plan.limits.maxMemberBytes&&(kind=='f'||header.size==0),"Invalid runtime member size");
            RuntimeFiles.require(header.size<=plan.limits.maxFileBytes-bytes,"Runtime expanded-byte limit");bytes+=header.size;
            String target=kind=='l'?linkTarget(name,header.link,header.type=='1',plan.limits.maxPathBytes):null;
            entries.put(name,new Entry(kind,target,header.type=='1'));
            RuntimePackagePlan.RequiredFile required=plan.required.get(name);RuntimeFiles.require(required==null||kind=='f',"Required runtime component is not a regular file");
            Path path=rootfs.resolve(name);
            if(kind=='d'){RuntimeFiles.directory(path);return;}
            if(kind=='l')return;
            files++;RuntimeFiles.directory(path.getParent());
            Saved prior=saved.get(name);boolean reuse=reusable(path,prior,header.size);
            Path partial=tmp.resolve("current-file");
            if(!reuse&&Files.exists(partial,LinkOption.NOFOLLOW_LINKS)){RuntimeFiles.plain(partial);Files.delete(partial);}
            FileChannel output=null;MessageDigest hash=RuntimeFiles.digest();byte[] head=new byte[(int)Math.min(4096,header.size)];int headBytes=0;
            long remaining=header.size;
            try{
                if(!reuse){output=FileChannel.open(partial,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE);RuntimeFiles.privateMode(partial,false,false);}
                while(remaining>0){RuntimeWork.check(cancel);int size=(int)Math.min(buffer.length,remaining);tar.readFully(buffer,0,size);hash.update(buffer,0,size);
                    if(headBytes<head.length){int take=Math.min(size,head.length-headBytes);System.arraycopy(buffer,0,head,headBytes,take);headBytes+=take;}
                    if(output!=null){ByteBuffer chunk=ByteBuffer.wrap(buffer,0,size);while(chunk.hasRemaining())output.write(chunk);}
                    remaining-=size;progress.update(reuse?"resume-runtime":"extract-runtime",name,bytes-remaining,plan.expectedFileBytes);
                }
                if(output!=null)output.force(true);
            }finally{if(output!=null)output.close();}
            tar.padding(header.size);String digest=RuntimeFiles.hex(hash.digest());
            if(required!=null){RuntimeFiles.require(required.bytes==header.size&&required.sha256.equals(digest),"Runtime component hash differs: "+name);inspect(head,required);found.add(name);}
            if(reuse){RuntimeFiles.require(prior.hash.equals(digest),"Runtime resume hash differs");reused++;return;}
            if(Files.exists(path,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.plain(path);
            RuntimeFiles.privateMode(partial,false,(header.mode&0111)!=0);Files.move(partial,path,StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING);
            progress.update("verify-runtime",name,bytes,plan.expectedFileBytes);
            RuntimeFiles.require(RuntimeFiles.hashFile(path,header.size,cancel).equals(digest),"Runtime copy readback failed");
            long modified=Files.getLastModifiedTime(path,LinkOption.NOFOLLOW_LINKS).toMillis();
            String record=Base64.getEncoder().encodeToString(name.getBytes(StandardCharsets.UTF_8))+"\t"+header.size+"\t"+digest+"\t"+modified+"\n";
            if(Files.exists(journal,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.plain(journal);
            try(FileChannel channel=FileChannel.open(journal,StandardOpenOption.CREATE,StandardOpenOption.WRITE,StandardOpenOption.APPEND,LinkOption.NOFOLLOW_LINKS)){
                RuntimeFiles.privateMode(journal,false,false);ByteBuffer data=ByteBuffer.wrap(record.getBytes(StandardCharsets.UTF_8));while(data.hasRemaining())channel.write(data);channel.force(true);
            }
            copied+=header.size;progress.update("runtime-file-prepared",name,bytes,plan.expectedFileBytes);
        }
        void inventoryClosure()throws IOException{
            // A prior rejected archive must never contribute extra files to a
            // later valid extraction. Walk without following links, with no
            // second retained inventory, before any staged generation activates.
            Files.walkFileTree(rootfs,new java.nio.file.SimpleFileVisitor<Path>(){
                private void verify(Path path,java.nio.file.attribute.BasicFileAttributes attributes)throws IOException{
                    RuntimeWork.check(cancel);if(path.equals(rootfs))return;
                    String name=rootfs.relativize(path).toString();Entry expected=entries.get(name);
                    if(expected==null)RuntimeFiles.require(attributes.isDirectory()&&parents.contains(name),"Unlisted file in runtime stage; stage preserved for recovery");
                    else if(expected.kind=='d')RuntimeFiles.require(attributes.isDirectory(),"Runtime directory changed during extraction");
                    else if(expected.kind=='f')RuntimeFiles.require(attributes.isRegularFile(),"Runtime file changed during extraction");
                    else RuntimeFiles.require(expected.hard?attributes.isRegularFile():attributes.isSymbolicLink(),"Unexpected existing runtime link type");
                }
                public java.nio.file.FileVisitResult preVisitDirectory(Path path,java.nio.file.attribute.BasicFileAttributes attrs)throws IOException{verify(path,attrs);return java.nio.file.FileVisitResult.CONTINUE;}
                public java.nio.file.FileVisitResult visitFile(Path path,java.nio.file.attribute.BasicFileAttributes attrs)throws IOException{verify(path,attrs);return java.nio.file.FileVisitResult.CONTINUE;}
            });
        }
        void links()throws IOException{
            for(Map.Entry<String,Entry> item:entries.entrySet()){
                RuntimeWork.check(cancel);Entry entry=item.getValue();if(entry.kind!='l')continue;
                Path output=rootfs.resolve(item.getKey()),target=rootfs.resolve(entry.target);RuntimeFiles.directory(output.getParent());
                if(entry.hard){Entry destination=entries.get(entry.target);RuntimeFiles.require(destination!=null&&destination.kind=='f',"Runtime hardlink target is not a regular archive file");RuntimeFiles.plain(target);
                    if(Files.exists(output,LinkOption.NOFOLLOW_LINKS)){RuntimeFiles.plain(output);RuntimeFiles.require(Files.isSameFile(output,target),"Resumed runtime hardlink differs");}else Files.createLink(output,target);
                }else{
                    Path relative=output.getParent().relativize(target);if(relative.toString().isEmpty())relative=Paths.get(".");
                    if(Files.exists(output,LinkOption.NOFOLLOW_LINKS))RuntimeFiles.require(Files.isSymbolicLink(output)&&Files.readSymbolicLink(output).equals(relative),"Resumed runtime symlink differs");
                    else Files.createSymbolicLink(output,relative);
                }
            }
        }
    }
    static String linkTarget(String name,String raw,boolean hard,int maximum)throws IOException{
        RuntimeFiles.require(raw!=null&&!raw.isEmpty()&&raw.getBytes(StandardCharsets.UTF_8).length<=maximum,"Unsafe runtime link target");
        for(int i=0;i<raw.length();i++)RuntimeFiles.require(raw.charAt(i)>=32&&raw.charAt(i)!='\\',"Unsafe runtime link character");
        if(hard)return RuntimeFiles.memberPath(raw,maximum);
        boolean named=false;for(String part:raw.split("/",-1)){if(!part.isEmpty()&&!part.equals(".")&&!part.equals(".."))named=true;RuntimeFiles.require(!part.equals("..")||!named,"Ambiguous parent in runtime link");}
        Path target=raw.startsWith("/")?Paths.get(raw.substring(1)).normalize():Paths.get(name).getParent()==null?Paths.get(raw).normalize():Paths.get(name).getParent().resolve(raw).normalize();
        String normalized=target.toString();RuntimeFiles.require(!target.isAbsolute()&&!normalized.equals("..")&&!normalized.startsWith("../"),"Runtime link escapes root");return normalized;
    }
    private static void inspect(byte[] head,RuntimePackagePlan.RequiredFile pin)throws IOException{
        if(pin.elfMachine!=0)RuntimeFiles.require(head.length>=64&&head[0]==0x7f&&head[1]=='E'&&head[2]=='L'&&head[3]=='F'&&head[4]==2&&head[5]==1&&u16(head,18)==pin.elfMachine,"Runtime ELF architecture differs");
        if(pin.peMachine!=0){RuntimeFiles.require(head.length>=64&&head[0]=='M'&&head[1]=='Z',"Runtime PE header missing");long offset=u32(head,60);RuntimeFiles.require(offset>=64&&offset<=head.length-26,"Runtime PE header bounds");int pos=(int)offset;RuntimeFiles.require(head[pos]=='P'&&head[pos+1]=='E'&&head[pos+2]==0&&head[pos+3]==0&&u16(head,pos+4)==pin.peMachine,"Runtime PE architecture differs");}
    }
    private static int u16(byte[] bytes,int offset){return(bytes[offset]&255)|((bytes[offset+1]&255)<<8);}
    private static long u32(byte[] bytes,int offset){return u16(bytes,offset)|((long)u16(bytes,offset+2)<<16);}
    private static String utf8(byte[] bytes)throws IOException{try{return StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString();}catch(CharacterCodingException bad){throw new IOException("Invalid runtime UTF-8 metadata",bad);}}
    private static final class Counted extends InputStream {
        final InputStream input;final long limit;final RuntimeWork.Cancellation cancel;long count;
        Counted(InputStream input,long limit,RuntimeWork.Cancellation cancel){this.input=input;this.limit=limit;this.cancel=cancel;}
        public int read()throws IOException{byte[] one=new byte[1];int count=read(one,0,1);return count==-1?-1:one[0]&255;}
        public int read(byte[] buffer,int offset,int length)throws IOException{RuntimeWork.check(cancel);int size=input.read(buffer,offset,length);if(size>0){RuntimeFiles.require(size<=limit-count,"Runtime compressed-byte limit");count+=size;}return size;}
        public void close()throws IOException{input.close();}
    }
    private static final class Header {String name,link;long size,mode;char type;}
    private static final class Tar {
        final InputStream input;final RuntimePackagePlan plan;final RuntimeWork.Cancellation cancel;long expanded,headers;String longName,longLink;
        Tar(InputStream input,RuntimePackagePlan plan,RuntimeWork.Cancellation cancel){this.input=input;this.plan=plan;this.cancel=cancel;}
        void readFully(byte[] bytes,int offset,int size)throws IOException{
            int done=0;while(done<size){RuntimeWork.check(cancel);int got=input.read(bytes,offset+done,size-done);RuntimeFiles.require(got>0,"Truncated runtime tar stream");done+=got;expanded+=got;checkLimit();}
        }
        void checkLimit()throws IOException{RuntimeFiles.require(expanded<=plan.limits.maxFileBytes+(long)plan.limits.maxEntries*(2L*plan.limits.maxPathBytes+4096)+10240,"Runtime gzip expanded-byte limit");}
        void padding(long size)throws IOException{int pad=(int)((512-size%512)%512);if(pad>0){byte[] bytes=new byte[pad];readFully(bytes,0,pad);for(byte b:bytes)RuntimeFiles.require(b==0,"Nonzero runtime tar padding");}}
        Header next()throws IOException{
            while(true){byte[] block=new byte[512];readFully(block,0,512);
                boolean zero=true;for(byte b:block)if(b!=0){zero=false;break;}
                if(zero){RuntimeFiles.require(longName==null&&longLink==null,"Orphan GNU runtime header");byte[] end=new byte[512];readFully(end,0,512);for(byte b:end)RuntimeFiles.require(b==0,"Invalid runtime tar end marker");
                    byte[] tail=new byte[RuntimeFiles.BUFFER];int count;while((count=input.read(tail))!=-1){RuntimeWork.check(cancel);expanded+=count;checkLimit();for(int i=0;i<count;i++)RuntimeFiles.require(tail[i]==0,"Unexpected runtime tar trailing data");}return null;}
                headers++;RuntimeFiles.require(headers<=plan.limits.maxEntries*3L,"Runtime tar header limit");long checksum=0;for(int i=0;i<512;i++)checksum+=i>=148&&i<156?32:block[i]&255;RuntimeFiles.require(octal(block,148,8)==checksum,"Runtime tar checksum mismatch");
                boolean gnu=block[257]=='u'&&block[258]=='s'&&block[259]=='t'&&block[260]=='a'&&block[261]=='r'&&block[262]==' ';
                boolean posix=block[257]=='u'&&block[258]=='s'&&block[259]=='t'&&block[260]=='a'&&block[261]=='r'&&block[262]==0;
                RuntimeFiles.require(gnu||posix,"Unsupported runtime tar header format");
                Header header=new Header();header.name=string(block,0,100);header.link=string(block,157,100);header.size=octal(block,124,12);header.mode=octal(block,100,8);header.type=(char)(block[156]&255);if(header.type==0)header.type='0';
                if(posix){String prefix=string(block,345,155);if(!prefix.isEmpty())header.name=prefix+"/"+header.name;}
                if(header.type=='L'||header.type=='K'){
                    RuntimeFiles.require(header.size>0&&header.size<=plan.limits.maxPathBytes+1,"GNU runtime metadata exceeds path limit");byte[] data=new byte[(int)header.size];readFully(data,0,data.length);padding(data.length);
                    RuntimeFiles.require(data[data.length-1]==0,"GNU runtime metadata is unterminated");String value=string(data,0,data.length);
                    if(header.type=='L'){RuntimeFiles.require(longName==null,"Duplicate GNU long name");longName=value;}else{RuntimeFiles.require(longLink==null,"Duplicate GNU long link");longLink=value;}continue;
                }
                RuntimeFiles.require(header.type=='0'||header.type=='1'||header.type=='2'||header.type=='5',"Unsupported runtime tar member (PAX/sparse/special files rejected)");
                if(longName!=null){header.name=longName;longName=null;}if(longLink!=null){header.link=longLink;longLink=null;}return header;
            }
        }
        static String string(byte[] bytes,int offset,int length)throws IOException{int size=0;while(size<length&&bytes[offset+size]!=0)size++;for(int i=size;i<length;i++)RuntimeFiles.require(bytes[offset+i]==0,"Nonzero bytes after runtime metadata terminator");byte[] data=new byte[size];System.arraycopy(bytes,offset,data,0,size);return utf8(data);}
        static long octal(byte[] bytes,int offset,int length)throws IOException{long result=0;boolean ended=false,started=false;for(int i=0;i<length;i++){int b=bytes[offset+i]&255;if(b==0||b==' '){if(started||b==0)ended=true;continue;}RuntimeFiles.require(!ended&&b>='0'&&b<='7'&&result<=Long.MAX_VALUE/8,"Invalid runtime tar numeric field");started=true;result=result*8+b-'0';}return result;}
    }
}
