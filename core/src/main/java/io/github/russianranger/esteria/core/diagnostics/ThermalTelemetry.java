package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;

/** Bounded heat and load observations over one client session, read from procfs and sysfs.
 *
 * Every source is optional. Android, SELinux or the vendor may deny a file; the first
 * complete denial marks that source unavailable and it is not read again, so a
 * session does not repeat denied reads. Output contains fixed process-role labels and
 * hardware sensor labels only. It never contains PIDs, process names, arguments or
 * paths. Process CPU covers every process this app's UID can see, including PRoot
 * tracers and their guests. These are observations, not temperature or gameplay
 * qualification. */
public final class ThermalTelemetry {
    public static final int MAX_PROCESSES = 512, MAX_ZONES = 160, REPORTED_ZONES = 8, MAX_POLICIES = 8, MAX_ROLES = 16;
    private static final int SMALL_FILE = 4096;
    private static final Set<String> WINE_SERVICES = Set.of("services.exe", "winedevice.exe", "plugplay.exe",
        "explorer.exe", "rpcss.exe", "svchost.exe", "conhost.exe", "start.exe", "wineboot.exe", "tabtip.exe");

    private enum Source { UNKNOWN, AVAILABLE, UNAVAILABLE }

    /** Running summary of a numeric reading. */
    static final class Stat {
        long count; double first, last, sum, min = Double.POSITIVE_INFINITY, max = Double.NEGATIVE_INFINITY;
        void observe(double value) {
            if (count == 0) first = value;
            last = value; sum += value; count++;
            if (value < min) min = value;
            if (value > max) max = value;
        }
        double average() { return count == 0 ? Double.NaN : sum / count; }
    }

    private static final class Policy {
        final String label; final Path directory; final Stat current = new Stat(), cap = new Stat(); Long hardwareMaxKhz;
        Policy(String label, Path directory) { this.label = label; this.directory = directory; }
    }

    private static final class Zone {
        final String label; final Path temperature; final Stat celsius = new Stat();
        Zone(String label, Path temperature) { this.label = label; this.temperature = temperature; }
    }

    private static final class Seen {
        final long start, ticks; final String role;
        Seen(long start, long ticks, String role) { this.start = start; this.ticks = ticks; this.role = role; }
    }

    private static final class Role {
        long ticks; int maxProcesses; double peakCorePercent;
        long residentMaxKib = -1, residentLastKib = -1, swapMaxKib = -1, gpuMaxKib = -1, gpuLastKib = -1;
    }

    /** Resident (anonymous plus shared), swapped and KGSL GPU memory of one sample, in KiB; -1 when unreadable. */
    private static final class Memory {
        long resident = -1, swap = -1, gpu = -1;
        void add(long[] reading) {
            if (reading[0] >= 0) resident = Math.max(0, resident) + reading[0];
            if (reading[1] >= 0) swap = Math.max(0, swap) + reading[1];
            if (reading[2] >= 0) gpu = Math.max(0, gpu) + reading[2];
        }
    }

    private final Path proc, sys;
    private final int selfPid;
    private final long ticksPerSecond;
    private Source cpufreq = Source.UNKNOWN, gpu = Source.UNKNOWN, zones = Source.UNKNOWN, processes = Source.UNKNOWN,
        meminfo = Source.UNKNOWN, pressure = Source.UNKNOWN, kgslProcesses = Source.UNKNOWN;
    private final Stat memoryAvailable = new Stat(), swapFree = new Stat(), pressureSome = new Stat(), pressureFull = new Stat(),
        stackResident = new Stat(), stackSwap = new Stat(), stackGpu = new Stat(), gpuPages = new Stat();
    private long memoryTotalKib = -1, swapTotalKib = -1;
    private final List<Policy> policies = new ArrayList<>();
    private final List<Zone> thermalZones = new ArrayList<>();
    private final Stat headroom = new Stat(), refresh = new Stat(), gpuBusy = new Stat(), gpuClock = new Stat(), gpuTemperature = new Stat(),
        gpuCap = new Stat(), gpuFloor = new Stat();
    private String gpuGovernor, gpuSteps;
    private Map<Integer, Seen> seen = new HashMap<>();
    private final Map<String, Role> roles = new TreeMap<>();
    private int visibleProcessesMax;
    private long samples, firstMs, lastMs;

    /** @param proc normally /proc; @param sys normally /sys; @param selfPid this app's process id. */
    public ThermalTelemetry(Path proc, Path sys, int selfPid, long ticksPerSecond) {
        if (proc == null || sys == null || ticksPerSecond <= 0) throw new IllegalArgumentException("Telemetry roots and clock ticks required");
        this.proc = proc; this.sys = sys; this.selfPid = selfPid; this.ticksPerSecond = ticksPerSecond;
    }

    /** Read every available source once. Android-only readings are supplied by the caller and may be null. */
    public void sample(long nowMs, Double thermalHeadroom, Double refreshHz) {
        long interval = samples == 0 ? 0 : Math.max(0, nowMs - lastMs);
        if (samples == 0) firstMs = nowMs;
        if (thermalHeadroom != null && Double.isFinite(thermalHeadroom) && thermalHeadroom >= 0) headroom.observe(thermalHeadroom);
        if (refreshHz != null && Double.isFinite(refreshHz) && refreshHz > 0) refresh.observe(refreshHz);
        readPolicies();
        readGpu();
        readZones();
        readMemory();
        readProcesses(interval, samples == 0);
        lastMs = nowMs;
        samples++;
    }

    public long samples() { return samples; }

    // ---- CPU frequency policies ----

    private void readPolicies() {
        if (cpufreq == Source.UNAVAILABLE) return;
        if (cpufreq == Source.UNKNOWN) {
            Path root = sys.resolve("devices/system/cpu/cpufreq");
            for (Path directory : children(root, "policy", MAX_POLICIES)) {
                String label = directory.getFileName().toString();
                if (label.matches("policy[0-9]{1,3}")) policies.add(new Policy(label, directory));
            }
            policies.sort(Comparator.comparingInt(policy -> Integer.parseInt(policy.label.substring(6))));
        }
        boolean any = false;
        for (Policy policy : policies) {
            if (policy.hardwareMaxKhz == null) policy.hardwareMaxKhz = number(policy.directory.resolve("cpuinfo_max_freq"));
            Long current = number(policy.directory.resolve("scaling_cur_freq"));
            Long cap = number(policy.directory.resolve("scaling_max_freq"));
            if (current != null && current > 0) { policy.current.observe(current / 1000.0); any = true; }
            if (cap != null && cap > 0) { policy.cap.observe(cap / 1000.0); any = true; }
        }
        cpufreq = settle(cpufreq, any);
    }

    // ---- Adreno KGSL ----

    private void readGpu() {
        if (gpu == Source.UNAVAILABLE) return;
        Path kgsl = sys.resolve("class/kgsl/kgsl-3d0");
        Long busy = leadingNumber(text(kgsl.resolve("gpu_busy_percentage")));
        Long clock = number(kgsl.resolve("gpuclk"));
        Long temperature = number(kgsl.resolve("temp"));
        boolean any = false;
        if (busy != null && busy >= 0 && busy <= 100) { gpuBusy.observe(busy); any = true; }
        if (clock != null && clock > 0) { gpuClock.observe(clock / 1_000_000.0); any = true; }
        Double celsius = celsius(temperature);
        if (celsius != null) { gpuTemperature.observe(celsius); any = true; }
        // Limits show whether the device profile or thermal policy holds the GPU clock down.
        Long cap = number(kgsl.resolve("max_gpuclk"));
        Long floor = number(kgsl.resolve("devfreq/min_freq"));
        if (cap != null && cap > 0) gpuCap.observe(cap / 1_000_000.0);
        if (floor != null && floor > 0) gpuFloor.observe(floor / 1_000_000.0);
        if (gpuGovernor == null) {
            String governor = text(kgsl.resolve("devfreq/governor"));
            if (governor != null && governor.strip().matches("[A-Za-z0-9_.-]{1,32}")) gpuGovernor = governor.strip();
        }
        if (gpuSteps == null) {
            String steps = text(kgsl.resolve("gpu_available_frequencies"));
            if (steps != null) {
                StringBuilder megahertz = new StringBuilder();
                for (String step : steps.strip().split("\\s+")) {
                    if (!step.matches("[0-9]{6,10}") || megahertz.length() > 120) continue;
                    if (megahertz.length() > 0) megahertz.append(',');
                    megahertz.append(Long.parseLong(step) / 1_000_000);
                }
                if (megahertz.length() > 0) gpuSteps = megahertz.toString();
            }
        }
        gpu = settle(gpu, any);
    }

    // ---- Thermal zones ----

    private void readZones() {
        if (zones == Source.UNAVAILABLE) return;
        if (zones == Source.UNKNOWN) {
            Map<String, Integer> repeats = new HashMap<>();
            for (Path directory : children(sys.resolve("class/thermal"), "thermal_zone", MAX_ZONES)) {
                String type = label(text(directory.resolve("type")));
                if (type == null) continue;
                int count = repeats.merge(type, 1, Integer::sum);
                thermalZones.add(new Zone(count == 1 ? type : type + "-" + count, directory.resolve("temp")));
            }
        }
        boolean any = false;
        List<Zone> unreadable = new ArrayList<>();
        for (Zone zone : thermalZones) {
            Double value = celsius(number(zone.temperature));
            if (value != null) { zone.celsius.observe(value); any = true; }
            else if (zone.celsius.count == 0) unreadable.add(zone);
        }
        // Drop zones that have never produced a reading so denied files are not retried.
        thermalZones.removeAll(unreadable);
        zones = settle(zones, any);
    }

    // ---- Per-role process CPU ----

    private void readProcesses(long intervalMs, boolean baseline) {
        if (processes == Source.UNAVAILABLE) return;
        Map<Integer, Seen> current = new HashMap<>();
        Map<String, Long> delta = new HashMap<>();
        Map<String, Integer> count = new HashMap<>();
        Map<String, Memory> memory = new HashMap<>();
        Memory stack = new Memory();
        // Per-process KGSL accounting exists only where the driver exposes its proc directory.
        if (kgslProcesses == Source.UNKNOWN)
            kgslProcesses = Files.isDirectory(sys.resolve("class/kgsl/kgsl/proc")) ? Source.AVAILABLE : Source.UNAVAILABLE;
        for (Path directory : children(proc, "", MAX_PROCESSES)) {
            String name = directory.getFileName().toString();
            if (!name.matches("[0-9]{1,9}")) continue;
            int pid = Integer.parseInt(name);
            long[] stat = parseStat(text(directory.resolve("stat")));
            if (stat == null) continue;
            Seen previous = seen.get(pid);
            boolean same = previous != null && previous.start == stat[1];
            String role = same ? previous.role : role(argumentZero(directory.resolve("cmdline")), pid == selfPid);
            long used = same ? stat[0] - previous.ticks : (baseline ? 0 : stat[0]);
            current.put(pid, new Seen(stat[1], stat[0], role));
            delta.merge(role, Math.max(0, used), Long::sum);
            count.merge(role, 1, Integer::sum);
            long[] reading = processMemory(directory, pid);
            memory.computeIfAbsent(role, ignored -> new Memory()).add(reading);
            stack.add(reading);
        }
        seen = current;
        processes = settle(processes, !current.isEmpty());
        if (stack.resident >= 0) stackResident.observe(stack.resident);
        if (stack.swap >= 0) stackSwap.observe(stack.swap);
        if (stack.gpu >= 0) stackGpu.observe(stack.gpu);

        visibleProcessesMax = Math.max(visibleProcessesMax, current.size());
        for (Map.Entry<String, Integer> entry : count.entrySet()) {
            Role role = roles.get(entry.getKey());
            if (role == null) {
                if (roles.size() >= MAX_ROLES) continue;
                role = new Role(); roles.put(entry.getKey(), role);
            }
            long used = delta.getOrDefault(entry.getKey(), 0L);
            Memory held = memory.get(entry.getKey());
            if (held != null) {
                if (held.resident >= 0) { role.residentMaxKib = Math.max(role.residentMaxKib, held.resident); role.residentLastKib = held.resident; }
                if (held.swap >= 0) role.swapMaxKib = Math.max(role.swapMaxKib, held.swap);
                if (held.gpu >= 0) { role.gpuMaxKib = Math.max(role.gpuMaxKib, held.gpu); role.gpuLastKib = held.gpu; }
            }
            role.ticks += used;
            role.maxProcesses = Math.max(role.maxProcesses, entry.getValue());
            if (!baseline && intervalMs > 0)
                role.peakCorePercent = Math.max(role.peakCorePercent, used * 100_000.0 / ticksPerSecond / intervalMs);
        }
    }

    /** RssAnon+RssShmem and VmSwap from /proc/PID/status, and KGSL GPU memory of that process, in KiB. */
    private long[] processMemory(Path directory, int pid) {
        long[] reading = {-1, -1, -1};
        String status = text(directory.resolve("status"));
        if (status != null) {
            Long anonymous = statusKib(status, "RssAnon:"), shared = statusKib(status, "RssShmem:"), swapped = statusKib(status, "VmSwap:");
            if (anonymous != null) reading[0] = anonymous + (shared == null ? 0 : shared);
            if (swapped != null) reading[1] = swapped;
        }
        if (kgslProcesses != Source.UNAVAILABLE) {
            Path kgsl = sys.resolve("class/kgsl/kgsl/proc").resolve(Integer.toString(pid));
            Long mapped = number(kgsl.resolve("gpumem_mapped")), unmapped = number(kgsl.resolve("gpumem_unmapped"));
            if (mapped != null || unmapped != null)
                reading[2] = ((mapped == null ? 0 : mapped) + (unmapped == null ? 0 : unmapped)) / 1024;
        }
        return reading;
    }

    static Long statusKib(String status, String field) {
        int at = status.startsWith(field) ? 0 : status.indexOf("\n" + field);
        if (at < 0) return null;
        if (at > 0) at++;
        return leadingNumber(status.substring(at + field.length()).replaceFirst("^[ \t]+", ""), 12);
    }

    // ---- System memory ----

    private void readMemory() {
        if (meminfo != Source.UNAVAILABLE) {
            String info = text(proc.resolve("meminfo"));
            Long total = info == null ? null : statusKib(info, "MemTotal:"), available = info == null ? null : statusKib(info, "MemAvailable:");
            if (available != null) {
                memoryAvailable.observe(available);
                if (total != null) memoryTotalKib = total;
                Long swapTotal = statusKib(info, "SwapTotal:"), free = statusKib(info, "SwapFree:");
                if (swapTotal != null) swapTotalKib = swapTotal;
                if (free != null && swapTotal != null && swapTotal > 0) swapFree.observe(free);
            }
            meminfo = settle(meminfo, available != null);
        }
        if (pressure != Source.UNAVAILABLE) {
            String lines = text(proc.resolve("pressure/memory"));
            Double some = average10(lines, "some"), full = average10(lines, "full");
            if (some != null) pressureSome.observe(some);
            if (full != null) pressureFull.observe(full);
            pressure = settle(pressure, some != null || full != null);
        }
        if (gpu != Source.UNAVAILABLE) {
            Long pages = number(sys.resolve("class/kgsl/kgsl/page_alloc"));
            if (pages != null && pages >= 0) gpuPages.observe(pages / 1024.0);
        }
    }

    /** "some avg10=1.23 avg60=..." from a PSI file. */
    static Double average10(String lines, String kind) {
        if (lines == null) return null;
        for (String line : lines.split("\n")) {
            if (!line.startsWith(kind + " ")) continue;
            int at = line.indexOf("avg10=");
            if (at < 0) return null;
            String value = line.substring(at + 6).split("\\s")[0];
            try { double parsed = Double.parseDouble(value); return parsed >= 0 && parsed <= 100 ? parsed : null; }
            catch (NumberFormatException malformed) { return null; }
        }
        return null;
    }

    /** Fixed role for a process from its first argument. Unknown programs are "other". */
    static String role(String argumentZero, boolean self) {
        if (self) return "app";
        if (argumentZero == null || argumentZero.isEmpty()) return "other";
        int slash = Math.max(argumentZero.lastIndexOf('/'), argumentZero.lastIndexOf('\\'));
        String name = argumentZero.substring(slash + 1).toLowerCase(Locale.ROOT);
        if (name.startsWith("libproot")) return "proot-tracer";
        if (name.equals("xtigervnc") || name.equals("xvnc")) return "xserver";
        if (name.equals("esteria-x11-frame")) return "frame-helper";
        if (name.equals("esteria-x11-input")) return "input-helper";
        if (name.equals("wineserver")) return "wineserver";
        if (name.endsWith(".exe")) return WINE_SERVICES.contains(name) ? "wine-services" : "wine-client";
        if (name.startsWith("wine")) return "wine-client";
        if (name.equals("worldserver")) return "worldserver";
        if (name.equals("authserver")) return "authserver";
        if (name.equals("mysqld")) return "mysqld";
        if (name.equals("mysql") || name.startsWith("python")) return "server-helper";
        if (name.equals("sh") || name.equals("bash") || name.equals("dash") || name.equals("env")) return "shell";
        return "other";
    }

    /** Returns {utime+stime, starttime} or null. The command field may contain spaces and parentheses. */
    static long[] parseStat(String stat) {
        if (stat == null) return null;
        int close = stat.lastIndexOf(')');
        if (close < 0 || close + 2 > stat.length()) return null;
        String[] fields = stat.substring(close + 2).trim().split(" +");
        // fields[0] is field 3 (state); utime/stime are fields 14/15; starttime is field 22.
        if (fields.length < 20) return null;
        try {
            long user = Long.parseLong(fields[11]), system = Long.parseLong(fields[12]), start = Long.parseLong(fields[19]);
            return user < 0 || system < 0 || start < 0 ? null : new long[]{user + system, start};
        } catch (NumberFormatException malformed) {
            return null;
        }
    }

    // ---- Output ----

    /** Compact facts for one support field. Every key is fixed or a sanitized hardware label. */
    public Map<String, String> facts() {
        Map<String, String> facts = new LinkedHashMap<>();
        if (samples == 0) return facts;
        facts.put("samples", Long.toString(samples));
        facts.put("elapsedMs", Long.toString(lastMs - firstMs));
        summary(facts, "thermalHeadroom", headroom, 2, true);
        if (refresh.count > 0) {
            facts.put("display.refreshHz.min", decimal(refresh.min, 1));
            facts.put("display.refreshHz.max", decimal(refresh.max, 1));
        } else facts.put("display.refreshHz", "unavailable");
        if (cpufreq == Source.AVAILABLE) {
            for (Policy policy : policies) {
                String prefix = "cpu." + policy.label;
                if (policy.current.count > 0) {
                    facts.put(prefix + ".curAvgMHz", decimal(policy.current.average(), 0));
                    facts.put(prefix + ".curMaxMHz", decimal(policy.current.max, 0));
                }
                if (policy.cap.count > 0) facts.put(prefix + ".capMinMHz", decimal(policy.cap.min, 0));
                if (policy.hardwareMaxKhz != null) facts.put(prefix + ".hwMaxMHz", decimal(policy.hardwareMaxKhz / 1000.0, 0));
            }
        } else facts.put("cpu.status", "unavailable");
        if (gpu == Source.AVAILABLE) {
            if (gpuBusy.count > 0) {
                facts.put("gpu.busyAvgPct", decimal(gpuBusy.average(), 0));
                facts.put("gpu.busyMaxPct", decimal(gpuBusy.max, 0));
            }
            if (gpuClock.count > 0) {
                facts.put("gpu.clockAvgMHz", decimal(gpuClock.average(), 0));
                facts.put("gpu.clockMaxMHz", decimal(gpuClock.max, 0));
            }
            if (gpuTemperature.count > 0) facts.put("gpu.tempMaxC", decimal(gpuTemperature.max, 1));
            if (gpuCap.count > 0) { facts.put("gpu.capMinMHz", decimal(gpuCap.min, 0)); facts.put("gpu.capMaxMHz", decimal(gpuCap.max, 0)); }
            if (gpuFloor.count > 0) facts.put("gpu.floorMaxMHz", decimal(gpuFloor.max, 0));
            if (gpuGovernor != null) facts.put("gpu.governor", gpuGovernor);
            if (gpuSteps != null) facts.put("gpu.stepsMHz", gpuSteps);
        } else facts.put("gpu.status", "unavailable");
        if (zones == Source.AVAILABLE) {
            List<Zone> hottest = new ArrayList<>(thermalZones);
            hottest.removeIf(zone -> zone.celsius.count == 0);
            hottest.sort(Comparator.comparingDouble((Zone zone) -> zone.celsius.max).reversed().thenComparing(zone -> zone.label));
            facts.put("zones.readable", Integer.toString(hottest.size()));
            for (Zone zone : hottest.subList(0, Math.min(REPORTED_ZONES, hottest.size())))
                facts.put("zone." + zone.label + ".maxC", decimal(zone.celsius.max, 1));
        } else facts.put("zones.status", "unavailable");
        if (meminfo == Source.AVAILABLE) {
            if (memoryTotalKib > 0) facts.put("memory.totalMiB", Long.toString(memoryTotalKib / 1024));
            facts.put("memory.availableMinMiB", decimal(memoryAvailable.min / 1024, 0));
            facts.put("memory.availableLastMiB", decimal(memoryAvailable.last / 1024, 0));
            if (swapTotalKib > 0) facts.put("memory.swapTotalMiB", Long.toString(swapTotalKib / 1024));
            if (swapFree.count > 0) { facts.put("memory.swapFreeMinMiB", decimal(swapFree.min / 1024, 0)); facts.put("memory.swapFreeLastMiB", decimal(swapFree.last / 1024, 0)); }
        } else facts.put("memory.status", "unavailable");
        if (pressure == Source.AVAILABLE) {
            if (pressureSome.count > 0) facts.put("memory.pressureSomeAvg10Max", decimal(pressureSome.max, 2));
            if (pressureFull.count > 0) facts.put("memory.pressureFullAvg10Max", decimal(pressureFull.max, 2));
        } else facts.put("memory.pressure", "unavailable");
        if (gpuPages.count > 0) facts.put("gpu.pagesMaxMiB", decimal(gpuPages.max / 1024, 0));
        if (stackResident.count > 0) {
            facts.put("stack.residentMaxMiB", decimal(stackResident.max / 1024, 0));
            facts.put("stack.residentLastMiB", decimal(stackResident.last / 1024, 0));
        }
        if (stackSwap.count > 0) facts.put("stack.swapMaxMiB", decimal(stackSwap.max / 1024, 0));
        if (stackGpu.count > 0) {
            facts.put("stack.gpuMaxMiB", decimal(stackGpu.max / 1024, 0));
            facts.put("stack.gpuLastMiB", decimal(stackGpu.last / 1024, 0));
        }
        if (processes == Source.AVAILABLE) {
            double seconds = Math.max(1, lastMs - firstMs) / 1000.0;
            facts.put("process.visibleMax", Integer.toString(visibleProcessesMax));
            List<Map.Entry<String, Role>> ordered = new ArrayList<>(roles.entrySet());
            ordered.sort(Comparator.comparingLong((Map.Entry<String, Role> entry) -> entry.getValue().ticks).reversed()
                .thenComparing(Map.Entry::getKey));
            for (Map.Entry<String, Role> entry : ordered) {
                Role role = entry.getValue();
                String prefix = "role." + entry.getKey();
                double cpuSeconds = (double) role.ticks / ticksPerSecond;
                facts.put(prefix + ".cpuSeconds", decimal(cpuSeconds, 1));
                facts.put(prefix + ".avgCorePct", decimal(cpuSeconds * 100 / seconds, 1));
                facts.put(prefix + ".peakCorePct", decimal(role.peakCorePercent, 1));
                facts.put(prefix + ".maxProcesses", Integer.toString(role.maxProcesses));
                if (role.residentMaxKib >= 0) {
                    facts.put(prefix + ".residentMaxMiB", Long.toString(role.residentMaxKib / 1024));
                    facts.put(prefix + ".residentLastMiB", Long.toString(role.residentLastKib / 1024));
                }
                if (role.swapMaxKib > 0) facts.put(prefix + ".swapMaxMiB", Long.toString(role.swapMaxKib / 1024));
                if (role.gpuMaxKib > 0) {
                    facts.put(prefix + ".gpuMaxMiB", Long.toString(role.gpuMaxKib / 1024));
                    facts.put(prefix + ".gpuLastMiB", Long.toString(role.gpuLastKib / 1024));
                }
            }
        } else facts.put("process.status", "unavailable");
        return facts;
    }

    private static void summary(Map<String, String> facts, String prefix, Stat stat, int places, boolean withStart) {
        if (stat.count == 0) { facts.put(prefix, "unavailable"); return; }
        if (withStart) facts.put(prefix + ".start", decimal(stat.first, places));
        facts.put(prefix + ".last", decimal(stat.last, places));
        facts.put(prefix + ".max", decimal(stat.max, places));
        facts.put(prefix + ".samples", Long.toString(stat.count));
    }

    // ---- Bounded file helpers ----

    private static Source settle(Source state, boolean any) {
        if (any) return Source.AVAILABLE;
        return state == Source.UNKNOWN ? Source.UNAVAILABLE : state;
    }

    private static List<Path> children(Path directory, String prefix, int limit) {
        List<Path> result = new ArrayList<>();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(directory)) {
            for (Path entry : entries) {
                if (!entry.getFileName().toString().startsWith(prefix)) continue;
                result.add(entry);
                if (result.size() >= limit) break;
            }
        } catch (IOException | RuntimeException unavailable) {
            return List.of();
        }
        result.sort(Comparator.comparing(path -> path.getFileName().toString()));
        return result;
    }

    static String text(Path file) {
        try (InputStream in = Files.newInputStream(file, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = in.readNBytes(SMALL_FILE);
            return new String(bytes, StandardCharsets.US_ASCII);
        } catch (IOException | RuntimeException unavailable) {
            return null;
        }
    }

    private static String argumentZero(Path cmdline) {
        String value = text(cmdline);
        if (value == null) return null;
        int end = value.indexOf('\0');
        return end < 0 ? value.trim() : value.substring(0, end);
    }

    private static Long number(Path file) {
        String value = text(file);
        if (value == null) return null;
        try { return Long.parseLong(value.trim()); }
        catch (NumberFormatException malformed) { return null; }
    }

    static Long leadingNumber(String value) { return leadingNumber(value, 9); }

    static Long leadingNumber(String value, int maxDigits) {
        if (value == null) return null;
        String trimmed = value.trim();
        int end = 0;
        while (end < trimmed.length() && Character.isDigit(trimmed.charAt(end))) end++;
        if (end == 0 || end > maxDigits) return null;
        return Long.parseLong(trimmed.substring(0, end));
    }

    /** Sysfs reports millidegrees on Qualcomm devices; small values are already degrees. */
    static Double celsius(Long raw) {
        if (raw == null) return null;
        double value = Math.abs(raw) >= 1000 ? raw / 1000.0 : raw;
        return value > 0 && value < 200 ? value : null;
    }

    /** Hardware sensor labels only: letters, digits, dot, dash and underscore, at most 32 characters. */
    static String label(String raw) {
        if (raw == null) return null;
        String value = raw.trim();
        if (value.isEmpty() || value.length() > 32 || !value.matches("[A-Za-z0-9._-]+")) return null;
        return value;
    }

    static String decimal(double value, int places) {
        if (!Double.isFinite(value)) return "unavailable";
        return String.format(Locale.ROOT, "%." + places + "f", value);
    }
}
