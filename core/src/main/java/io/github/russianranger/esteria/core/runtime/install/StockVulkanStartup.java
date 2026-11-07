package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Validate the two startup CVars which can lower the selected Vulkan shader targets. */
final class StockVulkanStartup {
    private static final Pattern SET_FIELD = Pattern.compile("\"([^\"]*)(?:\"|$)|([^ ,;\t\"]+)");
    // ConsoleGxOverride tokenizes the numeric key on space/comma and the value on space/semicolon.
    private static final Pattern OVERRIDE_KEY = Pattern.compile("([^ ,]+)[ ,]?");
    private static final Pattern OVERRIDE_VALUE = Pattern.compile("[^ ;]+[ ;]?");
    private static final Pattern NONZERO_KEY = Pattern.compile("[-+]?0*[1-9][0-9]*");

    private StockVulkanStartup() { }

    static void requireCompatible(Path launch, Path wtf, RuntimeWork.Cancellation cancellation) throws IOException {
        Map<String,Path> settings = settingsFiles(wtf);
        Map<String,Path> root = settingsFiles(launch);
        // CVar::Load opens a bare filename before trying WTF/. Only RunOnce files enumerated
        // in WTF are loaded, but a file at the executable root can shadow any of them.
        if (root.containsKey(ClientLaunchView.LOCALE_INPUT))
            throw new IOException("A file beside the client shadows the managed startup settings");
        Path fallback = settings.remove("Config.wtf");
        Path config = root.getOrDefault("Config.wtf", fallback);
        Map<String,String> values = new TreeMap<>(String.CASE_INSENSITIVE_ORDER);
        if (config != null) readSettings(config, values);
        for (Map.Entry<String,Path> entry : settings.entrySet()) {
            RuntimeWork.check(cancellation);
            readSettings(root.getOrDefault(entry.getKey(), entry.getValue()), values);
        }
        String fixed = values.getOrDefault("fixedFunction", "");
        RuntimeFiles.require(fixed.isEmpty() || fixed.matches("-?0+"),
                "Stock Vulkan shaders require fixedFunction 0 in the active client startup settings");
        String overrides = values.getOrDefault("gxOverride", "");
        Matcher key = OVERRIDE_KEY.matcher(overrides);
        Matcher value = OVERRIDE_VALUE.matcher(overrides);
        int offset = 0;
        while (key.find(offset) && value.find(key.end())) {
            // The native parser uses atol(key), including zero for a malformed key.
            RuntimeFiles.require(key.group(1).length() <= 255 && NONZERO_KEY.matcher(key.group(1)).matches(),
                    "Stock Vulkan shaders require the default pixel shader target. Check gxOverride in Config.wtf and RunOnce settings");
            offset = value.end();
        }
    }

    private static Map<String,Path> settingsFiles(Path directory) throws IOException {
        Map<String,Path> found = new TreeMap<>((left,right) -> asciiUpper(left).compareTo(asciiUpper(right)));
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(directory)) {
            int count = 0;
            for (Path file : entries) {
                RuntimeFiles.require(++count <= 8192, "Client startup settings inventory exceeds its bound");
                String name = file.getFileName().toString();
                String lower = asciiLower(name);
                if (!lower.equals("config.wtf") && !(lower.startsWith("runonce") && lower.endsWith(".wtf"))) continue;
                RuntimeFiles.require(found.put(name, file) == null, "Case-colliding client startup settings");
            }
        }
        return found;
    }

    private static void readSettings(Path path, Map<String,String> values) throws IOException {
        RuntimeFiles.plain(path);
        long bytes = Files.size(path);
        RuntimeFiles.require(bytes <= 1 << 20, "Client startup settings exceed the 1 MiB read bound");
        String text = RuntimeFiles.smallText(path, (int)bytes);
        if (text.startsWith("\uFEFF")) text = text.substring(1);
        int nul = text.indexOf('\0');
        if (nul >= 0) text = text.substring(0, nul);
        for (String line : text.split("[\r\n]+")) {
            if (line.length() < 4 || !asciiLower(line.substring(0, 4)).equals("set ")) continue;
            Matcher fields = SET_FIELD.matcher(line.substring(4));
            if (!fields.find()) continue;
            String name = asciiLower(field(fields));
            if (!name.equals("fixedfunction") && !name.equals("gxoverride")) continue;
            // The client truncates console arguments to 1023 bytes. Never infer compatibility
            // from a suffix it might have discarded.
            RuntimeFiles.require(line.getBytes(java.nio.charset.StandardCharsets.UTF_8).length <= 1023,
                    "Cannot select stock shader settings from an overlong " + name + " command");
            values.put(name, fields.find() ? field(fields) : "");
        }
    }

    private static String asciiLower(String text) {
        return text.chars().allMatch(c -> c < 128) ? text.toLowerCase(java.util.Locale.ROOT) : text;
    }

    private static String asciiUpper(String text) {
        return text.chars().allMatch(c -> c < 128) ? text.toUpperCase(java.util.Locale.ROOT) : text;
    }

    private static String field(Matcher match) {
        return match.group(1) == null ? match.group(2) : match.group(1);
    }
}
