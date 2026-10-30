package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ClientLaunchViewTests {
    private static void check(boolean value){if(!value)throw new AssertionError();}
    private interface Checked {void run()throws Exception;}
    private static void fails(Checked operation)throws Exception {try{operation.run();throw new AssertionError("Expected failure");}catch(IOException expected){}}
    private static byte[] pe(boolean dll) {
        byte[] bytes=new byte[1024*1024];ByteBuffer b=ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN);
        b.putShort(0,(short)0x5a4d);b.putInt(60,64);b.putInt(64,0x4550);b.putShort(68,(short)0xaa64);b.putShort(86,(short)(dll?0x2002:2));b.putShort(88,(short)0x20b);
        for(int i=128;i<bytes.length;i++)bytes[i]=(byte)(i*17);return bytes;
    }
    private static RuntimePackagePlan client(Path source,String identity)throws Exception {
        Files.createDirectories(source.resolve("bin"));Map<String,RuntimePackagePlan.RequiredFile> pins=new TreeMap<>();
        for(String name:new String[]{"WowClient64.exe","XvidDecoder.dll"}) {
            byte[] data=pe(name.endsWith("dll"));Files.write(source.resolve("bin/"+name),data);
            pins.put("bin/"+name,new RuntimePackagePlan.RequiredFile(data.length,RuntimeFiles.hex(RuntimeFiles.digest().digest(data)),0,0xaa64));
        }
        return new RuntimePackagePlan("client-arm64",RuntimeFiles.hashText(identity),"client.tar.gz",128,"f".repeat(64),2,2L<<20,
            new RuntimePackagePlan.Limits(10,2L<<20,4L<<20,4096,1<<20),pins);
    }
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("esteria-launch-tests-");
        try {
            Path source=root.resolve("provider"),imported=root.resolve("imported"),work=root.resolve("work");Files.createDirectories(work);
            RuntimePackagePlan client=client(source,"revision1");Files.createDirectories(imported.resolve("Data/enUS"));
            Files.writeString(imported.resolve("Data/common.MPQ"),"fixture-content-not-a-real-MPQ");
            Files.writeString(imported.resolve("Data/enUS/locale-enUS.MPQ"),"fixture-locale");
            Path original=imported.resolve("Data/enUS/realmlist.wtf");Files.writeString(original,"SET realmList \"remote.example\"\n");
            Files.createDirectories(imported.resolve("Fonts"));Files.writeString(imported.resolve("Fonts/FRIZQT__.TTF"),"synthetic-font");
            Files.writeString(imported.resolve("EsteriaItems.bin"),"fixture-catalog");Files.writeString(imported.resolve("EsteriaOff.txt"),"do not import");
            ClientLaunchView.Plan plan=new ClientLaunchView.Plan(source,client,imported,"1".repeat(64));
            ClientLaunchView views=new ClientLaunchView(work);AtomicBoolean cancelled=new AtomicBoolean();
            fails(()->views.prepare(plan,(phase,path,done,total)->{if(done>=262144)cancelled.set(true);},cancelled::get));
            check(!Files.exists(work.resolve("launch/"+plan.generation)));cancelled.set(false);
            Path partial=work.resolve("launch-staging/"+plan.generation+"/.WowClient64.exe.partial");check(Files.size(partial)>=262144);
            ClientLaunchView.Result ready=views.prepare(plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(plan.deferredLooseTrees.isEmpty());
            check(Files.readSymbolicLink(ready.directory.resolve("Fonts/FRIZQT__.TTF")).toString().equals("/esteria-data/Fonts/FRIZQT__.TTF"));
            check(!ready.alreadyPrepared&&Files.isRegularFile(ready.directory.resolve("WowClient64.exe")));
            check(Files.readSymbolicLink(ready.directory.resolve("Data/common.MPQ")).toString().equals("/esteria-data/Data/common.MPQ"));
            check(Files.readSymbolicLink(ready.directory.resolve("WTF")).toString().equals("/work/client-state/WTF"));
            check(Files.readSymbolicLink(ready.directory.resolve("EsteriaItems.bin")).toString().equals("/esteria-data/EsteriaItems.bin"));
            check(!Files.exists(ready.directory.resolve("EsteriaOff.txt"),LinkOption.NOFOLLOW_LINKS));
            check(Files.readString(ready.directory.resolve("Data/enUS/realmlist.wtf")).contains("127.0.0.1:3724"));
            check(Files.readString(original).contains("remote.example"));
            Files.writeString(work.resolve("client-state/WTF/Config.wtf"),"user-settings-preserved");
            Files.writeString(ready.directory.resolve("EsteriaDecomp.log"),"prior log");
            ClientLaunchView.Result reused=views.prepare(plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);check(reused.alreadyPrepared);
            RuntimePackagePlan updated=client(source,"revision2");ClientLaunchView.Plan next=new ClientLaunchView.Plan(source,updated,imported,"1".repeat(64));
            ClientLaunchView.Result replacement=views.prepare(next,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(!replacement.directory.equals(ready.directory)&&Files.readString(ready.directory.resolve("EsteriaDecomp.log")).equals("prior log"));
            check(Files.readString(work.resolve("client-state/WTF/Config.wtf")).equals("user-settings-preserved"));
            check(next.arguments().equals(Arrays.asList("-datadir","Z:\\work\\launch\\"+next.generation,"-vulkan")));
            check(next.environment().get("GX_VULKAN_SHADERS").equals("Z:\\esteria-shaders"));
            Path shadow=ready.directory.resolve("Data/enUS/Realmlist.wtf");Files.writeString(shadow,"SET realmList \"remote.invalid\"");
            fails(()->views.prepare(plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));Files.delete(shadow);
            Files.createDirectories(imported.resolve("interface/AddOns/Test"));
            ClientLaunchView.Plan blocked=new ClientLaunchView.Plan(source,client,imported,"4".repeat(64));
            check(blocked.deferredLooseTrees.equals(Collections.singletonList("Interface")));fails(blocked::arguments);
            Path longName=imported.resolve("Data/"+"x".repeat(180));Files.writeString(longName,"long");
            fails(()->new ClientLaunchView.Plan(source,client,imported,"1".repeat(64)));Files.delete(longName);
            // No host link is followed or repaired, even where a legitimate guest link belongs.
            Path link=ready.directory.resolve("Data/common.MPQ");Files.delete(link);Files.createSymbolicLink(link,original);
            fails(()->views.prepare(plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));check(Files.readSymbolicLink(link).equals(original));
            Files.createSymbolicLink(imported.resolve("Data/escape"),work);
            fails(()->new ClientLaunchView.Plan(source,client,imported,"1".repeat(64)));Files.delete(imported.resolve("Data/escape"));
            Files.writeString(imported.resolve("Data/COMMON.mpq"),"collision");
            fails(()->new ClientLaunchView.Plan(source,client,imported,"1".repeat(64)));Files.delete(imported.resolve("Data/COMMON.mpq"));
            Files.writeString(imported.resolve("Data/bad\\name.MPQ"),"bad");
            fails(()->new ClientLaunchView.Plan(source,client,imported,"1".repeat(64)));Files.delete(imported.resolve("Data/bad\\name.MPQ"));
            Files.writeString(replacement.directory.resolve("esteriaoff.txt"),"unexpected marker");
            fails(()->views.prepare(next,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));
            Path lower=root.resolve("lower-import");Files.createDirectories(lower.resolve("data/enUS"));Files.createDirectories(lower.resolve("fonts"));
            Files.createDirectories(lower.resolve("iNtErFaCe"));Files.writeString(lower.resolve("data/enUS/locale-enUS.MPQ"),"lower-fixture");Files.writeString(lower.resolve("fonts/A.ttf"),"font");
            ClientLaunchView.Plan lowerPlan=new ClientLaunchView.Plan(source,updated,lower,"5".repeat(64));
            ClientLaunchView.Result lowerView=views.prepare(lowerPlan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(Files.readSymbolicLink(lowerView.directory.resolve("Data/enUS/locale-enUS.MPQ")).toString().equals("/esteria-data/data/enUS/locale-enUS.MPQ"));
            check(Files.readSymbolicLink(lowerView.directory.resolve("Fonts/A.ttf")).toString().equals("/esteria-data/fonts/A.ttf"));
            check(lowerPlan.deferredLooseTrees.equals(Collections.singletonList("Interface")));fails(lowerPlan::arguments);
            Files.createDirectories(lower.resolve("Data"));fails(()->new ClientLaunchView.Plan(source,updated,lower,"5".repeat(64)));Files.delete(lower.resolve("Data"));
            Files.createSymbolicLink(lower.resolve("unrelated-root-link"),original);fails(()->new ClientLaunchView.Plan(source,updated,lower,"5".repeat(64)));
            Path unowned=root.resolve("unowned");Files.createDirectories(unowned.resolve("launch"));Files.writeString(unowned.resolve("launch/keep"),"valuable");
            fails(()->new ClientLaunchView(unowned));check(Files.readString(unowned.resolve("launch/keep")).equals("valuable"));
            // Corrupt owned partial bytes are preserved rather than silently overwritten.
            ClientLaunchView.Plan third=new ClientLaunchView.Plan(source,updated,imported,"3".repeat(64));
            AtomicBoolean cancelThird=new AtomicBoolean();fails(()->views.prepare(third,(phase,path,done,total)->cancelThird.set(true),cancelThird::get));
            Path corrupt=work.resolve("launch-staging/"+third.generation+"/.WowClient64.exe.partial");Files.write(corrupt,new byte[]{12},StandardOpenOption.WRITE);
            fails(()->views.prepare(third,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));check(Files.readAllBytes(corrupt)[0]==12);
            System.out.println("PASS: persistent launch view, PE hash/type checks, interrupted-copy resume, preservation, loopback locale overlay, guest-only links and hostile-path rejection");
        } finally {
            Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
                public FileVisitResult visitFile(Path path,java.nio.file.attribute.BasicFileAttributes attributes)throws IOException{Files.delete(path);return FileVisitResult.CONTINUE;}
                public FileVisitResult postVisitDirectory(Path path,IOException error)throws IOException{Files.delete(path);return FileVisitResult.CONTINUE;}
            });
        }
    }
}
