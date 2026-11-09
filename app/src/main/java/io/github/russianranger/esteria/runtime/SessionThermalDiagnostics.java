package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.BatteryManager;
import android.os.Build;
import android.os.PowerManager;
import android.os.SystemClock;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Worker-owned readings over the reconstructed client lifetime. Holds no listener or timer. */
public final class SessionThermalDiagnostics {
    static final long INTERVAL_MS = 30_000;
    private final LongSupplier clock;
    private final Supplier<Integer> readBattery;
    private final Supplier<Integer> readStatus;
    private final Summary battery = new Summary();
    private final Summary status = new Summary();
    private long samples, startMs, lastMs;

    public SessionThermalDiagnostics(Context context) {
        this(SystemClock::elapsedRealtime, () -> {
            Intent reading = context.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            if (reading == null || !reading.hasExtra(BatteryManager.EXTRA_TEMPERATURE)
                    || !reading.getBooleanExtra(BatteryManager.EXTRA_PRESENT, true)) return null;
            // Android's battery service broadcasts batteryTemperatureTenthsCelsius.
            return reading.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Integer.MIN_VALUE);
        }, () -> {
            if (Build.VERSION.SDK_INT < 29) return null;
            PowerManager manager = context.getSystemService(PowerManager.class);
            if (manager == null) return null;
            int value = manager.getCurrentThermalStatus();
            return value >= PowerManager.THERMAL_STATUS_NONE && value <= PowerManager.THERMAL_STATUS_SHUTDOWN
                    ? value : null;
        });
    }

    SessionThermalDiagnostics(LongSupplier clock, Supplier<Integer> readBattery, Supplier<Integer> readStatus) {
        this.clock = clock;
        this.readBattery = readBattery;
        this.readStatus = readStatus;
    }

    public void sampleIfDue() {
        long now = clock.getAsLong();
        if (samples == 0 || now - lastMs >= INTERVAL_MS) sample(now);
    }

    public void sampleAtClientStop() {
        long now = clock.getAsLong();
        if (samples > 0 && now > lastMs) sample(now);
    }

    private void sample(long now) {
        if (samples == 0) startMs = now;
        battery.observe(read(readBattery), samples == 0);
        status.observe(read(readStatus), samples == 0);
        lastMs = now;
        samples++;
    }

    private static Integer read(Supplier<Integer> reader) {
        try {
            Integer value = reader.get();
            return value == null || value == Integer.MIN_VALUE ? null : value;
        } catch (RuntimeException unavailable) {
            // Vendor service or sensor availability must never affect gameplay or shutdown.
            return null;
        }
    }

    private static final class Summary {
        Integer start, last, max;
        long available;

        void observe(Integer value, boolean first) {
            if (first) start = value;
            last = value;
            if (value == null) return;
            available++;
            if (max == null || value > max) max = value;
        }

        void append(Map<String, String> facts, String prefix, boolean tenthsCelsius) {
            facts.put(prefix + ".availableSamples", Long.toString(available));
            facts.put(prefix + ".start", format(start, tenthsCelsius));
            facts.put(prefix + ".last", format(last, tenthsCelsius));
            facts.put(prefix + ".max", format(max, tenthsCelsius));
        }

        static String format(Integer value, boolean tenthsCelsius) {
            if (value == null) return "unavailable";
            return tenthsCelsius ? Double.toString(value / 10.0) : value.toString();
        }
    }

    public Map<String, String> facts() {
        if (samples == 0) return Map.of();
        Map<String, String> result = new LinkedHashMap<>();
        result.put("game.thermal.intervalMs", Long.toString(INTERVAL_MS));
        result.put("game.thermal.elapsedMs", Long.toString(lastMs - startMs));
        result.put("game.thermal.samples", Long.toString(samples));
        battery.append(result, "game.thermal.batteryCelsius", true);
        status.append(result, "game.thermal.androidStatusCode", false);
        return result;
    }
}
