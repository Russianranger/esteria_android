package io.github.russianranger.esteria.core.presentation;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;

/** Bounded observations of X11 replies and successful Android buffer posts, across surface lifetimes. */
public final class PresentationSamples {
    private static final long MILLIS = 1_000_000L;
    public static final long IDLE_AFTER_NANOS = 500 * MILLIS;
    private final long[] postIntervals = new long[257]; // Millisecond upper edges through 255, then overflow.
    private long posted, unchanged, idleReadbacks, bytes, captureNs, receiveNs, surfaceNs;
    private long observedNs, intervalCount, maxIntervalNs;

    /** The pinned guest handles 30/60 FPS. At 24 FPS the reader paces requests itself. */
    public static long requestDelayNanos(int cap, long lastStart, long now) {
        return cap == 24 ? Math.max(0, 1_000_000_000L / 24 - (now - lastStart)) : 0;
    }

    public static boolean idleReadback(long now, long lastChange, long lastInput) {
        return now - lastChange >= IDLE_AFTER_NANOS && now - lastInput >= IDLE_AFTER_NANOS;
    }

    /**
     * Applies idle pacing to the normal readback interval.
     * After half a second of identical pixels and no input, poll at half rate
     * with a 15 Hz floor. A changed frame or input restores the selected cadence.
     */
    public static long requestDelayNanos(int cap, long lastStart, long now, long lastChange, long lastInput) {
        if (!idleReadback(now, lastChange, lastInput)) {
            return requestDelayNanos(cap, lastStart, now);
        }
        long idleInterval = cap == 60 ? 1_000_000_000L / 30 : 1_000_000_000L / 15;
        return Math.max(0, idleInterval - (now - lastStart));
    }

    /** Caller supplies elapsed time since previous successful reply within this attachment, or since the first request. */
    public void reply(boolean changed, long elapsedNs, long sincePreviousPostNs, long[] nativeStats) {
        reply(changed, elapsedNs, sincePreviousPostNs, nativeStats, false);
    }

    public synchronized void reply(boolean changed, long elapsedNs, long sincePreviousPostNs, long[] nativeStats,
                                   boolean idleRequest) {
        if (idleRequest) idleReadbacks++;
        observedNs += elapsedNs;
        if (!changed) {
            unchanged++;
            return;
        }
        posted++;
        bytes += nativeStats[5];
        captureNs += nativeStats[2];
        receiveNs += nativeStats[3];
        surfaceNs += nativeStats[4];
        if (sincePreviousPostNs >= 0) {
            intervalCount++;
            maxIntervalNs = Math.max(maxIntervalNs, sincePreviousPostNs);
            int bin = (int)Math.min(256, ceilMs(sincePreviousPostNs));
            postIntervals[bin]++;
        }
    }

    public synchronized long[] counters() {
        return new long[]{posted, unchanged, bytes, captureNs, receiveNs, surfaceNs};
    }

    private static long ceilMs(long ns) { return (ns + MILLIS - 1) / MILLIS; }

    private long percentile(int percent) {
        long rank = (intervalCount * percent + 99) / 100, count = 0;
        for (int i = 0; i < postIntervals.length - 1; i++) {
            count += postIntervals[i];
            if (count >= rank) return i;
        }
        return ceilMs(maxIntervalNs);
    }

    public synchronized Map<String,String> facts() {
        Map<String,String> facts = new LinkedHashMap<>();
        facts.put("presentation.postedFrames", Long.toString(posted));
        facts.put("presentation.unchangedReads", Long.toString(unchanged));
        facts.put("presentation.idleReadbacks", Long.toString(idleReadbacks));
        facts.put("presentation.observedMs", Long.toString(observedNs / MILLIS));
        facts.put("presentation.postedBytes", Long.toString(bytes));
        // Native timings describe changed replies only. Receive includes waiting for the guest and its capture.
        facts.put("presentation.changedCaptureMs", Long.toString(captureNs / MILLIS));
        facts.put("presentation.changedRequestToPixelsMs", Long.toString(receiveNs / MILLIS));
        facts.put("presentation.changedSurfaceMs", Long.toString(surfaceNs / MILLIS));
        if (observedNs >= 1_000_000_000L)
            facts.put("presentation.postsPerSecond", String.format(Locale.ROOT, "%.2f", posted * 1e9 / observedNs));
        facts.put("presentation.postIntervals", Long.toString(intervalCount));
        if (intervalCount > 0) {
            facts.put("presentation.postIntervalP50UpperMs", Long.toString(percentile(50)));
            facts.put("presentation.postIntervalP95UpperMs", Long.toString(percentile(95)));
            facts.put("presentation.postIntervalMaxMs", Long.toString(ceilMs(maxIntervalNs)));
        }
        return facts;
    }
}
