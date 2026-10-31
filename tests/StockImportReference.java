import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.StockClientCompatibility;
import io.github.russianranger.esteria.core.importer.StockClientSelection;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/** Cross-language host fixture: real public importer/selection, no Android or gameplay claim. */
public final class StockImportReference {
    public static void main(String[] args) throws Exception {
        if (args.length < 3) throw new IllegalArgumentException("route store source [exclusions reportSha256]");
        String route = args[0];
        GameDataImporter importer = new GameDataImporter(Path.of(args[1]));
        Path source = Path.of(args[2]).toRealPath(), result;
        if (route.equals("folder")) {
            result = importer.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT,
                    GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED).gameDirectory;
        } else if (route.equals("zip")) {
            result = importer.importZip(source, GameDataImporter.ImportKind.BASE_CLIENT,
                    GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED).gameDirectory;
        } else if (route.equals("select") && args.length == 5) {
            Path decisions = Path.of(args[3]);
            if (Files.size(decisions) > 8 << 20) throw new IllegalArgumentException("fixture exclusion bound");
            Map<String, String> excluded = new LinkedHashMap<>();
            for (String line : Files.readAllLines(decisions, StandardCharsets.UTF_8)) {
                String[] fields = line.split("\t", -1);
                if (fields.length != 2 || !fields[1].matches("[0-9a-f]{64}"))
                    throw new IllegalArgumentException("fixture exclusion record");
                String name = new String(Base64.getDecoder().decode(fields[0]), StandardCharsets.UTF_8);
                if (excluded.put(name, fields[1]) != null || excluded.size() > 4096)
                    throw new IllegalArgumentException("fixture exclusion inventory");
            }
            result = StockClientSelection.apply(importer, source, source.getParent().getFileName().toString(),
                    excluded, args[4], GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
        } else throw new IllegalArgumentException("unknown fixture route: " + route);
        StockClientCompatibility.inspect(result, "enUS").requirePreparationInputs();
        if (!result.equals(importer.resolveCurrent())) throw new AssertionError("result is not active");
        System.out.println(result);
    }
}
