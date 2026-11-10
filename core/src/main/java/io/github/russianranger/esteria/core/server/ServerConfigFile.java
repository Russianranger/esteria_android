package io.github.russianranger.esteria.core.server;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** One rendered AzerothCore configuration file as settings an owner can browse: section, documented help,
 * kind and listed choices. Values are the file's own; nothing here writes the file. */
public final class ServerConfigFile {
    public static final int MAX_BYTES = 4 << 20, MAX_HELP = 2400, MAX_SETTINGS = 4096;
    public enum Kind { SWITCH, CHOICE, INTEGER, DECIMAL, TEXT }

    public static final class Choice {
        public final String value, label;
        Choice(String value, String label) { this.value = value; this.label = label; }
        @Override public String toString() { return value + " - " + label; }
    }

    public static final class Setting {
        public final String file, key, value, section, help;
        public final boolean quoted;
        public final Kind kind;
        public final List<Choice> choices;
        Setting(String file, String key, String value, boolean quoted, String section, String help, Kind kind, List<Choice> choices) {
            this.file = file; this.key = key; this.value = value; this.quoted = quoted; this.section = section; this.help = help;
            this.kind = kind; this.choices = Collections.unmodifiableList(choices);
        }
        /** What a switch writes: true/false where the file uses words, otherwise 1/0. */
        public String switchValue(boolean on) {
            boolean words = value.equalsIgnoreCase("true") || value.equalsIgnoreCase("false");
            return words ? (on ? "true" : "false") : (on ? "1" : "0");
        }
        public static boolean switchedOn(String candidate) {
            return candidate.equals("1") || candidate.equalsIgnoreCase("true");
        }
        /** The label of the listed choice with this value, or null. */
        public String choiceLabel(String candidate) {
            for (Choice choice : choices) if (choice.value.equals(candidate)) return choice.label;
            return null;
        }
    }

    private static final Pattern RULE = Pattern.compile("^#{10,}\\s*$");
    private static final Pattern TITLE = Pattern.compile("^#\\s+([A-Z0-9][A-Z0-9 &/(),.'+_-]{1,60}?)\\s*$");
    private static final Pattern SETTING = Pattern.compile("^\\s*([A-Za-z0-9_][A-Za-z0-9_.-]{0,127})\\s*=\\s*(.*?)\\s*$");
    private static final Pattern NAME_LINE = Pattern.compile("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$");
    private static final Pattern CHOICE = Pattern.compile("^(?:[A-Za-z]+:)?\\s*(-?[0-9]+(?:\\.[0-9]+)?)\\s+-\\s+\\((.{1,90})\\)\\s*$");
    private static final Pattern INTEGER = Pattern.compile("-?[0-9]{1,18}");
    private static final Pattern DECIMAL = Pattern.compile("-?(?:[0-9]{1,12}\\.[0-9]{0,8}|\\.[0-9]{1,8})");

    public final String name;
    public final List<Setting> settings;
    public final List<String> sections;

    private ServerConfigFile(String name, List<Setting> settings, List<String> sections) {
        this.name = name; this.settings = Collections.unmodifiableList(settings); this.sections = Collections.unmodifiableList(sections);
    }

    public static ServerConfigFile read(Path path, String name) throws IOException {
        if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Server configuration file is unavailable");
        try (InputStream in = Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS)) {
            byte[] bytes = in.readNBytes(MAX_BYTES + 1);
            if (bytes.length > MAX_BYTES) throw new IOException("Server configuration file exceeds its bound");
            return parse(name, new String(bytes, StandardCharsets.UTF_8));
        }
    }

    public static ServerConfigFile parse(String name, String text) {
        Map<String, Setting> byKey = new LinkedHashMap<>();
        Set<String> sections = new LinkedHashSet<>();
        String fallback = fallbackSection(name), section = fallback;
        List<String> block = new ArrayList<>();
        boolean afterSetting = false, afterRule = false;
        for (String raw : text.split("\n", -1)) {
            String line = raw.endsWith("\r") ? raw.substring(0, raw.length() - 1) : raw;
            if (RULE.matcher(line).matches()) { afterRule = true; block.clear(); afterSetting = false; continue; }
            if (afterRule) {
                afterRule = false;
                Matcher title = TITLE.matcher(line);
                if (title.matches()) {
                    String heading = title.group(1).trim();
                    if (!heading.equals("SECTION INDEX") && !heading.equals("EXAMPLE CONFIG")) section = titleCase(heading);
                    continue;
                }
            }
            if (line.startsWith("#")) {
                if (afterSetting) { block.clear(); afterSetting = false; }
                if (block.size() < 200) block.add(line.substring(1));
                continue;
            }
            Matcher setting = SETTING.matcher(line);
            if (!setting.matches() || line.trim().startsWith("[")) continue;
            String key = setting.group(1), rawValue = setting.group(2);
            boolean quoted = rawValue.length() >= 2 && rawValue.startsWith("\"") && rawValue.endsWith("\"");
            String value = quoted ? rawValue.substring(1, rawValue.length() - 1) : rawValue;
            String help = help(block);
            List<Choice> choices = choices(block);
            byKey.remove(key);
            if (byKey.size() < MAX_SETTINGS) {
                byKey.put(key, new Setting(name, key, value, quoted, section, help, kind(key, value, quoted, help, choices), choices));
                sections.add(section);
            }
            afterSetting = true;
        }
        if (sections.isEmpty()) sections.add(fallback);
        return new ServerConfigFile(name, new ArrayList<>(byKey.values()), new ArrayList<>(sections));
    }

    /** "modules/playerbots.conf" -> "Playerbots"; "worldserver.conf" -> "World server". */
    public static String fallbackSection(String name) {
        String base = name.substring(name.lastIndexOf('/') + 1);
        if (base.endsWith(".conf")) base = base.substring(0, base.length() - 5);
        if (base.equals("worldserver")) return "World server";
        base = base.replace('_', ' ').replace('-', ' ').trim();
        if (base.startsWith("mod ")) base = base.substring(4);
        return base.isEmpty() ? "General" : Character.toUpperCase(base.charAt(0)) + base.substring(1);
    }

    static String titleCase(String heading) {
        String lower = heading.toLowerCase(Locale.ROOT);
        lower = Character.toUpperCase(lower.charAt(0)) + lower.substring(1);
        return lower.replace("Ffapvp", "FFA PvP").replace("Outdoorpvp", "Outdoor PvP").replace("pvp", "PvP")
            .replace("(cais)", "(CAIS)").replace(" ah ", " AH ").replace("Lfg", "LFG");
    }

    private static String help(List<String> block) {
        List<String> lines = new ArrayList<>();
        for (String line : block) {
            String trimmed = line.trim();
            if (NAME_LINE.matcher(trimmed).matches() && !trimmed.endsWith(".") && trimmed.chars().anyMatch(Character::isUpperCase)) continue;
            lines.add(line);
        }
        while (!lines.isEmpty() && lines.get(0).trim().isEmpty()) lines.remove(0);
        while (!lines.isEmpty() && lines.get(lines.size() - 1).trim().isEmpty()) lines.remove(lines.size() - 1);
        int indent = Integer.MAX_VALUE;
        for (String line : lines) if (!line.trim().isEmpty()) indent = Math.min(indent, line.length() - line.stripLeading().length());
        StringBuilder out = new StringBuilder();
        for (String line : lines) {
            String shown = line.trim().isEmpty() ? "" : line.substring(Math.min(indent, line.length())).stripTrailing();
            if (out.length() + shown.length() + 1 > MAX_HELP) { out.append("…"); break; }
            if (out.length() > 0) out.append('\n');
            out.append(shown);
        }
        return out.toString();
    }

    private static List<Choice> choices(List<String> block) {
        Map<String, Choice> found = new LinkedHashMap<>();
        for (String line : block) {
            Matcher choice = CHOICE.matcher(line.trim());
            if (!choice.matches()) continue;
            String label = choice.group(2).trim();
            // "1 - (Rate.Drop.Item.Poor)" names a key's default in a shared block; it is not a choice.
            if (NAME_LINE.matcher(label).matches() && label.contains(".")) continue;
            found.putIfAbsent(choice.group(1), new Choice(choice.group(1), label));
            if (found.size() == 24) break;
        }
        return found.size() >= 2 ? new ArrayList<>(found.values()) : new ArrayList<>();
    }

    static Kind kind(String key, String value, boolean quoted, String help, List<Choice> choices) {
        if (quoted) return Kind.TEXT;
        boolean numeric = INTEGER.matcher(value).matches() || DECIMAL.matcher(value).matches();
        if (!choices.isEmpty() && numeric) {
            boolean binary = choices.size() == 2 && choices.stream().allMatch(choice -> choice.value.equals("0") || choice.value.equals("1"));
            return binary ? Kind.SWITCH : Kind.CHOICE;
        }
        if (INTEGER.matcher(value).matches()) {
            String lower = help.toLowerCase(Locale.ROOT);
            boolean documentedSwitch = (value.equals("0") || value.equals("1")) &&
                (lower.contains("(enabled)") || lower.contains("(disabled)") || lower.contains("(enable)") || lower.contains("(disable)") ||
                 lower.startsWith("enable") || lower.contains("enable/disable") || lower.contains("enable or disable") ||
                 lower.contains("description: enable") || lower.contains("1 = enabled") || lower.contains("0 = disabled"));
            if (documentedSwitch) return Kind.SWITCH;
            // Rates and multipliers are read as floats even where the file writes a whole number.
            boolean rate = key.startsWith("Rate.") || key.contains(".Rate") || key.contains("Multiplier") || key.contains("Modifier");
            return rate ? Kind.DECIMAL : Kind.INTEGER;
        }
        if (DECIMAL.matcher(value).matches()) return Kind.DECIMAL;
        if (value.equalsIgnoreCase("true") || value.equalsIgnoreCase("false")) return Kind.SWITCH;
        return Kind.TEXT;
    }
}
