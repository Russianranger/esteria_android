package io.github.russianranger.esteria.core.server;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** The reviewed policy (config/world-config-policy.json) as plain rules. The guest helper enforces the same
 * document again before the worldserver starts; these rules only keep the app from offering what it would refuse. */
public final class ServerConfigRules {
    public static final Pattern KEY = Pattern.compile("[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}");
    private static final Pattern INTEGER = Pattern.compile("-?[0-9]{1,18}");
    private static final Pattern DECIMAL = Pattern.compile("-?(?:[0-9]{1,12}(?:\\.[0-9]{0,8})?|\\.[0-9]{1,8})");

    public final int maxOverrides, maxValueLength;
    private final Pattern files;
    private final Set<String> protectedKeys, heavyKeys;
    private final List<Pattern> protectedPatterns, heavyPatterns;
    private final Map<String, String> launchDefaults;

    public ServerConfigRules(int maxOverrides, int maxValueLength, Pattern files, Set<String> protectedKeys,
            List<Pattern> protectedPatterns, Set<String> heavyKeys, List<Pattern> heavyPatterns, Map<String, String> launchDefaults) {
        if (maxOverrides < 1 || maxOverrides > 1024 || maxValueLength < 1 || maxValueLength > 1024)
            throw new IllegalArgumentException("Invalid server settings bounds");
        this.maxOverrides = maxOverrides; this.maxValueLength = maxValueLength; this.files = files;
        this.protectedKeys = Set.copyOf(protectedKeys); this.protectedPatterns = List.copyOf(protectedPatterns);
        this.heavyKeys = Set.copyOf(heavyKeys); this.heavyPatterns = List.copyOf(heavyPatterns);
        this.launchDefaults = Collections.unmodifiableMap(Map.copyOf(launchDefaults));
    }

    public boolean fileAllowed(String name) { return name != null && files.matcher(name).matches(); }

    /** Reserved for Esteria: database, paths, network, logging and the stock profile's module switches. */
    public boolean managed(String key) {
        if (protectedKeys.contains(key)) return true;
        for (Pattern pattern : protectedPatterns) if (pattern.matcher(key).find()) return true;
        return false;
    }

    /** Settings that can raise CPU load, heat or startup time. */
    public boolean heavy(String key) {
        if (heavyKeys.contains(key)) return true;
        for (Pattern pattern : heavyPatterns) if (pattern.matcher(key).find()) return true;
        return false;
    }

    /** The value the session starts with when the owner chose nothing, if it differs from the file. */
    public String launchDefault(String key) { return launchDefaults.get(key); }

    /** Null when the value may be saved for this setting; otherwise a short reason for the owner. */
    public String problem(ServerConfigFile.Setting setting, String value) {
        if (managed(setting.key)) return "Esteria manages this setting";
        if (value == null || (value.isEmpty() && setting.kind != ServerConfigFile.Kind.TEXT)) return "Enter a value";
        if (value.length() > maxValueLength) return "Use at most " + maxValueLength + " characters";
        if (!value.equals(value.strip())) return "Remove spaces at the start or end";
        for (int i = 0; i < value.length(); i++) {
            char c = value.charAt(i);
            if (Character.isISOControl(c) || c == '"' || c == '\\' || Character.getType(c) == Character.LINE_SEPARATOR ||
                    Character.getType(c) == Character.PARAGRAPH_SEPARATOR || Character.getType(c) == Character.FORMAT ||
                    Character.isSurrogate(c) || Character.getType(c) == Character.UNASSIGNED || Character.getType(c) == Character.PRIVATE_USE ||
                    (Character.getType(c) == Character.SPACE_SEPARATOR && c != ' '))
                return "Quotes, backslashes and control characters are not allowed";
        }
        switch (setting.kind) {
            case SWITCH:
                if (!(value.equals("0") || value.equals("1") || value.equalsIgnoreCase("true") || value.equalsIgnoreCase("false")))
                    return "Choose on or off";
                return null;
            case INTEGER:
                return INTEGER.matcher(value).matches() ? null : "Enter a whole number";
            case DECIMAL:
                return DECIMAL.matcher(value).matches() ? null : "Enter a number";
            case CHOICE:
                return INTEGER.matcher(value).matches() || DECIMAL.matcher(value).matches() ? null : "Enter a number";
            default:
                return null;
        }
    }

    /** IniKeyToEnvVarKey in the pinned server's Config.cpp, with its AC_ prefix. */
    public static String environmentName(String key) {
        StringBuilder out = new StringBuilder("AC_");
        for (int i = 0; i < key.length(); i++) {
            char current = key.charAt(i);
            if (current == ' ' || current == '.' || current == '-') { out.append('_'); continue; }
            if (i != key.length() - 1) {
                char next = key.charAt(i + 1);
                boolean upper = Character.isUpperCase(current), nextUpper = Character.isUpperCase(next);
                boolean digit = Character.isDigit(current), nextDigit = Character.isDigit(next);
                if ((!upper && nextUpper) || (!digit && nextDigit) || (digit && !nextDigit)) {
                    out.append(Character.toUpperCase(current)).append('_');
                    continue;
                }
            }
            out.append(Character.toUpperCase(current));
        }
        return out.toString();
    }
}
