package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;

/** Synthetic monotonic times; no Android/server/gameplay evidence. */
public final class ServerStartupTimingTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private interface Checked {void run()throws Exception;}
    private static void rejected(Checked action)throws Exception {
        try{action.run();throw new AssertionError("Invalid status accepted");}catch(IOException expected){ }
    }
    private static ServerStartupTiming timing(){return new ServerStartupTiming(0,"op","source","proof",7L<<30,8L<<20);}
    private static boolean nativeStatus(ServerStartupTiming clock,long now,long sequence,long elapsed)throws IOException {
        return clock.observe(now,"op","source","proof",sequence,"native-startup","worldserver","owned-world-listener",now,elapsed,"");
    }
    public static void main(String[] args)throws Exception {
        long admission=ServerStartupTiming.ADMISSION_MILLIS,nativeBudget=ServerStartupTiming.NATIVE_MILLIS+ServerStartupTiming.RECEIPT_MILLIS;
        ServerStartupTiming clock=timing();
        check(!clock.expired(admission-1)&&clock.expired(admission),"Admission is independently bounded");
        clock=timing();nativeStatus(clock,admission-1000,1,0);
        check(!clock.expired(admission+1000),"Admission time must not consume native service budget");
        check(!clock.expired(admission-1000+nativeBudget-1)&&clock.expired(admission-1000+nativeBudget),"Native budget is independently bounded");
        nativeStatus(clock,admission-1000+nativeBudget,2,nativeBudget);
        check(clock.expired(admission-1000+nativeBudget),"Progress cannot renew native budget");
        ServerStartupTiming late=timing();rejected(()->nativeStatus(late,admission,1,0));
        check(late.expired(admission),"Late phase cannot renew expired admission");
        ServerStartupTiming stale=timing();
        rejected(()->stale.observe(1,"other","source","proof",1,"admission","helper","source-selection",0,-1,""));
        rejected(()->stale.observe(1,"op","other","proof",1,"admission","helper","source-selection",0,-1,""));
        rejected(()->stale.observe(1,"op","source","other",1,"admission","helper","source-selection",0,-1,""));
        nativeStatus(stale,100,1,50);
        check(stale.expired(50+nativeBudget),"Already elapsed native startup is deducted from remaining budget");
        check(!nativeStatus(stale,100,1,50),"Exact repeated receipt is idempotent");
        rejected(()->nativeStatus(stale,101,1,50));
        rejected(()->nativeStatus(stale,101,0,50));
        rejected(()->nativeStatus(stale,101,2,49));
        rejected(()->stale.observe(101,"op","source","proof",2,"admission","helper","source-selection",101,-1,""));
        rejected(()->stale.observe(101,"op","source","proof",2,"native-startup","password","owned-world-listener",101,51,""));
        rejected(()->stale.observe(101,"op","source","proof",2,"native-startup","worldserver","arbitrary log",101,51,""));
        rejected(()->stale.observe(101,"op","source","proof",2,"native-startup","worldserver","owned-world-listener",101,51,"secret text"));
        stale.observe(101,"op","source","proof",2,"native-startup","worldserver","owned-world-listener",101,51,"TimeoutError");
        String detail=stale.diagnostic(102);
        check(detail.contains("process=worldserver")&&detail.contains("readiness=owned-world-listener")&&
            detail.contains("nativeElapsedMs=52")&&detail.contains("failure=TimeoutError"),"Precise bounded failure diagnosis");
        // A 7 GiB receipt needs 896 seconds of scheduled reads at the configured Gentle rate,
        // before filesystem and digest work. Exercise both an incomplete seal and a full fallback.
        var seal=ServerStartupTiming.ReadStage.SEAL;
        var audit=ServerStartupTiming.ReadStage.AUDIT;
        var bulk=timing();long rate=8L<<20,bytes=7L<<30;
        for(int second=1;second<=896;second++)
            check(bulk.readProgress(second*1000L,seal,second*rate,rate,rate),"Seal progress");
        check(!bulk.expired(896000),"Full seal may outlive old admission deadline");
        for(int second=1;second<=896;second++)
            check(bulk.readProgress((896+second)*1000L,audit,second*rate,rate,rate),"Fallback progress");
        check(!bulk.readProgress(1793000,audit,bytes+1000,rate,rate),"Extra metadata cannot earn another pass");
        check(!bulk.expired(1792000+admission-1)&&bulk.expired(1792000+admission),"Stalled read is bounded");
        nativeStatus(bulk,1794000,1,0);
        check(!bulk.expired(1794000+nativeBudget-1)&&bulk.expired(1794000+nativeBudget),"Full audit does not buy native time");
        var phase=timing();
        for(int second=1;second<=896;second++)phase.readProgress(second*1000L,audit,second*rate,rate,rate);
        phase.observe(1000000,"op","source","proof",1,"admission","helper","schema-verification",1000000,-1,"");
        check(!phase.expired(896000+admission),"A newly reached real schema phase updates idle time");
        rejected(()->phase.observe(1000001,"op","source","proof",2,"admission","helper","source-selection",1000001,-1,""));
        phase.observe(1000002,"op","source","proof",2,"admission","helper","schema-verification",1000002,-1,"");
        check(phase.expired(1000000+admission),"Repeated schema heartbeat cannot refresh idle deadline");
        var idle=timing();idle.readProgress(100,audit,1,rate,rate);
        check(!idle.readProgress(admission-1,audit,1,rate,rate),"Same byte count is not fresh progress");
        rejected(()->idle.readProgress(admission+100,audit,2,rate,rate));
        var pressure=new ServerStartupTiming(0,"op","source","proof",bytes,64L<<20);
        for(int second=1;second<=3584;second++)
            pressure.readProgress(second*1000L,audit,second*(2L<<20),64L<<20,2L<<20);
        check(!pressure.expired(3584000),"Active memory-pressure rate is distinct from configured Fast");
        rejected(()->pressure.readProgress(3584100,audit,bytes-1,64L<<20,2L<<20));
        rejected(()->pressure.readProgress(3584100,audit,bytes,rate,rate));
        rejected(()->pressure.readProgress(3584100,audit,bytes,64L<<20,1));
        // Sparse one-byte heartbeats cannot outlive the receipt-sized hard budget.
        var trickle=timing();
        for(int i=1;i<12;i++)trickle.readProgress(i*60000L,audit,i,rate,rate);
        check(trickle.expired(admission),"Trickle cannot renew the hard deadline");
        System.out.println("PASS: separate startup budgets and immutable source/operation-bound progress");
    }
}
