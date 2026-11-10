package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;
import java.util.Map;

/** Real temporary procfs/sysfs-shaped trees. No device sensor, Android API or guest process is used. */
public final class ThermalTelemetryTests {
    private static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void write(Path file, String text) throws IOException {
        Files.createDirectories(file.getParent());
        Files.write(file, text.getBytes(StandardCharsets.US_ASCII));
    }
    /** A stat line in the kernel's layout: utime/stime are fields 14/15, starttime is field 22. */
    private static String stat(int pid, String comm, long user, long system, long start) {
        StringBuilder line = new StringBuilder().append(pid).append(" (").append(comm).append(") S 1");
        for (int field = 5; field <= 13; field++) line.append(" 0");
        line.append(' ').append(user).append(' ').append(system);
        for (int field = 16; field <= 21; field++) line.append(" 0");
        line.append(' ').append(start).append(" 0 0\n");
        return line.toString();
    }
    private static void process(Path proc, int pid, String comm, String argv0, long user, long system, long start) throws IOException {
        write(proc.resolve(pid + "/stat"), stat(pid, comm, user, system, start));
        write(proc.resolve(pid + "/cmdline"), argv0 == null ? "" : argv0 + "\0--secret-argument\0");
    }
    private static void remove(Path root) throws IOException {
        try (var paths = Files.walk(root)) {
            for (Path path : paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new)) Files.delete(path);
        }
    }

    private static void roles() {
        check("app".equals(ThermalTelemetry.role("/system/bin/app_process64", true)), "own process is the app");
        check("proot-tracer".equals(ThermalTelemetry.role("/data/app/x/lib/arm64/libproot.so", false)), "PRoot tracer");
        check("xserver".equals(ThermalTelemetry.role("/usr/bin/Xtigervnc", false)), "X server");
        check("frame-helper".equals(ThermalTelemetry.role("/esteria-bridges/bin/esteria-x11-frame", false)), "frame helper");
        check("input-helper".equals(ThermalTelemetry.role("/esteria-bridges/bin/esteria-x11-input", false)), "input helper");
        check("wineserver".equals(ThermalTelemetry.role("/opt/wine/bin/wineserver", false)), "wineserver");
        check("wine-client".equals(ThermalTelemetry.role("Z:\\work\\launch\\abc\\WowClient64.exe", false)), "game exe");
        check("wine-services".equals(ThermalTelemetry.role("C:\\windows\\system32\\services.exe", false)), "Wine services");
        check("wine-client".equals(ThermalTelemetry.role("/opt/wine/bin/wine64-preloader", false)), "Wine loader");
        check("worldserver".equals(ThermalTelemetry.role("/esteria-server-programs/bin/worldserver", false)), "worldserver");
        check("authserver".equals(ThermalTelemetry.role("/esteria-server-programs/bin/authserver", false)), "authserver");
        check("mysqld".equals(ThermalTelemetry.role("/usr/sbin/mysqld", false)), "database");
        check("server-helper".equals(ThermalTelemetry.role("/usr/bin/python3", false)), "server helper");
        check("other".equals(ThermalTelemetry.role("", false)) && "other".equals(ThermalTelemetry.role("/bin/unknown", false)), "unknown programs");
    }

    private static void parsing() {
        long[] values = ThermalTelemetry.parseStat(stat(7, "a (weird) name", 120, 30, 9999));
        check(values != null && values[0] == 150 && values[1] == 9999, "comm with spaces and parentheses");
        check(ThermalTelemetry.parseStat("7 (short) S 1 2") == null && ThermalTelemetry.parseStat(null) == null, "truncated stat");
        check(Long.valueOf(37).equals(ThermalTelemetry.leadingNumber("37 %\n")), "KGSL busy percentage");
        check(Double.valueOf(45.5).equals(ThermalTelemetry.celsius(45500L)) && Double.valueOf(41.0).equals(ThermalTelemetry.celsius(41L)),
            "millidegrees and degrees");
        check(ThermalTelemetry.celsius(-273000L) == null && ThermalTelemetry.celsius(0L) == null, "invalid sensor readings");
        check("cpu-1-0-usr".equals(ThermalTelemetry.label("cpu-1-0-usr\n")) && ThermalTelemetry.label("bad label") == null &&
            ThermalTelemetry.label("x".repeat(33)) == null, "sensor labels are sanitized");
    }

    private static void sampling(Path root) throws IOException {
        Path proc = root.resolve("proc"), sys = root.resolve("sys");
        write(sys.resolve("devices/system/cpu/cpufreq/policy0/cpuinfo_max_freq"), "2016000\n");
        write(sys.resolve("devices/system/cpu/cpufreq/policy0/scaling_cur_freq"), "1000000\n");
        write(sys.resolve("devices/system/cpu/cpufreq/policy0/scaling_max_freq"), "2016000\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/gpu_busy_percentage"), "40 %\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/gpuclk"), "500000000\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/max_gpuclk"), "680000000\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/devfreq/min_freq"), "401000000\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/devfreq/governor"), "msm-adreno-tz\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/gpu_available_frequencies"), "680000000 615000000 401000000 220000000 bad\n");
        write(sys.resolve("class/thermal/thermal_zone0/type"), "cpu-1-0-usr\n");
        write(sys.resolve("class/thermal/thermal_zone0/temp"), "61000\n");
        write(sys.resolve("class/thermal/thermal_zone1/type"), "gpuss-0\n");
        write(sys.resolve("class/thermal/thermal_zone1/temp"), "58000\n");
        // A zone whose temperature is denied is dropped after the first read.
        write(sys.resolve("class/thermal/thermal_zone2/type"), "denied\n");
        process(proc, 100, "app", "/system/bin/app_process64", 500, 100, 1);
        process(proc, 200, "libproot.so", "/data/app/x/lib/arm64/libproot.so", 100, 0, 10);
        process(proc, 4321, "worldserver", "/esteria-server-programs/bin/worldserver", 1000, 0, 11);
        ThermalTelemetry telemetry = new ThermalTelemetry(proc, sys, 100, 100);
        telemetry.sample(1_000, 0.40, 120.0);

        // Ten seconds later: worldserver used 5 s of CPU, the tracer 1 s; a new frame helper started.
        write(sys.resolve("devices/system/cpu/cpufreq/policy0/scaling_cur_freq"), "2000000\n");
        write(sys.resolve("devices/system/cpu/cpufreq/policy0/scaling_max_freq"), "1500000\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/gpu_busy_percentage"), "80 %\n");
        write(sys.resolve("class/kgsl/kgsl-3d0/max_gpuclk"), "401000000\n");
        write(sys.resolve("class/thermal/thermal_zone0/temp"), "66500\n");
        process(proc, 200, "libproot.so", "/data/app/x/lib/arm64/libproot.so", 200, 0, 10);
        process(proc, 4321, "worldserver", "/esteria-server-programs/bin/worldserver", 1300, 200, 11);
        process(proc, 300, "frame", "/esteria-bridges/bin/esteria-x11-frame", 50, 0, 900);
        telemetry.sample(11_000, 0.65, 60.0);

        // A reused PID with a new start time is a different process; its whole lifetime counts.
        process(proc, 300, "frame", "/esteria-bridges/bin/esteria-x11-frame", 20, 0, 2000);
        Files.delete(proc.resolve("200/stat"));
        telemetry.sample(21_000, Double.NaN, null);

        Map<String, String> facts = telemetry.facts();
        String text = facts.toString();
        check("3".equals(facts.get("samples")) && "20000".equals(facts.get("elapsedMs")), "window");
        check("0.40".equals(facts.get("thermalHeadroom.start")) && "0.65".equals(facts.get("thermalHeadroom.max")) &&
            "2".equals(facts.get("thermalHeadroom.samples")), "headroom ignores NaN");
        check("60.0".equals(facts.get("display.refreshHz.min")) && "120.0".equals(facts.get("display.refreshHz.max")), "refresh");
        // Three readings of 1000, 2000 and 2000 MHz; the cap fell from 2016 to 1500 MHz.
        check("1667".equals(facts.get("cpu.policy0.curAvgMHz")) && "2000".equals(facts.get("cpu.policy0.curMaxMHz")) &&
            "1500".equals(facts.get("cpu.policy0.capMinMHz")) && "2016".equals(facts.get("cpu.policy0.hwMaxMHz")), "CPU policy and throttle cap");
        check("67".equals(facts.get("gpu.busyAvgPct")) && "80".equals(facts.get("gpu.busyMaxPct")) &&
            "500".equals(facts.get("gpu.clockMaxMHz")) && !facts.containsKey("gpu.tempMaxC"), "GPU without a temperature file");
        // A thermal or profile cap fell from 680 to 401 MHz while the floor stayed at 401 MHz.
        check("401".equals(facts.get("gpu.capMinMHz")) && "680".equals(facts.get("gpu.capMaxMHz")) &&
            "401".equals(facts.get("gpu.floorMaxMHz")) && "msm-adreno-tz".equals(facts.get("gpu.governor")) &&
            "680,615,401,220".equals(facts.get("gpu.stepsMHz")), "GPU clock limits");
        check("2".equals(facts.get("zones.readable")) && "66.5".equals(facts.get("zone.cpu-1-0-usr.maxC")) &&
            "58.0".equals(facts.get("zone.gpuss-0.maxC")) && !text.contains("denied"), "zones");
        check("5.0".equals(facts.get("role.worldserver.cpuSeconds")) && "25.0".equals(facts.get("role.worldserver.avgCorePct")) &&
            "50.0".equals(facts.get("role.worldserver.peakCorePct")), "worldserver CPU from the baseline");
        check("1.0".equals(facts.get("role.proot-tracer.cpuSeconds")), "tracer CPU stops when its stat disappears");
        check("0.7".equals(facts.get("role.frame-helper.cpuSeconds")) && "1".equals(facts.get("role.frame-helper.maxProcesses")),
            "new processes count from their start, including a reused PID");
        check("0.0".equals(facts.get("role.app.cpuSeconds")), "baseline excludes CPU before the window");
        check(!text.contains("secret") && !text.contains("/data/") && !text.contains("4321") && !text.contains("esteria-bridges"),
            "no arguments, paths or PIDs");
    }

    private static void unavailable(Path root) throws IOException {
        Files.createDirectories(root.resolve("empty"));
        ThermalTelemetry telemetry = new ThermalTelemetry(root.resolve("empty/proc"), root.resolve("empty/sys"), 1, 100);
        check(telemetry.facts().isEmpty(), "no window before a sample");
        telemetry.sample(5, null, null);
        telemetry.sample(10, null, null);
        Map<String, String> facts = telemetry.facts();
        check("unavailable".equals(facts.get("cpu.status")) && "unavailable".equals(facts.get("gpu.status")) &&
            "unavailable".equals(facts.get("zones.status")) && "unavailable".equals(facts.get("process.status")) &&
            "unavailable".equals(facts.get("thermalHeadroom")) && "unavailable".equals(facts.get("display.refreshHz")),
            "every denied source is reported, not guessed");
    }

    private static void graphics(Path root) throws IOException {
        Path config = root.resolve("Config.wtf");
        write(config, "SET realmList \"127.0.0.1:3724\"\r\nSET gxResolution \"1280x720\"\r\nSET gxMultisample \"4\"\r\n" +
            "SET farclip \"777\"\r\nSET accountName \"someone\"\r\nSET ffxGlow \"1\"\r\nSET shadowLevel \"bad;value\"\r\n" +
            "SET maxFPS \"30\"\r\nSET lumenveil \"0\"\r\n");
        Map<String, String> settings = ClientGraphicsSettings.read(config);
        check("1280x720".equals(settings.get("gxresolution")) && "4".equals(settings.get("gxmultisample")) &&
            "777".equals(settings.get("farclip")) && "1".equals(settings.get("ffxglow")) && "30".equals(settings.get("maxfps")) &&
            "0".equals(settings.get("lumenveil")), "graphics CVars, including the Lumenveil switch");
        check(!settings.containsKey("realmlist") && !settings.containsKey("accountname") && !settings.containsKey("shadowlevel"),
            "non-graphics and unsafe values are excluded");
        check(ClientGraphicsSettings.read(root.resolve("missing.wtf")).isEmpty() && ClientGraphicsSettings.read(null).isEmpty(),
            "missing settings");
    }

    public static void main(String[] args) throws Exception {
        Path root = Files.createTempDirectory("esteria-thermal-telemetry");
        try {
            roles(); parsing(); sampling(root); unavailable(root); graphics(root);
        } finally {
            remove(root);
        }
        System.out.println("Thermal telemetry passed 5 host groups: roles, parsing, sampled procfs/sysfs window, unavailable sources, graphics settings; no device sensor or Android run");
    }
}
