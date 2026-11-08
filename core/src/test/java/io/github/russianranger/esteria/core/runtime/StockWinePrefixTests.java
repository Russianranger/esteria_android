package io.github.russianranger.esteria.core.runtime;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

/** Fast launch classification can decline mutation without opening an existing registry or Wine payload. */
final class StockWinePrefixTests {
    private static final String ARCHIVE="c0e13ed15a69fa72541684ac5cef49d71d5d95ee494146bc6e40d11b6977ab46";
    private static void require(boolean yes,String message) { if(!yes)throw new AssertionError(message); }

    static void inspectOrdinaryLaunch() throws Exception {
        Path base=Files.createTempDirectory("esteria-wine-ownership-").toRealPath();
        try {
            Path work=Files.createDirectory(base.resolve("work"));
            Path runtime=base.resolve("unread-provider");
            require(StockWinePrefix.inspect(work,runtime,ARCHIVE).status()==StockWinePrefix.Status.ABSENT,
                    "New work keeps the ordinary first-use path");
            Path sys=Files.createDirectories(work.resolve("home/.wine/drive_c/windows/system32"));
            Path driver=Files.createDirectory(sys.resolve("driverstore"));
            Path manifest=Files.write(sys.resolve("winevulkan.json"),new byte[137]);
            require(StockWinePrefix.inspect(work,runtime,ARCHIVE).status()==StockWinePrefix.Status.NO_REPAIR,
                    "A complete-looking native filesystem takes the cheap, non-mutating normal path");
            require(StockWinePrefix.inspect(work,runtime,"different").status()==StockWinePrefix.Status.UNRECOGNIZED,
                    "An unselected provider cannot authorize Wine setup");
            Files.delete(driver);
            require(!StockWinePrefix.inspect(work,runtime,ARCHIVE).requiresRepair(),"One unrelated missing file never forces setup");
            Files.delete(manifest);
            StockWinePrefix unknown=StockWinePrefix.inspect(work,runtime,ARCHIVE);
            require(unknown.status()==StockWinePrefix.Status.UNRECOGNIZED, "Vulkan files alone do not establish old Mono interruption");
            try(ExclusiveFileLease owner=ExclusiveFileLease.acquire(work.resolve(".client-launch-setup.lock"),"busy")) {
                try {unknown.beginRepair(owner);throw new AssertionError("Unknown prefix authorized mutation");}
                catch(IOException expected) { require(!Files.exists(work.resolve(".stock-wine-prefix-repair-v1.pending")),
                        "Unrecognized prefix never acquired a repair intent"); }
            }
            Files.createSymbolicLink(driver,base);
            require(!StockWinePrefix.inspect(work,runtime,ARCHIVE).requiresRepair(),"Symlinked completion witness rejected");
        } finally {
            try(var paths=Files.walk(base)) {
                for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);
            }
        }
    }
}
