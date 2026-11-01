package io.github.russianranger.esteria;

import android.content.Context;
import android.util.Xml;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.diagnostics.SupportLogSelection;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.runtime.PreparationChildFixture;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.Test;
import org.junit.runner.RunWith;
import org.xmlpull.v1.XmlPullParser;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public final class WorldPreparationDiagnosticsTest {
    private static Context context(){return InstrumentationRegistry.getInstrumentation().getTargetContext();}
    private static Path temporary()throws Exception{return Files.createTempDirectory(context().getFilesDir().toPath(),"world-diagnostic-").toRealPath();}
    private static void remove(Path root)throws Exception{try(var paths=Files.walk(root)){for(Path p:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(p);}}
    private static Map<String,Path> logs(Path root){String op="a".repeat(32);return Map.of(
        "setup.data.stdout.log",root.resolve("state/server-data-operations/"+op+"/logs/stdout.log"),
        "setup.turnip.stderr.log",root.resolve("state/turnip-probe-operations/"+op+"/logs/stderr.log"));}
    private static String persistedPreference(String name)throws Exception{
        Path xml=context().getFilesDir().getParentFile().toPath().resolve("shared_prefs/"+name+".xml");
        try(InputStream input=Files.newInputStream(xml)){
            XmlPullParser parser=Xml.newPullParser();parser.setInput(input,"UTF-8");
            for(int type=parser.getEventType();type!=XmlPullParser.END_DOCUMENT;type=parser.next())
                if(type==XmlPullParser.START_TAG&&"string".equals(parser.getName())&&"ownedSupportLogs".equals(parser.getAttributeValue(null,"name")))return parser.nextText();
        }
        return null;
    }
    @Test public void actualSharedPreferencesXmlRoundTripPreservesOwnedLogRecords()throws Exception{
        Path root=temporary();String name="world-log-roundtrip-"+UUID.randomUUID().toString().replace("-","");
        try{
            String stored=SupportLogSelection.encodePreference(root,logs(root));
            assertFalse(stored.contains("\n"));assertFalse(stored.contains("\t"));
            assertTrue(context().getSharedPreferences(name,Context.MODE_PRIVATE).edit().putString("ownedSupportLogs",stored).commit());
            String actual=persistedPreference(name);
            assertEquals("Single-line preference envelope must round-trip actual XML exactly",stored,actual);
            assertEquals(logs(root),SupportLogSelection.recoverPreference(root,actual).logs);
            String legacy=SupportLogSelection.encode(root,logs(root));
            assertTrue(context().getSharedPreferences(name,Context.MODE_PRIVATE).edit().putString("ownedSupportLogs",legacy).commit());
            actual=persistedPreference(name);assertNotNull(actual);assertTrue(actual.startsWith(legacy));
            for(int i=legacy.length();i<actual.length();i++)assertEquals(' ',actual.charAt(i));
            assertEquals("Only serializer-added outer spaces are normalized",logs(root),SupportLogSelection.recoverPreference(root,actual).logs);
            assertEquals(logs(root),SupportLogSelection.recoverPreference(root,legacy+"    ").logs);
            try{SupportLogSelection.decode(root,legacy+"    ");fail("Strict legacy decoder accepted XML padding");}catch(java.io.IOException expected){}
        }finally{context().deleteSharedPreferences(name);remove(root);}
    }
    @Test public void oneInvalidRetainedRolePreservesOtherStrictlyValidatedLogs()throws Exception{
        Path root=temporary();try{
            String encoded=SupportLogSelection.encode(root,logs(root)).replace("server-data-operations/","server-data-work/");
            try{SupportLogSelection.decode(root,encoded);fail("Strict decoder accepted invalid role");}catch(java.io.IOException expected){}
            SupportLogSelection.Recovery recovery=SupportLogSelection.recoverPreference(root,encoded+"    ");
            assertEquals(1,recovery.rejected);assertEquals(1,recovery.logs.size());assertTrue(recovery.logs.containsKey("setup.turnip.stderr.log"));
            assertEquals(recovery.logs,SupportLogSelection.decode(root,SupportLogSelection.encode(root,recovery.logs)));
            assertTrue(recovery.reason.length()>0&&recovery.reason.length()<128);
            String frame=SupportLogSelection.encodePreference(root,logs(root));String prefix=frame.substring(0,frame.indexOf(':')+1);
            String privateRecord=SupportLogSelection.encode(root,logs(root)).replace("state/server-data-operations/"+"a".repeat(32)+"/logs/stdout.log","config/private.log");
            recovery=SupportLogSelection.recoverPreference(root,prefix+java.util.Base64.getEncoder().encodeToString(privateRecord.getBytes(java.nio.charset.StandardCharsets.US_ASCII)));
            assertEquals(1,recovery.rejected);assertEquals(1,recovery.logs.size());assertTrue(recovery.logs.containsKey("setup.turnip.stderr.log"));
            String unsafe=SupportLogSelection.encode(root,logs(root)).replace("logs/stdout.log\n","logs/stdout.log \n");
            recovery=SupportLogSelection.recoverPreference(root,unsafe+"    ");assertEquals(1,recovery.rejected);assertFalse(recovery.logs.containsKey("setup.data.stdout.log"));
        }finally{remove(root);}
    }
    @Test public void phaseAndRealOwnedChildObservationSurviveDiagnosticReconstruction()throws Exception{
        Path root=temporary();try{
            Path receipt=root.resolve("last.properties");WorldPreparationDiagnostics diagnostics=new WorldPreparationDiagnostics(receipt);
            diagnostics.begin("PREPARE_WORLD");diagnostics.phase("world-admission-data-tools","");
            assertEquals("world-admission-data-tools",new WorldPreparationDiagnostics(receipt).facts().get("preparation.last.phase"));
            diagnostics.phase("server-data-child-launch","");
            assertEquals("server-data-child-launch",new WorldPreparationDiagnostics(receipt).facts().get("preparation.last.phase"));
            diagnostics.child("android-real-child",PreparationChildFixture.sample(root));diagnostics.checkpoint();
            Map<String,String> retained=new WorldPreparationDiagnostics(receipt).facts();
            assertTrue(retained.get("preparation.last.childObservation").contains("role=android-real-child"));
            assertTrue(retained.get("preparation.last.childObservation").contains("wholeGroupMembershipVerified=false"));
            assertEquals("running",retained.get("preparation.last.result"));
            try{io.github.russianranger.esteria.core.runtime.install.RuntimeWork.checkMemoryPressureExit(PreparationChildFixture.exit(root,75));fail("Typed memory exit was ignored after parent memory recovered");}
            catch(io.github.russianranger.esteria.core.runtime.install.RuntimeWork.MemoryPressureException paused){diagnostics.failed(paused);}
            assertEquals("paused-memory",new WorldPreparationDiagnostics(receipt).facts().get("preparation.last.result"));
            diagnostics.begin("PREPARE_WORLD");io.github.russianranger.esteria.core.runtime.install.RuntimeWork.checkMemoryPressureExit(PreparationChildFixture.exit(root,0));diagnostics.finish("complete",null);
            assertEquals("complete",new WorldPreparationDiagnostics(receipt).facts().get("preparation.last.result"));
        }finally{remove(root);}
    }
    @Test public void parentPreparationReadsUseBoundedRealCacheAdviceAndRemainCancellable()throws Exception{
        Path root=temporary();try{
            Path source=root.resolve("source.bin");try(RandomAccessFile output=new RandomAccessFile(source.toFile(),"rw")){byte[] bytes=new byte[128<<10];for(int i=0;i<32;i++)output.write(bytes);output.getFD().sync();}
            WorldPreparationDiagnostics diagnostics=new WorldPreparationDiagnostics(root.resolve("last.properties"));diagnostics.begin("PREPARE_WORLD");
            ImportIoController controller=new ImportIoController(context(),diagnostics);AtomicBoolean cancelled=new AtomicBoolean();long began=System.nanoTime(),offset=0;
            try(io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy.Scope scope=io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy.install((path,at,count)->controller.readObserved(path,at,count,cancelled::get));InputStream input=Files.newInputStream(source)){byte[] bytes=new byte[128<<10];for(int n;(n=input.read(bytes))!=-1;){io.github.russianranger.esteria.core.runtime.install.RuntimeReadPolicy.consumed(source,offset,n);offset+=n;}}
            controller.recordFinal();assertTrue("Actual preparation policy caps this4MiB read",System.nanoTime()-began>=480000000L);
            Map<String,String> facts=new WorldPreparationDiagnostics(root.resolve("last.properties")).facts();
            assertEquals("4194304",facts.get("preparation.last.ioCacheDropBytes"));assertEquals("0",facts.get("preparation.last.ioCacheDropErrors"));
            cancelled.set(true);try{controller.readObserved(source,0,1,cancelled::get);fail("Cancelled preparation continued");}catch(GameDataImporter.ImportCancelledException expected){diagnostics.failed(expected);assertEquals("paused",new WorldPreparationDiagnostics(root.resolve("last.properties")).facts().get("preparation.last.result"));}
        }finally{remove(root);}
    }
}
