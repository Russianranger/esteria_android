package io.github.russianranger.esteria.core.server;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Host checks of the server settings parser, the reviewed policy and the owner's saved choices. */
public final class ServerConfigTests {
    private static void check(boolean condition, String message) { if (!condition) throw new AssertionError(message); }

    // Shapes copied from the pinned worldserver.conf.dist and playerbots.conf.dist.
    static final String WORLD = String.join("\r\n",
        "################################################", "[worldserver]", "",
        "###################################################################################################",
        "# SECTION INDEX", "#", "#    CONNECTIONS AND DIRECTORIES", "#    EXPERIENCE",
        "###################################################################################################", "",
        "###################################################################################################",
        "# CONNECTIONS AND DIRECTORIES", "#",
        "#    RealmID", "#        Description: ID of the Realm using this config.", "#        Default:     1", "", "RealmID = 1", "",
        "#", "#    DataDir", "#        Description: Data directory setting.", "#        Default:     \".\"", "",
        "DataDir = \"/esteria-data\"", "",
        "#", "#    WorldDatabaseInfo", "#        Description: Database connection settings for the world server.", "",
        "WorldDatabaseInfo = \"127.0.0.1;13306;esteria;s3cret;acore_world\"", "",
        "###################################################################################################",
        "# SERVER", "#",
        "#    GameType", "#        Description: Server realm type.", "#        Default:     0  - (NORMAL)",
        "#                     1  - (PVP)", "#                     6  - (RP)", "", "GameType = 0", "",
        "#", "#    MinWorldUpdateTime",
        "#        Description: Minimum time (milliseconds) between world update ticks (for mostly idle servers).",
        "#        Default:     1 - (0.001 second)", "", "MinWorldUpdateTime = 1", "",
        "#", "#    Motd", "#        Description: Message of the Day.", "", "Motd = \"Welcome to an AzerothCore server.\"", "",
        "###################################################################################################",
        "# EXPERIENCE", "#",
        "#    Rate.Drop.Item.Poor", "#    Rate.Drop.Item.Normal",
        "#        Description: Drop rates for money and items based on quality.",
        "#        Default:     1 - (Rate.Drop.Item.Poor)", "#                     1 - (Rate.Drop.Item.Normal)", "",
        "Rate.Drop.Item.Poor             = 1", "Rate.Drop.Item.Normal           = 1", "",
        "#", "#    Rate.Honor", "#        Default:     1", "", "Rate.Honor = 1.5", "",
        "#", "#    Quests.IgnoreRaid", "#        Description: Allow non-raid quests to be completed while in a raid group.",
        "#        Default:     0 - (Disabled)", "#                     1 - (Enabled)", "", "Quests.IgnoreRaid = 0",
        "Quests.IgnoreRaid = 1", "");
    static final String BOTS = String.join("\n",
        "[worldserver]", "", "##################################################", "# PLAYERBOTS", "#",
        "# Enable or disable Playerbots module", "AiPlayerbot.Enabled = 1", "",
        "# Randombot count", "AiPlayerbot.MinRandomBots = 0", "AiPlayerbot.MaxRandomBots = 0", "",
        "# Map IDs where bots can be teleported to", "# Defaults: 0 = Eastern Kingdoms, 1 = Kalimdor",
        "AiPlayerbot.RandomBotMaps = 0,1,530,571", "", "# Comma-separated list of bot names", "AiPlayerbot.LevelBrackets.ExcludeNames = ",
        "", "# Bots pick their quest rewards", "AiPlayerbot.AutoPickReward = yes", "", "# Allow bots to use cheats",
        "AiPlayerbot.SomeFlag = false", "AiPlayerbot.CommandServerPort = 0", "");

    private static ServerConfigFile.Setting find(ServerConfigFile file, String key) {
        for (ServerConfigFile.Setting setting : file.settings) if (setting.key.equals(key)) return setting;
        throw new AssertionError("missing " + key);
    }

    private static void parsing() {
        ServerConfigFile world = ServerConfigFile.parse("worldserver.conf", WORLD);
        check(world.sections.equals(List.of("Connections and directories", "Server", "Experience")), "sections " + world.sections);
        check(world.settings.size() == 10, "settings " + world.settings.size());
        ServerConfigFile.Setting realm = find(world, "RealmID");
        check(realm.kind == ServerConfigFile.Kind.INTEGER && realm.value.equals("1") && realm.help.startsWith("Description: ID of the Realm") &&
            !realm.help.contains("RealmID\n"), "integer with help, key line removed: " + realm.help);
        ServerConfigFile.Setting data = find(world, "DataDir");
        check(data.quoted && data.value.equals("/esteria-data") && data.kind == ServerConfigFile.Kind.TEXT, "quoted text");
        ServerConfigFile.Setting type = find(world, "GameType");
        check(type.kind == ServerConfigFile.Kind.CHOICE && type.choices.size() == 3 && "RP".equals(type.choiceLabel("6")) &&
            type.section.equals("Server"), "choice " + type.choices);
        check(find(world, "MinWorldUpdateTime").kind == ServerConfigFile.Kind.INTEGER, "one documented value is not a choice");
        check(find(world, "Motd").value.equals("Welcome to an AzerothCore server."), "text");
        ServerConfigFile.Setting normal = find(world, "Rate.Drop.Item.Normal");
        check(normal.kind == ServerConfigFile.Kind.DECIMAL && normal.choices.isEmpty() && normal.help.contains("Drop rates") &&
            normal.section.equals("Experience"), "shared help block, key defaults are not choices");
        check(find(world, "Rate.Honor").kind == ServerConfigFile.Kind.DECIMAL, "decimal");
        ServerConfigFile.Setting raid = find(world, "Quests.IgnoreRaid");
        check(raid.kind == ServerConfigFile.Kind.SWITCH && raid.value.equals("1") && raid.switchValue(false).equals("0"),
            "documented switch; a repeated key keeps the last value");
        check(world.settings.get(world.settings.size() - 1) == raid, "a repeated key moves to its last position");

        ServerConfigFile bots = ServerConfigFile.parse("modules/playerbots.conf", BOTS);
        check(bots.sections.equals(List.of("Playerbots")), "module section " + bots.sections);
        check(find(bots, "AiPlayerbot.Enabled").kind == ServerConfigFile.Kind.SWITCH, "enable switch from help");
        check(find(bots, "AiPlayerbot.MaxRandomBots").kind == ServerConfigFile.Kind.INTEGER &&
            find(bots, "AiPlayerbot.MaxRandomBots").help.equals("Randombot count"), "shared module comment");
        check(find(bots, "AiPlayerbot.RandomBotMaps").kind == ServerConfigFile.Kind.TEXT, "list text");
        check(find(bots, "AiPlayerbot.LevelBrackets.ExcludeNames").value.isEmpty(), "empty list");
        ServerConfigFile.Setting words = find(bots, "AiPlayerbot.SomeFlag");
        check(words.kind == ServerConfigFile.Kind.SWITCH && words.switchValue(true).equals("true"), "word switch keeps words");
        check(ServerConfigFile.fallbackSection("modules/mod_dungeon_clear.conf").equals("Dungeon clear") &&
            ServerConfigFile.fallbackSection("worldserver.conf").equals("World server"), "fallback section names");
        check(ServerConfigFile.titleCase("FFAPVP").equals("FFA PvP") && ServerConfigFile.titleCase("PLAY TIME LIMIT (CAIS)").equals("Play time limit (CAIS)"),
            "section acronyms");
    }

    static ServerConfigRules policy(Path path) throws IOException {
        String json = Files.readString(path, StandardCharsets.UTF_8);
        Map<String, String> defaults = new HashMap<>();
        Matcher pair = Pattern.compile("\"([A-Za-z.]+)\": \"([0-9]+)\"").matcher(section(json, "launchDefaults", '{', '}'));
        while (pair.find()) defaults.put(pair.group(1), pair.group(2));
        List<Pattern> protectedPatterns = new ArrayList<>(), heavyPatterns = new ArrayList<>();
        for (String pattern : strings(section(json, "protectedPatterns", '[', ']'))) protectedPatterns.add(Pattern.compile(pattern));
        for (String pattern : strings(section(json, "heavyPatterns", '[', ']'))) heavyPatterns.add(Pattern.compile(pattern));
        Matcher file = Pattern.compile("\"filePattern\": \"((?:[^\"\\\\]|\\\\.)*)\"").matcher(json);
        check(file.find(), "file pattern");
        return new ServerConfigRules(256, 255, Pattern.compile(unescape(file.group(1))),
            new LinkedHashSet<>(strings(section(json, "protectedKeys", '[', ']'))), protectedPatterns,
            new LinkedHashSet<>(strings(section(json, "heavyKeys", '[', ']'))), heavyPatterns, defaults);
    }
    private static String section(String json, String name, char open, char close) {
        int start = json.indexOf('"' + name + '"'); start = json.indexOf(open, start);
        return json.substring(start + 1, json.indexOf(close, start));
    }
    private static List<String> strings(String array) {
        List<String> out = new ArrayList<>();
        Matcher item = Pattern.compile("\"((?:[^\"\\\\]|\\\\.)*)\"").matcher(array);
        while (item.find()) out.add(unescape(item.group(1)));
        return out;
    }
    private static String unescape(String text) { return text.replace("\\\\", "\\"); }

    private static void rules(ServerConfigRules rules) {
        for (String key : List.of("RealmID", "DataDir", "WorldDatabaseInfo", "LoginDatabase.WorkerThreads", "Updates.EnableDatabases",
                "Logger.root", "Appender.Console", "LogsDir", "Console.Enable", "Ra.Port", "SOAP.IP", "AiPlayerbot.CommandServerPort",
                "PidFile", "Transmogrification.Enable", "Expansion", "Network.Threads", "Eluna.Enabled", "IPLocationFile"))
            check(rules.managed(key), "managed " + key);
        for (String key : List.of("Rate.XP.Kill", "GameType", "Motd", "MinWorldUpdateTime", "AiPlayerbot.MaxRandomBots",
                "MapUpdate.Threads", "Quests.IgnoreRaid", "AutoBalance.Enable"))
            check(!rules.managed(key), "owner choice " + key);
        check(rules.heavy("AiPlayerbot.MaxRandomBots") && rules.heavy("Visibility.Distance.Continents") && !rules.heavy("Rate.XP.Kill"), "heavy");
        check("20".equals(rules.launchDefault("MinWorldUpdateTime")) && "50".equals(rules.launchDefault("MapUpdateInterval")) &&
            rules.launchDefault("Rate.XP.Kill") == null, "launch defaults");
        check(rules.fileAllowed("worldserver.conf") && rules.fileAllowed("modules/playerbots.conf") && !rules.fileAllowed("authserver.conf") &&
            !rules.fileAllowed("modules/../worldserver.conf") && !rules.fileAllowed("mysql.cnf"), "files");

        ServerConfigFile world = ServerConfigFile.parse("worldserver.conf", WORLD);
        ServerConfigFile.Setting kill = find(world, "Rate.Drop.Item.Poor"), honor = find(world, "Rate.Honor"),
            raid = find(world, "Quests.IgnoreRaid"), motd = find(world, "Motd"), realm = find(world, "RealmID");
        ServerConfigFile.Setting tick = find(world, "MinWorldUpdateTime");
        check(rules.problem(tick, "3") == null && rules.problem(tick, "2.5") != null && rules.problem(tick, "") != null, "whole numbers");
        check(kill.kind == ServerConfigFile.Kind.DECIMAL && rules.problem(kill, "1.5") == null && rules.problem(kill, "3") == null,
            "rates take decimals even when the file writes a whole number");
        check(rules.problem(honor, "2.5") == null && rules.problem(honor, "2") == null && rules.problem(honor, "x") != null, "decimals");
        check(rules.problem(raid, "1") == null && rules.problem(raid, "2") != null, "switches");
        check(rules.problem(motd, "Hello, Thor") == null && rules.problem(motd, "") == null && rules.problem(motd, "say \"hi\"") != null &&
            rules.problem(motd, "a\tb") != null && rules.problem(motd, " x") != null && rules.problem(motd, "x".repeat(256)) != null &&
            rules.problem(motd, "no break") != null, "text values");
        check(rules.problem(realm, "2") != null, "managed values are refused");

        check(ServerConfigRules.environmentName("AiPlayerbot.MaxRandomBots").equals("AC_AI_PLAYERBOT_MAX_RANDOM_BOTS") &&
            ServerConfigRules.environmentName("Rate.XP.Kill").equals("AC_RATE_XP_KILL") &&
            ServerConfigRules.environmentName("MinWorldUpdateTime").equals("AC_MIN_WORLD_UPDATE_TIME") &&
            ServerConfigRules.environmentName("LogDB.Opt.ClearTime").equals("AC_LOG_DB_OPT_CLEAR_TIME") &&
            ServerConfigRules.environmentName("myNestedConfig.opt1").equals("AC_MY_NESTED_CONFIG_OPT_1") &&
            ServerConfigRules.environmentName("Arena.ArenaSeason.ID").equals("AC_ARENA_ARENA_SEASON_ID"), "environment names");
    }

    private static void store(ServerConfigRules rules, Path root) throws IOException {
        ServerConfigFile world = ServerConfigFile.parse("worldserver.conf", WORLD);
        ServerConfigFile bots = ServerConfigFile.parse("modules/playerbots.conf", BOTS);
        ServerConfigOverrides overrides = ServerConfigOverrides.read(root.resolve("missing"));
        check(overrides.count() == 0, "missing store is empty");
        overrides.set(find(world, "Rate.Drop.Item.Poor"), "3", rules);
        overrides.set(find(bots, "AiPlayerbot.MaxRandomBots"), "20", rules);
        overrides.set(find(world, "Motd"), "Hello", rules);
        overrides.set(find(bots, "AiPlayerbot.RandomBotMaps"), "", rules);
        overrides.set(find(world, "Motd"), "Welcome to an AzerothCore server.", rules);
        check(overrides.count() == 3 && overrides.get("worldserver.conf", "Motd") == null, "the file value removes an override");
        overrides.set(find(world, "MinWorldUpdateTime"), "1", rules);
        check("1".equals(overrides.get("worldserver.conf", "MinWorldUpdateTime")), "the file value differs from the session default");
        overrides.set(find(world, "MinWorldUpdateTime"), "20", rules);
        check(overrides.get("worldserver.conf", "MinWorldUpdateTime") == null, "the session default removes the override");
        try { overrides.set(find(world, "DataDir"), "/x", rules); throw new AssertionError("managed setting saved"); }
        catch (IllegalArgumentException expected) { /* Refused. */ }
        Path saved = root.resolve("settings/world-settings.tsv");
        overrides.write(saved);
        ServerConfigOverrides again = ServerConfigOverrides.read(saved);
        check(again.all().equals(overrides.all()) && "".equals(again.get("modules/playerbots.conf", "AiPlayerbot.RandomBotMaps")),
            "round trip " + again.all());
        Files.writeString(saved, "Esteria world settings v1\nworldserver.conf\tRate XP\t2\n");
        try { ServerConfigOverrides.read(saved); throw new AssertionError("malformed accepted"); } catch (IOException expected) { /* Refused. */ }
        Files.writeString(saved, "something else\n");
        try { ServerConfigOverrides.read(saved); throw new AssertionError("unknown accepted"); } catch (IOException expected) { /* Refused. */ }
        ServerConfigRules small = new ServerConfigRules(1, 255, Pattern.compile(".*"), Set.of(), List.of(), Set.of(), List.of(), Map.of());
        ServerConfigOverrides limited = new ServerConfigOverrides();
        limited.set(find(world, "Rate.Drop.Item.Poor"), "2", small);
        limited.set(find(world, "Rate.Drop.Item.Poor"), "4", small);
        try { limited.set(find(world, "Rate.Honor"), "2", small); throw new AssertionError("limit"); }
        catch (IllegalArgumentException expected) { /* Refused. */ }
    }

    public static void main(String[] args) throws Exception {
        Path repository = Paths.get(args.length > 0 ? args[0] : ".").toAbsolutePath().normalize();
        Path policy = repository.resolve("config/world-config-policy.json");
        if (!Files.isRegularFile(policy)) policy = repository.getParent().resolve("config/world-config-policy.json");
        Path root = Files.createTempDirectory("esteria-server-config");
        parsing();
        ServerConfigRules rules = policy(policy);
        rules(rules);
        store(rules, root);
        System.out.println("Server settings passed 3 host groups: parsing, reviewed policy, saved choices; no server or Android run");
    }
}
