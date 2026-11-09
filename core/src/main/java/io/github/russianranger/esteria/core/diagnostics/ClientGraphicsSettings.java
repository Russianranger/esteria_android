package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Reads the render-cost settings the client saved to WTF/Config.wtf.
 * Only allowlisted graphics CVars with short, plain values are returned, so the result
 * never carries realm, account, path or chat settings. A missing or unreadable file
 * returns an empty map. */
public final class ClientGraphicsSettings {
    public static final int MAX_BYTES = 64 * 1024;
    /** Lower-case names of 3.3.5a CVars that change GPU or presentation load. */
    public static final Set<String> NAMES = Set.of("gxresolution", "gxrefresh", "gxwindow", "gxmaximize",
        "gxmultisample", "gxmultisamplequality", "gxvsync", "gxtriplebuffer", "maxfps", "maxfpsbk", "farclip",
        "horizonfarclip", "shadowlevel", "extshadowquality", "waterlod", "watermaxlod", "ffxglow", "ffxdeath",
        "ffxspecial", "ffxnetherworld", "environmentdetail", "groundeffectdensity", "groundeffectdist",
        "particledensity", "spelleffectlevel", "weatherdensity", "texturefilteringmode", "projectedtextures",
        "terrainmiplevel", "basemip", "componenttexturelevel", "skycloudlod", "timingmethod");
    private static final Pattern SET = Pattern.compile("^\\s*SET\\s+([A-Za-z0-9_]{1,48})\\s+\"([^\"\\r\\n]{0,48})\"\\s*$",
        Pattern.CASE_INSENSITIVE);
    private static final Pattern PLAIN = Pattern.compile("[A-Za-z0-9 .x-]{1,24}");

    private ClientGraphicsSettings() { }

    public static Map<String, String> read(Path config) {
        Map<String, String> settings = new TreeMap<>();
        if (config == null) return settings;
        String text;
        try (InputStream in = Files.newInputStream(config, LinkOption.NOFOLLOW_LINKS)) {
            text = new String(in.readNBytes(MAX_BYTES), StandardCharsets.UTF_8);
        } catch (IOException | RuntimeException unavailable) {
            return settings;
        }
        for (String line : text.split("\r?\n")) {
            Matcher set = SET.matcher(line);
            if (!set.matches()) continue;
            String name = set.group(1).toLowerCase(Locale.ROOT), value = set.group(2);
            if (NAMES.contains(name) && PLAIN.matcher(value).matches()) settings.put(name, value);
        }
        return settings;
    }
}
