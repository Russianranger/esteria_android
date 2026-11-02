package io.github.russianranger.esteria.core.runtime.install;

/** Verification/copy pacing only. Native worker count and memory limits stay fixed. */
public enum PreparationSpeed {
    GENTLE("gentle", "Gentle — 8 MiB/s", 8L << 20),
    BALANCED("balanced", "Balanced — 32 MiB/s", 32L << 20),
    FAST("fast", "Fast — 64 MiB/s", 64L << 20);

    public static final PreparationSpeed DEFAULT = BALANCED;
    public static final String ENVIRONMENT_KEY = "ESTERIA_PREPARATION_SPEED";
    public final String id, label;
    public final long bytesPerSecond;

    PreparationSpeed(String id, String label, long bytesPerSecond) {
        this.id = id; this.label = label; this.bytesPerSecond = bytesPerSecond;
    }
    public static PreparationSpeed fromId(String id) {
        for (PreparationSpeed speed : values()) if (speed.id.equals(id)) return speed;
        throw new IllegalArgumentException("Unknown preparation speed");
    }
    @Override public String toString() { return label; }
}
