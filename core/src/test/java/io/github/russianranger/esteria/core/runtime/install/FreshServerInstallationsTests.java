package io.github.russianranger.esteria.core.runtime.install;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.Comparator;
import java.util.Map;
import java.util.TreeMap;

/** Real private filesystem transactions with clearly synthetic receipt contents.
 * These tests qualify storage/recovery only, never SQL, servers or gameplay. */
public final class FreshServerInstallationsTests {
    private interface Action {void run() throws Exception;}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    private static void rejects(Action action) throws Exception {
        try{action.run();throw new AssertionError("Operation must preserve/refuse this state");}catch(IOException expected){ }
    }
    private static FreshServerInstallations.Selection selection(String suffix) throws IOException {
        return new FreshServerInstallations.Selection(Map.of("sourceLock","a".repeat(63)+suffix,"runtimeArchive","b".repeat(64),
            "programsArchive","c".repeat(64),"contentReceipt","d".repeat(64),"compiledModules","e".repeat(64)));
    }
    private static Map<String,Boolean> flags() {
        Map<String,Boolean> flags=new TreeMap<>();for(String name:new String[]{"baselineComplete","compiledUpdaterComplete",
            "coreLedgersVerified","sameRevisionReentryVerified","localRealmVerified","localAccountVerified","playerbotsSchemaVerified","cleanEngineStopped"})flags.put(name,true);
        return flags;
    }
    private static String file(Path path,String text) throws Exception {
        RuntimeFiles.directory(path.getParent());Files.writeString(path,text);return RuntimeFiles.hashFile(path,Files.size(path),()->false);
    }
    private static FreshServerInstallations.PromotionProof fixtureProof(FreshServerInstallations.Attempt attempt) throws Exception {
        return fixtureProof(attempt,"8.0.46");
    }
    private static FreshServerInstallations.PromotionProof fixtureProof(FreshServerInstallations.Attempt attempt,String version) throws Exception {
        try(FreshServerInstallations.Workspace workspace=attempt.retainWorkspace()) {
            Path work=workspace.directory();
            String bootstrap=file(work.resolve("state/database-bootstrap.json"),"TEST_ONLY_BOOTSTRAP_NO_MYSQL\n");
            String stopped=file(work.resolve("mysql-sessions/"+"f".repeat(32)+"/stopped.json"),"TEST_ONLY_STOP_NO_PROCESS\n");
            String setup=file(work.resolve("state/server-setup-complete.json"),"TEST_ONLY_COMPLETE_NO_RUNTIME_QUALIFICATION\n");
            file(work.resolve("state/database/characters.ibd"),"TEST_ONLY_CHARACTER_SENTINEL_RETAINED\n");
            return new FreshServerInstallations.PromotionProof(attempt.selection,"01234567-89ab-4cde-8fab-0123456789ab",version,"f".repeat(32),bootstrap,stopped,setup,flags());
        }
    }
    private static void successfulPromotionAndUpdatePreservation(Path root) throws Exception {
        FreshServerInstallations store=new FreshServerInstallations(root);FreshServerInstallations.Active active;
        try(FreshServerInstallations.Attempt attempt=store.begin(selection("a"),1)) {
            active=attempt.promote(fixtureProof(attempt));
            check(active.work.equals(root.resolve("db/"+attempt.slotId)),"Promotion must retain the original physical work path");
        }
        check(active.directoryFor(root).equals(active.work),"Typed active workspace retains its application root");
        Path complete=active.work.resolve("state/server-setup-complete.json");
        byte[] completeBytes=Files.readAllBytes(complete);
        String completeHash=RuntimeFiles.hashFile(complete,completeBytes.length,RuntimeWork.NEVER_CANCELLED);
        check(active.setupReceiptSha256.equals(completeHash),"Exposed setup identity comes from the validated promotion proof");
        FreshServerInstallations.Active restored=new FreshServerInstallations(root).active(selection("a"));
        check(restored.setupReceiptSha256.equals(completeHash),"Reopened active selection exposes the same proof-bound setup receipt");
        Files.writeString(complete,"TEST_ONLY_UNTRUSTED_REPLACEMENT_RECEIPT\n");
        check(active.setupReceiptSha256.equals(completeHash),"Existing typed identity never rehashes an untrusted current marker");
        rejects(()->new FreshServerInstallations(root).active(selection("a")));
        Files.write(complete,completeBytes);
        rejects(()->active.directoryFor(root.getParent()));
        Path sentinel=active.work.resolve("state/database/characters.ibd");byte[] saved=Files.readAllBytes(sentinel);
        Path pointer=root.resolve("state/server-installations/active");FileTime retained=FileTime.fromMillis(12345000);Files.setLastModifiedTime(pointer,retained);
        check(new FreshServerInstallations(root).active(selection("a")).work.equals(active.work),"Reopened application resolves the same database");
        check(Files.getLastModifiedTime(pointer).equals(retained),"Resolving active installation must not rewrite it");
        rejects(()->store.begin(selection("a"),1));rejects(()->store.active(selection("1")));
        check(java.util.Arrays.equals(saved,Files.readAllBytes(sentinel)),"Reinitialization/source mismatch preserve characters");
    }
    private static void exactVersionSuffixRoundTrip(Path root) throws Exception {
        int index=0;
        for(String version:new String[]{"8.0.46-0ubuntu0.24.04.4","8.0.46+pkg~build_1"}) {
            Path directory=RuntimeFiles.directory(root.resolve("version"+(index++)));
            FreshServerInstallations store=new FreshServerInstallations(directory);String expected;
            try(FreshServerInstallations.Attempt attempt=store.begin(selection("a"),1)) {
                FreshServerInstallations.Active active=attempt.promote(fixtureProof(attempt,version));
                expected=active.setupReceiptSha256;
                check(Files.readString(directory.resolve("state/server-installations/"+attempt.slotId+".proof"))
                    .contains("mysqlVersion="+version+"\n"),"Exact version suffix is retained rather than stripped");
            }
            check(new FreshServerInstallations(directory).active(selection("a")).setupReceiptSha256.equals(expected),
                "Suffix-bearing storage proof must reconstruct the same bound setup receipt");
        }
    }
    private static void cancellationRetainsFailedSlotAndStartsFresh(Path root) throws Exception {
        FreshServerInstallations store=new FreshServerInstallations(root);Path old;String oldId;
        try(FreshServerInstallations.Attempt attempt=store.begin(selection("a"),1)) {
            oldId=attempt.slotId;
            try(FreshServerInstallations.Workspace workspace=attempt.retainWorkspace()) {
                workspace.requireRuntimeArchive("b".repeat(64));
                rejects(()->workspace.requireRuntimeArchive("1".repeat(64)));
                old=workspace.directory();file(old.resolve("state/partial.sql"),"TEST_ONLY_PARTIAL_IMPORT_PRESERVED\n");
                rejects(()->attempt.abandon("cancelled"));rejects(attempt::close);
                rejects(()->new FreshServerInstallations(root).begin(selection("a"),1));
            }
            attempt.abandon("cancelled");
        }
        byte[] retained=Files.readAllBytes(old.resolve("state/partial.sql"));
        try(FreshServerInstallations.Attempt retry=store.begin(selection("a"),1)) {
            check(!retry.slotId.equals(oldId),"Cancellation retry allocates a new database rather than replaying SQL");
            check(java.util.Arrays.equals(retained,Files.readAllBytes(old.resolve("state/partial.sql"))),"Failed state and diagnostics are retained");
            retry.abandon("cancelled");
        }
    }
    private static void legacyAndStorageGuards(Path root) throws Exception {
        FreshServerInstallations store=new FreshServerInstallations(root);
        Path legacy=root.resolve("state/server-work/database/character-save");file(legacy,"TEST_ONLY_LEGACY_CHARACTER\n");
        rejects(()->store.begin(selection("a"),1));check(Files.readString(legacy).equals("TEST_ONLY_LEGACY_CHARACTER\n"),"Legacy state must never be adopted or reseeded");
    }
    private static void interruptedBoundaries(Path root) throws Exception {
        for(String phase:new String[]{"allocated","proof-written","ready-written","active-pointer-written"}) {
            Path fixture=RuntimeFiles.directory(root.resolve(phase));
            FreshServerInstallations failing=new FreshServerInstallations(fixture,at->{if(at.equals(phase))throw new IOException("TEST_ONLY_INTERRUPTION");});
            if(phase.equals("allocated")) {
                rejects(()->failing.begin(selection("a"),1));
                String old=Files.readString(fixture.resolve("state/server-installations/staging")).trim();
                try(FreshServerInstallations.Attempt retry=new FreshServerInstallations(fixture).begin(selection("a"),1)) {
                    check(!retry.slotId.equals(old),"Interrupted allocation must not adopt the prior mutable slot");
                    check(Files.isDirectory(fixture.resolve("db/"+old),LinkOption.NOFOLLOW_LINKS),"Interrupted slot remains available for diagnostics");
                }
            } else {
                try(FreshServerInstallations.Attempt attempt=failing.begin(selection("a"),1)) {
                    FreshServerInstallations.PromotionProof proof=fixtureProof(attempt);rejects(()->attempt.promote(proof));
                }
                FreshServerInstallations reopened=new FreshServerInstallations(fixture);
                FreshServerInstallations.Active active=reopened.active(selection("a"));
                if(phase.equals("proof-written"))check(active==null,"An uncommitted proof alone cannot make a database active");
                else check(active!=null && Files.exists(active.work.resolve("state/database/characters.ibd")),"Durable complete promotion recovers after interruption without moving data");
            }
        }
    }
    public static void main(String[] arguments) throws Exception {
        Path root=Files.createTempDirectory("esteria-fresh-store-fixture-").toRealPath();
        try {
            successfulPromotionAndUpdatePreservation(RuntimeFiles.directory(root.resolve("promotion")));
            exactVersionSuffixRoundTrip(RuntimeFiles.directory(root.resolve("version-suffix")));
            cancellationRetainsFailedSlotAndStartsFresh(RuntimeFiles.directory(root.resolve("cancellation")));
            // This test exercises same-process file-lock contention explicitly.
            Path partial=RuntimeFiles.directory(root.resolve("partial"));FreshServerInstallations store=new FreshServerInstallations(partial);
            try(FreshServerInstallations.Attempt attempt=store.begin(selection("a"),1)) {
                FreshServerInstallations.PromotionProof proof=fixtureProof(attempt);
                try(FreshServerInstallations.Workspace workspace=attempt.retainWorkspace()) {
                    file(workspace.directory().resolve("state/server-setup-complete.json"),"TEST_ONLY_CHANGED_RECEIPT\n");
                    rejects(()->attempt.promote(proof));
                }
                rejects(()->attempt.promote(proof));
            }
            Map<String,Boolean> incomplete=flags();incomplete.put("compiledUpdaterComplete",false);
            rejects(()->new FreshServerInstallations.PromotionProof(selection("a"),"01234567-89ab-4cde-8fab-0123456789ab","8.0.46","f".repeat(32),"a".repeat(64),"b".repeat(64),"c".repeat(64),incomplete));
            new FreshServerInstallations.PromotionProof(selection("a"),"01234567-89ab-4cde-8fab-0123456789ab",
                "8.0.46-0ubuntu0.24.04.4","f".repeat(32),"a".repeat(64),"b".repeat(64),"c".repeat(64),flags());
            for(String invalid:new String[]{"8.0.*","8.0.46-MariaDB","9.0.1","8.0.46 latest","8.0.46\n"})
                rejects(()->new FreshServerInstallations.PromotionProof(selection("a"),"01234567-89ab-4cde-8fab-0123456789ab",invalid,
                    "f".repeat(32),"a".repeat(64),"b".repeat(64),"c".repeat(64),flags()));
            legacyAndStorageGuards(RuntimeFiles.directory(root.resolve("legacy")));
            Path noSpace=RuntimeFiles.directory(root.resolve("no-space"));
            FreshServerInstallations insufficient=new FreshServerInstallations(noSpace,phase->{ },directory->0);
            rejects(()->insufficient.begin(selection("a"),1));
            try(var files=Files.list(noSpace.resolve("db"))){check(files.findAny().isEmpty(),"Insufficient storage allocates no database slot");}
            interruptedBoundaries(RuntimeFiles.directory(root.resolve("interruption")));
            System.out.println("Fresh installation promotion/cancellation/receipt binding/legacy preservation and interrupted filesystem recovery passed; synthetic receipts only, no SQL or runtime qualification");
        } finally {
            try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}
        }
    }
}
