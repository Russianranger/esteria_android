package io.github.russianranger.esteria.core.runtime;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Comparator;

/** Host Wine REGv2 fixtures. Production Android controls exercise the actual stopped hives. */
public final class StockWinePrefixRegistryTests {
    private static final String HEADER = "WINE REGISTRY Version 2\n;; All keys relative to ";
    private static final String MACHINE = HEADER + "REGISTRY\\\\Machine\n\n#arch=win64\n";
    private static final String USER =
            HEADER + "REGISTRY\\\\User\\\\S-1-5-21-0-0-0-1000\n\n#arch=win64\n";
    private static final String CV = "Software\\Microsoft\\Windows\\CurrentVersion\\";

    private static String section(String key, String serialized) {
        return "\n["
                + key.replace("\\", "\\\\")
                + "] 1794139770\n#time=1d0cabbadf00d42\n"
                + serialized
                + "\n";
    }

    private static String com(String guid, String dll) {
        return section(
                "Software\\Classes\\CLSID\\{" + guid + "}\\INPROCSERVER32",
                "@=\"C:\\\\Windows\\\\system32\\\\" + dll + "\"\n\"ThreadingModel\"=\"Both\"");
    }

    private static final String EARLY =
            MACHINE
                    + com("E436EBB3-524F-11CE-9F53-0020AF0BA770", "quartz.dll")
                    + com("78530B75-61F9-11D2-8CAD-00A024580902", "qedit.dll")
                    + com("82D353DF-90BD-4382-8BC2-3F6192B76E34", "wmvdecod.dll");
    private static final String DX =
            section(
                    "Software\\Microsoft\\DirectX",
                    "\"Version\"=\"4.09.00.0904\"\n"
                            + "\"InstalledVersion\"=hex:00,00,00,09,00,00,00,00");
    private static final String DEBUG =
            section(
                    "Software\\Microsoft\\Windows NT\\CurrentVersion\\AeDebug",
                    "\"Debugger\"=\"winedbg --auto %ld %ld\"");
    private static final String PREFS =
            section("Software\\Esteria Test\\Settings", "\"Retained\"=\"unknown retained value\"");

    private static void check(boolean ok) {
        if (!ok) throw new AssertionError();
    }

    private static void checkFileProtectionQueue(Path prefix, Path windows, Path machine)
            throws Exception {
        String key = "Software\\Microsoft\\Windows NT\\CurrentVersion\\Winlogon";
        Path sys = Files.createDirectory(windows.resolve("system32"));
        Path queue = Files.createDirectory(sys.resolve("DLLCache"));
        Files.writeString(machine, EARLY + section(key, "\"SFCDllCacheDir\"=\"C:\\\\retained\""));
        check(!StockWinePrefixRegistry.safeToUpdate(prefix));
        Files.writeString(
                machine,
                EARLY
                        + section(
                                key,
                                "\"SFCDllCacheDir\"=\"C:\\\\windows\\\\system32\\\\dllcache\""));
        check(StockWinePrefixRegistry.safeToUpdate(prefix));
        Path file = Files.writeString(queue.resolve("retained.dll"), "keep");
        check(!StockWinePrefixRegistry.safeToUpdate(prefix));
        check(Files.readString(file).equals("keep"));
        Files.delete(file);
        Path alias = sys.resolve("dllcache");
        Files.createDirectory(alias);
        check(!StockWinePrefixRegistry.safeToUpdate(prefix));
        Files.delete(alias);
        Files.delete(queue);
        Files.createSymbolicLink(alias, prefix);
        check(!StockWinePrefixRegistry.safeToUpdate(prefix));
        Files.delete(alias);
        check(StockWinePrefixRegistry.safeToUpdate(prefix));
    }

    public static void main(String[] args) throws Exception {
        Path prefix = Files.createTempDirectory("esteria-reg-guard-");
        try {
            Path machine = prefix.resolve("system.reg"), user = prefix.resolve("user.reg");
            Path windows = Files.createDirectories(prefix.resolve("drive_c/windows"));
            Path home = Files.createDirectories(prefix.resolve("drive_c/users/guest"));
            Files.writeString(machine, EARLY);
            for (String foreignRoot :
                    new String[] {
                        USER.replace("to REGISTRY", "to "),
                        USER.replace("0-1000", "0-1001"),
                        USER.replace("User", "Machine")
                    }) {
                Files.writeString(user, foreignRoot + PREFS);
                check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            }
            Files.writeString(user, USER + PREFS);
            check(
                    StockWinePrefixRegistry.inspect(prefix)
                            == StockWinePrefixRegistry.Stage.MISSING_DEFAULTS);
            check(StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(machine, EARLY + DEBUG);
            check(
                    StockWinePrefixRegistry.inspect(prefix)
                            == StockWinePrefixRegistry.Stage.RESUMABLE);
            Files.writeString(machine, EARLY + DX + DEBUG);
            check(
                    StockWinePrefixRegistry.inspect(prefix)
                            == StockWinePrefixRegistry.Stage.COMPLETE);
            for (String invalid :
                    new String[] {
                        EARLY + DX.replace("4.09.00.0904", "custom"),
                        EARLY + DX + DX,
                        EARLY.replace("qedit.dll", "other.dll"),
                        MACHINE + DX + DEBUG,
                        EARLY.replace("win64", "win32"),
                        EARLY.replace("Version 2", "Version 1"),
                        EARLY.replace("to REGISTRY", "to "),
                        EARLY.replace("to REGISTRY", "to FOREIGN"),
                        EARLY.replace("\\\\Machine", "\\\\User"),
                        EARLY + section("Software\\Microsoft\\DirectX", "#link")
                    }) {
                Files.writeString(machine, invalid);
                check(
                        StockWinePrefixRegistry.inspect(prefix)
                                == StockWinePrefixRegistry.Stage.UNKNOWN);
            }
            for (String key :
                    new String[] {
                        CV + "Run",
                        CV + "RunServicesOnce",
                        CV + "RunOnce",
                        "Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\RunOnce"
                    }) {
                Files.writeString(machine, EARLY + section(key, "\"Launch\"=\"custom.exe\""));
                check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            }
            Files.writeString(
                    machine,
                    EARLY
                            + section(
                                    "System\\CurrentControlSet\\Control\\Session Manager",
                                    "\"PendingFileRenameOperations\"=str(7):\"test\""));
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(machine, EARLY + DX.replace("4.09.00.0904", "custom"));
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(machine, EARLY + DX.replace("09,00", "08,00"));
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(machine, EARLY);
            String urls = "Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\";
            String nav = "AppEvents\\Schemes\\Apps\\Explorer\\Navigating\\.Current";
            for (String scheme : new String[] {"ftp", "http", "https"}) {
                Files.writeString(
                        user,
                        USER + section(urls + scheme + "\\UserChoice", "\"ProgId\"=\"custom\""));
                check(!StockWinePrefixRegistry.safeToUpdate(prefix));
                Files.writeString(
                        user,
                        USER
                                + section(
                                        urls + scheme + "\\UserChoice",
                                        "\"ProgId\"=\"" + scheme + "\""));
                check(StockWinePrefixRegistry.safeToUpdate(prefix));
            }
            Files.writeString(user, USER + section(nav, "@=\"custom.wav\""));
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(
                    user,
                    USER
                            + section(
                                    CV + "Explorer\\User Shell Folders",
                                    "\"Startup\"=\"D:\\\\custom\""));
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.writeString(user, USER + PREFS + section(nav, "@=\"\""));
            check(StockWinePrefixRegistry.safeToUpdate(prefix));
            Path startup =
                    Files.createDirectories(
                            home.resolve(
                                    "AppData/Roaming/Microsoft/Windows/Start"
                                            + " Menu/Programs/StartUp"));
            Files.writeString(startup.resolve("custom.lnk"), "preserve");
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.delete(startup.resolve("custom.lnk"));
            Files.writeString(windows.resolve("WININIT.INI"), "preserve");
            check(!StockWinePrefixRegistry.safeToUpdate(prefix));
            Files.delete(windows.resolve("WININIT.INI"));
            check(StockWinePrefixRegistry.safeToUpdate(prefix));
            check(Files.readString(user).contains(PREFS));
            checkFileProtectionQueue(prefix, windows, machine);

        } finally {
            try (var paths = Files.walk(prefix)) {
                for (Path p : paths.sorted(Comparator.reverseOrder()).toList()) Files.delete(p);
            }
        }
        System.out.println(
                "PASS Wine REGv2 retained interruption, completed and guarded update fixtures");
    }
}
