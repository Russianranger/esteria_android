package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;

/** Synthetic monotonic times; no Android/server/gameplay evidence. */
public final class ServerStartupTimingTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    private interface Checked {void run()throws Exception;}
    private static void rejected(Checked action)throws Exception {
        try{action.run();throw new AssertionError("Invalid status accepted");}catch(IOException expected){ }
    }
    private static ServerStartupTiming timing(){return new ServerStartupTiming(0,"op","source","proof");}
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
        System.out.println("PASS: separate startup budgets and immutable source/operation-bound progress");
    }
}
