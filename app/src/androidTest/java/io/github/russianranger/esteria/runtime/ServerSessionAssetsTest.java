package io.github.russianranger.esteria.runtime;

import android.content.Context;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;
import io.github.russianranger.esteria.BuildConfig;
import io.github.russianranger.esteria.core.runtime.process.ServerDataRunPlan;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.security.MessageDigest;
import java.util.Comparator;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

/** APK/private metadata only. Synthetic files are not usable game data, tools,
 * source qualification or an authorization to execute a server session. */
@RunWith(AndroidJUnit4.class)
public final class ServerSessionAssetsTest {
    @Test public void completeSessionHelperClosureInstallsAndReusesExactBytes()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"session-helper-test-");
        try {
            Path generations=GuestHelperAssets.directory(root,"generations");
            String generation=GuestHelperAssets.install(context,"server-session",generations,LocalServerSession.HELPERS);
            Path installed=generations.resolve(generation),retained=installed.resolve("local-server.json");
            FileTime stamp=FileTime.fromMillis(12345000);Files.setLastModifiedTime(retained,stamp);
            for(String name:LocalServerSession.HELPERS)try(var input=context.getAssets().open("server-session/"+name)) {
                assertArrayEquals(input.readAllBytes(),Files.readAllBytes(installed.resolve(name)));
            }
            assertEquals(generation,GuestHelperAssets.install(context,"server-session",generations,LocalServerSession.HELPERS));
            assertEquals(stamp,Files.getLastModifiedTime(retained));
            try(var files=Files.walk(installed)){assertEquals(24,files.filter(Files::isRegularFile).count());}
        }finally{remove(root);}
    }
    @FunctionalInterface private interface Action {void run()throws Exception;}
    private static void refuses(Action action)throws Exception {try{action.run();fail("Changed/invalid metadata accepted");}catch(IOException expected){ }}
    private static String hash(byte[] bytes)throws Exception {StringBuilder value=new StringBuilder(64);for(byte b:MessageDigest.getInstance("SHA-256").digest(bytes))value.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return value.toString();}
    private static void write(Path path,String value)throws Exception {Files.write(path,value.getBytes(StandardCharsets.UTF_8));}
    private static JSONObject pin(Path path)throws Exception {byte[] bytes=Files.readAllBytes(path);return new JSONObject().put("bytes",bytes.length).put("sha256",hash(bytes));}
    @Test public void privateDataMetadataBindingRejectsChangedAncestryAndQualificationClaims()throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        Path root=Files.createTempDirectory(context.getFilesDir().getCanonicalFile().toPath(),"data-binding-test-");
        String server="f35f04d01689f034778e3474b3c820092f51e461",importId="a".repeat(64);
        try {
            Path game=Files.createDirectory(root.resolve("game")),tools=Files.createDirectory(root.resolve("tools")),work=Files.createDirectory(root.resolve("work"));
            Path imported=Files.createDirectories(game.resolve("generations").resolve(importId));Files.createDirectory(imported.resolve("data"));
            write(game.resolve("current"),importId+"\n");
            write(imported.resolve("complete"),"format=1\nclientBuild=12340\nrequest="+importId+"\nsource="+"b".repeat(64)+"\n");
            write(imported.resolve("journal.tsv"),"TEST_ONLY_METADATA_NO_GAME_ASSETS\n");
            String helpers=ServerDataAssets.install(context,work);
            JSONObject toolSelection=new JSONObject().put("formatVersion",1).put("clientRevision",BuildConfig.CLIENT_REVISION).put("serverRevision",server)
                .put("files",new JSONObject()).put("orderedSourceReceipt",new JSONObject().put("bytes",1).put("sha256","c".repeat(64)));
            String toolJson=ServerDataBinding.canonical(toolSelection)+"\n";write(work.resolve("data-tools-selection.json"),toolJson);
            ServerDataRunPlan plan=new ServerDataRunPlan(game,tools,work,helpers,hash(toolJson.getBytes(StandardCharsets.UTF_8)),"enUS",1);
            JSONObject metadata=new JSONObject().put(importId+"/complete",pin(imported.resolve("complete"))).put(importId+"/journal.tsv",pin(imported.resolve("journal.tsv")));
            JSONObject inputs=new JSONObject().put("formatVersion",1).put("importGeneration",importId).put("clientRevision",BuildConfig.CLIENT_REVISION)
                .put("serverRevision",server).put("locale","enUS").put("threads",1).put("importMetadata",metadata)
                .put("toolSelectionSha256",hash(toolJson.getBytes(StandardCharsets.UTF_8)))
                .put("contentProfile",io.github.russianranger.esteria.core.content.ContentProfile.ID)
                .put("preparationHelperGeneration",helpers);
            String generation=hash((ServerDataBinding.canonical(inputs)+"\n").getBytes(StandardCharsets.UTF_8));
            Path store=Files.createDirectory(work.resolve("server-data")),selected=Files.createDirectories(store.resolve("generations").resolve(generation));
            Files.createDirectory(selected.resolve("data"));write(store.resolve("current"),generation+"\n");
            write(selected.resolve("order.json"),"TEST_ONLY_METADATA_NOT_AN_ORDER_MANIFEST\n");write(selected.resolve("order.tsv"),"TEST_ONLY_METADATA_NOT_A_WIRE_MANIFEST\n");
            JSONObject provider=new JSONObject().put("effectiveLocale","enUS").put("manifest",pin(selected.resolve("order.json"))).put("wire",pin(selected.resolve("order.tsv")));
            JSONObject receipt=new JSONObject().put("formatVersion",1).put("scope","local-server-data-format-checked-not-world-qualified").put("generation",generation)
                .put("inputs",inputs).put("files",new JSONObject().put("TEST_ONLY_NO_USABLE_GAME_DATA",new JSONObject().put("bytes",1).put("sha256","d".repeat(64))))
                .put("providerOrder",provider).put("preflight",new JSONObject().put("checks_passed",true))
                .put("worldQualified",false).put("androidQualified",false).put("gameplayQualified",false);
            Path receiptFile=selected.resolve("receipt.json");write(receiptFile,receipt.toString()+"\n");
            ServerDataBinding binding=ServerDataBinding.inspect(plan,server);assertEquals(generation,binding.generation);binding.requireUnchanged();
            inputs.put("contentProfile","esteria-custom");write(receiptFile,receipt.toString()+"\n");refuses(()->ServerDataBinding.inspect(plan,server));
            inputs.put("contentProfile",io.github.russianranger.esteria.core.content.ContentProfile.ID);
            inputs.put("preparationHelperGeneration","e".repeat(64));write(receiptFile,receipt.toString()+"\n");refuses(()->ServerDataBinding.inspect(plan,server));
            inputs.put("preparationHelperGeneration",helpers);write(receiptFile,receipt.toString()+"\n");
            ServerDataBinding.inspect(plan,server).requireUnchanged();
            // This intentionally tests metadata binding only: the production
            // guest refuses this fixture's nonexistent formats/source provider.
            receipt.put("worldQualified",true);write(receiptFile,receipt.toString()+"\n");refuses(()->ServerDataBinding.inspect(plan,server));
            receipt.put("worldQualified",false).getJSONObject("preflight").put("checks_passed",false);write(receiptFile,receipt.toString()+"\n");refuses(()->ServerDataBinding.inspect(plan,server));
            receipt.getJSONObject("preflight").put("checks_passed",true);write(receiptFile,receipt.toString()+"\n");
            ServerDataBinding retained=ServerDataBinding.inspect(plan,server);
            write(imported.resolve("journal.tsv"),"TEST_ONLY_CHANGED_METADATA\n");refuses(retained::requireUnchanged);
            assertFalse(Files.exists(work.resolve("state/server-setup-complete.json")));
            assertFalse(Files.exists(work.resolve("server-sessions")));
        }finally{remove(root);}
    }
    private static void remove(Path root)throws Exception {try(var paths=Files.walk(root)){for(Path path:paths.sorted(Comparator.reverseOrder()).toArray(Path[]::new))Files.delete(path);}}
}
