package io.github.russianranger.esteria.core.diagnostics;

import java.io.IOException;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/** Exports only explicitly supplied logs and public version/status facts, never database or config files. */
public final class SupportBundle {
    private SupportBundle() { }
    public static final int MAX_LOG_BYTES = 64 * 1024;
    public static final int MAX_LOG_FILES = 32;
    public static String redact(String value) {
        return value.replaceAll("(?im)([A-Za-z]*DatabaseInfo)([\"']?\\s*[=:]\\s*)([^\\r\\n]+)", "$1$2[redacted]")
                .replaceAll("(?im)(password|passwd|pwd|token|secret|authorization|cookie|account(?:name)?|username)([\"']?\\s*[=:]\\s*)([^\\r\\n]+)", "$1$2[redacted]")
                .replaceAll("(?i)(mysql|mariadb)://[^\\s@]+@", "$1://[redacted]@")
                .replaceAll("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+=*", "Bearer [redacted]");
    }
    public static void write(OutputStream destination, Map<String, String> facts, Map<String, Path> logs) throws IOException {
        if (facts.size() > 64 || logs.size() > MAX_LOG_FILES) throw new IOException("Support bundle entry limit exceeded");
        try (ZipOutputStream zip = new ZipOutputStream(destination, StandardCharsets.UTF_8)) {
            StringBuilder metadata = new StringBuilder("Esteria support bundle v1\nNo database or game data is included.\n");
            for (Map.Entry<String, String> fact : facts.entrySet()) {
                if (!fact.getKey().matches("[a-zA-Z0-9._-]{1,64}")) throw new IOException("Invalid diagnostic field");
                String value = fact.getValue() == null ? "" : fact.getValue();
                metadata.append(fact.getKey()).append('=').append(value.substring(0, Math.min(8192, value.length()))).append('\n');
            }
            entry(zip, "status.txt", redact(metadata.toString()));
            for (Map.Entry<String, Path> log : logs.entrySet()) {
                if (!log.getKey().matches("[a-zA-Z0-9._-]{1,80}\\.log")) throw new IOException("Invalid diagnostic log name");
                Path path = log.getValue();
                if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS)) continue;
                byte[] tail;
                boolean partialLine = false;
                try (RandomAccessFile input = new RandomAccessFile(path.toFile(), "r")) {
                    long size = input.length();
                    int count = (int) Math.min(size, MAX_LOG_BYTES);
                    long start = size - count;
                    if (start > 0) { input.seek(start - 1); partialLine = input.read() != '\n'; }
                    tail = new byte[count]; input.seek(start); input.readFully(tail);
                }
                int begin = 0;
                // The missing beginning may contain the credential key. Never export an
                // unclassifiable partial first line when taking a bounded log tail.
                if (partialLine) { while (begin < tail.length && tail[begin++] != '\n') { } }
                entry(zip, "logs/" + log.getKey(), redact(new String(tail, begin, tail.length - begin, StandardCharsets.UTF_8)));
            }
        }
    }
    private static void entry(ZipOutputStream zip, String path, String content) throws IOException {
        zip.putNextEntry(new ZipEntry(path)); zip.write(content.getBytes(StandardCharsets.UTF_8)); zip.closeEntry();
    }
}
