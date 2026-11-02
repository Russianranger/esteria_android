package io.github.russianranger.esteria.core.runtime.install;

import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;

/** Actual host filesystem/installer tests. No owner assets or gameplay claim. */
public final class RuntimeStorageMaintenanceTests {
    private static final String A="a".repeat(64),B="b".repeat(64),C="c".repeat(64),D="d".repeat(64),E="e".repeat(64);
    private static final RuntimeStorageMaintenance.Guard IDLE=()->{};
    @FunctionalInterface private interface Attempt{void run()throws Exception;}
    private static int passed;
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void refused(Attempt attempt)throws Exception {
        try{attempt.run();}catch(IOException expected){return;}throw new AssertionError("Unsafe maintenance admitted");
    }
    private static void run(String name,Attempt test)throws Exception{test.run();passed++;System.out.println("PASS "+name);}
    private static Path temp()throws IOException{return Files.createTempDirectory("esteria-storage-maintenance-").toRealPath();}
    private static void clean(Path root)throws IOException {
        try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
    }
    private static Path file(Path root,String relative,String text)throws IOException {
        Path path=root.resolve(relative);Files.createDirectories(path.getParent());Files.writeString(path,text);return path;
    }
    private static Path generation(Path root,String key,String kind,String id,boolean complete)throws IOException {
        Path at=root.resolve("runtimes").resolve(key).resolve(kind).resolve(id);Files.createDirectories(at.resolve("rootfs"));
        Files.writeString(at.resolve("owner"),"esteria-runtime-stage-v1\n"+id+"\n");
        Files.writeString(at.resolve("rootfs/payload"),"immutable component "+id);
        if(complete)Files.writeString(at.resolve("complete"),"format=1\ngeneration="+id+"\nsourcePin="+A+
            "\narchiveSha256="+B+"\ngameplayQualified=false\n");
        return at;
    }
    private static void current(Path root,String key,String id)throws IOException {file(root,"runtimes/"+key+"/current",id+"\n");}
    private static long bytes(Path root)throws IOException {
        long sum=0;try(var paths=Files.walk(root)){for(Path path:paths.toArray(Path[]::new))if(Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS))sum+=Files.size(path);}return sum;
    }
    private static RuntimeStorageMaintenance.Report scan(Path root,Map<String,String> pins)throws IOException {
        return RuntimeStorageMaintenance.scan(root,pins,IDLE,RuntimeWork.NEVER_CANCELLED);
    }
    private static RuntimeStorageMaintenance.Report trim(Path root,Map<String,String> pins)throws IOException {
        return RuntimeStorageMaintenance.trim(root,pins,IDLE,RuntimeWork.NEVER_CANCELLED,RuntimeWork.NONE);
    }
    private static void protectedContent()throws Exception {
        Path root=temp();try {
            Path active=generation(root,"server-arm64","generations",A,true);
            Path selected=generation(root,"server-arm64","staging",B,false);
            Path obsolete=generation(root,"server-arm64","generations",C,true);
            Path abandoned=generation(root,"server-arm64","staging",D,false);
            Path unknown=generation(root,"server-arm64","generations",E,true);Files.writeString(unknown.resolve("owner"),"FOREIGN");
            current(root,"server-arm64",A);
            for(String path:List.of("game/generations/owned/data/Data/common.MPQ","db/live/characters","state/wine-prefix/save",
                    "server-data-work/server-data/staging/partial/mmaps/tile","state/shader-work/shaders/current",
                    "state/server-installations/active"))file(root,path,"PRESERVE "+path);
            long expected=bytes(obsolete)+bytes(abandoned);Map<String,String> pins=Map.of("server-arm64",B);
            RuntimeStorageMaintenance.Report preview=scan(root,pins),again=scan(root,pins);
            check(preview.reclaimableBytes==expected&&preview.removedBytes==0&&preview.obsoleteGenerations==2&&preview.unknownItemsPreserved==1,"Exact bounded preview recognizes only owned obsolete trees");
            check(again.reclaimableBytes==expected&&Files.exists(obsolete)&&Files.exists(abandoned),"Repeated scan is deterministic and keeps candidates");
            RuntimeStorageMaintenance.Report removed=trim(root,pins);
            check(removed.removedBytes==expected&&removed.removedItems==2&&!Files.exists(obsolete)&&!Files.exists(abandoned),"Only selected obsolete objects removed");
            check(Files.exists(active.resolve("rootfs/payload"))&&Files.exists(selected.resolve("rootfs/payload"))&&Files.exists(unknown.resolve("rootfs/payload")),"Current, expected staging and foreign content retained");
            check(Files.readString(root.resolve("game/generations/owned/data/Data/common.MPQ")).startsWith("PRESERVE")&&
                Files.readString(root.resolve("db/live/characters")).startsWith("PRESERVE")&&
                Files.readString(root.resolve("server-data-work/server-data/staging/partial/mmaps/tile")).startsWith("PRESERVE"),"Imported client, DB and incomplete navigation remain untouched");
            check(scan(root,pins).reclaimableBytes==0,"Trim is idempotent");
        }finally{clean(root);}
    }
    private static void actualInstallerCache()throws Exception {
        Path root=temp();try {
            List<RuntimeInstallerTests.Member> members=RuntimeInstallerTests.base();Path source=RuntimeInstallerTests.tar(root,members);
            RuntimePackagePlan fixture=RuntimeInstallerTests.plan(source,members);
            RuntimePackagePlan plan=new RuntimePackagePlan("wine-arm64",fixture.sourcePinSha256,fixture.archiveName,fixture.archiveBytes,
                fixture.archiveSha256,fixture.expectedEntries,fixture.expectedFileBytes,fixture.limits,fixture.required);
            byte[] archive=Files.readAllBytes(source);AtomicInteger network=new AtomicInteger();
            Path copied=new DownloadCache(root.resolve("runtime-downloads")).obtain(URI.create("https://example.invalid/runtime.tar.gz"),
                plan.archiveName,plan.archiveBytes,plan.archiveSha256,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,(uri,offset)->{
                    network.incrementAndGet();check(offset==0,"Fresh fixture download");return new DownloadCache.Response(200,archive.length,null,new ByteArrayInputStream(archive));});
            RuntimeInstaller installer=new RuntimeInstaller(root.resolve("runtimes/wine-arm64"));RuntimeInstaller.Result first=installer.install(copied,plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            RuntimeStorageMaintenance.Report preview=scan(root,Map.of("wine-arm64",plan.generation));
            check(preview.cachedArchives==1&&preview.reclaimableBytes>=archive.length,"Installed runtime makes actual pinned download cache redundant");
            RuntimeStorageMaintenance.Report removed=trim(root,Map.of("wine-arm64",plan.generation));
            check(removed.removedBytes==preview.reclaimableBytes&&!Files.exists(copied),"Full archive plus recognized sidecars removed");
            RuntimeInstaller.Result repeat=installer.install(root.resolve("does-not-exist.archive"),plan,RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            check(repeat.alreadyInstalled&&repeat.copiedBytes==0&&repeat.rootfs.equals(first.rootfs)&&network.get()==1,"Actual repeat setup succeeds without archive or another network request");
            check(Files.readString(repeat.rootfs.resolve("usr/bin/tool")).equals("executable-data"),"Installed payload remains intact");
        }finally{clean(root);}
    }
    private static void embeddedAndUnknownCaches()throws Exception {
        Path root=temp();try {
            generation(root,"client-arm64","generations",A,true);current(root,"client-arm64",A);
            byte[] payload="embedded archive".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            Path cache=root.resolve("runtime-embedded-cache/client-arm64");
            Path archive=new EmbeddedArchiveCache(cache).obtain("client.archive",payload.length,RuntimeFiles.hex(RuntimeFiles.digest().digest(payload)),
                offset->new ByteArrayInputStream(payload,(int)offset,payload.length-(int)offset),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED);
            Path unknown=file(root,"runtime-embedded-cache/client-arm64/not-owned.archive","PRESERVED");
            Path badOwner=file(root,"runtime-embedded-cache/client-arm64/"+E+".owner","unrecognized owner");
            long expected=bytes(cache)-Files.size(unknown)-Files.size(badOwner)-Files.size(cache.resolve(".lock"));
            RuntimeStorageMaintenance.Report report=trim(root,Map.of("client-arm64",A));
            check(report.cachedArchives==1&&report.removedBytes==expected&&!Files.exists(archive),"Only recognized embedded group is reclaimed");
            check(Files.readString(unknown).equals("PRESERVED")&&Files.exists(badOwner)&&report.unknownItemsPreserved==1,"Unknown cache objects preserved");
        }finally{clean(root);}
    }
    private static void pendingAndOmittedPins()throws Exception {
        Path root=temp();try {
            generation(root,"wine-arm64","generations",A,true);current(root,"wine-arm64",A);
            byte[] payload="not yet selected archive".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            Path cache=new DownloadCache(root.resolve("runtime-downloads")).obtain(URI.create("https://example.invalid/runtime"),"wine.archive",payload.length,
                RuntimeFiles.hex(RuntimeFiles.digest().digest(payload)),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,
                (uri,offset)->new DownloadCache.Response(200,payload.length,null,new ByteArrayInputStream(payload)));
            check(trim(root,Map.of("wine-arm64",B)).cachedArchives==0&&Files.exists(cache),"Pending expected generation keeps archives for resume");
            check(trim(root,Map.of()).cachedArchives==0&&Files.exists(cache),"Omitted provider preserves current generation and cache");
            refused(()->scan(root,Map.of("../../db",A)));refused(()->scan(root,Map.of("wine-arm64","../db")));
        }finally{clean(root);}
    }
    private static void unusableSelectedRuntimeKeepsCache()throws Exception {
        Path root=temp();try {
            Path selected=generation(root,"wine-arm64","generations",A,true);current(root,"wine-arm64",A);
            Files.delete(selected.resolve("rootfs/payload"));Files.delete(selected.resolve("rootfs"));
            byte[] payload="repair archive".getBytes(java.nio.charset.StandardCharsets.UTF_8);
            Path cache=new DownloadCache(root.resolve("runtime-downloads")).obtain(URI.create("https://example.invalid/runtime"),"wine.archive",payload.length,
                RuntimeFiles.hex(RuntimeFiles.digest().digest(payload)),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED,
                (uri,offset)->new DownloadCache.Response(200,payload.length,null,new ByteArrayInputStream(payload)));
            RuntimeStorageMaintenance.Report report=trim(root,Map.of("wine-arm64",A));
            check(report.cachedArchives==0&&Files.exists(cache)&&Files.exists(selected.resolve("complete")),"Missing installed root does not make a repair archive redundant");
        }finally{clean(root);}
    }
    private static void symlinksAndCanonicalPaths()throws Exception {
        Path root=temp(),outside=temp();try {
            Path target=file(outside,"save","OUTSIDE SAVE");Path obsolete=generation(root,"client-arm64","generations",C,true);
            Files.createSymbolicLink(obsolete.resolve("rootfs/external"),outside);
            Path linked=root.resolve("runtimes/client-arm64/generations/"+D);Files.createSymbolicLink(linked,outside);
            trim(root,Map.of("client-arm64",A));
            check(Files.readString(target).equals("OUTSIDE SAVE")&&Files.isSymbolicLink(linked),"Owned internal links are unlinked without traversing targets; unknown linked generations preserved");
            Path alias=outside.resolve("alias");Files.createSymbolicLink(alias,root);
            refused(()->scan(alias,Map.of()));refused(()->scan(root.resolve("../"+root.getFileName()),Map.of()));
            Files.createDirectories(root.resolve("runtime-embedded-cache"));Files.createSymbolicLink(root.resolve("runtime-embedded-cache/server-arm64"),outside);
            refused(()->trim(root,Map.of()));check(Files.readString(target).equals("OUTSIDE SAVE"),"Linked managed root is refused before any deletion");
        }finally{clean(root);clean(outside);}
    }
    private static void leaseAndIdleRefusal()throws Exception {
        Path root=temp();try {
            Path obsolete=generation(root,"server-arm64","generations",C,true);Map<String,String> pins=Map.of("server-arm64",A);
            refused(()->RuntimeStorageMaintenance.trim(root,pins,()->{throw new IOException("game remains owned");},RuntimeWork.NEVER_CANCELLED,RuntimeWork.NONE));
            check(!Files.exists(root.resolve(".runtime-maintenance.lock"))&&Files.exists(obsolete),"Busy guard refuses even lease creation");
            try(ExclusiveFileLease owner=ExclusiveFileLease.acquire(root.resolve("runtimes/server-arm64/.lock"),"owned")) {
                refused(()->trim(root,pins));check(owner.isValid()&&Files.exists(obsolete),"Live installer lease remains valid after trim refusal");
            }
            Path cache=Files.createDirectories(root.resolve("runtime-downloads"));
            try(ExclusiveFileLease owner=ExclusiveFileLease.acquire(cache.resolve(".lock"),"owned")) {
                refused(()->trim(root,pins));check(owner.isValid()&&Files.exists(obsolete),"Cache lease blocks deletion across stores");
            }
            trim(root,pins);check(!Files.exists(obsolete),"Refused maintenance releases its own leases for retry");
        }finally{clean(root);}
    }
    private static void cancellationAndResume()throws Exception {
        Path root=temp();try {
            Path obsolete=generation(root,"server-arm64","generations",C,true);Map<String,String> pins=Map.of("server-arm64",A);
            refused(()->RuntimeStorageMaintenance.trim(root,pins,IDLE,()->true,RuntimeWork.NONE));
            check(Files.exists(obsolete)&&!Files.exists(root.resolve(".runtime-maintenance.lock")),"Precancelled trim leaves storage untouched");
            Path trash=root.resolve("runtimes/server-arm64/cleanup-trash/generations-"+C);
            refused(()->RuntimeStorageMaintenance.trim(root,pins,IDLE,()->Files.exists(trash),RuntimeWork.NONE));
            check(!Files.exists(obsolete)&&Files.isRegularFile(trash.resolve("maintenance-owner")),"Cancellation after atomic quarantine leaves resumable owned cleanup");
            check(scan(root,pins).obsoleteGenerations==1,"Incomplete cleanup is recognized next time");
            trim(root,pins);check(!Files.exists(trash)&&scan(root,pins).reclaimableBytes==0,"Retry removes remaining trash without reusing partial runtime");
        }finally{clean(root);}
    }
    private static void malformedAndBounded()throws Exception {
        final Path root=temp();try {
            Path obsolete=generation(root,"server-arm64","generations",C,true);
            Path deep=obsolete.resolve("rootfs");for(int i=0;i<130;i++)deep=Files.createDirectory(deep.resolve("d"));Files.writeString(deep.resolve("payload"),"DEEP");
            refused(()->trim(root,Map.of("server-arm64",A)));check(Files.exists(obsolete.resolve("owner")),"Depth bound fails the complete inventory before deletion");
        }finally{clean(root);}
        Path second=temp();try {
            Path bad=generation(second,"server-arm64","generations",C,true);Files.writeString(bad.resolve("complete"),"format=999\n");
            file(second,"runtimes/server-arm64/cleanup-trash/generations-"+D+"/maintenance-owner","FOREIGN");
            RuntimeStorageMaintenance.Report report=trim(second,Map.of("server-arm64",A));
            check(report.reclaimableBytes==0&&report.unknownItemsPreserved==2&&Files.exists(bad.resolve("rootfs/payload")),"Malformed receipts and foreign trash remain intact");
        }finally{clean(second);}
    }
    public static void main(String[] args)throws Exception {
        run("current, expected, unknown, imported, database and world work preservation",RuntimeStorageMaintenanceTests::protectedContent);
        run("actual downloaded runtime cache trim and offline repeat installation",RuntimeStorageMaintenanceTests::actualInstallerCache);
        run("embedded archive ownership groups and unknown cache preservation",RuntimeStorageMaintenanceTests::embeddedAndUnknownCaches);
        run("unprepared caches, omitted providers and path-like pins retained or refused",RuntimeStorageMaintenanceTests::pendingAndOmittedPins);
        run("missing selected runtime root retains its repair archive",RuntimeStorageMaintenanceTests::unusableSelectedRuntimeKeepsCache);
        run("canonical roots, linked managed stores and non-following obsolete symlink removal",RuntimeStorageMaintenanceTests::symlinksAndCanonicalPaths);
        run("idle guard plus installer/cache lease refusal and reacquisition",RuntimeStorageMaintenanceTests::leaseAndIdleRefusal);
        run("pre-cancellation, atomic quarantine and interrupted cleanup resume",RuntimeStorageMaintenanceTests::cancellationAndResume);
        run("bounded traversal and malformed ownership preservation",RuntimeStorageMaintenanceTests::malformedAndBounded);
        System.out.println("Runtime storage maintenance tests passed: "+passed+"; host filesystem/installer evidence only");
    }
}
