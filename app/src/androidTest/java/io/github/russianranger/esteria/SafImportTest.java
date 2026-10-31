package io.github.russianranger.esteria;

import android.content.ContentProvider;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.MatrixCursor;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.content.res.AssetFileDescriptor;
import android.provider.DocumentsContract;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.StockClientCompatibility;
import io.github.russianranger.esteria.core.diagnostics.SupportBundle;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** Real Android URI/resolver/stream and importer components, using tiny synthetic PE/MPQ headers.
 * The in-process provider is a controlled fixture, not the owner's document provider or game data. */
@RunWith(AndroidJUnit4.class)
public final class SafImportTest {
    private static Path temporary() throws IOException {
        return Files.createTempDirectory(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir().toPath(), "saf-import-").toRealPath();
    }
    private static void remove(Path root) throws IOException {
        try (var paths = Files.walk(root)) { for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path); }
    }
    interface Action { void run() throws Exception; }
    private static IOException refuses(Action action) throws Exception {
        try { action.run(); } catch (IOException expected) { return expected; }
        throw new AssertionError("Expected import failure");
    }
    @Test public void opaqueFolderDocumentsAndStagedZipUseTheSameClientRoot() throws Exception {
        Path root = temporary();
        try {
            Map<String, byte[]> payload = new LinkedHashMap<>();
            payload.put("README.txt", "client bundle".getBytes(StandardCharsets.UTF_8));
            payload.put("__MACOSX/._ignored", new byte[]{1});
            payload.put("ChromieCraft/Wow.exe", pe());
            for (String name : List.of("common", "common-2", "expansion", "lichking", "patch", "patch-2", "patch-3"))
                payload.put("ChromieCraft/Data/" + name + ".MPQ", mpq());
            payload.put("ChromieCraft/Data/enUS/locale-enUS.MPQ", mpq());
            payload.put("ChromieCraft/Data/enUS/speech-enUS.MPQ", mpq());
            payload.put("ChromieCraft/Data/Interface.MpQ", "inactive ancillary archive".getBytes(StandardCharsets.UTF_8));
            Provider fixture = new Provider(root.resolve("provider"), payload);
            ContentResolver resolver = ContentResolver.wrap(fixture);
            AtomicBoolean cancel = new AtomicBoolean();
            GameDataImporter.Result folder;
            try (SafTreeSource source = new SafTreeSource(resolver, fixture.tree(), cancel, (f, d, t) -> {})) {
                folder = new GameDataImporter(root.resolve("folder-store")).importSource(source,
                        GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, cancel::get);
                assertEquals("Selected source container", source.selectedRootName());
            }
            byte[] zipBytes;
            try (ByteArrayOutputStream bytes = new ByteArrayOutputStream(); ZipOutputStream zip = new ZipOutputStream(bytes)) {
                for (var entry : payload.entrySet()) { zip.putNextEntry(new ZipEntry(entry.getKey())); zip.write(entry.getValue()); zip.closeEntry(); }
                zip.finish(); zipBytes = bytes.toByteArray();
            }
            fixture.archive(zipBytes);
            Path staged = UriStager.stage(resolver, fixture.archiveUri(), root.resolve("zip-stage"), cancel, (n, total) -> {});
            GameDataImporter.Result zipped = new GameDataImporter(root.resolve("zip-store")).importZip(staged,
                    GameDataImporter.ImportKind.BASE_CLIENT, GameDataImporter.NO_PROGRESS, cancel::get);
            try (var paths = Files.walk(folder.gameDirectory)) {
                for (Path path : (Iterable<Path>) paths.filter(Files::isRegularFile)::iterator) {
                    Path relative = folder.gameDirectory.relativize(path);
                    assertArrayEquals(relative.toString(), Files.readAllBytes(path), Files.readAllBytes(zipped.gameDirectory.resolve(relative)));
                }
            }
            assertTrue(Files.isRegularFile(folder.gameDirectory.resolve("Wow.exe")));
            assertTrue(Files.isRegularFile(folder.gameDirectory.resolve("Data/Interface.MpQ")));
            assertFalse(Files.exists(folder.gameDirectory.resolve("ChromieCraft")));
            StockClientCompatibility.inspect(folder.gameDirectory, "enUS").requirePreparationInputs();
            StockClientCompatibility.inspect(zipped.gameDirectory, "enUS").requirePreparationInputs();
            assertEquals("Provider is traversed once, not re-enumerated at promotion", fixture.directoryCount(), fixture.childQueries);
        } finally { remove(root); }
    }
    @Test public void providerMutationDenialAndCancellationKeepTheirCausalDetails() throws Exception {
        Path root = temporary();
        try {
            Provider fixture = new Provider(root.resolve("provider"), Map.of("Data/common.MPQ", mpq()));
            AtomicBoolean cancel = new AtomicBoolean();
            try (SafTreeSource source = new SafTreeSource(ContentResolver.wrap(fixture), fixture.tree(), cancel, (f, d, t) -> {})) {
                List<GameDataImporter.InputEntry> entries = source.snapshot(cancel::get);
                GameDataImporter.InputEntry entry = entries.get(0);
                assertEquals("Data/common.MPQ", entry.relativePath);
                assertFalse("Opaque document ID deliberately differs from its filename", entry.id.contains("common"));
                fixture.records.get(entry.id).modified++;
                assertTrue(refuses(() -> source.verifyUnchanged(entry)).getMessage().contains("Data/common.MPQ"));
                fixture.records.get(entry.id).modified--;
                fixture.denyOpen = true;
                IOException denial = refuses(() -> source.open(entry));
                assertTrue(denial.getMessage().contains("Data/common.MPQ"));
                assertTrue(ImportDiagnostics.failure(denial).contains("SecurityException"));
                source.cancel();
                assertTrue(refuses(() -> source.open(entry)) instanceof GameDataImporter.ImportCancelledException);
            }
        } finally { remove(root); }
    }
    @Test public void failedImportReceiptSurvivesRecreationAndExportsBoundedRedactedCauses() throws Exception {
        Path root = temporary();
        try {
            Path receipt = root.resolve("state/import-last.properties");
            ImportDiagnostics diagnostics = new ImportDiagnostics(receipt);
            String source = "content://fixture/tree/opaque-user-document-id";
            diagnostics.begin("folder", "BASE_CLIENT", "fixture", source, "ChromieCraft");
            diagnostics.phase("layout-validation", ".", "Data/Interface.MPQ");
            IOException failure = new IOException("observed Data/Interface.MPQ", new SecurityException("password=private-test-value"));
            failure.addSuppressed(new IOException("provider cleanup failed"));
            diagnostics.finish("failed", failure);
            ImportDiagnostics retained = new ImportDiagnostics(receipt);
            Map<String, String> facts = retained.facts();
            assertEquals("folder", facts.get("import.last.route"));
            assertEquals(".", facts.get("import.last.detectedRoot"));
            assertEquals("layout-validation", facts.get("import.last.phase"));
            assertEquals("Data/Interface.MPQ", facts.get("import.last.path"));
            assertEquals("failed", facts.get("import.last.result"));
            assertTrue(facts.get("import.last.sourceIdentitySha256").matches("[0-9a-f]{64}"));
            String saved = new String(Files.readAllBytes(receipt), StandardCharsets.UTF_8);
            assertFalse(saved.contains(source)); assertFalse(saved.contains("private-test-value"));
            assertTrue(facts.get("import.last.failure").contains("caused-by=java.lang.SecurityException"));
            assertTrue(facts.get("import.last.failure").contains("suppressed=java.io.IOException"));
            ByteArrayOutputStream bundle = new ByteArrayOutputStream(); SupportBundle.write(bundle, facts, Map.of());
            assertTrue(bundle.size() > 0);
            IOException cycle = new IOException("cycle"); IOException outer = new IOException("outer", cycle); cycle.initCause(outer);
            assertTrue(ImportDiagnostics.failure(outer).contains("exception cycle"));
        } finally { remove(root); }
    }

    private static byte[] mpq() {
        ByteBuffer b = ByteBuffer.allocate(64).order(ByteOrder.LITTLE_ENDIAN);
        b.putInt(0, 0x1a51504d); b.putInt(4, 32); b.putInt(8, 64); b.putShort(14, (short) 3);
        b.putInt(16, 32); b.putInt(20, 48); b.putInt(24, 1); b.putInt(28, 1); return b.array();
    }
    private static byte[] pe() {
        ByteBuffer b = ByteBuffer.allocate(1024).order(ByteOrder.LITTLE_ENDIAN);
        b.putShort(0, (short) 0x5a4d); b.putInt(0x3c, 0x80); b.putInt(0x80, 0x4550);
        b.putShort(0x84, (short) 0x14c); b.putShort(0x86, (short) 1); b.putShort(0x94, (short) 224);
        int optional = 0x98; b.putShort(optional, (short) 0x10b); b.putInt(optional + 92, 16);
        b.putInt(optional + 112, 0x1000); b.putInt(optional + 116, 512);
        int section = optional + 224; b.putInt(section + 8, 512); b.putInt(section + 12, 0x1000); b.putInt(section + 16, 512); b.putInt(section + 20, 512);
        int res = 512;
        b.putShort(res + 14, (short) 1); b.putInt(res + 16, 16); b.putInt(res + 20, 0x80000020);
        b.putShort(res + 46, (short) 1); b.putInt(res + 48, 1); b.putInt(res + 52, 0x80000040);
        b.putShort(res + 78, (short) 1); b.putInt(res + 80, 1033); b.putInt(res + 84, 96);
        b.putInt(res + 96, 0x1080); b.putInt(res + 100, 92);
        int data = res + 128; b.putShort(data, (short) 92); b.putShort(data + 2, (short) 52);
        String key = "VS_VERSION_INFO"; for (int i = 0; i < key.length(); i++) b.putChar(data + 6 + i * 2, key.charAt(i));
        b.putInt(data + 40, 0xfeef04bd); b.putInt(data + 44, 0x10000); b.putInt(data + 48, 0x30003); b.putInt(data + 52, (5 << 16) | 12340);
        return b.array();
    }
    private static final class Record {
        final String id, path, name; final boolean directory; final Path bytes;
        long modified = 1700000000000L;
        Record(String id, String path, boolean directory, Path bytes) {
            this.id = id; this.path = path; this.directory = directory; this.bytes = bytes;
            name = path.isEmpty() ? "Selected source container" : path.substring(path.lastIndexOf('/') + 1);
        }
    }
    private static final class Provider extends ContentProvider {
        static final String AUTHORITY = "esteria.fixture.documents";
        final Path root;
        final Map<String, Record> records = new LinkedHashMap<>();
        final Map<String, Record> paths = new LinkedHashMap<>();
        Record archive; int childQueries; boolean denyOpen;
        Provider(Path root, Map<String, byte[]> payload) throws IOException {
            this.root = Files.createDirectory(root); add("", true, null);
            for (var entry : payload.entrySet()) {
                String path = entry.getKey(); int slash = path.indexOf('/');
                while (slash >= 0) { String parent = path.substring(0, slash); if (!paths.containsKey(parent)) add(parent, true, null); slash = path.indexOf('/', slash + 1); }
                Path bytes = root.resolve("file-" + records.size()); Files.write(bytes, entry.getValue()); add(path, false, bytes);
            }
            android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
            android.content.pm.ProviderInfo info = new android.content.pm.ProviderInfo();
            info.authority = AUTHORITY; info.exported = false; info.applicationInfo = context.getApplicationInfo();
            attachInfo(context, info);
        }
        private Record add(String path, boolean directory, Path bytes) {
            Record record = new Record("opaque:" + records.size() + "/unrelated-id", path, directory, bytes);
            records.put(record.id, record); paths.put(path, record); return record;
        }
        int directoryCount() { return (int) records.values().stream().filter(record -> record.directory).count(); }
        Uri tree() { return DocumentsContract.buildTreeDocumentUri(AUTHORITY, paths.get("").id); }
        void archive(byte[] bytes) throws IOException { Path file = root.resolve("zip-document"); Files.write(file, bytes); archive = new Record("zip:id/with:separators", "client.zip", false, file); records.put(archive.id, archive); }
        Uri archiveUri() { return DocumentsContract.buildDocumentUri(AUTHORITY, archive.id); }
        @Override public boolean onCreate() { return true; }
        @Override public Cursor query(Uri uri, String[] projection, String selection, String[] args, String order) {
            String id = DocumentsContract.getDocumentId(uri);
            MatrixCursor cursor = new MatrixCursor(projection);
            if (uri.getLastPathSegment().equals("children")) {
                childQueries++; Record parent = records.get(id);
                for (Record child : records.values()) {
                    String parentPath = child.path.contains("/") ? child.path.substring(0, child.path.lastIndexOf('/')) : "";
                    if (!child.path.isEmpty() && parent.path.equals(parentPath)) row(cursor, child, projection);
                }
            } else if (records.containsKey(id)) row(cursor, records.get(id), projection);
            return cursor;
        }
        private void row(MatrixCursor cursor, Record record, String[] projection) {
            Object[] values = new Object[projection.length];
            for (int i = 0; i < projection.length; i++) {
                String key = projection[i];
                if (DocumentsContract.Document.COLUMN_DOCUMENT_ID.equals(key)) values[i] = record.id;
                else if (DocumentsContract.Document.COLUMN_DISPLAY_NAME.equals(key)) values[i] = record.name;
                else if (DocumentsContract.Document.COLUMN_MIME_TYPE.equals(key)) values[i] = record.directory ? DocumentsContract.Document.MIME_TYPE_DIR : "application/octet-stream";
                else if (DocumentsContract.Document.COLUMN_FLAGS.equals(key)) values[i] = 0;
                else if (DocumentsContract.Document.COLUMN_LAST_MODIFIED.equals(key)) values[i] = record.modified;
                else if (DocumentsContract.Document.COLUMN_SIZE.equals(key)) try { values[i] = record.directory ? 0 : Files.size(record.bytes); } catch (IOException e) { throw new IllegalStateException(e); }
            }
            cursor.addRow(values);
        }
        @Override public AssetFileDescriptor openAssetFile(Uri uri, String mode, CancellationSignal signal) throws java.io.FileNotFoundException {
            if (signal != null) signal.throwIfCanceled();
            return openAssetFile(uri, mode);
        }
        @Override public AssetFileDescriptor openAssetFile(Uri uri, String mode) throws java.io.FileNotFoundException {
            if (denyOpen) throw new SecurityException("Fixture document read denied");
            Record record = records.get(DocumentsContract.getDocumentId(uri));
            if (record == null || record.directory) throw new java.io.FileNotFoundException("No fixture document");
            return new AssetFileDescriptor(ParcelFileDescriptor.open(record.bytes.toFile(), ParcelFileDescriptor.MODE_READ_ONLY), 0, record.bytes.toFile().length());
        }
        @Override public String getType(Uri uri) { return "application/octet-stream"; }
        @Override public Uri insert(Uri uri, ContentValues values) { throw new UnsupportedOperationException(); }
        @Override public int delete(Uri uri, String where, String[] args) { throw new UnsupportedOperationException(); }
        @Override public int update(Uri uri, ContentValues values, String where, String[] args) { throw new UnsupportedOperationException(); }
    }
}
