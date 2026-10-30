package io.github.russianranger.esteria.core.diagnostics;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

public final class SupportBundleTest {
    public static void main(String[] args) throws Exception {
        Path log = Files.createTempFile("esteria-diag-", ".log");
        StringBuilder lines = new StringBuilder(); for (int i = 0; i < 10000; i++) lines.append("example line\n");
        lines.append("password=hidden-secret\nAuthorization: Bearer abc123\naccount=PLAYER\n");
        lines.append("LoginDatabaseInfo = \"127.0.0.1;13306;esteria;db-hidden;acore_auth\"\n");
        lines.append("{\"password\":\"json-hidden\"}\nmysql://user:uri-hidden@127.0.0.1/example\nBearer auth-hidden\n");
        Files.write(log, lines.toString().getBytes(StandardCharsets.UTF_8));
        Map<String, String> facts = new LinkedHashMap<>(); facts.put("version", "test-1"); facts.put("state", "FAILED");
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        SupportBundle.write(output, facts, Collections.singletonMap("world.log", log));
        int count = 0;
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(output.toByteArray()))) {
            for (ZipEntry entry; (entry = zip.getNextEntry()) != null;) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
                for (int n; (n = zip.read(buffer)) != -1;) bytes.write(buffer, 0, n);
                String value = new String(bytes.toByteArray(), StandardCharsets.UTF_8);
                if (value.contains("hidden-secret") || value.contains("abc123") || value.contains("PLAYER") || value.contains("db-hidden") || value.contains("json-hidden") || value.contains("uri-hidden") || value.contains("auth-hidden")) throw new AssertionError("secret leaked");
                if (entry.getName().equals("logs/world.log") && bytes.size() > SupportBundle.MAX_LOG_BYTES + 200) throw new AssertionError("log bound exceeded");
                count++;
            }
        }
        if (count != 2) throw new AssertionError("missing diagnostics");
        try {
            SupportBundle.write(new ByteArrayOutputStream(), facts, Collections.singletonMap("../secrets.log", log));
            throw new AssertionError("unsafe entry accepted");
        } catch (IOException expected) { }
        StringBuilder partialSecret = new StringBuilder("password=");
        for (int i = 0; i < SupportBundle.MAX_LOG_BYTES + 100; i++) partialSecret.append('s');
        partialSecret.append("\nsafe remainder\n");
        Files.write(log, partialSecret.toString().getBytes(StandardCharsets.UTF_8));
        ByteArrayOutputStream partial = new ByteArrayOutputStream();
        SupportBundle.write(partial, facts, Collections.singletonMap("world.log", log));
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(partial.toByteArray()))) {
            for (ZipEntry entry; (entry = zip.getNextEntry()) != null;) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
                for (int n; (n = zip.read(buffer)) != -1;) bytes.write(buffer, 0, n);
                if (entry.getName().equals("logs/world.log") && !new String(bytes.toByteArray(), StandardCharsets.UTF_8).equals("safe remainder\n"))
                    throw new AssertionError("partial credential line leaked");
            }
        }
        System.out.println("SupportBundle: bounded export, credential redaction and traversal tests passed");
    }
}
