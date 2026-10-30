package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.net.ssl.HttpsURLConnection;

/** Explicit HTTPS acquisition with pinned-byte verification and bounded resume. */
public final class DownloadCache {
    public interface Transport { Response open(URI url, long offset) throws IOException; }
    public static class Response implements AutoCloseable {
        public final int status;
        public final long contentLength;
        public final String contentRange;
        public final InputStream body;
        public Response(int status,long contentLength,String contentRange,InputStream body) {this.status=status;this.contentLength=contentLength;this.contentRange=contentRange;this.body=body;}
        public void close() throws IOException { if(body!=null)body.close(); }
    }
    private final Path root;
    public final boolean directorySyncSupported;
    public DownloadCache(Path root) throws IOException {this.root=RuntimeFiles.directory(root);directorySyncSupported=RuntimeFiles.sync(this.root);}
    public Path obtain(URI uri,String name,long bytes,String sha,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation) throws IOException {
        return obtain(uri,name,bytes,sha,progress,cancellation,new HttpsTransport());
    }
    public Path obtain(URI uri,String name,long bytes,String sha,RuntimeWork.Progress progress,RuntimeWork.Cancellation cancellation,Transport transport) throws IOException {
        https(uri);RuntimeFiles.hashPin(sha);
        RuntimeFiles.require(name!=null&&name.matches("[A-Za-z0-9._-]{1,128}")&&bytes>0&&bytes<=(8L<<30),"Invalid download pin");
        String pin="esteria-download-v1\n"+name+"\n"+bytes+"\n"+sha+"\n";
        String id=RuntimeFiles.hashText(pin);
        Path archive=root.resolve(id+".archive"),partial=root.resolve(id+".partial"),owner=root.resolve(id+".owner"),receipt=root.resolve(id+".verified");
        try(RuntimeFiles.Lock ignored=RuntimeFiles.lock(root)) {
            RuntimeWork.check(cancellation);
            if(Files.exists(archive,LinkOption.NOFOLLOW_LINKS)) {
                RuntimeFiles.plain(archive);RuntimeFiles.require(Files.size(archive)==bytes,"Cached archive size differs; original cache preserved");
                String identity=pin+Files.getLastModifiedTime(archive,LinkOption.NOFOLLOW_LINKS).toMillis()+"\n";
                if(!Files.exists(receipt,LinkOption.NOFOLLOW_LINKS)||!RuntimeFiles.smallText(receipt,1024).equals(identity)) {
                    progress.update("verify-download",name,0,bytes);
                    RuntimeFiles.require(RuntimeFiles.hashFile(archive,bytes,cancellation).equals(sha),"Cached archive hash differs; original cache preserved");
                    RuntimeFiles.atomicText(receipt,identity,directorySyncSupported);
                }
                progress.update("cached",name,bytes,bytes);return archive;
            }
            if(Files.exists(owner,LinkOption.NOFOLLOW_LINKS)) RuntimeFiles.require(RuntimeFiles.smallText(owner,1024).equals(pin),"Download ownership pin differs");
            else {
                RuntimeFiles.require(!Files.exists(partial,LinkOption.NOFOLLOW_LINKS),"Unowned partial download preserved");
                RuntimeFiles.atomicText(owner,pin,directorySyncSupported);
            }
            long offset=0;
            if(Files.exists(partial,LinkOption.NOFOLLOW_LINKS)) {RuntimeFiles.plain(partial);offset=Files.size(partial);RuntimeFiles.require(offset<=bytes,"Partial download exceeds pinned size");}
            RuntimeFiles.require(root.toFile().getUsableSpace()>=bytes-offset+(16L<<20),"Insufficient storage for runtime download");
            MessageDigest hash=RuntimeFiles.digest();
            byte[] buffer=new byte[RuntimeFiles.BUFFER];
            if(offset>0) {
                try(InputStream input=Files.newInputStream(partial,LinkOption.NOFOLLOW_LINKS)) {
                    int count;long read=0;
                    while((count=input.read(buffer))!=-1) {RuntimeWork.check(cancellation);read+=count;RuntimeFiles.require(read<=offset,"Partial download changed");hash.update(buffer,0,count);progress.update("verify-resume",name,read,offset);}
                    RuntimeFiles.require(read==offset,"Partial download changed");
                }
            }
            if(offset<bytes) {
                try(Response response=transport.open(uri,offset)) {
                    RuntimeFiles.require(response.body!=null,"Download response has no data");
                    if(response.status==HttpURLConnection.HTTP_OK) {offset=0;hash.reset();}
                    else {
                        RuntimeFiles.require(response.status==HttpURLConnection.HTTP_PARTIAL,"Runtime download HTTP status "+response.status);
                        Matcher range=Pattern.compile("bytes ([0-9]+)-([0-9]+)/([0-9]+)").matcher(response.contentRange==null?"":response.contentRange);
                        RuntimeFiles.require(range.matches(),"Invalid download Content-Range");
                        long start=number(range.group(1)),end=number(range.group(2)),total=number(range.group(3));
                        RuntimeFiles.require(start==offset&&end==bytes-1&&total==bytes,"Download range differs from pinned archive");
                    }
                    RuntimeFiles.require(response.contentLength<0||response.contentLength==bytes-offset,"Download length differs from pin");
                    try(FileChannel output=FileChannel.open(partial,StandardOpenOption.CREATE,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS)) {
                        RuntimeFiles.privateMode(partial,false,false);output.truncate(offset);output.position(offset);
                        long completed=offset;
                        try {
                            int count;
                            while((count=response.body.read(buffer))!=-1) {
                                RuntimeWork.check(cancellation);RuntimeFiles.require(count<=bytes-completed,"Download exceeds pinned length");
                                ByteBuffer data=ByteBuffer.wrap(buffer,0,count);while(data.hasRemaining())output.write(data);
                                hash.update(buffer,0,count);completed+=count;progress.update("download",name,completed,bytes);
                            }
                            RuntimeFiles.require(completed==bytes,"Interrupted runtime download; partial retained for resume");
                        } finally {output.force(true);}
                    }
                }
            }
            RuntimeWork.check(cancellation);
            if(!RuntimeFiles.hex(hash.digest()).equals(sha)) {Files.deleteIfExists(partial);throw new IOException("Downloaded runtime hash differs from pin; no existing runtime changed");}
            RuntimeFiles.plain(partial);RuntimeFiles.require(Files.size(partial)==bytes,"Downloaded file changed before publication");
            Files.move(partial,archive,StandardCopyOption.ATOMIC_MOVE);
            RuntimeFiles.require(!directorySyncSupported||RuntimeFiles.sync(root),"Download cache sync failed");
            RuntimeFiles.atomicText(receipt,pin+Files.getLastModifiedTime(archive,LinkOption.NOFOLLOW_LINKS).toMillis()+"\n",directorySyncSupported);
            progress.update("download-verified",name,bytes,bytes);return archive;
        }
    }
    private static long number(String value) throws IOException {try{return Long.parseLong(value);}catch(NumberFormatException bad){throw new IOException("Invalid download range",bad);}}
    private static void https(URI uri) throws IOException {
        RuntimeFiles.require(uri!=null&&"https".equalsIgnoreCase(uri.getScheme())&&uri.getHost()!=null&&uri.getRawUserInfo()==null&&uri.getFragment()==null,"Runtime downloads require a credential-free HTTPS URL");
    }
    private static final class HttpsTransport implements Transport {
        public Response open(URI original,long offset) throws IOException {
            URI uri=original;
            for(int redirects=0;redirects<8;redirects++) {
                https(uri);
                HttpsURLConnection connection=(HttpsURLConnection)uri.toURL().openConnection();
                connection.setInstanceFollowRedirects(false);connection.setConnectTimeout(15000);connection.setReadTimeout(15000);
                connection.setRequestProperty("Accept-Encoding","identity");
                if(offset>0)connection.setRequestProperty("Range","bytes="+offset+"-");
                try {
                    int status=connection.getResponseCode();
                    if(status==301||status==302||status==303||status==307||status==308) {
                        String location=connection.getHeaderField("Location");RuntimeFiles.require(location!=null&&location.length()<=8192,"Invalid runtime download redirect");
                        uri=uri.resolve(location);connection.disconnect();continue;
                    }
                    RuntimeFiles.require(status==200||status==206,"Runtime download HTTP status "+status);
                    RuntimeFiles.require(connection.getContentEncoding()==null||"identity".equalsIgnoreCase(connection.getContentEncoding()),"Unexpected download transfer encoding");
                    return new Response(status,connection.getContentLengthLong(),connection.getHeaderField("Content-Range"),connection.getInputStream()) {
                        public void close() throws IOException {try{super.close();}finally{connection.disconnect();}}
                    };
                }catch(IOException|RuntimeException error){connection.disconnect();throw error;}
            }
            throw new IOException("Too many runtime download redirects");
        }
    }
}
