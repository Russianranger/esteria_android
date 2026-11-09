package io.github.russianranger.esteria.runtime;

import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.display.DisplayManager;
import android.os.BatteryManager;
import android.os.Build;
import android.os.PowerManager;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import android.view.Display;
import io.github.russianranger.esteria.core.diagnostics.ThermalTelemetry;
import java.nio.file.Paths;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.LongSupplier;
import java.util.function.Supplier;

/** Worker-owned readings over the reconstructed client lifetime. Holds no listener or timer. */
public final class SessionThermalDiagnostics {
    static final long INTERVAL_MS = 10_000;
    private final LongSupplier clock;
    private final Supplier<Integer> readBattery;
    private final Supplier<Integer> readStatus;
    private final Supplier<Double> readHeadroom;
    private final Supplier<Double> readRefresh;
    private final ThermalTelemetry telemetry;
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
        }, () -> headroom(context), () -> {
            DisplayManager displays = context.getSystemService(DisplayManager.class);
            Display display = displays == null ? null : displays.getDisplay(Display.DEFAULT_DISPLAY);
            return display == null ? null : (double) display.getRefreshRate();
        }, new ThermalTelemetry(Paths.get("/proc"), Paths.get("/sys"), android.os.Process.myPid(), clockTicks()));
    }

    SessionThermalDiagnostics(LongSupplier clock, Supplier<Integer> readBattery, Supplier<Integer> readStatus) {
        this(clock, readBattery, readStatus, () -> null, () -> null, null);
    }

    SessionThermalDiagnostics(LongSupplier clock, Supplier<Integer> readBattery, Supplier<Integer> readStatus,
                              Supplier<Double> readHeadroom, Supplier<Double> readRefresh, ThermalTelemetry telemetry) {
        this.clock = clock;
        this.readBattery = readBattery;
        this.readStatus = readStatus;
        this.readHeadroom = readHeadroom;
        this.readRefresh = readRefresh;
        this.telemetry = telemetry;
    }

    /** Android's normalized forecast: 1.0 corresponds to severe throttling. NaN when unsupported. */
    private static Double headroom(Context context) {
        if (Build.VERSION.SDK_INT < 30) return null;
        PowerManager manager = context.getSystemService(PowerManager.class);
        return manager == null ? null : (double) manager.getThermalHeadroom(10);
    }

    private static long clockTicks() {
        long ticks = Os.sysconf(OsConstants._SC_CLK_TCK);
        return ticks > 0 ? ticks : 100;
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
        if (telemetry != null) {
            try {
                telemetry.sample(now, read(readHeadroom), read(readRefresh));
            } catch (RuntimeException unavailable) {
                // Procfs, sysfs or vendor sensor failures must never affect gameplay or shutdown.
            }
        }
        lastMs = now;
        samples++;
    }

    private static <T> T read(Supplier<T> reader) {
        try {
            T value = reader.get();
            return value == null || Integer.valueOf(Integer.MIN_VALUE).equals(value) ? null : value;
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

    /** Device load and sensor detail for the separate bounded support field; empty without a window. */
    public Map<String, String> detail() {
        if (samples == 0 || telemetry == null) return Map.of();
        return telemetry.facts();
    }
}
