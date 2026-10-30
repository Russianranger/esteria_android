package io.github.russianranger.esteria.core.runtime.process;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/** Pinned Esteria server console command. Requires Console.Enable=1 and
 * Wintergrasp.DeferShutdownTimer=0. The owner must still observe process exit;
 * neither pipe delivery nor exit alone qualifies character/bot persistence.
 */
public final class WorldConsoleShutdown implements OwnedProcess.GracefulInputStop {
    private static final byte[] COMMAND="server shutdown 1\n".getBytes(StandardCharsets.US_ASCII);
    @Override public void request(OwnedProcess process) throws IOException {
        if (!process.writeInput(COMMAND,Duration.ofMillis(500)))
            throw new IOException("World console shutdown command could not be queued within its deadline");
        // Keep stdin open: EOF itself requests StopNow in the pinned console.
    }
}
