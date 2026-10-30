package io.github.russianranger.esteria.runtime;

import io.github.russianranger.esteria.core.runtime.process.OwnedProcess;
import io.github.russianranger.esteria.core.runtime.process.WorldConsoleShutdown;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Real Linux JNI streams, including binary input and kernel-pipe backpressure. */
final class NativeOwnerInputTests {
    private static void check(boolean value,String message) { if (!value) throw new AssertionError(message); }
    private static OwnedProcess.Specification spec(Path path,String command) throws IOException {
        Files.createDirectory(path);
        return new OwnedProcess.Specification(Path.of("/bin/sh"),List.of("-c",command),Map.of("PATH","/usr/bin:/bin"),
            path,path.resolve("out"),path.resolve("err"),true);
    }
    private static void done(OwnedProcess child) throws Exception {
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
        while (child.isAlive()&&System.nanoTime()<deadline) Thread.sleep(5);
        check(!child.isAlive()&&child.exitCode()==0&&child.failure()==null,"Input fixture must exit normally");
    }
    private static int fill(OwnedProcess child,byte[] message) throws Exception {
        int accepted=0;
        while (accepted<1024*1024&&child.writeInput(message,Duration.ZERO)) accepted+=message.length;
        check(accepted>0&&accepted<1024*1024,"Expected finite kernel backpressure");return accepted;
    }
    static int run(NativeProcessBridge backend,Path root) throws Exception {
        List<OwnedProcess> children=new ArrayList<>();
        try {
            Path echoPath=root.resolve("input-echo");
            OwnedProcess echo=OwnedProcess.startInteractive(backend,spec(echoPath,"cat"),null);children.add(echo);
            byte[] bytes=new byte[257];for(int i=0;i<bytes.length;i++)bytes[i]=(byte)i;
            check(echo.writeInput(bytes,Duration.ofMillis(100)),"Binary input refused");
            echo.closeInput();done(echo);check(Arrays.equals(bytes,Files.readAllBytes(echoPath.resolve("out"))),"Binary input or EOF changed");
            try { echo.writeInput(bytes,Duration.ZERO);throw new AssertionError("Exited input accepted"); } catch(IOException expected) { }
            try { backend.writeInput(999999999,bytes,0);throw new AssertionError("Unknown handle accepted"); } catch(IOException expected) { }
            try { backend.writeInput(999999999,new byte[4097],0);throw new AssertionError("Oversized input accepted"); } catch(IOException expected) { }
            System.out.println("PASS JNI binary stdin, explicit EOF, dead/unknown handles and size bound");

            Path pressurePath=root.resolve("input-pressure");
            OwnedProcess pressure=OwnedProcess.startInteractive(backend,spec(pressurePath,"while [ ! -f drain ]; do sleep .01; done; cat"),null);children.add(pressure);
            byte[] block=new byte[4096];Arrays.fill(block,(byte)'b');int accepted=fill(pressure,block);
            byte[] refused=new byte[4096];Arrays.fill(refused,(byte)'r');long began=System.nanoTime();
            check(!pressure.writeInput(refused,Duration.ofMillis(80)),"Full pipe accepted a message");
            check(System.nanoTime()-began<TimeUnit.MILLISECONDS.toNanos(500),"Backpressure wait exceeded bound");
            Files.writeString(pressurePath.resolve("drain"),"go");pressure.closeInput();done(pressure);
            byte[] actual=Files.readAllBytes(pressurePath.resolve("out")),expected=new byte[accepted];Arrays.fill(expected,(byte)'b');
            check(Arrays.equals(actual,expected),"Timed out write queued partial bytes");
            System.out.println("PASS JNI real backpressure timeout queues zero bytes");

            OwnedProcess closing=OwnedProcess.startInteractive(backend,spec(root.resolve("input-close"),"exec sleep 30"),null);children.add(closing);fill(closing,block);
            AtomicReference<Throwable> send=new AtomicReference<>();
            Thread writer=new Thread(()->{try {closing.writeInput(block,Duration.ofSeconds(1));send.set(new AssertionError("Closed writer returned normally"));}catch(Throwable failure){send.set(failure);}});
            writer.start();Thread.sleep(50);began=System.nanoTime();closing.closeInput();writer.join(1000);
            check(!writer.isAlive()&&send.get() instanceof IOException&&System.nanoTime()-began<TimeUnit.MILLISECONDS.toNanos(500),"Concurrent input close did not cancel writer");
            try {closing.stop(Duration.ZERO);}catch(IOException expectedStop) { }
            Path brokenPath=root.resolve("input-broken");
            OwnedProcess broken=OwnedProcess.startInteractive(backend,spec(brokenPath,"exec 0<&-; printf ready; exec sleep 30"),null);children.add(broken);
            long ready=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
            while(Files.size(brokenPath.resolve("out"))<5&&System.nanoTime()<ready)Thread.sleep(5);
            check(Files.readString(brokenPath.resolve("out")).equals("ready"),"Closed-reader fixture not ready");
            try {broken.writeInput(bytes,Duration.ofMillis(100));throw new AssertionError("Closed reader accepted input");}catch(IOException expectedPipe) { }
            try {broken.stop(Duration.ZERO);}catch(IOException expectedStop) { }
            System.out.println("PASS JNI concurrent close and EPIPE preserve host process");

            Path commandPath=root.resolve("input-command");
            OwnedProcess command=OwnedProcess.startInteractive(backend,spec(commandPath,
                "IFS= read -r command; [ \"$command\" = 'server shutdown 1' ] || exit 9; printf command-received > receipt"),new WorldConsoleShutdown());children.add(command);
            command.stop(Duration.ofSeconds(3));check(!command.wasForced()&&command.exitCode()==0&&command.failure()==null,"Console fixture did not finish normally");
            check(Files.readString(commandPath.resolve("receipt")).equals("command-received"),"Exact source-confirmed console command not received");
            check(Files.size(commandPath.resolve("out"))==0&&Files.size(commandPath.resolve("err"))==0,"Owner logged input content");
            System.out.println("PASS source-confirmed command delivery plus normal fixture exit; no world/save qualification");
            return 4;
        } finally {
            for(OwnedProcess child:children)if(child.isAlive())try {child.stop(Duration.ZERO);}catch(IOException expected) { }
            for(OwnedProcess child:children)check(!child.isAlive(),"Input fixture cleanup incomplete");
        }
    }
}
