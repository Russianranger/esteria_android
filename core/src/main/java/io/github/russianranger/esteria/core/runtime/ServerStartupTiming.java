package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.util.List;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** A receipt-sized allowance for advancing admission reads, then a separate fixed native budget.
 * A separate owned readiness receipt admits play. */
public final class ServerStartupTiming {
    public static final long ADMISSION_MILLIS=TimeUnit.MINUTES.toMillis(12);
    public static final long NATIVE_MILLIS=TimeUnit.SECONDS.toMillis(180);
    // The guest enforces 180 seconds. Allow only polling/receipt delivery overhead.
    public static final long RECEIPT_MILLIS=TimeUnit.SECONDS.toMillis(5);
    // The original bounded allowance covers setup, filesystem walks, preflight and schema checks.
    // Only newly observed paced reads earn additional time, capped at one selected inventory per reader.
    public enum ReadStage { SEAL("cache-seal"), AUDIT("session-audit");
        public final String id;
        ReadStage(String id){this.id=id;}
    }
    private static final List<String> ADMISSION_STEPS=List.of("source-selection","provider-verification",
        "prepared-data-verification","schema-verification","configuration-verification","realm-offline-recovery");
    private int lastAdmissionStep=-1;
    private final long started,payloadBytes,normalRate;
    private final long[] counted=new long[ReadStage.values().length],lowestRate=new long[counted.length];
    private long lastProgress,lastMeasuredBytes;
    private ReadStage stage;
    private long nativeStarted,sequence=-1,elapsed=-1,nativeElapsed=-1;
    private boolean nativePhase,sealing;
    private String phase="admission",process="helper",condition="java-provider-admission",failure="";
    private final String operation,sourceLock,activeProof;
    public ServerStartupTiming(long now,String operation,String sourceLock,String activeProof,long payloadBytes,long normalRate) {
        if(payloadBytes<0||payloadBytes>(96L<<30)||normalRate<(2L<<20)||normalRate>(64L<<20))
            throw new IllegalArgumentException("Invalid selected admission workload");
        this.started=now;this.lastProgress=now;this.operation=operation;this.sourceLock=sourceLock;this.activeProof=activeProof;
        this.payloadBytes=payloadBytes;this.normalRate=normalRate;
        java.util.Arrays.fill(lowestRate,normalRate);
    }
    public synchronized void sealing(boolean active){sealing=active;}
    public synchronized boolean readProgress(long now,ReadStage selected,long rawBytes,long configuredRate,long minimumRate)throws IOException {
        if(stage==ReadStage.AUDIT&&selected==ReadStage.SEAL)throw new IOException("Admission read phase moved backwards");
        if(rawBytes<0||configuredRate!=normalRate||(minimumRate!=normalRate&&minimumRate!=(2L<<20)))
            throw new IOException("Invalid selected admission read counters");
        // The policy also counts small helper/order metadata. Only the selected payload earns time.
        long bytes=Math.min(rawBytes,payloadBytes);
        int index=selected.ordinal();
        if(bytes<counted[index]||minimumRate>lowestRate[index])throw new IOException("Admission counters moved backwards");
        if(nativePhase||bytes==counted[index])return false;
        if(expired(now))throw new IOException("Late admission read progress; "+diagnostic(now));
        counted[index]=bytes;lowestRate[index]=minimumRate;lastProgress=now;stage=selected;lastMeasuredBytes=rawBytes;
        return true;
    }
    private long admissionBudget() {
        long budget=ADMISSION_MILLIS;
        // One paced interval plus one interval for actual hashing/PRoot I/O at the observed policy limit.
        for(int i=0;i<counted.length;i++)budget+=counted[i]*2000/lowestRate[i];
        return budget;
    }
    public synchronized boolean observe(long now,String operation,String sourceLock,String activeProof,long sequence,
            String phase,String process,String condition,long elapsed,long nativeElapsed,String failure)throws IOException {
        if(!this.operation.equals(operation)||!this.sourceLock.equals(sourceLock)||!this.activeProof.equals(activeProof))
            throw new IOException("Server startup status operation/source identity differs");
        if(!Set.of("admission","native-startup").contains(phase)||!Set.of("helper","authserver","worldserver").contains(process)||
                !Set.of("source-selection","provider-verification","prepared-data-verification","schema-verification",
                    "configuration-verification","realm-offline-recovery","native-launch","owned-auth-listener","auth-challenge",
                    "owned-world-listener","world-challenge","world-console","owned-ready").contains(condition)||
                sequence<0||elapsed<0||elapsed>TimeUnit.DAYS.toMillis(3)||nativeElapsed< -1||nativeElapsed>elapsed||
                (!failure.isEmpty()&&!failure.matches("[A-Za-z][A-Za-z0-9]{0,63}"))||
                (phase.equals("admission")!=(nativeElapsed==-1)))
            throw new IOException("Invalid bounded server startup status");
        if(sequence==this.sequence) {
            if(!phase.equals(this.phase)||!process.equals(this.process)||!condition.equals(this.condition)||
                    elapsed!=this.elapsed||nativeElapsed!=this.nativeElapsed||!failure.equals(this.failure))
                throw new IOException("Server startup status changed without advancing sequence");
            return false;
        }
        if(sequence<this.sequence||elapsed<this.elapsed||nativeElapsed<this.nativeElapsed||
                (nativePhase&&phase.equals("admission")))throw new IOException("Server startup status moved backwards");
        if(phase.equals("admission")){
            int step=ADMISSION_STEPS.indexOf(condition);
            if(step<0||!process.equals("helper")||step<lastAdmissionStep)throw new IOException("Admission phase moved backwards or differs");
            if(step>lastAdmissionStep){
                if(expired(now))throw new IOException("Late admission phase transition; "+diagnostic(now));
                lastAdmissionStep=step;lastProgress=now;
            }
        }
        if(!nativePhase&&phase.equals("native-startup")) {
            // A late/malformed transition can never renew an already expired admission.
            if(expired(now))throw new IOException("Server admission deadline exceeded before native phase receipt; "+diagnostic(now));
            nativeStarted=now-nativeElapsed;nativePhase=true;
        }
        this.sequence=sequence;this.elapsed=elapsed;this.nativeElapsed=nativeElapsed;
        this.phase=phase;this.process=process;this.condition=condition;this.failure=failure;
        return true;
    }
    public synchronized boolean expired(long now) {
        if(nativePhase)return now-nativeStarted>=NATIVE_MILLIS+RECEIPT_MILLIS;
        return now-lastProgress>=ADMISSION_MILLIS||now-started>=admissionBudget();
    }
    public synchronized String diagnostic(long now) {
        String reason=nativePhase?"native-readiness-deadline":
            now-lastProgress>=ADMISSION_MILLIS?"admission-no-progress":"admission-workload-deadline";
        return "phase="+phase+" process="+(sealing?"cache-sealer":process)+
            " readiness="+(sealing?"prepared-data-verification":condition)+" elapsedMs="+Math.max(0,now-started)+
            (expired(now)?" expired="+reason:"")+
            (nativePhase?"":" readStage="+(stage==null?"none":stage.id)+" pacedBytesAtLastProgress="+lastMeasuredBytes+
                " budgetedBytes="+(stage==null?0:counted[stage.ordinal()])+
                " selectedBytes="+payloadBytes+" configuredBytesPerSecond="+normalRate+
                " lowestBytesPerSecond="+(stage==null?normalRate:lowestRate[stage.ordinal()])+
                " idleMs="+Math.max(0,now-lastProgress)+" admissionBudgetMs="+admissionBudget())+
            " nativeElapsedMs="+(!nativePhase?0:Math.max(0,now-nativeStarted))+
            (failure.isEmpty()?"":" failure="+failure);
    }
}
