package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Comparator;

public final class LocalAccountHandoffTests {
    private static void writeText(Path path, String text) throws IOException { Files.write(path, text.getBytes(StandardCharsets.UTF_8)); }
    private static String readText(Path path) throws IOException { return new String(Files.readAllBytes(path), StandardCharsets.UTF_8); }
    private interface Checked { void run() throws Exception; }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void fails(Checked operation) throws Exception {
        try { operation.run(); throw new AssertionError("Expected refusal"); } catch (IOException expected) { }
    }
    public static void main(String[] args) throws Exception {
        Path root = args.length == 0 ? Files.createTempDirectory("esteria-handoff-") :
                Files.createTempDirectory(Paths.get(args[0]).toRealPath(), "esteria-handoff-");
        char[] username = "EST0123456789ABCD".toCharArray(), password = "ABCDEFGHJKLMNPQR".toCharArray();
        try {
            String generation = "a".repeat(64);
            writeText(root.resolve(".owner"), "esteria-client-launch-v1\n" + generation + "\n");
            Files.write(root.resolve("WowClient64.exe"), new byte[]{77, 90});
            Path saved = root.resolve("WTF"); Files.createDirectory(saved);
            writeText(saved.resolve("Config.wtf"), "preserve user settings");
            ClientLaunchView.Result view = new ClientLaunchView.Result(root, generation, 0, true, true);
            Path target = root.resolve(LocalAccountHandoff.FILENAME);
            LocalAccountHandoff first = LocalAccountHandoff.create(view, username, password);
            byte[] record = Files.readAllBytes(target);
            check(record.length == 57 && new String(record, 0, 8, StandardCharsets.US_ASCII).equals("ESTLOGN1"));
            check(new String(record, 24, 17, StandardCharsets.US_ASCII).equals(new String(username)));
            check(new String(record, 41, 16, StandardCharsets.US_ASCII).equals(new String(password)));
            check(Files.getPosixFilePermissions(target).equals(PosixFilePermissions.fromString("rw-------")));
            fails(() -> LocalAccountHandoff.create(view, username, password));
            check(Arrays.equals(record, Files.readAllBytes(target))); first.close(); first.close(); check(!Files.exists(target));
            LocalAccountHandoff consumed = LocalAccountHandoff.create(view, username, password);
            check(!Arrays.equals(record, Files.readAllBytes(target))); Files.delete(target); consumed.close();
            LocalAccountHandoff changed = LocalAccountHandoff.create(view, username, password);
            byte[] altered = Files.readAllBytes(target); altered[56] ^= 1; Files.write(target, altered);
            fails(changed::close); check(Arrays.equals(altered, Files.readAllBytes(target))); Files.delete(target);
            LocalAccountHandoff replaced = LocalAccountHandoff.create(view, username, password);
            Path original = root.resolve("retained-original"); Files.move(target, original);
            Files.copy(original, target); Files.setPosixFilePermissions(target, PosixFilePermissions.fromString("rw-------"));
            fails(replaced::close); check(Files.exists(target)); Files.delete(target); Files.delete(original);
            LocalAccountHandoff linked = LocalAccountHandoff.create(view, username, password);
            Path alias = root.resolve("alias"); Files.createLink(alias, target);
            fails(linked::close); check(Files.exists(alias)); Files.delete(alias); linked.close();
            Files.createSymbolicLink(target, saved.resolve("Config.wtf"));
            fails(() -> LocalAccountHandoff.create(view, username, password)); Files.delete(target);
            for (String boundary : new String[]{"created", "written", "synced"}) {
                fails(() -> LocalAccountHandoff.create(view, username, password, phase -> {
                    if (phase.equals(boundary)) throw new IOException("Injected construction failure");
                }));
                check(!Files.exists(target));
                try (LocalAccountHandoff retry = LocalAccountHandoff.create(view, username, password)) { check(Files.size(target) == 57); }
            }
            fails(() -> LocalAccountHandoff.create(view, username, password, phase -> {
                if (phase.equals("written")) { writeText(target, "foreign replacement"); throw new IOException("Injected changed-file failure"); }
            }));
            check(readText(target).equals("foreign replacement")); Files.delete(target);
            fails(() -> LocalAccountHandoff.create(view, "EST0123456789ABCG".toCharArray(), password));
            fails(() -> LocalAccountHandoff.create(view, username, "invalid password".toCharArray()));
            check(!Files.exists(target));
            writeText(root.resolve(".owner"), "foreign owner\n");
            fails(() -> LocalAccountHandoff.create(view, username, password));
            check(readText(saved.resolve("Config.wtf")).equals("preserve user settings"));
            Arrays.fill(record, (byte) 0); Arrays.fill(altered, (byte) 0);
            System.out.println("PASS handoff wire format, exclusive creation, random nonce, private mode, consumed cleanup, changed/replaced/linked preservation, validation and saved settings");
        } finally {
            Arrays.fill(username, '\0'); Arrays.fill(password, '\0');
            try (var paths = Files.walk(root)) { for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path); }
        }
    }
}
