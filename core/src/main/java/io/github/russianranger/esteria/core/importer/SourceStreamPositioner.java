package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.io.InputStream;

/** Resumes relative to a provider stream's origin without bypassing its bounds. */
public final class SourceStreamPositioner {
    private static final long SKIP_CHUNK = 1L << 20;
    private static final int READ_CHUNK = 32 << 10;
    private SourceStreamPositioner() { }

    public static void advance(InputStream input,long offset,GameDataImporter.Cancellation cancellation)throws IOException {
        advance(input, offset, cancellation, ImportIoGovernor.unthrottled());
    }
    public static void advance(InputStream input,long offset,GameDataImporter.Cancellation cancellation,ImportIoGovernor governor)throws IOException {
        if(input==null||cancellation==null||offset<0)throw new IllegalArgumentException("Source stream, nonnegative offset and cancellation are required");
        if(governor==null)throw new IllegalArgumentException("Import I/O governor is required");
        byte[] discard=null;
        while(offset>0) {
            check(cancellation);
            governor.checkpoint(cancellation);
            long requested=Math.min(offset,SKIP_CHUNK);
            // AssetFileDescriptor streams maintain their own origin and remaining
            // length in skip(). Direct FileChannel positioning bypasses both.
            // An IOException leaves progress ambiguous and must propagate.
            long skipped=input.skip(requested);
            if(skipped<0||skipped>requested)throw new IOException("Source ended or returned an invalid resume position");
            if(skipped>0){offset-=skipped;governor.read(skipped,cancellation);continue;}
            if(discard==null)discard=new byte[READ_CHUNK];
            int requestedRead=(int)Math.min(discard.length,offset);
            int read=input.read(discard,0,requestedRead);
            if(read<0)throw new IOException("Source ended before the saved resume position");
            if(read==0||read>requestedRead)throw new IOException("Source returned an invalid resume read length");
            offset-=read;
            governor.read(read,cancellation);
        }
        check(cancellation);
    }
    private static void check(GameDataImporter.Cancellation cancellation)throws GameDataImporter.ImportCancelledException {
        if(cancellation.isCancelled()||Thread.currentThread().isInterrupted())throw new GameDataImporter.ImportCancelledException();
    }
}
