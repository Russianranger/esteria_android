package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;

/** Actual Android child observation; no guest/runtime qualification. */
public final class PreparationChildFixture {
    private PreparationChildFixture(){}
    public static ProcessUsageSnapshot sample(Path work)throws Exception{
        OwnedProcess child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(java.nio.file.Paths.get("/system/bin/sh"),
            List.of("sh","-c","sleep 5"),Map.of("PATH","/system/bin"),work,work.resolve("stdout.log"),work.resolve("stderr.log")),null);
        try{return child.usage();}finally{child.terminateAuxiliary();}
    }
    public static int exit(Path work,int code)throws Exception{
        if(code<0||code>255)throw new IllegalArgumentException("Exit fixture range");
        OwnedProcess child=OwnedProcess.start(new NativeProcessBridge(),new OwnedProcess.Specification(java.nio.file.Paths.get("/system/bin/sh"),
            List.of("sh","-c","exit "+code),Map.of("PATH","/system/bin"),work,work.resolve("stdout.log"),work.resolve("stderr.log")),null);
        long deadline=System.nanoTime()+5_000_000_000L;
        try{
            while(child.isAlive()&&System.nanoTime()<deadline)Thread.sleep(10);
            if(child.isAlive())throw new java.io.IOException("Exit fixture timed out");
            if(child.failure()!=null)throw child.failure();
            return child.exitCode();
        }finally{if(child.isAlive())child.terminateAuxiliary();}
    }
}
