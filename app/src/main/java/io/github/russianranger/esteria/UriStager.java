package io.github.russianranger.esteria;

import android.content.ContentResolver;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.OpenableColumns;
import java.io.IOException;
import java.io.InputStream;
import java.io.RandomAccessFile;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import io.github.russianranger.esteria.core.runtime.ExclusiveFileLease;
import java.nio.file.attribute.FileTime;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.atomic.AtomicBoolean;
import io.github.russianranger.esteria.core.importer.GameDataImporter;
import io.github.russianranger.esteria.core.importer.SourceStreamPositioner;
import io.github.russianranger.esteria.core.importer.ImportIoGovernor;

/** Turns a SAF document into a seekable ZIP without ever buffering the archive in RAM. */
final class UriStager {
    interface Progress { void update(long copied, long total); }
    private static final long RESERVE = 64L << 20;
    private static final long MAX_ARCHIVE_BYTES = 256L << 30;
    private static final class Info {
        long size = -1, modified = -1;
        boolean reliable() { return size >= 0 && modified > 0; }
        String fingerprint() { return size + ":" + modified; }
    }
    static Path stage(ContentResolver resolver, Uri uri, Path directory, AtomicBoolean cancelled, Progress progress) throws Exception {
        return stage(resolver, uri, directory, cancelled, progress, ImportIoGovernor.unthrottled(), null);
    }
    static Path stage(ContentResolver resolver, Uri uri, Path directory, AtomicBoolean cancelled, Progress progress,
                      ImportIoGovernor governor, ImportIoController controller) throws Exception {
        if (!"content".equals(uri.getScheme())) throw new IOException("Choose an archive through Android's file picker");
        Files.createDirectories(directory);
        try (ExclusiveFileLease lease = ExclusiveFileLease.acquire(directory.resolve("stage.lock"),"A previous archive copy is still stopping; retry in a moment")) {
            return stageLocked(resolver, uri, directory, cancelled, progress, governor, controller);
        }
    }
    private static Path stageLocked(ContentResolver resolver, Uri uri, Path directory, AtomicBoolean cancelled, Progress progress,
                                    ImportIoGovernor governor, ImportIoController controller) throws Exception {
        governor.checkpoint(cancelled::get);
        Info info = info(resolver, uri);
        if (info.size > MAX_ARCHIVE_BYTES) throw new IOException("Archive exceeds the 256 GiB import limit");
        String id = digest(uri.toString() + "\n" + info.fingerprint());
        Path archive = directory.resolve(id + ".zip"), partial = directory.resolve(id + ".partial");
        // Unknown modification time cannot establish that a cached source is unchanged.
        if (info.reliable() && Files.isRegularFile(archive) && Files.size(archive) == info.size) {
            Files.setLastModifiedTime(archive, FileTime.fromMillis(info.modified));
            return archive;
        }
        long offset = info.reliable() && Files.isRegularFile(partial) ? Files.size(partial) : 0;
        if (offset > info.size && info.size >= 0) offset = 0;
        long remaining = info.size >= 0 ? info.size - offset : RESERVE;
        if (directory.toFile().getUsableSpace() < remaining + RESERVE)
            throw new IOException("Not enough storage to stage this archive. A ZIP copy is needed before extraction.");
        try (android.content.res.AssetFileDescriptor descriptor = resolver.openAssetFileDescriptor(uri, "r");
             InputStream input = descriptor == null ? null : descriptor.createInputStream();
             RandomAccessFile output = new RandomAccessFile(partial.toFile(), "rw")) {
            if (input == null) throw new IOException("The selected document could not be opened");
            output.setLength(offset);
            SourceStreamPositioner.advance(input, offset, cancelled::get, governor);
            ImportIoController.SourceCache sourceCache = controller == null ? null : controller.sourceCache(descriptor.getParcelFileDescriptor(), descriptor.getStartOffset() + offset);
            output.seek(offset);
            ImportIoGovernor.Transfer transfer = governor.begin(partial, output.getChannel(), offset, cancelled::get);
            byte[] buffer = new byte[128 * 1024];
            long copied = offset, reportAt = 0;
            while (true) {
                governor.checkpoint(cancelled::get);
                int count = input.read(buffer); if (count == -1) break;
                if (cancelled.get()) throw new GameDataImporter.ImportCancelledException();
                copied += count;
                if (copied > MAX_ARCHIVE_BYTES || (info.size >= 0 && copied > info.size)) throw new IOException("Archive changed size during import");
                output.write(buffer, 0, count);
                transfer.wrote(count);
                if (sourceCache != null) sourceCache.consumed(count);
                long now = System.nanoTime();
                if (now - reportAt >= 200_000_000L) { progress.update(copied, info.size); reportAt = now; }
            }
            if (info.size >= 0 && copied != info.size) throw new IOException("The archive is truncated or changed during copying");
            Info after = info(resolver, uri);
            if (info.reliable() && !info.fingerprint().equals(after.fingerprint())) throw new IOException("Archive metadata changed during import");
            if (cancelled.get()) throw new GameDataImporter.ImportCancelledException();
            transfer.finish();
            if (sourceCache != null) sourceCache.finish();
        }
        Files.move(partial, archive, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        // Preserve provider identity across staging cleanup/reimport; otherwise a fresh local
        // copy time would make the importer treat an unchanged ZIP as a different generation.
        if (info.reliable()) Files.setLastModifiedTime(archive, FileTime.fromMillis(info.modified));
        return archive;
    }
    private static Info info(ContentResolver resolver, Uri uri) {
        Info result = new Info();
        try (Cursor cursor = resolver.query(uri, new String[]{OpenableColumns.SIZE, DocumentsContract.Document.COLUMN_LAST_MODIFIED}, null, null, null)) {
            if (cursor != null && cursor.moveToFirst()) {
                int size = cursor.getColumnIndex(OpenableColumns.SIZE), modified = cursor.getColumnIndex(DocumentsContract.Document.COLUMN_LAST_MODIFIED);
                if (size >= 0 && !cursor.isNull(size)) result.size = cursor.getLong(size);
                if (modified >= 0 && !cursor.isNull(modified)) result.modified = cursor.getLong(modified);
            }
        } catch (RuntimeException ignored) { /* Unknown identity disables resume, not import. */ }
        return result;
    }
    private static String digest(String value) throws Exception {
        byte[] hash = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
        StringBuilder text = new StringBuilder(); for (byte b : hash) text.append(String.format(java.util.Locale.ROOT, "%02x", b & 255));
        return text.toString();
    }
}
