package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.os.Looper;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.StockClientCompatibility;
import io.github.russianranger.esteria.core.importer.StockClientSelection;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import io.github.russianranger.esteria.core.runtime.ServiceOperationGuard;
import io.github.russianranger.esteria.core.runtime.install.RuntimeWork;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProotLaunch;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import org.json.*;

/** Content-level stock inspection followed by immutable app-owned selection.
 * The owner remains retained on timeout; it never modifies the source client.
 * Receipt reuse trusts the immutable importer and exact helper/tool identities,
 * not arbitrary user JSON. Runtime signatures/world execution stay separate. */
public final class StockClientSetup {
    private static final Map<Path,Handle> OWNERS=new ConcurrentHashMap<>();
    private static final Set<String> HELPERS=Set.of("stock_content_inspection.py","stock_shader_generation.py","shader_generation.py","extractor_order.py","server_data_preflight.py","world_io.py","stock_shader_translate.py");
    private StockClientSetup() { }
    /** Install only immutable APK-owned helpers; callers mount this directory
     * separately from the preserved upstream shader compiler provider. */
    public static Path installHelpers(Context context,Path root)throws IOException {
        if(!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical stock helper storage required");
        Path work=GuestHelperAssets.directory(root,"state/stock-client-work");
        Path helpers=GuestHelperAssets.directory(work,"helpers");
        String generation=GuestHelperAssets.install(context,"stock-client",helpers,HELPERS);
        return helpers.resolve(generation);
    }
    public enum State { ALLOCATED,RUNNING,PREPARED,FAILED,CLOSED }
    public static Handle begin(Context context,Path root,RuntimeSetup wine,ShaderToolsSetup tools,String locale)throws IOException {
        background();
        if(root==null||!root.equals(context.getFilesDir().getCanonicalFile().toPath()))throw new IOException("Private canonical stock setup storage required");
        if(!Arrays.asList("deDE","enGB","enUS","esES","frFR","koKR","zhCN","zhTW","enCN","enTW","esMX","ruRU").contains(locale))throw new IOException("Choose the imported client language");
        tools.requireWineArchive(wine.archiveSha256());
        if(wine.current()==null||tools.current()==null)throw new IOException("Prepare the client runtime and shader tools before stock inspection");
        Path work=GuestHelperAssets.directory(root,"state/stock-client-work");
        if(OWNERS.containsKey(work))throw new IOException("Previous stock inspection cleanup remains retained");
        ExclusiveFileLease lease=ExclusiveFileLease.acquire(work.resolve(".stock-client.lock"),"Stock inspection is already active");
        try {
            Handle result=new Handle(context.getApplicationContext(),root,work,wine,tools,locale,lease);
            if(OWNERS.putIfAbsent(work,result)!=null)throw new IOException("Stock inspection owner remains retained");
            return result;
        }catch(IOException|RuntimeException|Error error){try{lease.close();}catch(IOException close){error.addSuppressed(close);}throw error;}
    }
    public static final class Handle implements AutoCloseable {
        final Context context;final Path root,work;final RuntimeSetup wine;final ShaderToolsSetup tools;final String locale;
        final ExclusiveFileLease lease;final ServiceOperationGuard operations=new ServiceOperationGuard();
        volatile State state=State.ALLOCATED;volatile OwnedProcess process;volatile ExclusiveFileLease importedLease;
        volatile Map<String,Path> logs=Map.of();
        Handle(Context context,Path root,Path work,RuntimeSetup wine,ShaderToolsSetup tools,String locale,ExclusiveFileLease lease) {
            this.context=context;this.root=root;this.work=work;this.wine=wine;this.tools=tools;this.locale=locale;this.lease=lease;
        }
        public State state(){return state;}
        public Map<String,Path> diagnosticLogs(){return logs;}
        public boolean processAlive(){OwnedProcess child=process;return child!=null&&child.isAlive();}
        public io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot usage(){OwnedProcess child=process;return child==null?null:child.usage();}
        public Path prepare(RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation)throws IOException {
            background();return operations.run(()->{
                if(state!=State.ALLOCATED)throw new IOException("Stock setup owner is single use");state=State.RUNNING;
                RuntimeWork.Cancellation stop=()->operations.isStopRequested()||(cancellation!=null&&cancellation.isCancelled());
                try {
                    String helper=installHelpers(context,root).getFileName().toString();
                    GameDataImporter importer=new GameDataImporter(root.resolve("game"));
                    for(int pass=0;pass<2;pass++) {
                        check(stop);
                        importedLease=ExclusiveFileLease.acquire(root.resolve("game/import.lock"),"Imported client data is in use");
                        Path source=importer.resolveCurrent();
                        if(source==null)throw new IOException("Import your complete build12340 client first");
                        StockClientCompatibility.Report structure=StockClientCompatibility.inspect(source,locale);structure.requirePreparationInputs();
                        String generation=source.getParent().getFileName().toString();
                        String cacheIdentity=sha256((helper+"\n"+tools.toolManifestSha256()+"\n"+importMetadata(source)).getBytes(StandardCharsets.US_ASCII));
                        String reportName="report-"+generation+"-"+locale+"-"+cacheIdentity+".json";
                        Path report=work.resolve(reportName);
                        if(!Files.exists(report,LinkOption.NOFOLLOW_LINKS))runInspection(source,generation,helper,reportName,progress,stop);
                        JSONObject proof=readReport(report,generation);
                        Map<String,String> excluded=exclusions(proof,source);
                        String digest=sha256(read(report,8<<20));
                        // The importer acquires the very same import lease. Only
                        // after the child is reaped may selection release/reacquire.
                        importedLease.close();importedLease=null;
                        Path selected=StockClientSelection.apply(importer,source,generation,excluded,digest,
                            (path,bytes,total,count,files)->{if(progress!=null)progress.update("stock-client-selecting",path,bytes,total);},stop::isCancelled);
                        if(selected.equals(source)){state=State.PREPARED;return selected;}
                    }
                    throw new IOException("Stock selection changed repeatedly; preserved source and prepared outputs");
                }catch(IOException|RuntimeException error){state=State.FAILED;throw error;}
            });
        }
        private void runInspection(Path source,String generation,String helper,String reportName,RuntimeWork.Progress progress,RuntimeWork.Cancellation stop)throws IOException {
            Path sessions=GuestHelperAssets.directory(root,"state/stock-client-operations");
            Path session=Files.createDirectory(sessions.resolve(UUID.randomUUID().toString().replace("-","")));
            logs=Map.of("setup.stock.stdout.log",session.resolve("logs/stdout.log"),"setup.stock.stderr.log",session.resolve("logs/stderr.log"));
            if(progress!=null)progress.update("stock-client-inspecting","Checking effective stock UI, DBC and shader inputs",0,-1);
            List<String> args=Arrays.asList("/usr/bin/python3","-B","-s","-E","/work/helpers/"+helper+"/stock_content_inspection.py",
                "--source","/esteria-data/generations/"+generation+"/data","--tools","/esteria-shader-tools/tools",
                "--client-revision",tools.revision(),"--locale",locale,"--generation",generation,"--report","/work/"+reportName,"--android-low-memory");
            process=ProotProcess.start(context,wine.installer(),wine.packagePlan(),work,session,args,wine.wineEnvironment(),
                Arrays.asList(new ProotLaunch.Mount(root.resolve("game"),"/esteria-data"),new ProotLaunch.Mount(tools.current(),"/esteria-shader-tools")),null);
            long deadline=System.nanoTime()+TimeUnit.MINUTES.toNanos(30);
            long nextProgress=0;ServerDataSetup.ProgressLines lines=new ServerDataSetup.ProgressLines();String observedPhase="stock-client-inspecting";
            while(process.isAlive()) {
                check(stop);if(System.nanoTime()>=deadline)throw new IOException("Stock inspection timed out; logs and imported data retained");
                if(progress!=null&&System.nanoTime()>=nextProgress){String observed=lines.read(session.resolve("logs/stdout.log"));if(observed!=null)observedPhase="stock-client-"+observed;progress.update(observedPhase,"Checking stock content",0,-1);nextProgress=System.nanoTime()+TimeUnit.SECONDS.toNanos(1);}
                try{Thread.sleep(100);}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException("Stock inspection interrupted; owner retained",error);}
            }
            RuntimeWork.checkMemoryPressureExit(process.exitCode());
            if(process.failure()!=null||process.wasForced()||(process.exitCode()!=0&&!Files.isRegularFile(work.resolve(reportName),LinkOption.NOFOLLOW_LINKS)))throw new IOException("Stock content inspection failed (exit "+process.exitCode()+"); export the support bundle for the exact member/codec failure",process.failure());
        }
        private JSONObject readReport(Path report,String generation)throws IOException {
            try {
                JSONObject proof=new JSONObject(new String(read(report,8<<20),StandardCharsets.UTF_8));
                if(!"stock-3.3.5a".equals(proof.get("contentProfile"))||!generation.equals(proof.get("importGeneration"))||
                    !tools.revision().equals(proof.get("clientRevision"))||!locale.equals(proof.get("requestedLocale")))throw new IOException("Stock report source/tool identity differs");
                JSONArray unknown=proof.getJSONArray("unknownOverlays"),errors=proof.getJSONArray("errors");
                if(unknown.length()>0)throw new IOException("Stock profile cannot classify optional overlay "+unknown.get(0).toString()+"; its source is preserved. Supply the clean client or an identified optional overlay.");
                if(errors.length()>0)throw new IOException("Essential stock content: "+errors.get(0));
                if(!tools.toolManifestSha256().equals(proof.get("toolManifestSha256")))throw new IOException("Stock report tool identity differs");
                if(!Boolean.TRUE.equals(proof.get("passed")))throw new IOException("Stock content inspection did not pass");
                return proof;
            }catch(JSONException error){throw new IOException("Invalid bounded stock compatibility report",error);}
        }
        private Map<String,String> exclusions(JSONObject proof,Path source)throws IOException {
            try {
                Map<String,String> result=new TreeMap<>();JSONArray rows=proof.getJSONArray("exclusions");
                if(rows.length()>4096)throw new IOException("Stock exclusion inventory exceeds bound");
                for(int i=0;i<rows.length();i++) {
                    JSONObject row=rows.getJSONObject(i);String path=row.getString("path"),hash=row.getString("sha256"),reason=row.getString("reason");
                    if(reason.isEmpty()||reason.length()>1024||!hash.matches("[0-9a-f]{64}")||result.put(path,hash)!=null)throw new IOException("Invalid content-confirmed stock exclusion");
                    Path file=source.resolve(path).normalize();
                    if(!file.startsWith(source)||!file.equals(file.toRealPath())||!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||Files.size(file)!=row.getLong("bytes"))throw new IOException("Optional overlay changed after inspection");
                }
                return result;
            }catch(JSONException error){throw new IOException("Invalid stock exclusion evidence",error);}
        }
        @Override public void close()throws IOException {close(Duration.ofSeconds(20));}
        public void close(Duration timeout)throws IOException {
            background();try(ServiceOperationGuard.StopPermit permit=operations.stopWithin(timeout)) {
                if(state==State.CLOSED)return;
                if(process!=null&&process.isAlive()){process.stop(permit.remaining());if(process.isAlive())throw new IOException("Stock inspection child remains alive; import owner retained");}
                if(importedLease!=null){importedLease.close();importedLease=null;}
                lease.close();state=State.CLOSED;OWNERS.remove(work,this);
            }
        }
    }
    /** Bounded importer metadata changes invalidate inspection reuse without
     * hashing the multi-gigabyte immutable archive set on ordinary starts. */
    private static String importMetadata(Path source)throws IOException {
        try {
            java.security.MessageDigest digest=java.security.MessageDigest.getInstance("SHA-256");
            Path generations=source.getParent().getParent(),at=source.getParent();Set<String> seen=new HashSet<>();long total=0;
            while(true) {
                String name=at.getFileName().toString();
                if(!name.matches("[0-9a-f]{64}")||!seen.add(name)||seen.size()>32)throw new IOException("Invalid stock import ancestry");
                for(String record:Arrays.asList("complete","journal.tsv")) {
                    Path file=at.resolve(record);long size=Files.size(file);
                    total+=size;if(total>(64L<<20))throw new IOException("Stock import metadata exceeds64MiB");
                    digest.update((name+"/"+record+"\n"+size+"\n").getBytes(StandardCharsets.US_ASCII));
                    updateDigest(file,record.equals("complete")?2048:32L<<20,digest);
                }
                Path parent=at.resolve("base-ready");
                if(!Files.exists(parent,LinkOption.NOFOLLOW_LINKS))break;
                byte[] bytes=read(parent,66);String next=new String(bytes,StandardCharsets.US_ASCII);
                if(!next.matches("[0-9a-f]{64}\\n"))throw new IOException("Invalid stock import parent");
                digest.update(bytes);at=generations.resolve(next.substring(0,64));
            }
            StringBuilder result=new StringBuilder();for(byte value:digest.digest())result.append(String.format(Locale.ROOT,"%02x",value&255));return result.toString();
        }catch(java.security.NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
    private static void updateDigest(Path file,long maximum,java.security.MessageDigest digest)throws IOException {
        if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||!file.equals(file.toRealPath())||Files.size(file)>maximum)throw new IOException("Invalid bounded stock import metadata");
        java.nio.file.attribute.BasicFileAttributes before=Files.readAttributes(file,java.nio.file.attribute.BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);long count=0;
        try(InputStream input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS)) {byte[] block=new byte[128<<10];for(int got;(got=input.read(block))!=-1;){count+=got;if(count>maximum)throw new IOException("Stock metadata grew beyond bound");digest.update(block,0,got);io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy.consumed(file,count-got,got);}}
        java.nio.file.attribute.BasicFileAttributes after=Files.readAttributes(file,java.nio.file.attribute.BasicFileAttributes.class,LinkOption.NOFOLLOW_LINKS);
        if(count!=before.size()||count!=after.size()||!before.lastModifiedTime().equals(after.lastModifiedTime()))throw new IOException("Stock import metadata changed during inspection reuse check");
    }
    private static String sha256(byte[] bytes)throws IOException {
        try {StringBuilder result=new StringBuilder();for(byte value:java.security.MessageDigest.getInstance("SHA-256").digest(bytes))result.append(String.format(Locale.ROOT,"%02x",value&255));return result.toString();}
        catch(java.security.NoSuchAlgorithmException impossible){throw new IOException("SHA-256 unavailable",impossible);}
    }
    private static byte[] read(Path file,int maximum)throws IOException {
        if(!Files.isRegularFile(file,LinkOption.NOFOLLOW_LINKS)||!file.equals(file.toRealPath())||Files.size(file)>maximum)throw new IOException("Missing or excessive stock inspection report");
        try(InputStream input=Files.newInputStream(file,LinkOption.NOFOLLOW_LINKS);ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            byte[] block=new byte[4096];for(int count;(count=input.read(block))!=-1;){if(output.size()+count>maximum)throw new IOException("Stock report grew beyond bound");output.write(block,0,count);}return output.toByteArray();
        }
    }
    private static void check(RuntimeWork.Cancellation stop)throws RuntimeWork.CancelledException {if(stop.isCancelled()||Thread.currentThread().isInterrupted())throw new RuntimeWork.CancelledException();}
    private static void background(){if(Looper.myLooper()==Looper.getMainLooper())throw new IllegalStateException("Stock setup must run off the UI thread");}
}
