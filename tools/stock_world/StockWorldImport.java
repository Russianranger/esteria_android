import io.github.russianranger.esteria.core.importer.GameDataImporter;
import java.nio.file.Files;
import java.nio.file.Path;

/** Exercises the public stock import API on a private, disposable Linux runner. */
public final class StockWorldImport {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Expected source and private import store");
        Path source = Path.of(args[0]).toRealPath();
        GameDataImporter importer = new GameDataImporter(Path.of(args[1]).toRealPath());
        GameDataImporter.Result result = Files.isDirectory(source)
            ? importer.importFolder(source, GameDataImporter.ImportKind.BASE_CLIENT,
                GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED)
            : importer.importZip(source, GameDataImporter.ImportKind.BASE_CLIENT,
                GameDataImporter.NO_PROGRESS, GameDataImporter.NEVER_CANCELLED);
        System.out.println("Imported build 12340; generation=" + result.generation +
            " copiedBytes=" + result.copiedBytes + " reusedFiles=" + result.reusedFiles);
    }
}
