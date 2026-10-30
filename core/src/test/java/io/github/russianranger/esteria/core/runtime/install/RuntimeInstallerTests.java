package io.github.russianranger.esteria.core.runtime.install;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.GZIPOutputStream;

/** Real file/stream tests; synthetic rootfs data is not gameplay qualification. */
public final class RuntimeInstallerTests {
    interface Test {void run()throws Exception;}
    private static int passed;
    private static Path temporaryRoot;
    private static final RuntimePackagePlan.Limits LIMITS=new RuntimePackagePlan.Limits(50000,128L<<20,256L<<20,4096,32L<<20);
    private static final URI URI_PIN=URI.create("https://example.invalid/runtime.tar.gz");
    public static void main(String[] args)throws Exception{
        passed=0;
        temporaryRoot=args.length==0?null:java.nio.file.Paths.get(args[0]).toRealPath();
        run("atomic install, safe guest links and cached repeat",RuntimeInstallerTests::installation);
        run("client-only APK source changes reuse unchanged server component generations",RuntimeInstallerTests::serverGeneration);
        run("denied hardlinks use verified resumable immutable copies",RuntimeInstallerTests::hardlinkCopy);
        run("cancel and resume verified files without activation",RuntimeInstallerTests::resume);
        run("torn resume journal and changed staged file recover",RuntimeInstallerTests::journalRecovery);
        run("failed update preserves active runtime and unrelated saves",RuntimeInstallerTests::failedUpdate);
        run("generation promotion interruption recovers",RuntimeInstallerTests::promotionRecovery);
        run("rejected archive residue cannot enter a later generation",RuntimeInstallerTests::rejectedResidue);
        run("same-size modified required binaries fail cached verification",RuntimeInstallerTests::requiredTamper);
        run("unsafe paths, duplicate names and link ancestors rejected",RuntimeInstallerTests::unsafePaths);
        run("escaping links, hardlink chains and special members rejected",RuntimeInstallerTests::unsafeLinks);
        run("GNU long names work and metadata budgets are bounded",RuntimeInstallerTests::longNamesAndLimits);
        run("tar checksum, gzip CRC and archive/component identities checked",RuntimeInstallerTests::corruption);
        run("concurrent setup cannot overwrite the owner",RuntimeInstallerTests::concurrency);
        run("64 MiB file streams with bounded heap",RuntimeInstallerTests::streaming);
        run("interrupted HTTP download resumes exact pinned bytes",RuntimeInstallerTests::downloadResume);
        run("range mismatch preserves partial and ignored range restarts",RuntimeInstallerTests::downloadRange);
        run("download cancellation resumes and cached repeat avoids network",RuntimeInstallerTests::downloadCancel);
        run("bad downloads and symlink caches preserve existing data",RuntimeInstallerTests::downloadSafety);
        System.out.println("Runtime installer tests passed: "+passed);
    }
    static void run(String name,Test test)throws Exception{test.run();passed++;System.out.println("PASS "+name);}
    static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    static void fail(Test test)throws Exception{try{test.run();}catch(IOException expected){return;}throw new AssertionError("Expected IOException");}
    static Path temp()throws IOException{return (temporaryRoot==null?Files.createTempDirectory("esteria-runtime-test-"):Files.createTempDirectory(temporaryRoot,"runtime-test-")).toRealPath();}
    static byte[] bytes(String text){return text.getBytes(StandardCharsets.UTF_8);}
    static String sha(byte[] data){return RuntimeFiles.hex(RuntimeFiles.digest().digest(data));}
    static final class Member {
        String name,link="";char type='0';byte[] data;long length;int mode=0644;
        Member(String name,String data){this.name=name;this.data=bytes(data);this.length=this.data.length;}
        Member link(char type,String target){this.type=type;link=target;data=new byte[0];length=0;return this;}
    }
    static Member file(String name,String value){return new Member(name,value);}
    static List<Member> base(){return Arrays.asList(file("usr/bin/tool","executable-data"),file("etc/marker","version-one"),new Member("tool-link","").link('2',"/usr/bin/tool"),new Member("tool-hard","").link('1',"usr/bin/tool"),new Member("usr/bin/X11","").link('2',"."));}
    static Path tar(Path root,List<Member> members)throws IOException{
        Path path=Files.createTempFile(root,"archive-",".tar.gz");
        try(OutputStream file=Files.newOutputStream(path);GZIPOutputStream out=new GZIPOutputStream(file)){
            for(Member member:members){
                if(bytes(member.name).length>100){byte[] full=Arrays.copyOf(bytes(member.name),bytes(member.name).length+1);writeHeader(out,"././@LongLink",'L',full.length,"",0644);out.write(full);pad(out,full.length);}
                writeHeader(out,member.name.length()>100?member.name.substring(0,100):member.name,member.type,member.length,member.link,member.mode);
                if(member.data!=null)out.write(member.data);else{byte[] buffer=new byte[65536];Arrays.fill(buffer,(byte)73);for(long left=member.length;left>0;left-=Math.min(left,buffer.length))out.write(buffer,0,(int)Math.min(left,buffer.length));}
                pad(out,member.length);
            }
            out.write(new byte[1024]);
        }return path;
    }
    static void put(byte[] header,int offset,int length,String value){byte[] content=bytes(value);System.arraycopy(content,0,header,offset,Math.min(length,content.length));}
    static void octal(byte[] header,int offset,int length,long value){put(header,offset,length,String.format(java.util.Locale.ROOT,"%0"+(length-1)+"o",value));}
    static void writeHeader(OutputStream out,String name,char type,long size,String link,int mode)throws IOException{
        byte[] header=new byte[512];put(header,0,100,name);octal(header,100,8,mode);octal(header,108,8,0);octal(header,116,8,0);octal(header,124,12,size);octal(header,136,12,0);
        Arrays.fill(header,148,156,(byte)' ');header[156]=(byte)type;put(header,157,100,link);put(header,257,8,"ustar  ");
        long sum=0;for(byte b:header)sum+=b&255;put(header,148,8,String.format(java.util.Locale.ROOT,"%06o\0 ",sum));out.write(header);
    }
    static void pad(OutputStream out,long size)throws IOException{out.write(new byte[(int)((512-size%512)%512)]);}
    static RuntimePackagePlan plan(Path archive,List<Member> members)throws IOException{return plan(archive,members,LIMITS);}
    static RuntimePackagePlan plan(Path archive,List<Member> members,RuntimePackagePlan.Limits limits)throws IOException{
        Map<String,RuntimePackagePlan.RequiredFile> required=new LinkedHashMap<>();long total=0;
        for(Member member:members){total+=member.length;if(member.type=='0'&&member.data!=null&&required.isEmpty())required.put(member.name,new RuntimePackagePlan.RequiredFile(member.length,sha(member.data),0,0));}
        if(required.isEmpty())required.put("required",new RuntimePackagePlan.RequiredFile(0,sha(new byte[0]),0,0));
        return new RuntimePackagePlan("wine-test",sha(bytes("source-pin")),"fixture.tar.gz",Files.size(archive),RuntimeFiles.hashFile(archive,Files.size(archive),RuntimeWork.NEVER_CANCELLED),members.size(),total,limits,required);
    }
    static RuntimeInstaller.Result install(RuntimeInstaller installer,Path archive,RuntimePackagePlan plan)throws IOException{return installer.install(archive,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);}
    static void serverGeneration()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan fixture=plan(archive,members);
        String serverBuild=sha(bytes("archived-server-build-source-lock"));
        String oldApp=sha(bytes("client-before")),newApp=sha(bytes("client-after"));
        check(!oldApp.equals(newApp),"current APK identities differ");
        for(String id:Arrays.asList("server-content-arm64","server-programs-arm64","server-extractors-arm64")){
            // Current APK hashes are checked by the adapter. Both descriptors
            // pass the unchanged archived server-build identity to this plan.
            RuntimePackagePlan before=new RuntimePackagePlan(id,serverBuild,fixture.archiveName,fixture.archiveBytes,fixture.archiveSha256,fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,fixture.required);
            RuntimePackagePlan after=new RuntimePackagePlan(id,serverBuild,fixture.archiveName,fixture.archiveBytes,fixture.archiveSha256,fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,fixture.required);
            check(before.generation.equals(after.generation),"client-only APK identity does not recopy server component");
            RuntimeInstaller installer=new RuntimeInstaller(root.resolve(id));RuntimeInstaller.Result first=install(installer,archive,before);
            RuntimeInstaller.Result repeat=installer.install(root.resolve("missing-unused-archive"),after,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(repeat.alreadyInstalled&&repeat.copiedBytes==0&&repeat.rootfs.equals(first.rootfs),"completed generation reused without archive recopy");
            RuntimePackagePlan differentBuild=new RuntimePackagePlan(id,sha(bytes("changed-server-source")),fixture.archiveName,fixture.archiveBytes,fixture.archiveSha256,fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,fixture.required);
            check(!before.generation.equals(differentBuild.generation),"server build drift changes generation");
            RuntimePackagePlan differentArchive=new RuntimePackagePlan(id,serverBuild,fixture.archiveName,fixture.archiveBytes,sha(bytes("changed-artifact")),fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,fixture.required);
            check(!before.generation.equals(differentArchive.generation),"artifact drift changes generation");
            Map<String,RuntimePackagePlan.RequiredFile> changed=new LinkedHashMap<>(fixture.required);String name=changed.keySet().iterator().next();
            RuntimePackagePlan.RequiredFile row=changed.get(name);changed.put(name,new RuntimePackagePlan.RequiredFile(row.bytes,sha(bytes("changed-required-file")),row.elfMachine,row.peMachine));
            RuntimePackagePlan differentFile=new RuntimePackagePlan(id,serverBuild,fixture.archiveName,fixture.archiveBytes,fixture.archiveSha256,fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,changed);
            check(!before.generation.equals(differentFile.generation),"required-file drift changes generation");
        }
    }
    static void installation()throws Exception{
        Path root=temp();List<Member> members=base();members.get(0).mode=04755;Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));
        RuntimeInstaller.Result result=install(installer,archive,plan);check(result.copiedBytes==26+result.hardLinkCopyBytes&&result.reusedFiles==0,"all regular bytes copied");
        check(Files.readSymbolicLink(result.rootfs.resolve("tool-link")).toString().equals("usr/bin/tool"),"absolute guest link rewritten");check(Files.isSameFile(result.rootfs.resolve("tool-hard"),result.rootfs.resolve("usr/bin/tool"))||result.hardLinkCopies==1,"hardlink is linked or explicitly copied");
        check(Arrays.equals(Files.readAllBytes(result.rootfs.resolve("tool-hard")),Files.readAllBytes(result.rootfs.resolve("usr/bin/tool"))),"hardlink content retained");
        check(Files.isExecutable(result.rootfs.resolve("usr/bin/tool")),"execute mode preserved privately");
        check(Files.readSymbolicLink(result.rootfs.resolve("usr/bin/X11")).toString().equals("."),"same-directory symlink stays dot, not empty");
        Files.delete(archive);RuntimeInstaller.Result repeat=install(installer,archive,plan);check(repeat.alreadyInstalled&&repeat.copiedBytes==0&&repeat.reusedFiles==2,"repeat reuses completed private generation");check(installer.resolveCurrent(plan).equals(result.rootfs),"current generation");
    }
    static void hardlinkCopy()throws Exception{
        Path root=temp();List<Member> members=base();members.get(0).mode=0755;Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);
        RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"),(output,target)->{throw new java.nio.file.AccessDeniedException(output.toString());});
        AtomicBoolean cancelled=new AtomicBoolean();
        fail(()->installer.install(archive,plan,(phase,path,done,total)->{if(phase.equals("copy-runtime-link"))cancelled.set(true);},cancelled::get));
        check(installer.resolveCurrent(plan)==null,"interrupted link copy cannot activate");
        check(Files.exists(root.resolve("store/staging").resolve(plan.generation).resolve("temporary/current-link")),"cancelled copy remains owned staging data");
        RuntimeInstaller.Result result=install(installer,archive,plan);
        check(result.hardLinkCopies==1&&result.hardLinkCopyBytes==15&&!Files.isSameFile(result.rootfs.resolve("tool-hard"),result.rootfs.resolve("usr/bin/tool")),"copy metrics record real extra storage");
        check(Files.isExecutable(result.rootfs.resolve("tool-hard")),"copied link keeps executable mode");
        check(install(installer,archive,plan).hardLinkCopies==1,"cached receipt preserves copy metrics");
        check(!Files.exists(result.rootfs.getParent().resolve("temporary/current-link")),"completed generation has no abandoned copy");
        Path alias=result.rootfs.resolve("tool-hard");long modified=Files.getLastModifiedTime(alias).toMillis();
        Files.setPosixFilePermissions(alias,java.nio.file.attribute.PosixFilePermissions.fromString("rwxr-----"));
        fail(()->installer.resolveCurrent(plan));RuntimeFiles.privateMode(alias,false,true);
        Files.write(alias,bytes("modified-copy!!"));Files.setLastModifiedTime(alias,FileTime.fromMillis(modified+1000));
        fail(()->installer.resolveCurrent(plan));fail(()->install(installer,archive,plan));
        Files.write(alias,bytes("executable-data"));Files.setLastModifiedTime(alias,FileTime.fromMillis(modified+2000));
        check(installer.resolveCurrent(plan).equals(result.rootfs),"timestamp-changed but authentic copy is rehashed and accepted");
        Path store=root.resolve("retry-native");RuntimeInstaller denied=new RuntimeInstaller(store,(output,target)->{throw new java.nio.file.AccessDeniedException(output.toString());});cancelled.set(false);
        fail(()->denied.install(archive,plan,(phase,path,done,total)->{if(phase.equals("copy-runtime-link"))cancelled.set(true);},cancelled::get));
        RuntimeInstaller.Result retried=install(new RuntimeInstaller(store),archive,plan);
        check(!Files.exists(retried.rootfs.getParent().resolve("temporary/current-link")),"retry cleans abandoned copy even when native linking becomes available");
        if(retried.hardLinkCopies==0)check(Files.isSameFile(retried.rootfs.resolve("tool-hard"),retried.rootfs.resolve("usr/bin/tool")),"host retry actually used native hardlink");
    }
    static void resume()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));AtomicBoolean cancel=new AtomicBoolean();
        fail(()->installer.install(archive,plan,(phase,path,done,total)->{if(phase.equals("runtime-file-prepared"))cancel.set(true);},cancel::get));check(installer.resolveCurrent(plan)==null,"cancel does not activate");
        RuntimeInstaller.Result result=install(installer,archive,plan);check(result.reusedFiles==1&&result.copiedBytes==11+result.hardLinkCopyBytes,"resume skips copied and read-back file");
    }
    static void journalRecovery()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));AtomicBoolean cancel=new AtomicBoolean();
        fail(()->installer.install(archive,plan,(phase,path,done,total)->{if(phase.equals("runtime-file-prepared"))cancel.set(true);},cancel::get));
        Path stage=root.resolve("store/staging").resolve(plan.generation);Files.write(stage.resolve("journal.tsv"),bytes("torn-record"),java.nio.file.StandardOpenOption.APPEND);
        Path tool=stage.resolve("rootfs/usr/bin/tool");long modified=Files.getLastModifiedTime(tool).toMillis();Files.write(tool,bytes("changed-content"));Files.setLastModifiedTime(tool,FileTime.fromMillis(modified+1000));
        RuntimeInstaller.Result result=install(installer,archive,plan);check(result.reusedFiles==0&&new String(Files.readAllBytes(result.rootfs.resolve("usr/bin/tool")),StandardCharsets.UTF_8).equals("executable-data"),"changed file recopied");
        check(!new String(Files.readAllBytes(result.rootfs.getParent().resolve("journal.tsv")),StandardCharsets.UTF_8).contains("torn-record"),"torn journal tail removed");
    }
    static void failedUpdate()throws Exception{
        Path root=temp();RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan old=plan(archive,members);Path active=install(installer,archive,old).rootfs;
        Path saves=root.resolve("saves");Files.write(saves,bytes("player-data"));List<Member> bad=Arrays.asList(file("required","new"),file("../outside","bad"));Path update=tar(root,bad);RuntimePackagePlan next=plan(update,bad);
        fail(()->install(installer,update,next));check(installer.resolveCurrent(old).equals(active)&&!Files.exists(root.resolve("outside")),"failed update retained active tree");check(new String(Files.readAllBytes(saves),StandardCharsets.UTF_8).equals("player-data"),"saves untouched");
    }
    static void promotionRecovery()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));RuntimeInstaller.Result result=install(installer,archive,plan);
        Files.delete(root.resolve("store/current"));Path staged=root.resolve("store/staging").resolve(plan.generation);Files.move(result.rootfs.getParent(),staged);
        RuntimeInstaller.Result recovered=install(installer,archive,plan);check(recovered.alreadyInstalled&&installer.resolveCurrent(plan).equals(recovered.rootfs),"completed stage safely promotes");
    }
    static void rejectedResidue()throws Exception{
        Path root=temp();byte[] random=new byte[5000];new java.util.Random(57).nextBytes(random);
        List<Member> good=Arrays.asList(file("required","okay"),file("large",java.util.Base64.getEncoder().encodeToString(random)));
        Path archive=tar(root,good);RuntimePackagePlan plan=plan(archive,good);
        List<Member> bad=Arrays.asList(file("required","okay"),file("orphan","poison"),file("large","short"));Path rejected=tar(root,bad);
        check(Files.size(rejected)<Files.size(archive),"rejected fixture is smaller");Files.write(rejected,Arrays.copyOf(Files.readAllBytes(rejected),(int)Files.size(archive)));
        RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));fail(()->install(installer,rejected,plan));
        Path stage=root.resolve("store/staging").resolve(plan.generation).resolve("rootfs");check(Files.isRegularFile(stage.resolve("orphan")),"rejected archive left staged evidence");
        fail(()->install(installer,archive,plan));check(installer.resolveCurrent(plan)==null,"unlisted rejected file is never published");
    }
    static void requiredTamper()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));Path rootfs=install(installer,archive,plan).rootfs;
        Path binary=rootfs.resolve("usr/bin/tool");byte[] data=Files.readAllBytes(binary);data[0]^=1;Files.write(binary,data);
        fail(()->installer.resolveCurrent(plan));fail(()->install(installer,archive,plan));
    }
    static void rejects(List<Member> members)throws Exception{Path root=temp();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));fail(()->install(installer,archive,plan));check(installer.resolveCurrent(plan)==null,"malformed archive unactivated");}
    static void unsafePaths()throws Exception{
        for(String path:new String[]{"../escape","/absolute","a/../../escape","a\\b","a//b"})rejects(Arrays.asList(file("required","ok"),file(path,"bad")));
        rejects(Arrays.asList(file("required","ok"),file("same","one"),file("same","two")));
        rejects(Arrays.asList(file("required","ok"),new Member("link","").link('2',"target"),file("link/child","bad")));
        rejects(Arrays.asList(file("required","ok"),file("parent/child","good"),file("parent","bad")));
    }
    static void unsafeLinks()throws Exception{
        for(Member link:Arrays.asList(new Member("bad","").link('2',"../escape"),new Member("bad","").link('2',"a/../escape"),new Member("bad","").link('1',"missing"),new Member("bad","").link('3',""),new Member("bad","").link('x',""),new Member("bad","").link('S',"")))rejects(Arrays.asList(file("required","ok"),link));
        rejects(Arrays.asList(file("required","ok"),new Member("symbolic","").link('2',"required"),new Member("hard","").link('1',"symbolic")));
    }
    static void longNamesAndLimits()throws Exception{
        Path root=temp();String longName="usr/share/"+String.join("",Collections.nCopies(200,"x"));List<Member> members=Arrays.asList(file("required","ok"),file(longName,"long-content"));Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);
        check(Files.isRegularFile(install(new RuntimeInstaller(root.resolve("store")),archive,plan).rootfs.resolve(longName)),"GNU long name extracted");
        RuntimePackagePlan.Limits small=new RuntimePackagePlan.Limits(10,1024,10240,4096,1024);RuntimePackagePlan limited=plan(archive,members,small);fail(()->install(new RuntimeInstaller(root.resolve("limited")),archive,limited));
        Path huge=root.resolve("long-header.tar.gz");try(GZIPOutputStream out=new GZIPOutputStream(Files.newOutputStream(huge))){writeHeader(out,"././@LongLink",'L',1L<<25,"",0644);}
        RuntimePackagePlan hugePlan=plan(huge,Collections.singletonList(file("required","ok")));fail(()->install(new RuntimeInstaller(root.resolve("huge")),huge,hugePlan));
    }
    static void corruption()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan original=plan(archive,members);byte[] data=Files.readAllBytes(archive);data[data.length-8]^=1;Files.write(archive,data);
        RuntimePackagePlan corrupt=plan(archive,members);fail(()->install(new RuntimeInstaller(root.resolve("crc")),archive,corrupt));
        Path valid=tar(root,members);RuntimePackagePlan validPlan=plan(valid,members);
        RuntimePackagePlan wrongHash=new RuntimePackagePlan("wine-test",original.sourcePinSha256,original.archiveName,Files.size(valid),String.join("",Collections.nCopies(64,"0")),validPlan.expectedEntries,validPlan.expectedFileBytes,LIMITS,validPlan.required);
        fail(()->install(new RuntimeInstaller(root.resolve("hash")),valid,wrongHash));
        Map<String,RuntimePackagePlan.RequiredFile> required=new LinkedHashMap<>(validPlan.required);required.put("usr/bin/tool",new RuntimePackagePlan.RequiredFile(15,sha(bytes("executable-data")),183,0));
        RuntimePackagePlan wrongArch=new RuntimePackagePlan("wine-test",validPlan.sourcePinSha256,validPlan.archiveName,validPlan.archiveBytes,validPlan.archiveSha256,validPlan.expectedEntries,validPlan.expectedFileBytes,LIMITS,required);
        fail(()->install(new RuntimeInstaller(root.resolve("arch")),valid,wrongArch));
    }
    static void concurrency()throws Exception{
        Path root=temp();List<Member> members=base();Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller installer=new RuntimeInstaller(root.resolve("store"));boolean[] checked={false};
        installer.install(archive,plan,(phase,path,done,total)->{if(!checked[0]){checked[0]=true;try{install(new RuntimeInstaller(root.resolve("store")),archive,plan);throw new AssertionError("Second installer acquired lock");}catch(IOException expected){}}},RuntimeWork.NEVER_CANCELLED);check(checked[0],"lock contention checked");
    }
    static void streaming()throws Exception{
        Path root=temp();Member large=file("large","");large.data=null;large.length=64L<<20;List<Member> members=Arrays.asList(file("required","ok"),large);Path archive=tar(root,members);RuntimePackagePlan plan=plan(archive,members);RuntimeInstaller.Result result=install(new RuntimeInstaller(root.resolve("store")),archive,plan);check(Files.size(result.rootfs.resolve("large"))==64L<<20,"large file fully streamed");
    }
    static byte[] downloadBytes(){byte[] bytes=new byte[400000];for(int i=0;i<bytes.length;i++)bytes[i]=(byte)(i*31);return bytes;}
    static DownloadCache.Response response(byte[] bytes,int start){return new DownloadCache.Response(start==0?200:206,bytes.length-start,start==0?null:"bytes "+start+"-"+(bytes.length-1)+"/"+bytes.length,new ByteArrayInputStream(bytes,start,bytes.length-start));}
    static DownloadCache.Transport interrupted(byte[] bytes){return(uri,offset)->new DownloadCache.Response(200,bytes.length,null,new InputStream(){int position;public int read()throws IOException{if(position>=150000)throw new IOException("connection interrupted");return bytes[position++]&255;}public int read(byte[] target,int off,int len)throws IOException{if(position>=150000)throw new IOException("connection interrupted");int count=Math.min(len,150000-position);System.arraycopy(bytes,position,target,off,count);position+=count;return count;}});}
    static void downloadResume()throws Exception{
        Path root=temp();DownloadCache cache=new DownloadCache(root.resolve("cache"));byte[] data=downloadBytes();String hash=sha(data);fail(()->cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,interrupted(data)));
        long[] observed={0};Path archive=cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->{observed[0]=offset;return response(data,(int)offset);});check(observed[0]==150000&&Arrays.equals(Files.readAllBytes(archive),data),"download resumed exact offset");
    }
    static void downloadRange()throws Exception{
        Path root=temp();DownloadCache cache=new DownloadCache(root.resolve("cache"));byte[] data=downloadBytes();String hash=sha(data);fail(()->cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,interrupted(data)));
        fail(()->cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->new DownloadCache.Response(206,data.length-offset,"bytes 2-9/10",new ByteArrayInputStream(data))));
        Path archive=cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->{check(offset==150000,"bad range preserved partial");return response(data,0);});check(Arrays.equals(Files.readAllBytes(archive),data),"server ignoring Range restarts safely");
    }
    static void downloadCancel()throws Exception{
        Path root=temp();DownloadCache cache=new DownloadCache(root.resolve("cache"));byte[] data=downloadBytes();String hash=sha(data);AtomicBoolean cancel=new AtomicBoolean();fail(()->cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,(phase,path,done,total)->{if(phase.equals("download"))cancel.set(true);},cancel::get,(uri,offset)->response(data,0)));
        Path archive=cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->{check(offset>0,"partial retained after cancel");return response(data,(int)offset);});
        Path repeat=cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->{throw new AssertionError("Cached repeat used network");});check(archive.equals(repeat),"cache reused");
    }
    static void downloadSafety()throws Exception{
        Path root=temp();DownloadCache cache=new DownloadCache(root.resolve("cache"));byte[] data=downloadBytes();String hash=sha(data);Path valid=cache.obtain(URI_PIN,"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->response(data,0));
        byte[] wrong=data.clone();wrong[0]^=1;fail(()->cache.obtain(URI_PIN,"other.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->response(wrong,0)));check(Arrays.equals(Files.readAllBytes(valid),data),"failed update preserved valid archive");
        String pin="esteria-download-v1\nevil.tar.gz\n"+data.length+"\n"+hash+"\n";Path outside=root.resolve("outside");Files.write(outside,bytes("keep"));Files.createSymbolicLink(root.resolve("cache").resolve(RuntimeFiles.hashText(pin)+".partial"),outside);
        fail(()->cache.obtain(URI_PIN,"evil.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->response(data,0)));check(new String(Files.readAllBytes(outside),StandardCharsets.UTF_8).equals("keep"),"cache symlink preserved outside file");
        fail(()->cache.obtain(URI.create("http://example.invalid/file"),"runtime.tar.gz",data.length,hash,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->response(data,0)));
    }
}
