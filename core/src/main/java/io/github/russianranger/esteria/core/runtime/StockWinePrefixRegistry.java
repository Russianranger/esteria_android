package io.github.russianranger.esteria.core.runtime;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

/** Stopped, owner-selected Wine 10.13 registry observations; never authority to run wineboot. */
final class StockWinePrefixRegistry {
    enum Stage {
        MISSING_DEFAULTS,
        COMPLETE,
        RESUMABLE,
        UNKNOWN
    }

    private static final String SOFTWARE = "software\\", MS = SOFTWARE + "microsoft\\";
    private static final String CV = MS + "windows\\currentversion\\";
    private static final String CLSID = SOFTWARE + "classes\\clsid\\";
    private static final String QUARTZ =
            CLSID + "{e436ebb3-524f-11ce-9f53-0020af0ba770}\\inprocserver32";
    private static final String QEDIT =
            CLSID + "{78530b75-61f9-11d2-8cad-00a024580902}\\inprocserver32";
    private static final String WMV =
            CLSID + "{82d353df-90bd-4382-8bc2-3f6192b76e34}\\inprocserver32";
    private static final String DIRECTX = MS + "directx",
            DEBUG = MS + "windows nt\\currentversion\\aedebug";
    private static final String WINLOGON = MS + "windows nt\\currentversion\\winlogon";
    private static final String SESSION = "system\\currentcontrolset\\control\\session manager";
    private static final String SHELL = CV + "explorer\\shell folders",
            USER_SHELL = CV + "explorer\\user shell folders";
    private static final String STARTUP =
            "appdata\\roaming\\microsoft\\windows\\start menu\\programs\\startup";
    private static final String NAV = "appevents\\schemes\\apps\\explorer\\navigating\\.current";
    private static final String URL = MS + "windows\\shell\\associations\\urlassociations\\";
    private static final String FILE_PATH = "c:\\windows\\system32\\";
    private static final String[] SCHEMES = {"ftp", "http", "https"};
    private static final String CONTROL_SET = "system\\controlset001\\control\\session manager";
    private static final Set<String> SYSTEM =
            Set.of(QUARTZ, QEDIT, WMV, DIRECTX, DEBUG, SESSION, CONTROL_SET, WINLOGON);
    private static final Set<String> USER =
            Set.of(
                    NAV,
                    URL + "ftp\\userchoice",
                    URL + "http\\userchoice",
                    URL + "https\\userchoice",
                    SHELL,
                    USER_SHELL);

    private StockWinePrefixRegistry() {}

    static Stage inspect(Path prefix) {
        try {
            Map<String, String> v = read(prefix.resolve("system.reg"), true);
            // WineFakeDlls registers these three native COM resources before the Mono prompt.
            if (!dll(v, QUARTZ, "quartz.dll")
                    || !dll(v, QEDIT, "qedit.dll")
                    || !dll(v, WMV, "wmvdecod.dll")) return Stage.UNKNOWN;
            String dx = value(v, DIRECTX, "Version"), debug = value(v, DEBUG, "Debugger");
            if ((dx != null && !dx.equals(quoted("4.09.00.0904")))
                    || (debug != null && !debug.equals(quoted("winedbg --auto %ld %ld"))))
                return Stage.UNKNOWN;
            if (dx != null && debug != null) return Stage.COMPLETE;
            if (dx == null && debug == null) return Stage.MISSING_DEFAULTS;
            return Stage.RESUMABLE;
        } catch (IOException e) {
            return Stage.UNKNOWN;
        }
    }

    static boolean safeToUpdate(Path prefix) {
        try {
            Map<String, String> system = read(prefix.resolve("system.reg"), true),
                    user = read(prefix.resolve("user.reg"), false);
            if (system.containsKey("autorun")
                    || user.containsKey("autorun")
                    || !absentOr(system, WINLOGON, "SFCDllCacheDir", quoted(FILE_PATH + "dllcache"))
                    || value(system, SESSION, "PendingFileRenameOperations") != null
                    || value(system, CONTROL_SET, "PendingFileRenameOperations") != null
                    || !absentOr(system, DIRECTX, "Version", quoted("4.09.00.0904"))
                    || !absentOr(system, DIRECTX, "InstalledVersion", "hex:00,00,00,09,00,00,00,00")
                    || !absentOr(user, NAV, "@", quoted(""))) return false;
            for (String scheme : SCHEMES)
                if (!absentOr(user, URL + scheme + "\\userchoice", "ProgId", quoted(scheme)))
                    return false;
            Path c = prefix.resolve("drive_c"), windows = c.resolve("windows");
            if (!directory(c) || !directory(windows) || child(windows, "wininit.ini") != null)
                return false;
            // wineboot -u installs and then deletes each queued Windows File Protection file.
            if (!emptyFolderIfPresent(c, "windows", "system32", "dllcache")) return false;
            Path users = c.resolve("users");
            if (!directory(users)) return false;
            Set<String> folders = new HashSet<>();
            int count = 0;
            try (DirectoryStream<Path> entries = Files.newDirectoryStream(users)) {
                for (Path home : entries) {
                    if (++count > 32 || !directory(home)) return false;
                    String name = home.getFileName().toString();
                    if (!name.matches("[A-Za-z0-9._ -]{1,80}")) return false;
                    folders.add(
                            quoted("c:\\users\\" + name + "\\" + STARTUP).toLowerCase(Locale.ROOT));
                    if (!emptyFolderIfPresent(
                            home,
                            "AppData",
                            "Roaming",
                            "Microsoft",
                            "Windows",
                            "Start Menu",
                            "Programs",
                            "Startup")) return false;
                }
            }
            for (String key : new String[] {SHELL, USER_SHELL}) {
                String saved = value(user, key, "Startup");
                if (saved != null
                        && !folders.contains(saved.toLowerCase(Locale.ROOT))
                        && !saved.equalsIgnoreCase("str(2):" + quoted("%USERPROFILE%\\" + STARTUP))
                        && !saved.equalsIgnoreCase(
                                "str(2):"
                                        + quoted(
                                                "%APPDATA%\\Microsoft\\Windows\\Start"
                                                        + " Menu\\Programs\\Startup")))
                    return false;
            }
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    private static boolean directory(Path path) {
        return Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS);
    }

    private static boolean emptyFolderIfPresent(Path at, String... components) throws IOException {
        for (String component : components) {
            at = child(at, component);
            if (at == null) return true;
            if (!directory(at)) return false;
        }
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(at)) {
            return !entries.iterator().hasNext();
        }
    }

    // Windows names are case-insensitive on the guest, even on a case-sensitive prefix volume.
    private static Path child(Path directory, String name) throws IOException {
        Path match = null;
        int count = 0;
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(directory)) {
            for (Path p : entries) {
                if (++count > 4096) throw new IOException("Folder exceeds bound");
                if (p.getFileName().toString().equalsIgnoreCase(name)) {
                    if (match != null) throw new IOException("Ambiguous Windows path");
                    match = p;
                }
            }
        }
        return match;
    }

    private static boolean autorun(String key, boolean system) {
        if (system && key.startsWith("software\\wow6432node\\"))
            key = SOFTWARE + key.substring("software\\wow6432node\\".length());
        return key.equals(CV + "run")
                || (system && (key.equals(CV + "runonce") || key.equals(CV + "runservicesonce")));
    }

    private static String quoted(String s) {
        return "\"" + s.replace("\\", "\\\\") + "\"";
    }

    private static String value(Map<String, String> values, String section, String name) {
        return values.get(section + "|" + name.toLowerCase(Locale.ROOT));
    }

    private static boolean absentOr(
            Map<String, String> values, String section, String name, String expected) {
        String raw = value(values, section, name);
        return raw == null || raw.equalsIgnoreCase(expected);
    }

    private static boolean dll(Map<String, String> values, String key, String name) {
        return quoted(FILE_PATH + name).equalsIgnoreCase(value(values, key, "@"));
    }

    private static Map<String, String> read(Path path, boolean machine) throws IOException {
        long size = Files.size(path);
        if (size < 32 || size > (8L << 20) || !Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Unsupported Wine registry");
        Map<String, String> values = new HashMap<>();
        Set<String> seen = new HashSet<>();
        try (BufferedReader f =
                new BufferedReader(
                        new InputStreamReader(
                                Files.newInputStream(path, LinkOption.NOFOLLOW_LINKS),
                                StandardCharsets.UTF_8))) {
            if (!"WINE REGISTRY Version 2".equals(f.readLine()))
                throw new IOException("Registry version");
            // Wine's dump_path includes the REGISTRY root key. Its fixed local_user_sid
            // is S-1-5-21-0-0-0-1000 for this Wine source on ARM64.
            String hive = machine ? "Machine" : "User\\\\S-1-5-21-0-0-0-1000";
            if (!(";; All keys relative to REGISTRY\\\\" + hive).equals(f.readLine()))
                throw new IOException("Registry root");
            if (!"".equals(f.readLine()) || !"#arch=win64".equals(f.readLine()))
                throw new IOException("Registry architecture");
            String section = null;
            boolean run = false;
            long length = 0;
            for (String line; (line = f.readLine()) != null; ) {
                length += line.length() + 1;
                if (length > (8L << 20) || line.length() > 16384)
                    throw new IOException("Registry record exceeds bound");
                if (line.startsWith("[")) {
                    int end = line.lastIndexOf("] ");
                    if (end < 1) throw new IOException("Registry section");
                    String key =
                            line.substring(1, end).replace("\\\\", "\\").toLowerCase(Locale.ROOT);
                    run = autorun(key, machine);
                    section = run || (machine ? SYSTEM : USER).contains(key) ? key : null;
                    if (section != null && !seen.add(section))
                        throw new IOException("Duplicate observed section");
                } else if (section != null && !line.isEmpty() && !line.startsWith("#time=")) {
                    if (line.equals("#link")) throw new IOException("Linked observed section");
                    if (run) {
                        values.put("autorun", "1");
                        continue;
                    }
                    String name;
                    int end;
                    if (line.startsWith("@=")) {
                        name = "@";
                        end = 2;
                    } else if (line.startsWith("\"") && (end = line.indexOf("\"=", 1)) > 1) {
                        name = line.substring(1, end);
                        end += 2;
                    } else continue;
                    String key = section + "|" + name.toLowerCase(Locale.ROOT);
                    if (values.size() >= 512 || values.put(key, line.substring(end)) != null)
                        throw new IOException("Duplicate/bounded observed value");
                }
            }
        }
        return values;
    }
}
