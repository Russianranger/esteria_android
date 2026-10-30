package io.github.russianranger.esteria.core.runtime.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.BasicFileAttributes;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;

public final class ClientUiStoreTests {
    private interface Checked {void run()throws Exception;}
    private static void check(boolean condition){if(!condition)throw new AssertionError();}
    private static void fails(Checked operation)throws Exception {try{operation.run();throw new AssertionError("Expected failure");}catch(IOException expected){}}
    private static String id(String label){return RuntimeFiles.hashText(label);}
    private static Path generation(Path store,String name,String parent,Map<String,byte[]> changed)throws Exception {
        Path at=store.resolve("generations/"+name),data=at.resolve("data");Files.createDirectories(data);
        if(parent!=null) {
            Path old=store.resolve("generations/"+parent+"/data");
            Files.walkFileTree(old,new SimpleFileVisitor<Path>() {
                public FileVisitResult preVisitDirectory(Path path,BasicFileAttributes attrs)throws IOException{Files.createDirectories(data.resolve(old.relativize(path)));return FileVisitResult.CONTINUE;}
                public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException{Files.createLink(data.resolve(old.relativize(path)),path);return FileVisitResult.CONTINUE;}
            });
            Files.writeString(at.resolve("base-ready"),parent+"\n");
        }
        StringBuilder journal=new StringBuilder();
        for(Map.Entry<String,byte[]> entry:changed.entrySet()) {
            Path file=data.resolve(entry.getKey());Files.createDirectories(file.getParent());Files.deleteIfExists(file);Files.write(file,entry.getValue());
            journal.append('\n').append(Base64.getEncoder().encodeToString(entry.getKey().getBytes(StandardCharsets.UTF_8))).append('\t').append(entry.getValue().length).append('\t').append(Files.getLastModifiedTime(file).toMillis()).append('\t').append(RuntimeFiles.hex(RuntimeFiles.digest().digest(entry.getValue()))).append('\n');
        }
        // A torn earlier journal record is normal after an interrupted import.
        journal.append("\nold-partial-record\n");Files.writeString(at.resolve("journal.tsv"),journal.toString());
        Files.writeString(at.resolve("complete"),"format=1\nclientBuild=12340\nrequest="+name+"\nsource="+id("source-"+name)+"\ndirectorySync=true\ncontentCompatibility=unqualified\n");
        return data;
    }
    private static byte[] bytes(String value){return value.getBytes(StandardCharsets.UTF_8);}
    private static ImportedUiSource source(Path store,String generation)throws Exception{return ImportedUiSource.fromImportStore(store,generation,RuntimeWork.NEVER_CANCELLED);}
    private static RuntimePackagePlan client(Path root)throws Exception {
        Files.createDirectories(root.resolve("bin"));Map<String,RuntimePackagePlan.RequiredFile> pins=new TreeMap<>();
        for(String name:new String[]{"WowClient64.exe","XvidDecoder.dll"}) {
            byte[] data=new byte[128];java.nio.ByteBuffer pe=java.nio.ByteBuffer.wrap(data).order(java.nio.ByteOrder.LITTLE_ENDIAN);
            pe.putShort(0,(short)0x5a4d);pe.putInt(60,64);pe.putInt(64,0x4550);pe.putShort(68,(short)0xaa64);pe.putShort(86,(short)(name.endsWith("dll")?0x2002:2));pe.putShort(88,(short)0x20b);
            Files.write(root.resolve("bin/"+name),data);pins.put("bin/"+name,new RuntimePackagePlan.RequiredFile(data.length,RuntimeFiles.hex(RuntimeFiles.digest().digest(data)),0,0xaa64));
        }
        return new RuntimePackagePlan("client-arm64",id("client-source"),"client.gz",10,id("archive"),2,256,new RuntimePackagePlan.Limits(2,128,256,4096,4096),pins);
    }
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("esteria-ui-tests-");
        try {
            Path imports=root.resolve("imports"),work=root.resolve("work");Files.createDirectories(work);
            byte[] large=new byte[1024*1024];Arrays.fill(large,(byte)45);
            String first=id("base");Path original=generation(imports,first,null,Map.of("interface/AddOns/Test/main.lua",bytes("original-lua"),"interface/AddOns/Test/large.bin",large,"interface/AddOns/Test/Test.pub",bytes("source-key"),"Data/common.MPQ",bytes("synthetic-not-game-data")));
            ImportedUiSource a=source(imports,first);check(a.files==3&&a.bytes==large.length+12+10);
            ClientUiStore ui=new ClientUiStore(work);check(ui.current(RuntimeWork.NEVER_CANCELLED)==null);
            AtomicBoolean cancel=new AtomicBoolean();fails(()->ui.prepare(a,(phase,path,done,total)->{if(done>=262144)cancel.set(true);},cancel::get));
            check(ui.current(RuntimeWork.NEVER_CANCELLED)==null);cancel.set(false);
            ClientUiStore.Candidate initial=ui.prepare(a,RuntimeWork.NONE,cancel::get);check(!initial.reused);
            ClientUiStore.Assessment start=ui.assess(initial,RuntimeWork.NEVER_CANCELLED);check(!start.requiresReview);
            ui.activate(initial,start.digest,false,RuntimeWork.NEVER_CANCELLED);check(ui.current(RuntimeWork.NEVER_CANCELLED).equals(initial.interfaceDirectory));
            Path provider=root.resolve("client-provider");RuntimePackagePlan client=client(provider);
            ClientUiStore.Selection selection=ui.selectedFor(a,RuntimeWork.NEVER_CANCELLED);
            ClientLaunchView.Plan launchPlan=new ClientLaunchView.Plan(provider,client,original,first,selection);
            ClientLaunchView views=new ClientLaunchView(work);ClientLaunchView.Result launch=views.prepare(launchPlan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(launchPlan.deferredLooseTrees.isEmpty()&&launchPlan.arguments().size()==3);
            check(Files.readSymbolicLink(launch.directory.resolve("Interface")).toString().equals(selection.guestPath()));
            fails(()->new ClientLaunchView.Plan(provider,client,original,id("wrong-import"),selection));
            Path lua=initial.interfaceDirectory.resolve("AddOns/Test/main.lua"),pub=initial.interfaceDirectory.resolve("AddOns/Test/Test.pub");
            Files.writeString(lua,"user-modified");Files.writeString(pub,"game-updated-key");Files.writeString(initial.interfaceDirectory.resolve("AddOns/Test/Test.url"),"runtime-url-not-logged");
            Path wtf=work.resolve("client-state/WTF/Account/SavedVariables.lua");Files.createDirectories(wtf.getParent());Files.writeString(wtf,"persistent-account-settings");
            check(Files.readString(original.resolve("interface/AddOns/Test/main.lua")).equals("original-lua"));
            check(Files.readString(original.resolve("interface/AddOns/Test/Test.pub")).equals("source-key"));
            ClientUiStore.Candidate same=ui.prepare(a,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);check(same.reused&&same.interfaceDirectory.equals(initial.interfaceDirectory));
            ClientUiStore.Assessment sameReport=ui.assess(same,RuntimeWork.NEVER_CANCELLED);check(!sameReport.requiresReview&&sameReport.previousMutations.size()==3);
            ui.activate(same,sameReport.digest,false,RuntimeWork.NEVER_CANCELLED);
            // Data-only import inherits Interface hashes from its base journal.
            String dataUpdate=id("data-only");generation(imports,dataUpdate,first,Map.of("Data/patch-X.MPQ",bytes("new-data-only")));
            ImportedUiSource inherited=source(imports,dataUpdate);check(inherited.inventoryId.equals(a.inventoryId));
            ClientUiStore.Candidate retained=ui.prepare(inherited,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);check(retained.reused&&retained.interfaceDirectory.equals(initial.interfaceDirectory));
            check(Files.readString(lua).equals("user-modified"));
            // Conflicting imported UI uses a separate pristine copy. Nothing is selected yet.
            String update=id("ui-update");generation(imports,update,dataUpdate,Map.of("interface/AddOns/Test/main.lua",bytes("new-vendor-lua")));
            ImportedUiSource b=source(imports,update);check(!b.inventoryId.equals(a.inventoryId));
            ClientUiStore.Candidate next=ui.prepare(b,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            ClientUiStore.Assessment report=ui.assess(next,RuntimeWork.NEVER_CANCELLED);check(report.requiresReview&&report.conflicts.size()==1&&report.previousMutations.size()==3);
            fails(()->ui.activate(next,report.digest,false,RuntimeWork.NEVER_CANCELLED));check(ui.current(RuntimeWork.NEVER_CANCELLED).equals(initial.interfaceDirectory));
            Files.writeString(lua,"changed-after-report");fails(()->ui.activate(next,report.digest,true,RuntimeWork.NEVER_CANCELLED));
            ClientUiStore.Assessment fresh=ui.assess(next,RuntimeWork.NEVER_CANCELLED);
            Files.writeString(next.interfaceDirectory.resolve("AddOns/Test/added.lua"),"candidate-edit");fails(()->ui.activate(next,fresh.digest,true,RuntimeWork.NEVER_CANCELLED));
            ClientUiStore.Assessment reviewed=ui.assess(next,RuntimeWork.NEVER_CANCELLED);check(reviewed.candidateMutations.size()==1);
            ui.activate(next,reviewed.digest,true,RuntimeWork.NEVER_CANCELLED);check(Files.readString(lua).equals("changed-after-report"));
            check(Files.readString(next.interfaceDirectory.resolve("AddOns/Test/main.lua")).equals("new-vendor-lua"));check(Files.readString(wtf).equals("persistent-account-settings"));
            fails(launchPlan::arguments);fails(()->views.prepare(launchPlan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));
            ClientUiStore.Selection changedSelection=ui.selectedFor(b,RuntimeWork.NEVER_CANCELLED);
            ClientLaunchView.Plan changedLaunch=new ClientLaunchView.Plan(provider,client,b.dataRoot,update,changedSelection);
            check(views.prepare(changedLaunch,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).directory!=null);
            // A metadata mutation after source selection is not adopted.
            Path journal=imports.resolve("generations/"+update+"/journal.tsv");String journalText=Files.readString(journal);Files.writeString(journal,journalText+"\n");
            fails(()->ui.prepare(b,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));Files.writeString(journal,journalText);
            Path evil=next.interfaceDirectory.resolve("AddOns/Test/host-link");Files.createSymbolicLink(evil,original);
            fails(()->ui.assess(next,RuntimeWork.NEVER_CANCELLED));Files.delete(evil);
            // Immutable baseline/provenance cannot authorize their own replacement.
            Path baseline=next.interfaceDirectory.getParent().resolve("inventory.tsv");String inventory=Files.readString(baseline);Files.writeString(baseline,inventory+"\n");
            fails(()->ui.assess(next,RuntimeWork.NEVER_CANCELLED));Files.writeString(baseline,inventory);
            Path proof=next.interfaceDirectory.getParent().resolve("provenance/"+update);Files.writeString(proof,"changed");fails(()->ui.assess(next,RuntimeWork.NEVER_CANCELLED));
            // Reject missing inherited hashes, root links and cycles without creating a UI generation.
            String missing=id("missing");Path missingData=generation(imports,missing,null,Map.of("interface/AddOns/X/a.lua",bytes("file")));
            Files.writeString(missingData.getParent().resolve("journal.tsv"),"");fails(()->source(imports,missing));
            String cyclic=id("cycle");generation(imports,cyclic,null,Map.of());Files.writeString(imports.resolve("generations/"+cyclic+"/base-ready"),cyclic+"\n");fails(()->source(imports,cyclic));
            String linked=id("link");Path linkedData=generation(imports,linked,null,Map.of());Files.createSymbolicLink(linkedData.resolve("Interface"),original);fails(()->source(imports,linked));
            Path overlapping=work.resolve("bad-import-store");String empty=id("empty-overlap");generation(overlapping,empty,null,Map.of());
            ImportedUiSource misplaced=source(overlapping,empty);fails(()->ui.prepare(misplaced,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED));
            Path foreign=root.resolve("foreign");Files.createDirectories(foreign.resolve("client-state/UI"));Files.writeString(foreign.resolve("client-state/keep"),"preserve");
            fails(()->new ClientUiStore(foreign));check(Files.readString(foreign.resolve("client-state/keep")).equals("preserve"));
            System.out.println("PASS: UI overlay ancestry/hash binding, interrupted copy, mutation-preserving reuse, source conflict reports, stale activation rejection, retained generations/WTF and unsafe ownership/link/baseline rejection");
        } finally {
            Files.walkFileTree(root,new SimpleFileVisitor<Path>() {
                public FileVisitResult visitFile(Path path,BasicFileAttributes attrs)throws IOException{Files.delete(path);return FileVisitResult.CONTINUE;}
                public FileVisitResult postVisitDirectory(Path path,IOException error)throws IOException{Files.delete(path);return FileVisitResult.CONTINUE;}
            });
        }
    }
}
