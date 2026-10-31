package io.github.russianranger.esteria;

import android.content.ComponentCallbacks2;
import android.os.ParcelFileDescriptor;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.ImportIoGovernor;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
@SuppressWarnings("deprecation")
public final class ImportIoControllerTest {
    private static Path temporary() throws Exception {
        return Files.createTempDirectory(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir().toPath(), "import-io-");
    }
    @Test public void trimSignalsAndSystemHeadroomSelectTheCorrectPolicy() throws Exception {
        assertEquals(0, ImportIoController.trimPressure(ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN));
        assertEquals(1, ImportIoController.trimPressure(ComponentCallbacks2.TRIM_MEMORY_RUNNING_LOW));
        assertEquals(2, ImportIoController.trimPressure(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL));
        assertEquals(0, ImportIoController.pressureLevel(4L<<30,256L<<20,false,16L<<20,256L<<20,0));
        assertEquals(1, ImportIoController.pressureLevel(400L<<20,256L<<20,false,16L<<20,256L<<20,0));
        assertEquals(2, ImportIoController.pressureLevel(4L<<30,256L<<20,true,16L<<20,256L<<20,0));
        assertEquals(2, ImportIoController.pressureLevel(4L<<30,256L<<20,false,240L<<20,256L<<20,0));
        Path root=temporary();
        try {
            ImportIoController controller=new ImportIoController(InstrumentationRegistry.getInstrumentation().getTargetContext(),new ImportDiagnostics(root.resolve("unused.properties")));
            controller.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN);assertEquals(0,controller.recentTrimPressure());
            controller.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_RUNNING_CRITICAL);
            controller.onTrimMemory(ComponentCallbacks2.TRIM_MEMORY_UI_HIDDEN);assertEquals(2,controller.recentTrimPressure());
        } finally {Files.delete(root);}
    }
    @Test public void nativeCacheAdvicePreservesSyncedFileBytes() throws Exception {
        Path root=temporary(), path=root.resolve("synced.bin");
        try {
            try(RandomAccessFile file=new RandomAccessFile(path.toFile(),"rw")) {
                byte[] block=new byte[65536]; for(int i=0;i<block.length;i++)block[i]=(byte)i;
                for(int i=0;i<33;i++)file.write(block); file.getFD().sync();
                try(ParcelFileDescriptor fd=ParcelFileDescriptor.open(path.toFile(),ParcelFileDescriptor.MODE_READ_ONLY)) {
                    assertEquals("Compiled native advisory cache helper must execute",0,NativeImportCache.drop(fd.getFd(),0,file.length()));
                }
                assertEquals(22,NativeImportCache.drop(-1,0,1));
                file.seek(0);byte[] actual=new byte[block.length];file.readFully(actual);assertArrayEquals(block,actual);
                file.seek(file.length()-block.length);file.readFully(actual);assertArrayEquals(block,actual);
            }
        } finally {Files.deleteIfExists(path);Files.delete(root);}
    }
    @Test public void severePressureBlocksWritesAndStopRemainsPrompt() throws Exception {
        AtomicInteger pressure=new AtomicInteger(2);AtomicBoolean cancel=new AtomicBoolean();AtomicReference<Throwable> result=new AtomicReference<>();
        ImportIoGovernor governor=new ImportIoGovernor(8L<<20,2L<<20,pressure::get,(p,o,n)->{});
        Thread worker=new Thread(()->{try{governor.checkpoint(cancel::get);result.set(new AssertionError("Pressure checkpoint passed before recovery"));}catch(Throwable failure){result.set(failure);}});
        worker.start();Thread.sleep(250);assertTrue("Severe pressure waits before further I/O",worker.isAlive());
        long began=System.nanoTime();cancel.set(true);worker.join(1500);assertFalse("Stop remains interruptible",worker.isAlive());
        assertTrue(result.get() instanceof GameDataImporter.ImportCancelledException);assertTrue((System.nanoTime()-began)<1500000000L);
        pressure.set(0);governor.checkpoint(()->false);
    }
    @Test public void controllerPersistsRealSyncCacheAndSystemPressureObservations() throws Exception {
        Path root=temporary(), output=root.resolve("out.bin"), receipt=root.resolve("import.properties");
        try {
            ImportDiagnostics diagnostics=new ImportDiagnostics(receipt);diagnostics.begin("folder","BASE_CLIENT","fixture","opaque","test");
            ImportIoController controller=new ImportIoController(InstrumentationRegistry.getInstrumentation().getTargetContext(),diagnostics);
            try(FileChannel channel=FileChannel.open(output,java.nio.file.StandardOpenOption.CREATE,java.nio.file.StandardOpenOption.WRITE)) {
                ImportIoGovernor.Transfer transfer=controller.governor().begin(output,channel,0,()->false);
                ByteBuffer block=ByteBuffer.allocate(128<<10);
                for(int i=0;i<17;i++){block.clear();while(block.hasRemaining())channel.write(block);transfer.wrote(block.capacity());}
                transfer.finish();
            }
            controller.recordFinal();Map<String,String> facts=new ImportDiagnostics(receipt).facts();
            assertEquals("8388608",facts.get("import.last.ioNormalBytesPerSecond"));
            assertEquals("2097152",facts.get("import.last.ioPressureBytesPerSecond"));
            assertTrue(Long.parseLong(facts.get("import.last.ioMemoryAvailableBytes"))>0);
            assertTrue(Long.parseLong(facts.get("import.last.ioCacheDropCalls"))>=2);
            assertEquals("0",facts.get("import.last.ioCacheDropErrors"));
            assertEquals(17L*(128<<10),Long.parseLong(facts.get("import.last.ioCacheDropBytes")));
        } finally {Files.deleteIfExists(output);Files.deleteIfExists(receipt);Files.delete(root);}
    }
}
