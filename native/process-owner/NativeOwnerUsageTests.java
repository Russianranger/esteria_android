package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.ProcessUsageSnapshot;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/** Real host JNI group observations; proc denials remain explicit outcomes.
 * Group-only counters never qualify detached guests or combined bot budgets. */
final class NativeOwnerUsageTests {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static boolean rssAvailable,pssAvailable,cpuAvailable;
    static int run(NativeProcessBridge backend,Path root)throws Exception {
        Path work=Files.createDirectory(root.resolve("usage-group"));
        OwnedProcess.Specification spec=new OwnedProcess.Specification(Path.of("/bin/sh"),List.of("-c","sleep 30 & sleep 30 & printf ready; wait"),Map.of("PATH","/usr/bin:/bin"),work,work.resolve("out"),work.resolve("err"));
        OwnedProcess child=OwnedProcess.start(backend,spec,null);
        try {
            long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);while(Files.size(work.resolve("out"))<5&&System.nanoTime()<deadline)Thread.sleep(5);
            check(Files.readString(work.resolve("out")).equals("ready"),"Real owned group fixture must fork before sampling");
            ProcessUsageSnapshot latest=null;
            for(int sample=0;sample<8;sample++) {
                latest=child.usage();check(latest!=null&&ProcessUsageSnapshot.SCOPE.equals(latest.scope()),"Usage is explicitly group-only");
                if(latest.visibleSetStable()) {
                    check(!latest.wholeGroupMembershipVerified()&&(latest.flags&ProcessUsageSnapshot.VISIBILITY_UNVERIFIED)!=0,"A stable visible census must never claim whole-group coverage");
                    check(latest.visibleMembersRssBytes().isPresent()&&latest.visibleMembersRssBytes().getAsLong()>0,"Stable visible-set resident RSS requires actual values");
                    check(latest.visibleMembersCpuNanos().isPresent(),"Stable visible-set CPU uses actual per-member counters");
                    rssAvailable=true;cpuAvailable=true;pssAvailable|=latest.visibleMembersPssBytes().isPresent();break;
                }
                check(latest.flags!=0&&latest.visibleMembersRssBytes().isEmpty()&&latest.visibleMembersPssBytes().isEmpty(),"Partial/unavailable membership cannot expose invented sums");
                Thread.sleep(10);
            }
            check(latest!=null,"A typed observation is always returned");
            check(child.logPaths().equals(Map.of("stdout",work.resolve("out"),"stderr",work.resolve("err"))),"Only original immutable spec log paths are exposed");
            try{child.logPaths().put("argv",root);throw new AssertionError("Public log paths were mutable");}catch(UnsupportedOperationException expected){ }
            check(child.isAlive()&&child.failure()==null,"Sampling cannot stop/change the native owner");
            System.out.println("PASS JNI live process-group usage scope, coverage and immutable log paths; RSS="+rssAvailable+" PSS="+pssAvailable+" CPU="+cpuAvailable+" flags="+latest.flags);
            AtomicBoolean finished=new AtomicBoolean();AtomicReference<Throwable> error=new AtomicReference<>();
            Thread sampler=new Thread(()->{try{while(!finished.get())child.usage();}catch(Throwable failure){error.set(failure);}});sampler.start();
            long began=System.nanoTime();child.terminateAuxiliary();finished.set(true);sampler.join(5000);
            check(!sampler.isAlive()&&error.get()==null&&!child.isAlive()&&System.nanoTime()-began<TimeUnit.SECONDS.toNanos(7),"Sampling races cannot block real native termination/reap");
            check((child.usage().flags&ProcessUsageSnapshot.NOT_RUNNING)!=0&&child.usage().visibleMembersPssBytes().isEmpty(),"Reaped owner never follows a stale PID");
            try{backend.usage(999999999L);throw new AssertionError("Unknown opaque handle accepted for resource sampling");}catch(IOException expected){ }
            check(child.diagnostics().length==5,"Existing diagnostics ABI remains unchanged");
            System.out.println("PASS JNI concurrent sampling/stop, dead/unknown opaque handles and original diagnostics ABI");
        }finally{if(child.isAlive())child.terminateAuxiliary();}
        // Source-format checks are fixtures, not native measurements.
        long[] wire={1,4096,1,2,6,3,3,3,3,300,200,7,100,0,0,0};
        ProcessUsageSnapshot complete=ProcessUsageSnapshot.fromNative(wire);wire[9]=999;
        check(complete.visibleMembersRssBytes().orElseThrow()==300&&complete.visibleMembersPssBytes().orElseThrow()==200&&complete.visibleMembersCpuNanos().orElseThrow()==70_000_000,"Validated native wire is immutable and CPU conversion excludes child counters");
        long[] partial={1,ProcessUsageSnapshot.VISIBILITY_UNVERIFIED|ProcessUsageSnapshot.PSS_UNAVAILABLE|ProcessUsageSnapshot.PROC_DENIED,1,2,6,3,3,2,3,300,100,7,100,0,1,0};
        ProcessUsageSnapshot denied=ProcessUsageSnapshot.fromNative(partial);
        check(denied.visibleSetStable()&&denied.visibleMembersPssBytes().isEmpty()&&denied.visibleMembersRssBytes().orElseThrow()==300,"PSS denial is explicit without discarding separately complete RSS");
        partial[1]|=ProcessUsageSnapshot.MEMBERSHIP_INCOMPLETE;
        denied=ProcessUsageSnapshot.fromNative(partial);check(denied.visibleMembersPssBytes().isEmpty()&&denied.visibleMembersRssBytes().isEmpty()&&denied.visibleMembersCpuNanos().isEmpty(),"Incomplete membership exposes no partial metric sum");
        try{ProcessUsageSnapshot.fromNative(new long[5]);throw new AssertionError("Old diagnostics ABI misread as usage");}catch(IOException expected){ }
        System.out.println("PASS typed usage wire, immutable coverage, denial and no-partial-sum policy");return 3;
    }
}
