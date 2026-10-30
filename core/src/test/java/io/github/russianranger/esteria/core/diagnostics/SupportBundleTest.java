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
        lines.append("session_key=srp-key-hidden\n{\"sessionKey\":\"camel-key-hidden\"}\nsaltHex=salt-hidden\nverifierHex=verifier-hidden\n");
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
                for(String secret:new String[]{"srp-key-hidden","camel-key-hidden","salt-hidden","verifier-hidden"})
                    if(value.contains(secret))throw new AssertionError("SRP credential leaked");
                if (entry.getName().equals("logs/world.log") && bytes.size() > SupportBundle.MAX_LOG_BYTES + 200) throw new AssertionError("log bound exceeded");
                count++;
            }
        }
        if (count != 2) throw new AssertionError("missing diagnostics");
        String[] accountMessages={"Account 'PRIVATE_ACCOUNT' has invalid credentials", "Banned account PRIVATE_ACCOUNT tried to login!",
            "account PRIVATE_ACCOUNT is using 'enUS' locale", "User 'PRIVATE_ACCOUNT' successfully authenticated",
            "account PRIVATE_ACCOUNT tried to login with invalid password!", "account PRIVATE_ACCOUNT got banned after failed logins",
            "because account PRIVATE_ACCOUNT failed to authenticate", "[ERROR] user PRIVATE_ACCOUNT tried to login, but session is invalid.",
            "Client 'PRIVATE_ACCOUNT' authenticated successfully from 127.0.0.1", "Authentication failed for account: 1 ('PRIVATE_ACCOUNT') address: 127.0.0.1",
            "SQL(p): INSERT INTO account(username, salt, verifier, email) VALUES(PRIVATE_ACCOUNT, BINARY, BINARY, PRIVATE_EMAIL)",
            "SQL(p): UPDATE account SET session_key=BINARY WHERE username='PRIVATE_ACCOUNT'"};
        for(String message:accountMessages){String redacted=SupportBundle.redact(message+"\n[ERROR] Reason retained\n");
            if(redacted.contains("PRIVATE_ACCOUNT")||redacted.contains("PRIVATE_EMAIL")||!redacted.endsWith("[ERROR] Reason retained\n"))
                throw new AssertionError("source-format account/SQL redaction failed");}
        if(!SupportBundle.redact("Local server startup failed: missing maps\nSQL(p): SELECT id FROM version\n").equals(
            "Local server startup failed: missing maps\nSQL(p): SELECT id FROM version\n"))throw new AssertionError("unrelated failure detail removed");
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
        // The integrated app emits more than 64 fields once all provider and
        // performance facts are present. Every retained field must reach export.
        Map<String, String> complete = new LinkedHashMap<>();
        for (int i = 0; i < SupportBundle.MAX_FACTS; i++) complete.put("component.fact" + i, "verified-value-" + i);
        ByteArrayOutputStream large = new ByteArrayOutputStream();
        SupportBundle.write(large, complete, Collections.emptyMap());
        String metadata = readMetadata(large);
        for (Map.Entry<String, String> fact : complete.entrySet())
            if (!metadata.contains(fact.getKey() + "=" + fact.getValue() + "\n"))
                throw new AssertionError("complete provider metadata was lost");
        complete.put("one.too.many", "refuse");
        rejectedBeforeOutput(complete);
        complete.clear();
        StringBuilder wide = new StringBuilder(); for (int i = 0; i < 6000; i++) wide.append('\u4e16');
        for (int i = 0; i < 15; i++) complete.put("unicode" + i, wide.toString());
        rejectedBeforeOutput(complete); // 90,000 characters exceed 256 KiB in UTF-8.
        complete.clear();
        StringBuilder ascii = new StringBuilder(); for (int i = 0; i < 8192; i++) ascii.append('x');
        for (int i = 0; i < 33; i++) complete.put("large" + i, ascii.toString());
        rejectedBeforeOutput(complete);
        System.out.println("SupportBundle: complete provider metadata, UTF-8 bounds, credential redaction and traversal tests passed");
    }
    private static String readMetadata(ByteArrayOutputStream output) throws IOException {
        try (ZipInputStream zip = new ZipInputStream(new ByteArrayInputStream(output.toByteArray()))) {
            ZipEntry entry = zip.getNextEntry();
            if (entry == null || !"status.txt".equals(entry.getName())) throw new AssertionError("missing metadata");
            ByteArrayOutputStream data = new ByteArrayOutputStream(); byte[] buffer = new byte[8192];
            for (int n; (n = zip.read(buffer)) != -1;) data.write(buffer, 0, n);
            if (data.size() > SupportBundle.MAX_METADATA_BYTES) throw new AssertionError("metadata byte bound exceeded");
            return new String(data.toByteArray(), StandardCharsets.UTF_8);
        }
    }
    private static void rejectedBeforeOutput(Map<String, String> facts) throws IOException {
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        try {
            SupportBundle.write(output, facts, Collections.emptyMap());
            throw new AssertionError("over-limit diagnostic metadata accepted");
        } catch (IOException expected) {
            if (output.size() != 0) throw new AssertionError("invalid metadata wrote a partial archive");
        }
    }
}
