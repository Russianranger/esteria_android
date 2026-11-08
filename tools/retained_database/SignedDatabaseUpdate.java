package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.ContextWrapper;
import android.os.Looper;
import io.github.russianranger.esteria.core.runtime.install.FreshServerInstallations;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.Arrays;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;

/** Separate observer DEX. Only the installed package supplies production classes and assets. */
public final class SignedDatabaseUpdate {
    private static void require(boolean ok,String reason) throws IOException {if(!ok)throw new IOException(reason);}

    public static void main(String[] args) throws Exception {
        if(args.length!=1)throw new IllegalArgumentException("one qualification phase required");
        if(Looper.myLooper()==null)Looper.prepareMainLooper();
        Class<?> thread=Class.forName("android.app.ActivityThread");
        Object instance=thread.getMethod("systemMain").invoke(null);
        Context system=(Context)thread.getMethod("getSystemContext").invoke(instance);
        Context pkg=system.createPackageContext("io.github.russianranger.esteria.stock",0);
        require(pkg.getApplicationInfo().uid==android.os.Process.myUid(),"installed UID required");
        Context context=new ContextWrapper(pkg){@Override public Context getApplicationContext(){return this;}};
        System.load(pkg.getApplicationInfo().nativeLibraryDir+"/libesteria_process.so");
        FutureTask<Void> task=new FutureTask<>(()->{
            if(args[0].startsWith("debug-")) {
                Class.forName("io.github.russianranger.esteria.runtime.RetainedDatabaseRepairTest")
                    .getMethod("runPhase",Context.class,String.class).invoke(null,context,args[0].substring(6));
            } else run(context,args[0]);
            return null;
        });
        new Thread(task,"signed-db-update-observer").start();
        try {task.get();}
        catch(Exception failure) {
            for(Throwable cause=failure;cause!=null;cause=cause.getCause()) {
                System.out.println("ESTERIA_ERROR "+cause.getClass().getName());
                for(StackTraceElement frame:cause.getStackTrace()) {
                    if(frame.getClassName().startsWith("io.github.russianranger.esteria."))
                        System.out.println("ESTERIA_FRAME "+frame);
                }
            }
            System.exit(1);
        }
        System.out.println("ESTERIA_RESULT "+args[0]+" success");
    }

    private static void run(Context ctx,String phase) throws Exception {
        long start=System.nanoTime();
        Path root=ctx.getFilesDir().getCanonicalFile().toPath(),qa=root.resolve("qa-signed-db");
        Path data=qa.resolve("unavailable-world-data");
        ServerRuntimeSetup server=new ServerRuntimeSetup(ctx,root);
        ServerProgramsSetup programs=new ServerProgramsSetup(ctx,root);
        ServerContentSetup content=new ServerContentSetup(ctx,root);
        RuntimeSetup wine=new RuntimeSetup(ctx,root);
        ClientRuntimeSetup client=new ClientRuntimeSetup(ctx,root);
        GuestBridgeSetup bridges=new GuestBridgeSetup(ctx,root);
        TurnipSetup graphics=new TurnipSetup(ctx,root);
        ServerDataToolsSetup dataTools=new ServerDataToolsSetup(ctx,root);
        ShaderToolsSetup shaderTools=new ShaderToolsSetup(ctx,root);
        RuntimeWork.Progress progress=(event,path,count,total)->{
            if(event.startsWith("database-")||event.startsWith("installation-"))
                System.out.println("ESTERIA_PHASE "+event+" elapsedMs="+TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start));
        };
        if(phase.equals("seed19")) {
            require(!Files.exists(root.resolve("db"))&&!Files.exists(root.resolve("runtimes")),"disposable fresh app required");
            Files.createDirectory(qa);Files.createDirectory(data);
            long bytes=server.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=programs.prepare(server.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=content.prepare(server.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=wine.installer().install(Paths.get("/esteria-qa/input/wine.tar.gz"),wine.packagePlan(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=client.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=bridges.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=graphics.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=dataTools.prepare(server.archiveSha256(),RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            bytes+=shaderTools.prepare(RuntimeWork.NONE,RuntimeWork.NEVER_CANCELLED).copiedBytes;
            System.out.println("ESTERIA_SEED providerCopiedBytes="+bytes+" client="+client.generation());
        }
        require(Files.isDirectory(data),"missing prior qualification owner");
        client.requireWineArchive(wine.archiveSha256());bridges.requireWineArchive(wine.archiveSha256());graphics.requireWineArchive(wine.archiveSha256());
        Path[] roots={server.current(),programs.current(),content.current(),wine.current(),client.current(),
            bridges.current(),graphics.current(),dataTools.current(),shaderTools.current()};
        verifyRetainedFiles(qa,roots,client,phase.equals("seed19"));
        if(phase.equals("seed19"))return;
        if(phase.equals("fail19")) {
            require(ServerInstallationSetup.completedOrNull(ctx,root,server,programs,content)==null,"unexpected preexisting slot");
            try(ServerInstallationSetup.Handle owner=ServerInstallationSetup.beginFresh(ctx,root,server,programs,content,data,1L<<30)) {
                Files.write(qa.resolve("old-slot"),owner.slotId().getBytes("US-ASCII"),StandardOpenOption.CREATE_NEW);
                try{owner.prepare(progress,RuntimeWork.NEVER_CANCELLED);throw new AssertionError("v19 unexpectedly completed");}
                catch(IOException expected){require("Server content receipt has not been prepared".equals(expected.getMessage()),"different v19 failure: "+expected);}
            }
            return;
        }
        String old=new String(Files.readAllBytes(qa.resolve("old-slot")),"US-ASCII");
        require(old.matches("[0-9a-f]{16}"),"invalid retained slot");
        Path oldBootstrap=root.resolve("db").resolve(old).resolve("state/database-bootstrap.json");
        require(Files.isRegularFile(oldBootstrap),"v19 staging lost");
        if(phase.equals("repair21")) {
            require(ServerInstallationSetup.completedOrNull(ctx,root,server,programs,content)==null,"incomplete v19 slot selected");
            var before=ServerInstallationSetup.retainedDiagnostics(root);
            require("abandoned/failed".equals(before.get("database.retained."+old)),"v19 failed slot journal missing");
            System.out.println("ESTERIA_RETAINED "+before);
            Files.write(qa.resolve("old-proof"),digest(oldBootstrap),StandardOpenOption.CREATE_NEW);
            try(ServerInstallationSetup.Handle owner=ServerInstallationSetup.beginFresh(ctx,root,server,programs,content,data,1L<<30)) {
                owner.prepare(progress,RuntimeWork.NEVER_CANCELLED);
                owner.finishPlayerbots(progress,RuntimeWork.NEVER_CANCELLED);
                FreshServerInstallations.Active active=owner.stopAndPromote(Duration.ofSeconds(30));
                require(!active.slotId.equals(old),"incomplete slot promoted");
                Files.write(qa.resolve("active"),identity(root,active),StandardOpenOption.CREATE_NEW);
            }
        } else if(!phase.equals("cold21"))throw new IOException("unknown phase");
        FreshServerInstallations.Active active=ServerInstallationSetup.completed(ctx,root,server,programs,new ServerContentSetup(ctx,root));
        require(Arrays.equals(identity(root,active),Files.readAllBytes(qa.resolve("active"))),"promoted identity or account changed");
        require(Arrays.equals(digest(oldBootstrap),Files.readAllBytes(qa.resolve("old-proof"))),"abandoned bootstrap changed");
        ServerDatabaseService.Handle service=ServerDatabaseService.startActive(ctx,root,server,active);
        try{
            ServerDatabaseService.awaitReady(service,System.nanoTime()+TimeUnit.MINUTES.toNanos(3),RuntimeWork.NEVER_CANCELLED);
            require(active.mysqlUuid.equals(service.instanceUuid()),"live SQL UUID differs");
        }finally{service.stop(Duration.ofSeconds(30));}
        require(!service.isAlive(),"MySQL did not stop");
        System.out.println("ESTERIA_ACTIVE slot="+active.slotId+" uuid="+active.mysqlUuid+" client="+client.generation()+" elapsedMs="+TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-start));
    }
    /** Measure every provider seal and the selected client payload across package replacement. */
    private static void verifyRetainedFiles(Path qa,Path[] roots,ClientRuntimeSetup client,boolean seed)throws Exception{
        MessageDigest summary=MessageDigest.getInstance("SHA-256");
        for(Path selected:roots) {
            require(selected!=null,"retained provider unavailable");
            Path seal=selected.resolveSibling("complete");
            observeFile(summary,seal);
        }
        long clientBytes=0;
        for(String name:new java.util.TreeSet<>(client.packagePlan().required.keySet())) {
            Path file=roots[4].resolve(name);
            observeFile(summary,file);
            clientBytes+=Files.size(file);
        }
        Path record=qa.resolve("selected-provider-identities");
        byte[] measured=summary.digest();
        if(seed)Files.write(record,measured,StandardOpenOption.CREATE_NEW);
        else require(MessageDigest.isEqual(measured,Files.readAllBytes(record)),"provider seal or client payload changed");
        System.out.println("ESTERIA_REUSE providerSeals="+roots.length+" clientRequiredFiles="+client.packagePlan().required.size()
            +" clientRequiredBytes="+clientBytes+" matchPrevious="+!seed);
    }
    private static void observeFile(MessageDigest summary,Path file)throws Exception{
        android.system.StructStat stat=android.system.Os.lstat(file.toString());
        require(android.system.OsConstants.S_ISREG(stat.st_mode),"expected regular retained file");
        String attributes=file+" "+stat.st_dev+" "+stat.st_ino+" "+stat.st_size+" "+Files.getLastModifiedTime(file)+"\n";
        summary.update(attributes.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        try(java.io.InputStream input=Files.newInputStream(file)) {
            byte[] buffer=new byte[65536];
            int count;
            while((count=input.read(buffer))!=-1)summary.update(buffer,0,count);
        }
    }
    private static byte[] digest(Path file)throws Exception{return MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));}
    private static byte[] identity(Path root,FreshServerInstallations.Active active)throws Exception{
        MessageDigest hash=MessageDigest.getInstance("SHA-256");
        hash.update(active.slotId.getBytes("US-ASCII"));hash.update(active.mysqlUuid.getBytes("US-ASCII"));hash.update(active.proofSha256.getBytes("US-ASCII"));
        return hash.digest(digest(active.directoryFor(root).resolve("state/accounts/local-player.json")));
    }
}
