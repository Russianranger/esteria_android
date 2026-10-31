package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Host ZIP inventory pressure fixture; no game data or device-LMK claim. */
public final class ZipSafetyMemoryTests {
    private ZipSafetyMemoryTests() { }
    public static void main(String[] args) throws Exception {
        Path directory = Files.createTempDirectory("esteria-zip-metadata-pressure-");
        Path archive = directory.resolve("long-names.zip");
        try {
            // Setup streams empty entries. The parser must never allocate from
            // payload size or retain all decoded names during its safety pass.
            try (ZipOutputStream output = new ZipOutputStream(Files.newOutputStream(archive))) {
                String suffix = "a".repeat(880);
                for (int index = 0; index < 1300; index++) {
                    output.putNextEntry(new ZipEntry("entry-" + index + "-" + suffix));
                    output.closeEntry();
                }
            }
            if (ZipSafety.inspect(archive, 2000, GameDataImporter.MetadataBudget.DEFAULT_MAX_BYTES,
                    GameDataImporter.NEVER_CANCELLED) != 1300) throw new AssertionError("Long-name inventory lost entries");
            AtomicInteger checks = new AtomicInteger();
            try {
                ZipSafety.inspect(archive, 2000, GameDataImporter.MetadataBudget.DEFAULT_MAX_BYTES,
                        () -> checks.incrementAndGet() >= 650);
                throw new AssertionError("Central-directory cancellation ignored");
            } catch (GameDataImporter.ImportCancelledException expected) {
                if (checks.get() > 650) throw new AssertionError("Cancellation did not stop promptly");
            }
            try {
                ZipSafety.inspect(archive, 2000, 512 * 1024, GameDataImporter.NEVER_CANCELLED);
                throw new AssertionError("Oversized central directory was accepted");
            } catch (IOException expected) {
                if (!expected.getMessage().contains("memory budget")) throw new AssertionError("Imprecise budget refusal", expected);
            }
            System.out.println("PASS ZIP 1300 long names under constrained heap, bounded central directory and mid-inventory cancellation");
        } finally {
            Files.deleteIfExists(archive);
            Files.deleteIfExists(directory);
        }
    }
}
