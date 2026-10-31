package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.nio.channels.FileChannel;
import java.nio.file.Path;
import java.util.Objects;
import java.util.function.IntSupplier;

/** Sequential import I/O pacing and bounded dirty-output windows. Not thread safe. */
public final class ImportIoGovernor {
    public static final long CHECKPOINT_BYTES = 2L << 20;
    private static final long MAX_SLEEP_NANOS = 100_000_000L;
    private static final long PRESSURE_TIMEOUT_NANOS = 60_000_000_000L;
    /** Called only after the written window has been forced to storage. Advisory failures belong to the adapter. */
    public interface Relief { void release(Path output, long offset, long length) throws IOException; }
    interface NanoClock { long now(); }
    interface Sleeper { void sleep(long nanos) throws InterruptedException; }
    private final long normalRate, pressureRate;
    private final IntSupplier pressure;
    private final Relief relief;
    private final NanoClock clock;
    private final Sleeper sleeper;
    private long deadline;

    /** Pressure levels: zero normal, one slower copying, two or greater wait for recovery. Zero rates disable pacing. */
    public ImportIoGovernor(long normalBytesPerSecond, long pressureBytesPerSecond, IntSupplier pressure, Relief relief) {
        this(normalBytesPerSecond, pressureBytesPerSecond, pressure, relief, System::nanoTime,
                nanos -> Thread.sleep(nanos / 1_000_000L, (int) (nanos % 1_000_000L)));
    }
    ImportIoGovernor(long normalBytesPerSecond, long pressureBytesPerSecond, IntSupplier pressure, Relief relief,
                     NanoClock clock, Sleeper sleeper) {
        if (normalBytesPerSecond < 0 || pressureBytesPerSecond < 0 ||
                (normalBytesPerSecond == 0) != (pressureBytesPerSecond == 0) || pressureBytesPerSecond > normalBytesPerSecond)
            throw new IllegalArgumentException("Invalid import byte rates");
        normalRate = normalBytesPerSecond; pressureRate = pressureBytesPerSecond;
        this.pressure = Objects.requireNonNull(pressure); this.relief = Objects.requireNonNull(relief);
        this.clock = Objects.requireNonNull(clock); this.sleeper = Objects.requireNonNull(sleeper);
        deadline = clock.now();
    }
    /** Existing host integrations remain unpaced; output windows are still flushed periodically. */
    public static ImportIoGovernor unthrottled() { return new ImportIoGovernor(0, 0, () -> 0, (p, o, n) -> { }); }

    public Transfer begin(Path output, FileChannel channel, long initialOffset, GameDataImporter.Cancellation cancellation) throws IOException {
        if (initialOffset < 0) throw new IllegalArgumentException("Negative output offset");
        checkpoint(cancellation);
        return new Transfer(Objects.requireNonNull(output), Objects.requireNonNull(channel), initialOffset, cancellation);
    }
    /** Account for consumed input which produced no output, including a nonseekable ZIP resume prefix. */
    public void read(long bytes, GameDataImporter.Cancellation cancellation) throws IOException {
        if (bytes < 0) throw new IllegalArgumentException("Negative transfer byte count");
        checkpoint(cancellation);
        long rate = pressure.getAsInt() > 0 ? pressureRate : normalRate;
        if (rate == 0 || bytes == 0) return;
        // Public call sites use bounded chunks, but avoid overflow for any legal long count/rate.
        double duration = Math.ceil((double) bytes * 1_000_000_000d / rate);
        if (duration > Long.MAX_VALUE / 2d) throw new IllegalArgumentException("Transfer chunk too large");
        long now = clock.now();
        deadline = Math.max(deadline, now) + (long) duration;
        while (deadline - clock.now() > 0) {
            checkpoint(cancellation);
            sleep(Math.min(MAX_SLEEP_NANOS, Math.max(0, deadline - clock.now())), cancellation);
        }
        checkCancelled(cancellation);
    }
    /** Severe pressure waits briefly for recovery, then pauses the import without publishing its generation. */
    public void checkpoint(GameDataImporter.Cancellation cancellation) throws IOException {
        checkCancelled(cancellation);
        long began = clock.now();
        while (pressure.getAsInt() >= 2) {
            if (clock.now() - began >= PRESSURE_TIMEOUT_NANOS) throw new GameDataImporter.ImportMemoryPressureException();
            sleep(MAX_SLEEP_NANOS, cancellation);
        }
        checkCancelled(cancellation);
    }
    private void sleep(long nanos, GameDataImporter.Cancellation cancellation) throws IOException {
        checkCancelled(cancellation);
        if (nanos <= 0) return;
        try { sleeper.sleep(nanos); }
        catch (InterruptedException interrupted) { Thread.currentThread().interrupt(); throw new GameDataImporter.ImportCancelledException(); }
        checkCancelled(cancellation);
    }
    private static void checkCancelled(GameDataImporter.Cancellation cancellation) throws GameDataImporter.ImportCancelledException {
        if (Objects.requireNonNull(cancellation).isCancelled() || Thread.currentThread().isInterrupted())
            throw new GameDataImporter.ImportCancelledException();
    }

    public final class Transfer {
        private final Path output;
        private final FileChannel channel;
        private final GameDataImporter.Cancellation cancellation;
        private long position, flushed;
        private boolean finished;
        private Transfer(Path output, FileChannel channel, long offset, GameDataImporter.Cancellation cancellation) {
            this.output = output; this.channel = channel; position = offset; flushed = offset; this.cancellation = cancellation;
        }
        /** Call after each completed bounded write, before reading the next input chunk. */
        public void wrote(long bytes) throws IOException {
            if (finished || bytes < 0 || bytes > Long.MAX_VALUE - position) throw new IllegalArgumentException("Invalid output transfer");
            position += bytes;
            if (position - flushed >= CHECKPOINT_BYTES) flush(false);
            read(bytes, cancellation);
        }
        /** Preserve the original final durable sync, then release only the remaining clean output window. */
        public void finish() throws IOException {
            if (finished) throw new IllegalStateException("Output transfer already finished");
            checkCancelled(cancellation);
            flush(true); finished = true;
            checkpoint(cancellation);
        }
        private void flush(boolean metadata) throws IOException {
            checkCancelled(cancellation);
            channel.force(metadata);
            if (position > flushed) { relief.release(output, flushed, position - flushed); flushed = position; }
        }
    }
}
