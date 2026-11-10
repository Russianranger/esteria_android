package io.github.russianranger.esteria.runtime;

import android.content.Context;
import io.github.russianranger.esteria.core.server.ServerConfigFile;
import io.github.russianranger.esteria.core.server.ServerConfigOverrides;
import io.github.russianranger.esteria.core.server.ServerConfigRules;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/** The owner's server settings: where the active rendered configuration is, the reviewed policy, the saved
 * choices, and the document the next server session reads. The rendered files themselves are never changed. */
public final class ServerSettingsStore {
    private static final String PREFERENCES = "server-settings", WORK = "work";
    private static final Pattern GENERATION = Pattern.compile("generations/[0-9a-f]{64}");
    public static final String DOCUMENT = "world-overrides.json";
    private static volatile ServerConfigRules cachedRules;

    private ServerSettingsStore() { }

    /** Called when a verified server session begins, so settings can be browsed without starting one. */
    static void rememberWork(Context context, Path work) {
        context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE).edit().putString(WORK, work.toString()).apply();
    }

    public static Path saved(Context context) {
        return context.getFilesDir().toPath().resolve("state/server-settings/world-settings.tsv");
    }

    public static ServerConfigOverrides overrides(Context context) throws IOException {
        return ServerConfigOverrides.read(saved(context));
    }

    /** The active configuration generation, or null before the local world has started once. */
    public static Path activeGeneration(Context context) throws IOException {
        String remembered = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE).getString(WORK, null);
        if (remembered == null) return null;
        Path root = context.getFilesDir().getCanonicalFile().toPath(), work = Paths.get(remembered);
        if (!work.isAbsolute() || !work.normalize().equals(work) || !work.startsWith(root) || work.equals(root)) return null;
        Path current = work.resolve("state/config/current");
        if (!Files.isSymbolicLink(current)) return null;
        String target = Files.readSymbolicLink(current).toString();
        if (!GENERATION.matcher(target).matches()) return null;
        Path generation = work.resolve("state/config").resolve(target);
        if (!Files.isDirectory(generation, LinkOption.NOFOLLOW_LINKS) || !generation.toRealPath().equals(generation)) return null;
        return generation;
    }

    /** worldserver.conf, then playerbots, then the other module files, by name. */
    public static List<String> files(Path generation, ServerConfigRules rules) throws IOException {
        List<String> names = new ArrayList<>();
        if (Files.isRegularFile(generation.resolve("worldserver.conf"), LinkOption.NOFOLLOW_LINKS)) names.add("worldserver.conf");
        Path modules = generation.resolve("modules");
        List<String> others = new ArrayList<>();
        if (Files.isDirectory(modules, LinkOption.NOFOLLOW_LINKS)) {
            try (DirectoryStream<Path> stream = Files.newDirectoryStream(modules, "*.conf")) {
                for (Path path : stream) {
                    String name = "modules/" + path.getFileName();
                    if (Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) && rules.fileAllowed(name) && others.size() < 128) others.add(name);
                }
            }
        }
        Collections.sort(others);
        if (others.remove("modules/playerbots.conf")) names.add("modules/playerbots.conf");
        names.addAll(others);
        return names;
    }

    public static ServerConfigFile read(Path generation, String name, ServerConfigRules rules) throws IOException {
        if (!rules.fileAllowed(name)) throw new IOException("Unknown server configuration file");
        return ServerConfigFile.read(generation.resolve(name), name);
    }

    /** The policy packaged with the session helpers, the same document the guest enforces. */
    public static ServerConfigRules rules(Context context) throws IOException {
        ServerConfigRules rules = cachedRules;
        if (rules != null) return rules;
        try (InputStream input = context.getAssets().open("server-session/world-config-policy.json")) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] block = new byte[8192];
            for (int count; (count = input.read(block)) != -1;) { out.write(block, 0, count); if (out.size() > 65536) throw new IOException("Policy too large"); }
            JSONObject policy = new JSONObject(new String(out.toByteArray(), StandardCharsets.UTF_8));
            if (policy.getInt("formatVersion") != 1 || !"esteria-world-config-overrides-policy".equals(policy.getString("scope")))
                throw new IOException("Unknown server settings policy");
            Map<String, String> defaults = new HashMap<>();
            JSONObject launch = policy.getJSONObject("launchDefaults");
            for (java.util.Iterator<String> keys = launch.keys(); keys.hasNext();) { String key = keys.next(); defaults.put(key, launch.getString(key)); }
            rules = new ServerConfigRules(policy.getInt("maxOverrides"), policy.getInt("maxValueLength"),
                Pattern.compile(policy.getString("filePattern")), strings(policy.getJSONArray("protectedKeys")),
                patterns(policy.getJSONArray("protectedPatterns")), strings(policy.getJSONArray("heavyKeys")),
                patterns(policy.getJSONArray("heavyPatterns")), defaults);
        } catch (JSONException | RuntimeException error) {
            throw new IOException("Invalid server settings policy", error);
        }
        cachedRules = rules;
        return rules;
    }

    private static Set<String> strings(JSONArray array) throws JSONException {
        Set<String> out = new LinkedHashSet<>();
        for (int i = 0; i < array.length(); i++) out.add(array.getString(i));
        return out;
    }

    private static List<Pattern> patterns(JSONArray array) throws JSONException {
        List<Pattern> out = new ArrayList<>();
        for (int i = 0; i < array.length(); i++) out.add(Pattern.compile(array.getString(i)));
        return out;
    }

    /** The document for the next session, or null when nothing was changed. */
    static byte[] sessionDocument(Context context) throws IOException {
        ServerConfigOverrides overrides = overrides(context);
        if (overrides.count() == 0) return null;
        try {
            JSONArray settings = new JSONArray();
            for (Map.Entry<String, Map<String, String>> file : overrides.all().entrySet())
                for (Map.Entry<String, String> setting : file.getValue().entrySet())
                    settings.put(new JSONObject().put("file", file.getKey()).put("key", setting.getKey()).put("value", setting.getValue()));
            JSONObject document = new JSONObject().put("formatVersion", 1).put("scope", "esteria-world-config-overrides").put("settings", settings);
            return (document.toString() + "\n").getBytes(StandardCharsets.UTF_8);
        } catch (JSONException error) {
            throw new IOException("Cannot write server settings", error);
        }
    }

    /** Support facts: the owner's chosen settings for the next start, names and values, bounded. */
    public static void supportFacts(Context context, Map<String, String> facts) {
        try {
            ServerConfigOverrides overrides = overrides(context);
            facts.put("server.settings.nextStart.count", Integer.toString(overrides.count()));
            if (overrides.count() == 0) return;
            StringBuilder shown = new StringBuilder();
            for (Map<String, String> settings : overrides.all().values())
                for (Map.Entry<String, String> setting : settings.entrySet()) {
                    String item = setting.getKey() + "=" + setting.getValue();
                    if (shown.length() + item.length() + 2 > 1800) { shown.append("; …"); break; }
                    if (shown.length() > 0) shown.append("; ");
                    shown.append(item);
                }
            facts.put("server.settings.nextStart", shown.toString());
        } catch (IOException | RuntimeException unavailable) {
            facts.put("server.settings.nextStart.count", "unreadable");
        }
    }
}
