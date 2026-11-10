package io.github.russianranger.esteria.core.server;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.NoSuchFileException;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/** The owner's chosen server settings, kept in app-private storage and applied at the next server start.
 * One line per setting: file, key and value separated by tabs; values never contain tabs or line breaks. */
public final class ServerConfigOverrides {
    public static final String HEADER = "Esteria world settings v1";
    public static final int MAX_BYTES = 256 << 10;
    private final Map<String, Map<String, String>> byFile = new LinkedHashMap<>();

    public static ServerConfigOverrides read(Path path) throws IOException {
        ServerConfigOverrides overrides = new ServerConfigOverrides();
        byte[] bytes;
        try (InputStream in = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            bytes = in.readNBytes(MAX_BYTES + 1);
        } catch (NoSuchFileException absent) {
            return overrides;
        }
        if (bytes.length > MAX_BYTES) throw new IOException("Saved server settings exceed their bound");
        String[] lines = new String(bytes, StandardCharsets.UTF_8).split("\n", -1);
        if (!HEADER.equals(lines[0])) throw new IOException("Unknown saved server settings");
        for (int i = 1; i < lines.length; i++) {
            if (lines[i].isEmpty()) continue;
            String[] fields = lines[i].split("\t", -1);
            if (fields.length != 3 || !ServerConfigRules.KEY.matcher(fields[1]).matches() || fields[0].isEmpty())
                throw new IOException("Malformed saved server setting");
            overrides.byFile.computeIfAbsent(fields[0], file -> new LinkedHashMap<>()).put(fields[1], fields[2]);
        }
        return overrides;
    }

    /** Atomic replacement in the same private directory. */
    public void write(Path path) throws IOException {
        StringBuilder text = new StringBuilder(HEADER).append('\n');
        for (Map.Entry<String, Map<String, String>> file : byFile.entrySet())
            for (Map.Entry<String, String> setting : file.getValue().entrySet())
                text.append(file.getKey()).append('\t').append(setting.getKey()).append('\t').append(setting.getValue()).append('\n');
        byte[] bytes = text.toString().getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_BYTES) throw new IOException("Server settings exceed their bound");
        Files.createDirectories(path.getParent());
        Path temporary = path.resolveSibling(path.getFileName() + ".tmp");
        Files.deleteIfExists(temporary);
        Files.write(temporary, bytes, StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE);
        try { Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
        catch (AtomicMoveNotSupportedException unsupported) { Files.move(temporary, path, StandardCopyOption.REPLACE_EXISTING); }
    }

    public String get(String file, String key) {
        Map<String, String> settings = byFile.get(file);
        return settings == null ? null : settings.get(key);
    }

    /** Records a value that differs from the file; a value equal to the file's removes the override. */
    public void set(ServerConfigFile.Setting setting, String value, ServerConfigRules rules) {
        String problem = rules.problem(setting, value);
        if (problem != null) throw new IllegalArgumentException(problem);
        if (!rules.fileAllowed(setting.file)) throw new IllegalArgumentException("This file cannot be changed");
        if (value.contains("\t") || value.contains("\n")) throw new IllegalArgumentException("Tabs and line breaks are not allowed");
        String launch = rules.launchDefault(setting.key);
        if (value.equals(launch != null ? launch : setting.value)) { remove(setting.file, setting.key); return; }
        Map<String, String> settings = byFile.computeIfAbsent(setting.file, file -> new LinkedHashMap<>());
        if (!settings.containsKey(setting.key) && count() >= rules.maxOverrides)
            throw new IllegalArgumentException("At most " + rules.maxOverrides + " settings can be changed");
        settings.put(setting.key, value);
    }

    public void remove(String file, String key) {
        Map<String, String> settings = byFile.get(file);
        if (settings == null) return;
        settings.remove(key);
        if (settings.isEmpty()) byFile.remove(file);
    }

    public void clear() { byFile.clear(); }

    public int count() {
        int total = 0;
        for (Map<String, String> settings : byFile.values()) total += settings.size();
        return total;
    }

    /** File -> key -> value, in the order they were chosen. */
    public Map<String, Map<String, String>> all() {
        Map<String, Map<String, String>> copy = new LinkedHashMap<>();
        byFile.forEach((file, settings) -> copy.put(file, Collections.unmodifiableMap(new LinkedHashMap<>(settings))));
        return Collections.unmodifiableMap(copy);
    }
}
