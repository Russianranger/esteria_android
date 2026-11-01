package io.github.russianranger.esteria;

import io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.Set;

/** Durable preparation checkpoint. Contains no client bytes, commands or credentials. */
final class WorldPreparationDiagnostics implements ImportIoController.Diagnostics {
    private static final int MAX_BYTES=32<<10;
    private static final Set<String> KEYS=Set.of("action","result","phase","path","failure","startedAtEpochMs","updatedAtEpochMs",
        "childObservation","childSampleAtEpochMs","javaHeapUsedBytes","javaHeapPeakObservedBytes","javaHeapLimitBytes",
        "ioPolicy","ioNormalBytesPerSecond","ioPressureBytesPerSecond","ioPressureLevel","ioActiveBytesPerSecond",
        "ioMemoryAvailableBytes","ioMemoryThresholdBytes","ioMemoryLow","ioMemorySampleAtEpochMs","ioTrimLevel","ioTrimAtEpochMs",
        "ioCacheDropCalls","ioCacheDropBytes","ioCacheDropErrors","ioCacheDropErrno","ioCacheDropStatus",
        "ioSystemDirtyKiB","ioSystemWritebackKiB","ioSystemDirtyPeakKiB","ioSystemWritebackPeakKiB");
    private final Path receipt;
    private final Map<String,String> values=new LinkedHashMap<>();
    private long savedAt,memoryAt,peakHeap;
    WorldPreparationDiagnostics(Path receipt){
        this.receipt=receipt;
        try{
            if(!Files.isRegularFile(receipt,LinkOption.NOFOLLOW_LINKS)||Files.size(receipt)>MAX_BYTES)return;
            Properties properties=new Properties();properties.load(new ByteArrayInputStream(Files.readAllBytes(receipt)));
            if(properties.size()>64)return;
            for(String key:properties.stringPropertyNames())if(allowed(key))values.put(key,bounded(properties.getProperty(key),8192));
        }catch(IOException|RuntimeException unavailable){values.clear();}
    }
    synchronized void begin(String action){
        values.clear();values.put("action",bounded(action,128));values.put("result","running");
        values.put("startedAtEpochMs",Long.toString(System.currentTimeMillis()));
        values.put("phase","preparation-admission");peakHeap=0;memoryAt=0;memory();checkpoint();
    }
    synchronized void phase(String phase,String path){
        boolean changed=!phase.equals(values.get("phase"));
        values.put("phase",bounded(phase,128));values.put("path",bounded(path,1024));
        values.put("updatedAtEpochMs",Long.toString(System.currentTimeMillis()));
        if(changed||System.nanoTime()-savedAt>2_000_000_000L)checkpoint();
    }
    synchronized void finish(String result,Throwable failure){
        values.put("result",bounded(result,64));if(failure!=null)values.put("failure",bounded(ImportDiagnostics.failure(failure),8192));checkpoint();
    }
    synchronized void failed(Throwable failure){
        boolean memory=failure instanceof MemoryPause||failure instanceof io.github.russianranger.esteria.core.runtime.install.RuntimeWork.MemoryPressureException
                ||failure instanceof io.github.russianranger.esteria.core.importer.GameDataImporter.ImportMemoryPressureException;
        boolean cancelled=failure instanceof io.github.russianranger.esteria.core.runtime.install.RuntimeWork.CancelledException
                ||failure instanceof io.github.russianranger.esteria.core.importer.GameDataImporter.ImportCancelledException;
        finish(memory?"paused-memory":cancelled?"paused":"failed",failure);
    }
    synchronized void child(String role,ProcessUsageSnapshot sample){
        if(sample==null)return;
        values.put("childObservation","role="+bounded(role,64)+"; scope="+sample.scope()+"; flags="+sample.flags
            +"; visibleMembers="+sample.visibleMembers+"; scanned="+sample.scannedProcesses
            +"; rssCoverage="+sample.rssMeasuredMembers+"; pssCoverage="+sample.pssMeasuredMembers
            +"; visibleRssBytes="+(sample.visibleMembersRssBytes().isPresent()?sample.visibleMembersRssBytes().getAsLong():"unavailable")
            +"; visiblePssBytes="+(sample.visibleMembersPssBytes().isPresent()?sample.visibleMembersPssBytes().getAsLong():"unavailable")
            +"; wholeGroupMembershipVerified=false");
        values.put("childSampleAtEpochMs",Long.toString(System.currentTimeMillis()));
    }
    public synchronized void io(String key,long value){io(key,Long.toString(value));}
    public synchronized void io(String key,String value){
        if(!key.startsWith("io")||!allowed(key))throw new IllegalArgumentException("Unknown bounded preparation observation");
        values.put(key,bounded(value,256));if(System.nanoTime()-savedAt>2_000_000_000L)checkpoint();
    }
    public synchronized void memory(){
        long now=System.nanoTime();if(memoryAt!=0&&now-memoryAt<1_000_000_000L)return;memoryAt=now;
        Runtime vm=Runtime.getRuntime();long used=vm.totalMemory()-vm.freeMemory();peakHeap=Math.max(peakHeap,used);
        values.put("javaHeapUsedBytes",Long.toString(used));values.put("javaHeapPeakObservedBytes",Long.toString(peakHeap));
        values.put("javaHeapLimitBytes",Long.toString(vm.maxMemory()));
    }
    synchronized Map<String,String> facts(){
        Map<String,String> facts=new LinkedHashMap<>();for(Map.Entry<String,String> entry:values.entrySet())facts.put("preparation.last."+entry.getKey(),entry.getValue());return facts;
    }
    public synchronized void checkpoint(){
        try{
            Properties properties=new Properties();properties.putAll(values);ByteArrayOutputStream bytes=new ByteArrayOutputStream();
            properties.store(bytes,"Bounded last world preparation; no game assets or credentials");if(bytes.size()>MAX_BYTES)return;
            Files.createDirectories(receipt.getParent());Path temporary=receipt.resolveSibling(receipt.getFileName()+".tmp");
            try(FileChannel output=FileChannel.open(temporary,StandardOpenOption.CREATE,StandardOpenOption.TRUNCATE_EXISTING,StandardOpenOption.WRITE)){
                ByteBuffer buffer=ByteBuffer.wrap(bytes.toByteArray());while(buffer.hasRemaining())output.write(buffer);output.force(true);
            }
            Files.move(temporary,receipt,StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE);savedAt=System.nanoTime();
        }catch(IOException|RuntimeException unavailable){/* Diagnostic failure never activates or reseeds data. */}
    }
    private static boolean allowed(String key){return key!=null&&KEYS.contains(key);}
    private static String bounded(String value,int maximum){if(value==null)return "";return value.length()<=maximum?value:value.substring(0,maximum)+"[truncated]";}
    static final class MemoryPause extends RuntimeException{
        private static final long serialVersionUID=1L;
        MemoryPause(){super("World preparation paused because Android memory is low. Completed work and saves are retained; retry preparation after memory recovers.");}
    }
}
