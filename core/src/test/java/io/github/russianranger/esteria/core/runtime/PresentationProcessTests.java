package io.github.russianranger.esteria.core.runtime;

import io.github.russianranger.esteria.core.presentation.X11SessionPlan;
import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import java.io.ByteArrayInputStream;
import java.io.DataInputStream;
import java.io.IOException;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Controlled backend ownership tests; these do not claim native or Android execution. */
public final class PresentationProcessTests {
    private static void check(boolean value,String reason) { if(!value)throw new AssertionError(reason); }
    private static final class Backend implements OwnedProcess.Backend {
        final CountDownLatch terminated=new CountDownLatch(1),release=new CountDownLatch(1);
        boolean hold; long logErrors; int terminations;
        public long start(OwnedProcess.Specification s) { return 1; }
        public int waitFor(long h,long ms) throws IOException {
            try { Thread.sleep(5); } catch(InterruptedException e) { throw new IOException(e); }
            return OwnedProcess.RUNNING;
        }
        public int terminate(long h) throws IOException {
            terminations++;terminated.countDown();
            if(hold)try { check(release.await(3,TimeUnit.SECONDS),"Blocked test backend timed out"); }
                catch(InterruptedException e){throw new IOException(e);}
            return 143;
        }
        public long[] diagnostics(long h) { return new long[]{0,0,0,0,logErrors}; }
    }
    private static OwnedProcess start(Backend backend,OwnedProcess.GracefulStop callback) throws IOException {
        return OwnedProcess.start(backend,new OwnedProcess.Specification(Path.of("/test/tool"),List.of(),Map.of(),
                Path.of("/test"),Path.of("/test/stdout"),Path.of("/test/stderr")),callback);
    }
    private static byte[] field(DataInputStream in) throws IOException { byte[] b=new byte[in.readUnsignedShort()];in.readFully(b);return b; }
    public static void main(String[] args)throws Exception {
        byte[] cookie=new byte[16];for(int i=0;i<cookie.length;i++)cookie[i]=(byte)(i+1);
        DataInputStream auth=new DataInputStream(new ByteArrayInputStream(X11SessionPlan.authority(987,cookie)));
        check(auth.readUnsignedShort()==65535&&field(auth).length==0,"Xauthority family/address encoding");
        check(Arrays.equals(field(auth),"987".getBytes(java.nio.charset.StandardCharsets.US_ASCII)),"Xauthority exact display");
        check(new String(field(auth),java.nio.charset.StandardCharsets.US_ASCII).equals("MIT-MAGIC-COOKIE-1"),"Xauthority method");
        check(Arrays.equals(field(auth),cookie)&&auth.read()==-1,"Xauthority cookie boundary");
        check(X11SessionPlan.server(987).contains("-auth")&&!X11SessionPlan.server(987).contains("-ac"),"X11 access control enabled");
        Backend normal=new Backend();OwnedProcess auxiliary=start(normal,null);auxiliary.terminateAuxiliary();
        check(auxiliary.wasForced()&&auxiliary.exitCode()==143&&auxiliary.failure()==null&&normal.terminations==1,"Explicit auxiliary status retained");
        Backend failure=new Backend();failure.logErrors=1;OwnedProcess broken=start(failure,null);
        try { broken.terminateAuxiliary();throw new AssertionError("Log failure hidden"); } catch(IOException expected) { }
        Backend guarded=new Backend();OwnedProcess persistent=start(guarded,()->{});
        try { persistent.terminateAuxiliary();throw new AssertionError("Graceful callback bypassed"); } catch(IllegalStateException expected) { }
        try { persistent.stop(Duration.ZERO);throw new AssertionError("Forced persistent stop hidden"); } catch(IOException expected) { }
        Backend race=new Backend();race.hold=true;OwnedProcess first=start(race,null);
        Thread stop=new Thread(()->{try { first.stop(Duration.ZERO); }catch(IOException expected){}});stop.start();
        check(race.terminated.await(2,TimeUnit.SECONDS),"Prior normal stop reached backend");race.release.countDown();
        try { first.terminateAuxiliary();throw new AssertionError("Auxiliary request erased prior stop failure"); } catch(IOException expected) { }
        stop.join(3000);check(!stop.isAlive()&&first.failure()!=null&&race.terminations==1,"First stop semantics retained");
        System.out.println("Authenticated X11 command and auxiliary shutdown contracts passed; no native execution claimed");
    }
}
