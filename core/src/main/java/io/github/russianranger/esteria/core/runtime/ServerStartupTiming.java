package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** Monotonic, non-renewable budgets for admission and actual native startup.
 * Progress is diagnostic only; the separate owned readiness receipt admits play. */
public final class ServerStartupTiming {
    public static final long ADMISSION_MILLIS=TimeUnit.MINUTES.toMillis(12);
    public static final long NATIVE_MILLIS=TimeUnit.SECONDS.toMillis(180);
    // The guest enforces 180 seconds. Allow only polling/receipt delivery overhead.
    public static final long RECEIPT_MILLIS=TimeUnit.SECONDS.toMillis(5);
    private final long started;
    private long nativeStarted,sequence=-1,elapsed=-1,nativeElapsed=-1;
    private boolean nativePhase;
    private String phase="admission",process="helper",condition="java-provider-admission",failure="";
    private final String operation,sourceLock,activeProof;
    public ServerStartupTiming(long now,String operation,String sourceLock,String activeProof) {
        this.started=now;this.operation=operation;this.sourceLock=sourceLock;this.activeProof=activeProof;
    }
    public synchronized boolean observe(long now,String operation,String sourceLock,String activeProof,long sequence,
            String phase,String process,String condition,long elapsed,long nativeElapsed,String failure)throws IOException {
        if(!this.operation.equals(operation)||!this.sourceLock.equals(sourceLock)||!this.activeProof.equals(activeProof))
            throw new IOException("Server startup status operation/source identity differs");
        if(!Set.of("admission","native-startup").contains(phase)||!Set.of("helper","authserver","worldserver").contains(process)||
                !Set.of("source-selection","provider-verification","prepared-data-verification","schema-verification",
                    "configuration-verification","native-launch","owned-auth-listener","auth-challenge",
                    "owned-world-listener","world-challenge","world-console","owned-ready").contains(condition)||
                sequence<0||elapsed<0||elapsed>TimeUnit.DAYS.toMillis(1)||nativeElapsed< -1||nativeElapsed>elapsed||
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
        if(!nativePhase&&phase.equals("native-startup")) {
            // A late/malformed transition can never renew an already expired admission.
            if(now-started>=ADMISSION_MILLIS)throw new IOException("Server admission deadline exceeded before native phase receipt");
            nativeStarted=now-nativeElapsed;nativePhase=true;
        }
        this.sequence=sequence;this.elapsed=elapsed;this.nativeElapsed=nativeElapsed;
        this.phase=phase;this.process=process;this.condition=condition;this.failure=failure;
        return true;
    }
    public synchronized boolean expired(long now) {
        return !nativePhase?now-started>=ADMISSION_MILLIS:now-nativeStarted>=NATIVE_MILLIS+RECEIPT_MILLIS;
    }
    public synchronized String diagnostic(long now) {
        return "phase="+phase+" process="+process+" readiness="+condition+" elapsedMs="+Math.max(0,now-started)+
            " nativeElapsedMs="+(!nativePhase?0:Math.max(0,now-nativeStarted))+
            (failure.isEmpty()?"":" failure="+failure);
    }
}
