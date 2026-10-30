package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.install.*;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Exercises the production app adapter with real importer/UI/launch stores; no Android or PE execution. */
public final class ClientLaunchSetupTest {
    private interface Operation { void run() throws Exception; }
    private static void check(boolean value) { if(!value)throw new AssertionError(); }
    private static void fails(Operation op) throws Exception {
        try { op.run(); throw new AssertionError("Expected refusal"); } catch(IOException expected) { }
    }
    private static String hash(byte[] bytes) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    }
    private static String id(String text) throws Exception { return hash(text.getBytes(StandardCharsets.UTF_8)); }
    private static Path imported(Path root,String name,String parent,Map<String,String> files) throws Exception {
        Path generations=root.resolve("game/generations"),generation=generations.resolve(name),data=generation.resolve("data");
        Files.createDirectories(data);
        if(parent!=null) {
            Path prior=generations.resolve(parent+"/data");
            Files.walkFileTree(prior,new SimpleFileVisitor<Path>() {
                public FileVisitResult preVisitDirectory(Path dir,BasicFileAttributes attrs)throws IOException { Files.createDirectories(data.resolve(prior.relativize(dir)));return FileVisitResult.CONTINUE; }
                public FileVisitResult visitFile(Path file,BasicFileAttributes attrs)throws IOException { Files.createLink(data.resolve(prior.relativize(file)),file);return FileVisitResult.CONTINUE; }
            });
            Files.writeString(generation.resolve("base-ready"),parent+"\n");
        }
        StringBuilder journal=new StringBuilder();
        for(Map.Entry<String,String> row:files.entrySet()) {
            Path path=data.resolve(row.getKey());Files.createDirectories(path.getParent());Files.deleteIfExists(path);
            byte[] value=row.getValue().getBytes(StandardCharsets.UTF_8);Files.write(path,value);
            journal.append(Base64.getEncoder().encodeToString(row.getKey().getBytes(StandardCharsets.UTF_8))).append('\t')
                    .append(value.length).append('\t').append(Files.getLastModifiedTime(path).toMillis()).append('\t').append(hash(value)).append('\n');
        }
        Files.writeString(generation.resolve("journal.tsv"),journal);
        Files.writeString(generation.resolve("complete"),"format=1\nclientBuild=12340\nrequest="+name+"\nsource="+id("source-"+name)+"\n");
        Files.writeString(root.resolve("game/current"),name+"\n");return data;
    }
    private static RuntimePackagePlan binaryFixture(Path at) throws Exception {
        Files.createDirectories(at.resolve("bin"));Map<String,RuntimePackagePlan.RequiredFile> pins=new TreeMap<>();
        for(String name:List.of("WowClient64.exe","XvidDecoder.dll")) {
            byte[] data=new byte[128];ByteBuffer pe=ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
            pe.putShort(0,(short)0x5a4d);pe.putInt(60,64);pe.putInt(64,0x4550);pe.putShort(68,(short)0xaa64);
            pe.putShort(86,(short)(name.endsWith("dll")?0x2002:2));pe.putShort(88,(short)0x20b);
            Files.write(at.resolve("bin/"+name),data);pins.put("bin/"+name,new RuntimePackagePlan.RequiredFile(data.length,hash(data),0,0xaa64));
        }
        return new RuntimePackagePlan("client-arm64",id("source"),"client.gz",10,id("archive"),2,256,
                new RuntimePackagePlan.Limits(2,128,256,4096,4096),pins);
    }
    private static ClientLaunchSetup.Prepared prepare(Path root,Path binaries,RuntimePackagePlan plan,String digest,RuntimeWork.Progress progress) throws Exception {
        return ClientLaunchSetup.prepareStored(root,binaries,plan,digest,progress,RuntimeWork.NEVER_CANCELLED);
    }
    private static ClientLaunchSetup.UiReview review(Path root,Path binaries,RuntimePackagePlan plan,String digest) throws Exception {
        try { prepare(root,binaries,plan,digest,RuntimeWork.NONE);throw new AssertionError("Expected review"); }
        catch(ClientLaunchSetup.ReviewRequired required) { return required.review; }
    }
    public static void main(String[] args) throws Exception {
        Path root=Files.createTempDirectory("esteria-app-ui-test-");
        try {
            Path binaries=root.resolve("client");RuntimePackagePlan plan=binaryFixture(binaries);
            check(prepare(root,binaries,plan,null,RuntimeWork.NONE)==null);
            String base=id("base");Path original=imported(root,base,null,Map.of("Data/common.MPQ","synthetic-data-not-a-game-asset",
                    "Interface/AddOns/Test/main.lua","source-main","Interface/AddOns/Test/remove.lua","source-remove"));
            ClientLaunchSetup.Prepared first=prepare(root,binaries,plan,null,RuntimeWork.NONE);
            check(first.plan.deferredLooseTrees.isEmpty());first.plan.arguments();
            ClientUiStore store=new ClientUiStore(first.work);Path initial=store.current(RuntimeWork.NEVER_CANCELLED);
            Files.writeString(initial.resolve("AddOns/Test/main.lua"),"private-lua-value-not-for-reports");
            Files.delete(initial.resolve("AddOns/Test/remove.lua"));Files.writeString(initial.resolve("AddOns/Test/added.lua"),"new-local");
            Path saved=first.work.resolve("client-state/WTF/saved.lua");Files.writeString(saved,"private-saved-vars");
            AtomicInteger assessments=new AtomicInteger();RuntimeWork.Progress progress=(phase,path,done,total)->{if(phase.equals("client-ui-assessing"))assessments.incrementAndGet();};
            prepare(root,binaries,plan,null,progress);check(assessments.get()==0);
            String dataOnly=id("data-only");imported(root,dataOnly,base,Map.of("Data/patch-X.MPQ","data-update"));
            prepare(root,binaries,plan,null,progress);check(assessments.get()==0&&store.current(RuntimeWork.NEVER_CANCELLED).equals(initial));
            String next=id("next");imported(root,next,dataOnly,Map.of("Interface/AddOns/Test/main.lua","new-imported-main"));
            ClientLaunchSetup.UiReview pending=review(root,binaries,plan,null);
            check(pending.conflicts==1&&pending.currentChanges==3&&pending.candidateChanges==0);
            check(pending.text.contains("1 modified, 1 added, 1 deleted")&&pending.text.contains("AddOns/Test/main.lua")
                    &&!pending.text.contains("private-lua-value")&&!pending.text.contains("private-saved-vars")&&pending.text.length()<4096);
            check(store.current(RuntimeWork.NEVER_CANCELLED).equals(initial)); // Dismissing cannot activate anything.
            Files.writeString(initial.resolve("AddOns/Test/main.lua"),"mutated-after-displayed-report");
            ClientLaunchSetup.UiReview refreshed=review(root,binaries,plan,pending.digest);
            check(!refreshed.digest.equals(pending.digest)&&refreshed.text.startsWith("The UI files changed"));
            check(store.current(RuntimeWork.NEVER_CANCELLED).equals(initial));
            fails(()->prepare(root,binaries,plan,"bad-token",RuntimeWork.NONE));
            ClientLaunchSetup.Prepared accepted=prepare(root,binaries,plan,refreshed.digest,RuntimeWork.NONE);
            Path selected=store.current(RuntimeWork.NEVER_CANCELLED);check(!selected.equals(initial));
            check(Files.readString(selected.resolve("AddOns/Test/main.lua")).equals("new-imported-main"));
            check(Files.readString(initial.resolve("AddOns/Test/main.lua")).equals("mutated-after-displayed-report"));
            check(Files.readString(original.resolve("Interface/AddOns/Test/main.lua")).equals("source-main"));
            check(Files.readString(saved).equals("private-saved-vars"));accepted.plan.arguments();fails(first.plan::arguments);
            // An old decision cannot be replayed after activation, even if the current tree is now clean.
            review(root,binaries,plan,refreshed.digest);check(store.current(RuntimeWork.NEVER_CANCELLED).equals(selected));
            String clean=id("clean-update");imported(root,clean,next,Map.of("Interface/AddOns/Test/main.lua","clean-update"));
            prepare(root,binaries,plan,null,RuntimeWork.NONE);check(!store.current(RuntimeWork.NEVER_CANCELLED).equals(selected));
            Path pointer=first.work.resolve("client-state/UI/current");String before=Files.readString(pointer);
            fails(()->ClientLaunchSetup.prepareStored(root,binaries,plan,null,RuntimeWork.NONE,()->true));
            check(Files.readString(pointer).equals(before));
            System.out.println("PASS: actual app adapter autoactivation, same-inventory reuse without assessment, bounded concrete review, stale/replayed decision refusal, retained old UI/import/WTF, typed launch view and cancellation");
        } finally {
            Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
                public FileVisitResult visitFile(Path file,BasicFileAttributes attrs)throws IOException { Files.delete(file);return FileVisitResult.CONTINUE; }
                public FileVisitResult postVisitDirectory(Path dir,IOException error)throws IOException { Files.delete(dir);return FileVisitResult.CONTINUE; }
            });
        }
    }
}
