package android.net;

import java.io.Closeable;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;

/** Host queue-policy fixture only. Never packaged into an APK. Any accidental
 * connect/read/write request fails rather than simulating an Android transport. */
public final class LocalSocket implements Closeable {
    public LocalSocket() { }
    public void connect(LocalSocketAddress address)throws IOException {throw new IOException("HOST_FIXTURE_SOCKET_IO_UNAVAILABLE");}
    public void setSoTimeout(int millis)throws IOException {throw new IOException("HOST_FIXTURE_SOCKET_IO_UNAVAILABLE");}
    public Credentials getPeerCredentials()throws IOException {throw new IOException("HOST_FIXTURE_SOCKET_IO_UNAVAILABLE");}
    public InputStream getInputStream()throws IOException {throw new IOException("HOST_FIXTURE_SOCKET_IO_UNAVAILABLE");}
    public OutputStream getOutputStream()throws IOException {throw new IOException("HOST_FIXTURE_SOCKET_IO_UNAVAILABLE");}
    public void shutdownInput()throws IOException { }
    public void shutdownOutput()throws IOException { }
    public void close()throws IOException { }
}
