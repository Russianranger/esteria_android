package io.github.russianranger.esteria;

import android.content.ContentResolver;
import android.content.res.AssetFileDescriptor;
import android.database.Cursor;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.OperationCanceledException;
import android.provider.DocumentsContract;
import java.io.FilterInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import io.github.russianranger.esteria.core.importer.GameDataImporter;

/** Read-only document-tree adapter. It never resolves provider IDs to filesystem paths. */
final class SafTreeSource implements GameDataImporter.InputSource, AutoCloseable {
    interface Progress { void update(int files, int directories, boolean reliableFileTimes); }
    private static final int MAX_DOCUMENTS = 200_000;
    private static final int MAX_DEPTH = 32;
    private static final long MAX_FILE_BYTES = 32L << 30, MAX_TOTAL_BYTES = 256L << 30;
    private static final String[] PROJECTION = {
            DocumentsContract.Document.COLUMN_DOCUMENT_ID,
            DocumentsContract.Document.COLUMN_DISPLAY_NAME,
            DocumentsContract.Document.COLUMN_MIME_TYPE,
            DocumentsContract.Document.COLUMN_SIZE,
            DocumentsContract.Document.COLUMN_LAST_MODIFIED,
            DocumentsContract.Document.COLUMN_FLAGS
    };
    private static final class Document {
        final String id, name, mime;
        final long size, modified;
        final int flags;
        Document(String id, String name, String mime, long size, long modified, int flags) {
            this.id = id; this.name = name; this.mime = mime; this.size = size; this.modified = modified; this.flags = flags;
        }
        boolean directory() { return DocumentsContract.Document.MIME_TYPE_DIR.equals(mime); }
    }
    private static final class Directory {
        final Document document; final String path; final int depth;
        Directory(Document document, String path, int depth) { this.document = document; this.path = path; this.depth = depth; }
    }
    private final ContentResolver resolver;
    private final Uri tree;
    private final AtomicBoolean cancelled;
    private final CancellationSignal queryCancellation = new CancellationSignal();
    private final Progress progress;
    private final Map<String, Document> observed = new HashMap<>();
    private final List<Document> directories = new ArrayList<>();
    private final GameDataImporter.MetadataBudget metadataBudget = new GameDataImporter.MetadataBudget();
    private final Object streamLock = new Object();
    private InputStream activeStream;
    private GameDataImporter.Cancellation importerCancellation;
    private boolean inventoried, reliableFileTimes = true;
    private String selectedRootName;

    SafTreeSource(ContentResolver resolver, Uri tree, AtomicBoolean cancelled, Progress progress) throws IOException {
        if (tree == null || !"content".equals(tree.getScheme()) || !DocumentsContract.isTreeUri(tree))
            throw new IOException("Choose a folder through Android's folder picker");
        this.resolver = resolver; this.tree = tree; this.cancelled = cancelled; this.progress = progress;
    }
    @Override public String identity() { return "android-saf-tree-v1\n" + tree; }
    boolean hasReliableFileTimes() { return reliableFileTimes; }
    String selectedRootName() { return selectedRootName; }

    @Override public List<GameDataImporter.InputEntry> snapshot(GameDataImporter.Cancellation cancellation) throws IOException {
        if (inventoried) throw new IOException("A folder source can be inventoried only once");
        inventoried = true; importerCancellation = cancellation; checkCancelled();
        Document root = readDocument(DocumentsContract.getTreeDocumentId(tree));
        if (!root.directory()) throw new IOException("The selected document is not a folder");
        selectedRootName = root.name;
        progress.update(0, 1, reliableFileTimes);
        metadataBudget.add("", root.id, true);
        observe(root); directories.add(root);
        ArrayDeque<Directory> pending = new ArrayDeque<>(); pending.add(new Directory(root, "", 0));
        List<GameDataImporter.InputEntry> files = new ArrayList<>();
        long totalBytes = 0, reportedAt = 0;
        while (!pending.isEmpty()) {
            checkCancelled(); Directory directory = pending.removeLast();
            Uri children = DocumentsContract.buildChildDocumentsUriUsingTree(tree, directory.document.id);
            try (Cursor cursor = query(children)) {
                while (cursor.moveToNext()) {
                    checkCancelled();
                    Document child = fromCursor(cursor);
                    validateName(child.name);
                    int depth = directory.depth + 1;
                    String path = directory.path.isEmpty() ? child.name : directory.path + "/" + child.name;
                    if (depth > MAX_DEPTH || path.getBytes(StandardCharsets.UTF_8).length > 1024)
                        throw new IOException("The source folder contains a path that is too deep or too long");
                    metadataBudget.add(path, child.id, child.directory());
                    observe(child); // Reject repeated IDs, including ancestor cycles and aliases.
                    if (child.directory()) {
                        directories.add(child); pending.add(new Directory(child, path, depth));
                    } else {
                        if (child.size < 0) throw new IOException("The file provider cannot report the size of " + path + ". Copy this client to local storage before importing.");
                        if (child.size > MAX_FILE_BYTES || totalBytes > MAX_TOTAL_BYTES - child.size)
                            throw new IOException("The source exceeds the import size limits");
                        totalBytes += child.size;
                        if (child.modified <= 0) reliableFileTimes = false;
                        files.add(new GameDataImporter.InputEntry(child.id, path, child.size, child.modified));
                    }
                    long now = System.nanoTime();
                    if (now - reportedAt >= 200_000_000L) { progress.update(files.size(), directories.size(), reliableFileTimes); reportedAt = now; }
                }
            } catch (OperationCanceledException e) { throw new GameDataImporter.ImportCancelledException(); }
            catch (GameDataImporter.ImportCancelledException e) { throw e; }
            catch (IOException e) { throw new IOException("Could not enumerate selected folder '" + selectedRootName
                    + "', relative directory '" + (directory.path.isEmpty() ? "." : directory.path) + "': " + e.getMessage(), e); }
            catch (RuntimeException e) { throw providerFailure("The file provider could not list relative directory '"
                    + (directory.path.isEmpty() ? "." : directory.path) + "' in selected folder '" + selectedRootName + "'", e); }
        }
        checkCancelled(); progress.update(files.size(), directories.size(), reliableFileTimes);
        return files;
    }

    @Override public InputStream open(GameDataImporter.InputEntry entry) throws IOException {
        checkCancelled(); Document document = known(entry);
        AssetFileDescriptor descriptor;
        try { descriptor = resolver.openAssetFileDescriptor(documentUri(document.id), "r", queryCancellation); }
        catch (OperationCanceledException e) { throw new GameDataImporter.ImportCancelledException(); }
        catch (IOException e) { throw new IOException("The file provider could not open relative path '" + entry.relativePath
                + "' in selected folder '" + selectedRootName + "': " + e.getMessage(), e); }
        catch (RuntimeException e) { throw providerFailure("The file provider could not open " + entry.relativePath, e); }
        if (descriptor == null) throw new IOException("The file provider could not open " + entry.relativePath);
        final InputStream input;
        try { input = descriptor.createInputStream(); }
        catch (IOException | RuntimeException failure) { descriptor.close(); throw failure; }
        FilterInputStream tracked = new FilterInputStream(input) {
            @Override public void close() throws IOException {
                try { super.close(); }
                finally {
                    try { descriptor.close(); }
                    finally { synchronized (streamLock) { if (activeStream == this) activeStream = null; } }
                }
            }
        };
        synchronized (streamLock) {
            if (cancelled.get() || queryCancellation.isCanceled()) { tracked.close(); throw new GameDataImporter.ImportCancelledException(); }
            if (activeStream != null) { tracked.close(); throw new IOException("Concurrent source streams are not supported"); }
            activeStream = tracked;
        }
        return tracked;
    }

    @Override public void verifyUnchanged(GameDataImporter.InputEntry entry) throws IOException {
        checkCancelled();
        try { verify(known(entry)); }
        catch (GameDataImporter.ImportCancelledException cancelled) { throw cancelled; }
        catch (IOException changed) { throw new IOException("Source verification failed at relative path '" + entry.relativePath
                + "' in selected folder '" + selectedRootName + "': " + changed.getMessage(), changed); }
    }
    @Override public void verifySnapshot(List<GameDataImporter.InputEntry> snapshot) throws IOException {
        // No second tree enumeration or rehashing: check the inventoried directory metadata.
        // The shared importer separately checks every original file's metadata before publishing.
        for (Document directory : directories) { checkCancelled(); verify(directory); }
    }
    private void verify(Document expected) throws IOException {
        Document actual = readDocument(expected.id);
        if (!actual.id.equals(expected.id) || !actual.name.equals(expected.name) || !actual.mime.equals(expected.mime)
                || (!actual.directory() && actual.size != expected.size)
                || (expected.modified > 0 && actual.modified != expected.modified))
            throw new IOException("The source changed during import. Keep the selected folder unchanged and retry.");
    }
    private Document known(GameDataImporter.InputEntry entry) throws IOException {
        Document document = observed.get(entry.id);
        if (document == null || document.directory() || document.size != entry.size || document.modified != entry.modifiedMillis)
            throw new IOException("Unknown source document");
        return document;
    }
    private void observe(Document document) throws IOException {
        if (observed.size() >= MAX_DOCUMENTS) throw new IOException("The selected folder contains too many documents (maximum 200,000)");
        if (observed.put(document.id, document) != null) throw new IOException("The file provider returned a repeated document or folder cycle");
    }
    private Document readDocument(String id) throws IOException {
        checkCancelled();
        try (Cursor cursor = query(documentUri(id))) {
            if (!cursor.moveToFirst()) throw new IOException("A source document was removed or is no longer readable");
            Document result = fromCursor(cursor);
            if (!id.equals(result.id) || cursor.moveToNext()) throw new IOException("The file provider returned inconsistent document metadata");
            return result;
        } catch (OperationCanceledException e) { throw new GameDataImporter.ImportCancelledException(); }
        catch (RuntimeException e) { throw providerFailure("The file provider could not verify source metadata", e); }
    }
    private Cursor query(Uri uri) throws IOException {
        checkCancelled();
        try {
            Cursor cursor = resolver.query(uri, PROJECTION, null, null, null, queryCancellation);
            if (cursor == null) throw new IOException("The file provider returned no metadata");
            return cursor;
        } catch (OperationCanceledException e) { throw new GameDataImporter.ImportCancelledException(); }
        catch (RuntimeException e) { throw providerFailure("The file provider denied access to the selected folder", e); }
    }
    private static Document fromCursor(Cursor cursor) throws IOException {
        String id = requiredString(cursor, DocumentsContract.Document.COLUMN_DOCUMENT_ID);
        String name = requiredString(cursor, DocumentsContract.Document.COLUMN_DISPLAY_NAME);
        String mime = requiredString(cursor, DocumentsContract.Document.COLUMN_MIME_TYPE);
        if (id.getBytes(StandardCharsets.UTF_8).length > 4096) throw new IOException("The file provider returned an oversized document identity");
        if (name.getBytes(StandardCharsets.UTF_8).length > 1024 || mime.getBytes(StandardCharsets.UTF_8).length > 256)
            throw new IOException("The file provider returned oversized document metadata");
        if ("inode/symlink".equals(mime) || "application/x-symlink".equals(mime))
            throw new IOException("The source contains a provider-reported symbolic link. Choose the actual files instead.");
        int flagsIndex = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_FLAGS);
        if (flagsIndex < 0 || cursor.isNull(flagsIndex)) throw new IOException("The file provider cannot report document capabilities");
        int flags = cursor.getInt(flagsIndex);
        if ((flags & DocumentsContract.Document.FLAG_VIRTUAL_DOCUMENT) != 0)
            throw new IOException("Virtual documents cannot be imported. Copy the actual files to local storage first.");
        int sizeIndex = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_SIZE);
        int timeIndex = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_LAST_MODIFIED);
        long size = sizeIndex >= 0 && !cursor.isNull(sizeIndex) ? cursor.getLong(sizeIndex) : -1;
        long modified = timeIndex >= 0 && !cursor.isNull(timeIndex) ? cursor.getLong(timeIndex) : -1;
        return new Document(id, name, mime, size, modified, flags);
    }
    private static String requiredString(Cursor cursor, String column) throws IOException {
        int index = cursor.getColumnIndex(column);
        if (index < 0 || cursor.isNull(index)) throw new IOException("The file provider returned incomplete document metadata");
        String value = cursor.getString(index);
        if (value.isEmpty()) throw new IOException("The file provider returned empty document metadata");
        return value;
    }
    private static void validateName(String name) throws IOException {
        if (name.equals(".") || name.equals("..") || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0
                || name.indexOf(':') >= 0 || name.endsWith(".") || name.endsWith(" "))
            throw new IOException("The selected folder contains an unsafe filename");
        for (int i = 0; i < name.length(); i++) if (name.charAt(i) < 32 || name.charAt(i) == 127)
            throw new IOException("The selected folder contains a control character in a filename");
    }
    private Uri documentUri(String id) { return DocumentsContract.buildDocumentUriUsingTree(tree, id); }
    private IOException providerFailure(String message, RuntimeException failure) {
        if (cancelled.get() || queryCancellation.isCanceled()) return new GameDataImporter.ImportCancelledException();
        return new IOException(message + " (" + failure.getClass().getSimpleName() + ")", failure);
    }
    private void checkCancelled() throws GameDataImporter.ImportCancelledException {
        if (cancelled.get() || queryCancellation.isCanceled() || Thread.currentThread().isInterrupted()
                || (importerCancellation != null && importerCancellation.isCancelled())) throw new GameDataImporter.ImportCancelledException();
    }
    void cancel() {
        queryCancellation.cancel();
        InputStream input;
        synchronized (streamLock) { input = activeStream; }
        if (input != null) try { input.close(); } catch (IOException ignored) { }
    }
    @Override public void close() { cancel(); }
}
