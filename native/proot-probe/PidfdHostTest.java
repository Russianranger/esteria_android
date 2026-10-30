package io.github.russianranger.esteria.runtime;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

/** Real Linux pidfd/JNI contracts. This is not Android/PRoot qualification. */
public final class PidfdHostTest {
    private interface Action {void run() throws Exception;}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void reject(Action action)throws Exception{try{action.run();}catch(IOException expected){return;}throw new AssertionError("Expected identity rejection");}
    private static long ticks(long pid)throws Exception{
        String line=Files.readString(Path.of("/proc/"+pid+"/stat"));return Long.parseLong(line.substring(line.lastIndexOf(')')+2).split(" ")[19]);
    }
    public static void main(String[] args)throws Exception{
        Process first=new ProcessBuilder("/bin/sleep","30").start(),second=new ProcessBuilder("/bin/sleep","30").start();
        long a=0,b=0;
        try{
            int firstPid=Math.toIntExact(first.pid()),secondPid=Math.toIntExact(second.pid());
            long firstTicks=ticks(firstPid);String executable=Path.of("/proc/"+firstPid+"/exe").toRealPath().toString();
            reject(()->ProbeProcessHandles.watch(firstPid,firstTicks+1,0,executable,""));
            reject(()->ProbeProcessHandles.watch(firstPid,firstTicks,secondPid,executable,""));
            reject(()->ProbeProcessHandles.watch(firstPid,firstTicks,0,"/wrong-executable",""));
            a=ProbeProcessHandles.watch(firstPid,firstTicks,0,executable,"");
            b=ProbeProcessHandles.watch(secondPid,ticks(secondPid),0,executable,"");
            check(!ProbeProcessHandles.exited(a,0)&&!ProbeProcessHandles.exited(b,0),"both exact processes live");
            ProbeProcessHandles.kill(a);check(ProbeProcessHandles.exited(a,3000),"first process exited");
            check(first.waitFor(3,TimeUnit.SECONDS)&&first.exitValue()!=0,"real child termination");
            check(second.isAlive()&&!ProbeProcessHandles.exited(b,0),"unrelated child remains alive");
            ProbeProcessHandles.kill(a); // Dead pidfd is safe and cannot retarget a reused PID.
            ProbeProcessHandles.close(a);long stale=a;a=0;reject(()->ProbeProcessHandles.kill(stale));
            ProbeProcessHandles.kill(b);check(ProbeProcessHandles.exited(b,3000),"second child cleanup");
            System.out.println("PROBE_PIDFD_HOST_OK identity=1 stableHandles=1 isolatedKill=1 staleRejected=1");
        }finally{
            for(long handle:new long[]{a,b})if(handle!=0)try{ProbeProcessHandles.kill(handle);}finally{ProbeProcessHandles.close(handle);}
            for(Process child:new Process[]{first,second}){child.destroyForcibly();check(child.waitFor(3,TimeUnit.SECONDS),"host child cleanup deadline");}
        }
    }
}
