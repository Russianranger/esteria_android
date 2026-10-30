package io.github.russianranger.esteria.core.runtime.process;

import java.io.IOException;
import java.util.OptionalLong;

/** A sampling window over one opaque owner's VISIBLE native group members only.
 * Detached PRoot tracees/daemon descendants are outside this scope. This is
 * insufficient for whole-guest, combined-client/server or bot-budget claims.
 * Visible-set RSS still counts shared pages once per observed member; it is not PSS. */
public final class ProcessUsageSnapshot {
    public static final String SCOPE="visible-owned-native-group-members-only";
    public static final int PROC_DENIED=1,MEMBERSHIP_INCOMPLETE=2,CHANGED=4,LIMIT=8,
        RSS_UNAVAILABLE=16,PSS_UNAVAILABLE=32,CPU_UNAVAILABLE=64,NOT_RUNNING=128,
        UNSUPPORTED_BACKEND=256,IO_ERROR=512,OWNER_BUSY=1024,NATIVE_ERROR=2048,VISIBILITY_UNVERIFIED=4096;
    public final long flags,startedMonotonicNanos,durationNanos;
    public final int scannedProcesses,visibleMembers,rssMeasuredMembers,pssMeasuredMembers,cpuMeasuredMembers,changedMembers,deniedEntries;
    private final long rss,pss,cpuTicks,ticksPerSecond;
    private ProcessUsageSnapshot(long[] values) {
        flags=values[1];startedMonotonicNanos=values[2];durationNanos=values[3];scannedProcesses=(int)values[4];visibleMembers=(int)values[5];
        rssMeasuredMembers=(int)values[6];pssMeasuredMembers=(int)values[7];cpuMeasuredMembers=(int)values[8];
        rss=values[9];pss=values[10];cpuTicks=values[11];ticksPerSecond=values[12];changedMembers=(int)values[13];deniedEntries=(int)values[14];
    }
    /** Versioned JNI wire; validation prevents malformed/partial arrays being
     * displayed as complete data. No PIDs, names, argv or environment are exposed. Visibility remains unverified. */
    public static ProcessUsageSnapshot fromNative(long[] values)throws IOException {
        if(values==null||values.length!=16||values[0]!=1||values[15]!=0||values[1]<0||(values[1]&VISIBILITY_UNVERIFIED)==0||(values[1]&~8191L)!=0)
            throw new IOException("Invalid owned process usage snapshot");
        for(int index=2;index<15;index++)if(values[index]<0)throw new IOException("Invalid owned process usage counters");
        if((values[5]==0&&values[1]==0)||values[4]>16384||values[5]>128||values[6]>values[5]||values[7]>values[5]||values[8]>values[5]||values[13]>16384||values[14]>32768||
                (values[8]>0&&values[12]==0)||
                ((values[1]&(NOT_RUNNING|UNSUPPORTED_BACKEND|OWNER_BUSY|NATIVE_ERROR))!=0&&
                    (values[5]!=0||values[6]!=0||values[7]!=0||values[8]!=0||values[9]!=0||values[10]!=0||values[11]!=0)))
            throw new IOException("Inconsistent owned process usage coverage");
        return new ProcessUsageSnapshot(values.clone());
    }
    static ProcessUsageSnapshot unavailable(int reason) {
        long[] values=new long[16];values[0]=1;values[1]=reason|MEMBERSHIP_INCOMPLETE|VISIBILITY_UNVERIFIED;
        return new ProcessUsageSnapshot(values);
    }
    public String scope(){return SCOPE;}
    /** Proc projection may silently hide even same-UID group tasks. */
    public boolean wholeGroupMembershipVerified(){return false;}
    /** Two bounded visible census scans and stable observed member identities. A stable
     * window is not a simultaneous atomic snapshot of all processes. */
    public boolean visibleSetStable(){return visibleMembers>0&&(flags&(MEMBERSHIP_INCOMPLETE|CHANGED|LIMIT|NOT_RUNNING|UNSUPPORTED_BACKEND|OWNER_BUSY|NATIVE_ERROR))==0;}
    /** Shared pages may be counted repeatedly. Never label this combined PSS. */
    public OptionalLong visibleMembersRssBytes(){return visibleSetStable()&&rssMeasuredMembers==visibleMembers&&(flags&RSS_UNAVAILABLE)==0?OptionalLong.of(rss):OptionalLong.empty();}
    /** Empty if visible census or ANY observed member's PSS is unavailable; partial sums are
     * deliberately not public and may never become a combined-memory total. */
    public OptionalLong visibleMembersPssBytes(){return visibleSetStable()&&pssMeasuredMembers==visibleMembers&&(flags&PSS_UNAVAILABLE)==0?OptionalLong.of(pss):OptionalLong.empty();}
    /** Accumulated user+system time of currently visible members, excludes child times.
     * This is not CPU percent, whole-tree time or a per-session lifetime total. */
    public OptionalLong visibleMembersCpuNanos(){
        if(!visibleSetStable()||cpuMeasuredMembers!=visibleMembers||(flags&CPU_UNAVAILABLE)!=0||ticksPerSecond<=0)return OptionalLong.empty();
        try{return OptionalLong.of(Math.addExact(Math.multiplyExact(cpuTicks/ticksPerSecond,1_000_000_000L),
            Math.multiplyExact(cpuTicks%ticksPerSecond,1_000_000_000L)/ticksPerSecond));}
        catch(ArithmeticException overflow){return OptionalLong.empty();}
    }
}
