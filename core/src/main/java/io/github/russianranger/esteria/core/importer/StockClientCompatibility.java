package io.github.russianranger.esteria.core.importer;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** Bounded import evidence. MPQ headers and VERSIONINFO are not content authentication. */
public final class StockClientCompatibility {
    public static final String REPORT_NAME = "stock-import-compatibility.txt";
    private static final List<String> LOCALES = Arrays.asList("deDE", "enGB", "enUS", "esES", "frFR", "koKR", "zhCN", "zhTW", "enCN", "enTW", "esMX", "ruRU");
    private static final List<String> ROOT_ARCHIVES = Arrays.asList("common.MPQ", "common-2.MPQ", "expansion.MPQ", "lichking.MPQ", "patch.MPQ", "patch-2.MPQ", "patch-3.MPQ");
    private static final int MAX_ENTRIES = 8192;
    private StockClientCompatibility() {}

    public static final class Report {
        public final String requestedLocale, effectiveLocale;
        public final List<String> installedLocales, errors, warnings, candidateOverlays, archiveEvidence;
        private Report(String requested, String effective, List<String> locales, List<String> errors,
                       List<String> warnings, List<String> overlays, List<String> archives) {
            requestedLocale = requested; effectiveLocale = effective;
            installedLocales = immutable(locales); this.errors = immutable(errors); this.warnings = immutable(warnings);
            candidateOverlays = immutable(overlays); archiveEvidence = immutable(archives);
        }
        public void requirePreparationInputs() throws IOException {
            if (!errors.isEmpty()) throw new IOException("Stock client preparation: " + String.join("; ", errors));
        }
        public String toText() {
            StringBuilder out = new StringBuilder("Esteria Stock 3.3.5a / non-custom import compatibility report\n")
                .append("contentProfile=stock-3.3.5a\nformatVersion=1\n")
                .append("requestedLocale=").append(requestedLocale).append('\n')
                .append("effectiveLocale=").append(effectiveLocale == null ? "unavailable" : effectiveLocale).append('\n')
                .append("installedLocales=").append(String.join(",", installedLocales)).append('\n')
                .append("structuralInputs=").append(errors.isEmpty() ? "passed" : "failed").append('\n')
                .append("exeEvidence=VERSIONINFO resource; required 3.3.5.12340; original executable is never launched\n")
                .append("archiveEvidence=bounded MPQ header/table extents, not complete archive integrity\n")
                .append("signedUi=not authenticated by import; original runtime signature checks remain enabled\n")
                .append("effectiveDbcLayouts=not inspected by import; validated during world preparation\n")
                .append("shaderInputs=not decoded by import; validated during shader preparation\n")
                .append("runtimeExecution=not demonstrated by import\n")
                .append("sourceInstallation=read only; source realm/account files remain unchanged\n")
                .append("standardPatches=preserved, including patch.MPQ, patch-2.MPQ, patch-3.MPQ and stock locale patches\n");
            out.append("errorCount=").append(errors.size()).append("; warningCount=").append(warnings.size())
                .append("; archiveCount=").append(archiveEvidence.size()).append("; unclassifiedOverlayCount=").append(candidateOverlays.size()).append('\n');
            // Fixed support metadata accepts at most 8 KiB of UTF-8. Errors are
            // emitted first; ordinary stock error paths are short and exact.
            int omitted = 0;
            for (String item : errors) if (!appendBounded(out, "error: " + item + "\n")) omitted++;
            for (String item : warnings) if (!appendBounded(out, "warning: " + item + "\n")) omitted++;
            for (String item : archiveEvidence) if (!appendBounded(out, "archive: " + item + "\n")) omitted++;
            for (String item : candidateOverlays) if (!appendBounded(out, "unclassified overlay candidate: " + item + "; filename alone does not establish identity or authorize exclusion\n")) omitted++;
            if (omitted > 0) out.append("detailsOmitted=").append(omitted).append("; report bounded to 8192 UTF-8 bytes\n");
            return out.toString();
        }
    }

    /** Call only at explicit import/preparation, while retaining the import lease. No whole-client hashing. */
    public static Report inspect(Path importedRoot, String requestedLocale) throws IOException {
        if (!LOCALES.contains(requestedLocale)) throw new IOException("Unsupported requested client locale: " + requestedLocale);
        Path root = importedRoot.toAbsolutePath().normalize();
        if (!Files.isDirectory(root, LinkOption.NOFOLLOW_LINKS) || !root.toRealPath().equals(root)) throw new IOException("Compatibility inspection requires the canonical imported client directory");
        List<String> errors = new ArrayList<>(), warnings = new ArrayList<>(), locales = new ArrayList<>(), overlays = new ArrayList<>(), archives = new ArrayList<>();
        Map<String, Path> rootEntries = children(root);
        Path exe = rootEntries.get("wow.exe");
        if (exe == null) errors.add("Missing Wow.exe version evidence (required 3.3.5.12340)");
        else {
            try { regular(exe); GameDataVerifier.verifyWowVersion(exe); }
            catch (IOException failure) { errors.add("Wow.exe: " + failure.getMessage()); }
        }
        Path data = rootEntries.get("data");
        if (data == null || !Files.isDirectory(data, LinkOption.NOFOLLOW_LINKS)) {
            errors.add("Missing Data directory");
            return new Report(requestedLocale, null, locales, errors, warnings, overlays, archives);
        }
        Map<String, Path> dataEntries = children(data);
        for (String name : ROOT_ARCHIVES) inspectArchive(dataEntries.get(name.toLowerCase(Locale.ROOT)), "Data/" + name, true, errors, archives);
        for (String locale : LOCALES) {
            Path folder = dataEntries.get(locale.toLowerCase(Locale.ROOT));
            if (folder != null && Files.isDirectory(folder, LinkOption.NOFOLLOW_LINKS)) {
                Map<String, Path> members = children(folder);
                Path local = members.get(("locale-" + locale + ".MPQ").toLowerCase(Locale.ROOT));
                if (local != null && Files.isRegularFile(local, LinkOption.NOFOLLOW_LINKS)) locales.add(locale);
                for (Map.Entry<String, Path> item : members.entrySet()) {
                    if (!item.getKey().endsWith(".mpq")) continue;
                    String path = "Data/" + folder.getFileName() + "/" + item.getValue().getFileName();
                    if (!stockLocaleArchive(item.getKey(), locale)) overlays.add(path);
                }
            }
        }
        String effective = null;
        int start = LOCALES.indexOf(requestedLocale);
        for (int i = 0; i < LOCALES.size(); i++) {
            String locale = LOCALES.get((start + i) % LOCALES.size());
            if (locales.contains(locale)) { effective = locale; break; }
        }
        if (effective == null) errors.add("Missing Data/<locale>/locale-<locale>.MPQ for every supported installed locale");
        else {
            Path folder = dataEntries.get(effective.toLowerCase(Locale.ROOT));
            Map<String, Path> members = children(folder);
            for (String stem : Arrays.asList("locale-", "speech-")) {
                String name = stem + effective + ".MPQ";
                inspectArchive(members.get(name.toLowerCase(Locale.ROOT)), "Data/" + effective + "/" + name, true, errors, archives);
            }
            for (String stem : Arrays.asList("expansion-locale-", "lichking-locale-", "expansion-speech-", "lichking-speech-", "patch-")) {
                String name = stem + effective + ".MPQ";
                Path path = members.get(name.toLowerCase(Locale.ROOT));
                if (path == null) warnings.add("Not supplied: Data/" + effective + "/" + name + "; completeness and required effective bytes still depend on preparation/runtime");
                else inspectArchive(path, "Data/" + effective + "/" + name, false, errors, archives);
            }
            if (effective.equals("enCN") || effective.equals("enTW")) errors.add("Effective locale " + effective + " is recognized by the client but unsupported by the pinned shader translator");
            if (!effective.equals(requestedLocale)) warnings.add("Requested " + requestedLocale + " is absent; source-defined client locale rotation selects " + effective);
        }
        for (Map.Entry<String, Path> item : dataEntries.entrySet()) {
            String name = item.getKey();
            if (!name.endsWith(".mpq")) continue;
            if (!ROOT_ARCHIVES.stream().anyMatch(stock -> stock.equalsIgnoreCase(name))) overlays.add("Data/" + item.getValue().getFileName());
        }
        if (rootEntries.containsKey("interface")) warnings.add("Loose Interface/AddOns content is outside the stock selection; stock signed UI must come from the selected archives");
        if (rootEntries.containsKey("esteriaserverdata")) warnings.add("Custom EsteriaServerData namespace is outside the stock profile; generated stock data is required");
        if (!overlays.isEmpty()) warnings.add("Additional archive candidates require content/identity classification before stock selection; no additional custom MPQ is required");
        Collections.sort(overlays); Collections.sort(archives);
        return new Report(requestedLocale, effective, locales, errors, warnings, overlays, archives);
    }

    private static boolean stockLocaleArchive(String name, String locale) {
        String lc = locale.toLowerCase(Locale.ROOT);
        for (String stem : Arrays.asList("locale-", "speech-", "expansion-locale-", "lichking-locale-", "expansion-speech-", "lichking-speech-", "patch-"))
            if (name.equals(stem + lc + ".mpq")) return true;
        return name.equals("patch-" + lc + "-2.mpq") || name.equals("patch-" + lc + "-3.mpq");
    }
    private static void inspectArchive(Path file, String relative, boolean required, List<String> errors, List<String> archives) throws IOException {
        if (file == null) { if (required) errors.add("Missing essential stock archive " + relative); return; }
        try {
            regular(file); GameDataVerifier.verifyMpq(file);
            archives.add(relative + "; bytes=" + Files.size(file) + "; header=passed");
        } catch (IOException failure) { errors.add(relative + ": " + failure.getMessage()); }
    }
    private static Map<String, Path> children(Path parent) throws IOException {
        Map<String, Path> result = new HashMap<>();
        try (DirectoryStream<Path> entries = Files.newDirectoryStream(parent)) {
            for (Path child : entries) {
                if (result.size() >= MAX_ENTRIES) throw new IOException("Compatibility inventory exceeds bounded directory entries");
                if (Files.isSymbolicLink(child)) throw new IOException("Linked client input refused: " + child.getFileName());
                String name = child.getFileName().toString().toLowerCase(Locale.ROOT);
                if (result.put(name, child) != null) throw new IOException("Case-colliding client path: " + child.getFileName());
            }
        }
        return result;
    }
    private static void regular(Path file) throws IOException {
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Expected regular archive/executable");
    }
    private static List<String> immutable(List<String> values) { return Collections.unmodifiableList(new ArrayList<>(values)); }
    private static boolean appendBounded(StringBuilder out, String line) {
        if (out.toString().getBytes(StandardCharsets.UTF_8).length + line.getBytes(StandardCharsets.UTF_8).length > 8096) return false;
        out.append(line); return true;
    }
}
