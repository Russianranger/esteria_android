package io.github.russianranger.esteria.core.importer;

import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.concurrent.atomic.AtomicBoolean;

/** Actual host file descriptors with provider-origin/length accounting and
 * bounded nonseekable streams. These fixtures do not execute Android providers. */
public final class SourceStreamPositionerTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    @FunctionalInterface private interface Attempt{void run()throws Exception;}
    private static void fails(Attempt attempt)throws Exception {
        try{attempt.run();}catch(IOException expected){return;}throw new AssertionError("Expected resume refusal");
    }
    /** Mirrors the relevant Android13 AssetFileDescriptor stream contract:
     * the FD starts at an origin and relative skip decrements a separate bound. */
    private static final class Slice extends FileInputStream {
        private long remaining;
        Slice(Path file,long origin,long length)throws IOException {
            super(file.toFile());check(super.skip(origin)==origin,"Fixture origin");remaining=length;
        }
        @Override public long skip(long count)throws IOException {
            if(remaining==0)return -1;
            long got=super.skip(Math.min(count,remaining));if(got>=0)remaining-=got;return got;
        }
        @Override public int read(byte[] bytes,int offset,int count)throws IOException {
            if(remaining==0)return -1;
            int got=super.read(bytes,offset,(int)Math.min(count,remaining));if(got>=0)remaining-=got;return got;
        }
        @Override public int read(byte[] bytes)throws IOException{return read(bytes,0,bytes.length);}
        @Override public int read()throws IOException {byte[] byteValue=new byte[1];return read(byteValue)==-1?-1:byteValue[0]&255;}
    }
    private static final class FastFile extends FileInputStream {
        int skipCalls,readCalls;long largestSkip;
        FastFile(Path file)throws IOException{super(file.toFile());}
        @Override public long skip(long count)throws IOException{skipCalls++;largestSkip=Math.max(largestSkip,count);return super.skip(count);}
        @Override public int read(byte[] bytes,int offset,int length)throws IOException{readCalls++;return super.read(bytes,offset,length);}
    }
    private static class Nonseekable extends InputStream {
        int position,reads,largestRead;boolean cancelOnRead;
        final AtomicBoolean cancelled=new AtomicBoolean();
        @Override public long skip(long count){return 0;}
        @Override public int read(){throw new AssertionError("Resume must use bounded bulk reads");}
        @Override public int read(byte[] bytes,int offset,int count){
            reads++;largestRead=Math.max(largestRead,count);
            for(int i=0;i<count;i++)bytes[offset+i]=(byte)position++;
            if(cancelOnRead)cancelled.set(true);return count;
        }
    }
    public static void run()throws Exception {
        Path root=Files.createTempDirectory("esteria-source-position-").toRealPath();
        try {
            byte[] prefix="PRIVATE_PREFIX".getBytes(StandardCharsets.US_ASCII),payload="123456789".getBytes(StandardCharsets.US_ASCII);
            Path sliced=root.resolve("slice.bin");
            Files.write(sliced,("PRIVATE_PREFIX123456789PRIVATE_SUFFIX").getBytes(StandardCharsets.US_ASCII));
            try(Slice broken=new Slice(sliced,prefix.length,payload.length)) {
                broken.getChannel().position(4);byte[] wrong=broken.readNBytes(5);
                check(!Arrays.equals(wrong,"56789".getBytes(StandardCharsets.US_ASCII)),"Actual descriptor fixture must expose the old absolute-position defect");
            }
            try(Slice input=new Slice(sliced,prefix.length,payload.length)) {
                SourceStreamPositioner.advance(input,4,GameDataImporter.NEVER_CANCELLED);
                check(Arrays.equals(input.readNBytes(32),"56789".getBytes(StandardCharsets.US_ASCII))&&input.read()==-1,
                        "Resume remains relative and does not expose the backing-file suffix");
            }
            try(Slice input=new Slice(sliced,prefix.length,payload.length)) {
                SourceStreamPositioner.advance(input,payload.length,GameDataImporter.NEVER_CANCELLED);
                check(input.read()==-1,"Exact slice-end resume updates provider remaining bytes");
            }
            try(Slice input=new Slice(sliced,prefix.length,payload.length)) {
                fails(()->SourceStreamPositioner.advance(input,payload.length+1,GameDataImporter.NEVER_CANCELLED));
                check(input.read()==-1,"Truncated provider cannot resume into a private backing-file suffix");
            }
            long largeOffset=(5L<<30)+17;Path sparse=root.resolve("large-sparse.bin");
            try(RandomAccessFile file=new RandomAccessFile(sparse.toFile(),"rw")) {file.seek(largeOffset);file.write(new byte[]{'E','N','D'});}
            try(FastFile input=new FastFile(sparse)) {
                SourceStreamPositioner.advance(input,largeOffset,GameDataImporter.NEVER_CANCELLED);
                check(input.readCalls==0&&input.skipCalls>1&&input.skipCalls<6000&&input.largestSkip<=1L<<20,
                        "Five-GiB file resume uses native relative skipping with bounded cancellation intervals, no payload reads");
                check(Arrays.equals(input.readNBytes(3),new byte[]{'E','N','D'})&&input.read()==-1,"Long resume offset does not truncate to32bits");
            }
            Nonseekable pipe=new Nonseekable();int offset=(128<<10)+7;
            SourceStreamPositioner.advance(pipe,offset,GameDataImporter.NEVER_CANCELLED);
            check(pipe.position==offset&&pipe.reads==5&&pipe.largestRead<=32<<10,"Zero-skip source advances with32KiB bounded bulk reads");
            Nonseekable cancelled=new Nonseekable();cancelled.cancelOnRead=true;
            try{SourceStreamPositioner.advance(cancelled,4L<<30,cancelled.cancelled::get);throw new AssertionError("Cancelled resume accepted");}
            catch(GameDataImporter.ImportCancelledException expected){check(cancelled.reads==1,"Cancellation is observed before another bulk read");}
            InputStream ambiguous=new InputStream(){
                @Override public long skip(long count)throws IOException{throw new IOException("TEST_ONLY_AMBIGUOUS_SKIP_PROGRESS");}
                @Override public int read(){throw new AssertionError("Failed skip must never fall back or retry");}
                @Override public int read(byte[] b,int o,int l){throw new AssertionError("Failed skip must never fall back or retry");}
            };
            fails(()->SourceStreamPositioner.advance(ambiguous,10,GameDataImporter.NEVER_CANCELLED));
            fails(()->SourceStreamPositioner.advance(new java.io.ByteArrayInputStream(new byte[3]),4,GameDataImporter.NEVER_CANCELLED));
            fails(()->SourceStreamPositioner.advance(new Nonseekable(){@Override public int read(byte[] b,int o,int l){return 0;}},10,GameDataImporter.NEVER_CANCELLED));
            fails(()->SourceStreamPositioner.advance(new Nonseekable(){@Override public long skip(long count){return count+1;}},10,GameDataImporter.NEVER_CANCELLED));
        } finally {
            try(var paths=Files.walk(root)){for(Path path:paths.sorted(java.util.Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
        }
    }
    public static void main(String[] arguments)throws Exception{run();System.out.println("Provider-relative resume fixtures passed; host FD/stream behavior only, no Android provider execution");}
}
