package io.github.russianranger.esteria;

import android.content.*;
import android.content.pm.ProviderInfo;
import android.content.res.AssetFileDescriptor;
import android.database.*;
import android.net.Uri;
import android.os.*;
import android.provider.DocumentsContract;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import java.io.*;
import java.nio.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.util.zip.*;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real Android resolver/pipe/SAF/ZIP imports. Generated structural fixtures are not game assets.
 * One 64KiB generator block supplies GiB payloads without buffering a client in either process. */
@RunWith(AndroidJUnit4.class)
public final class ImportMemoryStressTest {
    private static final long GIB=1L<<30, MODIFIED=1700000000000L;
    private static final String LARGE="Data/common.MPQ";
    private static Path temporary()throws IOException{return Files.createTempDirectory(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir().toPath(),"import-memory-").toRealPath();}
    private static void remove(Path root)throws IOException{try(var paths=Files.walk(root)){for(Path p:(Iterable<Path>)paths.sorted(Comparator.reverseOrder())::iterator)Files.delete(p);}}
    private static long javaBytes(){Runtime r=Runtime.getRuntime();return r.totalMemory()-r.freeMemory();}
    private static final class Samples implements GameDataImporter.ProgressListener {
        final ImportDiagnostics diagnostics;
        final long initialJava=javaBytes(),initialNative=Debug.getNativeHeapAllocatedSize(),initialPss=Debug.getPss()*1024L;
        long peakJava=initialJava,peakNative=initialNative,peakPss=initialPss,next;int count;
        Samples(Path root,String route){diagnostics=new ImportDiagnostics(root.resolve("diagnostics/import-last.properties"));diagnostics.begin(route,"BASE_CLIENT","fixture","generated-source","Generated client");}
        public void onDiagnostic(String phase,String detectedRoot,String path){diagnostics.phase(phase,detectedRoot,path);}
        public void onProgress(String path,long bytes,long total,int finished,int files){diagnostics.memory();if(bytes>=next||finished==files||(finished>0&&finished%128==0)){sample();next=bytes+(64L<<20);}}
        void sample(){peakJava=Math.max(peakJava,javaBytes());peakNative=Math.max(peakNative,Debug.getNativeHeapAllocatedSize());peakPss=Math.max(peakPss,Debug.getPss()*1024L);count++;}
        JSONObject result(String route)throws Exception{return new JSONObject().put("route",route).put("samples",count).put("initialJavaBytes",initialJava).put("peakJavaBytes",peakJava).put("javaGrowthBytes",peakJava-initialJava).put("initialNativeBytes",initialNative).put("peakNativeBytes",peakNative).put("nativeGrowthBytes",peakNative-initialNative).put("initialPssBytes",initialPss).put("peakPssBytes",peakPss).put("pssGrowthBytes",peakPss-initialPss);}
        void requireBounded(){assertTrue("Java working memory must not scale with payload",peakJava-initialJava<(48L<<20));assertTrue("Native working memory must not scale with payload",peakNative-initialNative<(32L<<20));assertTrue("Resident working memory stays bounded",peakPss-initialPss<(96L<<20));}
    }
    private static void report(JSONObject value)throws Exception{value.put("scope","android13-generated-structural-client-memory-fixture").put("ownerData",false).put("thorQualified",false).put("gameplayQualified",false);Bundle b=new Bundle();b.putString("stream","IMPORT_MEMORY_STRESS="+value+"\n");InstrumentationRegistry.getInstrumentation().sendStatus(2,b);}
    @Test public void gibibyteFolderAndNonseekableZipImportsKeepBoundedMemory()throws Exception{
        for(String route:List.of("folder","zip")){
            Path root=temporary();try{
                assertTrue("Disposable 4GiB userdata must fit staged ZIP plus imported GiB",root.toFile().getUsableSpace()>(2300L<<20));
                Provider provider=new Provider(GIB,0);ContentResolver resolver=ContentResolver.wrap(provider);AtomicBoolean cancel=new AtomicBoolean();Samples samples=new Samples(root,route);long began=System.nanoTime();GameDataImporter importer=new GameDataImporter(root.resolve("store"));GameDataImporter.Result result;
                if(route.equals("folder")){try(SafTreeSource source=new SafTreeSource(resolver,provider.tree(),cancel,(f,d,t)->{})){result=importer.importSource(source,GameDataImporter.ImportKind.BASE_CLIENT,samples,cancel::get);}}
                else{Path zip=UriStager.stage(resolver,provider.archiveUri(),root.resolve("stage"),cancel,(n,t)->samples.onProgress("zip-document-copy",n,t,0,1));assertTrue("Exercise large ZIP copy rather than tiny compressed zeros",Files.size(zip)>=GIB);samples.sample();samples.next=0;result=importer.importZip(zip,GameDataImporter.ImportKind.BASE_CLIENT,samples,cancel::get);}
                samples.diagnostics.finish("complete",null);samples.sample();provider.requireFinished();samples.requireBounded();assertEquals(GIB,Files.size(result.gameDirectory.resolve(LARGE)));assertEquals(provider.fileCount(),result.copiedFiles);
                String digest=null;for(String line:Files.readAllLines(result.gameDirectory.getParent().resolve("journal.tsv"),StandardCharsets.UTF_8)){String[] f=line.split("\t");if(new String(Base64.getDecoder().decode(f[0]),StandardCharsets.UTF_8).equals(LARGE))digest=f[3];}
                assertNotNull("Provider completed streamed source digest",provider.largeDigest.get());assertEquals("Actual journal matches streamed source",provider.largeDigest.get(),digest);
                report(samples.result(route).put("payloadBytes",GIB).put("copiedFiles",result.copiedFiles).put("copiedBytes",result.copiedBytes).put("sha256",digest).put("elapsedMillis",(System.nanoTime()-began)/1000000L));
            }finally{remove(root);}
        }
    }
    @Test public void thousandsOfOpaqueDocumentsStayBoundedAndSourceChecksRemainActive()throws Exception{
        Path root=temporary();try{Provider provider=new Provider(64,3200);AtomicBoolean cancel=new AtomicBoolean();Samples samples=new Samples(root,"opaque-inventory");GameDataImporter.Result result;
            try(SafTreeSource source=new SafTreeSource(ContentResolver.wrap(provider),provider.tree(),cancel,(f,d,t)->samples.sample())){result=new GameDataImporter(root.resolve("store")).importSource(source,GameDataImporter.ImportKind.BASE_CLIENT,samples,cancel::get);}
            samples.diagnostics.finish("complete",null);samples.sample();provider.requireFinished();samples.requireBounded();assertEquals(3210,result.copiedFiles);assertEquals(provider.fileCount(),result.copiedFiles);report(samples.result("opaque-inventory").put("documents",result.copiedFiles).put("opaqueIdCharacters",provider.records.get(0).id.length()).put("sourceQueries",provider.queries));
        }finally{remove(root);}
    }
    private static byte[] mpq(long bytes){ByteBuffer b=ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);b.putInt(0,0x1a51504d);b.putInt(4,32);b.putInt(8,(int)bytes);b.putShort(14,(short)3);b.putInt(16,32);b.putInt(20,48);b.putInt(24,1);b.putInt(28,1);return b.array();}
    private static byte[] pe(){
        ByteBuffer b=ByteBuffer.allocate(1024).order(ByteOrder.LITTLE_ENDIAN);b.putShort(0,(short)0x5a4d);b.putInt(0x3c,0x80);b.putInt(0x80,0x4550);b.putShort(0x84,(short)0x14c);b.putShort(0x86,(short)1);b.putShort(0x94,(short)224);
        int o=0x98;b.putShort(o,(short)0x10b);b.putInt(o+92,16);b.putInt(o+112,0x1000);b.putInt(o+116,512);int s=o+224;b.putInt(s+8,512);b.putInt(s+12,0x1000);b.putInt(s+16,512);b.putInt(s+20,512);
        int r=512;b.putShort(r+14,(short)1);b.putInt(r+16,16);b.putInt(r+20,0x80000020);b.putShort(r+46,(short)1);b.putInt(r+48,1);b.putInt(r+52,0x80000040);b.putShort(r+78,(short)1);b.putInt(r+80,1033);b.putInt(r+84,96);b.putInt(r+96,0x1080);b.putInt(r+100,92);
        int d=r+128;b.putShort(d,(short)92);b.putShort(d+2,(short)52);String key="VS_VERSION_INFO";for(int i=0;i<key.length();i++)b.putChar(d+6+i*2,key.charAt(i));b.putInt(d+40,0xfeef04bd);b.putInt(d+44,0x10000);b.putInt(d+48,0x30003);b.putInt(d+52,(5<<16)|12340);return b.array();
    }
    private static String hex(byte[] bytes){char[] out=new char[bytes.length*2],alphabet="0123456789abcdef".toCharArray();for(int i=0;i<bytes.length;i++){out[i*2]=alphabet[(bytes[i]>>>4)&15];out[i*2+1]=alphabet[bytes[i]&15];}return new String(out);}
    private static final class Record{
        final String id,path;final boolean directory;final long bytes;final byte[] small;
        Record(int index,String path,boolean directory,long bytes,byte[] small){id="opaque:"+index+"/"+"provider-identity-".repeat(7);this.path=path;this.directory=directory;this.bytes=bytes;this.small=small;}
        String name(){return path.isEmpty()?"Generated client":path.substring(path.lastIndexOf('/')+1);}
    }
    private static final class Provider extends ContentProvider{
        static final String AUTHORITY="esteria.memory.fixture";final List<Record> records=new ArrayList<>();final Map<String,Record> ids=new LinkedHashMap<>();final AtomicReference<Throwable> failure=new AtomicReference<>();final AtomicReference<String> largeDigest=new AtomicReference<>();final Record archive;int queries;
        Provider(long largeBytes,int extras){add("",true,0,null);add("Data",true,0,null);add("Data/enUS",true,0,null);add("Wow.exe",false,1024,pe());add(LARGE,false,largeBytes,largeBytes==64?mpq(64):null);
            for(String name:List.of("common-2","expansion","lichking","patch","patch-2","patch-3"))add("Data/"+name+".MPQ",false,64,mpq(64));add("Data/enUS/locale-enUS.MPQ",false,64,mpq(64));add("Data/enUS/speech-enUS.MPQ",false,64,mpq(64));
            if(extras>0)add("Data/extra",true,0,null);byte[] tiny={1};for(int i=0;i<extras;i++)add("Data/extra/"+"long-name-".repeat(5)+i+".txt",false,1,tiny);
            archive=new Record(-1,"client.zip",false,-1,null);ids.put(archive.id,archive);var context=InstrumentationRegistry.getInstrumentation().getTargetContext();ProviderInfo info=new ProviderInfo();info.authority=AUTHORITY;info.exported=false;info.applicationInfo=context.getApplicationInfo();attachInfo(context,info);
        }
        void add(String path,boolean directory,long bytes,byte[] small){Record r=new Record(records.size(),path,directory,bytes,small);records.add(r);ids.put(r.id,r);}
        int fileCount(){return(int)records.stream().filter(r->!r.directory).count();}
        Uri tree(){return DocumentsContract.buildTreeDocumentUri(AUTHORITY,records.get(0).id);}
        Uri archiveUri(){return DocumentsContract.buildDocumentUri(AUTHORITY,archive.id);}
        void requireFinished(){if(failure.get()!=null)throw new AssertionError("Generated provider failed",failure.get());}
        public boolean onCreate(){return true;}
        public Cursor query(Uri uri,String[] projection,String selection,String[] arguments,String order){queries++;MatrixCursor cursor=new MatrixCursor(projection);Record parent=ids.get(DocumentsContract.getDocumentId(uri));if(uri.getLastPathSegment().equals("children")){for(Record child:records){String path=child.path;int slash=path.lastIndexOf('/');String owner=slash<0?"":path.substring(0,slash);if(!path.isEmpty()&&owner.equals(parent.path))row(cursor,projection,child);}}else if(parent!=null)row(cursor,projection,parent);return cursor;}
        void row(MatrixCursor cursor,String[] projection,Record r){Object[] row=new Object[projection.length];for(int i=0;i<projection.length;i++){String key=projection[i];if(DocumentsContract.Document.COLUMN_DOCUMENT_ID.equals(key))row[i]=r.id;else if(DocumentsContract.Document.COLUMN_DISPLAY_NAME.equals(key))row[i]=r.name();else if(DocumentsContract.Document.COLUMN_MIME_TYPE.equals(key))row[i]=r.directory?DocumentsContract.Document.MIME_TYPE_DIR:"application/octet-stream";else if(DocumentsContract.Document.COLUMN_SIZE.equals(key))row[i]=r.bytes;else if(DocumentsContract.Document.COLUMN_LAST_MODIFIED.equals(key))row[i]=MODIFIED;else if(DocumentsContract.Document.COLUMN_FLAGS.equals(key))row[i]=0;}cursor.addRow(row);}
        public AssetFileDescriptor openAssetFile(Uri uri,String mode,CancellationSignal signal)throws FileNotFoundException{if(signal!=null)signal.throwIfCanceled();return openAssetFile(uri,mode);}
        public AssetFileDescriptor openAssetFile(Uri uri,String mode)throws FileNotFoundException{Record r=ids.get(DocumentsContract.getDocumentId(uri));if(r==null||r.directory)throw new FileNotFoundException("Missing generated fixture");try{ParcelFileDescriptor[] pipe=ParcelFileDescriptor.createPipe();Thread writer=new Thread(()->{try(OutputStream out=new ParcelFileDescriptor.AutoCloseOutputStream(pipe[1])){if(r==archive){try(ZipOutputStream zip=new ZipOutputStream(out)){zip.setLevel(Deflater.NO_COMPRESSION);for(Record child:records)if(!child.directory){ZipEntry entry=new ZipEntry(child.path);entry.setTime(MODIFIED);zip.putNextEntry(entry);write(child,zip);zip.closeEntry();}}}else write(r,out);}catch(Throwable e){failure.compareAndSet(null,e);}},"generated-import-document");writer.setDaemon(true);writer.start();return new AssetFileDescriptor(pipe[0],0,AssetFileDescriptor.UNKNOWN_LENGTH);}catch(IOException e){throw new FileNotFoundException(e.toString());}}
        void write(Record r,OutputStream out)throws Exception{if(r.small!=null){out.write(r.small);return;}MessageDigest hash=MessageDigest.getInstance("SHA-256");byte[] header=mpq(r.bytes);out.write(header);hash.update(header);byte[] block=new byte[64*1024];new Random(123456).nextBytes(block);long left=r.bytes-header.length;while(left>0){int n=(int)Math.min(left,block.length);out.write(block,0,n);hash.update(block,0,n);left-=n;}largeDigest.set(hex(hash.digest()));}
        public String getType(Uri uri){return"application/octet-stream";}
        public Uri insert(Uri uri,ContentValues values){throw new UnsupportedOperationException();}
        public int delete(Uri uri,String where,String[] args){throw new UnsupportedOperationException();}
        public int update(Uri uri,ContentValues values,String where,String[] args){throw new UnsupportedOperationException();}
    }
}
