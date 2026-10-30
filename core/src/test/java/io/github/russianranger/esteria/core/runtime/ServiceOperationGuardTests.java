package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

public final class ServiceOperationGuardTests {
    private static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
    public static void main(String[] arguments) throws Exception {
        ServiceOperationGuard guard=new ServiceOperationGuard();
        CountDownLatch started=new CountDownLatch(1),finishFile=new CountDownLatch(1);
        AtomicBoolean cancellationObserved=new AtomicBoolean(),fileCompleted=new AtomicBoolean();
        AtomicReference<Throwable> failure=new AtomicReference<>();
        Thread operation=new Thread(()->{
            try {guard.run(()->{
                started.countDown();
                try {
                    while(!guard.isStopRequested())Thread.sleep(1);
                    cancellationObserved.set(true);
                    if(!finishFile.await(5,TimeUnit.SECONDS))throw new IOException("Fixture SQL boundary timed out");
                }catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}
                fileCompleted.set(true);return null;
            });}catch(Throwable error){failure.set(error);}
        },"owned-sql-fixture");
        operation.start();check(started.await(2,TimeUnit.SECONDS),"Actual operation must acquire its guard");
        long before=System.nanoTime();
        try {guard.stopWithin(Duration.ofMillis(40));throw new AssertionError("In-flight SQL must retain its service");}
        catch(IOException expected){check(expected.getMessage().contains("retained"),"Timeout explains retained ownership");}
        check(System.nanoTime()-before<TimeUnit.SECONDS.toNanos(1),"Shutdown honors its bounded wait");
        check(guard.isStopRequested(),"Shutdown cancellation must remain visible");
        check(!fileCompleted.get(),"Timeout must not force-complete/interrupt the SQL file");
        finishFile.countDown();operation.join(2000);
        check(!operation.isAlive() && failure.get()==null && cancellationObserved.get() && fileCompleted.get(),
            "Operation reaches its own SQL boundary after cancellation");
        try(ServiceOperationGuard.StopPermit permit=guard.stopWithin(Duration.ofSeconds(1))) {
            check(permit.remaining().compareTo(Duration.ofSeconds(1))<=0,"Stop receives only its remaining deadline");
            check(permit.remaining().compareTo(Duration.ZERO)>0,"Retry can cleanly stop after the safe boundary");
        }
        try {guard.run(()->null);throw new AssertionError("New SQL must not start during requested shutdown");}
        catch(IOException expected){check(expected.getMessage().contains("shutdown"),"New work fails explicitly");}
        ServiceOperationGuard idle=new ServiceOperationGuard();
        try(ServiceOperationGuard.StopPermit permit=idle.stopWithin(Duration.ZERO)) {
            check(permit.remaining().equals(Duration.ZERO),"Idle zero-budget shutdown retains original forced-stop semantics");
        }
        System.out.println("Service operation cancellation, safe-boundary retention and shutdown deadlines passed; no engine execution claimed");
    }
}
